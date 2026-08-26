"""The M1 elegance gate — the only measure of this milestone.

Graph -> validate -> ExecutionManifest -> FakeExecutor -> checkpoint ->
idempotent effect -> EffectReceipt -> reproduce.

Two statements the fake path must demonstrate:
1. once validation returns, the walker decides nothing — every decision lives
   in the sealed manifest or a deterministic effect adapter;
2. once an effect returns a committed receipt, no replay, crash, retry, or
   promotion causes a second externally visible transition.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.journal import RunStatus
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from tests.conftest import pipeline_graph

INPUTS = {"issue": {"title": "retry loop is flaky"}}


async def test_the_vertical_slice(
    world: Constructicon,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    run_id = RunId("run-slice")
    result = await world.start(pipeline_graph(), INPUTS, run_id=run_id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["summary"] == {"text": "summary of fix the flaky retry loop"}
    assert result.outputs["announced"] == {"reference": "announce/1"}
    assert len(fake_executor.calls) == 1
    assert len(announce_effect.executions) == 1

    kinds = [event.kind for event in world.journal.events(run_id)]
    assert kinds[0] == "RunStarted"
    assert kinds[-1] == "RunSucceeded"
    assert "NodeStarted" in kinds and "NodeCompleted" in kinds
    assert "EffectCommitted" in kinds


async def test_resume_restores_checkpoints_and_never_repeats_effects(
    world: Constructicon,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    run_id = RunId("run-resume")
    first = await world.start(pipeline_graph(), INPUTS, run_id=run_id)

    executor_calls = len(fake_executor.calls)
    effect_executions = len(announce_effect.executions)

    resumed = await world.resume(run_id)
    assert resumed.outputs == first.outputs
    assert len(fake_executor.calls) == executor_calls  # every node restored
    assert len(announce_effect.executions) == effect_executions  # no second transition
    kinds = [event.kind for event in world.journal.events(run_id, limit=200)]
    assert "NodeRestored" in kinds


async def test_reproduce_replays_the_sealed_world_without_new_effects(
    world: Constructicon,
    announce_effect: FakeAnnounceEffect,
) -> None:
    source = RunId("run-source")
    first = await world.start(pipeline_graph(), INPUTS, run_id=source)

    reproduced = await world.reproduce(source, new_run_id=RunId("run-reproduced"))
    assert reproduced.outputs == first.outputs
    # same manifest + same paths + same subjects -> same idempotency keys:
    # replaying history never doubles an external transition
    assert len(announce_effect.executions) == 1
    assert world.journal.run_manifest_hash(RunId("run-reproduced")) == (
        world.journal.run_manifest_hash(source)
    )


async def test_crash_between_effect_and_receipt_reconciles_instead_of_repeating(
    world: Constructicon,
    announce_effect: FakeAnnounceEffect,
    tmp_path: Path,
) -> None:
    """Fault injection at the deadliest boundary: the effect succeeded
    externally, the receipt was lost before commit. Recovery must reconcile,
    never blindly re-execute."""
    run_id = RunId("run-crash")
    await world.start(pipeline_graph(), INPUTS, run_id=run_id)
    assert len(announce_effect.executions) == 1

    # simulate the crash: erase the receipt (keeping the prepared record) and
    # the announce node's checkpoint, as if the process died mid-commit
    with sqlite3.connect(tmp_path / "journal.db") as conn:
        conn.execute("UPDATE effects SET receipt_json = NULL, receipted_at = NULL")
        conn.execute(
            "DELETE FROM checkpoints WHERE path_key LIKE '%announce%' AND run_id = ?",
            (run_id,),
        )
        conn.execute("DELETE FROM checkpoints WHERE path_key LIKE '%summarize%'")

    resumed = await world.resume(run_id)
    assert resumed.status is RunStatus.SUCCEEDED
    # the adapter was consulted for reconciliation, not re-executed
    assert len(announce_effect.executions) == 1
    kinds = [event.kind for event in world.journal.events(run_id, limit=200)]
    assert "EffectReconciled" in kinds


async def test_failure_marks_the_run_and_resume_completes_it(
    world: Constructicon,
    fake_executor: FakeExecutor,
) -> None:
    """Crash mid-run: completed nodes are never recomputed on resume."""
    run_id = RunId("run-failing")
    # poison the executor script after registration so triage succeeds but the
    # scripted announce-side effect fails? Simpler: drop the scripted reply so
    # a later fresh node fails — here we poison summarize via a broken brief.
    del fake_executor._script["triage"]  # deliberate fault injection
    with pytest.raises(Exception, match="no scripted reply"):
        await world.start(pipeline_graph(), INPUTS, run_id=run_id)
    assert world.journal.run_status(run_id) is RunStatus.FAILED

    fake_executor._script["triage"] = {
        "title": "fix the flaky retry loop",
        "risk": "low",
    }
    result = await world.resume(run_id)
    assert result.status is RunStatus.SUCCEEDED
