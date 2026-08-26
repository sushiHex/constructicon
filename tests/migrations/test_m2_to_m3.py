"""A v2 (M2-era) database migrates additively to v3: the capability_leases
table appears; nothing else moves (M3 §6)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from constructicon.core.address import RunId
from constructicon.core.identity import digest
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal


def test_v2_database_gains_the_lease_table_and_nothing_else_moves(
    tmp_path: Path,
) -> None:
    db = tmp_path / "m2.db"
    # build a real store, then strip it back to the exact v2 shape
    journal = SqliteJournal(db)
    journal.create_run(
        RunId("run-m2"),
        manifest_json='{"stub": true}',
        manifest_hash=digest("manifest", 1, {"stub": True}),
        input_hash=digest("inputs", 1, {"a": 1}),
        inputs={"a": 1},
    )
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE capability_leases")
        conn.execute("PRAGMA user_version = 2")

    migrated = SqliteJournal(db)  # the v2 -> v3 chain runs here
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "capability_leases" in tables
    assert migrated.run_inputs(RunId("run-m2")) == {"a": 1}  # untouched
    assert migrated.capability_leases(RunId("run-m2")) == []
