"""Real lease fences and cancellation delivery across deferred acquisition.

Barriers establish ordering; the fake ledger is not an OS containment proof.
"""

from __future__ import annotations

import asyncio

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.run import OwnershipLost, RunStatus
from constructicon.runtime.walker import RunResult
from tests.api.test_executor_admission import INPUTS, executor_system
from tests.conftest import LEASE_TTL_S
from tests.executorworld import FakeExecutorProvider, register_component


@pytest.mark.parametrize("control", ["ownership", "cancel"])
async def test_control_changed_during_materialization_prevents_invocation(
    journal,
    clock,
    monkeypatch,
    control,
):
    provider = FakeExecutorProvider()
    system = executor_system(journal, provider)
    system._walker._heartbeat_interval_s = 0.001
    graph = await register_component(system, journal)
    entered, finish, observed_loss = asyncio.Event(), asyncio.Event(), asyncio.Event()
    heartbeat = journal.heartbeat

    def observe_heartbeat(*args, **kwargs):
        try:
            return heartbeat(*args, **kwargs)
        except OwnershipLost:
            observed_loss.set()
            raise

    monkeypatch.setattr(journal, "heartbeat", observe_heartbeat)

    async def pause(handle):
        entered.set()
        await finish.wait()

    provider.before_materialize = pause
    run_id = RunId(f"materialization-control-{control}")
    running = asyncio.create_task(system._start_direct(graph, INPUTS, run_id=run_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        old = provider.handles[0]
        if control == "ownership":
            clock.advance(LEASE_TTL_S + 1)
            winner = journal.claim_run(run_id, owner_id="successor", ttl_s=LEASE_TTL_S)
            assert winner.epoch == old.context.run_lease.epoch + 1
            await asyncio.wait_for(observed_loss.wait(), 5)
        else:
            journal.request_cancel(run_id)
        finish.set()
        if control == "ownership":
            with pytest.raises(OwnershipLost):
                await running
        else:
            assert (await running).status is RunStatus.CANCELLED
        assert provider.executor.calls == []
        assert journal.checkpoint(run_id, old.context.path) is None
        assert not any(event.kind == "NodeCompleted" for event in journal.events(run_id))
        rows = journal.capability_leases(run_id)
        if control == "ownership":
            assert [(row.state, row.disposition) for row in rows] == [("active", None)]
            assert not old.closed and provider.ledger.resources == {old.key}
            assert journal.run_state(run_id).owner_id == "successor"
            journal.release_run(winner)
            successor = FakeExecutorProvider(ledger=provider.ledger)
            recovered = executor_system(journal, successor, owner="successor")
            assert (await recovered._resume_direct(run_id)).status is RunStatus.SUCCEEDED
            assert successor.reconciled == [old.key] and len(successor.executor.calls) == 1
        else:
            assert [(row.state, row.disposition) for row in rows] == [("closed", "discarded")]
        assert provider.ledger.resources == set()
    finally:
        finish.set()
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("cancellation", ["cancel", "abandon"])
@pytest.mark.parametrize("sibling", [False, True])
@pytest.mark.parametrize("checkpointed", [False, True])
async def test_repeated_cancellation_finishes_recorded_cleanup(
    journal,
    monkeypatch,
    cancellation,
    sibling,
    checkpointed,
):
    provider = FakeExecutorProvider()
    second = FakeExecutorProvider(ledger=provider.ledger)
    providers = {"complete-fake": provider, **({"second": second} if sibling else {})}
    system = Constructicon(
        journal=journal,
        owner_id="cancelled-worker",
        capabilities=providers,
        catalog={key: value.descriptor(key) for key, value in providers.items()},
    )
    graph = await register_component(
        system,
        journal,
        bindings={"executor": "complete-fake", **({"z": "second"} if sibling else {})},
    )
    entered, close_started, finish_close = asyncio.Event(), asyncio.Event(), asyncio.Event()
    close_calls, interrupted = [], []
    original_close = provider.close

    async def pause(handle):
        provider.ledger.allocate(handle.key)
        entered.set()
        await asyncio.Event().wait()

    async def blocked_close(acquisition, disposition):
        close_calls.append((acquisition.resource_ref, disposition))
        close_started.set()
        try:
            await finish_close.wait()
        except asyncio.CancelledError:
            interrupted.append(acquisition.resource_ref)
            raise
        return await original_close(acquisition, disposition)

    if not checkpointed:
        (second if sibling else provider).before_materialize = pause
    monkeypatch.setattr(provider, "close", blocked_close)
    run_id = RunId("repeated-materialization-cancellation")
    system._prepare_run(system.validate(graph, INPUTS), run_id=run_id, inputs=INPUTS)
    running = asyncio.create_task(system._run_prepared(run_id, cancellation=cancellation))
    try:
        if not checkpointed:
            await asyncio.wait_for(entered.wait(), 5)
            running.cancel()
        await asyncio.wait_for(close_started.wait(), 5)
        for _ in range(2):
            running.cancel()
            await asyncio.sleep(0)  # Deliver this cancellation, not a timing guess.
        finish_close.set()
        outcome = (await asyncio.gather(running, return_exceptions=True))[0]
        assert isinstance(outcome, asyncio.CancelledError)
        assert interrupted == []
        assert close_calls == [(provider.handles[0].key, "release" if checkpointed else "discard")]
        assert provider.ledger.resources == set()
        assert len(provider.executor.calls) == int(checkpointed) and second.executor.calls == []
        rows = journal.capability_leases(run_id)
        assert [(row.state, row.disposition) for row in rows] == [
            ("closed", "released" if checkpointed else "discarded") for _ in providers
        ]
        assert (
            journal.checkpoint(run_id, provider.handles[0].context.path) is not None
        ) is checkpointed
        state = journal.run_state(run_id)
        assert state.owner_id is None
        assert state.status is (
            RunStatus.CANCELLED if cancellation == "cancel" else RunStatus.RUNNING
        )
        assert sum(event.kind == "RunCancelled" for event in journal.events(run_id)) == (
            cancellation == "cancel"
        )
    finally:
        finish_close.set()
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("failure", ["provider", "ownership"])
async def test_cleanup_failure_is_not_laundered_into_cancellation(
    journal,
    clock,
    monkeypatch,
    failure,
):
    provider = FakeExecutorProvider()
    system = executor_system(journal, provider)
    graph = await register_component(system, journal)
    entered, closing, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_close = provider.close

    async def pause(handle):
        provider.ledger.allocate(handle.key)
        entered.set()
        await asyncio.Event().wait()

    async def fail_close(acquisition, disposition):
        closing.set()
        await finish.wait()
        if failure == "provider":
            raise RuntimeError("provider could not close")
        return await original_close(acquisition, disposition)

    provider.before_materialize = pause
    monkeypatch.setattr(provider, "close", fail_close)
    run_id = RunId("cleanup-failure-is-evidence")
    running = asyncio.create_task(system._start_direct(graph, INPUTS, run_id=run_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        running.cancel()
        await asyncio.wait_for(closing.wait(), 5)
        running.cancel()
        await asyncio.sleep(0)
        if failure == "ownership":
            clock.advance(LEASE_TTL_S + 1)
            winner = journal.claim_run(run_id, owner_id="cleanup-successor", ttl_s=LEASE_TTL_S)
        finish.set()
        # Queue the closer before the cancelled waiter. The failed cleanup is
        # already terminal when the waiter resumes, so its result must be read.
        running.cancel()
        outcome = (await asyncio.gather(running, return_exceptions=True))[0]
        if failure == "provider":
            assert isinstance(outcome, RunResult) and outcome.status is RunStatus.FAILED
            assert any("provider could not close" in reason for reason in outcome.failures.values())
            assert provider.ledger.resources == {provider.handles[0].key}
        else:
            assert isinstance(outcome, OwnershipLost)
            assert journal.run_state(run_id).owner_id == winner.owner_id
            journal.release_run(winner)
        assert [(row.state, row.disposition) for row in journal.capability_leases(run_id)] == [
            ("active", None)
        ]
        assert not any(event.kind == "RunCancelled" for event in journal.events(run_id))
        assert provider.executor.calls == []
        recovered_provider = FakeExecutorProvider(ledger=provider.ledger)
        recovered = executor_system(journal, recovered_provider, owner="cleanup-successor")
        assert (await recovered._resume_direct(run_id)).status is RunStatus.SUCCEEDED
        assert recovered_provider.reconciled == [provider.handles[0].key]
        assert provider.ledger.resources == set()
    finally:
        finish.set()
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)
