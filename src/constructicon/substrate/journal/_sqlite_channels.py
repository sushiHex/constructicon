# mypy: disable-error-code="attr-defined"
"""Durable channel facts: append-only messages and acknowledgements.

Nothing here updates or deletes a message. A reply is admitted by the request
it answers, in one transaction that also acknowledges that request for its
author, so a crash can never leave a reply without its delivery fact.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from pydantic import ValidationError

from constructicon.core.address import RunId
from constructicon.core.channel import (
    REPLY_CONSUMES,
    ActorInboxRevision,
    ChannelAck,
    ChannelAckConflict,
    ChannelAckRecord,
    ChannelContract,
    ChannelDelivery,
    ChannelInteraction,
    ChannelMessage,
    ChannelMessageKind,
    ChannelReplyConflict,
    ChannelRevision,
    ChannelSendIntent,
    InvalidChannelRevision,
    discoverable_by,
    message_for_intent,
    message_for_reply,
    reply_message_id,
    same_message,
)
from constructicon.core.control import CommandRecord
from constructicon.core.effect import (
    ApprovalRecord,
    Attestation,
    ChannelSendSubject,
    validated_attested_channel_request,
    validated_channel_send_attestation,
)
from constructicon.core.envelope import Envelope
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.human import (
    approval_record_for_reply,
    canonical_exchange_fault,
    claims_approval_exchange,
    validated_channel_ack_provenance,
    validated_channel_approval_exchange,
    validated_channel_command_ack,
    validated_channel_command_reply,
    validated_new_channel_command_reply,
)
from constructicon.core.identity import (
    Digest,
    JsonValue,
    canonical_json,
    json_value,
    parse_json_value,
)
from constructicon.substrate.journal._sqlite_approvals import stored_approval_fact_from_row
from constructicon.substrate.journal._sqlite_attestations import (
    attestation_from_json,
    require_attestation_seal,
)
from constructicon.substrate.journal._sqlite_base import (
    _durable_datetime,
    _durable_digest,
    _durable_sequence,
    _durable_text,
)
from constructicon.substrate.journal._sqlite_commands import command_for_id
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    durable_fact_seal,
    require_durable_fact_seal,
    store_durable_fact_seal,
)

_MESSAGE_COLUMN_NAMES = (
    "message_id",
    "channel_id",
    "lane",
    "interaction",
    "kind",
    "reply_to",
    "recipient_actor_id",
    "sender_actor_id",
    "run_id",
    "path_json",
    "port",
    "type_id",
    "schema_hash",
    "reply_port",
    "reply_type_id",
    "reply_schema_hash",
    "envelope_json",
    "attestation_id",
    "command_id",
    "reply_provenance_version",
)
_MESSAGE_COLUMNS = ", ".join(_MESSAGE_COLUMN_NAMES)
_CURRENT_REPLY_PROVENANCE_VERSION = 1
_CURRENT_ACK_PROVENANCE_VERSION = 1
_MAX_SQL_VARIABLES = 900
CHANNEL_MESSAGE_FACT_FAMILY = "channel_message"
CHANNEL_ACK_FACT_FAMILY = "channel_acknowledgement"
CHANNEL_PROVENANCE_FACT_FAMILY = "channel_provenance"
_INVALID_INBOX_ROUTING = (
    "typeof(m.message_id) != 'text'"
    " OR typeof(m.channel_id) != 'text'"
    " OR typeof(m.kind) != 'text' OR m.kind NOT IN ('request', 'reply')"
    " OR typeof(m.interaction) != 'text'"
    " OR m.interaction NOT IN ('advice', 'approval')"
    " OR (m.recipient_actor_id IS NOT NULL"
    " AND constructicon_actor_id_is_canonical(m.recipient_actor_id) != 1)"
    " OR (m.kind = 'request' AND m.attestation_id IS NULL)"
    " OR (m.kind = 'reply' AND (m.reply_to IS NULL"
    " OR m.sender_actor_id IS NULL OR m.recipient_actor_id IS NOT NULL"
    " OR m.attestation_id IS NOT NULL))"
)
_INBOX_REQUEST_PROOF_MISMATCH = (
    "m.attestation_id IS NOT NULL AND"
    " constructicon_channel_request_routing_matches("
    "m.attestation_id, a.attestation_json, m.message_id, m.channel_id,"
    " m.kind, m.interaction, m.recipient_actor_id) != 1"
)


@dataclass(frozen=True)
class _StoredChannelMessage:
    """One relational channel row after every SQLite scalar is exact."""

    message_seq: int
    message: ChannelMessage
    attestation_id: str | None
    command_id: str | None
    reply_provenance_version: Literal[1] | None


def _sqlite_batch_size(
    connection: sqlite3.Connection,
    *,
    reserved: int = 0,
) -> int:
    """One conservative bind bound shared by every channel batch query."""

    available = connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER) - reserved
    if available < 1:
        raise RuntimeError("SQLite bind-variable limit is too small for channel projection")
    return min(available, _MAX_SQL_VARIABLES)


def _sealed_fact_key_selectors(
    connection: sqlite3.Connection,
    *,
    family: str,
    fact_keys: Sequence[str],
) -> dict[str, str]:
    """Read a bounded set of positive identities without projecting history."""

    unique = tuple(dict.fromkeys(fact_keys))
    retained: dict[str, str] = {}
    batch_size = _sqlite_batch_size(connection, reserved=1)
    for start in range(0, len(unique), batch_size):
        chunk = unique[start : start + batch_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            "SELECT fact_key, selector FROM durable_fact_seals WHERE family = ?"
            f" AND fact_key IN ({placeholders})",
            (family, *chunk),
        ).fetchall()
        for row in rows:
            fact_key = _durable_text(
                row["fact_key"],
                fact=f"durable {family!r} fact seal key",
            )
            if fact_key in retained:
                raise JournalDamaged(
                    f"durable {family!r} fact {fact_key!r} is sealed more than once"
                )
            retained[fact_key] = _durable_text(
                row["selector"],
                fact=f"durable {family!r} fact {fact_key!r} selector",
            )
    return retained


def _sealed_fact_keys(
    connection: sqlite3.Connection,
    *,
    family: str,
    fact_keys: Sequence[str],
) -> set[str]:
    return set(
        _sealed_fact_key_selectors(
            connection,
            family=family,
            fact_keys=fact_keys,
        )
    )


def _sequence_from_seal_selector(raw: str, *, fact: str) -> int:
    if not raw.isascii() or not raw.isdecimal() or raw.startswith("0"):
        raise JournalDamaged(f"{fact} is not a canonical positive sequence")
    value = int(raw)
    if value <= 0 or str(value) != raw:
        raise JournalDamaged(f"{fact} is not a canonical positive sequence")
    return value


def _channel_message_rows_for_ids(
    connection: sqlite3.Connection,
    message_ids: Sequence[str],
) -> tuple[sqlite3.Row, ...]:
    """Locate messages by derived identity and prove every requested absence."""

    unique = tuple(dict.fromkeys(message_ids))
    rows: list[sqlite3.Row] = []
    batch_size = _sqlite_batch_size(connection)
    for start in range(0, len(unique), batch_size):
        chunk = unique[start : start + batch_size]
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(
            connection.execute(
                f"SELECT * FROM channel_messages WHERE message_id IN ({placeholders})",
                chunk,
            ).fetchall()
        )
    located: set[str] = set()
    for row in rows:
        message_id = _durable_text(
            row["message_id"],
            fact="channel message relational identity",
        )
        if message_id in located:
            raise JournalDamaged(f"channel message {message_id!r} is stored more than once")
        located.add(message_id)
    _validate_channel_message_absences(
        connection,
        requested=unique,
        located=located,
    )
    return tuple(rows)


def _validate_channel_message_absences(
    connection: sqlite3.Connection,
    *,
    requested: Sequence[str],
    located: set[str],
) -> None:
    """Prove that every absent derived identity has no retained row seal."""

    missing = sorted(set(requested) - located)
    sealed_missing = _sealed_fact_keys(
        connection,
        family=CHANNEL_MESSAGE_FACT_FAMILY,
        fact_keys=missing,
    )
    if sealed_missing:
        raise JournalDamaged(
            "channel messages disappeared behind their positive seals: "
            + ", ".join(sorted(sealed_missing))
        )


def _channel_message_row(
    connection: sqlite3.Connection,
    message_id: Digest,
) -> sqlite3.Row | None:
    rows = _channel_message_rows_for_ids(connection, (str(message_id),))
    return rows[0] if rows else None


def _channel_request_routing_matches(
    attestation_id: object,
    attestation_json: object,
    message_id: object,
    channel_id: object,
    kind: object,
    interaction: object,
    recipient_actor_id: object,
) -> int:
    """SQLite selector fence backed by the request's independent send proof.

    Returning false widens the bounded inbox candidate query; the ordinary
    request projector then raises the typed damage with full proof context.
    No malformed or mismatched row may disappear behind a scope, recipient,
    kind, or cursor predicate merely because its forged selector is lexical.
    """

    try:
        exact_attestation_id = _durable_text(
            attestation_id,
            fact="inbox request attestation identity",
        )
        exact_attestation_json = _durable_text(
            attestation_json,
            fact=f"attestation {exact_attestation_id!r} bytes",
        )
        exact_message_id = _durable_text(
            message_id,
            fact="inbox request message identity",
        )
        exact_channel_id = _durable_text(
            channel_id,
            fact=f"channel request {exact_message_id} channel",
        )
        exact_kind = _durable_text(
            kind,
            fact=f"channel request {exact_message_id} kind",
        )
        exact_interaction = _durable_text(
            interaction,
            fact=f"channel request {exact_message_id} interaction",
        )
        if recipient_actor_id is not None and type(recipient_actor_id) is not str:
            return 0
        attestation = attestation_from_json(
            exact_attestation_json,
            expected_attestation_id=exact_attestation_id,
        )
        subject = attestation.subject
        subject_recipient = (
            str(subject.recipient_actor_id)
            if isinstance(subject, ChannelSendSubject)
            and subject.recipient_actor_id is not None
            else None
        )
        return int(
            attestation.action == "send"
            and attestation.ok
            and isinstance(subject, ChannelSendSubject)
            and exact_kind == "request"
            and str(subject.message_id) == exact_message_id
            and subject.channel_id == exact_channel_id
            and subject.interaction == exact_interaction
            and subject_recipient == recipient_actor_id
        )
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return 0


def _validate_append_only_sequence(
    connection: sqlite3.Connection,
    *,
    table: str,
    column: str,
    fact: str,
) -> int:
    """Prove one AUTOINCREMENT history has no deletion, gap, or coercion."""

    sequence_rows = connection.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = ?",
        (table,),
    ).fetchall()
    if len(sequence_rows) > 1:
        raise JournalDamaged(f"{fact} append-only high-water is stored twice")
    high_water = (
        _durable_sequence(
            sequence_rows[0]["seq"],
            fact=f"{fact} append-only high-water",
            allow_zero=True,
            kind="sequence",
        )
        if sequence_rows
        else 0
    )
    row = connection.execute(
        f"SELECT COUNT(*) AS fact_count, COALESCE(MIN({column}), 0) AS minimum,"
        f" COALESCE(MAX({column}), 0) AS maximum,"
        f" COALESCE(MAX(CASE WHEN typeof({column}) != 'integer'"
        f" OR {column} <= 0 THEN 1 ELSE 0 END), 0) AS damaged FROM {table}"
    ).fetchone()
    try:
        fact_count = _durable_sequence(
            row["fact_count"],
            fact=f"{fact} count",
            allow_zero=True,
            kind="count",
        )
        minimum = _durable_sequence(
            row["minimum"],
            fact=f"{fact} minimum position",
            allow_zero=True,
            kind="sequence",
        )
        maximum = _durable_sequence(
            row["maximum"],
            fact=f"{fact} maximum position",
            allow_zero=True,
            kind="sequence",
        )
        damaged = _durable_sequence(
            row["damaged"],
            fact=f"{fact} scalar-integrity flag",
            allow_zero=True,
            kind="sequence",
        )
    except JournalDamaged as exc:
        raise JournalDamaged(f"{fact} append-only history is damaged") from exc
    expected_minimum = 1 if high_water else 0
    if (
        damaged != 0
        or fact_count != high_water
        or minimum != expected_minimum
        or maximum != high_water
    ):
        raise JournalDamaged(f"{fact} append-only history is damaged")
    return high_water


def _validate_channel_history(connection: sqlite3.Connection) -> None:
    _required_channel_provenance_cutoffs(connection)
    _validate_append_only_sequence(
        connection,
        table="channel_messages",
        column="message_seq",
        fact="channel message",
    )
    _validate_append_only_sequence(
        connection,
        table="channel_acks",
        column="ack_seq",
        fact="channel acknowledgement",
    )
    row = connection.execute(
        "SELECT"
        " (SELECT COUNT(*) FROM channel_messages) AS message_facts,"
        " (SELECT COUNT(*) FROM durable_fact_seals WHERE family = ?)"
        " AS message_seals,"
        " (SELECT COUNT(*) FROM channel_acks) AS acknowledgement_facts,"
        " (SELECT COUNT(*) FROM durable_fact_seals WHERE family = ?)"
        " AS acknowledgement_seals,"
        " (SELECT COUNT(*) FROM durable_fact_seals WHERE family = ?)"
        " AS provenance_seals",
        (
            CHANNEL_MESSAGE_FACT_FAMILY,
            CHANNEL_ACK_FACT_FAMILY,
            CHANNEL_PROVENANCE_FACT_FAMILY,
        ),
    ).fetchone()
    exact = {
        name: _durable_sequence(
            row[name],
            fact=f"channel {name.replace('_', ' ')} count",
            allow_zero=True,
            kind="count",
        )
        for name in (
            "message_facts",
            "message_seals",
            "acknowledgement_facts",
            "acknowledgement_seals",
            "provenance_seals",
        )
    }
    if (
        exact["message_facts"] != exact["message_seals"]
        or exact["acknowledgement_facts"] != exact["acknowledgement_seals"]
        or exact["provenance_seals"] != 1
    ):
        raise JournalDamaged(
            "channel fact-seal inventory has an orphan or missing primary fact"
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
            _validate_channel_history(connection)
            rows = connection.execute(
                "SELECT * FROM channel_messages"
                " WHERE message_id = ? OR attestation_id = ? LIMIT 2",
                (str(intent.message_id), attestation_id),
            ).fetchall()
            if len(rows) > 1:
                raise JournalDamaged(
                    f"channel request {intent.message_id} has contradictory"
                    " message and attestation selectors"
                )
            row = rows[0] if rows else None
            if row is not None:
                stored = _stored_request_fact(connection, row)
                # Reconcile against the stored observation time; a reconstructed
                # send must not invent a second one.
                expected = message_for_intent(intent, created_at=stored.envelope.created_at)
                stored_attestation_id = _durable_text(
                    row["attestation_id"],
                    fact=f"channel request {intent.message_id} attestation identity",
                )
                if not same_message(stored, expected) or stored_attestation_id != attestation_id:
                    raise JournalDamaged(
                        f"channel message {intent.message_id} already stored with "
                        "a different logical intent"
                )
                return stored
            if durable_fact_seal(
                connection,
                family=CHANNEL_MESSAGE_FACT_FAMILY,
                fact_key=str(intent.message_id),
            ) is not None:
                raise JournalDamaged(
                    f"channel request {intent.message_id} disappeared behind its positive seal"
                )
            _validate_intent_attestation(
                connection,
                intent,
                attestation_id=attestation_id,
            )
            message = message_for_intent(intent, created_at=self._now())
            _insert_message(connection, message, attestation_id)
        self.fault_probe("channel.after_message_insert")
        return message

    def channel_message(self, *, channel_id: str, message_id: Digest) -> ChannelMessage | None:
        with self._read() as connection:
            _validate_channel_history(connection)
            row = _channel_message_row(connection, message_id)
            if row is None:
                return None
            message, _writer = _stored_message_fact(connection, row)
            return message if message.channel_id == channel_id else None

    def channel_delivery(
        self,
        *,
        message_id: Digest,
        actor_id: str,
    ) -> ChannelDelivery | None:
        """One message by identity, with its position and this actor's ack.

        The control plane serves an actor across channels, so it addresses a
        message by identity rather than by the channel that happens to hold it.
        It returns the same ``ChannelDelivery`` a page row carries, so a single
        read and a page feed one summary law instead of two shapes.

        No revision bounds this read, and it is deliberately not called a
        snapshot. The message and its position are immutable; ``acknowledged``
        is a delivery fact that a later ack can flip, so this is the current
        state of one message, not a cut. Only the immutable message becomes
        detail — an acknowledgement never enters a digest-bound document.
        """

        with self._read() as connection:
            _validate_channel_history(connection)
            row = _channel_message_row(connection, message_id)
            if row is None:
                return None
            message, _writer = _stored_message_fact(connection, row)
            acknowledgement = _ack_row(connection, message_id, actor_id)
            if acknowledgement is not None:
                _stored_ack_record(connection, acknowledgement, request=message)
        return ChannelDelivery(
            message_seq=_durable_sequence(
                row["message_seq"],
                fact=f"channel message {message.message_id} position",
                kind="message sequence",
            ),
            message=message,
            acknowledged=acknowledgement is not None,
        )

    def channel_message_command(self, *, message_id: Digest) -> str | None:
        """Which command wrote this message, if a command did."""

        with self._read() as connection:
            _validate_channel_history(connection)
            row = _channel_message_row(connection, message_id)
            if row is None:
                return None
            _message, writer = _stored_message_fact(connection, row)
            return writer

    def channel_reply_for(self, *, channel_id: str, request_id: Digest) -> ChannelMessage | None:
        with self._read() as connection:
            _validate_channel_history(connection)
            request_row = _channel_message_row(connection, request_id)
            if request_row is None:
                return None
            request = _stored_request_fact(connection, request_row)
            if request.channel_id != channel_id or request.reply_port is None:
                return None
            reply_id = reply_message_id(
                request_id=request.message_id,
                reply_port=request.reply_port,
            )
            row = _channel_message_row(connection, reply_id)
            contradictory = connection.execute(
                "SELECT * FROM channel_messages WHERE reply_to = ? AND message_id != ?"
                " LIMIT 1",
                (str(request.message_id), str(reply_id)),
            ).fetchone()
            if contradictory is not None:
                _stored_reply_fact(connection, request, contradictory)
                raise JournalDamaged(
                    f"channel request {request.message_id} has more than one stored reply"
                )
            if row is None:
                return None
            reply, _writer = _stored_reply_fact(
                connection,
                request,
                row,
            )
            return reply

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
            _validate_channel_history(connection)
            request, reply_port = _request_in_transaction(
                connection,
                channel_id=channel_id,
                request_id=request_id,
            )
            if request.interaction not in REPLY_CONSUMES:
                raise ContractViolation(
                    "an approval request can only be answered by the request-bound "
                    "approval operation"
                )
            reply_contract = request.reply_contract
            if reply_contract is None:
                raise ContractViolation(f"no channel request {request_id} to reply to")
            incoherence = canonical_exchange_fault(
                request.contract,
                reply_contract,
                request.interaction,
            )
            if incoherence is not None:
                raise ContractViolation(
                    f"channel request {request_id} carries an incoherent exchange: {incoherence}"
                )
            reply_id = reply_message_id(
                request_id=request.message_id,
                reply_port=reply_port,
            )
            existed = _channel_message_row(connection, reply_id) is not None
            reply = reply_in_transaction(
                connection,
                channel_id=channel_id,
                request_id=request_id,
                actor_id=actor_id,
                payload=payload,
                command_id=command_id,
                observe=self._now,
            )
            reply_row = _channel_message_row(connection, reply.message_id)
            if reply_row is None:
                raise JournalDamaged(f"channel reply {reply.message_id} disappeared")
            stored_reply = _stored_channel_message_from_row(connection, reply_row)
            # Schema 7 writes the command on the reply and validates its plan at
            # this boundary. A migrated schema-6 row is deliberately NULL and
            # retains its historical acknowledgement-based provenance.
            if stored_reply.command_id is not None:
                command = _command_in_transaction(connection, command_id)
                if existed:
                    validated_channel_command_reply(command, request, reply)
                else:
                    validated_new_channel_command_reply(command, request, reply)
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
            _validate_channel_history(connection)
            row = _channel_message_row(connection, message_id)
            if row is None:
                raise ContractViolation(f"no channel message {message_id} to acknowledge")
            message, _writer = _stored_message_fact(connection, row)
            if message.channel_id != channel_id:
                raise ContractViolation(f"no channel message {message_id} to acknowledge")
            if message.kind == "request":
                # A delivery observation may follow a complete reply, but it
                # may never manufacture the missing atomic half of a torn one.
                stored_reply_in_transaction(
                    connection,
                    channel_id=message.channel_id,
                    request_id=message.message_id,
                )
            return _claim_acknowledgement(
                connection,
                message,
                message_id,
                actor_id,
                command_id,
                self._now,
            )

    def channel_ack(
        self,
        *,
        message_id: Digest,
        actor_id: str,
    ) -> ChannelAckRecord | None:
        """Read one exact delivery fact together with its owning command."""

        with self._read() as connection:
            _validate_channel_history(connection)
            row = _ack_row(connection, message_id, actor_id)
            return _stored_ack_record(connection, row) if row is not None else None

    def channel_actor_revision(self, *, actor_id: str) -> ActorInboxRevision:
        """One cut over everything addressed to this actor, across channels.

        A transport's cut is per channel so unrelated traffic cannot advance
        it. An actor's inbox is a different query with a different bound: it
        spans channels, so its cut is the whole retained history.
        """

        del actor_id  # the cut bounds history; the query filters the actor
        with self._read() as connection:
            current = _current_revision(connection, channel_id=None)
        return ActorInboxRevision(
            message_seq=current.message_seq,
            ack_seq=current.ack_seq,
        )

    def channel_actor_inbox(
        self,
        *,
        actor_id: str,
        revision: ActorInboxRevision,
        interactions: frozenset[ChannelInteraction],
        after: tuple[int, str] | None,
        limit: int,
    ) -> tuple[ChannelDelivery, ...]:
        """Retained messages addressed to this actor that it may read, at one cut.

        ``interactions`` filters INSIDE the bounded query, so ``limit`` counts
        rows the caller may actually see. Filtering a fetched page afterwards
        would return short or empty pages while matching rows remained beyond
        the cut, and an empty page reads as "done".
        """

        if not interactions:
            return ()
        return self._inbox(
            channel_id=None,
            actor_id=actor_id,
            message_seq=revision.message_seq,
            ack_seq=revision.ack_seq,
            interactions=interactions,
            after=after,
            limit=limit,
        )

    def channel_revision(self, *, channel_id: str) -> ChannelRevision:
        with self._read() as connection:
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
        return self._inbox(
            channel_id=channel_id,
            actor_id=actor_id,
            message_seq=revision.message_seq,
            ack_seq=revision.ack_seq,
            after=after,
            limit=limit,
        )

    def _inbox(
        self,
        *,
        channel_id: str | None,
        actor_id: str,
        message_seq: int,
        ack_seq: int,
        after: tuple[int, str] | None,
        limit: int,
        interactions: frozenset[ChannelInteraction] | None = None,
    ) -> tuple[ChannelDelivery, ...]:
        """One paging law for both revision domains, over raw bounds."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        # `discoverable_by` as one SQL predicate: this actor's own messages,
        # plus open requests. The `kind` test is load-bearing — a reply also
        # carries a null recipient, so matching nulls alone would broadcast
        # every reply to every actor. Every returned row is checked against the
        # law itself below, so the two expressions cannot drift apart quietly.
        visible = [
            "(m.recipient_actor_id = ?"
            " OR (m.kind = 'request' AND m.recipient_actor_id IS NULL))"
        ]
        visible_params: list[object] = [actor_id]
        if channel_id is not None:
            visible.insert(0, "m.channel_id = ?")
            visible_params.insert(0, channel_id)
        if interactions is not None:
            ordered = sorted(interactions)
            visible.append(f"m.interaction IN ({','.join('?' for _ in ordered)})")
            visible_params.extend(ordered)
        if after is not None:
            visible.append(
                "(m.message_seq > ?"
                " OR (m.message_seq = ? AND m.message_id > ?))"
            )
            visible_params.extend((after[0], after[0], after[1]))
        params = [message_seq, *visible_params, limit]
        with self._read() as connection:
            connection.create_function(
                "constructicon_channel_request_routing_matches",
                7,
                _channel_request_routing_matches,
                deterministic=True,
            )
            current = _current_revision(connection, channel_id)

            if message_seq > current.message_seq or ack_seq > current.ack_seq:
                raise InvalidChannelRevision(
                    f"channel revision ({message_seq}, {ack_seq}) is ahead of retained history"
                )
            # An acknowledgement cannot exist in a snapshot that omits the message
            # it acknowledges, so bounds alone do not make a cut real. The probe
            # is scoped exactly as the cut is: a channel-local cut compared
            # against every channel's acks would call a freshly read revision
            # incoherent as soon as one journal carried a second channel.
            coherence = (
                "SELECT 1 FROM channel_acks AS acks"
                " JOIN channel_messages AS messages ON messages.message_id = acks.message_id"
                " WHERE acks.ack_seq <= ? AND messages.message_seq > ?"
            )
            coherence_params: tuple[object, ...] = (ack_seq, message_seq)
            if channel_id is not None:
                coherence += " AND messages.channel_id = ?"
                coherence_params = (*coherence_params, channel_id)
            incoherent = connection.execute(coherence + " LIMIT 1", coherence_params).fetchone()
            if incoherent is not None:
                raise InvalidChannelRevision(
                    f"channel revision ({message_seq}, {ack_seq}) acknowledges a "
                    "message it does not include"
                )
            rows = connection.execute(
                "SELECT m.* FROM channel_messages AS m"
                " LEFT JOIN attestations AS a ON a.attestation_id = m.attestation_id"
                " WHERE m.message_seq <= ? AND (("
                + " AND ".join(visible)
                + f") OR ({_INVALID_INBOX_ROUTING})"
                + f" OR ({_INBOX_REQUEST_PROOF_MISMATCH}))"
                + " ORDER BY m.message_seq, m.message_id LIMIT ?",
                tuple(params),
            ).fetchall()
            requests = _stored_request_facts(connection, rows)
            paged = [
                (
                    _durable_sequence(
                        row["message_seq"],
                        fact=f"channel message {message.message_id} position",
                        kind="message sequence",
                    ),
                    message,
                )
                for row, message in zip(rows, requests, strict=True)
            ]
            if not paged:
                return ()
            paged_message_ids = tuple(str(message.message_id) for _, message in paged)
            acknowledgement_rows: list[sqlite3.Row] = []
            acknowledgement_batch = _sqlite_batch_size(connection, reserved=1)
            for start in range(0, len(paged_message_ids), acknowledgement_batch):
                chunk = paged_message_ids[start : start + acknowledgement_batch]
                placeholders = ",".join("?" for _ in chunk)
                acknowledgement_rows.extend(
                    connection.execute(
                        "SELECT * FROM channel_acks"
                        f" WHERE ack_seq <= ? AND message_id IN ({placeholders})",
                        (ack_seq, *chunk),
                    ).fetchall()
                )
            messages_by_id = {str(message.message_id): message for _, message in paged}
            acknowledged: set[str] = set()
            observed_ack_keys: set[str] = set()
            for row in acknowledgement_rows:
                acknowledgement_message_id = _durable_text(
                    row["message_id"],
                    fact="channel acknowledgement message identity",
                )
                request = messages_by_id.get(acknowledgement_message_id)
                if request is None:
                    raise JournalDamaged(
                        "channel inbox selected an acknowledgement outside its page"
                    )
                stored_ack = _stored_ack_record(
                    connection,
                    row,
                    request=request,
                )
                if stored_ack.ack.actor_id == actor_id:
                    acknowledged.add(str(stored_ack.ack.message_id))
                    observed_ack_keys.add(_channel_ack_fact_key(stored_ack))
            expected_ack_keys = tuple(
                _channel_ack_fact_key_for(message.message_id, actor_id)
                for _, message in paged
            )
            sealed_ack_selectors = _sealed_fact_key_selectors(
                connection,
                family=CHANNEL_ACK_FACT_FAMILY,
                fact_keys=expected_ack_keys,
            )
            sealed_ack_keys_at_cut = {
                fact_key
                for fact_key, selector in sealed_ack_selectors.items()
                if _sequence_from_seal_selector(
                    selector,
                    fact=f"channel acknowledgement {fact_key} sealed position",
                )
                <= ack_seq
            }
            missing_ack_rows = sealed_ack_keys_at_cut - observed_ack_keys
            if missing_ack_rows:
                raise JournalDamaged(
                    "channel acknowledgements disappeared behind their positive seals: "
                    + ", ".join(sorted(missing_ack_rows))
                )
        for _, message in paged:
            # A page names its reader, so over-inclusion is the direction that
            # leaks. Re-deriving the law here is the same discipline
            # `validated_reply` applies to a stored pointer: SQL is a second
            # expression of a rule that lives in one place.
            if not discoverable_by(message, actor_id):
                raise JournalDamaged(
                    f"channel message {message.message_id} reached the inbox of "
                    f"{actor_id!r}, which may not discover it"
                )
        return tuple(
            ChannelDelivery(
                message_seq=message_seq,
                message=message,
                acknowledged=str(message.message_id) in acknowledged,
            )
            for message_seq, message in paged
        )


