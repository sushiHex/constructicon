"""Linux-only, single-call child reaper. Executed in a separate interpreter.

No task, workspace, Git, lease, or backend policy lives here. A private pipe
binds this process to its Python owner without a pre-exec parent-death race.
It retains the acquisition guard until its own descendants have been reaped.
The guard and owner pipe are never passed to bubblewrap or its payload.

This file is standalone stdlib so the trusted runtime can execute it with -I.
"""

from __future__ import annotations

import ctypes
import errno
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path


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


def supervise(owner_fd: int, argv: list[str]) -> int:
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
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    poller = select.poll()
    poller.register(owner_fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    if poller.poll(0):
        return 125  # The owner died even before our interpreter started.
    child = subprocess.Popen(argv, close_fds=True, env=dict(os.environ))
    result = 125
    try:
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break  # No descendant remains: only now may the guard close.
            if pid:
                if pid == child.pid:
                    result = os.waitstatus_to_exitcode(status)
                    child.returncode = result
                    stopping = True
                continue
            if poller.poll(10):
                stopping = True
            if stopping:
                _terminate_owned_children()
    finally:
        # An internal failure is not permission to return over living children.
        # Retain the guard throughout this exact-child reap as on normal exit.
        while True:
            _terminate_owned_children()
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if not pid:
                time.sleep(0.01)
    return result if result >= 0 else 128 - result


def main() -> int:
    owner_fd = int(sys.argv[1])
    guards = tuple(int(value) for value in sys.argv[2].split(","))
    # Validate both inherited handles before launching anything. Their only
    # ownership transfer is pass_fds into this interpreter, never into a child.
    os.fstat(owner_fd)
    for guard in guards:
        os.fstat(guard)
    try:
        return supervise(owner_fd, sys.argv[3:])
    except OSError as exc:
        print(f"constructicon supervisor refused: errno={exc.errno or errno.EIO}", file=sys.stderr)
        return 125
    finally:
        os.close(owner_fd)
        for guard in guards:
            os.close(guard)


if __name__ == "__main__":
    raise SystemExit(main())
