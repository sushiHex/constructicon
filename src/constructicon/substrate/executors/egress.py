"""Acquisition-scoped ``native_vendor_session_only`` egress (ADR 0020/0021, N3b).

One host-side CONNECT relay per native execution. The native zone keeps the
network namespace it already has, which holds only ``lo``, and reaches this
relay through one read-only pathname-socket leaf. The namespace bounds network
sockets; the relay adds the destination, resolver, TLS and lifetime rules:

* a destination is a sealed ``(host, port)`` with one pinned literal address.
  Nothing resolves a name, and the CONNECT host never reaches the dialler;
* the first ClientHello must name exactly the CONNECT host and carry no ECH.
  That rule binds only the first hello and is not a boundary: the pinned
  address is;
* every connection ends by the acquisition deadline, and teardown revokes every
  stream before its owner releases the acquisition's guards.

The relay never terminates, answers or injects TLS and has no HTTP client, so
it cannot follow a redirect. A denial is enforcement working and is counted in
``observed`` only. A relay failure is fatal and is raised with fixed text,
because the original exception names private locators.
"""

from __future__ import annotations

import array
import asyncio
import errno
import inspect
import ipaddress
import math
import os
import re
import socket
import stat
import string
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import Digest, digest
from constructicon.substrate._lifetime import finish_owned

ZONE_SOCKET = "/vendor-egress.sock"
"""The one fixed in-zone destination of the relay's socket leaf."""
SOCKET_NAME = "egress.sock"
MAX_SOCKET_PATH_BYTES = 107
"""Linux ``sun_path`` holds 108 bytes; one is left for the terminating NUL."""
CONNECT_HEAD_BYTES = 8192
HELLO_RECORD_BYTES = 5 + 16384
CHUNK_BYTES = 8192

ALLOCATION_FAILED = "the native egress relay could not allocate its private socket"
RELAY_FAILED = "the native egress relay failed"
SOCKET_CHANGED = "the native egress socket changed or is not an owned socket"

_ESTABLISHED = b"HTTP/1.1 200 Connection established\r\n\r\n"
_SERVER_NAME = 0x0000
_ECH = 0xFE0D
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_PORT = re.compile(r"[1-9][0-9]{0,4}")
_LETTERS = frozenset(string.ascii_lowercase)


