"""Linux-only, single-call child reaper. Executed in a separate interpreter.

No task, workspace, Git, lease, or backend policy lives here. A private pipe
binds this process to its Python owner without a pre-exec parent-death race.
It retains the acquisition guard until its own descendants have been reaped.
Guards and the controller pipe stay outside bubblewrap. A separate lifetime
descriptor reaches trusted PID 1 only; payloads inherit no private descriptor.

This file is standalone stdlib so the trusted runtime can execute it with -I.
"""

from __future__ import annotations

import ctypes
import errno
import math
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

NAMESPACE_SCRIPT = "/usr/libexec/constructicon-supervisor.py"
TERM_GRACE_S = 2.0


def _owner_closed(events: list[tuple[int, int]]) -> bool:
    if sys.platform != "linux":
        raise OSError("owner-pipe events require Linux")
    return any(flags & (select.POLLHUP | select.POLLERR) for _, flags in events)


class _Shutdown:
    """One non-renewable grace window, beginning at actual namespace TERM."""

    def __init__(self, deadline: float) -> None:
        self.deadline = deadline
        self._requested = False
        self.started: float | None = None

    def request(self, _signum: int = 0, _frame: object = None) -> None:
        self._requested = True

    def acknowledge_term(self, when: float) -> None:
        if self.started is None:
            self.started = when

    @property
    def requested(self) -> bool:
        return self._requested or time.monotonic() >= self.deadline

    @property
    def forced(self) -> bool:
        return (
            self.started is not None
            and time.monotonic() >= self.started + TERM_GRACE_S
        )


def _reap(
    child: subprocess.Popen[bytes], owner_fd: int, shutdown: _Shutdown,
    begin_term: Callable[[], float | None], force: Callable[[], None],
) -> int:
    if sys.platform != "linux":
        raise OSError("owned child reaping requires Linux")
    poller = select.poll()
    poller.register(owner_fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    result = 125

    def advance() -> None:
        if shutdown.requested and shutdown.started is None:
            when = begin_term()
            if when is not None:
                shutdown.acknowledge_term(when)
        if shutdown.forced:
            force()

    try:
        while True:
            if poller.poll(0):
                shutdown.request()
            advance()
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid:
                if pid == child.pid:
                    result = os.waitstatus_to_exitcode(status)
                    child.returncode = result
                    shutdown.request()
                continue
            time.sleep(0.01)
    finally:
        # A failure does not release guards over surviving work. The original
        # TERM time also survives repeated signals and fallback cleanup.
        shutdown.request()
        while True:
            advance()
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if not pid:
                time.sleep(0.01)
    return result if result >= 0 else 128 - result


def _signal_namespace(force: bool) -> None:
    if sys.platform != "linux" or os.getpid() != 1:
        raise OSError("namespace-wide signaling requires private PID 1")
    with suppress(ProcessLookupError):
        os.kill(-1, signal.SIGKILL if force else signal.SIGTERM)


def supervise_namespace(control: socket.socket, deadline: float, argv: list[str]) -> int:
    """Trusted PID 1 replaces bwrap's init; the payload inherits no private fd."""

    if sys.platform != "linux" or os.getpid() != 1:
        raise OSError("workload supervision requires a private Linux PID namespace")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE: protect this init's fds/memory.
        raise OSError(ctypes.get_errno(), "cannot protect namespace init")
    shutdown = _Shutdown(deadline)
    signal.signal(signal.SIGTERM, shutdown.request)
    signal.signal(signal.SIGINT, shutdown.request)
    poller = select.poll()
    poller.register(control.fileno(), select.POLLIN | select.POLLHUP | select.POLLERR)
    if poller.poll(0) or shutdown.requested:
        return 125
    child = subprocess.Popen(argv, close_fds=True, env=dict(os.environ))

    def begin_term() -> float:
        _signal_namespace(False)
        when = time.monotonic()
        # One atomic record on a private sequenced-packet socket. Both reapers
        # use this timestamp, never the earlier request/deadline observation.
        with suppress(BrokenPipeError, ConnectionResetError):
            control.send(struct.pack("!d", when))
        return when

    result = _reap(
        child, control.fileno(), shutdown, begin_term, lambda: _signal_namespace(True),
    )
    # This descriptor belongs to trusted PID 1, never the repository check.
    # Four-byte exit facts are distinct from the existing eight-byte TERM ack.
    control.send(struct.pack("!i", result))
    return result


def _subreaper() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "cannot become the call's child reaper")


def _terminate_owned_children() -> None:
    if sys.platform != "linux":
        raise OSError("child reaping requires Linux")
    # Only our unreaped children, including namespace init adopted when bwrap's
    # monitor exits. Never inspect unrelated /proc entries or replay a PID.
    # This process alone calls waitpid, so none can be reaped/reused between
    # reading this kernel-owned list and opening its pidfd.
    children = Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()
    for child in children:
        try:
            fd = os.pidfd_open(int(child))
        except ProcessLookupError:
            continue
        try:
            signal.pidfd_send_signal(fd, signal.SIGKILL)
        except ProcessLookupError:
            pass
        finally:
            os.close(fd)


