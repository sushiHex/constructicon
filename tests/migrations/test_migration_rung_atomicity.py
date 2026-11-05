"""Every ladder rung re-reads the version under the write lock it holds.

An opener chooses a rung from a `user_version` read before it holds the write
lock. If another constructor climbs the ladder in that window, the stale opener
must find the rung already taken and leave the store alone. Before the fix the
M5->M6 rung (and M1->M2 through M4->M5) ran anyway; M5->M6 wrote
`user_version = 6` over a schema-9 store and every later open raised
`JournalDamaged`. ADR 0016 forbids healing on open, so that was permanent.

These tests schedule two real `SqliteJournal` constructors: opener A is held
at the statement that would take the write lock until opener B has finished.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from constructicon.core.address import RunId
from constructicon.core.errors import JournalDamaged
from constructicon.substrate.journal import _sqlite_base
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.conftest import FakeClock, pipeline_graph
from tests.migrations.test_sqlite_from_v3_to_current import _register_pipeline
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6

_RUN = RunId("historical-race-run")


def _seed(database: Path, clock: FakeClock) -> None:
    journal = SqliteJournal(database, now_fn=clock.now)
    system, _executor, _effect = _register_pipeline(journal)
    inputs = {"issue": {"title": "historical run"}}
    manifest = system.validate(pipeline_graph(), inputs)
    journal.create_run(
        _RUN,
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs=inputs,
    )


def _drop_to_v5(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE channel_messages")
    connection.execute("DROP TABLE channel_acks")
    connection.execute("PRAGMA user_version = 5")


def _drop_to_v4(connection: sqlite3.Connection) -> None:
    _drop_to_v5(connection)
    connection.execute("DROP TABLE commands")
    connection.execute("DROP TABLE approvals")
    connection.execute("DROP TABLE run_origins")
    connection.execute("PRAGMA user_version = 4")


def _drop_to_v3(connection: sqlite3.Connection) -> None:
    _drop_to_v4(connection)
    connection.execute("PRAGMA user_version = 3")


def _drop_to_v2(connection: sqlite3.Connection) -> None:
    _drop_to_v3(connection)
    connection.execute("DROP TABLE capability_leases")
    connection.execute("PRAGMA user_version = 2")


_SHAPES: dict[int, Callable[[sqlite3.Connection], None]] = {
    5: _drop_to_v5,
    4: _drop_to_v4,
    3: _drop_to_v3,
    2: _drop_to_v2,
}


def _legacy_database(tmp_path: Path, clock: FakeClock, version: int) -> Path:
    database = tmp_path / f"v{version}.db"
    _seed(database, clock)
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        _SHAPES[version](connection)
        connection.commit()
    return database


def _version(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


@pytest.mark.parametrize("stale_version", [5, 4, 3, 2])
def test_a_stale_opener_does_not_rerun_a_rung_another_constructor_climbed(
    tmp_path: Path,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    stale_version: int,
) -> None:
    database = _legacy_database(tmp_path, clock, stale_version)

    paused = threading.Event()
    resume = threading.Event()
    stale_thread: list[int] = []
    original = _sqlite_base._SqliteBase._connect

    def scheduled(self: object) -> sqlite3.Connection:
        connection = original(self)  # type: ignore[arg-type]
        if threading.get_ident() not in stale_thread:
            return connection
        armed = [True]

        def hold(statement: str) -> None:
            # Fires before the statement runs: A has read its version and has
            # not yet asked for the write lock.
            if armed[0] and statement.strip().upper().startswith("BEGIN IMMEDIATE"):
                armed[0] = False
                paused.set()
                assert resume.wait(timeout=60)

        connection.set_trace_callback(hold)
        return connection

    monkeypatch.setattr(_sqlite_base._SqliteBase, "_connect", scheduled)

    outcome: list[BaseException | SqliteJournal] = []

    def open_stale() -> None:
        stale_thread.append(threading.get_ident())
        try:
            outcome.append(SqliteJournal(database, now_fn=clock.now))
        except BaseException as error:
            outcome.append(error)

    stale = threading.Thread(target=open_stale)
    stale.start()
    assert paused.wait(timeout=60), "the stale opener never reached the write lock"
    assert _version(database) == stale_version

    SqliteJournal(database, now_fn=clock.now)  # B climbs the whole ladder
    assert _version(database) == SCHEMA_VERSION

    resume.set()
    stale.join(timeout=60)
    assert not stale.is_alive()
    monkeypatch.undo()

    assert len(outcome) == 1 and isinstance(outcome[0], SqliteJournal), outcome
    assert _version(database) == SCHEMA_VERSION  # never downgraded
    reopened = SqliteJournal(database, now_fn=clock.now)
    assert reopened.run_record(_RUN) is not None


@pytest.mark.parametrize("version", [5, 4])
def test_a_rung_publishes_its_tables_and_its_version_together(
    tmp_path: Path,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    version: int,
) -> None:
    """`executescript` commits first; DDL must not become visible without the stamp."""

    database = _legacy_database(tmp_path, clock, version)
    seen: set[tuple[int, bool]] = set()
    marker = "channel_messages" if version == 5 else "commands"

    def observe() -> None:
        watcher = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            present = (
                watcher.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = ?", (marker,)
                ).fetchone()
                is not None
            )
            seen.add((int(watcher.execute("PRAGMA user_version").fetchone()[0]), present))
        finally:
            watcher.close()

    original = _sqlite_base._SqliteBase._connect

    def traced(self: object) -> sqlite3.Connection:
        connection = original(self)  # type: ignore[arg-type]
        connection.set_trace_callback(lambda _statement: observe())
        return connection

    monkeypatch.setattr(_sqlite_base._SqliteBase, "_connect", traced)
    SqliteJournal(database, now_fn=clock.now)
    monkeypatch.undo()

    assert (version, True) not in seen, sorted(seen)


def test_a_malformed_old_store_is_still_refused_and_left_at_its_version(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Re-reading under the lock must not turn into tolerance of damage."""

    database = _legacy_database(tmp_path, clock, 3)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO capability_leases (lease_id, acquisition_epoch, run_id,"
            " binding_id, scope_json, lifetime, state, created_at, updated_at)"
            " VALUES ('lease', 1, 'run', 'binding', 'not json', 'run', 'open', 't', 't')"
        )
        connection.commit()

    with pytest.raises(JournalDamaged):
        SqliteJournal(database, now_fn=clock.now)
    assert _version(database) == 3  # rolled back, not half-climbed
    with pytest.raises(JournalDamaged):
        SqliteJournal(database, now_fn=clock.now)


@pytest.mark.parametrize("stale_version", [0, 2, 3, 4, 5])
def test_every_stale_rung_is_a_no_op_on_a_current_store(
    tmp_path: Path,
    clock: FakeClock,
    stale_version: int,
) -> None:
    """The private steps of the ladder, called as a stale opener would."""

    database = tmp_path / "current.db"
    _seed(database, clock)
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    journal = SqliteJournal(database, now_fn=clock.now)
    steps = {
        0: journal._migrate_m1_to_m2,
        2: journal._migrate_m2_to_m3,
        3: journal._migrate_m3_to_m4,
        4: journal._migrate_m4_to_m5,
        5: journal._migrate_m5_to_m6,
    }
    connection = journal._connect()
    try:
        steps[stale_version](connection)
        assert not connection.in_transaction
    finally:
        connection.close()
    assert _version(database) == SCHEMA_VERSION
    with sqlite3.connect(database) as connection:
        after = connection.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    assert after == before
