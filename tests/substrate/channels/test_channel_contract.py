"""One synchronized Channel contract for the in-process and mailbox transports.

Every law here is transport-independent: identity is derived, history is
retained, a cut cannot shift beneath a reader, and an acknowledgement is a
delivery fact rather than proof that a component consumed anything (I4, I6).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.channel_commands import (
    ack_command_id,
    ack_with_command,
    prepare_reply_command,
    reply_command_id,
    reply_with_command,
)
from tests.channel_requests import (
    AttestedMailboxChannel as MailboxChannel,
)
from tests.channel_requests import (
    mint_send_attestation,
)
from tests.conftest import FakeClock
from tests.durable_seals import reseal_primary_fact

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
    ChannelInteraction,
    ChannelMessage,
    ChannelReplyConflict,
    ChannelRevision,
    ChannelSendIntent,
    InvalidChannelRevision,
    request_message_id,
)
from constructicon.core.control import CommandClaim, command_id_for
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.human import (
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
)
from constructicon.core.identity import JsonValue, canonical_json, digest
from constructicon.substrate.channels.in_process import InProcessChannel
from constructicon.substrate.journal._sqlite_channels import seal_channel_ack
from constructicon.substrate.journal._sqlite_commands import command_plan_fact_hash
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
    interaction: ChannelInteraction = "advice",
) -> ChannelSendIntent:
    return ChannelSendIntent(
        message_id=request_message_id(
            run_id=RUN,
            path=path,
            channel_id=CHANNEL_ID,
            channel_revision=CHANNEL_REVISION,
            lane="review",
            interaction=interaction,
            port=port,
        ),
        channel_id=CHANNEL_ID,
        channel_revision=CHANNEL_REVISION,
        lane="review",
        interaction=interaction,
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


def _nested_payload(payload: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(payload, dict)
    nested = payload["nested"]
    assert isinstance(nested, dict)
    return nested


def _seed_orphan_ack_owned_by_reply_command(
    channel: Channel,
    *,
    planned_request: ChannelMessage,
    acknowledged_request: ChannelMessage,
    idempotency_key: str,
) -> None:
    """Construct impossible history without weakening the current writer."""

    command_id = reply_command_id(ADVISOR, idempotency_key)
    if isinstance(channel, MailboxChannel):
        prepare_reply_command(
            channel,
            request_id=planned_request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            idempotency_key=idempotency_key,
        )
        with channel._journal._txn() as connection:
            connection.execute(
                "INSERT INTO channel_acks (message_id, actor_id, command_id,"
                " acked_at, ack_provenance_version) VALUES (?, ?, ?, ?, 1)",
                (
                    str(acknowledged_request.message_id),
                    ADVISOR,
                    command_id,
                    acknowledged_request.envelope.created_at.isoformat(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM channel_acks WHERE message_id = ? AND actor_id = ?",
                (str(acknowledged_request.message_id), ADVISOR),
            ).fetchone()
            assert row is not None
            seal_channel_ack(connection, row)
        return
    channel.acknowledge(
        message_id=acknowledged_request.message_id,
        actor_id=ADVISOR,
        command_id=command_id,
    )


def _retained_claim(journal: SqliteJournal, command_id: str) -> CommandClaim:
    record = journal.command(command_id)
    assert record is not None
    assert record.owner_id is not None
    assert record.lease_expires_at is not None
    return CommandClaim(
        command_id=record.command_id,
        actor_id=record.actor.actor_id,
        operation=record.operation,
        owner_id=record.owner_id,
        epoch=record.owner_epoch,
        expires_at=record.lease_expires_at,
    )


def _rebuild_channel_messages_with_projection(
    database: Path,
    *,
    column: str,
    projection: str,
) -> None:
    """Change one SQLite storage class without relying on column affinity."""

    with sqlite3.connect(database) as connection:
        columns = [
            str(row[1])
            for row in connection.execute("PRAGMA table_info(channel_messages)")
        ]
        assert column in columns
        connection.execute("ALTER TABLE channel_messages RENAME TO exact_channel_messages")
        connection.execute(f"CREATE TABLE channel_messages ({', '.join(columns)})")
        projected = [projection if name == column else name for name in columns]
        connection.execute(
            f"INSERT INTO channel_messages ({', '.join(columns)}) "
            f"SELECT {', '.join(projected)} FROM exact_channel_messages"
        )
        connection.execute("DROP TABLE exact_channel_messages")
        maximum = connection.execute(
            "SELECT COUNT(*) FROM channel_messages"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES ('channel_messages', ?)",
            (maximum,),
        )


def test_request_history_is_detached_from_inputs_and_every_returned_view(
    channel: Channel,
) -> None:
    payload: JsonValue = {"nested": {"value": "original"}}
    returned = channel.append_request(_intent(payload=payload), ATTESTATION)

    _nested_payload(payload)["value"] = "input-mutated"
    assert _nested_payload(returned.envelope.payload)["value"] == "original"

    _nested_payload(returned.envelope.payload)["value"] = "return-mutated"
    loaded = channel.message(returned.message_id)
    assert loaded is not None
    assert _nested_payload(loaded.envelope.payload)["value"] == "original"

    _nested_payload(loaded.envelope.payload)["value"] = "read-mutated"
    page = channel.inbox(
        actor_id=ADVISOR,
        revision=channel.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    assert _nested_payload(page[0].message.envelope.payload)["value"] == "original"

    _nested_payload(page[0].message.envelope.payload)["value"] = "page-mutated"
    reloaded = channel.message(returned.message_id)
    assert reloaded is not None
    assert _nested_payload(reloaded.envelope.payload)["value"] == "original"


def test_reply_history_is_detached_from_inputs_and_every_returned_view(
    channel: Channel,
) -> None:
    request = channel.append_request(_intent(), ATTESTATION)
    payload: JsonValue = {"nested": {"value": "original"}}
    returned = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload=payload,
        idempotency_key="cmd-detached-reply",
    )

    _nested_payload(payload)["value"] = "input-mutated"
    assert _nested_payload(returned.envelope.payload)["value"] == "original"

    _nested_payload(returned.envelope.payload)["value"] = "return-mutated"
    loaded = channel.reply_for(request.message_id)
    assert loaded is not None
    assert _nested_payload(loaded.envelope.payload)["value"] == "original"

    _nested_payload(loaded.envelope.payload)["value"] = "read-mutated"
    by_id = channel.message(returned.message_id)
    assert by_id is not None
    assert _nested_payload(by_id.envelope.payload)["value"] == "original"

    _nested_payload(by_id.envelope.payload)["value"] = "message-mutated"
    replayed = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"nested": {"value": "original"}},
        idempotency_key="cmd-detached-reply",
    )
    _nested_payload(replayed.envelope.payload)["value"] = "replay-mutated"
    final = channel.reply_for(request.message_id)
    assert final is not None
    assert _nested_payload(final.envelope.payload)["value"] == "original"


def test_in_process_reply_evidence_is_an_independent_bytes_snapshot() -> None:
    """The process transport keeps evidence separate from mutable message JSON."""

    channel = InProcessChannel(channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    reply = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"nested": {"value": 1}},
        idempotency_key="independent-proof",
    )
    retained = channel._by_id[str(reply.message_id)]
    _nested_payload(retained.envelope.payload)["value"] = True

    with pytest.raises(JournalDamaged, match="independently stored proof"):
        channel.message(reply.message_id)


@pytest.mark.parametrize(
    "projection",
    ("message", "inbox", "retry", "reply", "reply_for", "acknowledge"),
)
def test_in_process_request_evidence_is_an_independent_bytes_snapshot(
    projection: str,
) -> None:
    """Process memory corruption cannot rewrite an already admitted request."""

    channel = InProcessChannel(channel_id=CHANNEL_ID)
    intent = _intent(payload={"nested": {"value": 1}})
    request = channel.append_request(intent, ATTESTATION)
    if projection == "reply_for":
        reply_with_command(
            channel,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            idempotency_key="request-proof-reply",
        )
    retained = channel._by_id[str(request.message_id)]
    _nested_payload(retained.envelope.payload)["value"] = True

    with pytest.raises(JournalDamaged, match="independent intent proof"):
        if projection == "message":
            channel.message(request.message_id)
        elif projection == "inbox":
            channel.inbox(
                actor_id=ADVISOR,
                revision=channel.latest_revision(ADVISOR),
                after=None,
                limit=10,
            )
        elif projection == "retry":
            channel.append_request(intent, ATTESTATION)
        elif projection == "reply":
            reply_with_command(
                channel,
                request_id=request.message_id,
                actor_id=ADVISOR,
                payload={"advice": "ship"},
                idempotency_key="request-proof-new-reply",
            )
        elif projection == "reply_for":
            channel.reply_for(request.message_id)
        else:
            assert projection == "acknowledge"
            channel.acknowledge(
                message_id=request.message_id,
                actor_id=ADVISOR,
                command_id="request-proof-ack",
            )


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
    foreign = "att-someone-else"
    if isinstance(channel, MailboxChannel):
        foreign = mint_send_attestation(
            channel._journal,
            _intent(port="foreign-attestation"),
        ).attestation_id
    with pytest.raises(JournalDamaged, match="different logical intent"):
        channel.append_request(intent, foreign)


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
    reply = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-reply-1",
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


@pytest.mark.parametrize("transport", ("in_process", "mailbox"))
def test_reply_and_implied_ack_share_one_atomic_observation(
    transport: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Both transports construct the reply and its ack from one clock read."""

    class FailThirdObservation:
        def __init__(self) -> None:
            self.calls = 0

        def now(self):
            self.calls += 1
            if self.calls == 3:
                raise RuntimeError("timestamp unavailable")
            return clock.now()

    observations = FailThirdObservation()
    channel: Channel
    if transport == "in_process":
        channel = InProcessChannel(channel_id=CHANNEL_ID, now_fn=observations.now)
    else:
        channel = MailboxChannel(
            SqliteJournal(tmp_path / "clock-fault.db", now_fn=observations.now),
            channel_id=CHANNEL_ID,
        )
    request = channel.append_request(_intent(), ATTESTATION)
    reply = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-clock-fault",
    )
    replayed = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-clock-fault",
    )

    assert observations.calls == 2  # request once, then the whole reply exchange once
    assert replayed == reply
    assert channel.reply_for(request.message_id) == reply
    page = channel.inbox(
        actor_id=ADVISOR,
        revision=channel.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    assert [delivery.acknowledged for delivery in page] == [True]


@pytest.mark.parametrize("transport", ("in_process", "mailbox"))
def test_an_exact_ack_retry_does_not_invent_an_observation(
    transport: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    class FailThirdObservation:
        def __init__(self) -> None:
            self.calls = 0

        def now(self):
            self.calls += 1
            if self.calls == 3:
                raise RuntimeError("timestamp unavailable")
            return clock.now()

    observations = FailThirdObservation()
    channel: Channel
    if transport == "in_process":
        channel = InProcessChannel(channel_id=CHANNEL_ID, now_fn=observations.now)
    else:
        channel = MailboxChannel(
            SqliteJournal(tmp_path / "ack-clock-fault.db", now_fn=observations.now),
            channel_id=CHANNEL_ID,
        )
    request = channel.append_request(_intent(), ATTESTATION)
    first = ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-ack-clock-fault",
    )
    replayed = ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-ack-clock-fault",
    )

    assert replayed == first
    assert observations.calls == 2  # request once, then the first ack once


