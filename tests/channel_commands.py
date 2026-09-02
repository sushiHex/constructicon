"""Canonical command provenance for direct channel contract tests.

Production mailbox replies are authored by ``channels_reply`` commands.  A
transport test that calls the channel directly must therefore construct that
same durable fact instead of inventing an opaque command id that production can
never write.  The in-process transport receives the identical derived identity;
its independent proof snapshot supplies the same plan/evidence law without a
control store.
"""

from __future__ import annotations

from datetime import UTC, datetime

from constructicon.core.channel import Channel, ChannelAck, ChannelMessage, reply_message_id
from constructicon.core.control import (
    ADVISE_SCOPE,
    INTERACTION_SCOPES,
    AuthenticatedActor,
    command_id_for,
    command_request_hash,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import (
    ChannelAckPlan,
    ChannelReplyPlan,
    StoredChannelAckPlan,
    StoredChannelReplyPlan,
    sealed_reply_payload,
)
from constructicon.core.identity import Digest, JsonValue, json_value
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal


def reply_command_id(actor_id: str, idempotency_key: str) -> str:
    return command_id_for(actor_id, "channels_reply", idempotency_key)


def ack_command_id(actor_id: str, idempotency_key: str) -> str:
    return command_id_for(actor_id, "channels_ack", idempotency_key)


def ack_with_command(
    channel: Channel,
    *,
    message_id: Digest,
    actor_id: str,
    idempotency_key: str,
) -> ChannelAck:
    """Record one direct delivery fact with production command provenance."""

    durable_command_id = ack_command_id(actor_id, idempotency_key)
    if isinstance(channel, MailboxChannel):
        prepare_ack_command(
            channel,
            message_id=message_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    return channel.acknowledge(
        message_id=message_id,
        actor_id=actor_id,
        command_id=durable_command_id,
    )


def prepare_ack_command(
    channel: MailboxChannel,
    *,
    message_id: Digest,
    actor_id: str,
    idempotency_key: str,
) -> str:
    request = channel.message(message_id)
    if request is None:
        raise JournalDamaged(f"test acknowledgement names no request {message_id}")
    command_id = ack_command_id(actor_id, idempotency_key)
    journal = SqliteJournal(
        channel._journal._db_path,
        now_fn=lambda: datetime(2000, 1, 1, tzinfo=UTC),
    )
    if journal.command(command_id) is not None:
        return command_id
    command_request: JsonValue = {"message_id": str(message_id)}
    actor = AuthenticatedActor(
        actor_id=actor_id,
        auth_method="static",
        scopes=frozenset({INTERACTION_SCOPES[request.interaction]}),
    )
    result = journal.claim_command(
        actor=actor,
        operation="channels_ack",
        idempotency_key=idempotency_key,
        request_hash=command_request_hash(command_request),
        request=command_request,
        owner_id="test:channel-contract",
        ttl_s=30,
    )
    if result.claim is None:
        raise JournalDamaged(f"test could not prepare ack command {command_id!r}")
    plan = ChannelAckPlan(
        channel_id=request.channel_id,
        message_id=request.message_id,
        interaction=request.interaction,
        actor_id=actor.actor_id,
    )
    journal.store_command_plan(
        result.claim,
        json_value(StoredChannelAckPlan(plan=plan).model_dump(mode="json")),
    )
    return command_id


def reply_with_command(
    channel: Channel,
    *,
    request_id: Digest,
    actor_id: str,
    payload: JsonValue,
    idempotency_key: str,
) -> ChannelMessage:
    """Write one direct reply with production's exact derived command id."""

    request = channel.message(request_id)
    if request is None or request.reply_port is None:
        raise JournalDamaged(f"test reply names no request {request_id}")
    durable_command_id = reply_command_id(actor_id, idempotency_key)
    reply_id = reply_message_id(
        request_id=request.message_id,
        reply_port=request.reply_port,
    )
    durable_payload = sealed_reply_payload(
        request,
        answer=payload,
        actor_id=actor_id,
        reply_id=reply_id,
    )
    if isinstance(channel, MailboxChannel):
        prepare_reply_command(
            channel,
            request_id=request_id,
            actor_id=actor_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
    return channel.reply(
        request_id=request_id,
        actor_id=actor_id,
        payload=durable_payload,
        command_id=durable_command_id,
    )


def prepare_reply_command(
    channel: MailboxChannel,
    *,
    request_id: Digest,
    actor_id: str,
    payload: JsonValue,
    idempotency_key: str,
) -> str:
    request = channel.message(request_id)
    if request is None or request.reply_port is None:
        raise JournalDamaged(f"test reply names no request {request_id}")
    command_id = reply_command_id(actor_id, idempotency_key)
    # Command preparation must not consume the transport clock under test.
    journal = SqliteJournal(
        channel._journal._db_path,
        now_fn=lambda: datetime(2000, 1, 1, tzinfo=UTC),
    )
    if journal.command(command_id) is not None:
        return command_id
    command_request: JsonValue = {
        "message_id": str(request_id),
        "payload": json_value(payload),
    }
    actor = AuthenticatedActor(
        actor_id=actor_id,
        auth_method="static",
        scopes=frozenset({ADVISE_SCOPE}),
    )
    result = journal.claim_command(
        actor=actor,
        operation="channels_reply",
        idempotency_key=idempotency_key,
        request_hash=command_request_hash(command_request),
        request=command_request,
        owner_id="test:channel-contract",
        ttl_s=30,
    )
    if result.claim is None:
        raise JournalDamaged(f"test could not prepare reply command {command_id!r}")
    reply_id = reply_message_id(
        request_id=request.message_id,
        reply_port=request.reply_port,
    )
    plan = ChannelReplyPlan(
        channel_id=request.channel_id,
        request_id=request.message_id,
        interaction=request.interaction,
        actor_id=actor.actor_id,
        reply_id=reply_id,
        reply_port=request.reply_port,
        payload=sealed_reply_payload(
            request,
            answer=payload,
            actor_id=actor.actor_id,
            reply_id=reply_id,
        ),
        run_id=request.envelope.run_id,
        parked_event_seq=journal.max_event_seq(request.envelope.run_id),
    )
    journal.store_command_plan(
        result.claim,
        json_value(StoredChannelReplyPlan(plan=plan).model_dump(mode="json")),
    )
    return command_id
