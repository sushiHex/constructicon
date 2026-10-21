"""Credential-free private operator descriptor behavior."""

from __future__ import annotations

import asyncio
import os
import socket
import stat
import sys

import pytest

from constructicon.substrate.executors import claude_operator_io as operator


class FakeFDs:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, incoming: bytes = b"") -> None:
        self.incoming = incoming
        self.written: dict[int, bytearray] = {11: bytearray(), 12: bytearray()}
        self.blocking = {10: True, 11: True, 12: True}
        self.flags: list[tuple[int, bool]] = []
        self.partial = False
        monkeypatch.setattr(operator, "_read_fd", self.read)
        monkeypatch.setattr(operator, "_write_fd", self.write)
        monkeypatch.setattr(operator, "_get_blocking", self.get_blocking)
        monkeypatch.setattr(operator, "_set_blocking", self.set_blocking)
        monkeypatch.setattr(operator, "_fd_details", lambda fd: (stat.S_IFIFO, 1, fd))

    def read(self, fd: int, maximum: int) -> bytes:
        assert fd == 10 and not self.blocking[fd]
        chunk = self.incoming[:maximum]
        self.incoming = self.incoming[len(chunk):]
        return chunk

    def write(self, fd: int, data: bytes) -> int:
        assert fd in self.written and not self.blocking[fd]
        count = min(3, len(data)) if self.partial else len(data)
        self.written[fd].extend(data[:count])
        return count

    def get_blocking(self, fd: int) -> bool:
        return self.blocking[fd]

    def set_blocking(self, fd: int, blocking: bool) -> None:
        self.flags.append((fd, blocking))
        self.blocking[fd] = blocking


def lane() -> operator.ClaudeOperatorFDIO:
    loop = asyncio.get_running_loop()
    return operator.ClaudeOperatorFDIO(
        input_fd=10, output_fd=11, error_fd=12, deadline=loop.time() + 5,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("target,alias", [(11, 10), (11, 12), (12, 10)])
async def test_shared_backing_identity_refuses_before_any_flag_change(monkeypatch, target, alias):
    fake = FakeFDs(monkeypatch)
    inspected = []

    def details(fd):
        inspected.append(fd)
        return stat.S_IFSOCK, 1, alias if fd == target else fd

    monkeypatch.setattr(operator, "_fd_details", details)
    with pytest.raises(operator.OperatorIORefused):
        lane()
    assert inspected == [10, 11, 12]
    assert fake.flags == []


@pytest.mark.asyncio
async def test_distinct_devices_are_distinct_backing_endpoints(monkeypatch):
    fake = FakeFDs(monkeypatch, b"line\n")
    monkeypatch.setattr(operator, "_fd_details", lambda fd: (stat.S_IFSOCK, fd, 1))
    io = lane()
    assert await io.read_line() == b"line\n"
    await io.write_stdout(b"ok")
    assert fake.written[11] == b"ok"


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "linux", reason="real Linux socket descriptor identity")
async def test_linux_dup_socket_refuses_before_changing_shared_flags():
    left, right = socket.socketpair()
    duplicate = os.dup(left.fileno())
    err_read, err_write = os.pipe()
    try:
        original = os.fstat(left.fileno())
        copied = os.fstat(duplicate)
        assert (original.st_dev, original.st_ino) == (copied.st_dev, copied.st_ino)
        with pytest.raises(operator.OperatorIORefused):
            operator.ClaudeOperatorFDIO(
                input_fd=left.fileno(), output_fd=duplicate, error_fd=err_write,
                deadline=asyncio.get_running_loop().time() + 5,
            )
        assert os.get_blocking(left.fileno()) and os.get_blocking(duplicate)
    finally:
        os.close(duplicate)
        os.close(err_read)
        os.close(err_write)
        left.close()
        right.close()


