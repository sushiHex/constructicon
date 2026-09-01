"""A read is one view of the store, not a sequence of glimpses.

Every projection under ADR 0016 reads a primary fact and then the seal that
proves it, and the open-path inventory counts primary rows and then counts
seals. Outside a transaction each of those is a separate statement and, under
WAL, a separate snapshot — so a writer committing in the gap makes a healthy
store look like it holds a seal with no row. ADR 0016 forbids healing on open,
so that verdict is final: a concurrent writer could permanently condemn a
database that was never damaged.

The law is therefore stated at both boundaries a read can cross: the connection
a projection runs on, and the open path that decides whether a store may be
used at all.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import FakeClock, pipeline_graph
from tests.migrations.test_sqlite_from_v3_to_current import _register_pipeline

from constructicon.core.address import RunId
from constructicon.core.run import RunLease, RunStatus
from constructicon.substrate.journal import _sqlite_schema
from constructicon.substrate.journal.sqlite import SqliteJournal


def _running_run(database: Path, clock: FakeClock) -> tuple[SqliteJournal, RunLease]:
    journal = SqliteJournal(database, now_fn=clock.now)
    system, _executor, _effect = _register_pipeline(journal)
    inputs = {"issue": {"title": "snapshot"}}
    manifest = system.validate(pipeline_graph(), inputs)
    run_id = RunId("run-read-snapshot")
    journal.create_run(
        run_id,
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs=inputs,
    )
    lease = journal.claim_run(run_id, owner_id="snapshot", ttl_s=3600)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    return journal, lease


def _events(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS n FROM events").fetchone()
    return int(row["n"])


def test_one_read_holds_one_view_of_the_store(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Two statements in one read agree, and they agree about the past."""

    database = tmp_path / "one-view.db"
    journal, lease = _running_run(database, clock)
    writer = SqliteJournal(database, now_fn=clock.now)

    with journal._read() as connection:
        before = _events(connection)
        writer.append_event(lease, "CommittedMidRead")
        after = _events(connection)

    assert before == after, (
        f"one read saw {before} events and then {after}; a projection can read a "
        "fact from one state and its seal from another"
    )

    # The reader held a view, not a lock: the writer's commit really did land,
    # and the next read is the one that sees it.
    with journal._read() as connection:
        assert _events(connection) == before + 1


def test_opening_beside_a_committing_writer_is_not_damage(
    tmp_path: Path,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inventory counts rows and then counts seals; both must count one state.

    The commit is injected exactly between those two counts, which is the only
    window in which a healthy store could be condemned. A store that opens here
    opens against any interleaving, because every other gap is narrower.
    """

    database = tmp_path / "open-beside-writer.db"
    journal, lease = _running_run(database, clock)
    journal.append_event(lease, "Settled")

    original = _sqlite_schema.validate_durable_fact_seal_inventory
    committed = False

    def committing(connection: sqlite3.Connection, **counted: Any) -> None:
        nonlocal committed
        if not committed:
            committed = True
            journal.append_event(lease, "CommittedMidOpen")
        original(connection, **counted)

    monkeypatch.setattr(
        _sqlite_schema,
        "validate_durable_fact_seal_inventory",
        committing,
    )

    SqliteJournal(database, now_fn=clock.now)

    assert committed, "the writer never reached the window this test is about"
