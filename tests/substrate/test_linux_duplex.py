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


async def exchange(launcher, tmp_path, conversation, *, source=CHALLENGE, timeout=5):
    paths = AcquisitionPaths(tmp_path, acquisition_id_for("duplex-proof", 1))
    async with acquisition_guard(paths) as guard:
        return await launcher.exchange(
            ("/usr/bin/python3", "-I", "-c", source), workspace=None,
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


async def test_cancellation_joins_callback_and_closes_its_handle(launcher, tmp_path):
    entered = asyncio.Event()
    handles, joined = [], []

    async def conversation(io):
        handles.append(io)
        assert await io.read() == b"ready\n"
        entered.set()
        try:
            await io.read()
        finally:
            joined.append(True)

    task = asyncio.create_task(exchange(launcher, tmp_path, conversation, source=(
        "import time; print('ready', flush=True); time.sleep(100)"
    )))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert joined == [True]
        with pytest.raises(ContractViolation):
            await handles[0].write(b"stale")
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cleanup_failure_keeps_the_original_callback_error(launcher, tmp_path, monkeypatch):
    original = ValueError("callback defect")
    cleanup = RuntimeError("cleanup defect")
    failed = []
    finish = linux.finish_owned

    async def observe(task):
        value = await finish(task)
        if failed:
            raise cleanup
        return value

    monkeypatch.setattr(linux, "finish_owned", observe)

    async def conversation(io):
        assert await io.read() == b"ready\n"
        failed.append(True)
        raise original

    with pytest.raises(BaseExceptionGroup) as caught:
        await exchange(launcher, tmp_path, conversation, source="print('ready', flush=True)")
    assert original in caught.value.exceptions and cleanup in caught.value.exceptions
