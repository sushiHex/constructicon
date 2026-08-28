"""The vertical slice under M2 semantics.

Graph -> validate -> ExecutionManifest -> activate -> claim -> FakeExecutor ->
checkpoint -> idempotent effect -> EffectReceipt -> terminal transition ->
resume/reproduce.

Two statements the fake path must demonstrate:
1. once validation returns, the walker decides nothing — every decision lives
   in the sealed manifest or a deterministic effect adapter;
2. once an effect returns a committed receipt, no replay, crash, retry, or
   promotion causes a second externally visible transition.
"""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.run import RunStatus
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import LEASE_TTL_S, FakeClock, InjectedCrash, pipeline_graph

INPUTS = {"issue": {"title": "retry loop is flaky"}}


async def test_the_vertical_slice(
    world: Constructicon,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    run_id = RunId("run-slice")
    result = await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["summary"] == {"text": "summary of fix the flaky retry loop"}
    assert result.outputs["announced"] == {"reference": "announce/1"}
    assert len(fake_executor.calls) == 1
    assert len(announce_effect.executions) == 1

    kinds = [event.kind for event in world._journal.events(run_id)]
    assert kinds[0] == "RunStarted"
    assert kinds[-1] == "RunSucceeded"
    assert "NodeStarted" in kinds and "NodeCompleted" in kinds
    assert "EffectCommitted" in kinds

    state = world._journal.run_state(run_id)
    assert state is not None and state.status is RunStatus.SUCCEEDED
    assert state.liveness == "not_applicable"
    assert state.owner_id is None  # the lease was released on the way out


async def test_resume_of_a_succeeded_run_returns_the_materialized_result(
    world: Constructicon,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    """Crash after the terminal commit, before the caller saw the result: the
    answer comes back from durable checkpoints alone — no claim, no re-walk,
    no new events, status untouched."""
    run_id = RunId("run-resume")
    first = await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)
    events_before = len(world._journal.events(run_id, limit=200))

    resumed = await world._resume_direct(run_id)
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.outputs == first.outputs
    assert len(fake_executor.calls) == 1  # nothing re-executed
    assert len(announce_effect.executions) == 1  # no second transition
    assert len(world._journal.events(run_id, limit=200)) == events_before


async def test_resume_after_crash_restores_checkpoints_and_never_repeats_effects(
    world: Constructicon,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """Die after the announce checkpoint committed; a later worker reclaims the
    expired lease, restores triage and announce byte-for-byte, and only
    summarize executes anew."""
    run_id = RunId("run-crash-resume")
    completions = 0

    def probe(name: str) -> None:
        nonlocal completions
        if name == "completion.after_commit":
            completions += 1
            if completions == 2:  # triage committed, announce committed, die
                raise InjectedCrash(name)

    journal.fault_probe = probe
    with pytest.raises(InjectedCrash):
        await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)
    journal.fault_probe = lambda name: None

    state = world._journal.run_state(run_id)
    assert state is not None and state.status is RunStatus.RUNNING
    assert state.liveness == "live"  # the dead owner's lease has not expired yet
    clock.advance(LEASE_TTL_S + 1)
    state = world._journal.run_state(run_id)
    assert state is not None and state.liveness == "lost"

    resumed = await world._resume_direct(run_id)
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.outputs["summary"] == {"text": "summary of fix the flaky retry loop"}
    assert len(fake_executor.calls) == 1  # triage restored, never recomputed
    assert len(announce_effect.executions) == 1  # no second external transition
    kinds = [event.kind for event in world._journal.events(run_id, limit=200)]
    assert "RunReclaimed" in kinds
    assert "NodeRestored" in kinds


async def test_reproduce_replays_the_sealed_world_without_new_effects(
    world: Constructicon,
    announce_effect: FakeAnnounceEffect,
) -> None:
    source = RunId("run-source")
    first = await world._start_direct(pipeline_graph(), INPUTS, run_id=source)

    reproduced = await world._reproduce_direct(source, new_run_id=RunId("run-reproduced"))
    assert reproduced.outputs == first.outputs
    # same manifest + same paths + same subjects -> same idempotency keys:
    # replaying history never doubles an external transition
    assert len(announce_effect.executions) == 1
    assert world._journal.run_manifest_hash(RunId("run-reproduced")) == (
        world._journal.run_manifest_hash(source)
    )
    kinds = [event.kind for event in world._journal.events(RunId("run-reproduced"), limit=200)]
    assert "EffectDeduplicated" in kinds


async def test_node_failure_is_contained_and_resume_completes_the_run(
    world: Constructicon,
    fake_executor: FakeExecutor,
) -> None:
    """A failing node marks the run FAILED at closure — it is execution state,
    never an exception out of the walker — and resume re-walks it."""
    run_id = RunId("run-failing")
    del fake_executor._script["triage"]  # deliberate fault: no scripted reply
    result = await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)
    assert result.status is RunStatus.FAILED
    assert any("no scripted reply" in error for error in result.failures.values())
    assert len(result.blocked) == 2  # announce and summarize never ran
    state = world._journal.run_state(run_id)
    assert state is not None and state.status is RunStatus.FAILED

    fake_executor._script["triage"] = {
        "title": "fix the flaky retry loop",
        "risk": "low",
    }
    resumed = await world._resume_direct(run_id)
    assert resumed.status is RunStatus.SUCCEEDED
    kinds = [event.kind for event in world._journal.events(run_id, limit=200)]
    assert "NodeFailed" in kinds and "NodeBlocked" in kinds and "RunResumed" in kinds


async def test_cancel_is_honored_at_the_node_boundary_and_never_restarts(
    world: Constructicon,
    fake_executor: FakeExecutor,
    journal: SqliteJournal,
) -> None:
    run_id = RunId("run-cancelled")

    def probe(name: str) -> None:
        if name == "completion.after_commit":  # after triage: request cancel
            world._request_cancel(run_id)

    journal.fault_probe = probe
    result = await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)
    journal.fault_probe = lambda name: None
    assert result.status is RunStatus.CANCELLED
    state = world._journal.run_state(run_id)
    assert state is not None and state.status is RunStatus.CANCELLED

    executor_calls = len(fake_executor.calls)
    resumed = await world._resume_direct(run_id)  # reports cancelled, never restarts
    assert resumed.status is RunStatus.CANCELLED
    assert resumed.outputs == {}
    assert len(fake_executor.calls) == executor_calls