def test_an_identical_reply_retry_returns_one_exact_fact(
    channel: Channel,
    clock: FakeClock,
) -> None:
    request = channel.append_request(_intent(), ATTESTATION)
    first = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-reply-1",
    )
    clock.advance(600)
    second = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-reply-1",
    )
    assert second == first
    assert channel.latest_revision(ADVISOR).message_seq == 2  # no third message


def test_a_deleted_reply_cannot_be_hidden_or_replaced(channel: Channel) -> None:
    request = channel.append_request(_intent(), ATTESTATION)
    reply = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="deleted-reply-writer",
    )
    if isinstance(channel, MailboxChannel):
        with sqlite3.connect(channel._journal._db_path) as connection:
            connection.execute(
                "DELETE FROM channel_messages WHERE message_id = ?",
                (str(reply.message_id),),
            )
    else:
        assert isinstance(channel, InProcessChannel)
        channel._by_id.pop(str(reply.message_id))

    with pytest.raises(
        JournalDamaged,
        match=r"reply history|message .*history|fact-seal inventory",
    ):
        channel.reply_for(request.message_id)
    with pytest.raises(
        JournalDamaged,
        match=r"reply history|message .*history|fact-seal inventory",
    ):
        reply_with_command(
            channel,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "replacement"},
            idempotency_key="deleted-reply-contender",
        )


