# mypy: disable-error-code="attr-defined"
"""Durable channel facts: append-only messages and acknowledgements.

Nothing here updates or deletes a message. A reply is admitted by the request
it answers, in one transaction that also acknowledges that request for its
author, so a crash can never leave a reply without its delivery fact.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from constructicon.core.channel import (
    ChannelAck,
    ChannelAckConflict,
    ChannelContract,
    ChannelDelivery,
    ChannelMessage,
    ChannelReplyConflict,
    ChannelRevision,
    ChannelSendIntent,
    InvalidChannelRevision,
    message_for_intent,
    message_for_reply,
    reply_message_id,
    same_message,
)
from constructicon.core.envelope import Envelope
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import Digest, JsonValue, canonical_json

_MESSAGE_COLUMNS = (
    "message_id, channel_id, lane, interaction, kind, reply_to, recipient_actor_id,"
    " sender_actor_id, run_id, path_json, port, type_id, schema_hash, reply_port,"
    " reply_type_id, reply_schema_hash, envelope_json, attestation_id"
)


class _SqliteChannelsMixin:
    def channel_append_request(
        self,
        *,
        channel_id: str,
        intent: ChannelSendIntent,
        attestation_id: str,
    ) -> ChannelMessage:
        """Append one request, or return the exact stored fact for a retry."""

        if intent.channel_id != channel_id:
            raise ContractViolation(
                f"intent addresses channel {intent.channel_id!r}, not {channel_id!r}"
            )
        with self._txn() as connection:
            row = connection.execute(
                "SELECT * FROM channel_messages WHERE message_id = ?",
                (str(intent.message_id),),
            ).fetchone()
            if row is not None:
                stored = _message_from_row(row)
                # Reconcile against the stored observation time; a reconstructed
                # send must not invent a second one.
                expected = message_for_intent(intent, created_at=stored.envelope.created_at)
                if not same_message(stored, expected) or (
                    row["attestation_id"] != attestation_id
                ):
                    raise JournalDamaged(
                        f"channel message {intent.message_id} already stored with "
                        "a different logical intent"
                    )
                return stored
            message = message_for_intent(intent, created_at=self._now())
            _insert_message(connection, message, attestation_id)
        self.fault_probe("channel.after_message_insert")
        return message

    def channel_message(self, *, channel_id: str, message_id: Digest) -> ChannelMessage | None:
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM channel_messages WHERE message_id = ? AND channel_id = ?",
                (str(message_id), channel_id),
            ).fetchone()
        return _message_from_row(row) if row is not None else None

    def channel_reply_for(self, *, channel_id: str, request_id: Digest) -> ChannelMessage | None:
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM channel_messages WHERE reply_to = ? AND channel_id = ?",
                (str(request_id), channel_id),
            ).fetchone()
        return _message_from_row(row) if row is not None else None

    def channel_reply(
        self,
        *,
        channel_id: str,
        request_id: Digest,
        actor_id: str,
        payload: JsonValue,
        command_id: str,
    ) -> ChannelMessage:
        """Store the one authenticated reply and its request ack atomically."""

        with self._txn() as connection:
            request_row = connection.execute(
                "SELECT * FROM channel_messages WHERE message_id = ? AND channel_id = ?",
                (str(request_id), channel_id),
            ).fetchone()
            if request_row is None:
                raise ContractViolation(f"no channel request {request_id} to reply to")
            request = _message_from_row(request_row)
            if request.kind != "request" or request.reply_port is None:
                raise ContractViolation(f"no channel request {request_id} to reply to")
            reply_id = reply_message_id(
                request_id=request.message_id,
                reply_port=request.reply_port,
            )
            stored_row = connection.execute(
                "SELECT * FROM channel_messages WHERE message_id = ?",
                (str(reply_id),),
            ).fetchone()
            if stored_row is not None:
                stored = _message_from_row(stored_row)
                candidate = message_for_reply(
                    request,
                    actor_id=actor_id,
                    payload=payload,
                    created_at=stored.envelope.created_at,
                )
                if not same_message(stored, candidate):
                    raise ChannelReplyConflict(
                        f"request {request_id} already carries a different reply"
                    )
                _acknowledge(connection, request.message_id, actor_id, command_id, self._now_iso())
                return stored
            reply = message_for_reply(
                request,
                actor_id=actor_id,
                payload=payload,
                created_at=self._now(),
            )
            _insert_message(connection, reply, None)
            _acknowledge(connection, request.message_id, actor_id, command_id, self._now_iso())
        self.fault_probe("channel.after_reply_insert")
        return reply

    def channel_acknowledge(
        self,
        *,
        channel_id: str,
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> ChannelAck:
        with self._txn() as connection:
            present = connection.execute(
                "SELECT 1 FROM channel_messages WHERE message_id = ? AND channel_id = ?",
                (str(message_id), channel_id),
            ).fetchone()
            if present is None:
                raise ContractViolation(f"no channel message {message_id} to acknowledge")
            return _acknowledge(connection, message_id, actor_id, command_id, self._now_iso())

    def channel_revision(self, *, channel_id: str) -> ChannelRevision:
        with self._read() as connection, _snapshot(connection):
            return _current_revision(connection, channel_id)

    def channel_inbox(
        self,
        *,
        channel_id: str,
        actor_id: str,
        revision: ChannelRevision,
        after: tuple[int, str] | None,
        limit: int,
    ) -> tuple[ChannelDelivery, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        clauses = [
            "channel_id = ?",
            "recipient_actor_id = ?",
            "message_seq <= ?",
        ]
        params: list[object] = [channel_id, actor_id, revision.message_seq]
        if after is not None:
            clauses.append("(message_seq > ? OR (message_seq = ? AND message_id > ?))")
            params.extend((after[0], after[0], after[1]))
        params.append(limit)
        with self._read() as connection, _snapshot(connection):
            current = _current_revision(connection, channel_id)
            if revision.message_seq > current.message_seq or revision.ack_seq > current.ack_seq:
                raise InvalidChannelRevision(
                    f"channel revision {revision.model_dump()} is ahead of retained history"
                )
            # An acknowledgement cannot exist in a snapshot that omits the message
            # it acknowledges, so bounds alone do not make a cut real.
            incoherent = connection.execute(
                "SELECT 1 FROM channel_acks AS acks"
                " JOIN channel_messages AS messages ON messages.message_id = acks.message_id"
                " WHERE acks.ack_seq <= ? AND messages.message_seq > ? LIMIT 1",
                (revision.ack_seq, revision.message_seq),
            ).fetchone()
            if incoherent is not None:
                raise InvalidChannelRevision(
                    f"channel revision {revision.model_dump()} acknowledges a message "
                    "it does not include"
                )
            rows = connection.execute(
                "SELECT * FROM channel_messages WHERE "
                + " AND ".join(clauses)
                + " ORDER BY message_seq, message_id LIMIT ?",
                tuple(params),
            ).fetchall()
            paged = [(int(row["message_seq"]), _message_from_row(row)) for row in rows]
            if not paged:
                return ()
            placeholders = ",".join("?" for _ in paged)
            acknowledged = {
                str(ack["message_id"])
                for ack in connection.execute(
                    "SELECT message_id FROM channel_acks WHERE actor_id = ?"
                    f" AND ack_seq <= ? AND message_id IN ({placeholders})",
                    (actor_id, revision.ack_seq, *(str(m.message_id) for _, m in paged)),
                ).fetchall()
            }
        return tuple(
            ChannelDelivery(
                message_seq=message_seq,
                message=message,
                acknowledged=str(message.message_id) in acknowledged,
            )
            for message_seq, message in paged
        )


@contextmanager
def _snapshot(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One WAL read snapshot, so multi-statement reads see one consistent state.

    Reading the two sequence maxima in separate statements could otherwise
    straddle another host's commit and manufacture a cut that never existed —
    an ack visible while the message from its own transaction is not.
    """

    connection.execute("BEGIN")
    try:
        yield connection
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def _current_revision(connection: sqlite3.Connection, channel_id: str) -> ChannelRevision:
    """The cut for ONE channel, so an unrelated channel cannot advance it."""

    messages = connection.execute(
        "SELECT COALESCE(MAX(message_seq), 0) FROM channel_messages WHERE channel_id = ?",
        (channel_id,),
    ).fetchone()[0]
    acks = connection.execute(
        "SELECT COALESCE(MAX(acks.ack_seq), 0) FROM channel_acks AS acks"
        " JOIN channel_messages AS messages ON messages.message_id = acks.message_id"
        " WHERE messages.channel_id = ?",
        (channel_id,),
    ).fetchone()[0]
    return ChannelRevision(message_seq=int(messages), ack_seq=int(acks))


