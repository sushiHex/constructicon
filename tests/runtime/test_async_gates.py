"""The async call convention is admitted and awaited by the unchanged walker."""

import asyncio

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.control import RunSubmission
from constructicon.core.gates import MergeEvaluation, MergeGate
from constructicon.core.run import RunStatus
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.gates.runner import MergeEvaluation as LegacyEvaluation
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.gateworld import ControlledGateProvider, register_gate
from tests.gitworld import WRITE_GRANTS
from tests.runtime.test_async_workspace import until


def gate_system(journal, provider, *, owner="gate-owner", lease_ttl_s=30):
    return Constructicon(
        journal=journal, root_grants=WRITE_GRANTS, capabilities={"gate": provider},
        catalog={"gate": CapabilityDescriptor(
            capability_id="gate", kind="gates.contained", revision=provider.revision,
            leased=True,
        )}, owner_id=owner, lease_ttl_s=lease_ttl_s,
        heartbeat_interval_s=min(1, lease_ttl_s / 5),
    )


def test_merge_evaluation_is_the_same_legacy_class_and_wire_shape():
    assert LegacyEvaluation is MergeEvaluation
    value = MergeEvaluation(subject=None, attestation_id=None, checks=())
    assert value.model_dump_json() == '{"subject":null,"attestation_id":null,"checks":[]}'
    assert not value.ok


@pytest.mark.parametrize("finish", ["pass", "cancel", "shutdown"])
async def test_walker_awaits_gate_and_never_checkpoints_cancelled_work(tmp_path, finish):
    provider = ControlledGateProvider()
    journal = SqliteJournal(tmp_path / "gate.sqlite")
    system = gate_system(journal, provider)
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        graph = await register_gate(control)
        assert system.describe_component("test/async-gate").name == "test/async-gate"
        assert system.rdeps("test/async-gate") == []
        assert system.describe().capabilities
        submission = await control.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"candidate": {"commit": "a" * 40}},
            idempotency_key="start-gate",
        )
        assert isinstance(submission, RunSubmission), submission
        await until(lambda: provider.handles and provider.handles[0].started.is_set())
        handle = provider.handles[0]
        assert isinstance(handle, MergeGate)
        assert journal.checkpoint(submission.run_id, handle.context.path) is None
        if finish == "pass":
            handle.allowed.set()
            await until(lambda: journal.run_state(submission.run_id).status is RunStatus.SUCCEEDED)
            assert journal.checkpoint(submission.run_id, handle.context.path) is not None
            assert provider.dispositions == ["release"]
        else:
            if finish == "cancel":
                await control.runs_cancel(
                    RUN_ACTOR, run_id=submission.run_id, idempotency_key="cancel",
                )
                await until(
                    lambda: journal.run_state(submission.run_id).status is RunStatus.CANCELLED,
                )
            else:
                await control.shutdown()
            assert journal.checkpoint(submission.run_id, handle.context.path) is None
            await until(lambda: handle.closed)
            assert provider.dispositions == ["discard"]
        assert handle.closed
    finally:
        await control.shutdown()


async def test_gate_double_holds_the_caller_until_explicit_release():
    from dataclasses import replace

    from tests.substrate.test_contained_workspace import context

    provider = ControlledGateProvider()
    acquired = await provider.acquire(replace(context(), check_control=lambda: None))
    pending = asyncio.create_task(acquired.resource.verify("a" * 40))
    await acquired.resource.started.wait()
    assert not pending.done()
    acquired.resource.allowed.set()
    assert isinstance(await pending, MergeEvaluation)
