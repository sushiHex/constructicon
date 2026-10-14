"""Actual walker attempts after administrative accounting abandonment."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.core.control import (
    CapabilityAcquisitionPair,
    CapabilityDisposalResult,
    RunResultPreviewV2,
    RunSubmission,
)
from constructicon.core.errors import ContractViolation
from constructicon.core.run import CleanupUnresolved, RunStatus
from tests.api.test_capability_disposal import ADMIN, READER
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.api.test_executor_admission import INPUTS
from tests.executorworld import AllocationLedger, register_component
from tests.runtime.test_ownership_loss_custody import Custody, RetainingProvider, World


class FailingCleanupProvider(RetainingProvider):
    """Retained resource/guard and provider operations share the real lease path."""

    def __init__(self, *, ledger, custody, retain_guard=False):
        super().__init__(ledger=ledger, custody=custody)
        self.calls = []
        self.fail_close = True
        self.fail_reconcile = True
        self.retain_guard = retain_guard

    async def acquire(self, context):
        self.calls.append("acquire")
        if self.retain_guard and any(lock.locked() for lock in self.custody.locks.values()):
            raise ContractViolation("retained physical acquisition guard refuses reuse")
        return await super().acquire(context)

    async def close(self, acquisition, disposition):
        self.calls.append("close")
        if self.fail_close:
            raise OSError("persistent provider cleanup failure")
        return await super().close(acquisition, disposition)

    async def relinquish(self, acquisition):
        self.calls.append("relinquish")
        if self.retain_guard:
            # The fake external owner retains custody independently of the
            # journal's NULL worker owner, just as a surviving supervisor can.
            self.relinquished.append(acquisition.resource_ref)
            return
        await super().relinquish(acquisition)

    async def reconcile(self, context, stale):
        self.calls.append("reconcile")
        if self.fail_reconcile:
            raise OSError("persistent provider reconciliation failure")
        return await super().reconcile(context, stale)


@asynccontextmanager
async def failed_host_world(journal, clock, *, checkpointed=True, retain_guard=False,
                            sibling=False):
    ledger, custody = AllocationLedger(), Custody()
    provider = FailingCleanupProvider(ledger=ledger, custody=custody, retain_guard=retain_guard)
    providers = {"retaining": provider}
    if sibling:
        providers["sibling"] = FailingCleanupProvider(ledger=ledger, custody=custody)
    world = World(journal=journal, clock=clock, ledger=ledger, custody=custody,
                  providers=providers)
    system = world.system("disposal-worker", providers)
    if not checkpointed:
        async def fail_node(handle):
            raise ValueError("uncheckpointed invocation failure")

        provider.before_execute = fail_node
    bindings = {"executor": "retaining", **({"z": "sibling"} if sibling else {})}
    graph = await register_component(system, journal, bindings=bindings)
    failed = asyncio.Event()
    failures = []

    def observe_failure(run_id, error):
        failures.append((run_id, error))
        failed.set()

    host = RunHost(system, journal=journal, now_fn=clock.now, on_failure=observe_failure)
    control = ControlPlane(system=system, store=journal, run_host=host, owner_id="disposal-host")
    await control.startup()
    submission = await control.runs_start(RUN_ACTOR, proposal=graph, inputs=INPUTS,
                                         idempotency_key="cleanup-failure")
    assert isinstance(submission, RunSubmission)
    async with asyncio.timeout(5):
        await failed.wait()
        await asyncio.gather(*tuple(host._tasks.values()))
        await host.startup()
    run_id = submission.run_id
    assert len(failures) == 1
    failure = failures[0][1]
    if sibling:
        assert isinstance(failure, ExceptionGroup)
        assert len(failure.exceptions) == 2
        assert all(isinstance(error, OSError) for error in failure.exceptions)
    else:
        assert isinstance(failure, OSError)
    assert run_id in host._deferred and host.active_run_ids == ()
    state = journal.run_state(run_id)
    assert state.status is RunStatus.RUNNING and state.owner_id is None
    assert len(journal.capability_leases(run_id)) == (2 if sibling else 1)
    assert all(row.state == "active" for row in journal.capability_leases(run_id))
    checkpoint = journal.checkpoint(run_id, provider.handles[0].context.path)
    assert (checkpoint is not None) is checkpointed
    try:
        yield world, system, host, control, run_id, failures
    finally:
        await control.shutdown()
        for resource in providers.values():
            for handle in resource.handles:
                handle.release()


async def dispose_provider(control, journal, run_id, provider, *, key="abandon-cleanup"):
    pair = CapabilityAcquisitionPair(lease_id=provider.acquisitions[0].lease_id,
                                    acquisition_epoch=provider.handles[0].context.run_lease.epoch)
    before_calls = list(provider.calls)
    before_operations = list(provider.ledger.operations)
    before_handles = list(provider.handles)
    before_executions = list(provider.executor.calls)
    result = await control.runs_dispose_capabilities(
        ADMIN, run_id=run_id, pairs=(pair,), reason="persistent fake cleanup failure",
        idempotency_key=key,
    )
    assert isinstance(result, CapabilityDisposalResult)
    assert result.physical_cleanup == "unverified"
    replay = await control.runs_dispose_capabilities(
        ADMIN, run_id=run_id, pairs=(pair,), reason="persistent fake cleanup failure",
        idempotency_key=key,
    )
    assert isinstance(replay, CapabilityDisposalResult) and replay.command.replayed
    assert replay.receipt == result.receipt
    assert provider.calls == before_calls and provider.ledger.operations == before_operations
    assert provider.handles == before_handles and provider.executor.calls == before_executions
    assert next(row for row in journal.capability_leases(run_id)
                if row.lease_id == pair.lease_id
                and row.acquisition_epoch == pair.acquisition_epoch).state == "lost"
    return result


async def join_attempt(host, run_id):
    """One observed pump scan, the chosen worker, and its retirement callback."""
    async with asyncio.timeout(5):
        await host.startup()
        assert host.active_run_ids == (run_id,)
        await asyncio.gather(*tuple(host._tasks.values()))
        await host.startup()
    assert host.active_run_ids == ()


@pytest.mark.parametrize("checkpointed,cancelled", ((True, False), (True, True), (False, False)))
async def test_fresh_resume_clears_actual_failure_deferral_and_preserves_next_attempt_contract(
    journal, clock, checkpointed, cancelled,
):
    async with failed_host_world(journal, clock, checkpointed=checkpointed) as fixture:
        world, _, host, control, run_id, failures = fixture
        provider = world.providers["retaining"]
        if cancelled:
            await control.runs_cancel(RUN_ACTOR, run_id=run_id,
                                      idempotency_key="retain-cancellation")
        before = journal.run_head(run_id).record
        executions = len(provider.executor.calls)
        await dispose_provider(control, journal, run_id, provider)
        assert journal.run_head(run_id).record == before
        await host.startup()
        assert run_id in host._deferred and host.active_run_ids == ()
        assert run_id not in host._requested
        assert len(failures) == 1 and len(provider.executor.calls) == executions
        provider.fail_close = False
        provider.before_execute = None
        baseline = journal.max_event_seq(run_id)
        submitted = await control.runs_resume(RUN_ACTOR, run_id=run_id,
                                              idempotency_key="fresh-post-disposal-resume")
        assert isinstance(submitted, RunSubmission) and run_id not in host._deferred
        await join_attempt(host, run_id)
        expected = RunStatus.CANCELLED if cancelled else RunStatus.SUCCEEDED
        assert journal.run_state(run_id).status is expected
        attempts = [event for event in journal.events(run_id, after_seq=baseline)
                    if event.kind == "RunReclaimed"]
        assert len(attempts) == 1
        assert attempts[0].payload == {"resume_command_id": submitted.command.command_id}
        assert "reconcile" not in provider.calls
        assert len(provider.executor.calls) == executions + int(not checkpointed and not cancelled)
        rows = journal.capability_leases(run_id)
        assert rows[0].state == "lost"
        if not checkpointed:
            assert len(rows) == 2 and rows[1].state == "closed"
            assert rows[1].acquisition_epoch > rows[0].acquisition_epoch
        preview = control.runs_result(READER, run_id)
        assert isinstance(preview, RunResultPreviewV2)
        assert preview.status is expected and preview.capability_accounting.disposed_count == 1
        if not cancelled:
            assert preview.outputs == {"summary": {"text": "materialized"}}


async def test_restarted_host_recovers_disposed_checkpoint_without_explicit_resume(journal, clock):
    async with failed_host_world(journal, clock) as fixture:
        world, system, _host, control, run_id, _ = fixture
        provider = world.providers["retaining"]
        await dispose_provider(control, journal, run_id, provider)
        calls = list(provider.calls)
        executions = len(provider.executor.calls)
        baseline = journal.max_event_seq(run_id)
        await control.shutdown()
        fresh = RunHost(system, journal=journal, now_fn=clock.now)
        try:
            await join_attempt(fresh, run_id)
        finally:
            await fresh.shutdown()
        assert journal.run_state(run_id).status is RunStatus.SUCCEEDED
        attempts = [event for event in journal.events(run_id, after_seq=baseline)
                    if event.kind == "RunReclaimed"]
        assert len(attempts) == 1 and not attempts[0].payload
        assert provider.calls == calls and len(provider.executor.calls) == executions


async def test_disposal_retains_provider_guard_that_refuses_fresh_uncheckpointed_acquisition(
    journal, clock,
):
    async with failed_host_world(journal, clock, checkpointed=False, retain_guard=True) as fixture:
        world, _, host, control, run_id, _ = fixture
        provider = world.providers["retaining"]
        old_handle = provider.handles[0]
        assert old_handle.held and world.custody.lock(old_handle.key).locked()
        resources = set(world.ledger.resources)
        await dispose_provider(control, journal, run_id, provider)
        assert old_handle.held and world.custody.lock(old_handle.key).locked()
        assert world.ledger.resources == resources
        provider.before_execute = None
        provider.fail_close = False
        submitted = await control.runs_resume(RUN_ACTOR, run_id=run_id,
                                              idempotency_key="guard-still-authoritative")
        assert isinstance(submitted, RunSubmission)
        await join_attempt(host, run_id)
        assert journal.run_state(run_id).status is RunStatus.FAILED
        assert provider.calls.count("acquire") == 2 and len(provider.handles) == 1
        assert provider.executor.calls == [] and "reconcile" not in provider.calls
        assert world.ledger.resources == resources and old_handle.held
        failed = [event for event in journal.events(run_id) if event.kind == "NodeFailed"]
        assert failed[-1].payload["error"] == "retained physical acquisition guard refuses reuse"


async def test_unnamed_active_obligation_keeps_cancelled_run_nonterminal(journal, clock):
    async with failed_host_world(journal, clock, sibling=True) as fixture:
        world, _, host, control, run_id, failures = fixture
        named, unnamed = world.providers["retaining"], world.providers["sibling"]
        await control.runs_cancel(RUN_ACTOR, run_id=run_id, idempotency_key="blocked-cancellation")
        await dispose_provider(control, journal, run_id, named)
        submitted = await control.runs_resume(RUN_ACTOR, run_id=run_id,
                                              idempotency_key="unnamed-reconciliation-attempt")
        assert isinstance(submitted, RunSubmission)
        await join_attempt(host, run_id)
        assert len(failures) == 2 and isinstance(failures[-1][1], OSError)
        assert unnamed.calls.count("reconcile") == 1 and "reconcile" not in named.calls
        assert journal.cancel_requested(run_id)
        assert journal.run_state(run_id).status is RunStatus.RUNNING
        assert journal.run_state(run_id).owner_id is None and run_id in host._deferred
        rows = journal.capability_leases(run_id)
        assert sorted(row.state for row in rows) == ["active", "lost"]
        # Affirmatively exercise the unchanged terminal guard with the unnamed
        # acquisition still active, rather than infer it from failed reconcile.
        lease = journal.claim_run(run_id, owner_id="terminal-guard-proof", ttl_s=30)
        try:
            with pytest.raises(CleanupUnresolved):
                journal.transition_run(lease, expected=frozenset({RunStatus.RUNNING}),
                                       target=RunStatus.CANCELLED, event_kind="RunCancelled")
        finally:
            journal.release_run(lease)
        assert journal.run_state(run_id).status is RunStatus.RUNNING