def _insert_message(
    connection: sqlite3.Connection,
    message: ChannelMessage,
    attestation_id: str | None,
) -> None:
    connection.execute(
        f"INSERT INTO channel_messages ({_MESSAGE_COLUMNS})"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(message.message_id),
            message.channel_id,
            message.lane,
            message.interaction,
            message.kind,
            str(message.reply_to) if message.reply_to is not None else None,
            message.recipient_actor_id,
            message.sender_actor_id,
            message.envelope.run_id,
            canonical_json(message.envelope.path.model_dump(mode="json")),
            message.envelope.port,
            message.contract.type_id,
            message.contract.schema_hash,
            message.reply_port,
            message.reply_contract.type_id if message.reply_contract is not None else None,
            (
                message.reply_contract.schema_hash
                if message.reply_contract is not None
                else None
            ),
            message.envelope.model_dump_json(),
            attestation_id,
        ),
    )


def _acknowledge(
    connection: sqlite3.Connection,
    message_id: Digest,
    actor_id: str,
    command_id: str,
    acked_at: str,
) -> ChannelAck:
    owner = connection.execute(
        "SELECT message_id, actor_id FROM channel_acks WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    if owner is not None and (owner["message_id"], owner["actor_id"]) != (
        str(message_id),
        actor_id,
    ):
        raise JournalDamaged(f"command {command_id!r} already acknowledged a different message")
    stored = connection.execute(
        "SELECT * FROM channel_acks WHERE message_id = ? AND actor_id = ?",
        (str(message_id), actor_id),
    ).fetchone()
    if stored is not None:
        if stored["command_id"] != command_id:
            raise ChannelAckConflict(
                f"message {message_id} is already acknowledged for {actor_id!r} "
                f"by another command; {command_id!r} may not claim it"
            )
        return _ack_from_row(stored)
    connection.execute(
        "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at)"
        " VALUES (?, ?, ?, ?)",
        (str(message_id), actor_id, command_id, acked_at),
    )
    row = connection.execute(
        "SELECT * FROM channel_acks WHERE message_id = ? AND actor_id = ?",
        (str(message_id), actor_id),
    ).fetchone()
    return _ack_from_row(row)


