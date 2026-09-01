"""M6 persistence: SQLite v4 gains control records without invented provenance."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from constructicon.core.address import RunId
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.conftest import FakeClock, pipeline_graph
from tests.migrations.test_sqlite_from_v3_to_current import _register_pipeline
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6


def test_v4_to_v5_adds_control_tables_without_inventing_run_origins(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    database = tmp_path / "m4.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    system, _executor, _effect = _register_pipeline(journal)
    inputs = {"issue": {"title": "historical run"}}
    manifest = system.validate(pipeline_graph(), inputs)
    historical_run = RunId("historical-m4-run")
    journal.create_run(
        historical_run,
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs=inputs,
    )

    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE channel_messages")
        connection.execute("DROP TABLE channel_acks")
        connection.execute("DROP TABLE commands")
        connection.execute("DROP TABLE approvals")
        connection.execute("DROP TABLE run_origins")
        connection.execute("PRAGMA user_version = 4")
        connection.commit()

    migrated = SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"commands", "approvals", "run_origins"} <= tables
    assert migrated.run_origin(historical_run) is None
    record = migrated.run_record(historical_run)
    assert record is not None and record.origin is None
