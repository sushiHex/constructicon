"""The in-zone proxy bridge: a byte shim to the egress leaf, never a boundary.

The forwarder functions run in-process over loopback TCP with only the leaf
dial substituted, the one platform primitive, as the N3b suites substitute the
relay's. The fork, readiness and exec cases need Linux and run in its
unprivileged ``verify`` job; the zone itself is proved in the foundation lane
(``test_native_egress_bridge.py``). Design: ``M8-N4-proxy-bridge.md``.
"""

from __future__ import annotations

import asyncio
import errno
import os
import signal
import socket
import struct
import sys
import threading
from contextlib import suppress

import pytest

from constructicon.substrate.executors import _egress_bridge as bridge
from constructicon.substrate.executors.egress import ZONE_SOCKET
from tests.substrate.test_egress import (
    ALLOWED,
    DECOY,
    ESTABLISHED,
    LINUX,
    real_hello,
    relay_for,
    until,
)
from tests.substrate.test_egress import controlled_loopback as controlled_loopback
from tests.substrate.test_egress import listeners as listeners
from tests.substrate.test_egress import peer as peer

SECONDS = 5.0


class Upstream:
    """A recording stand-in for the relay's leaf: one TCP listener on loopback."""

    def __init__(self) -> None:
        self.server = socket.create_server(("127.0.0.1", 0))
        self.dialled = 0

    def dial(self) -> socket.socket:
        self.dialled += 1
        return socket.create_connection(self.server.getsockname()[:2], timeout=SECONDS)

    def accept(self) -> socket.socket:
        self.server.settimeout(SECONDS)
        sock, _ = self.server.accept()
        sock.settimeout(SECONDS)
        return sock


@pytest.fixture
def upstream(monkeypatch):
    instance = Upstream()
    monkeypatch.setattr(bridge, "_dial_leaf", instance.dial)
    yield instance
    instance.server.close()


def pair() -> tuple[socket.socket, socket.socket]:
    """(client, accepted): the vendor's end and the forwarder's end of one link."""
    with socket.create_server(("127.0.0.1", 0)) as server:
        client = socket.create_connection(server.getsockname()[:2], timeout=SECONDS)
        accepted, _ = server.accept()
    return client, accepted


def start(accepted: socket.socket) -> threading.Thread:
    thread = threading.Thread(target=bridge.forward, args=(accepted,), daemon=True)
    thread.start()
    return thread


def finished(thread: threading.Thread) -> bool:
    thread.join(SECONDS)
    return not thread.is_alive()


def read_to_eof(sock: socket.socket) -> tuple[bytes, bool]:
    """Everything until EOF, and whether EOF (or a reset) actually arrived."""
    data = bytearray()
    sock.settimeout(SECONDS)
    try:
        while chunk := sock.recv(65536):
            data.extend(chunk)
    except TimeoutError:
        return bytes(data), False
    except ConnectionError:
        pass
    return bytes(data), True


def read_exactly(sock: socket.socket, count: int) -> bytes:
    data = bytearray()
    sock.settimeout(SECONDS)
    while len(data) < count and (chunk := sock.recv(min(65536, count - len(data)))):
        data.extend(chunk)
    return bytes(data)


def reset(sock: socket.socket) -> None:
    """Close with zero linger, so the peer sees a reset rather than EOF."""
    linger = struct.pack("HH" if sys.platform == "win32" else "ii", 1, 0)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
    sock.close()


# --- accepting paths first ----------------------------------------------------


def test_bytes_cross_unchanged_in_both_directions(upstream):
    client, accepted = pair()
    thread = start(accepted)
    leaf = upstream.accept()
    # Several chunks, and nothing HTTP-shaped: the forwarder parses nothing.
    outbound = bytes(range(256)) * 1024
    inbound = b"\x16\x03\x01" + os.urandom(200_000)

    def send(sock: socket.socket, data: bytes) -> None:
        sock.sendall(data)
        sock.shutdown(socket.SHUT_WR)

    sender = threading.Thread(target=send, args=(client, outbound), daemon=True)
    sender.start()
    assert read_to_eof(leaf) == (outbound, True)
    assert finished(sender)
    sender = threading.Thread(target=send, args=(leaf, inbound), daemon=True)
    sender.start()
    assert read_to_eof(client) == (inbound, True)
    assert finished(sender)
    assert finished(thread), "the forwarder outlived both EOFs"
    assert upstream.dialled == 1
    for sock in (client, leaf):
        sock.close()