def test_a_second_different_reply_is_refused_as_a_lost_race(channel: Channel) -> None:
    """Two processes replying concurrently admit one exact reply."""

    request = channel.append_request(_intent(), ATTESTATION)
    reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-reply-1",
    )
    with pytest.raises(ChannelReplyConflict, match="already answered by another command"):
        reply_with_command(
            channel,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "hold"},
            idempotency_key="cmd-reply-2",
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


def test_generic_reply_cannot_partially_answer_an_approval(channel: Channel) -> None:
    """Only the request-bound approval transaction may write this exchange."""

    request = channel.append_request(_intent(interaction="approval"), ATTESTATION)

    with pytest.raises(ContractViolation, match="request-bound approval"):
        channel.reply(
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"decision": "approved"},
            command_id="cmd-generic-approval",
        )

    assert channel.reply_for(request.message_id) is None
    page = channel.inbox(
        actor_id=ADVISOR,
        revision=channel.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    assert len(page) == 1
    assert page[0].message == request
    assert page[0].acknowledged is False


@pytest.mark.parametrize(
    ("request_contract", "reply_contract"),
    (
        (APPROVAL_REQUEST_CONTRACT, APPROVAL_REPLY_CONTRACT),
        (APPROVAL_REQUEST_CONTRACT, REPLY_CONTRACT),
        (REQUEST_CONTRACT, APPROVAL_REPLY_CONTRACT),
    ),
)
def test_generic_reply_cannot_persist_an_incoherent_canonical_exchange(
    channel: Channel,
    request_contract: ChannelContract,
    reply_contract: ChannelContract,
) -> None:
    intent = _intent().model_copy(
        update={
            "contract": request_contract,
            "reply_contract": reply_contract,
        }
    )
    request = channel.append_request(intent, ATTESTATION)

    with pytest.raises(ContractViolation, match="incoherent exchange"):
        channel.reply(
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"decision": "approved"},
            command_id="cmd-incoherent-exchange",
        )

    assert channel.reply_for(request.message_id) is None
    page = channel.inbox(
        actor_id=ADVISOR,
        revision=channel.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    assert len(page) == 1
    assert page[0].message == request
    assert page[0].acknowledged is False


def test_acknowledgement_retains_history_and_never_claims_consumption(
    channel: Channel,
) -> None:
    request = channel.append_request(_intent(), ATTESTATION)
    first = ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-ack-1",
    )
    second = ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-ack-1",
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


