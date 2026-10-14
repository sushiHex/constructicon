"""Version extension preserves the exact v8 provenance baseline atomically."""

from __future__ import annotations

import sqlite3
import subprocess
import sys

import pytest

from constructicon.core.address import RunId
from constructicon.core.errors import JournalDamaged
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.migrations.test_sqlite_v7_to_v8 import historical_database, retained_bytes
from tests.run_worlds import create_test_run


def proofs(database):
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in ("capability_accounting_eras", "durable_fact_seals")
        }


@pytest.mark.parametrize("seam", ("before_commit", "after_commit"))
def test_real_process_v8_to_v9_crash_publishes_whole_version_or_none(tmp_path, seam):
    database = tmp_path / "atomic9.db"
    historical_database(database, "schema8-disposal-baseline.sql")
    before, before_proofs = retained_bytes(database), proofs(database)
    program = """
import os
import sys
from constructicon.substrate.journal._sqlite_schema import _SqliteSchemaMixin
from constructicon.substrate.journal.sqlite import SqliteJournal
original = _SqliteSchemaMixin._migrate_m8_to_m9
def interrupted(self, connection):
    def probe(name):
        if name == 'capability_disposal_migration.' + sys.argv[2]:
            os._exit(91)
    self.fault_probe = probe
    original(self, connection)
_SqliteSchemaMixin._migrate_m8_to_m9 = interrupted
SqliteJournal(sys.argv[1])
raise AssertionError('crash seam was not reached')
"""
    died = subprocess.run(
        [sys.executable, "-c", program, str(database), seam],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert died.returncode == 91, died.stderr.decode("utf-8", errors="replace")
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (
            8 if seam == "before_commit" else 9,
        )
    assert retained_bytes(database) == before
    assert proofs(database) == before_proofs
    recovered = SqliteJournal(database)
    assert retained_bytes(database) == before
    assert proofs(database) == before_proofs
    assert recovered.capability_disposal_receipt("genuinely-absent-command") is None
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (9,)


@pytest.mark.parametrize("damage", ("unknown_family", "disposed_audit", "era_inventory"))
def test_schema8_extension_refuses_nonclosed_or_false_baseline_without_remint(tmp_path, damage):
    from constructicon.substrate.journal._sqlite_execution_facts import seal_event

    database = tmp_path / f"dirty8-{damage}.db"
    historical_database(database, "schema8-disposal-baseline.sql")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        if damage == "unknown_family":
            connection.execute(
                "INSERT INTO durable_fact_seals VALUES (?, ?, ?, ?)",
                ("future_family", "future", "future", "sha256:" + "0" * 64),
            )
        elif damage == "era_inventory":
            connection.execute(
                "UPDATE capability_accounting_eras SET inventory_hash = ?", ("sha256:" + "0" * 64,)
            )
        else:
            run_id = "run-disposal-fixture"
            connection.execute(
                "INSERT INTO events (run_id, seq, kind, path_json, created_at, payload)"
                " VALUES (?, 4, 'CapabilityDisposalRecorded', NULL, ?, '{}')",
                (run_id, "2026-01-01T00:00:00+00:00"),
            )
            connection.execute("UPDATE runs SET next_event_seq = 4 WHERE run_id = ?", (run_id,))
            row = connection.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq = 4", (run_id,)
            ).fetchone()
            seal_event(connection, row)
    before, before_proofs = retained_bytes(database), proofs(database)
    failure = None
    try:
        SqliteJournal(database)
    except Exception as exc:
        failure = exc
    assert isinstance(failure, JournalDamaged), failure
    assert retained_bytes(database) == before
    assert proofs(database) == before_proofs
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (8,)


def test_new_schema9_run_keeps_the_named_schema8_creation_proof(tmp_path):
    database = tmp_path / "creation9.db"
    journal = SqliteJournal(database)
    run_id = RunId("created-on-nine")
    create_test_run(journal, run_id)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (9,)
        assert connection.execute(
            "SELECT source, floor FROM capability_accounting_eras WHERE run_id = ?", (run_id,)
        ).fetchone() == ("schema8-creation", 0)
    assert SqliteJournal(database).capability_accounting_snapshot(run_id).detail.items == ()
