"""The async contract has a genuine double and runs through the ordinary walker."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.control import RunSubmission
from constructicon.core.envelope import GitRef
from constructicon.core.errors import ContractViolation
from constructicon.core.run import RunStatus
from constructicon.core.workspace import AsyncWriteWorkspace
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.captureworld import ControlledWorkspaceProvider, register_capture
from tests.gitworld import WRITE_GRANTS
from tests.substrate.test_contained_workspace import context


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


async def test_real_walker_passes_control_and_awaits_capture_before_checkpoint(tmp_path):
    provider = ControlledWorkspaceProvider()
    journal = SqliteJournal(tmp_path / "control.sqlite")
    system = Constructicon(
        journal=journal,
        root_grants=WRITE_GRANTS,
        capabilities={"capture": provider},
        catalog={
            "capture": CapabilityDescriptor(
                capability_id="capture",
                kind="workspace.contained",
                revision="fake-async-v1",
                leased=True,
                requires_posture=WRITE_GRANTS.posture,
            )
        },
    )
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        graph = await register_capture(control)
        assert system.describe_component("test/async-capture").name == "test/async-capture"
        submission = await control.runs_start(
            RUN_ACTOR,
            proposal=graph,
            inputs={"goal": {"message": "capture"}},
            idempotency_key="start",
        )
        assert isinstance(submission, RunSubmission), submission
        await until(lambda: provider.handles and provider.handles[0].commit_started.is_set())
        handle = provider.handles[0]
        assert isinstance(handle, AsyncWriteWorkspace)
        assert handle.context.check_control is not None
        assert journal.checkpoint(submission.run_id, handle.context.path) is None
        assert journal.run_state(submission.run_id).status is RunStatus.RUNNING
        handle.commit_allowed.set()
        await until(lambda: journal.run_state(submission.run_id).status is RunStatus.SUCCEEDED)
        checkpoint = journal.checkpoint(submission.run_id, handle.context.path)
        assert checkpoint.outputs["candidate"].payload["commit"] == "b" * 40
        assert provider.dispositions == ["release"] and handle.closed
    finally:
        await control.shutdown()


async def test_async_workspace_double_blocks_each_operation_until_explicitly_released():
    provider = ControlledWorkspaceProvider()
    acquired = await provider.acquire(replace(context(), check_control=lambda: None))
    await acquired.materialize()
    workspace = acquired.resource
    source = GitRef(repository="fake-authority", commit="c" * 40)
    reset = asyncio.create_task(workspace.reset_to(source))
    await workspace.reset_started.wait()
    assert not reset.done() and workspace.git_ref() != source
    workspace.reset_allowed.set()
    await reset
    assert workspace.git_ref() == source
    commit = asyncio.create_task(workspace.commit_all("candidate"))
    await workspace.commit_started.wait()
    assert not commit.done()
    workspace.commit_allowed.set()
    assert await commit == workspace.git_ref().commit == "b" * 40
    await provider.close(acquired, "discard")
    with pytest.raises(ContractViolation, match="not an open invocation"):
        await workspace.commit_all("after closure")
