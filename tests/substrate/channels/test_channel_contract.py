"""One synchronized Channel contract for the in-process and mailbox transports.

Every law here is transport-independent: identity is derived, history is
retained, a cut cannot shift beneath a reader, and an acknowledgement is a
delivery fact rather than proof that a component consumed anything (I4, I6).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import FakeClock

from constructicon.core.address import (
    ExecutionPath,
    IterationFrame,
    RunId,
    ScopePath,
)
from constructicon.core.channel import (
    Channel,
    ChannelAckConflict,
    ChannelContract,
    ChannelMessage,
    ChannelReplyConflict,
    ChannelRevision,
    ChannelSendIntent,
    InvalidChannelRevision,
    request_message_id,
)
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import JsonValue, canonical_json, digest
from constructicon.substrate.channels.in_process import InProcessChannel
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal

CHANNEL_ID = "channel/review"
CHANNEL_REVISION = "1"
ADVISOR = "static:advisor"
RUN = RunId("run-channel-contract")
SCOPE = ScopePath(segments=("review",))
PATH = ExecutionPath(scope=SCOPE)
REQUEST_CONTRACT = ChannelContract(
    type_id="test/AdviceRequest",
    schema_hash="advice-request-v1",
)
REPLY_CONTRACT = ChannelContract(
    type_id="test/AdviceResponse",
    schema_hash="advice-response-v1",
)
ATTESTATION = "att-channel-contract"


@pytest.fixture(params=("in_process", "mailbox"))
def channel(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    clock: FakeClock,
) -> Channel:
    if request.param == "in_process":
        return InProcessChannel(channel_id=CHANNEL_ID, now_fn=clock.now)
    journal = SqliteJournal(tmp_path / "channels.db", now_fn=clock.now)
    return MailboxChannel(journal, channel_id=CHANNEL_ID)


def _intent(
    *,
    port: str = "request",
    reply_port: str = "reply",
    payload: JsonValue | None = None,
    path: ExecutionPath = PATH,
    recipient: str | None = ADVISOR,
) -> ChannelSendIntent:
    return ChannelSendIntent(
        message_id=request_message_id(
            run_id=RUN,
            path=path,
            channel_id=CHANNEL_ID,
            channel_revision=CHANNEL_REVISION,
            lane="review",
            interaction="advice",
            port=port,
        ),
        channel_id=CHANNEL_ID,
        channel_revision=CHANNEL_REVISION,
        lane="review",
        interaction="advice",
        recipient_actor_id=recipient,
        contract=REQUEST_CONTRACT,
        reply_contract=REPLY_CONTRACT,
        run_id=RUN,
        path=path,
        port=port,
        reply_port=reply_port,
        payload={"question": "ship it?"} if payload is None else payload,
    )


def test_an_identical_send_returns_one_exact_fact_without_inventing_a_time(
    channel: Channel,
    clock: FakeClock,
) -> None:
    """A reconstructed send reconciles; it never stamps a second observation."""

    intent = _intent()
    first = channel.append_request(intent, ATTESTATION)
    clock.advance(3600)  # a later host retries long after the original stamp
    second = channel.append_request(intent, ATTESTATION)
    assert second == first
    assert second.envelope.created_at == first.envelope.created_at
    assert channel.message(intent.message_id) == first


def test_a_contradictory_intent_under_one_derived_id_is_damage(channel: Channel) -> None:
    intent = _intent()
    channel.append_request(intent, ATTESTATION)
    # Same derived id, different payload: not an idempotent retry.
    contradiction = intent.model_copy(update={"payload": {"question": "different"}})
    with pytest.raises(JournalDamaged, match="different logical intent"):
        channel.append_request(contradiction, ATTESTATION)


def test_a_send_under_a_foreign_attestation_is_damage(channel: Channel) -> None:
    intent = _intent()
    channel.append_request(intent, ATTESTATION)
    with pytest.raises(JournalDamaged, match="different logical intent"):
        channel.append_request(intent, "att-someone-else")


def test_loop_frames_and_ports_produce_distinct_request_identities(channel: Channel) -> None:
    first_frame = ExecutionPath(
        scope=SCOPE,
        iterations=(IterationFrame(loop=SCOPE, index=0),),
    )
    second_frame = ExecutionPath(
        scope=SCOPE,
        iterations=(IterationFrame(loop=SCOPE, index=1),),
    )
    identities = {
        str(_intent(path=PATH).message_id),
        str(_intent(path=first_frame).message_id),
        str(_intent(path=second_frame).message_id),
        str(_intent(port="second-request").message_id),
    }
    assert len(identities) == 4  # one invocation, one bound port, one request


def test_a_reply_is_typed_by_its_request_and_acknowledges_it(channel: Channel) -> None:
    request = channel.append_request(_intent(), ATTESTATION)
    reply = channel.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-reply-1",
    )
    assert reply.kind == "reply"
    assert reply.reply_to == request.message_id
    assert reply.sender_actor_id == ADVISOR
    assert reply.contract == REPLY_CONTRACT  # the request pinned this, not the caller
    assert reply.envelope.port == "reply"
    assert reply.reply_contract is None and reply.reply_port is None
    assert channel.reply_for(request.message_id) == reply
    page = channel.inbox(
        actor_id=ADVISOR,
        revision=channel.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    assert [delivery.acknowledged for delivery in page] == [True]  # the reply acked it


def test_an_identical_reply_retry_returns_one_exact_fact(
    channel: Channel,
    clock: FakeClock,
) -> None:
    request = channel.append_request(_intent(), ATTESTATION)
    first = channel.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-reply-1",
    )
    clock.advance(600)
    second = channel.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-reply-1",
    )
    assert second == first
    assert channel.latest_revision(ADVISOR).message_seq == 2  # no third message


def test_a_second_different_reply_is_refused_as_a_lost_race(channel: Channel) -> None:
    """Two processes replying concurrently admit one exact reply."""

    request = channel.append_request(_intent(), ATTESTATION)
    channel.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-reply-1",
    )
    with pytest.raises(ChannelReplyConflict, match="already carries a different reply"):
        channel.reply(
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "hold"},
            command_id="cmd-reply-2",
        )


def test_replying_to_an_unknown_request_is_refused(channel: Channel) -> None:
    missing = digest("channel-message", 1, {"absent": True})
    with pytest.raises(ContractViolation, match="no channel request"):
        channel.reply(
            request_id=missing,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            command_id="cmd-reply-1",
        )


def test_acknowledgement_retains_history_and_never_claims_consumption(
    channel: Channel,
) -> None:
    request = channel.append_request(_intent(), ATTESTATION)
    first = channel.acknowledge(
        message_id=request.message_id,
        actor_id=ADVISOR,
        command_id="cmd-ack-1",
    )
    second = channel.acknowledge(
        message_id=request.message_id,
        actor_id=ADVISOR,
        command_id="cmd-ack-1",
    )
    assert second == first
    page = channel.inbox(
        actor_id=ADVISOR,
        revision=channel.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    assert [delivery.message for delivery in page] == [request]  # ack removed nothing
    assert page[0].acknowledged is True
    assert channel.reply_for(request.message_id) is None  # and consumed nothing


def test_one_command_cannot_acknowledge_two_messages(channel: Channel) -> None:
    first = channel.append_request(_intent(), ATTESTATION)
    second = channel.append_request(_intent(port="second-request"), ATTESTATION)
    channel.acknowledge(
        message_id=first.message_id,
        actor_id=ADVISOR,
        command_id="cmd-ack-1",
    )
    with pytest.raises(JournalDamaged, match="already acknowledged a different message"):
        channel.acknowledge(
            message_id=second.message_id,
            actor_id=ADVISOR,
            command_id="cmd-ack-1",
        )


def test_inbox_bounds_reject_zero_negative_and_excessive_sizes(channel: Channel) -> None:
    revision = channel.latest_revision(ADVISOR)
    for limit in (0, -1):
        with pytest.raises(ValueError, match="limit must be positive"):
            channel.inbox(actor_id=ADVISOR, revision=revision, after=None, limit=limit)
    with pytest.raises(ValueError, match="exceeds channel max_batch"):
        channel.inbox(actor_id=ADVISOR, revision=revision, after=None, limit=10_000)


def test_inbox_order_is_total_for_tied_timestamps(channel: Channel) -> None:
    """The clock never advances here; durable sequence still totally orders."""

    ports = ("request", "second-request", "third-request")
    sent = [channel.append_request(_intent(port=port), ATTESTATION) for port in ports]
    assert len({message.envelope.created_at for message in sent}) == 1  # all tied
    revision = channel.latest_revision(ADVISOR)
    first = channel.inbox(actor_id=ADVISOR, revision=revision, after=None, limit=2)
    assert [delivery.message for delivery in first] == sent[:2]
    cursor = (first[-1].message_seq, str(first[-1].message.message_id))
    rest = channel.inbox(actor_id=ADVISOR, revision=revision, after=cursor, limit=2)
    assert [delivery.message for delivery in rest] == sent[2:]


def test_an_old_revision_neither_absorbs_nor_loses_a_later_message_or_ack(
    channel: Channel,
) -> None:
    first = channel.append_request(_intent(), ATTESTATION)
    old = channel.latest_revision(ADVISOR)
    later = channel.append_request(_intent(port="second-request"), ATTESTATION)
    channel.acknowledge(
        message_id=first.message_id,
        actor_id=ADVISOR,
        command_id="cmd-ack-1",
    )

    at_old = channel.inbox(actor_id=ADVISOR, revision=old, after=None, limit=10)
    assert [delivery.message for delivery in at_old] == [first]  # the later send is invisible
    assert at_old[0].acknowledged is False  # and so is the later ack

    fresh = channel.latest_revision(ADVISOR)
    at_fresh = channel.inbox(actor_id=ADVISOR, revision=fresh, after=None, limit=10)
    assert [delivery.message for delivery in at_fresh] == [first, later]
    assert [delivery.acknowledged for delivery in at_fresh] == [True, False]


def test_a_future_or_incoherent_revision_is_refused(channel: Channel) -> None:
    channel.append_request(_intent(), ATTESTATION)
    current = channel.latest_revision(ADVISOR)
    for ahead in (
        ChannelRevision(message_seq=current.message_seq + 1, ack_seq=current.ack_seq),
        ChannelRevision(message_seq=current.message_seq, ack_seq=current.ack_seq + 1),
    ):
        with pytest.raises(InvalidChannelRevision, match="ahead of retained history"):
            channel.inbox(actor_id=ADVISOR, revision=ahead, after=None, limit=10)


def test_an_inbox_shows_only_messages_addressed_to_that_actor(channel: Channel) -> None:
    mine = channel.append_request(_intent(), ATTESTATION)
    channel.append_request(
        _intent(port="second-request", recipient="static:someone-else"),
        ATTESTATION,
    )
    page = channel.inbox(
        actor_id=ADVISOR,
        revision=channel.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    assert [delivery.message for delivery in page] == [mine]


def test_a_foreign_channel_intent_is_refused(channel: Channel) -> None:
    stranger = _intent().model_copy(update={"channel_id": "channel/other"})
    with pytest.raises(ContractViolation, match="not 'channel/review'"):
        channel.append_request(stranger, ATTESTATION)


def test_in_process_history_honestly_does_not_survive_a_new_instance(
    clock: FakeClock,
) -> None:
    first = InProcessChannel(channel_id=CHANNEL_ID, now_fn=clock.now)
    request = first.append_request(_intent(), ATTESTATION)
    assert first.profile.durability == "process"
    successor = InProcessChannel(channel_id=CHANNEL_ID, now_fn=clock.now)
    assert successor.message(request.message_id) is None  # no false durability


def test_mailbox_history_and_identities_survive_a_reopen(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    path = tmp_path / "mailbox.db"
    first = MailboxChannel(SqliteJournal(path, now_fn=clock.now), channel_id=CHANNEL_ID)
    request = first.append_request(_intent(), ATTESTATION)
    reply = first.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-reply-1",
    )
    assert first.profile.durability == "sqlite_wal"

    reopened = MailboxChannel(SqliteJournal(path, now_fn=clock.now), channel_id=CHANNEL_ID)
    assert reopened.message(request.message_id) == request
    assert reopened.reply_for(request.message_id) == reply
    page = reopened.inbox(
        actor_id=ADVISOR,
        revision=reopened.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    assert [delivery.message for delivery in page] == [request]
    assert page[0].acknowledged is True


def test_a_reconstructed_send_after_reopen_returns_the_original_message(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """The identity law survives process death: no second message, no new time."""

    path = tmp_path / "mailbox.db"
    intent = _intent()
    first = MailboxChannel(SqliteJournal(path, now_fn=clock.now), channel_id=CHANNEL_ID)
    original = first.append_request(intent, ATTESTATION)

    clock.advance(86_400)
    reopened = MailboxChannel(SqliteJournal(path, now_fn=clock.now), channel_id=CHANNEL_ID)
    reconstructed = reopened.append_request(intent, ATTESTATION)
    assert reconstructed == original
    assert reopened.latest_revision(ADVISOR).message_seq == 1


def test_both_transports_publish_an_honest_profile(tmp_path: Path) -> None:
    """Durability is the only guarantee the two transports may disagree about."""

    in_process = InProcessChannel(channel_id=CHANNEL_ID).profile
    mailbox = MailboxChannel(
        SqliteJournal(tmp_path / "profile.db"),
        channel_id=CHANNEL_ID,
    ).profile
    assert in_process.durability == "process"
    assert mailbox.durability == "sqlite_wal"
    for profile in (in_process, mailbox):
        assert profile.delivery == "at_least_once"  # never claims exactly-once
        assert profile.history == "retained"  # never claims a destructive dequeue
    assert in_process.model_dump(exclude={"durability"}) == mailbox.model_dump(
        exclude={"durability"}
    )


def test_two_hosts_replying_concurrently_admit_one_exact_reply(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Two independent handles on one database are two hosts: one reply wins."""

    path = tmp_path / "race.db"
    first = MailboxChannel(SqliteJournal(path, now_fn=clock.now), channel_id=CHANNEL_ID)
    second = MailboxChannel(SqliteJournal(path, now_fn=clock.now), channel_id=CHANNEL_ID)
    request = first.append_request(_intent(), ATTESTATION)

    winner = first.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-host-a",
    )
    with pytest.raises(ChannelReplyConflict, match="already carries a different reply"):
        second.reply(
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "hold"},
            command_id="cmd-host-b",
        )
    assert second.reply_for(request.message_id) == winner  # the loser observes the winner