@pytest.mark.asyncio
async def test_accepts_exact_input_bound_and_spends_the_only_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFDs(monkeypatch, b"x" * (operator.LINE_BYTES - 1) + b"\n")
    io = lane()
    assert await io.read_line() == b"x" * (operator.LINE_BYTES - 1) + b"\n"
    with pytest.raises(operator.OperatorIORefused, match=r"^Claude operator I/O refused$"):
        await io.read_line()
    assert fake.flags == [(10, False), (10, True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("incoming", [
    b"x" * operator.LINE_BYTES + b"\n", b"partial", b"first\nsecond\n",
])
async def test_rejects_overflow_and_partial_eof_without_returning_bytes(
    monkeypatch: pytest.MonkeyPatch, incoming: bytes,
) -> None:
    fake = FakeFDs(monkeypatch, incoming)
    io = lane()
    with pytest.raises(operator.OperatorIORefused, match=r"^Claude operator I/O refused$"):
        await io.read_line()
    with pytest.raises(operator.OperatorIORefused):
        await io.write_stdout(b"later")
    assert fake.written[11] == b"" and fake.blocking[10]


@pytest.mark.asyncio
async def test_partial_writes_and_exact_cumulative_output_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFDs(monkeypatch)
    fake.partial = True
    io = lane()
    await io.write_stdout(b"abcde")
    fake.partial = False
    await io.write_stdout(b"x" * (operator.STDOUT_BYTES - 5))
    await io.write_stderr(b"e" * operator.STDERR_BYTES)
    assert fake.written[11] == b"abcde" + b"x" * (operator.STDOUT_BYTES - 5)
    assert fake.written[12] == b"e" * operator.STDERR_BYTES
    with pytest.raises(operator.OperatorIORefused):
        await io.write_stdout(b"one over")
    with pytest.raises(operator.OperatorIORefused):
        await io.write_stderr(b"cannot resend")
    assert fake.blocking == {10: True, 11: True, 12: True}


@pytest.mark.asyncio
@pytest.mark.parametrize("stream,limit", [
    ("stdout", operator.STDOUT_BYTES), ("stderr", operator.STDERR_BYTES),
])
async def test_each_output_budget_binds_independently(monkeypatch, stream, limit):
    fake = FakeFDs(monkeypatch)
    io = lane()
    write = getattr(io, "write_" + stream)
    await write(b"x" * limit)
    with pytest.raises(operator.OperatorIORefused):
        await write(b"y")
    assert sum(len(value) for value in fake.written.values()) == limit


@pytest.mark.asyncio
async def test_registration_failure_restores_flags_and_poisoned_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFDs(monkeypatch)

    def blocked(fd: int, maximum: int) -> bytes:
        raise BlockingIOError

    async def unsupported(loop: asyncio.AbstractEventLoop, fd: int, *, writing: bool) -> None:
        raise RuntimeError("platform detail must not escape")

    monkeypatch.setattr(operator, "_read_fd", blocked)
    monkeypatch.setattr(operator, "_wait_ready", unsupported)
    io = lane()
    with pytest.raises(operator.OperatorIORefused) as caught:
        await io.read_line()
    assert str(caught.value) == "Claude operator I/O refused"
    assert fake.flags == [(10, False), (10, True)]


@pytest.mark.asyncio
async def test_partial_write_then_cancellation_cannot_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFDs(monkeypatch)
    waiting = asyncio.Event()
    entered = asyncio.Event()
    calls = 0

    def partial_then_block(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            fake.written[fd].extend(data[:1])
            return 1
        raise BlockingIOError

    async def wait_forever(loop: asyncio.AbstractEventLoop, fd: int, *, writing: bool) -> None:
        assert writing and fd == 11
        entered.set()
        await waiting.wait()

    monkeypatch.setattr(operator, "_write_fd", partial_then_block)
    monkeypatch.setattr(operator, "_wait_ready", wait_forever)
    io = lane()
    task = asyncio.create_task(io.write_stdout(b"secret"))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    with pytest.raises(operator.OperatorIORefused):
        await io.write_stdout(b"secret")
    assert calls == 2 and fake.written[11] == b"s" and fake.blocking[11]


@pytest.mark.asyncio
async def test_absolute_deadline_cannot_be_renewed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeFDs(monkeypatch, b"ok\n")
    loop = asyncio.get_running_loop()
    io = operator.ClaudeOperatorFDIO(
        input_fd=10, output_fd=11, error_fd=12, deadline=loop.time() - 1,
    )
    with pytest.raises(operator.OperatorIORefused):
        await io.read_line()
    assert fake.flags == []


@pytest.mark.asyncio
async def test_only_fifo_or_socket_endpoints_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeFDs(monkeypatch)
    monkeypatch.setattr(operator, "_fd_details",
                        lambda fd: (stat.S_IFREG if fd == 11 else stat.S_IFIFO, 1, fd))
    with pytest.raises(operator.OperatorIORefused, match=r"^Claude operator I/O refused$"):
        lane()
    monkeypatch.setattr(operator, "_fd_details", lambda fd: (stat.S_IFSOCK, 1, fd))
    assert isinstance(lane(), operator.ClaudeOperatorFDIO)
    loop = asyncio.get_running_loop()
    with pytest.raises(Exception) as caught:
        operator.ClaudeOperatorFDIO(
            input_fd=10, output_fd=10, error_fd=12, deadline=loop.time() + 5,
        )
    assert type(caught.value) is ValueError


@pytest.mark.asyncio
@pytest.mark.parametrize("writing", [False, True])
async def test_readiness_callback_is_removed_after_wake_and_cancel(writing: bool) -> None:
    real_loop = asyncio.get_running_loop()

    class Loop:
        def __init__(self) -> None:
            self.callback: object = None
            self.removed: list[tuple[int, bool]] = []

        def create_future(self) -> asyncio.Future[None]:
            return real_loop.create_future()

        def add_reader(self, fd: int, callback: object) -> None:
            assert not writing
            self.callback = callback

        def add_writer(self, fd: int, callback: object) -> None:
            assert writing
            self.callback = callback

        def remove_reader(self, fd: int) -> bool:
            self.removed.append((fd, False))
            return True

        def remove_writer(self, fd: int) -> bool:
            self.removed.append((fd, True))
            return True

    for cancel in (False, True):
        fake = Loop()
        task = asyncio.create_task(operator._wait_ready(fake, 10, writing=writing))  # type: ignore[arg-type]
        await asyncio.sleep(0)
        assert callable(fake.callback)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            fake.callback()
            await task
        assert fake.removed == [(10, writing)]


@pytest.mark.asyncio
async def test_invalidation_cancels_and_joins_pending_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFDs(monkeypatch)
    entered = asyncio.Event()
    released = asyncio.Event()

    def blocked(fd: int, maximum: int) -> bytes:
        raise BlockingIOError

    async def waiting(loop: asyncio.AbstractEventLoop, fd: int, *, writing: bool) -> None:
        assert not writing and fd == 10
        entered.set()
        await released.wait()

    monkeypatch.setattr(operator, "_read_fd", blocked)
    monkeypatch.setattr(operator, "_wait_ready", waiting)
    io = lane()
    task = asyncio.create_task(io.read_line())
    await asyncio.wait_for(entered.wait(), 1)
    io.invalidate()
    assert task.cancelling() > 0
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    with pytest.raises(operator.OperatorIORefused):
        await io.write_stderr(b"after scope")
    assert fake.flags == [(10, False), (10, True)]


@pytest.mark.asyncio
async def test_ready_then_cancel_before_read_resume_restores_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFDs(monkeypatch)
    entered = asyncio.Event()
    ready = asyncio.Event()
    calls = 0

    def blocked(fd: int, maximum: int) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BlockingIOError
        return b"ready\n"

    async def wake_then_cancel(loop: asyncio.AbstractEventLoop, fd: int,
                               *, writing: bool) -> None:
        entered.set()
        await ready.wait()
        current = asyncio.current_task()
        assert current is not None
        current.cancel()

    monkeypatch.setattr(operator, "_read_fd", blocked)
    monkeypatch.setattr(operator, "_wait_ready", wake_then_cancel)
    io = lane()
    task = asyncio.create_task(io.read_line())
    await asyncio.wait_for(entered.wait(), 1)
    ready.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert calls == 1 and fake.flags == [(10, False), (10, True)]


@pytest.mark.asyncio
async def test_last_write_await_rechecks_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFDs(monkeypatch)
    loop = asyncio.get_running_loop()
    tick = [loop.time()]
    monkeypatch.setattr(loop, "time", lambda: tick[0])
    io = operator.ClaudeOperatorFDIO(
        input_fd=10, output_fd=11, error_fd=12, deadline=tick[0] + 1,
    )
    loop.call_soon(lambda: tick.__setitem__(0, tick[0] + 2))
    with pytest.raises(operator.OperatorIORefused):
        await io.write_stdout(b"x")
    assert fake.written[11] == b"x" and fake.blocking[11]
    with pytest.raises(operator.OperatorIORefused):
        await io.write_stdout(b"x")


@pytest.mark.asyncio
async def test_read_failure_cancels_pending_sibling_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFDs(monkeypatch)
    entered = asyncio.Event()
    parked = asyncio.Event()

    def blocked(fd: int, data: bytes) -> int:
        raise BlockingIOError

    async def waiting(loop: asyncio.AbstractEventLoop, fd: int, *, writing: bool) -> None:
        assert writing and fd == 11
        entered.set()
        await parked.wait()

    monkeypatch.setattr(operator, "_write_fd", blocked)
    monkeypatch.setattr(operator, "_wait_ready", waiting)
    io = lane()
    writer = asyncio.create_task(io.write_stdout(b"private"))
    await asyncio.wait_for(entered.wait(), 1)
    with pytest.raises(operator.OperatorIORefused):
        await io.read_line()  # Fake EOF poisons the entire private scope.
    assert writer.cancelling() > 0
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(writer, 1)
    assert fake.blocking == {10: True, 11: True, 12: True}


@pytest.mark.asyncio
async def test_overlapping_writers_poison_and_join_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFDs(monkeypatch)
    entered = asyncio.Event()
    parked = asyncio.Event()
    calls = 0

    def blocked(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls > 1:
            return len(data)  # A forbidden second writer would otherwise park too.
        raise BlockingIOError

    async def waiting(loop: asyncio.AbstractEventLoop, fd: int, *, writing: bool) -> None:
        entered.set()
        await parked.wait()

    monkeypatch.setattr(operator, "_write_fd", blocked)
    monkeypatch.setattr(operator, "_wait_ready", waiting)
    io = lane()
    first = asyncio.create_task(io.write_stdout(b"first"))
    await asyncio.wait_for(entered.wait(), 1)
    with pytest.raises(operator.OperatorIORefused):
        await io.write_stderr(b"second")
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(first, 1)
    assert fake.written == {11: bytearray(), 12: bytearray()}
    assert fake.blocking == {10: True, 11: True, 12: True}


@pytest.mark.asyncio
async def test_restore_failure_preserves_cancellation_in_static_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeFDs(monkeypatch)
    entered = asyncio.Event()
    parked = asyncio.Event()

    def blocked(fd: int, maximum: int) -> bytes:
        raise BlockingIOError

    async def waiting(loop: asyncio.AbstractEventLoop, fd: int, *, writing: bool) -> None:
        entered.set()
        await parked.wait()

    def failed_restore(fd: int, blocking: bool) -> None:
        if blocking:
            raise OSError("private operating-system detail")

    monkeypatch.setattr(operator, "_read_fd", blocked)
    monkeypatch.setattr(operator, "_wait_ready", waiting)
    monkeypatch.setattr(operator, "_set_blocking", failed_restore)
    io = lane()
    reader = asyncio.create_task(io.read_line())
    await asyncio.wait_for(entered.wait(), 1)
    io.invalidate()
    with pytest.raises(BaseException) as caught:
        await asyncio.wait_for(reader, 1)
    assert isinstance(caught.value, BaseExceptionGroup)
    assert any(isinstance(item, asyncio.CancelledError) for item in caught.value.exceptions)
    assert any(isinstance(item, operator.OperatorIORefused) for item in caught.value.exceptions)
    assert "private operating-system detail" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "linux", reason="real fd callbacks require Linux")
async def test_linux_pipe_eof_and_cancelled_reader_restore_flags() -> None:
    read_fd, write_fd = os.pipe()
    sink_read, sink_write = os.pipe()
    err_read, err_write = os.pipe()
    try:
        loop = asyncio.get_running_loop()
        io = operator.ClaudeOperatorFDIO(
            input_fd=read_fd, output_fd=sink_write, error_fd=err_write,
            deadline=loop.time() + 5,
        )
        task = asyncio.create_task(io.read_line())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert os.get_blocking(read_fd)
        with pytest.raises(operator.OperatorIORefused):
            await io.read_line()
        io2 = operator.ClaudeOperatorFDIO(
            input_fd=read_fd, output_fd=sink_write, error_fd=err_write,
            deadline=loop.time() + 5,
        )
        os.write(write_fd, b"partial")
        os.close(write_fd)
        write_fd = -1
        with pytest.raises(operator.OperatorIORefused):
            await asyncio.wait_for(io2.read_line(), 1)
        assert os.get_blocking(read_fd)
    finally:
        for fd in (read_fd, write_fd, sink_read, sink_write, err_read, err_write):
            if fd >= 0:
                os.close(fd)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "linux", reason="real fd callbacks require Linux")
async def test_linux_blocked_output_cancels_without_holding_fd() -> None:
    input_read, input_write = os.pipe()
    output_read, output_write = os.pipe()
    error_read, error_write = os.pipe()
    try:
        os.set_blocking(output_write, False)
        while True:
            try:
                os.write(output_write, b"x" * 8192)
            except BlockingIOError:
                break
        os.set_blocking(output_write, True)
        loop = asyncio.get_running_loop()
        io = operator.ClaudeOperatorFDIO(
            input_fd=input_read, output_fd=output_write, error_fd=error_write,
            deadline=loop.time() + 5,
        )
        task = asyncio.create_task(io.write_stdout(b"one line\n"))
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert os.get_blocking(output_write)
        with pytest.raises(operator.OperatorIORefused):
            await io.write_stdout(b"retry\n")
    finally:
        for fd in (input_read, input_write, output_read, output_write, error_read,
                   error_write):
            os.close(fd)
