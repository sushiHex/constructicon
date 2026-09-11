"""Portable byte-law proofs, not operating-system containment evidence."""

import asyncio

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors.linux import _OwnedStop, _ProcessIO


class Writer:
    def __init__(self):
        self.data = bytearray()
        self.closed = False
        self.release = asyncio.Event()
        self.release.set()
        self.error = None

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        await self.release.wait()
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


def channel(*, budget=3):
    writer = Writer()
    output = bytearray()
    return _ProcessIO(writer, output, budget), writer, output


async def read_soon(io):
    try:
        return await asyncio.wait_for(io.read(), .5)
    except TimeoutError:
        pytest.fail("an available short read or actual EOF failed to progress")


async def test_input_is_cumulative_and_refusal_delivers_no_prefix():
    io, writer, _ = channel()
    await io.write(b"ab")
    with pytest.raises(ContractViolation):
        await io.write(b"cd")
    assert writer.data == b"ab" and io.spent == 2
    await io.write(b"c")
    await io.write(b"")
    assert writer.data == b"abc" and io.spent == 3
    with pytest.raises(ContractViolation):
        await io.write(b"d")
    with pytest.raises(ContractViolation):
        await io.write(bytearray())


async def test_available_short_read_progresses_without_filling_or_inventing_eof():
    io, _, output = channel()
    output.extend(b"short")
    assert await read_soon(io) == b"short"
    pending = asyncio.create_task(io.read())
    await asyncio.sleep(0)
    assert not pending.done()
    with pytest.raises(ContractViolation):
        await io.read()
    output.extend(b"last")
    io.eof = True
    io.changed.set()
    assert await asyncio.wait_for(pending, .5) == b"last"
    assert await read_soon(io) == await read_soon(io) == b""


@pytest.mark.parametrize("maximum", [0, -1, 8193, True, 1.5])
async def test_invalid_read_bounds_refuse(maximum):
    io, _, output = channel()
    output.extend(b"data")
    with pytest.raises(ContractViolation):
        await io.read(maximum)
    assert io.offset == 0


async def test_fragment_reads_keep_one_capture_cursor():
    io, _, output = channel()
    output.extend(b"abcdef")
    io.eof = True
    assert [await io.read(2) for _ in range(4)] == [b"ab", b"cd", b"ef", b""]
    assert output == b"abcdef"  # Consumption cannot erase salvage.


async def test_stdin_half_close_is_idempotent_but_scope_close_refuses_every_operation():
    io, writer, output = channel()
    await io.close_stdin()
    await io.close_stdin()
    assert writer.closed
    with pytest.raises(ContractViolation):
        await io.write(b"")
    output.extend(b"still readable")
    assert await io.read() == b"still readable"
    output.extend(b"after scope")
    io.eof = True
    io.invalidate()
    for operation in (io.read(), io.write(b""), io.close_stdin()):
        with pytest.raises(ContractViolation):
            await operation


async def test_overlapping_write_and_half_close_refuse_without_queueing():
    io, writer, _ = channel(budget=20000)
    writer.release.clear()
    pending = asyncio.create_task(io.write(b"x" * 16000))
    await asyncio.sleep(0)
    assert writer.data == b"x" * 8192 and not pending.done()
    for operation in (io.write(b"y"), io.close_stdin()):
        with pytest.raises(ContractViolation):
            await operation
    io.invalidate()
    writer.release.set()
    with pytest.raises(ContractViolation):
        await pending
    assert writer.data == b"x" * 8192 and io.spent == 16000


async def test_one_reader_and_one_writer_can_make_independent_progress():
    io, writer, output = channel()
    writer.release.clear()
    writing = asyncio.create_task(io.write(b"x"))
    reading = asyncio.create_task(io.read())
    try:
        await asyncio.sleep(0)
        assert not writing.done() and not reading.done()
        output.extend(b"reply")
        io.changed.set()
        assert await asyncio.wait_for(reading, .5) == b"reply"
        assert not writing.done()
        writer.release.set()
        await writing
        assert writer.data == b"x" and io.spent == 1
    finally:
        writer.release.set()
        io.invalidate(stopping=True)
        await asyncio.gather(reading, writing, return_exceptions=True)


@pytest.mark.parametrize("owned_shutdown", [False, True])
async def test_io_failure_is_subordinate_only_to_its_owned_shutdown(owned_shutdown):
    io, writer, _ = channel()
    writer.release.clear()
    writer.error = BrokenPipeError("observed pipe failure")
    pending = asyncio.create_task(io.write(b"x"))
    await asyncio.sleep(0)
    assert not pending.done() and writer.data == b"x"
    if owned_shutdown:
        io.invalidate(stopping=True)
    writer.release.set()
    caught = None
    try:
        await pending
    except Exception as exc:
        caught = exc
    assert isinstance(caught, _OwnedStop if owned_shutdown else BrokenPipeError)
    if owned_shutdown:
        assert caught.__cause__ is writer.error
    else:
        assert caught is writer.error
    assert io.spent == 1


async def test_owned_stop_wakes_a_pending_read():
    io, _, _ = channel()
    pending = asyncio.create_task(io.read())
    await asyncio.sleep(0)
    assert not pending.done()
    io.invalidate(stopping=True)
    with pytest.raises(_OwnedStop):
        await asyncio.wait_for(pending, .5)


@pytest.mark.parametrize("failed_before_stop", [False, True])
async def test_settled_write_failure_keeps_its_order_against_shutdown(failed_before_stop):
    io, writer, _ = channel()
    result = asyncio.get_running_loop().create_future()
    writer.drain = lambda: result
    pending = asyncio.create_task(io.write(b"x"))
    await asyncio.sleep(0)
    assert writer.data == b"x" and not pending.done()
    error = BrokenPipeError("pipe failure")
    if failed_before_stop:
        result.set_exception(error)
    io.invalidate(stopping=True)
    if not failed_before_stop:
        result.set_exception(error)
    caught = None
    try:
        await pending
    except Exception as exc:
        caught = exc
    assert isinstance(caught, BrokenPipeError if failed_before_stop else _OwnedStop)
    assert (caught if failed_before_stop else caught.__cause__) is error