def test_a_second_host_replaying_the_same_reply_sees_one_exact_fact(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    path = tmp_path / "replay.db"
    first = MailboxChannel(SqliteJournal(path, now_fn=clock.now), channel_id=CHANNEL_ID)
    second = MailboxChannel(SqliteJournal(path, now_fn=clock.now), channel_id=CHANNEL_ID)
    request = first.append_request(_intent(), ATTESTATION)
    original = first.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-host-a",
    )

    clock.advance(900)
    replayed = second.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-host-a",
    )
    assert replayed == original  # no second reply, no second observation time
    assert second.latest_revision(ADVISOR).message_seq == 2


# Every ChannelSendIntent field must be reachable by ONE of two protections:
# it feeds the derived message id (so a change yields a different message), or
# it lands on the durable message (so a change under one id is a contradiction).
# A field protected by neither could silently differ between two sends.
_ID_INPUTS = frozenset(
    {"run_id", "path", "channel_id", "channel_revision", "lane", "interaction", "port"}
)
_ON_MESSAGE = frozenset(
    {
        "message_id",
        "channel_id",
        "lane",
        "interaction",
        "recipient_actor_id",
        "contract",
        "reply_contract",
        "reply_port",
        "run_id",
        "path",
        "port",
        "payload",
        "schema_version",
    }
)