def reply_in_transaction(
    connection: sqlite3.Connection,
    *,
    channel_id: str,
    request_id: Digest,
    actor_id: str,
    payload: JsonValue,
    command_id: str,
    observe: Callable[[], datetime],
) -> ChannelMessage:
    """The reply and its request ack, inside a transaction someone else owns.

    Exposed at connection level so a caller that must commit further facts in
    the same transaction — a request-bound approval commits its `ApprovalRecord`
    with these two — composes one commit rather than two. Composing two
    committed operations would leave a death between them holding an approval
    that authorizes an exchange nobody answered.
    """

    _validate_channel_history(connection)

    request, reply_port = _request_in_transaction(
        connection,
        channel_id=channel_id,
        request_id=request_id,
    )
    reply_id = reply_message_id(request_id=request.message_id, reply_port=reply_port)
    owned = _reply_owned_by_command(connection, command_id)
    if owned is not None and owned != reply_id:
        raise JournalDamaged(f"command {command_id!r} already replied to a different request")
    stored_fact = stored_reply_in_transaction(
        connection,
        channel_id=channel_id,
        request_id=request_id,
    )
    if stored_fact is not None:
        stored, writer = stored_fact
        # Whose retry is this? A reply names the command that wrote it, so an
        # exact retry of that command reconciles and any other command lost the
        # race — identical bytes included. ADR 0014 admits one reply and owes
        # the loser a typed conflict, not a second success over one fact.
        if writer != command_id:
            raise ChannelReplyConflict(
                f"request {request_id} was already answered by another command"
            )
        candidate = message_for_reply(
            request,
            actor_id=actor_id,
            payload=payload,
            created_at=stored.envelope.created_at,
        )
        if not same_message(stored, candidate):
            raise ChannelReplyConflict(f"request {request_id} already carries a different reply")
        # The reply and acknowledgement were one transaction.  Finding the
        # former without the latter is damage, never an invitation for a retry
        # to manufacture the missing half.  `stored_reply_in_transaction`
        # already proved the acknowledgement before returning this fact.
        return stored
    existing_ack = _ack_row(connection, request.message_id, actor_id)
    if existing_ack is not None and existing_ack["command_id"] == command_id:
        raise JournalDamaged(
            f"command {command_id!r} owns a request acknowledgement without its reply"
        )
    observed_at = observe()
    reply = message_for_reply(
        request,
        actor_id=actor_id,
        payload=payload,
        created_at=observed_at,
    )
    _insert_message(connection, reply, None, command_id)
    _imply_acknowledgement(
        connection,
        request.message_id,
        actor_id,
        command_id,
        observed_at.isoformat(),
    )
    return reply


