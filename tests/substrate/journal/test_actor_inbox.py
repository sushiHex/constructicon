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

from constructicon.core.channel import ActorInboxRevision, InvalidChannelRevision
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal

OTHER_CHANNEL = "channel/escalation"
BOTH: frozenset[str] = frozenset({"advice", "approval"})


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
        interactions=BOTH,
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
            interactions=BOTH,
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
        interactions=BOTH,
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

    ahead = ActorInboxRevision(message_seq=current.message_seq + 1, ack_seq=current.ack_seq)
    with pytest.raises(InvalidChannelRevision, match="ahead of retained history"):
        journal.channel_actor_inbox(
            actor_id=ADVISOR,
            revision=ahead,
            interactions=BOTH,
            after=None,
            limit=10,
        )


def test_a_channel_local_cut_is_not_an_actor_cut(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """The two domains are distinct types, so mixing them cannot type-check.

    A channel-local cut sits at or below the global one, so bounding a
    cross-channel read with it would silently omit every other channel's
    messages rather than fail.
    """

    journal, review, escalation = _two_channels(tmp_path, clock)
    review.append_request(_intent(), ATTESTATION)
    escalation.append_request(_elsewhere(), ATTESTATION)

    channel_cut = review.latest_revision(ADVISOR)
    actor_cut = journal.channel_actor_revision(actor_id=ADVISOR)
    assert type(channel_cut) is not type(actor_cut)
    assert channel_cut.message_seq < actor_cut.message_seq  # and it under-bounds

    full = journal.channel_actor_inbox(
        actor_id=ADVISOR,
        revision=actor_cut,
        interactions=BOTH,
        after=None,
        limit=10,
    )
    assert len(full) == 2


def _approval(port: str):
    """One approval-interaction request to the same advisor."""

    base = _intent(port=port)
    return base.model_copy(
        update={
            "interaction": "approval",
            "message_id": request_message_id(
                run_id=base.run_id,
                path=base.path,
                channel_id=base.channel_id,
                channel_revision=base.channel_revision,
                lane=base.lane,
                interaction="approval",
                port=port,
            ),
        }
    )


def test_scope_filtering_never_truncates_a_page(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """`limit` must count rows the reader may see, not rows fetched.

    Filtering after the fact would return a short or empty page while matching
    rows remained beyond the cut — and an empty page reads as "done".
    """

    journal, review, _escalation = _two_channels(tmp_path, clock)
    # Two approvals the advise-only reader may not see, then two it may.
    review.append_request(_approval("approve-a"), ATTESTATION)
    review.append_request(_approval("approve-b"), ATTESTATION)
    visible = [
        review.append_request(_intent(port="advice-a"), ATTESTATION),
        review.append_request(_intent(port="advice-b"), ATTESTATION),
    ]
    revision = journal.channel_actor_revision(actor_id=ADVISOR)

    page = journal.channel_actor_inbox(
        actor_id=ADVISOR,
        revision=revision,
        interactions=frozenset({"advice"}),
        after=None,
        limit=2,
    )
    assert [delivery.message for delivery in page] == visible  # a full page, not empty


def test_an_actor_authorized_for_nothing_reads_nothing(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, review, _escalation = _two_channels(tmp_path, clock)
    review.append_request(_intent(), ATTESTATION)
    assert (
        journal.channel_actor_inbox(
            actor_id=ADVISOR,
            revision=journal.channel_actor_revision(actor_id=ADVISOR),
            interactions=frozenset(),
            after=None,
            limit=10,
        )
        == ()
    )


def test_a_reader_sees_only_the_interactions_it_is_authorized_for(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Authorization is read off each message's sealed interaction."""

    journal, review, _escalation = _two_channels(tmp_path, clock)
    advice = review.append_request(_intent(), ATTESTATION)
    approval = review.append_request(_approval("approve-a"), ATTESTATION)
    revision = journal.channel_actor_revision(actor_id=ADVISOR)

    def _page(interactions: frozenset[str]) -> list[object]:
        return [
            delivery.message
            for delivery in journal.channel_actor_inbox(
                actor_id=ADVISOR,
                revision=revision,
                interactions=interactions,
                after=None,
                limit=10,
            )
        ]

    assert _page(frozenset({"advice"})) == [advice]
    assert _page(frozenset({"approval"})) == [approval]
    assert _page(BOTH) == [advice, approval]
