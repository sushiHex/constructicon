"""M6 persistence: SQLite v4 gains control records without invented provenance."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from constructicon.core.address import RunId
from constructicon.core.control import RunOrigin
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.conftest import FakeClock, pipeline_graph
from tests.migrations.test_m3_to_m4 import _register_pipeline


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

    with sqlite3.connect(database) as connection:
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

    origin = RunOrigin(
        kind="reproduce",
        actor_id="static:migration-test",
        command_id="cmd-migration-test",
        source_run_id=historical_run,
    )
    new_run = RunId("m6-origin-run")
    migrated.create_run(
        new_run,
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs=inputs,
        origin=origin,
    )
    assert migrated.run_origin(new_run) == origin
    new_record = migrated.run_record(new_run)
    assert new_record is not None and new_record.origin == origin
