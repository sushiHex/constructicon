"""An actor's inbox spans channels; a transport's cut does not (M7 PR C).

A transport's revision is per channel so unrelated traffic cannot advance it.
An actor's inbox is a different query with a different bound, and the control
plane serves an actor rather than a channel.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import FakeClock
from tests.substrate.channels.test_channel_contract import (
    ADVISOR,
    ATTESTATION,
    CHANNEL_ID,
    _intent,
    request_message_id,
)

from constructicon.core.channel import ChannelRevision, InvalidChannelRevision
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal

OTHER_CHANNEL = "channel/escalation"


def _elsewhere(port: str = "request"):
    """One intent addressed to the same advisor on a different channel."""

    base = _intent(port=port)
    return base.model_copy(
        update={
            "channel_id": OTHER_CHANNEL,
            "message_id": request_message_id(
                run_id=base.run_id,
                path=base.path,
                channel_id=OTHER_CHANNEL,
                channel_revision=base.channel_revision,
                lane=base.lane,
                interaction=base.interaction,
                port=port,
            ),
        }
    )


def _two_channels(
    tmp_path: Path,
    clock: FakeClock,
) -> tuple[SqliteJournal, MailboxChannel, MailboxChannel]:
    journal = SqliteJournal(tmp_path / "actor-inbox.db", now_fn=clock.now)
    return (
        journal,
        MailboxChannel(journal, channel_id=CHANNEL_ID),
        MailboxChannel(journal, channel_id=OTHER_CHANNEL),
    )


def test_an_actor_sees_requests_from_every_channel_addressed_to_them(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, review, escalation = _two_channels(tmp_path, clock)
    first = review.append_request(_intent(), ATTESTATION)
    second = escalation.append_request(_elsewhere(), ATTESTATION)

    page = journal.channel_actor_inbox(
        actor_id=ADVISOR,
        revision=journal.channel_actor_revision(actor_id=ADVISOR),
        after=None,
        limit=10,
    )
    assert [delivery.message for delivery in page] == [first, second]
    assert {delivery.message.channel_id for delivery in page} == {CHANNEL_ID, OTHER_CHANNEL}

    # A transport still sees only its own channel.
    scoped = review.inbox(
        actor_id=ADVISOR,
        revision=review.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    assert [delivery.message for delivery in scoped] == [first]


def test_the_actor_cursor_is_the_key_the_page_publishes(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """`(message_seq, message_id)`, not a count of rows already seen."""

    journal, review, escalation = _two_channels(tmp_path, clock)
    sent = [
        review.append_request(_intent(), ATTESTATION),
        escalation.append_request(_elsewhere(), ATTESTATION),
        review.append_request(_intent(port="second-request"), ATTESTATION),
    ]
    revision = journal.channel_actor_revision(actor_id=ADVISOR)

    seen = []
    after: tuple[int, str] | None = None
    for _ in range(4):
        page = journal.channel_actor_inbox(
            actor_id=ADVISOR,
            revision=revision,
            after=after,
            limit=2,
        )
        if not page:
            break
        seen.extend(delivery.message for delivery in page)
        last = page[-1]
        after = (last.message_seq, str(last.message.message_id))

    assert seen == sent
    assert len(seen) == len({message.message_id for message in seen})


def test_an_actor_never_sees_another_actors_messages(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, review, _escalation = _two_channels(tmp_path, clock)
    mine = review.append_request(_intent(), ATTESTATION)
    review.append_request(
        _intent(port="second-request", recipient="static:someone-else"),
        ATTESTATION,
    )

    page = journal.channel_actor_inbox(
        actor_id=ADVISOR,
        revision=journal.channel_actor_revision(actor_id=ADVISOR),
        after=None,
        limit=10,
    )
    assert [delivery.message for delivery in page] == [mine]


def test_an_actor_cut_refuses_a_future_or_incoherent_revision(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, review, _escalation = _two_channels(tmp_path, clock)
    review.append_request(_intent(), ATTESTATION)
    current = journal.channel_actor_revision(actor_id=ADVISOR)

    ahead = ChannelRevision(message_seq=current.message_seq + 1, ack_seq=current.ack_seq)
    with pytest.raises(InvalidChannelRevision, match="ahead of retained history"):
        journal.channel_actor_inbox(
            actor_id=ADVISOR,
            revision=ahead,
            after=None,
            limit=10,
        )
