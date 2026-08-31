"""M7 persistence: SQLite v6 gains one reply-authority column and nothing else.

A v6 reply is not ownerless. The reply path *claimed* its request's
acknowledgement then, so that row already names the command that wrote the
reply. v7 records the same fact on the reply itself, and the read law falls back
to the acknowledgement for anything written before the upgrade — otherwise an
in-flight command that crashed under v6 would, on retry after the upgrade, lose
a race it never entered.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import (
    ChannelContract,
    ChannelReplyConflict,
    ChannelSendIntent,
    request_message_id,
)
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.conftest import FakeClock

CHANNEL_ID = "channel/legacy"
ADVISOR = "static:legacy-advisor"
RUN = RunId("run-v6-legacy")
PATH = ExecutionPath(scope=ScopePath(segments=("review",)))
CONTRACT = ChannelContract(type_id="test/Ask", schema_hash="ask-v1")
REPLY_CONTRACT = ChannelContract(type_id="test/Answer", schema_hash="answer-v1")
WRITER = "cmd-v6-writer"


def _intent() -> ChannelSendIntent:
    return ChannelSendIntent(
        message_id=request_message_id(
            run_id=RUN,
            path=PATH,
            channel_id=CHANNEL_ID,
            channel_revision="1",
            lane="review",
            interaction="advice",
            port="request",
        ),
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane="review",
        interaction="advice",
        recipient_actor_id=ADVISOR,
        contract=CONTRACT,
        reply_contract=REPLY_CONTRACT,
        run_id=RUN,
        path=PATH,
        port="request",
        reply_port="reply",
        payload={"question": "ship?"},
    )


def _dump(database: Path) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(database) as connection:
        tables = sorted(
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        )
        return {
            table: sorted(
                tuple(row) for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            )
            for table in tables
        }


def _seed_genuine_v6(database: Path, clock: FakeClock) -> tuple[str, str]:
    """One request and its reply, stored exactly as v6 stored them.

    The column is dropped after the write, so the reply carries no writer of its
    own — only the acknowledgement does, which is the v6 arrangement.
    """

    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), "att-v6")
    reply = channel.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id=WRITER,
    )
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE channel_messages DROP COLUMN command_id")
        connection.execute("PRAGMA user_version = 6")
        connection.commit()
    return str(request.message_id), str(reply.message_id)


def test_v6_to_v7_adds_one_column_and_rewrites_no_historical_row(tmp_path: Path) -> None:
    clock = FakeClock()
    database = tmp_path / "v6.db"
    _seed_genuine_v6(database, clock)
    before = _dump(database)

    SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(channel_messages)")
        }
    assert "command_id" in columns

    after = _dump(database)
    assert set(after) == set(before)
    for table, rows in before.items():
        if table == "channel_messages":
            # Every historical value survives; only a NULL column is appended.
            assert [row[:-1] for row in after[table]] == rows
            assert all(row[-1] is None for row in after[table])
        else:
            assert after[table] == rows


def test_a_v6_reply_still_reconciles_for_the_command_that_wrote_it(tmp_path: Path) -> None:
    """Its writer lives in the acknowledgement, so an exact retry is not a race."""

    clock = FakeClock()
    database = tmp_path / "retry.db"
    request_id, reply_id = _seed_genuine_v6(database, clock)

    journal = SqliteJournal(database, now_fn=clock.now)
    assert journal.channel_message_command(message_id=reply_id) == WRITER  # type: ignore[arg-type]

    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    clock.advance(600)
    replayed = channel.reply(
        request_id=request_id,  # type: ignore[arg-type]
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id=WRITER,
    )
    assert str(replayed.message_id) == reply_id
    assert journal.channel_actor_revision(actor_id=ADVISOR).message_seq == 2  # no third message


def test_a_v6_reply_still_refuses_a_different_command(tmp_path: Path) -> None:
    clock = FakeClock()
    database = tmp_path / "loser.db"
    request_id, _reply_id = _seed_genuine_v6(database, clock)

    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    with pytest.raises(ChannelReplyConflict, match="already answered by another command"):
        channel.reply(
            request_id=request_id,  # type: ignore[arg-type]
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            command_id="cmd-someone-else",
        )
