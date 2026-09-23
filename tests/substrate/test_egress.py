"""N3b relay rules; portable: only platform primitives and the peers' address seam.

``_bind_private_socket`` becomes a loopback TCP listener plus a stand-in file
whose inode is the recorded identity, held until the listener closes as a bound
socket holds its own, and ``_receive`` becomes a plain
``sock_recv``. ``_routable`` additionally admits the controlled peers' loopback
address, and nothing else; the policy tests use the real predicate. Everything
else is the production relay, driven against a real
recording peer in its own thread. The accepting path comes first. Assertions
run after the relay has exited, so an exit failure can never mask them. The
``LINUX`` section at the end uses the real primitives and skips elsewhere; a
skip is not evidence.
"""

from __future__ import annotations

import array
import asyncio
import errno
import inspect
import os
import socket
import ssl
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import egress
from constructicon.substrate.executors.egress import (
    ALLOCATION_FAILED,
    CONNECT_HEAD_BYTES,
    RELAY_FAILED,
    SOCKET_CHANGED,
    EgressDestination,
    EgressPolicy,
    EgressRefused,
    EgressRelay,
    EgressSocket,
    client_hello_sni,
    identity_digests,
    parse_connect,
)

ALLOWED = "allowed.invalid"
DECOY = "decoy.invalid"
ESTABLISHED = b"HTTP/1.1 200 Connection established\r\n\r\n"
LINUX = pytest.mark.skipif(sys.platform != "linux", reason="the real primitives need Linux")
CONTROLLED = "127.0.0.1"
"""The controlled peers' address: never admissible outside the test seam."""
UNDIALLED = "1.1.1.1"
"""A routable address for policies that no test ever dials."""


class LocalClose(asyncio.CancelledError):
    """Shaped like the handle's close latch: a CancelledError subclass."""


# --- substituted primitives, peer and client ---------------------------------


def controlled(routable):
    """The routability predicate widened by exactly the controlled peers' address.

    Production destinations must be globally routable. The peers here live on
    host loopback, so the suites replace the predicate, as they replace the
    platform primitives; the zone refusal sits outside it and stays real.
    """
    return lambda address: str(address) == CONTROLLED or routable(address)


@pytest.fixture
def controlled_loopback(monkeypatch):
    monkeypatch.setattr(egress, "_routable", controlled(egress._routable))


class PinningListener(socket.socket):
    """A loopback listener that holds its stand-in inode until it closes.

    A bound ``AF_UNIX`` socket holds its own inode until its last descriptor
    closes, so no other file can take that inode number meanwhile; once it is
    released, Linux CI measured the next file receiving it. The stand-in
    is held by a hard link outside the relay's directory, removed on close.
    ``path_at_close`` records whether the relay's path still existed then.
    """

    pin: Path | None = None
    path: Path | None = None
    path_at_close: bool | None = None

    def close(self) -> None:
        if self.pin is not None and self.path_at_close is None:
            self.path_at_close = os.path.lexists(self.path)
            self.pin.unlink()
        super().close()


@pytest.fixture
def listeners(monkeypatch, tmp_path_factory, controlled_loopback):
    bound: list[PinningListener] = []
    pins = tmp_path_factory.mktemp("pins")

    def bind(path):
        path.write_bytes(b"")  # the inode whose identity the relay records
        listener = PinningListener(socket.AF_INET, socket.SOCK_STREAM)
        listener.path, listener.pin = path, pins / str(len(bound))
        os.link(path, listener.pin)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        bound.append(listener)
        info = os.lstat(path)
        return listener, (info.st_dev, info.st_ino)

    async def receive(sock, count):
        return await asyncio.get_running_loop().sock_recv(sock, count)

    monkeypatch.setattr(egress, "_bind_private_socket", bind)
    monkeypatch.setattr(egress, "_receive", receive)
    return bound


class Connection:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.data = bytearray()
        self.eof = False
        self.eof_at: float | None = None

    def run(self) -> None:
        with suppress(OSError):
            while chunk := self.sock.recv(65536):
                self.data.extend(chunk)
        self.eof_at = time.monotonic()
        self.eof = True


class Peer:
    """A recording TCP peer on loopback, in its own thread, never the relay's loop."""

    def __init__(self) -> None:
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.connections: list[Connection] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                sock, _ = self.server.accept()
            except OSError:
                return
            connection = Connection(sock)
            self.connections.append(connection)
            threading.Thread(target=connection.run, daemon=True).start()

    def received(self) -> bytes:
        return b"".join(bytes(item.data) for item in self.connections)

    def close(self) -> None:
        for sock in (self.server, *(item.sock for item in self.connections)):
            with suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()


@pytest.fixture
def peer():
    instance = Peer()
    yield instance
    instance.close()