def test_a_client_half_close_still_carries_the_reply(upstream):
    client, accepted = pair()
    thread = start(accepted)
    leaf = upstream.accept()
    client.sendall(b"request")
    client.shutdown(socket.SHUT_WR)
    assert read_to_eof(leaf) == (b"request", True), "client EOF did not reach the leaf"
    try:
        leaf.sendall(b"reply after the client's EOF")
        leaf.shutdown(socket.SHUT_WR)
    except OSError as exc:
        # Linux reports a forwarder that closed both halves here, as ENOTCONN
        # or a reset: the reply had nowhere to go (first Linux mutation run).
        pytest.fail(f"the reply was not delivered after the client's half-close: {exc!r}")
    assert read_to_eof(client) == (b"reply after the client's EOF", True)
    assert finished(thread)
    for sock in (client, leaf):
        sock.close()


def test_an_upstream_half_close_still_carries_the_request(upstream):
    client, accepted = pair()
    thread = start(accepted)
    leaf = upstream.accept()
    leaf.sendall(b"early reply")
    leaf.shutdown(socket.SHUT_WR)
    assert read_to_eof(client) == (b"early reply", True), "leaf EOF did not reach the client"
    client.sendall(b"request after the leaf's EOF")
    client.shutdown(socket.SHUT_WR)
    assert read_to_eof(leaf) == (b"request after the leaf's EOF", True)
    assert finished(thread)
    for sock in (client, leaf):
        sock.close()


