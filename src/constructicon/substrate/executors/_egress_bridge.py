"""In-zone proxy bridge for the native vendor client. Linux-only, standalone stdlib.

The trusted launcher runs the vendor command through this file, from the
immutable runtime with ``-I``, only when it mounts the egress leaf. It is a
client-compatibility shim, not a boundary: the host relay behind the leaf
enforces every rule (I1). The pinned client reaches a proxy only as
``http://host:port`` over TCP (``M8-N4-proxy-bridge.md``), so each connection
to one loopback listener is joined, byte for byte, to one new leaf connection.
Nothing is parsed, answered or originated here.

The script refuses unless the leaf is a socket, binds the listener, forks the
forwarder, reads its one readiness byte, then replaces itself with the vendor
command, so the payload pid, stdio and exit status stay the vendor's. The
forwarder lives in the zone's private PID namespace, whose trusted PID 1
terminates and reaps it with the payload.
"""

from __future__ import annotations

import os
import signal
import socket
import stat
import sys
import threading
from contextlib import suppress

BRIDGE_SCRIPT = "/usr/libexec/constructicon-egress-bridge.py"
LEAF = "/vendor-egress.sock"
"""``egress.ZONE_SOCKET``; this standalone file cannot import it."""
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 18080
"""Fixed, outside Linux's default ephemeral range, bound before the vendor exists."""
CHUNK_BYTES = 65536
REFUSED = 126
READY = b"\x01"


def refuse(reason: str) -> int:
    print(f"constructicon egress bridge refused: {reason}", file=sys.stderr, flush=True)
    return REFUSED


def environment(inherited: dict[str, str]) -> dict[str, str]:
    """The launcher's environment plus exactly the one proxy variable."""
    return {**inherited, "HTTPS_PROXY": f"http://{PROXY_HOST}:{PROXY_PORT}"}


def leaf_is_socket() -> bool:
    try:
        return stat.S_ISSOCK(os.lstat(LEAF).st_mode)
    except OSError:
        return False


def _dial_leaf() -> socket.socket:
    """Platform primitive: one new connection to the relay's leaf."""
    if sys.platform != "linux":
        raise OSError("the egress leaf requires Linux")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(LEAF)
    except BaseException:
        sock.close()
        raise
    return sock


def _wake(*sockets: socket.socket) -> None:
    for sock in sockets:
        with suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)


def pump(source: socket.socket, destination: socket.socket) -> None:
    """One direction. EOF half-closes the other side; its reverse keeps flowing."""
    while data := source.recv(CHUNK_BYTES):
        destination.sendall(data)
    destination.shutdown(socket.SHUT_WR)


def forward(client: socket.socket) -> None:
    """Join one accepted connection to one new leaf connection, then close both.

    A failed dial closes the client unread and writes it nothing: the vendor
    sees a closed tunnel, never a reply authored here.
    """
    try:
        upstream = _dial_leaf()
    except OSError:
        client.close()
        return

    def direction(source: socket.socket, destination: socket.socket) -> None:
        try:
            pump(source, destination)
        except OSError:
            # Wakes the opposite pump, which may be blocked in recv.
            _wake(client, upstream)

    reverse = threading.Thread(target=direction, args=(upstream, client), daemon=True)
    reverse.start()
    direction(client, upstream)
    reverse.join()
    client.close()
    upstream.close()


def serve(listener: socket.socket) -> None:
    while True:
        client, _ = listener.accept()
        threading.Thread(target=forward, args=(client,), daemon=True).start()


def _isolate(*keep: int) -> None:
    """Drop the payload's stdio and every descriptor but ``keep``.

    The forwarder is forked from the process that becomes the vendor. A stdio
    copy held here would delay the host's EOF until PID 1 killed the forwarder.
    """
    if sys.platform != "linux":
        raise OSError("descriptor isolation requires Linux")
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    for name in os.listdir("/proc/self/fd"):
        fd = int(name)
        if fd > 2 and fd not in keep:
            with suppress(OSError):  # the listing's own descriptor, already closed
                os.close(fd)


def start_forwarder(listener: socket.socket) -> int:
    """Fork the forwarder; return its pid once it has reported readiness.

    Readiness is one byte written after isolation and before the first accept.
    EOF means the child died first; it is reaped here and refused.
    """
    if sys.platform != "linux":
        raise OSError("the forwarder requires Linux")
    read_end, write_end = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_end)
            _isolate(listener.fileno(), write_end)
            os.write(write_end, READY)
            os.close(write_end)
            serve(listener)
        finally:
            os._exit(1)
    os.close(write_end)
    try:
        ready = os.read(read_end, 1)
    finally:
        os.close(read_end)
    if ready != READY:
        os.waitpid(pid, 0)
        raise OSError("the forwarder never became ready")
    return pid


def _listen() -> socket.socket:
    return socket.create_server((PROXY_HOST, PROXY_PORT))


def _restore_signals() -> None:
    """Undo this interpreter's ignored signals, which an exec would keep.

    PID 1 launched this script through ``subprocess``, which restores them for
    the child; ``execve`` does not. Without this the vendor would inherit
    ignored ``SIGPIPE`` and ``SIGXFSZ``, unlike a launch without the bridge.
    """
    if sys.platform != "linux":
        raise OSError("signal restoration requires Linux")
    for kind in (signal.SIGPIPE, signal.SIGXFSZ):
        signal.signal(kind, signal.SIG_DFL)


def _exec(command: list[str], env: dict[str, str]) -> None:
    """Platform primitive: replace this process with the vendor command."""
    os.execve(command[0], command, env)


def main(argv: list[str]) -> int:
    command = argv[1:]
    if not command or not command[0].startswith("/"):
        return refuse("command")
    if not leaf_is_socket():
        return refuse("leaf")
    try:
        listener = _listen()
    except OSError:
        return refuse("listen")
    try:
        start_forwarder(listener)
    except OSError:
        return refuse("forwarder")
    finally:
        # The forwarder holds the only copy; the vendor inherits none.
        listener.close()
    try:
        _restore_signals()
        _exec(command, environment(dict(os.environ)))
    except OSError:
        return refuse("exec")
    return refuse("exec")  # a successful exec never returns


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
