"""M7 persistence: SQLite v5 gains empty channel tables and nothing else."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from constructicon.core.address import RunId
from constructicon.core.errors import JournalDamaged
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.conftest import FakeClock, pipeline_graph
from tests.migrations.test_sqlite_from_v3_to_current import _register_pipeline
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6

_CHANNEL_TABLES = {"channel_messages", "channel_acks"}


def _tables(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }


def _dump(
    database: Path,
    tables: set[str],
    *,
    columns: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every pre-M7 table, ordered, as plain comparable tuples."""

    with sqlite3.connect(database) as connection:
        return {
            table: sorted(
                tuple(row)
                for row in connection.execute(
                    "SELECT "
                    + (", ".join(columns[table]) if columns is not None else "*")
                    + f" FROM {table}"
                ).fetchall()
            )
            for table in sorted(tables)
        }


def _columns(database: Path, tables: set[str]) -> dict[str, tuple[str, ...]]:
    with sqlite3.connect(database) as connection:
        return {
            table: tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})"))
            for table in sorted(tables)
        }


def _seed_v6_database(database: Path, clock: FakeClock) -> SqliteJournal:
    journal = SqliteJournal(database, now_fn=clock.now)
    system, _executor, _effect = _register_pipeline(journal)
    inputs = {"issue": {"title": "historical run"}}
    manifest = system.validate(pipeline_graph(), inputs)
    journal.create_run(
        RunId("historical-v5-run"),
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs=inputs,
    )
    return journal


def test_v5_to_v6_adds_empty_channel_tables_and_rewrites_no_historical_row(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    database = tmp_path / "v5.db"
    _seed_v6_database(database, clock)

    _downgrade_v7_schema_to_v6(database)
    legacy_tables = _tables(database) - _CHANNEL_TABLES
    legacy_columns = _columns(database, legacy_tables)
    before = _dump(database, legacy_tables, columns=legacy_columns)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE channel_messages")
        connection.execute("DROP TABLE channel_acks")
        connection.execute("PRAGMA user_version = 5")
        connection.commit()
    assert _tables(database) & _CHANNEL_TABLES == set()  # a genuine v5 database

    migrated = SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert _tables(database) >= _CHANNEL_TABLES
    assert _dump(database, legacy_tables, columns=legacy_columns) == before

    with sqlite3.connect(database) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in sorted(_CHANNEL_TABLES)
        }
    assert counts == {"channel_acks": 0, "channel_messages": 0}
    record = migrated.run_record(RunId("historical-v5-run"))
    assert record is not None  # the historical run reopens unchanged


def test_a_database_newer_than_this_build_is_refused_rather_than_touched(
    tmp_path: Path,
) -> None:
    """The mechanism by which a pre-M7 binary refuses a schema-6 database."""

    clock = FakeClock()
    database = tmp_path / "future.db"
    _seed_v6_database(database, clock)
    with sqlite3.connect(database) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        connection.commit()

    with pytest.raises(JournalDamaged, match="newer than this build"):
        SqliteJournal(database, now_fn=clock.now)


def test_reopening_a_current_database_leaves_channel_history_intact(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    database = tmp_path / "reopen.db"
    _seed_v6_database(database, clock)
    before = _dump(database, _tables(database))

    SqliteJournal(database, now_fn=clock.now)
    assert _dump(database, _tables(database)) == before  # reopen is not a migration


def test_refusing_a_newer_database_does_not_change_its_journal_mode(
    tmp_path: Path,
) -> None:
    """"Refusing to touch it" must be literally true, pragmas included."""

    database = tmp_path / "future-delete-mode.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        connection.commit()

    with pytest.raises(JournalDamaged, match="newer than this build"):
        SqliteJournal(database, now_fn=FakeClock().now)

    with sqlite3.connect(database) as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "delete"  # a refused database keeps even its journal mode