def test_no_intent_field_escapes_both_identity_and_retry_equality() -> None:
    """A new intent field must change the id or be caught as a contradiction."""

    assert set(ChannelSendIntent.model_fields) - _ID_INPUTS - _ON_MESSAGE == set()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recipient_actor_id", "static:someone-else"),
        ("contract", REPLY_CONTRACT),
        ("reply_contract", REQUEST_CONTRACT),
        ("reply_port", "other-reply"),
        ("payload", {"question": "different"}),
    ],
)
def test_a_field_outside_the_derived_id_cannot_differ_silently(
    channel: Channel,
    field: str,
    value: object,
) -> None:
    """These fields share one message id, so a change is contradiction, not a retry."""

    base = _intent()
    channel.append_request(base, ATTESTATION)
    divergent = base.model_copy(update={field: value})
    assert divergent.message_id == base.message_id  # same derived identity
    with pytest.raises(JournalDamaged, match="different logical intent"):
        channel.append_request(divergent, ATTESTATION)


@pytest.mark.parametrize(
    "field",
    ["channel_revision", "lane", "interaction", "port"],
)
def test_a_field_inside_the_derived_id_produces_a_distinct_request(field: str) -> None:
    changed = request_message_id(
        run_id=RUN,
        path=PATH,
        channel_id=CHANNEL_ID,
        channel_revision="2" if field == "channel_revision" else CHANNEL_REVISION,
        lane="other-lane" if field == "lane" else "review",
        interaction="approval" if field == "interaction" else "advice",
        port="other-port" if field == "port" else "request",
    )
    assert changed != _intent().message_id  # a different request, never a collision


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"value": 1}, {"value": True}),
        ({"value": 1}, {"value": 1.0}),
        ({"value": 0}, {"value": False}),
    ],
)
def test_a_payload_differing_only_by_json_scalar_type_is_a_contradiction(
    channel: Channel,
    first: JsonValue,
    second: JsonValue,
) -> None:
    """Identity is a bytes law, not Python equality, where 1 == True == 1.0."""

    original = channel.append_request(_intent(payload=first), ATTESTATION)
    assert canonical_json(first) != canonical_json(second)  # genuinely different facts
    with pytest.raises(JournalDamaged, match="different logical intent"):
        channel.append_request(_intent(payload=second), ATTESTATION)
    assert channel.message(original.message_id) == original  # and nothing was replaced


