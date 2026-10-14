"""A clean missing run is proven without materializing unrelated history."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest
from tests.migrations.test_sqlite_v7_to_v8 import historical_database
from tests.run_worlds import create_test_run, start_test_run
from tests.substrate.journal.test_capability_accounting_snapshot import acquire

from constructicon.core.address import RunId
from constructicon.core.errors import JournalDamaged
from constructicon.substrate.journal.sqlite import SqliteJournal

MISSING = RunId("run-accounting-definitely-missing")


def test_missing_accounting_run_does_not_materialize_unrelated_history(tmp_path, monkeypatch):
    database = tmp_path / "unrelated-history.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    journal = SqliteJournal(database)
    unrelated = RunId("run-accounting-unrelated")
    create_test_run(journal, unrelated)
    worker = start_test_run(journal, unrelated, owner_id="unrelated-worker")
    for index in range(101):
        acquire(journal, worker, index)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM capability_leases").fetchone()[0] > 100
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_capability_lease_seals"
        ).fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] > 100
        assert connection.execute(
            "SELECT COUNT(*) FROM runs WHERE run_id = ?", (MISSING,),
        ).fetchone() == (0,)
    queries = []
    original_read = journal._read

    @contextmanager
    def traced_read():
        with original_read() as connection:
            connection.set_trace_callback(queries.append)
            yield connection

    monkeypatch.setattr(journal, "_read", traced_read)
    assert journal.capability_accounting_snapshot(MISSING) is None
    assert any(f"WHERE r.run_id = '{MISSING}'" in query for query in queries)
    assert any("AS damaged" in query and "child LEFT JOIN runs" in query for query in queries)
    global_materializations = [
        query for query in queries
        if query in {
            "SELECT * FROM capability_leases",
            "SELECT * FROM legacy_capability_lease_seals",
        } or query.startswith("SELECT * FROM events WHERE kind IN")
    ]
    assert global_materializations == [], global_materializations


@pytest.mark.parametrize(
    "orphan", ("lease", "event", "legacy_seal", "era", "era_seal", "run_world_seal"),
)
def test_missing_accounting_run_refuses_positive_orphan_evidence(tmp_path, orphan):
    database = tmp_path / f"orphan-{orphan}.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    journal = SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        if orphan == "lease":
            connection.execute(
                "UPDATE capability_leases SET run_id = ? WHERE rowid ="
                " (SELECT rowid FROM capability_leases LIMIT 1)", (MISSING,),
            )
        elif orphan == "event":
            connection.execute(
                "UPDATE events SET run_id = ? WHERE rowid ="
                " (SELECT rowid FROM events WHERE kind = 'LeaseAcquired' LIMIT 1)", (MISSING,),
            )
        elif orphan == "legacy_seal":
            connection.execute(
                "UPDATE legacy_capability_lease_seals SET run_id = ? WHERE rowid ="
                " (SELECT rowid FROM legacy_capability_lease_seals LIMIT 1)", (MISSING,),
            )
        elif orphan == "era":
            connection.execute(
                "UPDATE capability_accounting_eras SET run_id = ? WHERE rowid ="
                " (SELECT rowid FROM capability_accounting_eras LIMIT 1)", (MISSING,),
            )
        else:
            family = "capability_accounting_era" if orphan == "era_seal" else "run_world"
            connection.execute(
                "UPDATE durable_fact_seals SET fact_key = ?, selector = ? WHERE rowid ="
                " (SELECT rowid FROM durable_fact_seals WHERE family = ? LIMIT 1)",
                (MISSING, MISSING, family),
            )
        assert connection.total_changes == 1, "the fixture must retain one affirmative orphan fact"
    with pytest.raises(JournalDamaged):
        journal.capability_accounting_snapshot(MISSING)
