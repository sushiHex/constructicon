"""Private, attended Claude operator I/O over three borrowed Linux descriptors.

The caller owns and joins the native conversation and any I/O tasks. It lends
descriptors 0/1/2 exclusively for this scope and closes them itself. Changing
O_NONBLOCK also changes every alias of an open file description, including dup
and inherited descriptors; no other reader or writer may use those aliases
until the method has restored the original flag. No output is retained here.
"""

from __future__ import annotations

import asyncio
import math
import os
import stat
import sys

LINE_BYTES = 4096
STDOUT_BYTES = 256 * 1024
STDERR_BYTES = 64 * 1024
_CHUNK_BYTES = 8192


class OperatorIORefused(Exception):
    """Static private-I/O failure; contains no operator or native bytes."""


def _read_fd(fd: int, maximum: int) -> bytes:
    return os.read(fd, maximum)


def _write_fd(fd: int, data: bytes) -> int:
    return os.write(fd, data)


def _get_blocking(fd: int) -> bool:
    return bool(os.get_blocking(fd))  # type: ignore[attr-defined]


def _set_blocking(fd: int, blocking: bool) -> None:
    os.set_blocking(fd, blocking)  # type: ignore[attr-defined]


def _fd_details(fd: int) -> tuple[int, int, int]:
    info = os.fstat(fd)
    return info.st_mode, info.st_dev, info.st_ino


async def _wait_ready(loop: asyncio.AbstractEventLoop, fd: int, *, writing: bool) -> None:
    ready: asyncio.Future[None] = loop.create_future()

    def wake() -> None:
        if not ready.done():
            ready.set_result(None)

    installed = False
    try:
        if writing:
            loop.add_writer(fd, wake)
        else:
            loop.add_reader(fd, wake)
        installed = True
        await ready
    finally:
        if installed:
            if writing:
                loop.remove_writer(fd)
            else:
                loop.remove_reader(fd)