def test_a_deleted_acknowledgement_cannot_be_recreated(channel: Channel) -> None:
    request = channel.append_request(_intent(), ATTESTATION)
    ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="deleted-ack-writer",
    )
    if isinstance(channel, MailboxChannel):
        with sqlite3.connect(channel._journal._db_path) as connection:
            connection.execute(
                "DELETE FROM channel_acks WHERE message_id = ? AND actor_id = ?",
                (str(request.message_id), ADVISOR),
            )
    else:
        assert isinstance(channel, InProcessChannel)
        key = (str(request.message_id), ADVISOR)
        channel._ack_by_key.pop(key)
        channel._acks.clear()

    with pytest.raises(
        JournalDamaged,
        match=r"acknowledgement .*history|fact-seal inventory",
    ):
        ack_with_command(
            channel,
            message_id=request.message_id,
            actor_id=ADVISOR,
            idempotency_key="deleted-ack-writer",
        )


def test_one_command_cannot_acknowledge_two_messages(channel: Channel) -> None:
    first = channel.append_request(_intent(), ATTESTATION)
    second = channel.append_request(_intent(port="second-request"), ATTESTATION)
    ack_with_command(
        channel,
        message_id=first.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-ack-1",
    )
    with pytest.raises(
        JournalDamaged,
        match=r"already acknowledged a different message|no reply written by its command",
    ):
        ack_with_command(
            channel,
            message_id=second.message_id,
            actor_id=ADVISOR,
            idempotency_key="cmd-ack-1",
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
    ack_with_command(
        channel,
        message_id=first.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-ack-1",
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
    reply = reply_with_command(
        first,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-reply-1",
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

    winner = reply_with_command(
        first,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-host-a",
    )
    with pytest.raises(ChannelReplyConflict, match="already answered by another command"):
        reply_with_command(
            second,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "hold"},
            idempotency_key="cmd-host-b",
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
    original = reply_with_command(
        first,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-host-a",
    )

    clock.advance(900)
    replayed = reply_with_command(
        second,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-host-a",
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
    _seed_orphan_ack_owned_by_reply_command(
        channel,
        planned_request=request,
        acknowledged_request=other,
        idempotency_key="cmd-shared",
    )
    with pytest.raises(
        JournalDamaged,
        match=r"already acknowledged a different message|no reply written by its command",
    ):
        reply_with_command(
            channel,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            idempotency_key="cmd-shared",
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

    reply = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-reply-1",
    )
    assert reply.sender_actor_id == ADVISOR


def test_an_unaddressed_request_admits_any_authenticated_actor(
    channel: Channel,
) -> None:
    """Only an explicitly unassigned request is open to whoever picks it up."""

    request = channel.append_request(_intent(recipient=None), ATTESTATION)
    reply = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id="static:whoever",
        payload={"advice": "ship"},
        idempotency_key="cmd-open",
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
    reply = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-not-broadcast",
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
    winner = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id="static:first",
        payload={"advice": "ship"},
        idempotency_key="cmd-first",
    )
    with pytest.raises(ChannelReplyConflict):
        reply_with_command(
            channel,
            request_id=request.message_id,
            actor_id="static:second",
            payload={"advice": "hold"},
            idempotency_key="cmd-second",
        )
    assert channel.reply_for(request.message_id) == winner

    page = channel.inbox(
        actor_id="static:first",
        revision=channel.latest_revision("static:first"),
        after=None,
        limit=10,
    )
    assert [delivery.acknowledged for delivery in page] == [True]
    loser = ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id="static:second",
        idempotency_key="cmd-second-ack",
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
    ack_with_command(
        channel,
        message_id=second.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-ack-second",
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
    ack_with_command(
        channel,
        message_id=first.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-one",
    )
    with pytest.raises(ChannelAckConflict, match="may not claim it"):
        ack_with_command(
            channel,
            message_id=first.message_id,
            actor_id=ADVISOR,
            idempotency_key="cmd-two",
        )
    # Its immutable plan still names the first request; a fresh command may
    # independently acknowledge the second.
    ack_with_command(
        channel,
        message_id=second.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-three",
    )


def test_acknowledging_first_does_not_forfeit_the_right_to_reply(channel: Channel) -> None:
    """A reply implies a delivery fact; it does not claim one.

    Both transports must agree, or an actor that acknowledged a request before
    answering it could answer through one and be locked out through the other
    (I6). For an addressed request nobody else could take it up either.
    """

    request = channel.append_request(_intent(), ATTESTATION)
    ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-ack-first",
    )
    reply = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-reply-after",
    )
    assert channel.reply_for(request.message_id) == reply


def test_a_reply_command_cannot_heal_its_own_orphan_ack(channel: Channel) -> None:
    """The same command's ack without its atomic reply is impossible history."""

    request = channel.append_request(_intent(), ATTESTATION)
    _seed_orphan_ack_owned_by_reply_command(
        channel,
        planned_request=request,
        acknowledged_request=request,
        idempotency_key="cmd-torn-reply",
    )

    with pytest.raises(
        JournalDamaged,
        match=r"acknowledgement without its reply|no reply written by its command",
    ):
        reply_with_command(
            channel,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            idempotency_key="cmd-torn-reply",
        )
    assert channel.reply_for(request.message_id) is None


@pytest.mark.parametrize("actor_id", (ADVISOR, "static:second-advisor"))
def test_an_explicit_ack_cannot_heal_a_torn_reply(
    channel: Channel,
    actor_id: str,
) -> None:
    """No later delivery observation may manufacture an atomic reply half."""

    request = channel.append_request(_intent(), ATTESTATION)
    reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="reply-before-torn-ack",
    )
    key = (str(request.message_id), ADVISOR)
    if isinstance(channel, InProcessChannel):
        torn = channel._ack_by_key.pop(key)
        channel._acks.remove(torn)
        owner = next(command for command, owned in channel._ack_commands.items() if owned == key)
        del channel._ack_commands[owner]
    else:
        assert isinstance(channel, MailboxChannel)
        with sqlite3.connect(channel._journal._db_path) as connection:
            connection.execute(
                "DELETE FROM channel_acks WHERE message_id = ? AND actor_id = ?",
                key,
            )

    with pytest.raises(
        JournalDamaged,
        match=r"acknowledgement|fact-seal inventory",
    ):
        channel.acknowledge(
            message_id=request.message_id,
            actor_id=actor_id,
            command_id=f"ack-after-torn-reply-{actor_id}",
        )


def test_a_complete_reply_does_not_block_an_independent_delivery_ack(
    channel: Channel,
) -> None:
    request = channel.append_request(_intent(recipient=None), ATTESTATION)
    reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="complete-before-second-ack",
    )

    observed = ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id="static:second-advisor",
        idempotency_key="second-actor-after-complete-reply",
    )

    assert observed.message_id == request.message_id
    assert observed.actor_id == "static:second-advisor"


