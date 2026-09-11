"""Scripted protocol parity and actual Linux duplex lifetime proofs."""

import asyncio
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.process import ProcessIO
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors import linux
from constructicon.substrate.executors.linux import ProcessExchangeError
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests.duplexworld import ScriptedIO
from tests.substrate.test_linux_containment import launcher as launcher

CHALLENGE = """
import hashlib, os, sys
challenge = os.urandom(16).hex().encode()
print(challenge.decode(), flush=True)
answer = sys.stdin.buffer.readline().strip()
assert answer == hashlib.sha256(challenge).hexdigest().encode()
print('confirmed', flush=True)
assert sys.stdin.buffer.read() == b''
"""


async def exchange(launcher, tmp_path, conversation, *, source=CHALLENGE, timeout=5, command=None):
    paths = AcquisitionPaths(tmp_path, acquisition_id_for("duplex-proof", 1))
    async with acquisition_guard(paths) as guard:
        return await launcher.exchange(
            ("/usr/bin/python3", "-I", "-c", source) if command is None else command,
            workspace=None,
            posture=Posture.READ, guard_fds=(guard,), conversation=conversation, timeout_s=timeout,
        )


async def line(io: ProcessIO, maximum: int) -> bytes:
    value = bytearray()
    while not value.endswith(b"\n"):
        chunk = await io.read(maximum)
        assert chunk and len(chunk) <= maximum
        value.extend(chunk)
    return bytes(value)


@pytest.mark.parametrize("backend", ["scripted", "linux"])
@pytest.mark.parametrize("maximum", [1, 8192])
async def test_reply_dependent_conversation_and_scope(backend, maximum, request, tmp_path):
    observed = []
    handles = []

    async def conversation(io: ProcessIO):
        handles.append(io)
        challenge = await line(io, maximum)
        observed.append(challenge)
        with pytest.raises(ContractViolation):
            await io.read(0)
        await io.write(hashlib.sha256(challenge.strip()).hexdigest().encode() + b"\n")
        observed.append(await line(io, maximum))
        assert observed[-1] == b"confirmed\n"
        await io.close_stdin()
        await io.close_stdin()
        assert await io.read() == await io.read() == b""
        with pytest.raises(ContractViolation):
            await io.write(b"")

    if backend == "scripted":
        io = ScriptedIO()
        try:
            await asyncio.wait_for(conversation(io), 2)
        finally:
            io.invalidate()
        captured = io.history
    else:
        actual_launcher = request.getfixturevalue("launcher")
        result = await exchange(actual_launcher, tmp_path, conversation)
        assert result.returncode == 0 and result.payload_returncode == 0, result
        assert not result.timed_out and result.bound_exceeded is None
        captured = result.stdout
        evidence = os.environ.get("M8_EVIDENCE_DIRECTORY")
        if evidence:
            (Path(evidence) / f"duplex-progress-{maximum}.json").write_text(json.dumps({
                "launch_revision": str(actual_launcher.revision), "maximum": maximum,
                "stdout_hex": result.stdout.hex(), "stderr_hex": result.stderr.hex(),
                "returncode": result.returncode, "payload_returncode": result.payload_returncode,
                "timed_out": result.timed_out, "bound_exceeded": result.bound_exceeded,
            }))
    assert captured == b"".join(observed)
    for operation in (handles[0].read(), handles[0].write(b""), handles[0].close_stdin()):
        with pytest.raises(ContractViolation):
            await operation


@pytest.mark.parametrize("cause", ["error", "callback-timeout", "oversized-write"])
async def test_conversation_error_preserves_cause_and_salvage(launcher, tmp_path, cause):
    error = (
        TimeoutError("callback timeout, not launch expiry")
        if cause == "callback-timeout" else ValueError("callback defect")
    )

    async def conversation(io):
        assert await io.read() == b"ready\n"
        if cause == "oversized-write":
            await io.write(b"x" * (launcher.limits.input_bytes + 1))
        raise error

    with pytest.raises(ProcessExchangeError) as caught:
        await exchange(launcher, tmp_path, conversation, source=(
            "import time; print('ready', flush=True); time.sleep(100)"
        ))
    assert caught.value.result.stdout == b"ready\n"
    assert not caught.value.result.timed_out
    if cause == "oversized-write":
        assert isinstance(caught.value.__cause__, ContractViolation)
    else:
        assert caught.value.__cause__ is error


@pytest.mark.parametrize("phase", ["read", "write", "adapter"])
async def test_deadline_stops_and_joins_protocol_work(launcher, tmp_path, phase):
    entered = asyncio.Event()
    joined = []

    async def conversation(io):
        assert await io.read() == b"ready\n"
        entered.set()
        try:
            if phase == "read":
                await io.read()
            elif phase == "write":
                await io.write(b"x" * launcher.limits.input_bytes)
            else:
                await asyncio.Event().wait()
        finally:
            joined.append(True)

    result = await exchange(launcher, tmp_path, conversation, timeout=2, source=(
        "import time; print('ready', flush=True); time.sleep(100)"
    ))
    assert entered.is_set() and joined == [True]
    assert result.timed_out and result.stdout == b"ready\n"