class ClaudeOperatorFDIO:
    """One private input line and bounded, cancellable output on borrowed FDs.

    Construct inside the running loop. ``deadline`` is that loop's absolute
    monotonic time, shared with the native process; it cannot be renewed. The
    caller must join a cancelled read before concluding native termination.
    Neither this class nor a duplicate of its FDs takes descriptor ownership.
    """

    def __init__(self, *, input_fd: int, output_fd: int, error_fd: int,
                 deadline: float) -> None:
        fds = (input_fd, output_fd, error_fd)
        if (any(type(fd) is not int or fd < 0 for fd in fds)
                or len(set(fds)) != 3 or type(deadline) not in (float, int)
                or not math.isfinite(deadline)):
            raise ValueError("invalid Claude operator descriptor or deadline")
        try:
            details = tuple(_fd_details(fd) for fd in fds)
            if any(not (stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode))
                   for mode, _, _ in details):
                raise OperatorIORefused("Claude operator I/O refused")
            if len({(device, inode) for _, device, inode in details}) != 3:
                raise OperatorIORefused("Claude operator I/O refused")
        except OSError:
            raise OperatorIORefused("Claude operator I/O refused") from None
        self._loop = asyncio.get_running_loop()
        self._input_fd = input_fd
        self._output_fd = output_fd
        self._error_fd = error_fd
        self._deadline = deadline
        self._read_spent = False
        self._writing = False
        self._poisoned = False
        self._read_task: asyncio.Task[object] | None = None
        self._write_task: asyncio.Task[object] | None = None
        self._stdout_spent = 0
        self._stderr_spent = 0

    def invalidate(self) -> None:
        """End this scope; the owner must join cancelled operations afterward.

        Cancellation reaches each operation's callback-removal and flag-restore
        ``finally`` before that task can be joined. Borrowed FDs remain open.
        """
        self._poisoned = True
        current = asyncio.current_task()
        for task in (self._read_task, self._write_task):
            if task is not None and task is not current and not task.done():
                task.cancel()

    def _check(self) -> None:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        if (self._poisoned or asyncio.get_running_loop() is not self._loop
                or self._loop.time() >= self._deadline):
            raise OperatorIORefused("Claude operator I/O refused")

    async def read_line(self) -> bytes:
        """Spend the only input attempt; accept one complete LF line only."""
        if self._read_spent or self._poisoned:
            self.invalidate()
            raise OperatorIORefused("Claude operator I/O refused")
        self._read_spent = True
        self._read_task = asyncio.current_task()
        failure = False
        result: bytes | None = None
        try:
            self._check()
            was_blocking = _get_blocking(self._input_fd)
            try:
                if was_blocking:
                    _set_blocking(self._input_fd, False)
                buffered = bytearray()
                async with asyncio.timeout_at(self._deadline):
                    while True:
                        self._check()
                        try:
                            chunk = _read_fd(self._input_fd, LINE_BYTES + 1 - len(buffered))
                        except BlockingIOError:
                            await _wait_ready(self._loop, self._input_fd, writing=False)
                            continue
                        if not chunk:
                            failure = True
                            break
                        if type(chunk) is not bytes or len(chunk) > LINE_BYTES + 1 - len(buffered):
                            failure = True
                            break
                        buffered.extend(chunk)
                        newline = buffered.find(b"\n")
                        if newline >= 0:
                            if newline + 1 <= LINE_BYTES and newline + 1 == len(buffered):
                                result = bytes(buffered)
                                break
                            failure = True
                            break
                        if len(buffered) == LINE_BYTES + 1:
                            failure = True
                            break
            finally:
                if was_blocking:
                    pending = sys.exception()
                    try:
                        _set_blocking(self._input_fd, True)
                    except (OSError, RuntimeError):
                        self.invalidate()
                        if isinstance(pending, asyncio.CancelledError):
                            raise BaseExceptionGroup(
                                "Claude operator I/O cleanup refused",
                                [pending, OperatorIORefused("Claude operator I/O refused")],
                            ) from None
                        raise OperatorIORefused("Claude operator I/O refused") from None
            self._check()
        except asyncio.CancelledError:
            self.invalidate()
            raise
        except (OSError, TimeoutError, RuntimeError, ValueError, NotImplementedError,
                OperatorIORefused):
            failure = True
        finally:
            self._read_task = None
        if failure or result is None or self._poisoned:
            self.invalidate()
            raise OperatorIORefused("Claude operator I/O refused") from None
        return result

    async def write_stdout(self, data: bytes) -> None:
        await self._write(self._output_fd, data, stdout=True)

    async def write_stderr(self, data: bytes) -> None:
        await self._write(self._error_fd, data, stdout=False)

    async def _write(self, fd: int, data: bytes, *, stdout: bool) -> None:
        if self._writing or self._poisoned:
            self.invalidate()
            raise OperatorIORefused("Claude operator I/O refused")
        self._writing = True
        self._write_task = asyncio.current_task()
        failure = False
        try:
            self._check()
            spent = self._stdout_spent if stdout else self._stderr_spent
            limit = STDOUT_BYTES if stdout else STDERR_BYTES
            if type(data) is not bytes or len(data) > limit - spent:
                failure = True
            else:
                if stdout:
                    self._stdout_spent += len(data)
                else:
                    self._stderr_spent += len(data)
                was_blocking = _get_blocking(fd)
                try:
                    if was_blocking:
                        _set_blocking(fd, False)
                    offset = 0
                    async with asyncio.timeout_at(self._deadline):
                        while offset < len(data):
                            self._check()
                            chunk = data[offset:offset + _CHUNK_BYTES]
                            try:
                                written = _write_fd(fd, chunk)
                            except BlockingIOError:
                                await _wait_ready(self._loop, fd, writing=True)
                                continue
                            if type(written) is not int or not 1 <= written <= len(chunk):
                                failure = True
                                break
                            offset += written
                            await asyncio.sleep(0)
                finally:
                    if was_blocking:
                        pending = sys.exception()
                        try:
                            _set_blocking(fd, True)
                        except (OSError, RuntimeError):
                            self.invalidate()
                            if isinstance(pending, asyncio.CancelledError):
                                raise BaseExceptionGroup(
                                    "Claude operator I/O cleanup refused",
                                    [pending, OperatorIORefused("Claude operator I/O refused")],
                                ) from None
                            raise OperatorIORefused("Claude operator I/O refused") from None
            self._check()
        except asyncio.CancelledError:
            self.invalidate()
            raise
        except (OSError, TimeoutError, RuntimeError, ValueError, NotImplementedError,
                OperatorIORefused):
            failure = True
        finally:
            self._writing = False
            self._write_task = None
        if failure or self._poisoned:
            self.invalidate()
            raise OperatorIORefused("Claude operator I/O refused") from None