@pytest.mark.parametrize("damage", ("downgrade", "missing-command", "missing-cutoff"))
def test_current_ack_provenance_cannot_be_downgraded_or_orphaned(
    damage: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"ack-provenance-{damage}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key=f"ack-provenance-{damage}",
    )
    command_id = command_id_for(
        ADVISOR,
        "channels_ack",
        f"ack-provenance-{damage}",
    )
    with sqlite3.connect(database) as connection:
        if damage == "downgrade":
            connection.execute(
                "UPDATE channel_acks SET ack_provenance_version = 0"
                " WHERE message_id = ? AND actor_id = ?",
                (str(request.message_id), ADVISOR),
            )
        elif damage == "missing-command":
            connection.execute(
                "DELETE FROM commands WHERE command_id = ?",
                (command_id,),
            )
        else:
            connection.execute("DROP TABLE channel_provenance")

    with pytest.raises(
        JournalDamaged,
        match=r"provenance|cutoff|positive claim seal|durable tables",
    ):
        journal.channel_ack(message_id=request.message_id, actor_id=ADVISOR)


@pytest.mark.parametrize("projection", ("exact", "inbox"))
def test_a_current_ack_is_projected_only_through_its_exact_typed_plan(
    projection: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"ack-plan-{projection}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    key = f"ack-plan-{projection}"
    ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key=key,
    )
    revision = channel.latest_revision(ADVISOR)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        command_id = command_id_for(ADVISOR, "channels_ack", key)
        connection.execute(
            "UPDATE commands SET plan_json = json_set("
            "plan_json, '$.plan.channel_id', 'channel/forged') WHERE command_id = ?",
            (command_id,),
        )
        row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None
        reseal_primary_fact(
            connection,
            family="command_plan",
            fact_key=command_id,
            fact=command_plan_fact_hash(row),
        )

    with pytest.raises(JournalDamaged, match="contradicts its command"):
        if projection == "exact":
            journal.channel_ack(message_id=request.message_id, actor_id=ADVISOR)
        else:
            channel.inbox(
                actor_id=ADVISOR,
                revision=revision,
                after=None,
                limit=10,
            )