class EgressRefused(Exception):
    """A classified denial: enforcement working, never a relay failure."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _is_host(host: object) -> bool:
    """A positive DNS-name grammar whose final label begins with a letter.

    The final-label rule is what refuses every numeric or hexadecimal IPv4
    spelling (``127.1``, ``0x7f.1``, ``2130706433``) that some resolvers
    accept, rather than relying on ``ipaddress`` failing to parse them.
    """

    if type(host) is not str or not 0 < len(host) <= 253:
        return False
    labels = host.split(".")
    return (
        all(_LABEL.fullmatch(label) is not None for label in labels)
        and labels[-1][0] in _LETTERS
    )


def _is_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class EgressDestination:
    """One sealed ``(host, port)`` and the one literal address it is pinned to."""

    host: str
    port: int
    address: str

    def __post_init__(self) -> None:
        if not _is_host(self.host):
            raise ContractViolation("an egress destination requires a lowercase DNS name")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ContractViolation("an egress destination requires a port in 1..65535")
        if type(self.address) is not str or not _is_literal(self.address):
            raise ContractViolation("an egress destination pins one literal address")
        if str(ipaddress.ip_address(self.address)) != self.address:
            raise ContractViolation("an egress destination pins one canonical literal address")


@dataclass(frozen=True)
class EgressPolicy:
    """The sealed destination set; immutable before anything digests it."""

    destinations: tuple[EgressDestination, ...]
    connections: int

    def __post_init__(self) -> None:
        if type(self.destinations) is not tuple or not self.destinations or not all(
            isinstance(item, EgressDestination) for item in self.destinations
        ):
            raise ContractViolation("an egress policy requires a non-empty tuple of destinations")
        if len({(item.host, item.port) for item in self.destinations}) != len(self.destinations):
            raise ContractViolation("an egress policy names each (host, port) once")
        if type(self.connections) is not int or self.connections <= 0:
            raise ContractViolation("an egress policy requires a positive connection bound")

    def destination(self, host: str, port: int) -> EgressDestination | None:
        for item in self.destinations:
            if item.host == host and item.port == port:
                return item
        return None


def identity_digests(policy: EgressPolicy) -> dict[str, Digest]:
    """The five content fields of ``NativeEgressIdentityV1``.

    ``physical_conformance_revision`` is supplied by whoever ran qualification
    and is never minted here.
    """

    if not isinstance(policy, EgressPolicy):
        raise ContractViolation("egress identity requires a sealed policy")
    ordered = sorted(policy.destinations, key=lambda item: (item.host, item.port))
    return {
        "enforcement_build_digest": digest(
            "native-egress-build", 1, inspect.getsource(sys.modules[__name__]),
        ),
        "destination_policy_digest": digest(
            "native-egress-destinations", 1, [[item.host, item.port] for item in ordered],
        ),
        "resolver_policy_digest": digest(
            "native-egress-resolver", 1,
            [[item.host, item.port, item.address] for item in ordered],
        ),
        "tls_assumptions_digest": digest(
            "native-egress-tls", 1,
            [inspect.getsource(rule) for rule in (_record_length, client_hello_sni, _server_name)],
        ),
        "configuration_digest": digest("native-egress-configuration", 1, {
            "connections": policy.connections,
            "zone_socket": ZONE_SOCKET,
            "connect_head_bytes": CONNECT_HEAD_BYTES,
            "hello_record_bytes": HELLO_RECORD_BYTES,
        }),
    }


def parse_connect(head: bytes) -> tuple[str, int]:
    """The exact target of one ``CONNECT host:port HTTP/1.1`` head.

    Header lines are bounded by the caller and ignored. Nothing is resolved.
    """

    try:
        text = head.decode("ascii")
    except UnicodeDecodeError:
        raise EgressRefused("connect") from None
    if not text.endswith("\r\n\r\n"):
        raise EgressRefused("connect")
    parts = text.split("\r\n", 1)[0].split(" ")
    if len(parts) != 3 or parts[0] != "CONNECT" or parts[2] != "HTTP/1.1":
        raise EgressRefused("connect")
    host, separator, port = parts[1].rpartition(":")
    if host.startswith("[") or _is_literal(host):
        raise EgressRefused("ip_literal")
    if (
        not separator or _PORT.fullmatch(port) is None or int(port) > 65535
        or not _is_host(host)
    ):
        raise EgressRefused("connect")
    return host, int(port)


class _Reader:
    """Bounded TLS vector reads; running out of bytes is a refusal."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    @property
    def done(self) -> bool:
        return self._offset == len(self._data)

    def take(self, count: int) -> bytes:
        end = self._offset + count
        if end > len(self._data):
            raise EgressRefused("tls")
        value = self._data[self._offset:end]
        self._offset = end
        return value

    def vector(self, width: int) -> bytes:
        return self.take(int.from_bytes(self.take(width), "big"))

    def end(self) -> None:
        if not self.done:
            raise EgressRefused("tls")


def _record_length(header: bytes) -> int:
    """The body length of one bounded handshake-record header."""

    if len(header) != 5 or header[0] != 22:
        raise EgressRefused("tls")
    version = int.from_bytes(header[1:3], "big")
    if version < 0x0301 or version > 0x0303:
        raise EgressRefused("tls")
    length = int.from_bytes(header[3:5], "big")
    if not 0 < length <= HELLO_RECORD_BYTES - 5:
        raise EgressRefused("tls")
    return length


def _server_name(data: bytes) -> str:
    names = _Reader(data)
    entries = _Reader(names.vector(2))
    names.end()
    if entries.take(1) != b"\x00":
        raise EgressRefused("sni")
    raw = entries.vector(2)
    if not entries.done:
        raise EgressRefused("sni")
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        raise EgressRefused("sni") from None


