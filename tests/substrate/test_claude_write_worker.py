"""WRITE worker custody tests; portable doubles are not containment proof."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.substrate.executors import claude_read_worker as shared_worker
from constructicon.substrate.executors import claude_write_worker as worker
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessLimits, ProcessResult
from constructicon.substrate.git import contained
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from tests.substrate.test_claude_read_worker import custody as _read_custody
from tests.substrate.test_contained_capture import write_context, write_provider
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher

read_custody = _read_custody


@pytest.fixture
async def custody(read_custody, monkeypatch):
    original, _, _, original_launch, state = read_custody
    launch = replace(original_launch, limits=worker.WRITE_WORKER_LIMITS)
    workspace = ContainedWriteWorkspaceProvider(original.authority,
        root=original.root.with_name("write-owned"), target_ref=original.target_ref,
        provider_id="capture", posture=Posture.WRITE,
        launcher=replace(launch, limits=ProcessLimits()))

    async def run(self, command, **kwargs):
        assert state["held"] == 1
        if kwargs.get("input_kind") == "task":
            state["calls"].append((command, kwargs))
        return ProcessResult(0, b"worker text", b"", 0.01, payload_returncode=0)

    monkeypatch.setattr(LinuxLauncher, "run", run)
    ctx = write_context(workspace)
    acquired = await workspace.acquire(ctx)
    await acquired.materialize()
    return workspace, ctx, acquired, launch, state


def writer(custody, *, observe_result=None):
    workspace, ctx, acquired, launch, _ = custody
    return worker.ClaudeWriteWorker(provider=workspace, context=ctx,
        workspace=acquired.resource, launcher=launch, observe_result=observe_result)


async def test_write_uses_fixed_python_and_only_workspace_guard_with_remaining_deadline(custody):
    observed = []
    write = writer(custody, observe_result=observed.append)
    assert await write("print('bounded')", 30) == "worker text"
    _, _, acquired, _, state = custody
    assert state["held"] == 0
    command, kwargs = state["calls"][0]
    assert command == worker.WRITE_WORKER_COMMAND
    assert kwargs == {"workspace": Path(acquired.resource.path), "posture": Posture.WRITE,
        "guard_fds": (77,), "stdin": b"print('bounded')", "input_kind": "task",
        "timeout_s": kwargs["timeout_s"]}
    assert 0 < kwargs["timeout_s"] < 30
    assert observed == ["success"]
    assert await write("pass", 30) == "worker text"
    assert observed == ["success", "success"]


@pytest.mark.parametrize("program", [None, True, b"pass", "\ud800", "x" * (128 * 1024 + 1)],
                         ids=["null", "boolean", "bytes", "invalid-unicode", "over-bound"])
async def test_invalid_program_is_effect_free_and_poisoned(custody, program):
    write = writer(custody)
    with pytest.raises(ContractViolation):
        await write(program, 30)
    with pytest.raises(ContractViolation):
        await write("pass", 30)
    assert custody[-1]["calls"] == []


def test_program_bound_is_utf8_bytes_and_matches_frozen_write_contract():
    from constructicon.substrate.executors.codex_protocol import (
        TOOL_OUTPUT_BYTES,
        TOOL_PROGRAM_BYTES,
    )

    assert worker.WRITE_PROGRAM_BYTES == TOOL_PROGRAM_BYTES == 128 * 1024
    assert worker.WRITE_OUTPUT_BYTES == TOOL_OUTPUT_BYTES == 32 * 1024
    assert worker.validate_write_program("")
    assert worker.validate_write_program("é" * (64 * 1024))
    assert not worker.validate_write_program("é" * (64 * 1024 + 1))


@pytest.mark.parametrize("changes,category", [
    ({"returncode": 1, "payload_returncode": 1}, "nonzero"),
    ({"returncode": False}, "incomplete"),
    ({"payload_returncode": None}, "incomplete"),
    ({"payload_returncode": 2}, "incomplete"),
    ({"timed_out": True}, "timeout"),
    ({"timed_out": None}, "incomplete"),
    ({"bound_exceeded": "stdout"}, "output_bound"),
    ({"stdout": b"x" * (32 * 1024 + 1)}, "output_bound"),
    ({"stdout": b"\xff"}, "invalid_utf8"),
    ({"stderr": b"x" * 1025}, "output_bound"),
])
async def test_actual_failure_category_precedes_refusal_and_poison(custody, monkeypatch,
                                                                 changes, category):
    result = replace(ProcessResult(0, b"ok", b"", 0.01, payload_returncode=0), **changes)

    async def run(self, *args, **kwargs):
        return result

    monkeypatch.setattr(LinuxLauncher, "run", run)
    observed = []
    write = writer(custody, observe_result=observed.append)
    with pytest.raises(ContractViolation):
        await write("pass", 30)
    assert observed == [category]
    assert custody[-1]["held"] == 0
    with pytest.raises(ContractViolation):
        await write("pass", 30)


async def test_exact_program_and_output_bounds_are_accepted(custody, monkeypatch):
    async def run(self, *args, **kwargs):
        assert len(kwargs["stdin"]) == worker.WRITE_PROGRAM_BYTES
        return ProcessResult(0, b"x" * worker.WRITE_OUTPUT_BYTES, b"", 0.01, payload_returncode=0)

    monkeypatch.setattr(LinuxLauncher, "run", run)
    assert len(await writer(custody)("x" * worker.WRITE_PROGRAM_BYTES, 30)) == 32 * 1024


@pytest.mark.parametrize("change", ["owner", "grants", "revision", "control", "launcher"])
async def test_foreign_or_changed_workspace_authority_refuses(custody, change):
    provider, ctx, acquired, launch, _ = custody
    if change == "owner":
        ctx = replace(ctx, run_lease=ctx.run_lease.model_copy(update={"owner_id": "foreign"}))
    elif change == "grants":
        grants = ctx.binding.effective_grants.model_copy(update={"timeout_s": 29})
        ctx = replace(ctx, binding=ctx.binding.model_copy(update={"effective_grants": grants}))
    elif change == "revision":
        object.__setattr__(acquired.resource.context, "binding",
            ctx.binding.model_copy(update={"revision": "changed"}))
    elif change == "control":
        ctx = replace(ctx, check_control=None)
    else:
        launch = replace(launch, limits=ProcessLimits())
    with pytest.raises(ContractViolation):
        worker.ClaudeWriteWorker(provider=provider, context=ctx,
                                workspace=acquired.resource, launcher=launch)


async def test_result_observation_survives_terminal_closure_but_output_does_not(
    custody, monkeypatch,
):
    provider, _, acquired, _, state = custody
    observed = []

    async def run(self, *args, **kwargs):
        provider.closure.commit(acquired.resource.paths)
        return ProcessResult(0, b"must not publish", b"", 0.01, payload_returncode=0)

    monkeypatch.setattr(LinuxLauncher, "run", run)
    with pytest.raises(ContractViolation, match="permanently closed"):
        await writer(custody, observe_result=observed.append)("pass", 30)
    assert observed == ["success"] and state["held"] == 0


async def test_guard_exit_rechecks_authority_and_keeps_observed_result(custody, monkeypatch):
    provider, _, acquired, _, state = custody
    observed = []

    @asynccontextmanager
    async def closing_guard(paths):
        state["held"] += 1
        try:
            yield 77
        finally:
            state["held"] -= 1
            provider.closure.commit(paths)

    monkeypatch.setattr(contained, "acquisition_guard", closing_guard)
    with pytest.raises(ContractViolation, match="permanently closed"):
        await writer(custody, observe_result=observed.append)("pass", 30)
    assert observed == ["success"] and state["held"] == 0
    assert provider.closure.is_closed(acquired.resource.paths)


async def test_closure_between_thread_observation_and_resume_prevents_worker_launch(
    custody, monkeypatch,
):
    provider, _, acquired, _, state = custody
    finish = shared_worker.finish_owned

    async def close_after_observation(task):
        result = await finish(task)
        provider.closure.commit(acquired.resource.paths)
        return result

    monkeypatch.setattr(shared_worker, "finish_owned", close_after_observation)
    with pytest.raises(ContractViolation, match="permanently closed"):
        await writer(custody)("pass", 30)
    assert state["calls"] == [] and state["held"] == 0


async def test_completed_process_is_observed_when_owner_cancellation_wins(custody, monkeypatch):
    owner = asyncio.current_task()
    observed = []

    async def run(self, *args, **kwargs):
        owner.cancel()
        return ProcessResult(0, b"completed", b"", 0.01, payload_returncode=0)

    monkeypatch.setattr(LinuxLauncher, "run", run)
    with pytest.raises(asyncio.CancelledError):
        await writer(custody, observe_result=observed.append)("pass", 30)
    assert observed == ["success"] and custody[-1]["held"] == 0


async def test_repeated_cancellation_joins_before_guard_release_and_keeps_observer_failure(
    custody, monkeypatch,
):
    entered, release, joined = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def run(self, *args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            joined.set()
            return ProcessResult(0, b"joined", b"", 0.01, payload_returncode=0)

    def observe(category):
        assert category == "success" and joined.is_set()
        raise OSError("observation persistence failed")

    monkeypatch.setattr(LinuxLauncher, "run", run)
    task = asyncio.create_task(writer(custody, observe_result=observe)("pass", 30))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert custody[-1]["held"] == 1 and not task.done()
    task.cancel()
    release.set()
    with pytest.raises(BaseExceptionGroup) as caught:
        await task
    assert caught.value.subgroup(asyncio.CancelledError) is not None
    assert caught.value.subgroup(OSError) is not None
    assert joined.is_set() and custody[-1]["held"] == 0


async def test_overlap_poison_survives_first_worker_completion(custody, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(self, *args, **kwargs):
        entered.set()
        await release.wait()
        return ProcessResult(0, b"must not publish", b"", 0.01, payload_returncode=0)

    monkeypatch.setattr(LinuxLauncher, "run", run)
    write = writer(custody)
    first = asyncio.create_task(write("pass", 30))
    await entered.wait()
    with pytest.raises(ContractViolation):
        await write("pass", 30)
    release.set()
    with pytest.raises(ContractViolation):
        await first
    assert custody[-1]["held"] == 0


async def test_physical_linux_write_worker_uses_networkless_workspace(provider, launcher):
    workspace = write_provider(provider, launcher)
    ctx = write_context(workspace)
    acquired = await workspace.acquire(ctx)
    await acquired.materialize()
    observed = []
    try:
        write = worker.ClaudeWriteWorker(provider=workspace, context=ctx,
            workspace=acquired.resource,
            launcher=replace(launcher, limits=worker.WRITE_WORKER_LIMITS),
            observe_result=observed.append)
        assert await write("from pathlib import Path\nPath('written.txt').write_text('ready\\n')\n"
            "import socket\nassert not socket.socket().connect_ex(('1.1.1.1', 443)) == 0\n"
            "print('done')", 30) == "done\n"
        assert Path(acquired.resource.path, "written.txt").read_bytes() == b"ready\n"
        assert observed == ["success"]
    finally:
        await workspace.close(acquired, "discard")
