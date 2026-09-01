"""A write proves the fence it turns, not the history behind it.

Every run mutation used to project the run through a validator that walked the
whole event history and, per run, re-read every event seal in the database. The
cost of appending therefore grew with the run's own length — quadratic in the
one dimension a long-lived run grows in, and the same walk repeated once per run
when a store was opened.

The guarantee is stated here by counting, not by timing: a write projects a
bounded number of events, and that bound does not move when the history behind
it gets longer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import FakeClock, pipeline_graph
from tests.migrations.test_sqlite_from_v3_to_current import _register_pipeline

from constructicon.core.address import RunId
from constructicon.core.run import RunLease, RunStatus
from constructicon.substrate.journal import _sqlite_execution_facts
from constructicon.substrate.journal.sqlite import SqliteJournal


def _running_run(database: Path, clock: FakeClock) -> tuple[SqliteJournal, RunLease]:
    journal = SqliteJournal(database, now_fn=clock.now)
    system, _executor, _effect = _register_pipeline(journal)
    inputs = {"issue": {"title": "cost"}}
    manifest = system.validate(pipeline_graph(), inputs)
    run_id = RunId("run-write-cost")
    journal.create_run(
        run_id,
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs=inputs,
    )
    lease = journal.claim_run(run_id, owner_id="cost", ttl_s=3600)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    return journal, lease


def _projections_for_one_append(
    monkeypatch: pytest.MonkeyPatch,
    journal: SqliteJournal,
    lease: RunLease,
    kind: str,
) -> int:
    """How many event rows one append projects through the seal validator."""

    original = _sqlite_execution_facts._stored_event_from_row_without_relationship
    counted = 0

    def counting(connection, row):  # type: ignore[no-untyped-def]
        nonlocal counted
        counted += 1
        return original(connection, row)

    monkeypatch.setattr(
        _sqlite_execution_facts,
        "_stored_event_from_row_without_relationship",
        counting,
    )
    try:
        journal.append_event(lease, kind)
    finally:
        monkeypatch.undo()
    return counted


def test_one_append_costs_the_same_at_any_history_length(
    tmp_path: Path,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound is what matters, not its value: it must not move with N."""

    journal, lease = _running_run(tmp_path / "write-cost.db", clock)

    for step in range(4):
        journal.append_event(lease, f"Short{step}")
    early = _projections_for_one_append(monkeypatch, journal, lease, "MeasuredEarly")

    for step in range(60):
        journal.append_event(lease, f"Long{step}")
    late = _projections_for_one_append(monkeypatch, journal, lease, "MeasuredLate")

    assert early == late, (
        f"appending projected {early} events with a short history and {late} "
        "with a long one; a write is walking the history behind its fence"
    )
    # And the bound is small: the latest event a status names, and the baseline
    # an attempt relationship would compare against. Never the history.
    assert late <= 4


def test_opening_a_store_costs_the_same_per_run_however_many_runs_it_holds(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Inventory is a whole-store act, so it proves each seal once, not once per run.

    Opening used to run the global event-seal inventory and then repeat an
    equivalent per-run inventory for every retained run, so the work grew with
    runs x events rather than with rows.
    """

    database = tmp_path / "open-cost.db"
    journal, lease = _running_run(database, clock)
    for step in range(3):
        journal.append_event(lease, f"First{step}")

    system, _executor, _effect = _register_pipeline(journal)
    inputs = {"issue": {"title": "second"}}
    manifest = system.validate(pipeline_graph(), inputs)
    for index in range(6):
        other = RunId(f"run-open-cost-{index}")
        journal.create_run(
            other,
            manifest_json=manifest.model_dump_json(),
            manifest_hash=manifest.manifest_hash,
            input_hash=manifest.input_hash,
            inputs=inputs,
        )
        other_lease = journal.claim_run(other, owner_id="cost", ttl_s=3600)
        journal.transition_run(
            other_lease,
            expected=frozenset({RunStatus.PENDING}),
            target=RunStatus.RUNNING,
            event_kind="RunStarted",
        )
        for step in range(3):
            journal.append_event(other_lease, f"Other{step}")
        journal.release_run(other_lease)

    projections = 0
    original = _sqlite_execution_facts._stored_event_from_row_without_relationship

    def counting(connection, row):  # type: ignore[no-untyped-def]
        nonlocal projections
        projections += 1
        return original(connection, row)

    _sqlite_execution_facts._stored_event_from_row_without_relationship = counting
    try:
        SqliteJournal(database, now_fn=clock.now)
    finally:
        _sqlite_execution_facts._stored_event_from_row_without_relationship = original

    # 7 runs x 4 events = 28 rows. Each is proved by the global event inventory
    # and by the resume-provenance inventory, plus a bounded per-run lifecycle
    # read. A per-run re-inventory would multiply this by the number of runs.
    assert projections < 28 * 4, (
        f"opening projected {projections} events for 28 rows; inventory is "
        "repeating itself once per run"
    )