@pytest.mark.parametrize("bound", ["stdout", "record"])
async def test_output_bound_returns_salvage_with_a_stalled_reader(launcher, tmp_path, bound):
    launcher = replace(launcher, limits=replace(
        launcher.limits, stdout_bytes=2048, record_bytes=1024,
    ))

    async def conversation(_io):
        await asyncio.Event().wait()

    payload = "b'x\\n' * 3000" if bound == "stdout" else "b'x' * 1100"
    source = f"import os; os.write(1, {payload})"
    result = await exchange(launcher, tmp_path, conversation, source=source)
    assert result.bound_exceeded == bound and not result.timed_out
    assert result.stdout == (b"x\n" * 1024 if bound == "stdout" else b"x" * 1100)


@pytest.mark.parametrize("phase", ["read", "write", "adapter"])
async def test_cancellation_joins_callback_and_closes_its_handle(launcher, tmp_path, phase):
    entered = asyncio.Event()
    cleaning, release = asyncio.Event(), asyncio.Event()
    handles, joined = [], []

    async def conversation(io):
        handles.append(io)
        assert await io.read() == b"ready\n"
        entered.set()
        try:
            if phase == "read":
                await io.read()
            elif phase == "write":
                await io.write(b"x" * launcher.limits.input_bytes)
            else:
                await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            joined.append(True)

    task = asyncio.create_task(exchange(launcher, tmp_path, conversation, source=(
        "import time; print('ready', flush=True); time.sleep(100)"
    )))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and joined == []
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert joined == [True]
        with pytest.raises(ContractViolation):
            await handles[0].write(b"stale")
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancelled_spawn_is_joined_without_starting_the_conversation(
    launcher, tmp_path, monkeypatch,
):
    created, release = asyncio.Event(), asyncio.Event()
    processes, callbacks = [], []
    spawn = asyncio.create_subprocess_exec

    async def held_spawn(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        processes.append(process)
        if len(processes) == 2:  # Real workload setup, after the physical probe.
            created.set()
            await release.wait()
        return process

    async def conversation(_io):
        callbacks.append(True)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", held_spawn)
    task = asyncio.create_task(exchange(launcher, tmp_path, conversation, source="pass"))
    try:
        await asyncio.wait_for(created.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and callbacks == []
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(processes) == 2 and all(p.returncode is not None for p in processes)
        assert callbacks == []
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_repeated_bound_notifications_do_not_cancel_callback_cleanup(
    launcher, tmp_path, monkeypatch,
):
    launcher = replace(launcher, limits=replace(launcher.limits, stdout_bytes=2048))
    cleaning, owner_joining, release = (asyncio.Event() for _ in range(3))
    aborted, joined = [], []
    finish = linux.finish_owned

    async def observe(task):
        if cleaning.is_set():
            owner_joining.set()
        return await finish(task)

    monkeypatch.setattr(linux, "finish_owned", observe)

    async def conversation(io):
        assert await io.read() == b"ready\n"
        await io.write(b"go\n")
        try:
            await io.read()
        finally:
            cleaning.set()
            try:
                await release.wait()
                joined.append(True)
            except asyncio.CancelledError:
                aborted.append(True)
                raise

    task = asyncio.create_task(exchange(launcher, tmp_path, conversation, source=(
        "import os, sys\nprint('ready', flush=True)\n"
        "assert sys.stdin.readline() == 'go\\n'\nos.write(1, b'x' * 8192)"
    )))
    try:
        await asyncio.wait_for(owner_joining.wait(), 5)
        await asyncio.sleep(0)
        assert not aborted and not task.done()
        release.set()
        result = await task
        assert joined == [True] and result.bound_exceeded == "stdout"
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("fails", [False, True])
async def test_cancellation_during_spawn_preserves_its_message_and_late_failure(
    launcher, tmp_path, monkeypatch, fails,
):
    entered, release = asyncio.Event(), asyncio.Event()
    error = OSError("spawn refused")
    spawn = asyncio.create_subprocess_exec
    calls = 0

    async def delayed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            await release.wait()
            if fails:
                raise error
        return await spawn(*args, **kwargs)

    async def conversation(_io):
        pytest.fail("a cancelled spawn must not start its protocol")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    task = asyncio.create_task(exchange(launcher, tmp_path, conversation, source="pass"))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel("spawn cancellation")
        await asyncio.sleep(0)
        release.set()
        caught = None
        try:
            await task
        except BaseException as exc:
            caught = exc
        assert isinstance(caught, asyncio.CancelledError)
        assert caught.args == ("spawn cancellation",)
        if fails:
            assert isinstance(caught.__cause__, BaseExceptionGroup)
            assert error in caught.__cause__.exceptions
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_read_failure_after_callback_stop_keeps_both_errors(
    launcher, tmp_path, monkeypatch,
):
    original, pipe_error = ValueError("callback failed"), OSError("pipe failed")
    pending = asyncio.get_running_loop().create_future()
    spawn = asyncio.create_subprocess_exec
    invalidate = linux._ProcessIO.invalidate
    calls = 0

    def stopped(io, *, stopping=False):
        invalidate(io, stopping=stopping)
        if stopping and not pending.done() and calls == 2:
            pending.set_exception(pipe_error)

    async def observed_spawn(*args, **kwargs):
        nonlocal calls
        calls += 1
        process = await spawn(*args, **kwargs)
        if calls == 2:
            read = process.stdout.read
            reads = 0

            def observed_read(n):
                nonlocal reads
                reads += 1
                return read(n) if reads == 1 else pending

            monkeypatch.setattr(process.stdout, "read", observed_read)
        return process

    async def conversation(io):
        assert await io.read() == b"ready\n"
        raise original

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observed_spawn)
    monkeypatch.setattr(linux._ProcessIO, "invalidate", stopped)
    with pytest.raises(ProcessExchangeError) as caught:
        await exchange(launcher, tmp_path, conversation, source=(
            "import time; print('ready', flush=True); time.sleep(100)"
        ))
    cause = caught.value.__cause__
    assert isinstance(cause, BaseExceptionGroup)
    assert original in cause.exceptions and pipe_error in cause.exceptions


@pytest.mark.parametrize("phase", ["join", "report", "malformed", "invalid"])
async def test_cleanup_failure_keeps_the_original_callback_error(
    launcher, tmp_path, monkeypatch, phase,
):
    original = ValueError("callback defect")
    cleanup = RuntimeError("cleanup defect")
    failed = []
    finish = linux.finish_owned
    read = os.read

    async def observe(task):
        value = await finish(task)
        if failed:
            raise cleanup
        return value

    def broken_report(fd, count):
        if failed and count == 5:
            if phase == "report":
                raise cleanup
            return b"bad" if phase == "malformed" else b"\xff" * 4
        return read(fd, count)

    if phase == "join":
        monkeypatch.setattr(linux, "finish_owned", observe)
    else:
        monkeypatch.setattr(linux.os, "read", broken_report)

    async def conversation(io):
        assert await io.read() == b"ready\n"
        failed.append(True)
        raise original

    caught = None
    try:
        await exchange(launcher, tmp_path, conversation, source="print('ready', flush=True)")
    except BaseException as exc:
        caught = exc
    assert isinstance(caught, BaseExceptionGroup)
    assert original in caught.exceptions
    if phase in {"join", "report"}:
        assert cleanup in caught.exceptions
    else:
        assert any(isinstance(exc, ContractViolation) for exc in caught.exceptions)


@pytest.mark.parametrize(("source", "output", "diagnostics", "exit_code"), [
    ("pass", b"", b"", 0),
    ("import sys; sys.exit(7)", b"", b"", 7),
    ("import os; os.write(2, b'diagnostic')", b"", b"diagnostic", 0),
    ("import os; os.write(1, b'tail')", b"tail", b"", 0),
])
async def test_eof_and_exit_remain_process_observations(
    launcher, tmp_path, source, output, diagnostics, exit_code,
):
    received = bytearray()

    async def conversation(io):
        while chunk := await io.read(2):
            received.extend(chunk)
        assert await io.read() == b""

    result = await exchange(launcher, tmp_path, conversation, source=source)
    assert bytes(received) == result.stdout == output
    assert result.stderr == diagnostics
    assert result.returncode == result.payload_returncode == exit_code
    assert not result.timed_out and result.bound_exceeded is None


async def test_callback_return_does_not_claim_a_lingering_peer_completed(launcher, tmp_path):
    returned = []

    async def conversation(io):
        assert await io.read() == b"ready\n"
        returned.append(True)

    result = await exchange(launcher, tmp_path, conversation, timeout=2, source=(
        "import time; print('ready', flush=True); time.sleep(100)"
    ))
    assert returned == [True]
    assert result.timed_out and result.stdout == b"ready\n"


async def test_progress_does_not_renew_the_absolute_deadline(launcher, tmp_path):
    received = bytearray()

    async def conversation(io):
        while chunk := await io.read():
            received.extend(chunk)

    result = await exchange(launcher, tmp_path, conversation, timeout=2, source=(
        "import os, time\nwhile True: os.write(1, b'.\\n'); time.sleep(.01)"
    ))
    assert len(received) >= 6 and result.stdout.startswith(received)
    assert result.timed_out and result.bound_exceeded is None