async def until(predicate, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= end:
            return False
        await asyncio.sleep(0.01)
    return True


def real_hello(server_hostname: str | None = ALLOWED) -> bytes:
    """A genuine ClientHello record from the stdlib TLS client, never sent anywhere."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if server_hostname is None:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    tls = context.wrap_bio(ssl.MemoryBIO(), outgoing := ssl.MemoryBIO(),
                           server_hostname=server_hostname)
    with suppress(ssl.SSLWantReadError):
        tls.do_handshake()
    return outgoing.read()


def hello_parts(record: bytes):
    hello = record[5 + 4:]
    offset = 2 + 32
    offset += 1 + hello[offset]
    offset += 2 + int.from_bytes(hello[offset:offset + 2], "big")
    offset += 1 + hello[offset]
    size = int.from_bytes(hello[offset:offset + 2], "big")
    extensions, cursor = [], offset + 2
    while cursor < offset + 2 + size:
        kind = int.from_bytes(hello[cursor:cursor + 2], "big")
        length = int.from_bytes(hello[cursor + 2:cursor + 4], "big")
        extensions.append((kind, hello[cursor + 4:cursor + 4 + length]))
        cursor += 4 + length
    return record[1:3], hello[:offset], extensions


def rebuild(record, *, extensions=None, version=None, handshake=1, claimed_extra=0,
            content_type=22):
    original_version, head, original = hello_parts(record)
    encoded = b"".join(
        kind.to_bytes(2, "big") + len(data).to_bytes(2, "big") + data
        for kind, data in (original if extensions is None else extensions(original))
    )
    hello = head + len(encoded).to_bytes(2, "big") + encoded
    body = bytes([handshake]) + (len(hello) + claimed_extra).to_bytes(3, "big") + hello
    return (bytes([content_type]) + (version or original_version)
            + len(body).to_bytes(2, "big") + body)


def two_names(extensions):
    entries = b"".join(
        b"\x00" + len(name).to_bytes(2, "big") + name for name in (b"allowed.invalid", b"x.invalid")
    )
    data = len(entries).to_bytes(2, "big") + entries
    return [(kind, data if kind == 0 else value) for kind, value in extensions]


def fragmented(record):
    """The same handshake split across two records; each record alone is partial."""
    body = record[5:]
    first, second = body[:40], body[40:]
    return (record[:3] + len(first).to_bytes(2, "big") + first
            + record[:3] + len(second).to_bytes(2, "big") + second)


ECH = (0xFE0D, b"\x00\x01\x02\x03")
HELLOS = {
    # case: (record factory, reason)
    "no-sni": (lambda: real_hello(None), "sni"),
    "ech": (lambda: rebuild(real_hello(), extensions=lambda ext: [ECH, *ext]), "ech"),
    "ech-after-sni": (lambda: rebuild(real_hello(), extensions=lambda ext: [*ext, ECH]), "ech"),
    "not-client-hello": (lambda: rebuild(real_hello(), handshake=2), "tls"),
    "fragmented": (lambda: rebuild(real_hello(), claimed_extra=1), "tls"),
    "non-handshake": (lambda: rebuild(real_hello(), content_type=23), "tls"),
    "plaintext": (lambda: b"GET / HTTP/1.1\r\nHost: allowed.invalid\r\n\r\n", "tls"),
    "oversized": (lambda: b"\x16\x03\x01" + (16385).to_bytes(2, "big") + b"\x01" * 64, "tls"),
    "version-low": (lambda: rebuild(real_hello(), version=b"\x03\x00"), "tls"),
    "version-high": (lambda: rebuild(real_hello(), version=b"\x03\x04"), "tls"),
    "duplicate-extension": (
        lambda: rebuild(real_hello(), extensions=lambda ext: [*ext, (0x1234, b""), (0x1234, b"")]),
        "tls",
    ),
    "two-host-names": (lambda: rebuild(real_hello(), extensions=two_names), "sni"),
}


def head(host=ALLOWED, port=443, *, pad=0) -> bytes:
    padding = f"X-Pad: {'a' * pad}\r\n" if pad else ""
    return f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n{padding}\r\n".encode()


def policy_for(port: int, *, connections=4) -> EgressPolicy:
    return EgressPolicy(
        destinations=(EgressDestination(ALLOWED, port, CONTROLLED),),
        connections=connections,
    )


def relay_for(tmp_path, port, *, seconds=10.0, control=lambda: None, connections=4):
    deadline = asyncio.get_running_loop().time() + seconds
    return EgressRelay(
        policy_for(port, connections=connections), tmp_path / "payloads" / "acq-test",
        deadline, control,
    )


async def client(listeners):
    return await asyncio.open_connection(*listeners[-1].getsockname()[:2])


async def reply_of(reader, count=None, timeout=2.0) -> bytes | None:
    """The relay's reply bytes, ``b""`` once it closed, or None if nothing came."""
    count = len(ESTABLISHED) if count is None else count
    try:
        return await asyncio.wait_for(reader.readexactly(count), timeout)
    except asyncio.IncompleteReadError as exc:
        return exc.partial
    except ConnectionError:
        return b""
    except TimeoutError:
        return None


async def drive(relay, scenario):
    facts: dict = {}
    failure = None
    try:
        async with relay as bound:
            facts["socket"] = bound
            await scenario(facts)
    except ContractViolation as exc:
        failure = exc
    return facts, failure


def refuse_resolution(monkeypatch) -> list:
    """A resolver that records and refuses, proven live by one control call."""
    calls: list = []

    def refuse(*args, **kwargs):
        calls.append(args[:2])
        raise socket.gaierror(socket.EAI_NONAME, "the relay resolved a name")

    async def refuse_async(*args, **kwargs):
        return refuse(*args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", refuse_async)
    with suppress(socket.gaierror):
        socket.getaddrinfo("control.invalid", 443)
    assert calls == [("control.invalid", 443)], "the resolver recorder is not live"
    return calls


# --- accepting paths first ----------------------------------------------------


async def test_a_pipelined_connect_and_hello_is_forwarded_byte_identical(
    tmp_path, listeners, peer, monkeypatch,
):
    resolved = refuse_resolution(monkeypatch)
    hello = real_hello()
    relay = relay_for(tmp_path, peer.port)

    async def scenario(facts):
        reader, writer = await client(listeners)
        writer.write(head(port=peer.port) + hello)
        await writer.drain()
        facts["reply"] = await reply_of(reader)
        facts["forwarded"] = await until(lambda: len(peer.received()) >= len(hello))
        facts["observed"] = dict(relay.observed)
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None and relay.closed
    assert facts["reply"] == ESTABLISHED
    assert facts["forwarded"] and peer.received() == hello
    assert len(peer.connections) == 1
    assert facts["observed"] == {"accepted": 1}
    assert resolved == [("control.invalid", 443)], "the relay resolved a name"
    assert not facts["socket"].path.exists() and not facts["socket"].path.parent.exists()


def test_the_parser_returns_the_exact_host_of_a_real_hello():
    assert client_hello_sni(real_hello()) == ALLOWED
    assert client_hello_sni(real_hello(DECOY)) == DECOY
    assert parse_connect(head(port=8443)) == (ALLOWED, 8443)


async def test_the_first_hello_rule_binds_only_the_first_hello(tmp_path, listeners, peer):
    """The recorded limit: a pipelined second hello is not judged, and reaches
    only the same pinned peer. The SNI rule is not the boundary."""
    first, second = real_hello(), real_hello(DECOY)
    relay = relay_for(tmp_path, peer.port)

    async def scenario(facts):
        reader, writer = await client(listeners)
        writer.write(head(port=peer.port) + first + second)
        await writer.drain()
        facts["reply"] = await reply_of(reader)
        facts["forwarded"] = await until(
            lambda: len(peer.received()) >= len(first) + len(second),
        )
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None and facts["reply"] == ESTABLISHED
    assert facts["forwarded"] and peer.received() == first + second
    assert len(peer.connections) == 1


async def test_the_connect_head_bound_binds_at_its_limit(tmp_path, listeners, peer):
    hello = real_hello()
    base = len(head(port=peer.port, pad=1)) - 1
    exact = head(port=peer.port, pad=CONNECT_HEAD_BYTES - base)
    over = head(port=peer.port, pad=CONNECT_HEAD_BYTES - base + 1)
    assert (len(exact), len(over)) == (CONNECT_HEAD_BYTES, CONNECT_HEAD_BYTES + 1)
    relay = relay_for(tmp_path, peer.port)

    async def scenario(facts):
        reader, writer = await client(listeners)
        writer.write(exact + hello)
        await writer.drain()
        facts["exact"] = await reply_of(reader)
        facts["forwarded"] = await until(lambda: len(peer.received()) >= len(hello))
        refused_reader, refused_writer = await client(listeners)
        refused_writer.write(over)
        await refused_writer.drain()
        facts["over"] = await reply_of(refused_reader)
        await until(lambda: relay.observed["denied:head"] or relay.observed["denied:eof"])
        facts["observed"] = dict(relay.observed)
        writer.close()
        refused_writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None
    assert facts["exact"] == ESTABLISHED and facts["forwarded"]
    assert facts["over"] == b""
    assert facts["observed"] == {"accepted": 1, "denied:head": 1}
    assert len(peer.connections) == 1


async def test_the_connection_bound_binds_at_its_limit(tmp_path, listeners, peer):
    hello = real_hello()
    relay = relay_for(tmp_path, peer.port, connections=2)

    async def scenario(facts):
        writers = []
        for _ in range(2):
            reader, writer = await client(listeners)
            writer.write(head(port=peer.port) + hello)
            await writer.drain()
            facts.setdefault("replies", []).append(await reply_of(reader))
            writers.append(writer)
        await until(lambda: len(peer.connections) == 2)
        reader, writer = await client(listeners)
        writer.write(head(port=peer.port) + hello)
        facts["third"] = await reply_of(reader)
        writers.append(writer)
        facts["observed"] = dict(relay.observed)
        for item in writers:
            item.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None
    assert facts["replies"] == [ESTABLISHED, ESTABLISHED]
    assert facts["third"] == b""
    assert facts["observed"] == {"accepted": 2, "denied:connection_bound": 1}
    assert len(peer.connections) == 2


def hello_of_body(size: int) -> bytes:
    """A real hello grown to exactly ``size`` record-body bytes by one opaque extension."""
    base = real_hello()

    def grown(pad):
        return rebuild(base, extensions=lambda ext: [*ext, (0x1234, b"\x00" * pad)])

    record = grown(size - (len(grown(0)) - 5))
    assert len(record) - 5 == size
    return record


async def test_the_hello_record_bound_binds_at_its_limit(tmp_path, listeners, peer):
    exact, over = hello_of_body(16384), hello_of_body(16385)
    try:
        assert client_hello_sni(exact) == ALLOWED
    except EgressRefused as exc:
        pytest.fail(f"a hello record at the bound was refused: {exc.reason}")
    with pytest.raises(EgressRefused) as refused:
        client_hello_sni(over)
    assert refused.value.reason == "tls"
    relay = relay_for(tmp_path, peer.port)

    async def scenario(facts):
        _, writer, facts["established"] = await established(listeners, peer, exact)
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None and facts["established"]
    assert peer.received() == exact


# --- refusals ------------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(HELLOS))
def test_client_hello_refusals(case):
    factory, reason = HELLOS[case]
    with pytest.raises(EgressRefused) as refused:
        client_hello_sni(factory())
    assert refused.value.reason == reason


@pytest.mark.parametrize("case", ["other-sni", "two-record-hello", *sorted(HELLOS)])
async def test_a_refused_hello_reaches_no_peer(tmp_path, listeners, peer, monkeypatch, case):
    resolved = refuse_resolution(monkeypatch)
    if case == "other-sni":
        record, reason = real_hello(DECOY), "sni"
    elif case == "two-record-hello":
        record, reason = fragmented(real_hello()), "tls"
    else:
        factory, reason = HELLOS[case]
        record = factory()
    relay = relay_for(tmp_path, peer.port)

    async def scenario(facts):
        reader, writer = await client(listeners)
        writer.write(head(port=peer.port) + record)
        await writer.drain()
        facts["reply"] = await reply_of(reader)
        facts["closed"] = await reply_of(reader, 1)
        await until(lambda: bool(relay.observed))
        facts["observed"] = dict(relay.observed)
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None and relay.closed
    assert facts["reply"] == ESTABLISHED and facts["closed"] == b""
    assert facts["observed"] == {f"denied:{reason}": 1}
    assert peer.connections == [], "a refused hello reached the peer"
    assert resolved == [("control.invalid", 443)]


CONNECTS = {
    "non-member": (lambda port: head(DECOY, port), "destination"),
    "wrong-port": (lambda port: head(ALLOWED, port + 1 if port < 65535 else 1), "destination"),
    "ip-literal": (lambda port: head("127.0.0.1", port), "ip_literal"),
    "bracketed": (lambda port: head("[::1]", port), "ip_literal"),
    "absolute-form": (
        lambda port: f"GET http://{ALLOWED}:{port}/ HTTP/1.1\r\n\r\n".encode(), "connect",
    ),
    "userinfo": (lambda port: head(f"user@{ALLOWED}", port), "connect"),
    "numeric-host": (lambda port: head("0x7f.1", port), "connect"),
}


def test_the_connect_parser_returns_the_exact_target():
    assert parse_connect(head(ALLOWED, 443)) == (ALLOWED, 443)
    assert parse_connect(head(ALLOWED, 65535)) == (ALLOWED, 65535)
    assert parse_connect(b"CONNECT a.invalid:1 HTTP/1.1\r\n\r\n") == ("a.invalid", 1)


CONNECT_HEADS = {
    # case: (head, reason); each is refused by parse_connect's own gate.
    "unterminated": (b"CONNECT allowed.invalid:443 HTTP/1.1\r\n", "connect"),
    "non-ascii": ("CONNECT allowed.invalid:443 HTTP/1.1\r\nX: é\r\n\r\n".encode(), "connect"),
    "extra-token": (b"CONNECT allowed.invalid:443 HTTP/1.1 x\r\n\r\n", "connect"),
    "method": (b"POST allowed.invalid:443 HTTP/1.1\r\n\r\n", "connect"),
    "version": (b"CONNECT allowed.invalid:443 HTTP/1.0\r\n\r\n", "connect"),
    "zero-padded-port": (b"CONNECT allowed.invalid:0443 HTTP/1.1\r\n\r\n", "connect"),
    "signed-port": (b"CONNECT allowed.invalid:+443 HTTP/1.1\r\n\r\n", "connect"),
    "port-over-bound": (b"CONNECT allowed.invalid:65536 HTTP/1.1\r\n\r\n", "connect"),
    "no-port": (b"CONNECT allowed.invalid HTTP/1.1\r\n\r\n", "connect"),
    "userinfo": (b"CONNECT user@allowed.invalid:443 HTTP/1.1\r\n\r\n", "connect"),
    "numeric-host": (b"CONNECT 0x7f.1:443 HTTP/1.1\r\n\r\n", "connect"),
    "literal": (b"CONNECT 127.0.0.1:443 HTTP/1.1\r\n\r\n", "ip_literal"),
    "bracketed": (b"CONNECT [::1]:443 HTTP/1.1\r\n\r\n", "ip_literal"),
}


@pytest.mark.parametrize("case", sorted(CONNECT_HEADS))
def test_connect_parser_refusals(case):
    data, reason = CONNECT_HEADS[case]
    with pytest.raises(EgressRefused) as refused:
        parse_connect(data)
    assert refused.value.reason == reason


@pytest.mark.parametrize("case", sorted(CONNECTS))
async def test_a_refused_connect_reaches_no_peer(tmp_path, listeners, peer, monkeypatch, case):
    resolved = refuse_resolution(monkeypatch)
    factory, reason = CONNECTS[case]
    relay = relay_for(tmp_path, peer.port)

    async def scenario(facts):
        reader, writer = await client(listeners)
        writer.write(factory(peer.port) + real_hello())
        await writer.drain()
        facts["reply"] = await reply_of(reader)
        await until(lambda: bool(relay.observed))
        facts["observed"] = dict(relay.observed)
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None
    assert facts["reply"] == b"", "a refused CONNECT received a reply"
    assert facts["observed"] == {f"denied:{reason}": 1}
    assert peer.connections == []
    assert resolved == [("control.invalid", 443)]


# --- lifetime --------------------------------------------------------------------


async def established(listeners, peer, hello=None):
    hello = hello or real_hello()
    reader, writer = await client(listeners)
    writer.write(head(port=peer.port) + hello)
    await writer.drain()
    reply = await reply_of(reader)
    forwarded = await until(lambda: len(peer.received()) >= len(hello))
    return reader, writer, reply == ESTABLISHED and forwarded


async def test_the_deadline_cuts_an_actively_writing_stream(tmp_path, listeners, peer):
    relay = relay_for(tmp_path, peer.port, seconds=0.8)
    deadline = relay._deadline

    async def scenario(facts):
        _, writer, facts["established"] = await established(listeners, peer)
        with suppress(ConnectionError, OSError):
            while not peer.connections[0].eof and time.monotonic() < deadline + 3:
                writer.write(b"x" * 1024)
                await writer.drain()
                await asyncio.sleep(0.02)
        facts["observed"] = dict(relay.observed)
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None and facts["established"]
    ended = peer.connections[0].eof_at
    # asyncio runs timers up to one clock tick early (15.6 ms on Windows).
    tick = time.get_clock_info("monotonic").resolution
    assert ended is not None and deadline - tick <= ended <= deadline + 1.0, (ended, deadline)
    assert facts["observed"] == {"accepted": 1, "denied:deadline": 1}


async def test_the_deadline_cuts_an_idle_handler(tmp_path, listeners, peer):
    relay = relay_for(tmp_path, peer.port, seconds=0.4)
    deadline = relay._deadline

    async def scenario(facts):
        reader, writer = await client(listeners)
        writer.write(b"CONNECT allo")
        await writer.drain()
        facts["reply"] = await reply_of(reader, timeout=2.0)
        facts["at"] = time.monotonic()
        facts["observed"] = dict(relay.observed)
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None
    assert facts["reply"] == b"", "an idle handler outlived the deadline"
    assert facts["at"] <= deadline + 1.0
    assert facts["observed"] == {"denied:deadline": 1}
    assert peer.connections == []


async def test_a_read_resumed_past_the_deadline_forwards_nothing(
    tmp_path, listeners, peer, monkeypatch,
):
    """A read can resume in the same step that passes the deadline, before its
    timer runs; the synchronous check refuses it before the forward."""
    hello = real_hello()
    relay = relay_for(tmp_path, peer.port, seconds=1.0)
    deadline = relay._deadline

    async def late(sock, count):
        data = await asyncio.get_running_loop().sock_recv(sock, count)
        if b"after-deadline" in data:
            time.sleep(max(0.0, deadline - time.monotonic()) + 0.05)
        return data

    monkeypatch.setattr(egress, "_receive", late)

    async def scenario(facts):
        _, writer, facts["established"] = await established(listeners, peer, hello)
        writer.write(b"after-deadline")
        await writer.drain()
        facts["cut"] = await until(lambda: peer.connections[0].eof, 3.0)
        facts["observed"] = dict(relay.observed)
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None and facts["established"] and facts["cut"]
    assert peer.received() == hello, "a read resumed past the deadline was forwarded"
    assert facts["observed"] == {"accepted": 1, "denied:deadline": 1}


async def test_a_stream_timeout_before_the_deadline_is_a_reset(
    tmp_path, listeners, peer, monkeypatch,
):
    """ETIMEDOUT is a ``TimeoutError`` too; only the expired acquisition
    deadline is a deadline denial."""
    timed_out = OSError(errno.ETIMEDOUT, os.strerror(errno.ETIMEDOUT))
    assert isinstance(timed_out, TimeoutError)

    async def upstream_times_out(sock, count):
        if sock.getpeername()[1] == peer.port:
            raise timed_out
        return await asyncio.get_running_loop().sock_recv(sock, count)

    monkeypatch.setattr(egress, "_receive", upstream_times_out)
    relay = relay_for(tmp_path, peer.port, seconds=3600.0)

    async def scenario(facts):
        _, writer, facts["established"] = await established(listeners, peer)
        await until(lambda: relay.observed.total() > 1)
        facts["observed"] = dict(relay.observed)
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None and facts["established"]
    assert facts["observed"] == {"accepted": 1, "reset": 1}


async def test_a_cancelled_owner_still_reaping_admits_nothing(tmp_path, listeners, peer):
    """The owner's pending cancellation refuses before exit latches the stop,
    while the owner is still reaping its native tree."""
    relay = relay_for(tmp_path, peer.port)
    reaping, reaped = asyncio.Event(), asyncio.Event()
    facts: dict = {}

    async def owner():
        async with relay:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                reaping.set()
                await reaped.wait()
                raise

    task = asyncio.create_task(owner())
    try:
        assert await until(lambda: bool(listeners))
        task.cancel()
        await asyncio.wait_for(reaping.wait(), 5)
        reader, writer = await client(listeners)
        writer.write(head(port=peer.port) + real_hello())
        await writer.drain()
        facts["reply"] = await reply_of(reader)
        await until(lambda: bool(relay.observed))
        facts["observed"] = dict(relay.observed)
        writer.close()
    finally:
        reaped.set()
        await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled() and relay.closed
    assert facts["reply"] == b"", "a cancelled owner's relay answered a CONNECT"
    assert facts["observed"] == {"denied:stopped": 1}
    assert peer.connections == []


async def test_teardown_delivers_peer_eof_once_exit_returns(tmp_path, listeners, peer):
    relay = relay_for(tmp_path, peer.port)
    kept = []

    async def scenario(facts):
        _, writer, facts["established"] = await established(listeners, peer)
        kept.append(writer)  # the client stays open: only teardown may end it

    facts, failure = await drive(relay, scenario)
    try:
        # Checked before any await: exit returned only after joining every handler.
        assert relay._handlers and all(task.done() for task in relay._handlers)
        assert failure is None and relay.closed and facts["established"]
        assert await until(lambda: peer.connections[0].eof, 2.0), "a stream outlived the relay"
    finally:
        kept[0].close()


async def test_teardown_closes_a_client_whose_handler_never_ran(tmp_path, listeners, peer):
    """A handler cancelled before its first step never reaches its own finally."""
    relay = relay_for(tmp_path, peer.port)
    accepted = asyncio.get_running_loop().create_future()

    class Clients(list):
        def append(self, item):
            super().append(item)
            # Queues the owner's wake-up before the handler's first step, which
            # the accept loop schedules next in the same step. Polling for the
            # handler instead raced it: Linux CI saw it already started.
            accepted.set_result(None)

    relay._clients = Clients()

    async def scenario(facts):
        # A blocking loopback connect completes in the kernel, so the accept
        # happens while this step is already awaiting it.
        facts["sock"] = socket.create_connection(listeners[-1].getsockname()[:2], timeout=2.0)
        await accepted
        facts["state"] = inspect.getcoroutinestate(relay._handlers[0].get_coro())

    facts, failure = await drive(relay, scenario)
    try:
        assert failure is None and relay.closed
        assert facts["state"] == inspect.CORO_CREATED, "the handler had already started"
        assert relay._handlers[0].cancelled()
        reader, writer = await asyncio.open_connection(sock=facts["sock"])
        assert await reply_of(reader, 1) == b"", "an accepted client outlived exit"
        writer.close()
        assert relay.observed == {}
    finally:
        facts["sock"].close()


class HeldPeer:
    """A peer that accepts one connection and reads nothing until drained."""

    def __init__(self) -> None:
        self.server = socket.create_server(("127.0.0.1", 0))
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        self.port = self.server.getsockname()[1]
        self.sock: socket.socket | None = None
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        with suppress(OSError):
            self.sock, _ = self.server.accept()

    def drain(self) -> tuple[int, int]:
        """Bytes already held by this peer's kernel, then every byte it can read."""
        assert self.sock is not None
        self.sock.settimeout(1.0)
        try:
            held = len(self.sock.recv(1 << 22, socket.MSG_PEEK))
        except OSError:
            held = 0
        total = 0
        with suppress(OSError):
            while chunk := self.sock.recv(65536):
                total += len(chunk)
        return held, total

    def close(self) -> None:
        for sock in (self.server, self.sock):
            if sock is not None:
                sock.close()


async def test_nothing_queued_before_the_deadline_reaches_the_peer_after_exit(
    tmp_path, listeners,
):
    """A handler that ends by the deadline discards the upstream's send queue."""
    held_peer = HeldPeer()
    relay = relay_for(tmp_path, held_peer.port, seconds=1.0)
    deadline = relay._deadline

    async def scenario(facts):
        loop = asyncio.get_running_loop()
        reader, writer = await client(listeners)
        writer.write(head(port=held_peer.port) + real_hello())
        await writer.drain()
        facts["reply"] = await reply_of(reader)
        written = 0
        with suppress(OSError):
            while loop.time() < deadline + 0.3:
                writer.write(b"x" * 65536)
                with suppress(TimeoutError):
                    await asyncio.wait_for(writer.drain(), 0.1)
                    written += 65536
        facts["written"] = written
        facts["observed"] = dict(relay.observed)
        writer.close()

    try:
        facts, failure = await drive(relay, scenario)
        assert failure is None and relay.closed and facts["reply"] == ESTABLISHED
        assert facts["written"] >= 1 << 17, "the client never outran the peer"
        assert facts["observed"] == {"accepted": 1, "denied:deadline": 1}
        held, total = await asyncio.to_thread(held_peer.drain)
        assert total <= held, f"{total - held} queued bytes reached the peer after exit"
    finally:
        held_peer.close()


async def test_an_accept_after_stop_is_closed_unread(tmp_path, listeners, peer):
    def control():
        raise RuntimeError("ownership lost")

    relay = relay_for(tmp_path, peer.port, control=control)

    async def scenario(facts):
        reader, writer = await client(listeners)
        writer.write(head(port=peer.port) + real_hello())
        await writer.drain()
        await reply_of(reader)
        await until(lambda: relay.observed["denied:control"] == 1)
        idle_reader, idle_writer = await client(listeners)
        facts["idle"] = await reply_of(idle_reader, timeout=1.0)
        facts["observed"] = dict(relay.observed)
        writer.close()
        idle_writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None
    assert facts["idle"] == b"", "a stopped relay held a new connection open"
    assert facts["observed"] == {"denied:control": 1, "denied:stopped": 1}
    assert peer.connections == []


async def test_a_control_raise_before_the_dial_is_a_denial_and_stops_the_relay(
    tmp_path, listeners, peer,
):
    def control():
        raise LocalClose("the acquisition closed during physical work")

    relay = relay_for(tmp_path, peer.port, control=control)

    async def scenario(facts):
        reader, writer = await client(listeners)
        writer.write(head(port=peer.port) + real_hello())
        await writer.drain()
        facts["reply"] = await reply_of(reader)
        facts["closed"] = await reply_of(reader, 1)
        await until(lambda: bool(relay.observed))
        facts["observed"] = dict(relay.observed)
        writer.close()

    facts, failure = await drive(relay, scenario)
    # A CancelledError subclass from control is a counted denial, not the
    # handler's own cancellation and not a relay failure.
    assert failure is None and relay.closed
    assert facts["reply"] == ESTABLISHED and facts["closed"] == b""
    assert facts["observed"] == {"denied:control": 1}
    assert relay._stopping
    assert peer.connections == [], "the relay dialled after a control refusal"


async def test_control_lost_during_the_dial_closes_the_upstream_before_any_byte(
    tmp_path, listeners, peer,
):
    calls = []

    def control():
        calls.append(len(calls))
        if len(calls) > 1:  # the first check passed; ownership went while dialling
            raise RuntimeError("ownership lost")

    relay = relay_for(tmp_path, peer.port, control=control)

    async def scenario(facts):
        reader, writer = await client(listeners)
        writer.write(head(port=peer.port) + real_hello())
        await writer.drain()
        await reply_of(reader)
        facts["closed"] = await reply_of(reader, 1)
        await until(lambda: len(peer.connections) == 1 and peer.connections[0].eof)
        facts["observed"] = dict(relay.observed)
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None and calls == [0, 1]
    assert facts["closed"] == b""
    assert facts["observed"] == {"denied:control": 1}
    assert len(peer.connections) == 1 and peer.connections[0].eof
    assert bytes(peer.connections[0].data) == b"", "a byte reached the peer after control loss"


async def test_control_lost_on_an_established_stream_forwards_nothing_more(
    tmp_path, listeners, peer,
):
    """Control is rechecked after every resumed read, before its send, and latches stop."""
    lost = []

    def control():
        if lost:
            raise RuntimeError("ownership lost")

    hello = real_hello()
    relay = relay_for(tmp_path, peer.port, control=control)

    async def scenario(facts):
        reader, writer, facts["established"] = await established(listeners, peer, hello)
        writer.write(b"before-loss")
        await writer.drain()
        facts["forwarded"] = await until(lambda: peer.received().endswith(b"before-loss"))
        lost.append(True)
        writer.write(b"after-loss")
        await writer.drain()
        facts["cut"] = await until(lambda: peer.connections[0].eof, 2.0)
        facts["client"] = await reply_of(reader, 1)
        # The pump's control denial latched stop: a new connect is refused unread.
        second_reader, second = await client(listeners)
        second.write(head(port=peer.port) + hello)
        await second.drain()
        facts["second"] = await reply_of(second_reader)
        await until(lambda: relay.observed["denied:stopped"] == 1)
        facts["observed"] = dict(relay.observed)
        writer.close()
        second.close()

    facts, failure = await drive(relay, scenario)
    assert failure is None and facts["established"]
    assert facts["forwarded"], "the established stream did not forward before the loss"
    assert facts["cut"], "control loss left the established stream open"
    assert facts["client"] == b""
    assert peer.received() == hello + b"before-loss", "bytes read after control loss were sent"
    assert facts["second"] == b""
    assert facts["observed"] == {"accepted": 1, "denied:control": 1, "denied:stopped": 1}
    assert len(peer.connections) == 1


# --- exit, allocation and failure -------------------------------------------------


async def test_an_unclassified_handler_failure_is_fatal_at_exit(
    tmp_path, listeners, peer, monkeypatch,
):
    private = str(tmp_path)

    async def failing(sock, count):
        raise RuntimeError(f"unclassified failure under {private}")

    relay = relay_for(tmp_path, peer.port)

    async def scenario(facts):
        monkeypatch.setattr(egress, "_receive", failing)
        _, writer = await client(listeners)
        await until(lambda: relay._handlers and relay._handlers[0].done())
        writer.close()

    facts, failure = await drive(relay, scenario)
    assert isinstance(failure, ContractViolation), "an unclassified failure was not fatal"
    assert str(failure) == RELAY_FAILED and private not in repr(failure)
    assert isinstance(failure.__cause__, RuntimeError)
    assert not relay.closed
    assert not facts["socket"].path.parent.exists()


async def test_the_relay_never_suppresses_the_body_exception(tmp_path, listeners, peer):
    relay = relay_for(tmp_path, peer.port)
    with pytest.raises(RuntimeError, match="body failure"):
        async with relay:
            raise RuntimeError("body failure")
    assert relay.closed


async def test_an_existing_payload_is_refused_and_left_untouched(tmp_path, listeners, peer):
    relay = relay_for(tmp_path, peer.port)
    payload = tmp_path / "payloads" / "acq-test"
    payload.mkdir(parents=True)
    (payload / "marker").write_text("left by someone else")
    with pytest.raises(ContractViolation) as refused:
        async with relay:
            pass
    assert str(refused.value) == ALLOCATION_FAILED and str(tmp_path) not in str(refused.value)
    assert (payload / "marker").read_text() == "left by someone else"
    assert sorted(item.name for item in payload.iterdir()) == ["marker"]
    assert listeners == []


async def test_a_replaced_socket_is_not_unlinked_and_exit_raises(tmp_path, listeners, peer):
    relay = relay_for(tmp_path, peer.port)

    async def scenario(facts):
        path = facts["socket"].path
        path.unlink()
        path.write_text("a substituted inode")

    facts, failure = await drive(relay, scenario)
    assert isinstance(failure, ContractViolation) and str(failure) == RELAY_FAILED
    assert str(failure.__cause__) == SOCKET_CHANGED
    assert facts["socket"].path.read_text() == "a substituted inode"
    assert not relay.closed


async def test_the_socket_is_released_while_the_listener_still_holds_its_inode(
    tmp_path, listeners, peer,
):
    """``(dev, ino)`` names one file only while something holds that inode.

    Once the listener closes, a replacement created in the gap can receive the
    same number (Linux CI observed it on the runner's filesystem), so the
    identity check and unlink must both run while the listener still holds it.
    """
    relay = relay_for(tmp_path, peer.port)

    async def scenario(facts):
        pass

    facts, failure = await drive(relay, scenario)
    assert failure is None and relay.closed
    assert listeners[-1].path_at_close is False, "the listener closed before the release"
    assert not facts["socket"].path.parent.exists()


async def test_a_bind_failure_removes_its_directory_and_names_no_path(
    tmp_path, monkeypatch, controlled_loopback,
):
    def bind(path):
        raise OSError(22, "AF_UNIX path too long", str(path))

    monkeypatch.setattr(egress, "_bind_private_socket", bind)
    relay = relay_for(tmp_path, 443)
    with pytest.raises(ContractViolation) as refused:
        async with relay:
            pass
    assert str(refused.value) == ALLOCATION_FAILED
    assert str(tmp_path) not in str(refused.value)
    assert not (tmp_path / "payloads" / "acq-test").exists()


# --- the sealed policy ------------------------------------------------------------


def destination(host=ALLOWED, port=443, address=UNDIALLED):
    return EgressDestination(host, port, address)


def test_a_policy_digests_its_destinations_and_pins():
    other = destination(DECOY, 8443, "2606:4700:4700::1111")
    first = EgressPolicy((destination(), other), 2)
    same = EgressPolicy((other, destination()), 2)
    moved = EgressPolicy((destination(address="1.0.0.1"), other), 2)
    digests = identity_digests(first)
    assert set(digests) == {
        "enforcement_build_digest", "destination_policy_digest", "resolver_policy_digest",
        "tls_assumptions_digest", "configuration_digest",
    }
    assert identity_digests(same) == digests
    changed = {key for key, value in identity_digests(moved).items() if value != digests[key]}
    assert changed == {"resolver_policy_digest"}


POLICIES = {
    # case: (factory, the refusal's own reason)
    "numeric-host": (lambda: destination("127.1"), "DNS name"),
    "hex-host": (lambda: destination("0x7f.1"), "DNS name"),
    "decimal-host": (lambda: destination("2130706433"), "DNS name"),
    "upper-case": (lambda: destination("Allowed.invalid"), "DNS name"),
    "trailing-dot": (lambda: destination("allowed.invalid."), "DNS name"),
    "non-canonical-address": (lambda: destination(address="2606:4700:4700:0::1111"), "canonical"),
    "port-zero": (lambda: destination(port=0), "port"),
    "list": (lambda: EgressPolicy([destination()], 1), "tuple"),
    "bool-bound": (lambda: EgressPolicy((destination(),), True), "connection bound"),
    "duplicate": (
        lambda: EgressPolicy((destination(), destination(address="1.0.0.1")), 1), "once",
    ),
}
ADDRESSES = {
    # case: (address, the refusal's own reason); each is refused by the real rule.
    "loopback": ("127.0.0.1", "globally routable"),
    "loopback-v6": ("::1", "globally routable"),
    "mapped-loopback": ("::ffff:127.0.0.1", "globally routable"),
    "unspecified": ("0.0.0.0", "globally routable"),
    "private": ("10.0.0.1", "globally routable"),
    "shared": ("100.64.0.1", "globally routable"),
    "link-local": ("169.254.1.1", "globally routable"),
    "documentation": ("192.0.2.7", "globally routable"),
    "unique-local": ("fc00::1", "globally routable"),
    "site-local": ("fec0::1", "globally routable"),
    "multicast": ("224.0.0.1", "globally routable"),
    "multicast-v6": ("ff0e::1", "globally routable"),
    "reserved-v6": ("4000::1", "globally routable"),
    "scoped-link-local": ("fe80::1%eth0", "without a zone"),
    "zone": ("2606:4700:4700::1111%eth0", "without a zone"),
}


@pytest.mark.parametrize("case", sorted(POLICIES))
def test_a_policy_refuses_ambiguous_or_mutable_input(case):
    factory, reason = POLICIES[case]
    with pytest.raises(ContractViolation, match=reason):
        factory()


def test_a_globally_routable_address_is_admissible():
    for address in (UNDIALLED, "2606:4700:4700::1111"):
        assert destination(address=address).address == address


@pytest.mark.parametrize("case", sorted(ADDRESSES))
def test_a_host_local_or_zoned_address_is_never_admissible(case):
    """No loopback, private, link-local, multicast or reserved pin, and no zone.

    ADR 0020 excludes any localhost service inventory, and a zone id would
    send the dial through ``getaddrinfo``. This runs the real predicate.
    """
    address, reason = ADDRESSES[case]
    with pytest.raises(ContractViolation, match=reason):
        destination(address=address)


def test_the_controlled_seam_admits_the_peers_address_and_nothing_else(controlled_loopback):
    assert destination(address=CONTROLLED).address == CONTROLLED
    for address in ("127.0.0.2", "10.0.0.1", "fe80::1%lo"):
        with pytest.raises(ContractViolation):
            destination(address=address)


# --- the real primitives (Linux only) ----------------------------------------------


@LINUX
def test_the_real_bind_records_the_socket_it_created(tmp_path):
    import stat

    path = tmp_path / "egress.sock"
    listener, identity = egress._bind_private_socket(path)
    try:
        info = os.lstat(path)
        assert stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()
        assert identity == (info.st_dev, info.st_ino)
        EgressSocket(path, identity).require_current()
    finally:
        listener.close()


@LINUX
def test_require_current_refuses_a_replaced_socket(tmp_path):
    """The replacement is bound while the relay's listener still holds its inode.

    That is the only state in which the relay checks: closing the first
    listener before the replacement releases the inode, and Linux CI then
    measured the replacement receiving the same ``(dev, ino)``.
    """
    path = tmp_path / "egress.sock"
    first, identity = egress._bind_private_socket(path)
    try:
        path.unlink()
        second, replaced = egress._bind_private_socket(path)
        try:
            assert replaced != identity
            with pytest.raises(ContractViolation, match="changed"):
                EgressSocket(path, identity).require_current()
        finally:
            second.close()
    finally:
        first.close()


@LINUX
async def test_a_replaced_real_socket_is_not_unlinked_and_exit_raises(
    tmp_path, controlled_loopback,
):
    relay = relay_for(tmp_path, 443)
    replacement: list = []

    async def scenario(facts):
        path = facts["socket"].path
        path.unlink()
        replacement.append(egress._bind_private_socket(path))

    try:
        facts, failure = await drive(relay, scenario)
        assert isinstance(failure, ContractViolation) and str(failure) == RELAY_FAILED
        assert str(failure.__cause__) == SOCKET_CHANGED
        info = os.lstat(facts["socket"].path)
        assert (info.st_dev, info.st_ino) == replacement[0][1], "the replacement was unlinked"
        assert not relay.closed
    finally:
        for sock, _ in replacement:
            sock.close()


@LINUX
async def test_ancillary_descriptors_are_closed_and_refused():
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    read_end, write_end = os.pipe()
    try:
        right.setblocking(False)
        left.sendall(b"plain bytes")
        assert await egress._receive(right, 64) == b"plain bytes"
        left.sendmsg(
            [b"with a descriptor"],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [write_end]))],
        )
        os.close(write_end)
        write_end = -1
        with pytest.raises(EgressRefused) as refused:
            await egress._receive(right, 64)
        assert refused.value.reason == "ancillary"
        # Every write end is now closed, including the received copy.
        os.set_blocking(read_end, False)
        assert os.read(read_end, 1) == b""
    finally:
        for sock in (left, right):
            sock.close()
        for fd in (read_end, write_end):
            if fd >= 0:
                os.close(fd)


def test_identity_digests_refuse_an_unsealed_policy():
    with pytest.raises(ContractViolation):
        identity_digests(Path("not-a-policy"))  # type: ignore[arg-type]
