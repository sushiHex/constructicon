"""Projections are canonical: identical durable state, identical bytes (M2 §6).

``events.jsonl`` and ``summary.json`` derive from one SQLite read snapshot —
no wall clock, no derived liveness — so regeneration is byte-stable across
calls and across processes.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.errors import ContractViolation, JournalDamaged
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


@pytest.mark.parametrize(
    ("fact", "refusal"),
    # The run's seal covers `created_at`, so it refuses first — the positive
    # seal is the outer boundary, and the decoder behind it never runs.
    (("run", "contradicts its positive seal"), ("event", "durable timestamp")),
)
async def test_projection_uses_the_shared_strict_durable_decoders(
    fact: str,
    refusal: str,
    world: Constructicon,
    tmp_path: Path,
) -> None:
    run_id = RunId(f"run-project-damaged-{fact}")
    await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)
    with sqlite3.connect(world._journal._db_path) as connection:
        if fact == "run":
            connection.execute(
                "UPDATE runs SET created_at = '0' WHERE run_id = ?",
                (str(run_id),),
            )
        else:
            connection.execute(
                "UPDATE events SET created_at = '0' WHERE run_id = ? AND seq = ("
                "SELECT MIN(seq) FROM events WHERE run_id = ?)",
                (str(run_id), str(run_id)),
            )
        connection.commit()

    with pytest.raises(JournalDamaged, match=refusal):
        world.project_run(run_id, tmp_path / f"damaged-{fact}")


@pytest.mark.parametrize("column", ("input_hash", "manifest_hash"))
async def test_a_projection_requires_the_seal_of_the_run_it_projects(
    column: str,
    world: Constructicon,
    tmp_path: Path,
) -> None:
    """A valid value is not the same thing as the right one.

    The strict decoders refuse a scalar that could never have been written.
    They cannot refuse one that could — a digest swapped for another digest
    decodes perfectly, and the summary then states it as durable fact. What
    tells the two apart is the run's positive seal, and a projection that
    selected only the columns it prints was not in a position to ask for it.
    """

    run_id = RunId(f"run-project-rewritten-{column}")
    await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)
    honest = world.project_run(run_id, tmp_path / f"honest-{column}")

    forged = "sha256:" + "b" * 64
    with sqlite3.connect(world._journal._db_path) as connection:
        before = connection.execute(
            f"SELECT {column} FROM runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        assert before is not None and before[0] != forged
        connection.execute(
            f"UPDATE runs SET {column} = ? WHERE run_id = ?",
            (forged, str(run_id)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="contradicts its positive seal"):
        world.project_run(run_id, tmp_path / f"rewritten-{column}")
    assert honest.summary_digest  # the honest projection really did succeed