def test_a_durable_ack_requires_an_aware_observation_time(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "ack-naive-time.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="ack-naive-time",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_acks SET acked_at = ?"
            " WHERE message_id = ? AND actor_id = ?",
            ("2026-01-01T00:00:00", str(request.message_id), ADVISOR),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable fact") as damaged:
        journal.channel_ack(message_id=request.message_id, actor_id=ADVISOR)
    assert isinstance(damaged.value.__cause__, JournalDamaged)
    assert "durable timestamp" in str(damaged.value.__cause__)


@pytest.mark.parametrize(
    "actor_expression",
    ("CAST(actor_id AS BLOB)", "'static:other-advisor'"),
)
def test_ack_actor_corruption_cannot_look_like_an_unacknowledged_message(
    actor_expression: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "ack-actor-routing.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="ack-actor-routing",
    )
    revision = channel.latest_revision(ADVISOR)
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE channel_acks SET actor_id = {actor_expression}"
            " WHERE message_id = ?",
            (str(request.message_id),),
        )

    for read in (
        lambda: journal.channel_ack(
            message_id=request.message_id,
            actor_id=ADVISOR,
        ),
        lambda: journal.channel_delivery(
            message_id=request.message_id,
            actor_id=ADVISOR,
        ),
        lambda: channel.inbox(
            actor_id=ADVISOR,
            revision=revision,
            after=None,
            limit=10,
        ),
    ):
        with pytest.raises(JournalDamaged):
            read()


def test_a_delivery_never_coerces_its_durable_message_sequence(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "delivery-sequence.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    _rebuild_channel_messages_with_projection(
        database,
        column="message_seq",
        projection="CAST(message_seq AS REAL)",
    )

    with pytest.raises(
        JournalDamaged,
        match=r"append-only history|not a valid durable fact",
    ):
        journal.channel_delivery(message_id=request.message_id, actor_id=ADVISOR)


def test_an_inbox_never_bounds_history_with_a_coerced_message_sequence(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "inbox-sequence.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    channel.append_request(_intent(port="first"), ATTESTATION)
    channel.append_request(_intent(port="second"), ATTESTATION)
    revision = channel.latest_revision(ADVISOR)
    _rebuild_channel_messages_with_projection(
        database,
        column="message_seq",
        projection=(
            "CASE WHEN message_seq = 1 THEN CAST(message_seq AS REAL) ELSE message_seq END"
        ),
    )

    with pytest.raises(
        JournalDamaged,
        match=r"message append-only history|not a valid durable fact",
    ):
        channel.inbox(
            actor_id=ADVISOR,
            revision=revision,
            after=None,
            limit=10,
        )


@pytest.mark.parametrize(
    ("column", "projection"),
    (
        ("type_id", "CAST(1 AS INTEGER)"),
        ("envelope_json", "CAST(envelope_json AS BLOB)"),
        ("attestation_id", "CAST(attestation_id AS BLOB)"),
    ),
)
def test_a_channel_message_never_normalizes_relational_storage_classes(
    column: str,
    projection: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"message-storage-{column}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    _rebuild_channel_messages_with_projection(
        database,
        column=column,
        projection=projection,
    )

    with pytest.raises(JournalDamaged, match="not a valid durable fact"):
        channel.message(request.message_id)


@pytest.mark.parametrize(
    ("column", "expression"),
    (
        ("recipient_actor_id", "CAST(recipient_actor_id AS BLOB)"),
        ("recipient_actor_id", "' static:advisor'"),
        ("kind", "'invalid-kind'"),
        ("interaction", "'invalid-interaction'"),
        ("message_id", "CAST(message_id AS BLOB)"),
    ),
)
def test_inbox_routing_damage_cannot_hide_behind_scope_or_a_cursor(
    column: str,
    expression: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"inbox-routing-{column}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    channel.append_request(_intent(port="first"), ATTESTATION)
    second = channel.append_request(_intent(port="second"), ATTESTATION)
    revision = channel.latest_revision(ADVISOR)
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE channel_messages SET {column} = {expression} WHERE message_seq = 1"
        )

    with pytest.raises(JournalDamaged, match="not a valid durable fact"):
        channel.inbox(
            actor_id=ADVISOR,
            revision=revision,
            after=(revision.message_seq, str(second.message_id)),
            limit=10,
        )


@pytest.mark.parametrize(
    ("column", "value", "recipient"),
    (
        ("interaction", "approval", ADVISOR),
        ("recipient_actor_id", "static:other-advisor", ADVISOR),
        ("kind", "reply", None),
    ),
)
def test_valid_routing_values_cannot_hide_a_request_from_its_send_proof(
    column: str,
    value: str,
    recipient: str | None,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"inbox-proof-routing-{column}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    channel.append_request(
        _intent(port="proof-routed", recipient=recipient),
        ATTESTATION,
    )
    later = channel.append_request(_intent(port="later"), ATTESTATION)
    revision = journal.channel_actor_revision(actor_id=ADVISOR)
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE channel_messages SET {column} = ? WHERE message_seq = 1",
            (value,),
        )
        connection.commit()

    with pytest.raises(JournalDamaged):
        journal.channel_actor_inbox(
            actor_id=ADVISOR,
            revision=revision,
            interactions=frozenset({"advice"}),
            after=(revision.message_seq, str(later.message_id)),
            limit=10,
        )


