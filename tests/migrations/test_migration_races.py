"""Two processes opening one store must not condemn it between them.

The ladder decides which rung to climb from a `user_version` read before it
holds the write lock. Two openers can therefore both decide to climb the same
rung, and only one of them is right by the time it gets there. Since ADR 0016
forbids healing on open, the loser's verdict is not a retryable error: it is a
store that never opens again.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from constructicon.substrate.journal import _sqlite_base
from constructicon.substrate.journal._sqlite_schema import _has_legacy_runs_table
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.channel_commands import ack_with_command
from tests.channel_requests import AttestedMailboxChannel as MailboxChannel
from tests.conftest import FakeClock
from tests.migrations.test_sqlite_v6_to_v7 import (
    ADVISOR,
    CHANNEL_ID,
    _downgrade_v7_schema_to_v6,
    _intent,
)


def test_the_loser_of_a_v6_migration_race_does_not_re_migrate(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """The rung is chosen before the lock; it must be re-checked after it.

    Both openers read version 6 and both call the 6→7 step. Whichever gets the
    write lock second finds a current database and must leave it alone — the
    migration stamps every row it sees as legacy, so a second pass would read
    the winner's current provenance as a partly migrated contradiction.
    """

    database = tmp_path / "v6-race.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    request = MailboxChannel(journal, channel_id=CHANNEL_ID).append_request(
        _intent(),
        "att-race",
    )
    _downgrade_v7_schema_to_v6(database)

    # The winner climbs, and the store is then used: the acknowledgement below
    # is a current fact, stamped with current provenance.
    winner = SqliteJournal(database, now_fn=clock.now)
    ack_with_command(
        MailboxChannel(winner, channel_id=CHANNEL_ID),
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="race-current-ack",
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute(
            "SELECT ack_provenance_version FROM channel_acks"
        ).fetchone()[0] == 1

    # The loser is already inside the ladder with version 6 in hand. Calling the
    # step directly is exactly the state it holds when it reaches the lock.
    loser = SqliteJournal(database, now_fn=clock.now)
    connection = loser._connect()
    try:
        loser._migrate_m6_to_m7(connection)
    finally:
        connection.close()

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    # And the store still opens, which is the whole point.
    SqliteJournal(database, now_fn=clock.now)


def test_a_fresh_create_publishes_its_tables_and_its_version_together(
    tmp_path: Path,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No opener may ever see a store's tables without its version.

    A create that commits `runs` before `user_version` leaves a window in which
    a concurrent opener reads a brand-new database as a version-0 legacy one and
    runs the M1 ladder over it. This watches from outside after every statement
    the create executes, which is every moment such an opener could arrive.
    """

    database = tmp_path / "fresh-race.db"
    seen: set[tuple[int, bool]] = set()

    def observe() -> None:
        if not database.exists():
            return
        watcher = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            seen.add(
                (
                    int(watcher.execute("PRAGMA user_version").fetchone()[0]),
                    _has_legacy_runs_table(watcher),
                )
            )
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

    assert seen, "the create ran no statements to watch"
    assert (0, True) not in seen, (
        f"an outside opener could see tables without a version: {sorted(seen)}; "
        "it would read a brand-new database as version-0 legacy history"
    )
    # The trace fires before each statement, so the create's own commit is not
    # among the observations; the finished store is checked directly.
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert _has_legacy_runs_table(connection)


def test_a_second_opener_does_not_create_over_a_store_that_exists(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Losing the create race is joining, not overwriting."""

    database = tmp_path / "fresh-join.db"
    winner = SqliteJournal(database, now_fn=clock.now)
    request = MailboxChannel(winner, channel_id=CHANNEL_ID).append_request(
        _intent(),
        "att-join",
    )

    # The loser is inside the create fork with version 0 in hand, which is the
    # state it holds when it finally reaches the write lock.
    loser = SqliteJournal(database, now_fn=clock.now)
    connection = loser._connect()
    try:
        assert loser._create_current_schema(connection) is False
    finally:
        connection.close()

    assert MailboxChannel(loser, channel_id=CHANNEL_ID).message(request.message_id) is not None