def test_a_refused_acknowledgement_leaves_no_orphan_reply(channel: Channel) -> None:
    """A reply and its ack are one fact: a refused ack appends no reply."""

    other = channel.append_request(_intent(port="second-request"), ATTESTATION)
    request = channel.append_request(_intent(), ATTESTATION)
    channel.acknowledge(
        message_id=other.message_id,
        actor_id=ADVISOR,
        command_id="cmd-shared",
    )
    with pytest.raises(JournalDamaged, match="already acknowledged a different message"):
        channel.reply(
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            command_id="cmd-shared",
        )
    assert channel.reply_for(request.message_id) is None  # nothing was appended
    assert channel.latest_revision(ADVISOR).message_seq == 2


def test_one_channels_revision_is_never_advanced_by_another_channel(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Two mailboxes share one database; a cut still describes one channel."""

    journal = SqliteJournal(tmp_path / "two-channels.db", now_fn=clock.now)
    mine = MailboxChannel(journal, channel_id=CHANNEL_ID)
    theirs = MailboxChannel(journal, channel_id="channel/other")
    mine.append_request(_intent(), ATTESTATION)
    quiet = mine.latest_revision(ADVISOR)

    other_intent = _intent().model_copy(
        update={
            "channel_id": "channel/other",
            "message_id": request_message_id(
                run_id=RUN,
                path=PATH,
                channel_id="channel/other",
                channel_revision=CHANNEL_REVISION,
                lane="review",
                interaction="advice",
                port="request",
            ),
        }
    )
    theirs.append_request(other_intent, ATTESTATION)
    assert mine.latest_revision(ADVISOR) == quiet  # unrelated traffic moved nothing
    assert theirs.latest_revision(ADVISOR) != quiet


def test_paging_an_actor_whose_messages_are_sparse_never_redelivers(
    channel: Channel,
) -> None:
    """A page must carry its own continuation key.

    One actor's messages are sparse in a shared history, so a cursor derived
    from page position rather than durable sequence redelivers rows forever.
    """

    ports = [f"request-{index}" for index in range(6)]
    for index, port in enumerate(ports):
        recipient = ADVISOR if index % 2 == 0 else "static:other-advisor"
        channel.append_request(_intent(port=port, recipient=recipient), ATTESTATION)
    revision = channel.latest_revision(ADVISOR)

    seen: list[str] = []
    cursor: tuple[int, str] | None = None
    for _ in range(6):
        page = channel.inbox(actor_id=ADVISOR, revision=revision, after=cursor, limit=2)
        if not page:
            break
        seen.extend(delivery.message.envelope.port for delivery in page)
        cursor = (page[-1].message_seq, str(page[-1].message.message_id))

    assert seen == ["request-0", "request-2", "request-4"]  # every one, exactly once
    assert len(seen) == len(set(seen))


def test_a_delivery_reports_the_durable_sequence_not_its_page_position(
    channel: Channel,
) -> None:
    channel.append_request(_intent(recipient="static:other-advisor"), ATTESTATION)
    mine = channel.append_request(_intent(port="second-request"), ATTESTATION)
    page = channel.inbox(
        actor_id=ADVISOR,
        revision=channel.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    assert [delivery.message for delivery in page] == [mine]
    assert page[0].message_seq == 2  # second in history, first in this page


def test_only_the_sealed_recipient_may_answer_an_addressed_request(
    channel: Channel,
) -> None:
    """One reply per request, so an interloper could lock the recipient out."""

    request = channel.append_request(_intent(), ATTESTATION)
    with pytest.raises(ContractViolation, match="may not answer it"):
        channel.reply(
            request_id=request.message_id,
            actor_id="static:interloper",
            payload={"advice": "mine now"},
            command_id="cmd-interloper",
        )
    assert channel.reply_for(request.message_id) is None  # still answerable

    reply = channel.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-reply-1",
    )
    assert reply.sender_actor_id == ADVISOR


def test_an_unaddressed_request_admits_any_authenticated_actor(
    channel: Channel,
) -> None:
    """Only an explicitly unassigned request is open to whoever picks it up."""

    request = channel.append_request(_intent(recipient=None), ATTESTATION)
    reply = channel.reply(
        request_id=request.message_id,
        actor_id="static:whoever",
        payload={"advice": "ship"},
        command_id="cmd-open",
    )
    assert reply.sender_actor_id == "static:whoever"


def _page(channel: Channel, actor_id: str) -> list[ChannelMessage]:
    return [
        delivery.message
        for delivery in channel.inbox(
            actor_id=actor_id,
            revision=channel.latest_revision(actor_id),
            after=None,
            limit=10,
        )
    ]


def test_an_open_request_is_discoverable_by_every_actor(channel: Channel) -> None:
    """An unsealed recipient is a routing decision, not missing routing.

    Whoever holds the interaction's scope may take an open request, so it must
    be findable by them; an approved decision reachable only through a leaked
    digest would not be discoverable at all (I9). An addressed request stays
    private to the actor it names.
    """

    open_request = channel.append_request(_intent(recipient=None), ATTESTATION)
    addressed = channel.append_request(_intent(port="addressed"), ATTESTATION)

    assert _page(channel, ADVISOR) == [open_request, addressed]
    assert _page(channel, "static:whoever") == [open_request]


def test_a_reply_is_never_broadcast_to_an_inbox(channel: Channel) -> None:
    """A reply's null recipient means the opposite of an open request's.

    It is addressed to the run, not withheld from a person, so matching a null
    recipient rather than the message kind would put every reply in everybody's
    inbox — including actors with no part in the exchange.
    """

    request = channel.append_request(_intent(), ATTESTATION)
    reply = channel.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-not-broadcast",
    )
    assert reply.recipient_actor_id is None

    assert _page(channel, ADVISOR) == [request]
    assert _page(channel, "static:whoever") == []


def test_the_first_reply_to_an_open_request_wins(channel: Channel) -> None:
    """Anyone may answer an open request; exactly one answer exists.

    The winner's acknowledgement is atomic with its reply, and a loser may
    still record its own delivery fact against the retained request.
    """

    request = channel.append_request(_intent(recipient=None), ATTESTATION)
    winner = channel.reply(
        request_id=request.message_id,
        actor_id="static:first",
        payload={"advice": "ship"},
        command_id="cmd-first",
    )
    with pytest.raises(ChannelReplyConflict):
        channel.reply(
            request_id=request.message_id,
            actor_id="static:second",
            payload={"advice": "hold"},
            command_id="cmd-second",
        )
    assert channel.reply_for(request.message_id) == winner

    page = channel.inbox(
        actor_id="static:first",
        revision=channel.latest_revision("static:first"),
        after=None,
        limit=10,
    )
    assert [delivery.acknowledged for delivery in page] == [True]
    loser = channel.acknowledge(
        message_id=request.message_id,
        actor_id="static:second",
        command_id="cmd-second-ack",
    )
    assert loser.actor_id == "static:second"


def test_a_stale_message_id_on_an_intent_is_refused_at_the_transport(
    channel: Channel,
) -> None:
    """`model_copy` skips validators, so the transport re-derives the id itself."""

    forged = _intent().model_copy(update={"lane": "other-lane"})
    with pytest.raises(ContractViolation, match="derive"):
        channel.append_request(forged, ATTESTATION)


def test_a_revision_may_not_acknowledge_a_message_it_excludes(
    channel: Channel,
) -> None:
    """Bounds alone do not make a cut real; it must be causally coherent."""

    first = channel.append_request(_intent(), ATTESTATION)
    second = channel.append_request(_intent(port="second-request"), ATTESTATION)
    channel.acknowledge(
        message_id=second.message_id,
        actor_id=ADVISOR,
        command_id="cmd-ack-second",
    )
    current = channel.latest_revision(ADVISOR)
    torn = ChannelRevision(message_seq=1, ack_seq=current.ack_seq)
    assert first.message_id != second.message_id
    with pytest.raises(InvalidChannelRevision, match="does not include"):
        channel.inbox(actor_id=ADVISOR, revision=torn, after=None, limit=10)


def test_a_second_command_may_not_claim_an_existing_acknowledgement(
    channel: Channel,
) -> None:
    """One delivery fact, one owning command: else one command addresses two."""

    first = channel.append_request(_intent(), ATTESTATION)
    second = channel.append_request(_intent(port="second-request"), ATTESTATION)
    channel.acknowledge(
        message_id=first.message_id,
        actor_id=ADVISOR,
        command_id="cmd-one",
    )
    with pytest.raises(ChannelAckConflict, match="may not claim it"):
        channel.acknowledge(
            message_id=first.message_id,
            actor_id=ADVISOR,
            command_id="cmd-two",
        )
    # ...and cmd-two therefore never became free to address a second message.
    channel.acknowledge(
        message_id=second.message_id,
        actor_id=ADVISOR,
        command_id="cmd-two",
    )