def stored_reply_in_transaction(
    connection: sqlite3.Connection,
    *,
    channel_id: str,
    request_id: Digest,
) -> tuple[ChannelMessage, str] | None:
    """Read one complete reply fact inside the caller's transaction.

    A stored reply includes its validated relationship to the request, the
    command that wrote it (with the schema-6 acknowledgement fallback), and the
    sender's acknowledgement.  The reply and ack are atomic on every write
    path, so a strict subset is journal damage and must never be healed by an
    idempotent retry.
    """

    request, reply_port = _request_in_transaction(
        connection,
        channel_id=channel_id,
        request_id=request_id,
    )
    reply_id = reply_message_id(request_id=request.message_id, reply_port=reply_port)
    row = _channel_message_row(connection, reply_id)
    if row is None:
        return None
    return _stored_reply_fact(connection, request, row)


def _request_in_transaction(
    connection: sqlite3.Connection,
    *,
    channel_id: str,
    request_id: Digest,
) -> tuple[ChannelMessage, str]:
    row = _channel_message_row(connection, request_id)
    if row is None:
        raise ContractViolation(f"no channel request {request_id} to reply to")
    request = _stored_request_fact(connection, row)
    if (
        request.channel_id != channel_id
        or request.kind != "request"
        or request.reply_port is None
    ):
        raise ContractViolation(f"no channel request {request_id} to reply to")
    return request, request.reply_port


