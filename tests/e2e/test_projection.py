"""Projections are canonical: identical durable state, identical bytes (M2 §6).

``events.jsonl`` and ``summary.json`` derive from one SQLite read snapshot —
no wall clock, no derived liveness — so regeneration is byte-stable across
calls and across processes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.errors import ContractViolation
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock, pipeline_graph

INPUTS = {"issue": {"title": "retry loop is flaky"}}


async def test_projection_is_byte_stable_across_regeneration_and_processes(
    world: Constructicon, clock: FakeClock, tmp_path: Path
) -> None:
    run_id = RunId("run-project")
    await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = world.project_run(run_id, first_dir)
    second = world.project_run(run_id, second_dir)
    assert first == second
    assert (first_dir / "events.jsonl").read_bytes() == (
        second_dir / "events.jsonl"
    ).read_bytes()
    assert (first_dir / "summary.json").read_bytes() == (
        second_dir / "summary.json"
    ).read_bytes()

    # a different journal handle over the same file — the "fresh process" view
    clock.advance(3600)  # projections carry no wall clock: time must not matter
    other = SqliteJournal(tmp_path / "journal.db", now_fn=clock.now)
    from constructicon.substrate.journal.projection import project_run

    third_dir = tmp_path / "third"
    third = project_run(other, run_id, third_dir)
    assert third.events_digest == first.events_digest
    assert third.summary_digest == first.summary_digest


async def test_summary_projects_durable_state_only(
    world: Constructicon, tmp_path: Path
) -> None:
    run_id = RunId("run-project-summary")
    await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)
    result = world.project_run(run_id, tmp_path / "out")

    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["run_id"] == str(run_id)
    assert summary["status"] == "succeeded"
    assert summary["projected_through_seq"] == result.through_seq
    assert summary["event_count"] > 0
    assert "liveness" not in summary  # derived views never persist

    lines = (tmp_path / "out" / "events.jsonl").read_text().splitlines()
    assert len(lines) == summary["event_count"]
    kinds = [json.loads(line)["kind"] for line in lines]
    assert kinds[0] == "RunStarted" and kinds[-1] == "RunSucceeded"
    seqs = [json.loads(line)["seq"] for line in lines]
    assert seqs == sorted(seqs)


async def test_projection_refuses_unknown_runs(world: Constructicon, tmp_path: Path) -> None:
    with pytest.raises(ContractViolation, match="unknown run"):
        world.project_run(RunId("run-never-existed"), tmp_path / "out")
