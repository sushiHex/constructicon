"""The wake lookup must survive scale and refuse an unverified relationship."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.conftest import FakeClock
from tests.substrate.channels.test_channel_contract import (
    ADVISOR,
    ATTESTATION,
    CHANNEL_ID,
    _intent,
)

from constructicon.core.channel import reply_message_id
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import digest
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal


def test_a_page_of_many_waiting_requests_does_not_exceed_the_bind_limit(
    journal: SqliteJournal,
) -> None:
    """One placeholder per request would break SQLite's variable ceiling.

    A page of runs that each park many units reaches it on a default workload,
    and the exception would escape into the recovery pump.
    """

    requests = [digest("channel-message", 1, {"n": index}) for index in range(40_000)]
    assert journal.answered_requests(requests) == {}  # no reply exists for any


def test_duplicate_requests_are_asked_about_once(journal: SqliteJournal) -> None:
    request = digest("channel-message", 1, {"n": 1})
    assert journal.answered_requests([request] * 5_000) == {}


def test_a_reply_pointer_that_does_not_derive_from_its_request_is_damage(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """A `reply_to` pointer alone must never be treated as a relationship."""

    database = tmp_path / "tampered.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    answered = mailbox.append_request(_intent(), ATTESTATION)
    other = mailbox.append_request(_intent(port="second-request"), ATTESTATION)
    reply = mailbox.reply(
        request_id=answered.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-1",
    )
    assert journal.answered_requests([answered.message_id]) == {
        answered.message_id: reply.message_id
    }

    # Repoint the stored reply at the other request without changing anything
    # else — exactly what a tampered or damaged row looks like.
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_messages SET reply_to = ? WHERE message_id = ?",
            (str(other.message_id), str(reply.message_id)),
        )
        connection.commit()

    reopened = SqliteJournal(database, now_fn=clock.now)
    with pytest.raises(JournalDamaged, match="does not derive from request"):
        reopened.answered_requests([other.message_id])

    # And the read that would have handed a run that payload refuses too.
    with pytest.raises(JournalDamaged, match="contradicts the request"):
        MailboxChannel(reopened, channel_id=CHANNEL_ID).reply_for(other.message_id)


def test_a_genuine_reply_still_resolves(tmp_path: Path, clock: FakeClock) -> None:
    journal = SqliteJournal(tmp_path / "genuine.db", now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply = mailbox.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-1",
    )
    assert reply.message_id == reply_message_id(
        request_id=request.message_id,
        reply_port="reply",
    )
    assert mailbox.reply_for(request.message_id) == reply
    assert journal.answered_requests([request.message_id]) == {
        request.message_id: reply.message_id
    }


def test_an_absent_request_is_reported_as_unanswered(journal: SqliteJournal) -> None:
    assert journal.answered_requests([digest("channel-message", 1, {"absent": True})]) == {}