def client_hello_sni(record: bytes) -> str:
    """The one ``host_name`` of exactly one complete ClientHello record.

    It judges one record only: a later hello on the same connection (a
    HelloRetryRequest, a pipelined hello or a renegotiation) is never seen.
    """

    length = _record_length(record[:5])
    body = record[5:]
    if len(body) != length:
        raise EgressRefused("tls")
    if body[0] != 1:
        raise EgressRefused("tls")
    if int.from_bytes(body[1:4], "big") != len(body) - 4:
        raise EgressRefused("tls")
    hello = _Reader(body[4:])
    hello.take(2 + 32)
    hello.vector(1)
    hello.vector(2)
    hello.vector(1)
    extensions = _Reader(hello.vector(2))
    hello.end()
    seen: set[int] = set()
    name: str | None = None
    while not extensions.done:
        kind = int.from_bytes(extensions.take(2), "big")
        data = extensions.vector(2)
        if kind in seen:
            raise EgressRefused("tls")
        seen.add(kind)
        if kind == _ECH:
            raise EgressRefused("ech")
        if kind == _SERVER_NAME:
            name = _server_name(data)
    if name is None:
        raise EgressRefused("sni")
    return name


@dataclass(frozen=True)
class EgressSocket:
    """The relay's bound socket, identified by the inode recorded at bind."""

    path: Path
    identity: tuple[int, int]

    def require_current(self) -> None:
        """Positively re-identify the socket immediately before it is mounted."""

        if sys.platform != "linux":
            raise ContractViolation(SOCKET_CHANGED)
        try:
            info = os.lstat(self.path)
        except OSError as exc:
            raise ContractViolation(SOCKET_CHANGED) from exc
        if (
            not self.path.is_absolute()
            or os.path.realpath(self.path) != str(self.path)
            or not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != os.getuid()
            or (info.st_dev, info.st_ino) != self.identity
        ):
            raise ContractViolation(SOCKET_CHANGED)


def _bind_private_socket(path: Path) -> tuple[socket.socket, tuple[int, int]]:
    """Platform primitive: one listening pathname socket and its inode."""

    if sys.platform != "linux":
        raise ContractViolation("the native egress socket requires Linux")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
        info = os.lstat(path)
        listener.listen()
        listener.setblocking(False)
    except BaseException:
        listener.close()
        raise
    return listener, (info.st_dev, info.st_ino)


def _wake(ready: asyncio.Future[None]) -> None:
    if not ready.done():
        ready.set_result(None)


async def _receive(sock: socket.socket, count: int) -> bytes:
    """Platform primitive: a read that never accepts a passed descriptor.

    SCM_RIGHTS must be closed and refused, not silently discarded by a stream
    wrapper (the accepted fixture law).
    """

    if sys.platform != "linux":
        raise ContractViolation("the native egress relay requires Linux")
    loop = asyncio.get_running_loop()
    if sock.family != socket.AF_UNIX:
        return await loop.sock_recv(sock, count)
    while True:
        try:
            data, ancillary, flags, _ = sock.recvmsg(count, socket.CMSG_SPACE(1024))
        except BlockingIOError:
            ready: asyncio.Future[None] = loop.create_future()
            loop.add_reader(sock.fileno(), _wake, ready)
            try:
                await ready
            finally:
                loop.remove_reader(sock.fileno())
            continue
        for level, kind, raw in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                descriptors = array.array("i")
                descriptors.frombytes(raw[:len(raw) - len(raw) % descriptors.itemsize])
                for descriptor in descriptors:
                    os.close(descriptor)
        if ancillary or flags & socket.MSG_CTRUNC:
            raise EgressRefused("ancillary")
        return data


def _reason(group: BaseExceptionGroup[EgressRefused]) -> str:
    first = group.exceptions[0]
    return first.reason if isinstance(first, EgressRefused) else _reason(first)


async def _join(tasks: list[asyncio.Task[None]]) -> None:
    await asyncio.gather(*tasks, return_exceptions=True)


def _fixed(message: str, errors: list[BaseException]) -> ContractViolation:
    """Fixed public text; the private originals survive only as the cause."""

    failure = ContractViolation(message)
    failure.__cause__ = errors[0] if len(errors) == 1 else BaseExceptionGroup(message, errors)
    return failure