def supervise(
    owner_fd: int, deadline: float, argv: list[str], *, report_fd: int | None = None,
) -> int:
    if sys.platform != "linux":
        raise OSError("child supervision requires Linux")
    _subreaper()
    os.setsid()
    import resource

    # Per-process bounds, not a claim of per-tenant CPU/memory/PID isolation.
    # The pinned supervisor source includes these fixed limits in launch identity.
    for kind, value in (
        (resource.RLIMIT_CORE, 0),
        (resource.RLIMIT_NOFILE, 256),
        (resource.RLIMIT_FSIZE, 128 * 1024 * 1024),
        (resource.RLIMIT_AS, 2 * 1024 * 1024 * 1024),
    ):
        resource.setrlimit(kind, (value, value))
    shutdown = _Shutdown(deadline)
    signal.signal(signal.SIGTERM, shutdown.request)
    signal.signal(signal.SIGINT, shutdown.request)
    poller = select.poll()
    poller.register(owner_fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    # The same private pipe grants start and then witnesses owner lifetime.
    # Until Python owns the spawn handle, this setup child only holds guards.
    # Its independent monotonic deadline also covers a stalled controller.
    while not (events := poller.poll(10)):
        if shutdown.requested:
            return 125
    if _owner_closed(events):
        return 125  # Buffered permission cannot outlive observed owner death.
    if os.read(owner_fd, 1) != b"\x01" or shutdown.requested:
        return 125
    # TERM must reach workloads, not kill bwrap's monitor and trigger PDEATHSIG.
    # A private socket reaches only trusted init: EOF requests TERM; the reverse
    # direction acknowledges its actual send time. A delayed init cannot lose
    # its grace to an earlier external clock. No acknowledgement means no
    # fallback KILL or claim of quiescence; guards remain until children exit.
    # Acquisition guards remain here, outside every payload namespace.
    control, namespace = socket.socketpair(type=socket.SOCK_SEQPACKET)
    with control, namespace:
        control.setblocking(False)
        requested = False
        payload_exit: int | None = None
        term_time: float | None = None

        def read_control() -> None:
            nonlocal payload_exit, term_time
            with suppress(BlockingIOError, ConnectionResetError):
                while message := control.recv(9):
                    if len(message) == 8:
                        term_time = float(struct.unpack("!d", message)[0])
                    elif len(message) == 4 and payload_exit is None:
                        payload_exit = int(struct.unpack("!i", message)[0])
                    else:
                        raise OSError("invalid private namespace report")

        def begin_term() -> float | None:
            nonlocal requested
            if not requested:
                # The peer may already have exited. This never substitutes an
                # invented TERM timestamp for the peer's acknowledgement.
                with suppress(OSError):
                    control.shutdown(socket.SHUT_WR)
                requested = True
            read_control()
            return term_time

        namespace_fd = namespace.fileno()
        split = argv.index("--")
        command = [
            *argv[:split], "--as-pid-1", "--sync-fd", str(namespace_fd), "--",
            "/usr/bin/python3", "-I", NAMESPACE_SCRIPT, "--namespace",
            str(namespace_fd), str(deadline), *argv[split + 1:],
        ]
        if shutdown.requested or _owner_closed(poller.poll(0)):
            return 125
        child = subprocess.Popen(
            command, close_fds=True, pass_fds=(namespace_fd,), env=dict(os.environ),
        )
        namespace.close()
        result = _reap(child, owner_fd, shutdown, begin_term, _terminate_owned_children)
        read_control()
        if report_fd is not None and payload_exit is not None:
            os.write(report_fd, struct.pack("!i", payload_exit))
        return result


def main() -> int:
    if sys.argv[1] == "--namespace":
        owner_fd = int(sys.argv[2])
        deadline = float(sys.argv[3])
        if not math.isfinite(deadline):
            raise ValueError("a finite monotonic deadline is required")
        with socket.socket(fileno=owner_fd) as control:
            return supervise_namespace(control, deadline, sys.argv[4:])
    owner_fd = int(sys.argv[1])
    guards = tuple(int(value) for value in sys.argv[2].split(","))
    deadline = float(sys.argv[3])
    if not math.isfinite(deadline):
        raise ValueError("a finite monotonic deadline is required")
    # Validate both inherited handles before launching anything. Their only
    # ownership transfer is pass_fds into this interpreter, never into a child.
    os.fstat(owner_fd)
    for guard in guards:
        os.fstat(guard)
    report_fd = None
    arguments = sys.argv[4:]
    if arguments and arguments[0].startswith("--report-fd="):
        report_fd = int(arguments.pop(0).split("=", 1)[1])
        os.fstat(report_fd)
    try:
        return supervise(owner_fd, deadline, arguments, report_fd=report_fd)
    except OSError as exc:
        print(f"constructicon supervisor refused: errno={exc.errno or errno.EIO}", file=sys.stderr)
        return 125
    finally:
        os.close(owner_fd)
        for guard in guards:
            os.close(guard)
        if report_fd is not None:
            os.close(report_fd)


if __name__ == "__main__":
    raise SystemExit(main())