def test_the_vendor_environment_adds_exactly_the_proxy():
    inherited = {"HOME": "/tmp/home", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PWD": "/tmp"}
    assert bridge.environment(dict(inherited)) == {
        **inherited, "HTTPS_PROXY": "http://127.0.0.1:18080",
    }
    assert (bridge.PROXY_HOST, bridge.PROXY_PORT) == ("127.0.0.1", 18080)
    assert bridge.LEAF == ZONE_SOCKET


def head(shape: str, host: str, port: int) -> bytes:
    """A CONNECT head as each pinned client family writes it (design, finding c)."""
    extra = {
        # hyper-util's tunnel with Codex's default user agent: lower-case name.
        "reqwest": "user-agent: codex_cli_rs/0.153.4 (Linux 6.8.0; x86_64) unknown "
                   "(constructicon; 0)\r\n",
        "tungstenite": "Proxy-Connection: Keep-Alive\r\n",
    }[shape]
    return f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n{extra}\r\n".encode()


@pytest.mark.parametrize("shape", ["reqwest", "tungstenite"])
async def test_the_real_relay_admits_each_client_head_through_the_forwarder(
    tmp_path, listeners, peer, monkeypatch, shape,
):
    """The relay's parser sees the client's exact bytes through the forwarder:
    it admits the allowed head, replies with exactly the established line and
    nothing more before the hello, forwards the hello, and refuses the decoy."""
    relay = relay_for(tmp_path, peer.port)
    hello = real_hello()

    def tunnel(host: str) -> tuple[bytes, bytes | None]:
        client, accepted = pair()
        thread = start(accepted)
        client.sendall(head(shape, host, peer.port))
        reply = read_exactly(client, len(ESTABLISHED))
        after = None
        if reply == ESTABLISHED:
            client.settimeout(0.3)
            try:
                after = client.recv(64)  # tungstenite would drop any such byte
            except TimeoutError:
                after = b""
            client.sendall(hello)
        client.close()
        assert finished(thread)
        return reply, after

    async with relay:
        address = listeners[-1].getsockname()[:2]
        monkeypatch.setattr(
            bridge, "_dial_leaf", lambda: socket.create_connection(address, timeout=SECONDS),
        )
        allowed = await asyncio.to_thread(tunnel, ALLOWED)
        assert await until(lambda: peer.received() == hello)
        decoy = await asyncio.to_thread(tunnel, DECOY)
    assert allowed == (ESTABLISHED, b"")
    assert decoy == (b"", None)
    assert relay.observed["accepted"] == 1 and relay.observed["denied:destination"] == 1
    assert len(peer.connections) == 1


# --- refusing paths -----------------------------------------------------------


def test_a_failed_leaf_dial_closes_the_client_with_no_byte(monkeypatch):
    def refused():
        raise ConnectionRefusedError(errno.ECONNREFUSED, "the relay stopped")

    monkeypatch.setattr(bridge, "_dial_leaf", refused)
    client, accepted = pair()
    thread = start(accepted)
    client.sendall(b"CONNECT allowed.invalid:443 HTTP/1.1\r\n\r\n")
    data, ended = read_to_eof(client)
    assert finished(thread)
    assert ended, "the client stayed open after the leaf refused"
    assert data == b"", "the forwarder authored a reply"
    client.close()
    # Held until here: garbage collection must not be what closes the client.
    accepted.close()


# Linux only: the wake-up is Linux's shutdown(2), which returns a recv blocked
# in another thread. Windows does not (measured: a blocked recv stays blocked).
@LINUX
def test_an_upstream_reset_ends_an_idle_client(upstream):
    client, accepted = pair()
    thread = start(accepted)
    leaf = upstream.accept()
    reset(leaf)
    assert finished(thread), "the opposite pump was never woken"
    assert read_to_eof(client)[1]
    client.close()


@LINUX
def test_a_client_reset_ends_an_idle_upstream(upstream):
    client, accepted = pair()
    thread = start(accepted)
    leaf = upstream.accept()
    reset(client)
    assert finished(thread), "the opposite pump was never woken"
    assert read_to_eof(leaf)[1]
    leaf.close()


@pytest.mark.parametrize("case", ["absent", "regular-file"])
def test_the_leaf_check_refuses_anything_but_a_socket(tmp_path, monkeypatch, case):
    leaf = tmp_path / "vendor-egress.sock"
    if case == "regular-file":
        leaf.write_bytes(b"")  # what a leaf-less runtime shows at the path
    monkeypatch.setattr(bridge, "LEAF", str(leaf))
    assert bridge.leaf_is_socket() is False


@pytest.mark.parametrize("case", ["absent", "regular-file"])
def test_the_script_refuses_before_binding_without_a_leaf(tmp_path, monkeypatch, capsys, case):
    leaf = tmp_path / "vendor-egress.sock"
    if case == "regular-file":
        leaf.write_bytes(b"")
    monkeypatch.setattr(bridge, "LEAF", str(leaf))
    calls: list = []

    class Listener:
        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(bridge, "_listen", lambda: calls.append("listen") or Listener())
    monkeypatch.setattr(bridge, "start_forwarder", lambda listener: calls.append("fork"))
    monkeypatch.setattr(bridge, "_exec", lambda *args: calls.append("exec"))
    assert bridge.main(["bridge", "/usr/bin/true"]) == bridge.REFUSED
    assert calls == []
    assert capsys.readouterr().err == "constructicon egress bridge refused: leaf\n"


def test_the_script_refuses_a_relative_command(monkeypatch, capsys):
    monkeypatch.setattr(bridge, "leaf_is_socket", lambda: True)
    monkeypatch.setattr(bridge, "_listen", lambda: pytest.fail("bound for a refused command"))
    assert bridge.main(["bridge", "codex"]) == bridge.REFUSED
    assert bridge.main(["bridge"]) == bridge.REFUSED
    assert capsys.readouterr().err.count("refused: command") == 2


# --- Linux: fork, readiness and exec ------------------------------------------


@pytest.fixture
def unix_leaf(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("a pathname socket leaf needs Linux")
    path = tmp_path / "leaf.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen()
    monkeypatch.setattr(bridge, "LEAF", str(path))
    port = socket.create_server(("127.0.0.1", 0))
    monkeypatch.setattr(bridge, "PROXY_PORT", port.getsockname()[1])
    port.close()
    yield server
    server.close()


@LINUX
def test_the_leaf_check_admits_a_socket(unix_leaf):
    assert bridge.leaf_is_socket() is True


def reap(pid: int) -> None:
    with suppress(ProcessLookupError):
        os.kill(pid, 9)
    with suppress(ChildProcessError):
        os.waitpid(pid, 0)


class Execed(Exception):
    pass


@LINUX
def test_the_script_execs_only_after_the_forwarder_is_ready(unix_leaf, monkeypatch):
    listened: list[socket.socket] = []
    real_listen = bridge._listen
    monkeypatch.setattr(bridge, "_listen", lambda: listened.append(real_listen()) or listened[-1])
    started: list[int] = []
    real_start = bridge.start_forwarder
    monkeypatch.setattr(
        bridge, "start_forwarder", lambda listener: started.append(real_start(listener)) or 0,
    )
    seen: dict = {}

    def fake_exec(command, env):
        seen["command"], seen["env"] = command, env
        seen["listener_closed"] = listened[0].fileno() == -1
        seen["signals"] = [signal.getsignal(kind) for kind in (signal.SIGPIPE, signal.SIGXFSZ)]
        # Readiness came first: the forwarder already joins a connection to the leaf.
        with socket.create_connection(("127.0.0.1", bridge.PROXY_PORT), timeout=SECONDS) as sock:
            sock.sendall(b"through")
            unix_leaf.settimeout(SECONDS)
            leaf, _ = unix_leaf.accept()
            with leaf:
                seen["leaf_bytes"] = read_exactly(leaf, len(b"through"))
        raise Execed

    monkeypatch.setattr(bridge, "_exec", fake_exec)
    # This interpreter ignores both, as the bridge's own does; restored below.
    before = {kind: signal.signal(kind, signal.SIG_IGN) for kind in (
        signal.SIGPIPE, signal.SIGXFSZ)}
    try:
        with pytest.raises(Execed):
            bridge.main(["bridge", "/opt/vendor/bin/codex", "app-server"])
        assert seen["signals"] == [signal.SIG_DFL, signal.SIG_DFL], "exec keeps ignored signals"
        assert len(started) == 1, "exec was reached without a started forwarder"
        assert seen["command"] == ["/opt/vendor/bin/codex", "app-server"]
        assert seen["env"] == bridge.environment(dict(os.environ))
        assert seen["env"]["HTTPS_PROXY"] == f"http://127.0.0.1:{bridge.PROXY_PORT}"
        assert seen["listener_closed"], "the vendor would inherit the listener"
        assert seen["leaf_bytes"] == b"through"
        fds = {name: os.readlink(f"/proc/{started[0]}/fd/{name}")
               for name in os.listdir(f"/proc/{started[0]}/fd")}
        assert {fds[str(fd)] for fd in (0, 1, 2)} == {"/dev/null"}, fds
        rest = [target for name, target in fds.items() if name not in {"0", "1", "2"}]
        assert rest and all(target.startswith("socket:") for target in rest), fds
    finally:
        for kind, handler in before.items():
            signal.signal(kind, handler)
        for pid in started:
            reap(pid)


@LINUX
def test_a_forwarder_that_cannot_isolate_is_never_ready(unix_leaf, monkeypatch, capsys):
    def broken(*keep):
        raise OSError(errno.EBADF, "isolation failed")

    monkeypatch.setattr(bridge, "_isolate", broken)
    calls: list = []
    monkeypatch.setattr(bridge, "_exec", lambda *args: calls.append(args))
    assert bridge.main(["bridge", "/usr/bin/true"]) == bridge.REFUSED
    assert calls == [], "the vendor was exec'd without a ready forwarder"
    assert capsys.readouterr().err == "constructicon egress bridge refused: forwarder\n"
    # The refused listener is closed: nothing accepts on the proxy port.
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", bridge.PROXY_PORT), timeout=SECONDS)