class EgressRelay:
    """One acquisition's CONNECT relay, entered and exited by one owner task.

    ``observed`` counts classified outcomes as evidence only. ``closed`` is set
    as the last statement of a clean exit, never in a ``finally``.
    """

    def __init__(
        self, policy: EgressPolicy, directory: Path, deadline: float,
        check_control: Callable[[], None],
    ) -> None:
        if not isinstance(policy, EgressPolicy):
            raise ContractViolation("the native egress relay requires a sealed policy")
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ContractViolation("the native egress relay requires a finite deadline")
        if not callable(check_control):
            raise ContractViolation("the native egress relay requires its control check")
        self.observed: Counter[str] = Counter()
        self.closed = False
        self._policy = policy
        self._directory = directory
        self._deadline = deadline
        self._check_control = check_control
        self._stopping = False
        self._connections = 0
        self._owner: asyncio.Task[Any] | None = None
        self._socket: EgressSocket | None = None
        self._listener: socket.socket | None = None
        self._accept: asyncio.Task[None] | None = None
        self._handlers: list[asyncio.Task[None]] = []

    async def __aenter__(self) -> EgressSocket:
        if self._owner is not None:
            raise ContractViolation("a native egress relay is entered once")
        self._owner = asyncio.current_task()
        path = self._directory / SOCKET_NAME
        # Synchronous: no await can interleave between freshness and bind.
        try:
            self._directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._directory.mkdir(mode=0o700)
        except Exception as exc:
            raise ContractViolation(ALLOCATION_FAILED) from exc
        try:
            self._listener, identity = _bind_private_socket(path)
        except Exception as exc:
            errors: list[BaseException] = [exc]
            try:
                self._directory.rmdir()
            except OSError as cleanup:
                errors.append(cleanup)
            raise _fixed(ALLOCATION_FAILED, errors) from None
        self._socket = EgressSocket(path, identity)
        self._accept = asyncio.create_task(self._accept_loop())
        return self._socket

    async def __aexit__(
        self, kind: type[BaseException] | None, error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stopping = True
        cancellation = error if isinstance(error, asyncio.CancelledError) else None
        assert self._accept is not None and self._listener is not None
        tasks = [self._accept, *self._handlers]
        for task in tasks:
            task.cancel()
        # Join before closing the listener, so the accept reader is removed
        # before its descriptor can be reused.
        try:
            await finish_owned(asyncio.create_task(_join(tasks)))
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
        failures: list[BaseException] = []
        for task in tasks:
            failed = None if task.cancelled() else task.exception()
            if failed is not None:
                failures.append(failed)
        try:
            self._listener.close()
        except OSError as exc:
            failures.append(exc)
        try:
            self._release_path()
        except (OSError, ContractViolation) as exc:
            failures.append(exc)
        if failures:
            failure = _fixed(RELAY_FAILED, failures)
            if cancellation is not None:
                raise BaseExceptionGroup(RELAY_FAILED, [cancellation, failure])
            raise failure
        if cancellation is not None and cancellation is not error:
            raise cancellation
        self.closed = True

    def _release_path(self) -> None:
        """Unlink only the socket this relay bound, then its own directory."""

        assert self._socket is not None
        info = os.lstat(self._socket.path)
        if (info.st_dev, info.st_ino) != self._socket.identity:
            raise ContractViolation(SOCKET_CHANGED)
        os.unlink(self._socket.path)
        self._directory.rmdir()

    def _require_live(self, loop: asyncio.AbstractEventLoop) -> None:
        owner = self._owner
        if self._stopping or (owner is not None and owner.cancelling()):
            raise EgressRefused("stopped")
        if loop.time() >= self._deadline:
            raise EgressRefused("deadline")

    def _admit(self, loop: asyncio.AbstractEventLoop) -> None:
        """Liveness, then the owner's control check, synchronously."""

        self._require_live(loop)
        try:
            self._check_control()
        except (Exception, asyncio.CancelledError):
            # A synchronous raise from this call, including a CancelledError
            # subclass such as a local close, is a control denial. This
            # handler's own cancellation can only arrive at an await.
            self._stopping = True
            raise EgressRefused("control") from None

    async def _accept_loop(self) -> None:
        loop = asyncio.get_running_loop()
        assert self._listener is not None
        while True:
            client, _ = await loop.sock_accept(self._listener)
            client.setblocking(False)
            try:
                self._require_live(loop)
            except EgressRefused as refused:
                client.close()
                self.observed["denied:" + refused.reason] += 1
                continue
            self._connections += 1
            if self._connections > self._policy.connections:
                client.close()
                self.observed["denied:connection_bound"] += 1
                continue
            self._handlers.append(asyncio.create_task(self._handle(client)))

    async def _handle(self, client: socket.socket) -> None:
        loop = asyncio.get_running_loop()
        upstream: socket.socket | None = None
        try:
            try:
                async with asyncio.timeout_at(self._deadline):
                    upstream = await self._open(client, loop)
                    self.observed["accepted"] += 1
                    async with asyncio.TaskGroup() as streams:
                        streams.create_task(self._pump(client, upstream, loop))
                        streams.create_task(self._pump(upstream, client, loop))
            except* EgressRefused as refused:
                self.observed["denied:" + _reason(refused)] += 1
            except* TimeoutError:
                self.observed["denied:deadline"] += 1
            except* ConnectionError:
                self.observed["reset"] += 1
        finally:
            client.close()
            if upstream is not None:
                upstream.close()

    async def _fill(
        self, client: socket.socket, buffer: bytearray, limit: int,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        data = await _receive(client, limit - len(buffer))
        self._require_live(loop)
        if not data:
            raise EgressRefused("eof")
        buffer += data

    async def _open(self, client: socket.socket, loop: asyncio.AbstractEventLoop) -> socket.socket:
        """Judge one CONNECT and its first ClientHello, then dial the pin."""

        buffer = bytearray()
        while (end := buffer.find(b"\r\n\r\n")) < 0:
            if len(buffer) >= CONNECT_HEAD_BYTES:
                raise EgressRefused("head")
            await self._fill(client, buffer, CONNECT_HEAD_BYTES, loop)
        host, port = parse_connect(bytes(buffer[:end + 4]))
        # Bytes pipelined after the head stay in this one buffer, unforwarded.
        del buffer[:end + 4]
        destination = self._policy.destination(host, port)
        if destination is None:
            raise EgressRefused("destination")
        await loop.sock_sendall(client, _ESTABLISHED)
        self._require_live(loop)
        while len(buffer) < 5:
            await self._fill(client, buffer, 5, loop)
        total = 5 + _record_length(bytes(buffer[:5]))
        while len(buffer) < total:
            await self._fill(client, buffer, total, loop)
        if client_hello_sni(bytes(buffer[:total])) != host:
            raise EgressRefused("sni")
        self._admit(loop)
        pinned = ipaddress.ip_address(destination.address)
        upstream = socket.socket(
            socket.AF_INET6 if pinned.version == 6 else socket.AF_INET, socket.SOCK_STREAM,
        )
        try:
            upstream.setblocking(False)
            try:
                await loop.sock_connect(upstream, (destination.address, destination.port))
            except OSError:
                raise EgressRefused("upstream_unreachable") from None
            self._admit(loop)
            await loop.sock_sendall(upstream, bytes(buffer))
        except BaseException:
            upstream.close()
            raise
        return upstream

    async def _pump(
        self, source: socket.socket, destination: socket.socket,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        while True:
            data = await _receive(source, CHUNK_BYTES)
            # A queued wake-up runs before a timer expiring in the same
            # iteration, so the deadline and stop latch are rechecked here.
            self._require_live(loop)
            if not data:
                try:
                    destination.shutdown(socket.SHUT_WR)
                except OSError as exc:
                    # The destination already went away; its own read ends.
                    if exc.errno != errno.ENOTCONN:
                        raise
                return
            await loop.sock_sendall(destination, data)