def _stored_reply_fact(
    connection: sqlite3.Connection,
    request: ChannelMessage,
    row: sqlite3.Row,
) -> tuple[ChannelMessage, str]:
    stored_reply = _stored_channel_message_from_row(connection, row)
    candidate = stored_reply.message
    acknowledgement = (
        _ack_row(connection, request.message_id, candidate.sender_actor_id)
        if candidate.sender_actor_id is not None
        else None
    )
    acknowledgement_record, acknowledgement_writer = (
        _decoded_stored_ack_record(connection, acknowledgement)
        if acknowledgement is not None
        else (None, None)
    )
    _validate_reply_provenance_era(
        stored_reply,
        acknowledgement_record,
        legacy_message_through=_channel_provenance_cutoffs(connection)[1],
    )
    acknowledgement_command = (
        acknowledgement_record.command_id if acknowledgement_record is not None else None
    )
    writer = _stored_reply_writer(stored_reply.command_id, acknowledgement_command)
    writer_command = (
        _command_in_transaction(connection, stored_reply.command_id)
        if stored_reply.command_id is not None
        else acknowledgement_writer
    )
    approval_row = (
        connection.execute(
            "SELECT * FROM approvals WHERE command_id = ?",
            (writer,),
        ).fetchone()
        if claims_approval_exchange(request) and writer is not None
        else None
    )
    approval_fact = (
        stored_approval_fact_from_row(connection, approval_row)
        if approval_row is not None
        else None
    )
    validated = _validated_stored_reply_fact(
        request,
        candidate,
        stored_reply.command_id,
        acknowledgement_command=acknowledgement_command,
        stored_approval=(approval_fact[1] if approval_fact is not None else None),
        approval_command=(approval_fact[0] if approval_fact is not None else None),
        writer_command=writer_command,
    )
    if acknowledgement_record is not None and acknowledgement_writer is not None:
        validated_channel_ack_provenance(
            acknowledgement_writer,
            acknowledgement_record,
            request,
            reply=candidate,
            reply_command_id=writer,
            approval=(approval_fact[1] if approval_fact is not None else None),
        )
    return validated


def _validated_stored_reply_fact(
    request: ChannelMessage,
    reply: ChannelMessage,
    reply_command_id: str | None,
    *,
    acknowledgement_command: str | None,
    stored_approval: ApprovalRecord | None,
    approval_command: CommandRecord | None,
    writer_command: CommandRecord | None,
) -> tuple[ChannelMessage, str]:
    """Validate one complete reply fact from already-read immutable rows."""

    carried = approval_record_for_reply(request, reply)
    if acknowledgement_command is None:
        raise JournalDamaged(
            f"channel reply {reply.message_id} exists without its request acknowledgement"
        )
    writer = _stored_reply_writer(reply_command_id, acknowledgement_command)
    assert writer is not None  # the acknowledgement above supplies the legacy fallback
    if reply_command_id is not None and (
        writer_command is None or writer_command.command_id != writer
    ):
        raise JournalDamaged(
            f"channel reply {reply.message_id} names a missing writer command"
        )
    if carried is not None:
        if stored_approval is None or approval_command is None:
            raise JournalDamaged(
                f"approval reply {reply.message_id} exists without the approval "
                "record written in its own transaction"
            )
        if stored_approval != carried:
            raise JournalDamaged(
                f"approval reply {reply.message_id} carries a record its own command did not write"
            )
        validated_channel_approval_exchange(
            approval_command,
            stored_approval,
            request,
            reply,
        )
    elif writer_command is not None:
        validated_channel_command_reply(writer_command, request, reply)
    return reply, writer


def _command_in_transaction(
    connection: sqlite3.Connection,
    command_id: str,
) -> CommandRecord:
    """Read one current channel fact's writer through the canonical decoder."""

    command = command_for_id(connection, command_id)
    if command is None:
        raise JournalDamaged(f"channel fact names missing command {command_id!r}")
    return command


def _stored_reply_writer(
    reply_command_id: str | None,
    acknowledgement_command: str | None,
) -> str | None:
    """Resolve reply provenance on either side of the schema-7 migration."""

    return reply_command_id if reply_command_id is not None else acknowledgement_command


def _stored_request_fact(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    stored: _StoredChannelMessage | None = None,
) -> ChannelMessage:
    """Project one request beside the exact send authority that admitted it."""

    stored = (
        _stored_channel_message_from_row(connection, row)
        if stored is None
        else stored
    )
    request = stored.message
    if request.kind != "request":
        raise JournalDamaged(f"channel message {request.message_id} is not a request")
    attestation_id = stored.attestation_id
    if attestation_id is None:
        raise JournalDamaged(
            f"channel request {request.message_id} names no send attestation"
        )
    attestations = _attestations_in_transaction(connection, (attestation_id,))
    manifest_hashes = _run_manifest_hashes_in_transaction(
        connection,
        (request.envelope.run_id,),
    )
    return _validated_request_attestation(
        request,
        attestations[attestation_id],
        manifest_hash=manifest_hashes[str(request.envelope.run_id)],
    )


def _stored_request_facts(
    connection: sqlite3.Connection,
    rows: Sequence[sqlite3.Row],
) -> tuple[ChannelMessage, ...]:
    """Batch-project requests and their proofs without an N+1 recovery scan."""

    stored = tuple(_stored_channel_message_from_row(connection, row) for row in rows)
    requests = tuple(fact.message for fact in stored)
    if any(request.kind != "request" for request in requests):
        raise JournalDamaged("channel request projection selected a non-request message")
    attestation_ids = tuple(fact.attestation_id for fact in stored)
    if any(attestation_id is None for attestation_id in attestation_ids):
        raise JournalDamaged("channel request projection selected an unattested request")
    exact_attestation_ids = cast(tuple[str, ...], attestation_ids)
    if len(set(exact_attestation_ids)) != len(exact_attestation_ids):
        raise JournalDamaged("multiple channel requests name one send attestation")
    attestations = _attestations_in_transaction(connection, exact_attestation_ids)
    manifest_hashes = _run_manifest_hashes_in_transaction(
        connection,
        tuple(request.envelope.run_id for request in requests),
    )
    return tuple(
        _validated_request_attestation(
            request,
            attestations[attestation_id],
            manifest_hash=manifest_hashes[str(request.envelope.run_id)],
        )
        for request, attestation_id in zip(
            requests,
            exact_attestation_ids,
            strict=True,
        )
    )