def test_in_process_reply_lookup_uses_derived_identity_before_its_pointer(
    clock: FakeClock,
) -> None:
    channel = InProcessChannel(channel_id=CHANNEL_ID, now_fn=clock.now)
    request = channel.append_request(_intent(), ATTESTATION)
    reply = channel.reply(
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id="cmd-derived-reply",
    )
    forged = reply.model_copy(
        update={"reply_to": digest("channel-message", 1, {"forged": True})},
        deep=True,
    )
    reply_key = str(reply.message_id)
    channel._by_id[reply_key] = forged
    channel._messages[channel._seq_by_id[reply_key] - 1] = forged

    with pytest.raises(JournalDamaged):
        channel.reply_for(request.message_id)

    # A lookup by the forged pointer used to miss the torn reply and let an
    # explicit acknowledgement manufacture its missing atomic half.
    channel._acks.clear()
    channel._ack_by_key.clear()
    channel._ack_commands.clear()
    with pytest.raises(JournalDamaged):
        channel.acknowledge(
            message_id=request.message_id,
            actor_id=ADVISOR,
            command_id="cmd-heal-torn-reply",
        )
    assert channel._acks == []


def test_a_damaged_channel_identity_cannot_hide_from_its_scoped_revision(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "channel-id-storage.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    revision = channel.latest_revision(ADVISOR)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_messages SET channel_id = CAST(channel_id AS BLOB)"
        )

    for read in (
        lambda: channel.message(request.message_id),
        lambda: channel.reply_for(request.message_id),
    ):
        with pytest.raises(JournalDamaged, match="not a valid durable fact"):
            read()
    with pytest.raises(JournalDamaged, match="not a valid durable fact"):
        channel.reply(
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            command_id="cmd-channel-id-damage",
        )
    with pytest.raises(
        JournalDamaged,
        match=r"message sequence history is damaged|not a valid durable fact",
    ):
        channel.inbox(
            actor_id=ADVISOR,
            revision=revision,
            after=None,
            limit=10,
        )
    with pytest.raises(
        JournalDamaged,
        match=r"message sequence history is damaged|not a valid durable fact",
    ):
        channel.latest_revision(ADVISOR)


@pytest.mark.parametrize(
    ("column", "projection"),
    (
        (
            "reply_provenance_version",
            "CASE WHEN kind = 'reply' THEN CAST(reply_provenance_version AS REAL) "
            "ELSE reply_provenance_version END",
        ),
        (
            "command_id",
            "CASE WHEN kind = 'reply' THEN CAST(command_id AS BLOB) ELSE command_id END",
        ),
    ),
)
def test_a_current_reply_never_normalizes_its_authority_columns(
    column: str,
    projection: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"reply-storage-{column}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key=f"reply-storage-{column}",
    )
    _rebuild_channel_messages_with_projection(
        database,
        column=column,
        projection=projection,
    )

    with pytest.raises(JournalDamaged, match="not a valid durable fact"):
        channel.reply_for(request.message_id)


def test_a_channel_revision_refuses_an_orphan_acknowledgement(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "orphan-ack-revision.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    channel.append_request(_intent(), ATTESTATION)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, 1)",
            (
                str(digest("missing-channel-message", 1, {})),
                ADVISOR,
                "cmd-orphan-ack",
                clock.now().isoformat(),
            ),
        )

    with pytest.raises(
        JournalDamaged,
        match=(
            r"names a missing message|dependent durable fact|positive seal|"
            r"fact-seal inventory"
        ),
    ):
        channel.latest_revision(ADVISOR)


