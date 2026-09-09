"""Task outcomes from actual contained recordings, plus portable decoder laws."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.substrate.executors.linux import ProcessResult
from tests.containedworld import RecordedExecutorProvider, decode
from tests.substrate.test_contained_workspace import context
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher

PROGRAM = "import sys; sys.stdin.read(); print('{\"type\":\"result\",\"output\":{\"answer\":42}}')"


@pytest.mark.parametrize("raw,code,timeout,bound,status", [
    (b'{"type":"result","output":42}\n', 0, False, None, "success"),
    (b'{"type":"result","output":42}\n', 9, False, None, "failure"),
    (b'{"type":"result","output":42}\n', 0, True, None, "failure"),
    (b'{"type":"result","output":42}\n', -9, False, "record", "partial"),
    (b'broken\n{"type":"result","output":42}\n', 0, False, None, "partial"),
    (b'{"type":"unknown","output":42}\n', 0, False, None, "partial"),
    (b'{"type":"result","output":1,"output":2}\n', 0, False, None, "partial"),
    (b'{"type":"result","output":NaN}\n', 0, False, None, "partial"),
    (b'{"type":"result","output":', 0, False, None, "partial"),
    (b'', 0, False, None, "partial"),
])
def test_recorded_decoder_never_invents_clean_completion(raw, code, timeout, bound, status):
    result = decode(ProcessResult(code, raw, b"", .25, timeout, bound), "requested-alias")
    assert result.status == status
    assert result.served_model is None and result.usage is None and result.rate_limit is None
    assert result.requested_model == "requested-alias"


async def test_one_recorded_task_holds_both_leases_and_closes_before_return(provider, launcher):
    provider.launcher = launcher
    executor = RecordedExecutorProvider(launcher, provider, PROGRAM)
    assert executor.unavailable_reasons
    await executor.qualify()
    assert not executor.unavailable_reasons
    workspace = await provider.acquire(context())
    acquired = await executor.acquire(context(binding="executor"))
    assert not provider.root.exists()
    await workspace.materialize()
    await acquired.materialize()
    grants = acquired.resource.context.binding.effective_grants
    result = await acquired.resource.execute(
        TaskSpec(instruction="quotes'\"\n--option\u2603"),
        workspace=workspace.resource, grants=grants,
    )
    assert result.status == "success" and result.output == {"answer": 42}
    assert result.served_model is None and result.usage is None
    assert acquired.resource.active is None
    await executor.close(acquired, "release")
    await provider.close(workspace, "release")
    assert not workspace.resource.paths.payload.exists()
    assert provider.closure.is_closed(acquired.resource.paths)
    with pytest.raises(ContractViolation, match="not open"):
        await acquired.resource.execute(TaskSpec(instruction="retry"), workspace=workspace.resource,
                                        grants=grants)


@pytest.mark.parametrize("raw,bound,count", [
    (b'broken\nwrong\n{"type":"result","output":42}\n', None, 2),
    (b'{"type":"result","output":42}\n', "stdout", 0),
    (b'', None, 0),
    (b'{"type":"result","output":42}\n{"type":"result","output":43}\n', None, 1),
])
def test_recorded_damage_counts_observed_malformed_records_only(raw, bound, count):
    result = decode(ProcessResult(0, raw, b"", .25, bound_exceeded=bound), "requested")
    assert result.status == "partial"
    assert result.damage.malformed_records == count


async def test_recorded_program_cannot_change_after_its_identity_was_admitted(provider, launcher):
    provider.launcher = launcher
    executor = RecordedExecutorProvider(launcher, provider, PROGRAM)
    await executor.qualify()
    workspace = await provider.acquire(context())
    acquired = await executor.acquire(context(binding="executor"))
    await workspace.materialize()
    await acquired.materialize()
    identity = executor.identity.revision
    executor.program = "print('{\"type\":\"result\",\"output\":\"replacement\"}')"
    assert executor.identity.revision == identity  # The retained admission is unchanged.
    try:
        with pytest.raises(ContractViolation, match="program identity drifted"):
            await acquired.resource.execute(
                TaskSpec(instruction="test"), workspace=workspace.resource,
                grants=acquired.resource.context.binding.effective_grants,
            )
        assert acquired.resource.active is None
    finally:
        await executor.close(acquired, "discard")
        await provider.close(workspace, "discard")


@pytest.mark.parametrize("mismatch", ["network", "posture", "environment", "tool", "timeout"])
async def test_call_cannot_widen_the_acquisitions_sealed_grants(provider, launcher, mismatch):
    provider.launcher = launcher
    executor = RecordedExecutorProvider(launcher, provider, PROGRAM)
    await executor.qualify()
    acquired = await executor.acquire(context(binding="executor"))
    await acquired.materialize()
    grants = acquired.resource.context.binding.effective_grants
    changes = {
        "network": {"network": "allow"}, "posture": {"posture": "write"},
        "environment": {"env_allowlist": ("HOST_SECRET",)}, "tool": {"allowed_tools": ("shell",)},
        "timeout": {"timeout_s": 99},
    }
    with pytest.raises(ContractViolation, match="sealed invocation"):
        await acquired.resource.execute(TaskSpec(instruction="test"), workspace=None,
                                        grants=grants.model_copy(update=changes[mismatch]))
    await executor.close(acquired, "discard")


async def test_two_calls_serialize_and_close_prevents_the_waiting_call(provider, launcher):
    provider.launcher = launcher
    program = "import time; from pathlib import Path; print('ready',flush=True); time.sleep(100)"
    executor = RecordedExecutorProvider(launcher, provider, program)
    await executor.qualify()
    workspace = await provider.acquire(context())
    acquired = await executor.acquire(context(binding="executor"))
    await workspace.materialize()
    await acquired.materialize()
    handle = acquired.resource
    grants = handle.context.binding.effective_grants
    first = asyncio.create_task(handle.execute(TaskSpec(instruction="1"),
                                               workspace=workspace.resource, grants=grants))
    async with asyncio.timeout(10):
        while handle.active is None:
            await asyncio.sleep(.01)
    second = asyncio.create_task(handle.execute(TaskSpec(instruction="2"),
                                                workspace=workspace.resource, grants=grants))
    await asyncio.sleep(.02)
    assert not second.done()
    close = asyncio.create_task(executor.close(acquired, "discard"))
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(ContractViolation, match="closed"):
        await second
    await asyncio.wait_for(close, 10)
    await provider.close(workspace, "discard")
    assert handle.active is None and not workspace.resource.paths.payload.exists()


async def test_runtime_configuration_drift_cannot_retain_the_recorded_provider_identity(
    provider, launcher,
):
    provider.launcher = launcher
    executor = RecordedExecutorProvider(launcher, provider, PROGRAM)
    await executor.qualify()
    workspace = await provider.acquire(context())
    acquired = await executor.acquire(context(binding="executor"))
    await workspace.materialize()
    await acquired.materialize()
    launcher.limits = replace(launcher.limits, stdout_bytes=1000)
    with pytest.raises(ContractViolation, match="identity drifted"):
        await acquired.resource.execute(
            TaskSpec(instruction="test"), workspace=workspace.resource,
            grants=acquired.resource.context.binding.effective_grants,
        )
    await executor.close(acquired, "discard")
    await provider.close(workspace, "discard")