def _attestations_in_transaction(
    connection: sqlite3.Connection,
    attestation_ids: Sequence[str],
) -> dict[str, Attestation]:
    """Load one bounded proof map inside the caller's existing snapshot."""

    unique = tuple(dict.fromkeys(attestation_ids))
    if not unique:
        return {}
    rows: list[sqlite3.Row] = []
    batch_size = _sqlite_batch_size(connection)
    for start in range(0, len(unique), batch_size):
        chunk = unique[start : start + batch_size]
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(
            connection.execute(
                "SELECT attestation_id, attestation_json FROM attestations"
                f" WHERE attestation_id IN ({placeholders})",
                chunk,
            ).fetchall()
        )
    by_id: dict[str, Attestation] = {}
    for row in rows:
        attestation_id = _durable_text(
            row["attestation_id"],
            fact="channel send attestation identity",
        )
        if attestation_id in by_id:
            raise JournalDamaged(
                f"channel send attestation {attestation_id!r} is stored more than once"
            )
        stored = require_attestation_seal(connection, row)
        if stored.attestation.attestation_id != attestation_id:
            raise JournalDamaged(
                f"channel send attestation {attestation_id!r} contradicts its selector"
            )
        by_id[attestation_id] = stored.attestation
    missing = sorted(set(unique) - by_id.keys())
    if missing:
        raise JournalDamaged(
            f"channel requests name missing send attestations: {missing}"
        )
    return by_id


def _run_manifest_hashes_in_transaction(
    connection: sqlite3.Connection,
    run_ids: Sequence[RunId],
) -> dict[str, Digest]:
    """Load the exact admitted world for every request in this snapshot."""

    unique = tuple(dict.fromkeys(str(run_id) for run_id in run_ids))
    if not unique:
        return {}
    # Local import preserves the acyclic module boundary: the run projector
    # reaches attestation provenance for its global orphan proof.
    from constructicon.substrate.journal._sqlite_runs import run_facts_for_id

    by_id: dict[str, Digest] = {}
    for run_id in unique:
        facts = run_facts_for_id(connection, RunId(run_id))
        if facts is None:
            continue
        world, _event_seq, _event_kind = facts
        if str(world.run_id) != run_id:
            raise JournalDamaged(
                f"channel request run {run_id!r} contradicts its selector"
            )
        by_id[run_id] = world.manifest.manifest_hash
    missing = sorted(set(unique) - by_id.keys())
    if missing:
        raise JournalDamaged(f"channel requests name missing runs: {missing}")
    return by_id


def _validate_intent_attestation(
    connection: sqlite3.Connection,
    intent: ChannelSendIntent,
    *,
    attestation_id: str,
) -> Attestation:
    attestation = _attestations_in_transaction(connection, (attestation_id,))[attestation_id]
    manifest_hash = _run_manifest_hashes_in_transaction(
        connection,
        (intent.run_id,),
    )[str(intent.run_id)]
    try:
        return validated_channel_send_attestation(
            attestation,
            intent,
            expected_manifest_hash=manifest_hash,
        )
    except (TypeError, ValueError) as exc:
        raise JournalDamaged(
            f"channel request {intent.message_id} contradicts its send attestation"
        ) from exc


def _validated_request_attestation(
    request: ChannelMessage,
    attestation: Attestation,
    *,
    manifest_hash: Digest,
) -> ChannelMessage:
    try:
        return validated_attested_channel_request(
            attestation,
            request,
            expected_manifest_hash=manifest_hash,
        )
    except (TypeError, ValueError) as exc:
        raise JournalDamaged(
            f"channel request {request.message_id} contradicts its send attestation"
        ) from exc


def _stored_message_fact(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[ChannelMessage, str | None]:
    """Read one complete request or reply; no exact-read path sees a torn reply."""

    stored = _stored_channel_message_from_row(connection, row)
    message = stored.message
    if message.kind == "request":
        return _stored_request_fact(connection, row, stored=stored), None
    if message.reply_to is None:
        raise JournalDamaged(f"channel reply {message.message_id} names no request")
    request_row = _channel_message_row(connection, message.reply_to)
    if request_row is None:
        raise JournalDamaged(
            f"reply {message.message_id} names request {message.reply_to}, which is not stored"
        )
    request = _stored_request_fact(connection, request_row)
    if request.channel_id != message.channel_id:
        raise JournalDamaged(
            f"reply {message.message_id} names a request in another channel"
        )
    reply, writer = _stored_reply_fact(connection, request, row)
    return reply, writer


def _reply_owned_by_command(
    connection: sqlite3.Connection,
    command_id: str,
) -> Digest | None:
    """The one reply this command owns, on either side of schema 7."""

    current = connection.execute(
        "SELECT * FROM channel_messages WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    legacy = connection.execute(
        "SELECT replies.* FROM channel_messages AS replies"
        " JOIN channel_acks AS acks"
        " ON acks.message_id = replies.reply_to"
        " AND acks.actor_id = replies.sender_actor_id"
        " WHERE replies.command_id IS NULL AND replies.reply_to IS NOT NULL"
        " AND replies.reply_provenance_version IS NULL"
        " AND acks.command_id = ?",
        (command_id,),
    ).fetchone()
    if current is not None and legacy is not None:
        raise JournalDamaged(f"command {command_id!r} owns replies on both sides of schema 7")
    row = current if current is not None else legacy
    if row is None:
        return None
    message = _message_from_row(connection, row)
    if message.kind != "reply":
        raise JournalDamaged(f"command {command_id!r} owns a non-reply channel message")
    return message.message_id


def _current_revision(
    connection: sqlite3.Connection,
    channel_id: str | None,
) -> ChannelRevision:
    """The cut for one channel, or for all retained history when unscoped.

    Scoping matters for a transport: an unrelated channel must not advance a
    channel's cut. An actor's cross-channel inbox is bounded by the whole
    history instead, because that is the history it reads.
    """

    _validate_channel_history(connection)

    message_scope = "1" if channel_id is None else "channel_id = ?"
    message_params: tuple[str, ...] = (
        () if channel_id is None else (channel_id, channel_id)
    )
    message_row = connection.execute(
        f"SELECT COALESCE(MAX(CASE WHEN {message_scope} THEN message_seq END), 0)"
        " AS maximum, COALESCE(MAX(CASE"
        " WHEN typeof(channel_id) != 'text' THEN 1"
        f" WHEN {message_scope} AND (typeof(message_seq) != 'integer'"
        " OR message_seq <= 0) THEN 1 ELSE 0 END), 0) AS damaged"
        " FROM channel_messages",
        message_params,
    ).fetchone()
    ack_where = "" if channel_id is None else " WHERE messages.channel_id = ?"
    ack_params: tuple[str, ...] = () if channel_id is None else (channel_id,)
    ack_row = connection.execute(
        "SELECT COALESCE(MAX(acks.ack_seq), 0) AS maximum,"
        " COALESCE(MAX(CASE WHEN typeof(acks.ack_seq) != 'integer'"
        " OR acks.ack_seq <= 0 THEN 1 ELSE 0 END), 0) AS damaged"
        " FROM channel_acks AS acks"
        " JOIN channel_messages AS messages ON messages.message_id = acks.message_id"
        f"{ack_where}",
        ack_params,
    ).fetchone()
    orphan = connection.execute(
        "SELECT 1 FROM channel_acks AS acks"
        " LEFT JOIN channel_messages AS messages"
        " ON messages.message_id = acks.message_id"
        " WHERE messages.message_id IS NULL LIMIT 1"
    ).fetchone()
    if orphan is not None:
        raise JournalDamaged("channel acknowledgement names a missing message")
    message_damage = _durable_sequence(
        message_row["damaged"],
        fact="channel message sequence integrity flag",
        allow_zero=True,
        kind="message sequence",
    )
    acknowledgement_damage = _durable_sequence(
        ack_row["damaged"],
        fact="channel acknowledgement sequence integrity flag",
        allow_zero=True,
        kind="acknowledgement sequence",
    )
    if message_damage != 0:
        raise JournalDamaged("channel message sequence history is damaged")
    if acknowledgement_damage != 0:
        raise JournalDamaged("channel acknowledgement sequence history is damaged")
    return ChannelRevision(
        message_seq=_durable_sequence(
            message_row["maximum"],
            fact="maximum channel message position",
            allow_zero=True,
            kind="message sequence",
        ),
        ack_seq=_durable_sequence(
            ack_row["maximum"],
            fact="maximum channel acknowledgement position",
            allow_zero=True,
            kind="acknowledgement sequence",
        ),
    )


def _insert_message(
    connection: sqlite3.Connection,
    message: ChannelMessage,
    attestation_id: str | None,
    command_id: str | None = None,
) -> None:
    """Store one message and the authority that admitted it.

    A request names its attestation; a reply names the command. Exactly one of
    the two is ever set, because exactly one kind of authority writes each.
    """

    connection.execute(
        f"INSERT INTO channel_messages ({_MESSAGE_COLUMNS})"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            (message.reply_contract.schema_hash if message.reply_contract is not None else None),
            message.envelope.model_dump_json(),
            attestation_id,
            command_id,
            _CURRENT_REPLY_PROVENANCE_VERSION if command_id is not None else None,
        ),
    )
    row = _channel_message_row(connection, message.message_id)
    if row is None:
        raise JournalDamaged(
            f"channel message {message.message_id} disappeared during insertion"
        )
    seal_channel_message(connection, row)