def test_answered_requests_never_collapses_duplicate_reply_rows(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "duplicate-reply-row.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="duplicate-reply-row",
    )
    _rebuild_channel_messages_with_projection(
        database,
        column="message_seq",
        projection="message_seq",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO channel_messages SELECT * FROM channel_messages"
            " WHERE kind = 'reply'"
        )

    with pytest.raises(
        JournalDamaged,
        match=r"more than one stored reply|fact-seal inventory",
    ):
        journal.answered_requests([request.message_id])


def test_a_reply_command_cannot_be_rejected_after_writing_its_exchange(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal = SqliteJournal(tmp_path / "reject-after-reply.db", now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    key = "reject-after-reply"
    reply = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key=key,
    )
    command_id = reply_command_id(ADVISOR, key)
    claim = _retained_claim(journal, command_id)

    with pytest.raises(
        JournalDamaged,
        match="cannot be rejected after writing a channel reply",
    ):
        journal.reject_command(claim, {"status": "rejected"})

    command = journal.command(command_id)
    assert command is not None and command.state == "prepared"
    assert channel.reply_for(request.message_id) == reply


def test_an_ack_command_cannot_be_rejected_after_writing_its_delivery_fact(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal = SqliteJournal(tmp_path / "reject-after-ack.db", now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), ATTESTATION)
    key = "reject-after-ack"
    ack = ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key=key,
    )
    command_id = ack_command_id(ADVISOR, key)
    claim = _retained_claim(journal, command_id)

    with pytest.raises(
        JournalDamaged,
        match="cannot be rejected after writing a channel acknowledgement",
    ):
        journal.reject_command(claim, {"status": "rejected"})

    command = journal.command(command_id)
    assert command is not None and command.state == "prepared"
    stored = journal.channel_ack(message_id=request.message_id, actor_id=ADVISOR)
    assert stored is not None and stored.ack == ack


def test_one_command_cannot_reply_to_two_preacknowledged_requests(channel: Channel) -> None:
    """A prior ack must not bypass the one-command/one-reply provenance law."""

    first = channel.append_request(_intent(port="first-request"), ATTESTATION)
    second = channel.append_request(_intent(port="second-request"), ATTESTATION)
    ack_with_command(
        channel,
        message_id=first.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-ack-first",
    )
    ack_with_command(
        channel,
        message_id=second.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-ack-second",
    )
    reply_with_command(
        channel,
        request_id=first.message_id,
        actor_id=ADVISOR,
        payload={"advice": "first"},
        idempotency_key="cmd-one-reply",
    )

    with pytest.raises(JournalDamaged, match="already replied to a different request"):
        reply_with_command(
            channel,
            request_id=second.message_id,
            actor_id=ADVISOR,
            payload={"advice": "second"},
            idempotency_key="cmd-one-reply",
        )
    assert channel.reply_for(second.message_id) is None


def test_a_reply_command_cannot_acknowledge_another_message(channel: Channel) -> None:
    """Reply and ack ownership are one command namespace, not parallel ledgers."""

    first = channel.append_request(_intent(port="reply-first"), ATTESTATION)
    second = channel.append_request(_intent(port="ack-second"), ATTESTATION)
    ack_with_command(
        channel,
        message_id=first.message_id,
        actor_id=ADVISOR,
        idempotency_key="cmd-preack-first",
    )
    reply_with_command(
        channel,
        request_id=first.message_id,
        actor_id=ADVISOR,
        payload={"advice": "first"},
        idempotency_key="cmd-one-channel-mutation",
    )

    with pytest.raises(JournalDamaged, match="already replied to a different request"):
        channel.acknowledge(
            message_id=second.message_id,
            actor_id=ADVISOR,
            command_id=reply_command_id(ADVISOR, "cmd-one-channel-mutation"),
        )

    page = channel.inbox(
        actor_id=ADVISOR,
        revision=channel.latest_revision(ADVISOR),
        after=None,
        limit=10,
    )
    deliveries = {delivery.message.message_id: delivery for delivery in page}
    assert deliveries[second.message_id].acknowledged is False


def test_an_identical_reply_from_another_command_still_loses(channel: Channel) -> None:
    """ADR 0014 admits one reply and owes the loser a typed conflict.

    Identical bytes are not an exemption: two commands both reporting success
    over one fact would make the record say a thing was written twice. An exact
    retry of the *same* command still reconciles, because that is one command
    finishing what it started.
    """

    request = channel.append_request(_intent(), ATTESTATION)
    winner = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-identical-first",
    )
    with pytest.raises(ChannelReplyConflict, match="already answered by another command"):
        reply_with_command(
            channel,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            idempotency_key="cmd-identical-second",
        )
    replayed = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-identical-first",
    )
    assert replayed == winner
