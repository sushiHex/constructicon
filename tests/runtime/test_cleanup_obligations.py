"""Cleanup failures retain recovery authority and release local custody."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import (
    TERMINAL_STATUS_EVENTS,
    CleanupUnresolved,
    OwnershipLost,
    RunStatus,
)
from constructicon.core.workspace import lease_id_for
from tests.api.test_executor_admission import INPUTS
from tests.conftest import LEASE_TTL_S, InjectedCrash
from tests.executorworld import register_component
from tests.run_worlds import create_test_run, start_test_run
from tests.runtime.test_ownership_loss_custody import RetainingProvider, World
from tests.substrate.journal.test_lease_projection import _recorded_lease


@pytest.fixture
def world(journal, clock):
    return World(journal=journal, clock=clock)


async def outcome(running):
    return (await asyncio.gather(running, return_exceptions=True))[0]


class EagerProvider(RetainingProvider):
    async def acquire(self, context):
        acquisition = await super().acquire(context)
        await self.custody.lock(acquisition.resource_ref).acquire()
        acquisition.resource.held = True
        return replace(acquisition, materialize=None)


@pytest.mark.parametrize("target", tuple(TERMINAL_STATUS_EVENTS))
def test_active_rows_refuse_every_terminal_transition(journal, target):
    run_id = RunId(f"cleanup-guard-{target}")
    create_test_run(journal, run_id)
    lease = start_test_run(journal, run_id, owner_id="owner")
    path = ExecutionPath(scope=ScopePath(segments=("cleanup", "node")))
    row = CapabilityLease(
        lease_id=lease_id_for(run_id, path, "resource"),
        acquisition_epoch=lease.epoch,
        run_id=run_id,
        binding_id="resource",
        path=path,
        state="active",
        resource_ref="owned",
    )
    journal.record_capability_lease(lease, row)
    baseline = journal.events(run_id)
    error = None
    try:
        journal.transition_run(
            lease, expected=frozenset({RunStatus.RUNNING}), target=target,
            event_kind=TERMINAL_STATUS_EVENTS[target],
        )
    except Exception as exc:
        error = exc
    assert isinstance(error, CleanupUnresolved), error
    assert journal.events(run_id) == baseline
    assert journal.run_state(run_id).status is RunStatus.RUNNING
    assert journal.run_state(run_id).owner_id == "owner"
    assert journal.append_event(lease, "AfterRefusal").seq == baseline[-1].seq + 1
    journal.transition_capability_lease(
        lease, lease_id=row.lease_id, acquisition_epoch=lease.epoch,
        expected=frozenset({"active"}), target="closed", disposition="discarded",
    )
    journal.transition_run(
        lease, expected=frozenset({RunStatus.RUNNING}), target=target,
        event_kind=TERMINAL_STATUS_EVENTS[target],
    )
    assert journal.run_state(run_id).status is target


def test_terminal_cleanup_guard_preserves_ownership_and_projection_fences(tmp_path, clock):
    journal, lease, row, database = _recorded_lease(tmp_path, clock)
    clock.advance(LEASE_TTL_S + 1)
    winner = journal.claim_run(lease.run_id, owner_id="successor", ttl_s=LEASE_TTL_S)
    error = None
    try:
        journal.transition_run(
            lease, expected=frozenset({RunStatus.RUNNING}), target=RunStatus.SUCCEEDED,
            event_kind="RunSucceeded",
        )
    except Exception as exc:
        error = exc
    assert isinstance(error, OwnershipLost), error
    assert journal.run_state(lease.run_id).owner_id == winner.owner_id
    create_test_run(journal, RunId("damaged-owner"))
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE capability_leases SET run_id = 'damaged-owner' WHERE lease_id = ?",
            (row.lease_id,),
        )
    error = None
    try:
        journal.transition_run(
            winner, expected=frozenset({RunStatus.RUNNING}), target=RunStatus.SUCCEEDED,
            event_kind="RunSucceeded",
        )
    except Exception as exc:
        error = exc
    assert isinstance(error, JournalDamaged), error
    assert journal.run_state(lease.run_id).status is RunStatus.RUNNING


@pytest.mark.parametrize("grouped", [False, True], ids=["direct", "grouped"])
async def test_hard_death_during_close_retains_crash_semantics(world, grouped):
    provider = world.provider("retaining")
    run_id = RunId("hard-death-in-close")
    death = InjectedCrash("controller died")
    crash = BaseExceptionGroup("hard death", [death]) if grouped else death

    async def die(handle):
        raise crash

    provider.before_close = die
    result = await outcome(await world.start(run_id, {"executor": "retaining"}))
    assert result is crash
    assert world.journal.run_state(run_id).owner_id == "loser"
    assert world.rows(run_id) == [("active", None)]
    assert provider.relinquished == []
    assert world.held() == [True]
    provider.handles[0].release()


@pytest.mark.parametrize("grouped", [False, True], ids=["direct", "grouped"])
@pytest.mark.parametrize("lost", [False, True], ids=["normal", "lost"])
async def test_relinquishment_hard_death_preserves_the_known_loss_boundary(world, grouped, lost):
    provider, sibling = world.provider("retaining"), world.provider("sibling")
    run_id = RunId(f"relinquish-death-{lost}-{grouped}")
    death = InjectedCrash("release crashed")
    crash = BaseExceptionGroup("release hard death", [death]) if grouped else death

    async def fail_release(handle):
        raise crash

    provider.before_relinquish = fail_release
    if lost:
        entered, finish = asyncio.Event(), asyncio.Event()

        async def lose(handle):
            entered.set()
            await finish.wait()
            handle.context.check_control()

        provider.before_execute = lose
    else:
        async def fail_close(handle):
            raise OSError("close failed")

        provider.before_close = fail_close
    running = await world.start(run_id, {"executor": "retaining", "z": "sibling"})
    if lost:
        await entered.wait()
        world.lose(run_id)
        finish.set()
    result = await outcome(running)
    if lost:
        assert isinstance(result, OwnershipLost), result
        assert result.__cause__ is death
        assert sibling.relinquished == [sibling.handles[0].key]
        assert world.journal.run_state(run_id).owner_id == "successor"
        assert world.held() == [True, False]
    else:
        assert result is crash, result
        assert sibling.closes == [] and sibling.relinquished == []
        assert world.journal.run_state(run_id).owner_id == "loser"
        assert world.held() == [True, True]
    for resource in [provider, sibling]:
        resource.handles[0].release()


@pytest.mark.parametrize("node_fails", [False, True], ids=["checkpointed", "node-failed"])
async def test_failed_close_escapes_its_site_and_releases_every_sibling(world, node_fails):
    run_id = RunId(f"failed-close-{node_fails}")
    provider, sibling = world.provider("retaining"), world.provider("sibling")
    close_error = OSError("close failed")
    node_error = ValueError("invocation failed")

    async def fail_close(handle):
        raise close_error

    async def fail_node(handle):
        raise node_error

    provider.before_close = fail_close
    if node_fails:
        provider.before_execute = fail_node
    running = await world.start(run_id, {"executor": "retaining", "z": "sibling"})
    result = await outcome(running)
    assert result is close_error, result
    assert sibling.closes == ["discard" if node_fails else "release"]
    assert provider.relinquished == [provider.handles[0].key]
    assert sibling.relinquished == []
    assert world.held() == [False, False]
    assert sorted(world.rows(run_id)) == [
        ("active", None), ("closed", "discarded" if node_fails else "released"),
    ]
    state = world.journal.run_state(run_id)
    assert state.status is RunStatus.RUNNING and state.owner_id is None
    events = world.journal.events(run_id)
    failed = [event for event in events if event.kind == "NodeFailed"]
    assert len(failed) == int(node_fails)
    if node_fails:
        assert failed[0].payload == {"error": str(node_error), "error_type": "ValueError"}
        assert result.__cause__ is node_error
    assert not any(event.kind in TERMINAL_STATUS_EVENTS.values() for event in events)
    winner = world.lose(run_id)
    provider.before_close = None
    provider.before_execute = None
    await world.succeed(run_id, winner)
    assert len(provider.executor.calls) == int(not node_fails)


@pytest.mark.parametrize("heartbeat_fails", ["lost", "error"])
async def test_settle_heartbeat_failure_releases_unenrolled_custody(
    world, monkeypatch, heartbeat_fails,
):
    provider = EagerProvider(ledger=world.ledger, custody=world.custody)
    world.providers["retaining"] = provider
    journal = world.journal
    record = journal.record_capability_lease
    failure = (
        OwnershipLost("settle lost") if heartbeat_fails == "lost" else OSError("heartbeat failed")
    )

    def answer_lost(*args, **kwargs):
        record(*args, **kwargs)
        raise ConnectionError("record answer lost")

    def heartbeat(*args, **kwargs):
        raise failure

    monkeypatch.setattr(journal, "record_capability_lease", answer_lost)
    monkeypatch.setattr(journal, "heartbeat", heartbeat)
    run_id = RunId(f"settle-custody-{heartbeat_fails}")
    result = await outcome(await world.start(run_id, {"executor": "retaining"}))
    assert provider.relinquished == [provider.handles[0].key]
    assert world.held() == [False]
    assert provider.closes == []
    assert world.rows(run_id) == [("active", None)]
    assert result is failure, result


@pytest.mark.parametrize("record_lost", [False, True], ids=["record-error", "record-lost"])
async def test_unrecorded_close_loss_relinquishes_eager_custody(world, monkeypatch, record_lost):
    provider = EagerProvider(ledger=world.ledger, custody=world.custody)
    world.providers["retaining"] = provider
    loss = OwnershipLost("unrecorded close lost")
    record_error = OwnershipLost("record lost") if record_lost else ConnectionError("no row")

    def refuse_record(*args):
        raise record_error

    async def fail_close(handle):
        raise loss

    monkeypatch.setattr(world.journal, "record_capability_lease", refuse_record)
    provider.before_close = fail_close
    run_id = RunId("unrecorded-close-lost")
    result = await outcome(await world.start(run_id, {"executor": "retaining"}))
    assert result is (record_error if record_lost else loss)
    if record_lost:
        assert result.__cause__ is loss
    assert provider.relinquished == [provider.handles[0].key]
    assert world.held() == [False]
    assert world.rows(run_id) == []


@pytest.mark.parametrize("grouped", [False, True], ids=["direct", "grouped"])
async def test_unrecorded_known_loss_outranks_relinquishment_hard_death(
    world, monkeypatch, grouped,
):
    provider = EagerProvider(ledger=world.ledger, custody=world.custody)
    world.providers["retaining"] = provider
    loss, close_error = OwnershipLost("record lost"), OSError("close failed")
    death = InjectedCrash("release crashed")

    def refuse_record(*args):
        raise loss

    async def fail_close(handle):
        raise close_error

    async def fail_release(handle):
        raise BaseExceptionGroup("release died", [death]) if grouped else death

    monkeypatch.setattr(world.journal, "record_capability_lease", refuse_record)
    provider.before_close, provider.before_relinquish = fail_close, fail_release
    run_id = RunId(f"unrecorded-loss-crash-{grouped}")
    result = await outcome(await world.start(run_id, {"executor": "retaining"}))
    assert result is loss
    assert result.__cause__.exceptions == (close_error, death)
    assert world.rows(run_id) == []
    provider.handles[0].release()


@pytest.mark.parametrize("recorded", [False, True], ids=["unrecorded", "settled"])
@pytest.mark.parametrize("cancellation", ["cancel", "abandon"])
async def test_unenrolled_release_retains_observed_cancellation(
    world, monkeypatch, recorded, cancellation,
):
    provider = EagerProvider(ledger=world.ledger, custody=world.custody)
    world.providers["retaining"] = provider
    record = world.journal.record_capability_lease
    releasing, finish = asyncio.Event(), asyncio.Event()
    failure = OSError("unenrolled cleanup failed")

    def fail_record(*args):
        if recorded:
            record(*args)
        raise ConnectionError("record answer lost")

    def fail_heartbeat(*args, **kwargs):
        raise failure

    async def fail_close(handle):
        raise failure

    async def blocked_release(handle):
        releasing.set()
        await finish.wait()
        handle.release()

    monkeypatch.setattr(world.journal, "record_capability_lease", fail_record)
    if recorded:
        monkeypatch.setattr(world.journal, "heartbeat", fail_heartbeat)
    else:
        provider.before_close = fail_close
    provider.before_relinquish = blocked_release
    run_id = RunId(f"unenrolled-cancel-{recorded}-{cancellation}")
    system = world.system("owner", {"retaining": provider})
    graph = await register_component(system, world.journal, bindings={"executor": "retaining"})
    system._prepare_run(system.validate(graph, INPUTS), run_id=run_id, inputs=INPUTS)
    running = asyncio.create_task(system._run_prepared(run_id, cancellation=cancellation))
    await releasing.wait()
    running.cancel()
    await asyncio.sleep(0)
    finish.set()
    result = await outcome(running)
    assert result is failure
    assert world.journal.cancel_requested(run_id) is (cancellation == "cancel")
    assert world.journal.run_state(run_id).owner_id is None
    assert world.held() == [False]
    assert world.rows(run_id) == ([("active", None)] if recorded else [])


@pytest.mark.parametrize("cancellation", ["cancel", "abandon"])
async def test_asyncio_cancel_with_unresolved_rows_releases_and_records_only_user_cancel(
    world, monkeypatch, cancellation,
):
    run_id = RunId(f"cancel-unresolved-{cancellation}")
    provider = world.provider("retaining")
    entered = asyncio.Event()

    async def wait(handle):
        entered.set()
        await asyncio.Event().wait()

    async def unresolved(*args, **kwargs):
        pass

    provider.before_execute = wait
    system = world.system("owner", {"retaining": provider})
    graph = await register_component(system, world.journal, bindings={"executor": "retaining"})
    system._prepare_run(system.validate(graph, INPUTS), run_id=run_id, inputs=INPUTS)
    monkeypatch.setattr(system._walker, "_close_acquired", unresolved)
    running = asyncio.create_task(system._run_prepared(run_id, cancellation=cancellation))
    await entered.wait()
    running.cancel()
    result = await outcome(running)
    state = world.journal.run_state(run_id)
    assert state.status is RunStatus.RUNNING and state.owner_id is None
    assert world.journal.cancel_requested(run_id) is (cancellation == "cancel")
    expected = CleanupUnresolved if cancellation == "cancel" else asyncio.CancelledError
    assert isinstance(result, expected)
    assert not any(event.kind == "RunCancelled" for event in world.journal.events(run_id))
    provider.handles[0].release()


@pytest.mark.parametrize("observation", ["latched", "fenced", "failed"])
async def test_failed_close_observes_ownership_before_any_later_close(
    world, monkeypatch, observation,
):
    run_id = RunId(f"failed-close-observation-{observation}")
    provider, sibling = world.provider("retaining"), world.provider("sibling")
    closing, finish = asyncio.Event(), asyncio.Event()
    close_error = OSError("physical close failed")
    release_error = RuntimeError("release failed")
    observation_error = ConnectionError("ownership could not be observed")

    async def blocked_close(handle):
        closing.set()
        await finish.wait()
        raise close_error

    async def failed_release(handle):
        handle.release()
        raise release_error

    provider.before_close = blocked_close
    provider.before_relinquish = failed_release
    if observation != "latched":
        from constructicon.runtime.walker import Walker

        async def paused_heartbeat(*args):
            await asyncio.Event().wait()

        monkeypatch.setattr(Walker, "_heartbeat_loop", paused_heartbeat)
    running = await world.start(run_id, {"executor": "retaining", "z": "sibling"})
    await closing.wait()
    loss = observation != "failed"
    if loss:
        winner = world.lose(run_id)
        if observation == "latched":
            await world.latched.wait()
    else:
        def refuse_observation(*args, **kwargs):
            raise observation_error

        monkeypatch.setattr(world.journal, "heartbeat", refuse_observation)
    finish.set()
    result = await outcome(running)
    assert isinstance(result, OwnershipLost if loss else BaseExceptionGroup), result
    errors = result.__cause__.exceptions if loss else result.exceptions
    assert list(errors) == [close_error, release_error, *([] if loss else [observation_error])]
    assert sibling.closes == []
    assert sibling.relinquished == [sibling.handles[0].key]
    assert world.held() == [False, False]
    assert world.rows(run_id) == [("active", None), ("active", None)]
    assert world.journal.run_state(run_id).owner_id == (winner.owner_id if loss else None)


@pytest.mark.parametrize("release_crash", [False, True], ids=["released", "release-crash"])
async def test_close_batch_observes_latched_loss_before_its_first_close(world, release_crash):
    provider = world.provider("retaining")
    entered, finish = asyncio.Event(), asyncio.Event()

    async def wait(handle):
        entered.set()
        await finish.wait()
        handle.context.check_control()

    provider.before_execute = wait
    death = InjectedCrash("known-loss release crashed")
    if release_crash:
        async def fail_release(handle):
            raise BaseExceptionGroup("release died", [death])

        provider.before_relinquish = fail_release
    system = world.system("loser", {"retaining": provider})
    graph = await register_component(system, world.journal, bindings={"executor": "retaining"})
    run_id = RunId("close-batch-latched")
    running = asyncio.create_task(system._start_direct(graph, INPUTS, run_id=run_id))
    await entered.wait()
    lease = provider.handles[0].context.run_lease
    winner = world.lose(run_id)
    loss = OwnershipLost("already latched")
    try:
        closing = asyncio.create_task(system._walker._close_acquired(
            lease, [(provider, provider.acquisitions[0])], "discard", lost=[loss],
        ))
        assert await outcome(closing) is loss
        assert provider.closes == []
        assert provider.relinquished == ([] if release_crash else [provider.handles[0].key])
        assert world.held() == [release_crash]
        if release_crash:
            assert loss.__cause__ is death
        assert world.rows(run_id) == [("active", None)]
        assert world.journal.run_state(run_id).owner_id == winner.owner_id
    finally:
        finish.set()
        await outcome(running)
        provider.handles[0].release()


async def test_shared_release_errors_are_deduplicated_without_walking_context(world):
    run_id = RunId("shared-release-error")
    provider = world.provider("retaining")
    provider_error = OSError("provider close failed")
    provider_error.__context__ = ValueError("not an invocation error")
    release_error = RuntimeError("one release failed")

    async def close(handle):
        raise ExceptionGroup("close", [provider_error, release_error])

    async def relinquish(handle):
        handle.release()
        raise ExceptionGroup("same cached release", [release_error])

    provider.before_close = close
    provider.before_relinquish = relinquish
    result = await outcome(await world.start(run_id, {"executor": "retaining"}))
    assert isinstance(result, ExceptionGroup), result
    assert result.exceptions == (provider_error, release_error)
    assert world.held() == [False]
    assert not any(event.kind == "NodeFailed" for event in world.journal.events(run_id))


@pytest.mark.parametrize("diagnostic", ["error", "lost", "death"])
async def test_failed_node_diagnostic_preserves_cleanup_failure_and_cancellation(
    world, monkeypatch, diagnostic,
):
    provider = world.provider("retaining")
    run_id = RunId(f"cleanup-diagnostic-{diagnostic}")
    close_started, finish = asyncio.Event(), asyncio.Event()
    close_error, node_error = OSError("close failed"), ValueError("node failed")
    diagnostic_error = {
        "error": ConnectionError("diagnostic failed"),
        "lost": OwnershipLost("diagnostic lost"),
        "death": InjectedCrash("diagnostic crash"),
    }[diagnostic]
    append = world.journal.append_event

    async def fail_node(handle):
        raise node_error

    async def fail_close(handle):
        close_started.set()
        await finish.wait()
        raise close_error

    def fail_diagnostic(*args, **kwargs):
        if args[1] == "NodeFailed":
            if diagnostic == "lost":
                world.lose(run_id)
            raise diagnostic_error
        return append(*args, **kwargs)

    provider.before_execute, provider.before_close = fail_node, fail_close
    monkeypatch.setattr(world.journal, "append_event", fail_diagnostic)
    running = await world.start(run_id, {"executor": "retaining"})
    await close_started.wait()
    running.cancel()
    await asyncio.sleep(0)
    finish.set()
    result = await outcome(running)
    if diagnostic == "error":
        assert isinstance(result, ExceptionGroup), result
        assert result.exceptions == (close_error, diagnostic_error)
        assert result.__cause__ is node_error
        assert world.journal.cancel_requested(run_id)
    else:
        assert result is diagnostic_error
        if diagnostic == "lost":
            assert result.__cause__ is close_error
        assert not world.journal.cancel_requested(run_id)
    assert world.journal.run_state(run_id).owner_id == {
        "error": None, "lost": "successor", "death": "loser",
    }[diagnostic]
    assert world.held() == [False]
    assert world.rows(run_id) == [("active", None)]
    assert not any(event.kind == "NodeFailed" for event in world.journal.events(run_id))


@pytest.mark.parametrize("cancellation", ["cancel", "abandon"])
@pytest.mark.parametrize("checkpointed", [False, True], ids=["invoking", "checkpointed"])
async def test_failed_close_preserves_explicit_cancellation_intent(
    world, cancellation, checkpointed,
):
    provider = world.provider("retaining")
    run_id = RunId(f"failed-close-cancel-{cancellation}-{checkpointed}")
    entered, closing, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
    failure = OSError("cancelled close failed")

    async def wait(handle):
        entered.set()
        await asyncio.Event().wait()

    async def close(handle):
        closing.set()
        await finish.wait()
        raise failure

    if not checkpointed:
        provider.before_execute = wait
    provider.before_close = close
    system = world.system("owner", {"retaining": provider})
    graph = await register_component(system, world.journal, bindings={"executor": "retaining"})
    system._prepare_run(system.validate(graph, INPUTS), run_id=run_id, inputs=INPUTS)
    running = asyncio.create_task(system._run_prepared(run_id, cancellation=cancellation))
    if not checkpointed:
        await entered.wait()
        running.cancel()
    await closing.wait()
    running.cancel()
    await asyncio.sleep(0)
    finish.set()
    result = await outcome(running)
    assert result is failure, result
    assert isinstance(result.__cause__, asyncio.CancelledError)
    assert world.journal.cancel_requested(run_id) is (cancellation == "cancel")
    assert world.journal.run_state(run_id).status is RunStatus.RUNNING
    assert world.journal.run_state(run_id).owner_id is None
    assert world.held() == [False]
    assert world.rows(run_id) == [("active", None)]
    events = world.journal.events(run_id)
    assert not any(event.kind == "NodeFailed" for event in events)
    assert not any(event.kind in TERMINAL_STATUS_EVENTS.values() for event in events)
    checkpoint = world.journal.checkpoint(run_id, provider.handles[0].context.path)
    assert (checkpoint is not None) is checkpointed


async def test_failed_cancel_request_still_stops_heartbeat_and_releases(world, monkeypatch):
    from constructicon.runtime.walker import Walker

    provider = world.provider("retaining")
    run_id = RunId("cancel-request-failed")
    entered, stopped = asyncio.Event(), asyncio.Event()
    failure = OSError("cancel request failed")
    async def tracked_heartbeat(*args):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def wait(handle):
        entered.set()
        await asyncio.Event().wait()

    def refuse_request(*args, **kwargs):
        raise failure

    provider.before_execute = wait
    monkeypatch.setattr(Walker, "_heartbeat_loop", tracked_heartbeat)
    monkeypatch.setattr(world.journal, "request_cancel", refuse_request)
    running = await world.start(run_id, {"executor": "retaining"})
    await entered.wait()
    running.cancel()
    result = await outcome(running)
    assert result is failure, result
    assert isinstance(result.__cause__, asyncio.CancelledError)
    assert stopped.is_set()
    assert world.journal.run_state(run_id).owner_id is None
    assert world.journal.run_state(run_id).status is RunStatus.RUNNING
    assert not world.journal.cancel_requested(run_id)
    assert world.held() == [False]


@pytest.mark.parametrize("lose", [False, True], ids=["success", "ownership-lost"])
async def test_background_heartbeat_failure_releases_without_replacing_loss(
    world, monkeypatch, lose,
):
    from constructicon.runtime.walker import Walker

    provider = world.provider("retaining")
    run_id = RunId(f"heartbeat-stop-failure-{lose}")
    entered, finish, heartbeat_failed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    failure = OSError("background heartbeat failed")

    async def failed_heartbeat(*args):
        await entered.wait()
        heartbeat_failed.set()
        raise failure

    async def wait(handle):
        entered.set()
        await finish.wait()

    provider.before_execute = wait
    monkeypatch.setattr(Walker, "_heartbeat_loop", failed_heartbeat)
    running = await world.start(run_id, {"executor": "retaining"})
    await heartbeat_failed.wait()
    if lose:
        winner = world.lose(run_id)
    finish.set()
    result = await outcome(running)
    assert world.held() == [False]
    if lose:
        assert isinstance(result, OwnershipLost), result
        assert "OSError: background heartbeat failed" in result.__notes__[0]
        assert world.journal.run_state(run_id).owner_id == winner.owner_id
    else:
        assert result is failure, result
        assert world.journal.run_state(run_id).status is RunStatus.SUCCEEDED
        assert world.journal.run_state(run_id).owner_id is None


async def test_cancel_during_unfinished_acquire_cannot_cancel_a_successor(world, monkeypatch):
    from constructicon.runtime.walker import Walker

    provider = world.provider("retaining")
    entered = asyncio.Event()

    async def blocked_acquire(context):
        entered.set()
        await asyncio.Event().wait()

    async def paused_heartbeat(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(provider, "acquire", blocked_acquire)
    monkeypatch.setattr(Walker, "_heartbeat_loop", paused_heartbeat)
    run_id = RunId("cancel-unfinished-acquire-successor")
    running = await world.start(run_id, {"executor": "retaining"})
    await entered.wait()
    winner = world.lose(run_id)
    assert not world.journal.cancel_requested(run_id)
    running.cancel()
    result = await outcome(running)
    assert isinstance(result, OwnershipLost), result
    assert not world.journal.cancel_requested(run_id)
    assert world.journal.run_state(run_id).owner_id == winner.owner_id
    assert provider.handles == [] and world.rows(run_id) == []


async def test_cancel_request_hard_death_stops_the_heartbeat_without_releasing(world, monkeypatch):
    from constructicon.runtime.walker import Walker

    provider = world.provider("retaining")
    entered, stopped = asyncio.Event(), asyncio.Event()
    heartbeats = []
    crash = InjectedCrash("cancel request crashed")

    async def tracked_heartbeat(*args):
        heartbeats.append(asyncio.current_task())
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def wait(handle):
        entered.set()
        await asyncio.Event().wait()

    def fail_request(*args, **kwargs):
        raise crash

    provider.before_execute = wait
    monkeypatch.setattr(Walker, "_heartbeat_loop", tracked_heartbeat)
    monkeypatch.setattr(world.journal, "request_cancel", fail_request)
    run_id = RunId("cancel-request-hard-death")
    running = await world.start(run_id, {"executor": "retaining"})
    await entered.wait()
    running.cancel()
    try:
        assert await outcome(running) is crash
        assert stopped.is_set()
        assert heartbeats[0].done()
        assert world.journal.run_state(run_id).owner_id == "loser"
    finally:
        for heartbeat in heartbeats:
            heartbeat.cancel()
        await asyncio.gather(*heartbeats, return_exceptions=True)


@pytest.mark.parametrize("restored", [False, True], ids=["persistent", "restored"])
async def test_second_settle_observation_failure_relinquishes_earlier_siblings(
    world, monkeypatch, restored,
):
    from constructicon.runtime.walker import Walker

    first = EagerProvider(ledger=world.ledger, custody=world.custody)
    second = EagerProvider(ledger=world.ledger, custody=world.custody)
    world.providers.update(first=first, second=second)
    record = world.journal.record_capability_lease
    calls = 0
    observations = 0
    observation = OSError("ownership observation failed")
    heartbeat = world.journal.heartbeat

    def lose_second_answer(*args):
        nonlocal calls
        record(*args)
        calls += 1
        if calls == 2:
            raise ConnectionError("second answer lost")

    def fail_heartbeat(*args, **kwargs):
        nonlocal observations
        observations += 1
        if observations == 1 or not restored:
            raise observation
        return heartbeat(*args, **kwargs)

    async def paused_heartbeat(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(world.journal, "record_capability_lease", lose_second_answer)
    monkeypatch.setattr(world.journal, "heartbeat", fail_heartbeat)
    monkeypatch.setattr(Walker, "_heartbeat_loop", paused_heartbeat)
    run_id = RunId("second-settle-observation-failed")
    result = await outcome(await world.start(run_id, {"executor": "first", "z": "second"}))
    assert result is observation, result
    assert calls == 2
    assert first.closes == (["discard"] if restored else []) and second.closes == []
    assert first.relinquished == ([] if restored else [first.handles[0].key])
    assert second.relinquished == [second.handles[0].key]
    assert world.held() == [False, False]
    assert world.rows(run_id) == [
        ("closed", "discarded") if restored else ("active", None), ("active", None),
    ]
    assert observations >= 2
    assert world.journal.run_state(run_id).owner_id is None


async def test_row_write_failure_after_close_keeps_checkpoint_and_recovery_row(world, monkeypatch):
    provider = world.provider("retaining")
    failure = OSError("closed row write failed")

    def fail_transition(*args, **kwargs):
        raise failure

    monkeypatch.setattr(world.journal, "transition_capability_lease", fail_transition)
    run_id = RunId("physically-closed-row-write-failed")
    result = await outcome(await world.start(run_id, {"executor": "retaining"}))
    assert result is failure
    assert provider.closes == ["release"]
    assert provider.relinquished == [provider.handles[0].key]
    assert world.held() == [False]
    assert world.rows(run_id) == [("active", None)]
    assert world.journal.checkpoint(run_id, provider.handles[0].context.path) is not None
    assert world.journal.run_state(run_id).owner_id is None
    assert not any(event.kind == "NodeFailed" for event in world.journal.events(run_id))


@pytest.mark.parametrize("fence", ["external", "current", "owner", "epoch", "run-id", "stale"])
def test_cancel_request_optional_lease_fence_preserves_authority_and_sequence(
    journal, clock, fence,
):
    run_id, other = RunId("fenced-cancel"), RunId("other-fenced-cancel")
    create_test_run(journal, run_id)
    current = start_test_run(journal, run_id, owner_id="owner")
    create_test_run(journal, other)
    start_test_run(journal, other, owner_id="owner")
    selected, supplied = run_id, current
    if fence == "owner":
        supplied = current.model_copy(update={"owner_id": "not-owner"})
    elif fence == "epoch":
        supplied = current.model_copy(update={"epoch": current.epoch + 1})
    elif fence == "run-id":
        selected = other
    elif fence == "stale":
        clock.advance(LEASE_TTL_S + 1)
        current = journal.claim_run(run_id, owner_id="successor", ttl_s=LEASE_TTL_S)
    baseline = journal.events(run_id)
    error = None
    try:
        if fence == "external":
            journal.request_cancel(selected)
        else:
            journal.request_cancel(selected, lease=supplied)
    except Exception as exc:
        error = exc
    if fence in {"external", "current"}:
        assert error is None, error
        assert journal.cancel_requested(run_id)
    else:
        expected = ContractViolation if fence == "run-id" else OwnershipLost
        assert isinstance(error, expected), error
        assert not journal.cancel_requested(run_id)
    assert not journal.cancel_requested(other)
    assert journal.events(run_id) == baseline
    assert journal.append_event(current, "AfterCancelRequest").seq == baseline[-1].seq + 1


@pytest.mark.parametrize("cleanup_fails", [False, True], ids=["closed", "close-failed"])
async def test_successor_interposed_at_cancel_write_is_not_cancelled(
    world, monkeypatch, cleanup_fails,
):
    from constructicon.runtime.walker import Walker

    provider = world.provider("retaining")
    entered = asyncio.Event()
    request = world.journal.request_cancel
    winners = []
    run_id = RunId("interposed-cancel-successor")

    async def wait(handle):
        entered.set()
        await asyncio.Event().wait()

    async def paused_heartbeat(*args):
        await asyncio.Event().wait()

    def interpose_successor(requested, **kwargs):
        winners.append(world.lose(run_id))
        request(requested, **kwargs)

    provider.before_execute = wait
    if cleanup_fails:
        async def fail_close(handle):
            raise OSError("close failed before cancellation write")

        provider.before_close = fail_close
    monkeypatch.setattr(Walker, "_heartbeat_loop", paused_heartbeat)
    monkeypatch.setattr(world.journal, "request_cancel", interpose_successor)
    running = await world.start(run_id, {"executor": "retaining"})
    await entered.wait()
    running.cancel()
    result = await outcome(running)
    assert isinstance(result, OwnershipLost), result
    assert len(winners) == 1
    assert world.journal.run_state(run_id).owner_id == winners[0].owner_id
    assert not world.journal.cancel_requested(run_id)
    assert world.held() == [False]


async def test_loss_latched_while_stopping_heartbeat_skips_cancellation_write(world, monkeypatch):
    from constructicon.runtime.walker import Walker

    provider = world.provider("retaining")
    entered = asyncio.Event()
    loss = OwnershipLost("loss latched during heartbeat join")
    requests = []
    run_id = RunId("cancel-heartbeat-join-lost")
    request = world.journal.request_cancel

    async def blocked_acquire(context):
        entered.set()
        await asyncio.Event().wait()

    async def latch_on_stop(self, lease, lost):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            world.lose(run_id)
            lost.append(loss)

    def tracked_request(*args, **kwargs):
        requests.append(args)
        request(*args, **kwargs)

    monkeypatch.setattr(provider, "acquire", blocked_acquire)
    monkeypatch.setattr(Walker, "_heartbeat_loop", latch_on_stop)
    monkeypatch.setattr(world.journal, "request_cancel", tracked_request)
    running = await world.start(run_id, {"executor": "retaining"})
    await entered.wait()
    running.cancel()
    assert await outcome(running) is loss
    assert requests == []
    assert not world.journal.cancel_requested(run_id)
    assert world.journal.run_state(run_id).owner_id == "successor"


async def test_last_failed_close_observes_successor_without_latched_heartbeat(world, monkeypatch):
    from constructicon.runtime.walker import Walker

    provider = world.provider("retaining")
    closing, finish = asyncio.Event(), asyncio.Event()
    failure = OSError("last close failed")

    async def blocked_close(handle):
        closing.set()
        await finish.wait()
        raise failure

    async def paused_heartbeat(*args):
        await asyncio.Event().wait()

    provider.before_close = blocked_close
    monkeypatch.setattr(Walker, "_heartbeat_loop", paused_heartbeat)
    run_id = RunId("last-close-successor")
    running = await world.start(run_id, {"executor": "retaining"})
    await closing.wait()
    winner = world.lose(run_id)
    finish.set()
    result = await outcome(running)
    assert isinstance(result, OwnershipLost), result
    assert result.__cause__ is failure
    assert world.journal.run_state(run_id).owner_id == winner.owner_id
    assert world.rows(run_id) == [("active", None)]
    assert world.held() == [False]