def _claim_acknowledgement(
    connection: sqlite3.Connection,
    request: ChannelMessage,
    message_id: Digest,
    actor_id: str,
    command_id: str,
    observe: Callable[[], datetime],
) -> ChannelAck:
    """One delivery fact, claimed by one command; a second command conflicts."""

    stored = _stored_ack(connection, message_id, actor_id, command_id)
    if stored is not None:
        if stored.command_id != command_id:
            raise ChannelAckConflict(
                f"message {message_id} is already acknowledged for {actor_id!r} "
                f"by another command; {command_id!r} may not claim it"
            )
        return stored.ack
    command = _command_in_transaction(connection, command_id)
    validated_channel_command_ack(command, request)
    return _insert_ack(
        connection,
        message_id,
        actor_id,
        command_id,
        observe().isoformat(),
    )


def _imply_acknowledgement(
    connection: sqlite3.Connection,
    message_id: Digest,
    actor_id: str,
    command_id: str,
    acked_at: str,
) -> ChannelAck:
    """The request is acknowledged for this actor, whoever first recorded it.

    A reply does not *claim* a delivery fact, it implies one: an actor that
    answers a request plainly received it. Demanding that the reply's own
    command own that row would mean an actor who acknowledged a request before
    answering it could never answer it — a delivery observation would have
    consumed the right to reply, and for an addressed request nobody else could
    take it up.
    """

    stored = _stored_ack(connection, message_id, actor_id, command_id)
    if stored is not None:
        return stored.ack
    return _insert_ack(connection, message_id, actor_id, command_id, acked_at)