def _ack_from_row(row: sqlite3.Row) -> ChannelAck:
    return ChannelAck(
        message_id=Digest(row["message_id"]),
        actor_id=row["actor_id"],
        acked_at=datetime.fromisoformat(row["acked_at"]),
    )


def _message_from_row(row: sqlite3.Row) -> ChannelMessage:
    reply_type_id = row["reply_type_id"]
    reply_schema_hash = row["reply_schema_hash"]
    reply_contract = (
        ChannelContract(type_id=reply_type_id, schema_hash=reply_schema_hash)
        if reply_type_id is not None and reply_schema_hash is not None
        else None
    )
    return ChannelMessage(
        message_id=Digest(row["message_id"]),
        channel_id=row["channel_id"],
        lane=row["lane"],
        interaction=row["interaction"],
        kind=row["kind"],
        reply_to=Digest(row["reply_to"]) if row["reply_to"] is not None else None,
        recipient_actor_id=row["recipient_actor_id"],
        sender_actor_id=row["sender_actor_id"],
        contract=ChannelContract(
            type_id=row["type_id"],
            schema_hash=row["schema_hash"],
        ),
        reply_contract=reply_contract,
        reply_port=row["reply_port"],
        envelope=Envelope[JsonValue].model_validate_json(row["envelope_json"]),
    )
