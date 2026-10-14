"""Run status, accounting, era and selected cut come from one SQLite snapshot."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

import pytest
from tests.migrations.test_sqlite_v7_to_v8 import historical_database
from tests.run_worlds import create_test_run, start_test_run

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunStatus
from constructicon.core.workspace import lease_id_for
from constructicon.substrate.journal import _sqlite_accounting
from constructicon.substrate.journal.sqlite import SqliteJournal

RUN = RunId("run-accounting-snapshot")


def acquire(journal, worker, index):
    path = ExecutionPath(scope=ScopePath(segments=(f"lease-{index}",)))
    lease = CapabilityLease(
        lease_id=lease_id_for(worker.run_id, path, "workspace"),
        acquisition_epoch=worker.epoch,
        run_id=worker.run_id,
        binding_id="workspace",
        path=path,
        state="active",
    )
    journal.record_capability_lease(worker, lease)
    return lease


def test_accounting_snapshot_is_complete_beyond_a_hundred_pairs(tmp_path: Path) -> None:
    journal = SqliteJournal(tmp_path / "many-pairs.db")
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="accounting-worker")
    leases = [acquire(journal, worker, index) for index in range(101)]
    assert hasattr(journal, "capability_accounting_snapshot")
    snapshot = journal.capability_accounting_snapshot(RUN)
    assert snapshot is not None
    assert snapshot.run.status.value == "running"
    assert snapshot.detail.through_event_seq == 102
    assert len(snapshot.detail.items) == 101
    assert {item.lease_id for item in snapshot.detail.items} == {lease.lease_id for lease in leases}
    assert all(
        item.state == "active" and item.acquisition_event_seq is not None
        for item in snapshot.detail.items
    )


def test_accounting_old_cut_survives_later_close_and_acquisition(tmp_path: Path) -> None:
    journal = SqliteJournal(tmp_path / "cut.db")
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="accounting-worker")
    first = acquire(journal, worker, 0)
    assert hasattr(journal, "capability_accounting_snapshot")
    original = journal.capability_accounting_snapshot(RUN)
    assert original is not None
    journal.transition_capability_lease(
        worker,
        lease_id=first.lease_id,
        acquisition_epoch=first.acquisition_epoch,
        expected=frozenset({"active"}),
        target="closed",
        disposition="released",
    )
    acquire(journal, worker, 1)
    later = journal.capability_accounting_snapshot(RUN)
    assert later is not None and len(later.detail.items) == 2
    assert (
        journal.capability_accounting_snapshot(
            RUN,
            through_event_seq=original.detail.through_event_seq,
        ).detail
        == original.detail
    )
    assert later.detail != original.detail


def test_legacy_accounting_has_unknown_acquisition_sequence_and_positive_floor(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    journal = SqliteJournal(database)
    run = RunId("run-historical-capabilities")
    assert hasattr(journal, "capability_accounting_snapshot")
    snapshot = journal.capability_accounting_snapshot(run)
    assert snapshot is not None and len(snapshot.detail.items) == 3
    assert all(item.acquisition_event_seq is None for item in snapshot.detail.items)
    lost = next(item for item in snapshot.detail.items if item.state == "lost")
    assert lost.loss == "opaque_lost"
    assert lost.physical_cleanup == "unknown"
    assert lost.disposal_receipt is None
    with pytest.raises(ContractViolation, match="cut"):
        journal.capability_accounting_snapshot(run, through_event_seq=0)


def test_snapshot_refuses_erased_eventless_history(tmp_path: Path) -> None:
    database = tmp_path / "eventless.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM events WHERE kind='LeaseAcquired'")
        connection.execute(
            "UPDATE runs SET next_event_seq=1 WHERE run_id='run-historical-capabilities'"
        )
    journal = SqliteJournal(database)
    run = RunId("run-historical-capabilities")
    assert hasattr(journal, "capability_accounting_snapshot")
    assert len(journal.capability_accounting_snapshot(run).detail.items) == 3
    with sqlite3.connect(database) as connection:
        pair = connection.execute(
            "SELECT lease_id FROM capability_leases WHERE state='active'"
        ).fetchone()[0]
        connection.execute("DELETE FROM capability_leases WHERE lease_id=?", (pair,))
        connection.execute("DELETE FROM legacy_capability_lease_seals WHERE lease_id=?", (pair,))
    with pytest.raises(JournalDamaged, match="inventory"):
        journal.capability_accounting_snapshot(run)


def test_accounting_snapshot_keeps_status_and_cut_before_concurrent_commit(tmp_path, monkeypatch):
    database = tmp_path / "coherent.db"
    reader = SqliteJournal(database)
    create_test_run(reader, RUN)
    worker = start_test_run(reader, RUN, owner_id="accounting-worker")
    first = acquire(reader, worker, 0)
    writer = SqliteJournal(database)
    original = _sqlite_accounting.run_projection_for_id
    commits = []
    transactions = []

    def interleaved(connection, run_id, *, observe):
        transactions.append(connection.in_transaction)
        result = original(connection, run_id, observe=observe)
        if not commits:
            writer.transition_capability_lease(
                worker,
                lease_id=first.lease_id,
                acquisition_epoch=first.acquisition_epoch,
                expected=frozenset({"active"}),
                target="closed",
                disposition="released",
            )
            writer.transition_run(
                worker,
                expected=frozenset({RunStatus.RUNNING}),
                target=RunStatus.FAILED,
                event_kind="RunFailed",
            )
            commits.append(True)
        return result

    monkeypatch.setattr(_sqlite_accounting, "run_projection_for_id", interleaved)
    snapshot = reader.capability_accounting_snapshot(RUN)
    assert commits == [True]
    assert transactions == [True]
    assert snapshot.run.status.value == "running"
    assert snapshot.detail.through_event_seq == 2
    assert snapshot.detail.items[0].state == "active"
    later = reader.capability_accounting_snapshot(RUN)
    assert later.run.status.value == "failed"
    assert later.detail.items[0].state == "closed"
    assert later.detail.through_event_seq > snapshot.detail.through_event_seq


@pytest.mark.parametrize("kind", ("LeaseAcquired", "LeaseTransition"))
def test_snapshot_scoped_reverse_edges_refuse_missing_pair(tmp_path, kind):
    journal = SqliteJournal(tmp_path / "reverse.db")
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="accounting-worker")
    acquire(journal, worker, 0)
    assert len(journal.capability_accounting_snapshot(RUN).detail.items) == 1
    journal.append_event(worker, kind, payload={"lease_id": "missing-pair", "acquisition_epoch": 1})
    with pytest.raises(JournalDamaged, match="exact retained pair"):
        journal.capability_accounting_snapshot(RUN)


@pytest.mark.parametrize("kind", ("LeaseAcquired", "LeaseTransition"))
def test_snapshot_retains_exact_foreign_pair_contradictions(tmp_path, kind):
    journal = SqliteJournal(tmp_path / "foreign.db")
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="accounting-worker")
    lease = acquire(journal, worker, 0)
    other = RunId("run-unrelated")
    create_test_run(journal, other)
    other_worker = start_test_run(journal, other, owner_id="other-worker")
    journal.append_event(other_worker, "LeaseTransition", payload={"unrelated": "malformed"})
    assert len(journal.capability_accounting_snapshot(RUN).detail.items) == 1
    journal.append_event(
        other_worker,
        kind,
        payload={
            "lease_id": lease.lease_id,
            "acquisition_epoch": lease.acquisition_epoch,
        },
    )
    with pytest.raises(JournalDamaged, match=r"(contradictory|duplicate)"):
        journal.capability_accounting_snapshot(RUN)


def test_accounting_batch_does_not_repeat_whole_journal_pair_queries(tmp_path, monkeypatch):
    journal = SqliteJournal(tmp_path / "cost.db")
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="accounting-worker")
    for index in range(101):
        acquire(journal, worker, index)
    queries = []
    original_read = journal._read

    @contextmanager
    def traced():
        with original_read() as connection:
            connection.set_trace_callback(queries.append)
            yield connection

    monkeypatch.setattr(journal, "_read", traced)
    point_started = perf_counter()
    point = journal.capability_leases(RUN)
    point_elapsed = perf_counter() - point_started
    point_queries = list(queries)
    queries.clear()
    started = perf_counter()
    snapshot = journal.capability_accounting_snapshot(RUN)
    elapsed = perf_counter() - started
    assert snapshot is not None and len(snapshot.detail.items) == 101
    assert {item.lease_id for item in snapshot.detail.items} == {lease.lease_id for lease in point}
    whole_history = [q for q in queries if "SELECT * FROM events WHERE kind IN" in q]
    assert len(whole_history) == 1
    assert not any("constructicon_lease_event_identity" in q for q in queries)
    point_history = [q for q in point_queries if "SELECT * FROM events WHERE kind IN" in q]
    assert len(point_history) == 101
    print(f"101-pair existing reader: {len(point_queries)} SQL statements, {point_elapsed:.4f}s")
    print(f"101-pair accounting: {len(queries)} SQL statements, {elapsed:.4f}s")


@pytest.mark.parametrize("column,value", (("status", "succeeded"), ("next_event_seq", 50)))
def test_snapshot_status_and_extent_use_canonical_run_law(tmp_path, column, value):
    database = tmp_path / "run-damage.db"
    journal = SqliteJournal(database)
    create_test_run(journal, RUN)
    start_test_run(journal, RUN, owner_id="accounting-worker")
    assert journal.capability_accounting_snapshot(RUN).run.status.value == "running"
    with sqlite3.connect(database) as connection:
        connection.execute(f"UPDATE runs SET {column}=?", (value,))
    with pytest.raises(JournalDamaged):
        journal.capability_accounting_snapshot(RUN)


def test_accounting_keeps_old_unmarked_foreign_event_opaque(tmp_path):
    """Admitted synthetic old shape, not a claim that an old writer produced it."""

    database = tmp_path / "opaque-owner.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    with sqlite3.connect(database) as connection:
        # Move the old lost pair's unmarked acquisition to the other retained run.
        # Both run extents remain exact; legacy history deliberately does not
        # interpret these old payloads as current owner/lifecycle authority.
        connection.execute(
            "UPDATE events SET run_id='run-historical-empty', seq=2"
            " WHERE run_id='run-historical-capabilities' AND seq=4"
        )
        connection.execute(
            "INSERT INTO events SELECT 'run-historical-empty', 1, kind,"
            " path_json, payload, created_at"
            " FROM events WHERE run_id='run-historical-capabilities' AND seq=1"
        )
        connection.execute(
            "UPDATE runs SET next_event_seq=3 WHERE run_id='run-historical-capabilities'"
        )
        connection.execute(
            "UPDATE runs SET status='running', owner_epoch=1, owner_pid=123,"
            " heartbeat_at='2026-01-01T00:00:00+00:00', next_event_seq=2"
            " WHERE run_id='run-historical-empty'"
        )
    journal = SqliteJournal(database)
    run = RunId("run-historical-capabilities")
    canonical = journal.capability_leases(run)
    snapshot = journal.capability_accounting_snapshot(run)
    assert len(canonical) == len(snapshot.detail.items) == 3
    assert {(item.lease_id, item.state) for item in snapshot.detail.items} == {
        (item.lease_id, item.state) for item in canonical
    }
    assert all(item.acquisition_event_seq is None for item in snapshot.detail.items)
    assert snapshot.detail.through_event_seq == 3
    assert sum(item.loss == "opaque_lost" for item in snapshot.detail.items) == 1