def _stored_ack(
    connection: sqlite3.Connection,
    message_id: Digest,
    actor_id: str,
    command_id: str,
) -> ChannelAckRecord | None:
    reply_key = _reply_ack_key_owned_by_command(connection, command_id)
    if reply_key is not None and reply_key != (str(message_id), actor_id):
        raise JournalDamaged(f"command {command_id!r} already replied to a different request")
    owner = connection.execute(
        "SELECT message_id, actor_id FROM channel_acks WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    if owner is not None:
        owner_key = (
            _durable_text(
                owner["message_id"],
                fact=f"command {command_id!r} acknowledgement message",
            ),
            _durable_text(
                owner["actor_id"],
                fact=f"command {command_id!r} acknowledgement actor",
            ),
        )
        if owner_key != (str(message_id), actor_id):
            raise JournalDamaged(
                f"command {command_id!r} already acknowledged a different message"
            )
    row = _ack_row(connection, message_id, actor_id)
    return _stored_ack_record(connection, row) if row is not None else None


def _reply_ack_key_owned_by_command(
    connection: sqlite3.Connection,
    command_id: str,
) -> tuple[str, str] | None:
    """The delivery key implied by this command's reply, if it owns one."""

    reply_id = _reply_owned_by_command(connection, command_id)
    if reply_id is None:
        return None
    row = _channel_message_row(connection, reply_id)
    if row is None:
        raise JournalDamaged(f"command {command_id!r} owns an invalid channel reply")
    reply = _message_from_row(connection, row)
    if reply.kind != "reply" or reply.reply_to is None or reply.sender_actor_id is None:
        raise JournalDamaged(f"command {command_id!r} owns an invalid channel reply")
    return str(reply.reply_to), reply.sender_actor_id


def _ack_row(
    connection: sqlite3.Connection,
    message_id: Digest,
    actor_id: str,
) -> sqlite3.Row | None:
    rows = connection.execute(
        "SELECT * FROM channel_acks WHERE message_id = ? ORDER BY ack_seq",
        (str(message_id),),
    ).fetchall()
    selected: sqlite3.Row | None = None
    for row in rows:
        record, _command = _decoded_stored_ack_record(connection, row)
        if record.ack.actor_id != actor_id:
            continue
        if selected is not None:
            raise JournalDamaged(
                f"channel message {message_id} has duplicate acknowledgements for "
                f"actor {actor_id!r}"
            )
        selected = row
    if selected is None:
        fact_key = _channel_ack_fact_key_for(message_id, actor_id)
        if durable_fact_seal(
            connection,
            family=CHANNEL_ACK_FACT_FAMILY,
            fact_key=fact_key,
        ) is not None:
            raise JournalDamaged(
                f"channel acknowledgement {fact_key} disappeared behind its positive seal"
            )
    return selected


def _insert_ack(
    connection: sqlite3.Connection,
    message_id: Digest,
    actor_id: str,
    command_id: str,
    acked_at: str,
) -> ChannelAck:
    command = _command_in_transaction(connection, command_id)
    fact = {
        "channels_reply": "channel reply",
        "runs_approve": "approval exchange",
        "channels_ack": "channel acknowledgement",
    }.get(command.operation, "channel acknowledgement")
    if command.state != "prepared":
        raise JournalDamaged(
            f"new {fact} for {message_id} belongs to a terminal command"
        )
    if command.plan is None:
        raise JournalDamaged(
            f"new {fact} for {message_id} belongs to a planless command"
        )
    connection.execute(
        "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
        " ack_provenance_version) VALUES (?, ?, ?, ?, ?)",
        (
            str(message_id),
            actor_id,
            command_id,
            acked_at,
            _CURRENT_ACK_PROVENANCE_VERSION,
        ),
    )
    row = connection.execute(
        "SELECT * FROM channel_acks WHERE message_id = ? AND actor_id = ?",
        (str(message_id), actor_id),
    ).fetchone()
    if row is None:
        raise JournalDamaged(
            f"channel acknowledgement for {message_id}/{actor_id!r} disappeared"
        )
    seal_channel_ack(connection, row)
    return _ack_from_values(
        message_id=str(message_id),
        actor_id=actor_id,
        acked_at=acked_at,
    )


def _ack_from_row(row: sqlite3.Row) -> ChannelAck:
    return _ack_from_values(
        message_id=row["message_id"],
        actor_id=row["actor_id"],
        acked_at=row["acked_at"],
    )


def _ack_from_values(
    *,
    message_id: object,
    actor_id: object,
    acked_at: object,
) -> ChannelAck:
    rendered_message_id = message_id if type(message_id) is str else repr(message_id)
    rendered_actor_id = actor_id if type(actor_id) is str else repr(actor_id)
    try:
        exact_message_id = _durable_text(
            message_id,
            fact="channel acknowledgement message identity",
        )
        exact_actor_id = _durable_text(
            actor_id,
            fact="channel acknowledgement actor identity",
        )
        exact_acked_at = _durable_text(
            acked_at,
            fact="channel acknowledgement observation time",
        )
        return ChannelAck(
            message_id=Digest(exact_message_id),
            actor_id=exact_actor_id,
            acked_at=_durable_datetime(
                exact_acked_at,
                fact=(
                    f"channel acknowledgement for message {rendered_message_id!r} "
                    f"and actor {rendered_actor_id!r} observation time"
                ),
            ),
        )
    except (JournalDamaged, TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(
            f"channel acknowledgement for message {rendered_message_id!r} and actor "
            f"{rendered_actor_id!r} is not a valid durable fact"
        ) from exc


def _stored_ack_record(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    request: ChannelMessage | None = None,
) -> ChannelAckRecord:
    record, command = _decoded_stored_ack_record(connection, row)
    if command is None:
        return record
    if request is None:
        request_row = _channel_message_row(connection, record.ack.message_id)
        if request_row is None:
            raise JournalDamaged(
                f"channel acknowledgement names missing message {record.ack.message_id}"
            )
        request = _stored_request_fact(connection, request_row)
    reply: ChannelMessage | None = None
    reply_command_id: str | None = None
    approval: ApprovalRecord | None = None
    if command.operation in {"channels_reply", "runs_approve"}:
        reply_row = connection.execute(
            "SELECT * FROM channel_messages WHERE reply_to = ? AND channel_id = ?",
            (str(request.message_id), request.channel_id),
        ).fetchone()
        if reply_row is not None:
            stored_reply = _stored_channel_message_from_row(connection, reply_row)
            reply = stored_reply.message
            reply_command_id = _stored_reply_writer(
                stored_reply.command_id,
                record.command_id,
            )
        if command.operation == "runs_approve":
            approval_row = connection.execute(
                "SELECT * FROM approvals WHERE command_id = ?",
                (command.command_id,),
            ).fetchone()
            if approval_row is not None:
                approval_command, approval = stored_approval_fact_from_row(
                    connection,
                    approval_row,
                )
                if approval_command.command_id != command.command_id:
                    raise JournalDamaged(
                        f"approval {approval.approval_id!r} contradicts its "
                        "acknowledgement command"
                    )
    return validated_channel_ack_provenance(
        command,
        record,
        request,
        reply=reply,
        reply_command_id=reply_command_id,
        approval=approval,
    )


def _decoded_ack_record_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[ChannelAckRecord, CommandRecord | None]:
    """Decode row shape and era before applying exchange semantics."""

    command_id = row["command_id"]
    command: CommandRecord | None = None
    provenance_version = row["ack_provenance_version"]
    if (
        type(provenance_version) is int
        and provenance_version == 1
        and type(command_id) is str
    ):
        command = command_for_id(connection, command_id)
    record = _ack_record_from_values(
        message_id=row["message_id"],
        actor_id=row["actor_id"],
        command_id=command_id,
        acked_at=row["acked_at"],
        ack_seq=row["ack_seq"],
        provenance_version=provenance_version,
        legacy_ack_through=_ack_provenance_cutoff(connection),
        command=command,
    )
    if command is not None and command.actor.actor_id != record.ack.actor_id:
        raise JournalDamaged(
            f"channel acknowledgement for message {record.ack.message_id} contradicts "
            "its command's run, actor, or subject"
        )
    return record, command


def _channel_ack_fact_key_for(message_id: Digest, actor_id: str) -> str:
    return canonical_json(
        {
            "message_id": str(message_id),
            "actor_id": actor_id,
        }
    )


def _channel_ack_fact_key(record: ChannelAckRecord) -> str:
    return _channel_ack_fact_key_for(record.ack.message_id, record.ack.actor_id)


def channel_ack_fact_hash(
    row: sqlite3.Row,
    *,
    record: ChannelAckRecord | None = None,
    connection: sqlite3.Connection,
) -> Digest:
    """Hash every exact scalar in one immutable delivery observation."""

    if record is None:
        record, _command = _decoded_ack_record_from_row(connection, row)
    return _channel_ack_fact_hash_values(
        message_id=row["message_id"],
        actor_id=row["actor_id"],
        command_id=row["command_id"],
        acked_at=row["acked_at"],
        ack_seq=row["ack_seq"],
        record=record,
    )


def _channel_ack_fact_hash_values(
    *,
    message_id: object,
    actor_id: object,
    command_id: object,
    acked_at: object,
    ack_seq: object,
    record: ChannelAckRecord,
) -> Digest:
    exact_ack_seq = _durable_sequence(
        ack_seq,
        fact=(
            f"channel acknowledgement for {record.ack.message_id}/"
            f"{record.ack.actor_id!r} position"
        ),
        kind="acknowledgement sequence",
    )
    return durable_fact_hash(
        CHANNEL_ACK_FACT_FAMILY,
        {
            "ack_seq": exact_ack_seq,
            "message_id": _durable_text(
                message_id,
                fact="channel acknowledgement sealed message identity",
            ),
            "actor_id": _durable_text(
                actor_id,
                fact="channel acknowledgement sealed actor identity",
            ),
            "command_id": _durable_text(
                command_id,
                fact="channel acknowledgement sealed command identity",
            ),
            "acked_at": _durable_text(
                acked_at,
                fact="channel acknowledgement sealed observation time",
            ),
            "ack_provenance_version": record.provenance_version,
        },
    )


def seal_channel_ack(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Write or reconcile one acknowledgement's independent positive seal."""

    record, _command = _decoded_ack_record_from_row(connection, row)
    ack_seq = _durable_sequence(
        row["ack_seq"],
        fact="channel acknowledgement sealed position",
        kind="acknowledgement sequence",
    )
    store_durable_fact_seal(
        connection,
        family=CHANNEL_ACK_FACT_FAMILY,
        fact_key=_channel_ack_fact_key(record),
        selector=str(ack_seq),
        fact_hash=channel_ack_fact_hash(
            row,
            record=record,
            connection=connection,
        ),
    )


def _decoded_stored_ack_record(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[ChannelAckRecord, CommandRecord | None]:
    """Project one acknowledgement only beside its independent positive seal."""

    record, command = _decoded_ack_record_from_row(connection, row)
    ack_seq = _durable_sequence(
        row["ack_seq"],
        fact="channel acknowledgement sealed position",
        kind="acknowledgement sequence",
    )
    require_durable_fact_seal(
        connection,
        family=CHANNEL_ACK_FACT_FAMILY,
        fact_key=_channel_ack_fact_key(record),
        selector=str(ack_seq),
        fact_hash=channel_ack_fact_hash(
            row,
            record=record,
            connection=connection,
        ),
    )
    return record, command


def _decoded_channel_provenance(
    connection: sqlite3.Connection,
) -> tuple[sqlite3.Row, tuple[int, int]]:
    """Decode the singleton cutoff row without consulting its fact seal."""

    try:
        rows = connection.execute(
            "SELECT singleton, legacy_ack_through, legacy_message_through"
            " FROM channel_provenance"
        ).fetchall()
    except sqlite3.Error as exc:
        raise JournalDamaged(
            "channel provenance cutoff is missing or unreadable"
        ) from exc
    if (
        len(rows) != 1
        or type(rows[0]["singleton"]) is not int
        or rows[0]["singleton"] != 1
        or type(rows[0]["legacy_ack_through"]) is not int
        or rows[0]["legacy_ack_through"] < 0
        or type(rows[0]["legacy_message_through"]) is not int
        or rows[0]["legacy_message_through"] < 0
    ):
        raise JournalDamaged("channel provenance cutoff is invalid")
    return rows[0], (
        _durable_sequence(
            rows[0]["legacy_ack_through"],
            fact="channel acknowledgement provenance cutoff",
            allow_zero=True,
            kind="acknowledgement sequence",
        ),
        _durable_sequence(
            rows[0]["legacy_message_through"],
            fact="channel message provenance cutoff",
            allow_zero=True,
            kind="message sequence",
        ),
    )


def channel_provenance_fact_hash(row: sqlite3.Row) -> Digest:
    """Hash the exact immutable migration cut that distinguishes row eras."""

    singleton = _durable_sequence(
        row["singleton"],
        fact="channel provenance singleton",
        kind="singleton",
    )
    legacy_ack_through = _durable_sequence(
        row["legacy_ack_through"],
        fact="channel acknowledgement provenance cutoff",
        allow_zero=True,
        kind="acknowledgement sequence",
    )
    legacy_message_through = _durable_sequence(
        row["legacy_message_through"],
        fact="channel message provenance cutoff",
        allow_zero=True,
        kind="message sequence",
    )
    if singleton != 1:
        raise JournalDamaged("channel provenance cutoff is invalid")
    return durable_fact_hash(
        CHANNEL_PROVENANCE_FACT_FAMILY,
        {
            "singleton": singleton,
            "legacy_ack_through": legacy_ack_through,
            "legacy_message_through": legacy_message_through,
        },
    )


def seal_channel_provenance(connection: sqlite3.Connection) -> None:
    """Write or reconcile the independent seal for the one migration cut."""

    row, _cutoffs = _decoded_channel_provenance(connection)
    store_durable_fact_seal(
        connection,
        family=CHANNEL_PROVENANCE_FACT_FAMILY,
        fact_key="1",
        selector="1",
        fact_hash=channel_provenance_fact_hash(row),
    )


def _required_channel_provenance_cutoffs(
    connection: sqlite3.Connection,
) -> tuple[int, int]:
    row, cutoffs = _decoded_channel_provenance(connection)
    require_durable_fact_seal(
        connection,
        family=CHANNEL_PROVENANCE_FACT_FAMILY,
        fact_key="1",
        selector="1",
        fact_hash=channel_provenance_fact_hash(row),
    )
    return cutoffs


def _channel_provenance_cutoffs(connection: sqlite3.Connection) -> tuple[int, int]:
    return _required_channel_provenance_cutoffs(connection)


def _ack_provenance_cutoff(connection: sqlite3.Connection) -> int:
    return _required_channel_provenance_cutoffs(connection)[0]


def _validate_reply_provenance_era(
    stored: _StoredChannelMessage,
    acknowledgement: ChannelAckRecord | None,
    *,
    legacy_message_through: int,
) -> None:
    """Distinguish migrated replies from current facts without inference."""

    if stored.message.kind != "reply":
        raise JournalDamaged(
            f"channel message {stored.message.message_id} is not a reply"
        )
    if stored.command_id is None:
        if (
            stored.reply_provenance_version is not None
            or stored.message_seq > legacy_message_through
            or acknowledgement is None
            or acknowledgement.provenance_version != 0
        ):
            raise JournalDamaged(
                f"channel reply {stored.message.message_id} has invalid provenance era"
            )
        return
    if (
        stored.reply_provenance_version != _CURRENT_REPLY_PROVENANCE_VERSION
        or stored.message_seq <= legacy_message_through
    ):
        raise JournalDamaged(
            f"channel reply {stored.message.message_id} has invalid provenance era"
        )


def _ack_record_from_values(
    *,
    message_id: object,
    actor_id: object,
    command_id: object,
    acked_at: object,
    ack_seq: object,
    provenance_version: object,
    legacy_ack_through: int,
    command: CommandRecord | None,
) -> ChannelAckRecord:
    ack = _ack_from_values(
        message_id=message_id,
        actor_id=actor_id,
        acked_at=acked_at,
    )
    try:
        exact_command_id = _durable_text(
            command_id,
            fact="channel acknowledgement command identity",
        )
        exact_ack_seq = _durable_sequence(
            ack_seq,
            fact="channel acknowledgement position",
            kind="acknowledgement sequence",
        )
        if type(provenance_version) is int and provenance_version == 0:
            exact_provenance: Literal[0, 1] = 0
            if exact_ack_seq > legacy_ack_through:
                raise ValueError("legacy acknowledgement lies above its migration cutoff")
            if command is not None and command.command_id != exact_command_id:
                raise ValueError("legacy acknowledgement names another command")
        elif type(provenance_version) is int and provenance_version == 1:
            exact_provenance = 1
            if (
                exact_ack_seq <= legacy_ack_through
                or command is None
                or command.command_id != exact_command_id
            ):
                raise ValueError("current acknowledgement has no exact writer command")
        else:
            raise ValueError("acknowledgement provenance version is unsupported")
        return ChannelAckRecord(
            ack=ack,
            command_id=exact_command_id,
            provenance_version=exact_provenance,
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(
            f"channel acknowledgement for message {ack.message_id!s} and actor "
            f"{ack.actor_id!r} has invalid command provenance"
        ) from exc


def _stored_ack_record_from_values(
    connection: sqlite3.Connection,
    *,
    message_id: object,
    actor_id: object,
    command_id: object,
    acked_at: object,
    ack_seq: object,
    provenance_version: object,
    legacy_ack_through: int,
    command: CommandRecord | None,
) -> ChannelAckRecord:
    """Project one aliased/joined ack only beside its exact positive seal."""

    record = _ack_record_from_values(
        message_id=message_id,
        actor_id=actor_id,
        command_id=command_id,
        acked_at=acked_at,
        ack_seq=ack_seq,
        provenance_version=provenance_version,
        legacy_ack_through=legacy_ack_through,
        command=command,
    )
    exact_ack_seq = _durable_sequence(
        ack_seq,
        fact="channel acknowledgement sealed position",
        kind="acknowledgement sequence",
    )
    require_durable_fact_seal(
        connection,
        family=CHANNEL_ACK_FACT_FAMILY,
        fact_key=_channel_ack_fact_key(record),
        selector=str(exact_ack_seq),
        fact_hash=_channel_ack_fact_hash_values(
            message_id=message_id,
            actor_id=actor_id,
            command_id=command_id,
            acked_at=acked_at,
            ack_seq=ack_seq,
            record=record,
        ),
    )
    return record


def _optional_durable_text(raw: object, *, fact: str) -> str | None:
    return None if raw is None else _durable_text(raw, fact=fact)


def _decoded_channel_message_from_row(row: sqlite3.Row) -> _StoredChannelMessage:
    """Decode one message and every relational scalar without normalization."""

    raw_message_id = row["message_id"]
    identity = f"channel message {raw_message_id!r}"
    try:
        message_seq = _durable_sequence(
            row["message_seq"],
            fact=f"{identity} position",
            kind="message sequence",
        )
        message_id = _durable_digest(
            _durable_text(raw_message_id, fact=f"{identity} identity"),
            fact=f"{identity} identity",
        )
        channel_id = _durable_text(row["channel_id"], fact=f"{identity} channel")
        lane = _durable_text(row["lane"], fact=f"{identity} lane")
        interaction = cast(
            ChannelInteraction,
            _durable_text(row["interaction"], fact=f"{identity} interaction"),
        )
        kind = cast(
            ChannelMessageKind,
            _durable_text(row["kind"], fact=f"{identity} kind"),
        )
        reply_to_text = _optional_durable_text(
            row["reply_to"],
            fact=f"{identity} request identity",
        )
        reply_to = (
            _durable_digest(reply_to_text, fact=f"{identity} request identity")
            if reply_to_text is not None
            else None
        )
        recipient_actor_id = _optional_durable_text(
            row["recipient_actor_id"],
            fact=f"{identity} recipient actor",
        )
        sender_actor_id = _optional_durable_text(
            row["sender_actor_id"],
            fact=f"{identity} sender actor",
        )
        run_id = RunId(_durable_text(row["run_id"], fact=f"{identity} run"))
        path_json = _durable_text(row["path_json"], fact=f"{identity} path projection")
        port = _durable_text(row["port"], fact=f"{identity} port")
        contract = ChannelContract(
            type_id=_durable_text(
                row["type_id"],
                fact=f"{identity} contract type",
            ),
            schema_hash=_durable_text(
                row["schema_hash"],
                fact=f"{identity} contract schema",
            ),
        )
        reply_port = _optional_durable_text(
            row["reply_port"],
            fact=f"{identity} reply port",
        )
        reply_type_id = _optional_durable_text(
            row["reply_type_id"],
            fact=f"{identity} reply contract type",
        )
        reply_schema_hash = _optional_durable_text(
            row["reply_schema_hash"],
            fact=f"{identity} reply contract schema",
        )
        if (reply_type_id is None) != (reply_schema_hash is None):
            raise ValueError("reply contract columns are only meaningful together")
        reply_contract = (
            ChannelContract(type_id=reply_type_id, schema_hash=reply_schema_hash)
            if reply_type_id is not None and reply_schema_hash is not None
            else None
        )
        raw_envelope = parse_json_value(
            _durable_text(
                row["envelope_json"],
                fact=f"{identity} envelope",
            )
        )
        envelope = Envelope[JsonValue].model_validate(raw_envelope)
        if canonical_json(raw_envelope) != canonical_json(
            json_value(envelope.model_dump(mode="json"))
        ):
            raise ValueError("channel envelope is not a lossless durable value")
        attestation_id = _optional_durable_text(
            row["attestation_id"],
            fact=f"{identity} attestation identity",
        )
        command_id = _optional_durable_text(
            row["command_id"],
            fact=f"{identity} command identity",
        )
        raw_reply_provenance = row["reply_provenance_version"]
        reply_provenance_version: Literal[1] | None
        if raw_reply_provenance is None:
            reply_provenance_version = None
        elif (
            type(raw_reply_provenance) is int
            and raw_reply_provenance == _CURRENT_REPLY_PROVENANCE_VERSION
        ):
            reply_provenance_version = 1
        else:
            raise ValueError("channel reply provenance version is unsupported")
        message = ChannelMessage(
            message_id=message_id,
            channel_id=channel_id,
            lane=lane,
            interaction=interaction,
            kind=kind,
            reply_to=reply_to,
            recipient_actor_id=recipient_actor_id,
            sender_actor_id=sender_actor_id,
            contract=contract,
            reply_contract=reply_contract,
            reply_port=reply_port,
            envelope=envelope,
        )
        if (
            message.envelope.run_id != run_id
            or canonical_json(message.envelope.path.model_dump(mode="json"))
            != path_json
            or message.envelope.port != port
        ):
            raise ValueError("channel envelope contradicts its relational projection")
        if message.kind == "request":
            if (
                attestation_id is None
                or command_id is not None
                or reply_provenance_version is not None
            ):
                raise ValueError("channel request has invalid durable authority columns")
        elif (
            attestation_id is not None
            or (command_id is None) != (reply_provenance_version is None)
        ):
            raise ValueError("channel reply has invalid durable authority columns")
        return _StoredChannelMessage(
            message_seq=message_seq,
            message=message,
            attestation_id=attestation_id,
            command_id=command_id,
            reply_provenance_version=reply_provenance_version,
        )
    except (JournalDamaged, TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(f"{identity} is not a valid durable fact") from exc


def channel_message_fact_hash(
    row: sqlite3.Row,
    *,
    stored: _StoredChannelMessage | None = None,
) -> Digest:
    """Hash every exact SQLite scalar in one immutable channel message."""

    stored = _decoded_channel_message_from_row(row) if stored is None else stored
    identity = f"channel message {stored.message.message_id}"
    optional_text = {
        "reply_to",
        "recipient_actor_id",
        "sender_actor_id",
        "reply_port",
        "reply_type_id",
        "reply_schema_hash",
        "attestation_id",
        "command_id",
    }
    exact_fields: dict[str, object] = {"message_seq": stored.message_seq}
    for name in _MESSAGE_COLUMN_NAMES:
        raw = row[name]
        if name == "reply_provenance_version":
            exact_fields[name] = stored.reply_provenance_version
        elif name in optional_text:
            exact_fields[name] = _optional_durable_text(
                raw,
                fact=f"{identity} sealed {name}",
            )
        else:
            exact_fields[name] = _durable_text(
                raw,
                fact=f"{identity} sealed {name}",
            )
    return durable_fact_hash(CHANNEL_MESSAGE_FACT_FAMILY, exact_fields)


def seal_channel_message(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Write or reconcile one message's independent identity/content seal."""

    stored = _decoded_channel_message_from_row(row)
    store_durable_fact_seal(
        connection,
        family=CHANNEL_MESSAGE_FACT_FAMILY,
        fact_key=str(stored.message.message_id),
        selector=str(stored.message_seq),
        fact_hash=channel_message_fact_hash(row, stored=stored),
    )


def _stored_channel_message_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> _StoredChannelMessage:
    """Project one message only beside its independent positive seal."""

    stored = _decoded_channel_message_from_row(row)
    require_durable_fact_seal(
        connection,
        family=CHANNEL_MESSAGE_FACT_FAMILY,
        fact_key=str(stored.message.message_id),
        selector=str(stored.message_seq),
        fact_hash=channel_message_fact_hash(row, stored=stored),
    )
    return stored


def _message_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> ChannelMessage:
    return _stored_channel_message_from_row(connection, row).message


def validate_channel_fact_seal_inventory(
    connection: sqlite3.Connection,
) -> tuple[int, int]:
    """Prove every channel row and both immutable era cutoffs, both ways."""

    try:
        cutoffs = _required_channel_provenance_cutoffs(connection)
        message_rows = connection.execute(
            "SELECT * FROM channel_messages ORDER BY message_seq"
        ).fetchall()
        for row in message_rows:
            _stored_message_fact(connection, row)
        acknowledgement_rows = connection.execute(
            "SELECT * FROM channel_acks ORDER BY ack_seq"
        ).fetchall()
        acknowledgements: set[tuple[str, str]] = set()
        for row in acknowledgement_rows:
            record = _stored_ack_record(connection, row)
            key = (str(record.ack.message_id), record.ack.actor_id)
            if key in acknowledgements:
                raise JournalDamaged(
                    f"channel acknowledgement {key!r} is stored more than once"
                )
            acknowledgements.add(key)
        retained = {
            _durable_text(row["family"], fact="channel fact seal family"):
            _durable_sequence(
                row["retained"],
                fact="channel fact seal count",
                allow_zero=True,
                kind="count",
            )
            for row in connection.execute(
                "SELECT family, COUNT(*) AS retained FROM durable_fact_seals"
                " WHERE family IN (?, ?, ?) GROUP BY family",
                (
                    CHANNEL_MESSAGE_FACT_FAMILY,
                    CHANNEL_ACK_FACT_FAMILY,
                    CHANNEL_PROVENANCE_FACT_FAMILY,
                ),
            ).fetchall()
        }
    except sqlite3.Error as exc:
        raise JournalDamaged("channel fact-seal inventory is unreadable") from exc
    expected = {
        CHANNEL_MESSAGE_FACT_FAMILY: len(message_rows),
        CHANNEL_ACK_FACT_FAMILY: len(acknowledgement_rows),
        CHANNEL_PROVENANCE_FACT_FAMILY: 1,
    }
    if any(retained.get(family, 0) != count for family, count in expected.items()):
        raise JournalDamaged(
            "channel fact-seal inventory has an orphan or missing primary fact"
        )
    return cutoffs
