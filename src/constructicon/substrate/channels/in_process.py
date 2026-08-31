"""The in-process channel: same contract, honestly weaker durability.

It exists for same-process composition and for the shared contract suite, not
as the human-wait transport. Its profile says ``durability="process"`` and it
never pretends a new instance remembers anything (I4).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from threading import Lock

from constructicon.core.channel import (
    MAX_INBOX_BATCH,
    ChannelAck,
    ChannelAckConflict,
    ChannelDelivery,
    ChannelMessage,
    ChannelProfile,
    ChannelReplyConflict,
    ChannelRevision,
    ChannelSendIntent,
    InvalidChannelRevision,
    discoverable_by,
    message_for_intent,
    message_for_reply,
    reply_message_id,
    same_message,
    validated_reply,
)
from constructicon.core.envelope import utc_now
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import Digest, JsonValue


class InProcessChannel:
    """``kind="channel.in_process"`` — append-only history for one process."""

    def __init__(
        self,
        *,
        channel_id: str,
        max_batch: int = MAX_INBOX_BATCH,
        now_fn: Callable[[], datetime] = utc_now,
    ) -> None:
        if max_batch <= 0:
            raise ValueError("channel max_batch must be positive")
        self._channel_id = channel_id
        self._max_batch = max_batch
        self._now = now_fn
        self._lock = Lock()
        # Append-only. A list index plus one IS the durable sequence, mirroring
        # the SQLite AUTOINCREMENT columns the mailbox transport uses.
        self._messages: list[ChannelMessage] = []
        self._acks: list[ChannelAck] = []
        self._by_id: dict[str, ChannelMessage] = {}
        self._seq_by_id: dict[str, int] = {}
        self._attestations: dict[str, str] = {}
        self._ack_by_key: dict[tuple[str, str], ChannelAck] = {}
        self._ack_commands: dict[str, tuple[str, str]] = {}
        # Which command wrote each reply, so an exact retry of that command
        # is told apart from a second command that lost the race. The
        # mailbox transport keeps the same fact in a durable column.
        self._reply_commands: dict[str, str] = {}

    @property
    def profile(self) -> ChannelProfile:
        return ChannelProfile(durability="process", max_batch=self._max_batch)

    def append_request(
        self,
        intent: ChannelSendIntent,
        attestation_id: str,
    ) -> ChannelMessage:
        if intent.channel_id != self._channel_id:
            raise ContractViolation(
                f"intent addresses channel {intent.channel_id!r}, not {self._channel_id!r}"
            )
        with self._lock:
            stored = self._by_id.get(str(intent.message_id))
            if stored is not None:
                # A reconstructed send reconciles against the stored observation
                # time rather than inventing a second one.
                expected = message_for_intent(intent, created_at=stored.envelope.created_at)
                if not same_message(stored, expected) or self._attestations.get(
                    str(intent.message_id)
                ) != attestation_id:
                    raise JournalDamaged(
                        f"channel message {intent.message_id} already stored with "
                        "a different logical intent"
                    )
                return stored
            message = message_for_intent(intent, created_at=self._now())
            self._append(message)
            self._attestations[str(message.message_id)] = attestation_id
            return message

    def message(self, message_id: Digest) -> ChannelMessage | None:
        with self._lock:
            return self._by_id.get(str(message_id))

    def reply_for(self, request_id: Digest) -> ChannelMessage | None:
        with self._lock:
            stored = next(
                (
                    message
                    for message in self._messages
                    if message.kind == "reply" and message.reply_to == request_id
                ),
                None,
            )
            if stored is None:
                return None
            request = self._by_id.get(str(request_id))
            if request is None:
                raise JournalDamaged(f"reply names request {request_id}, which is not stored")
            return validated_reply(request, stored)

    def reply(
        self,
        *,
        request_id: Digest,
        actor_id: str,
        payload: JsonValue,
        command_id: str,
    ) -> ChannelMessage:
        with self._lock:
            request = self._by_id.get(str(request_id))
            if request is None or request.kind != "request" or request.reply_port is None:
                raise ContractViolation(f"no channel request {request_id} to reply to")
            reply_id = reply_message_id(
                request_id=request.message_id,
                reply_port=request.reply_port,
            )
            stored = self._by_id.get(str(reply_id))
            if stored is not None:
                if self._reply_commands.get(str(reply_id)) != command_id:
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
                    raise ChannelReplyConflict(
                        f"request {request_id} already carries a different reply"
                    )
                self._imply_acknowledgement(request.message_id, actor_id, command_id)
                return stored
            # A reply atomically acknowledges its request for that actor, so the
            # acknowledgement must be admissible before anything is appended.
            self._ack_key(request.message_id, actor_id, command_id)
            reply = message_for_reply(
                request,
                actor_id=actor_id,
                payload=payload,
                created_at=self._now(),
            )
            self._append(reply)
            self._reply_commands[str(reply.message_id)] = command_id
            self._imply_acknowledgement(request.message_id, actor_id, command_id)
            return reply

    def acknowledge(
        self,
        *,
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> ChannelAck:
        with self._lock:
            return self._claim_acknowledgement(message_id, actor_id, command_id)

    def latest_revision(self, actor_id: str) -> ChannelRevision:
        del actor_id  # the cut is over retained history, not over one actor
        with self._lock:
            return ChannelRevision(
                message_seq=len(self._messages),
                ack_seq=len(self._acks),
            )

    def inbox(
        self,
        *,
        actor_id: str,
        revision: ChannelRevision,
        after: tuple[int, str] | None,
        limit: int,
    ) -> tuple[ChannelDelivery, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if limit > self._max_batch:
            raise ValueError(f"limit exceeds channel max_batch {self._max_batch}")
        with self._lock:
            if revision.message_seq > len(self._messages) or revision.ack_seq > len(self._acks):
                raise InvalidChannelRevision(
                    f"channel revision {revision.model_dump()} is ahead of retained history"
                )
            # An acknowledgement cannot exist in a snapshot that omits the message
            # it acknowledges, so bounds alone do not make a cut real.
            if any(
                self._seq_by_id[str(ack.message_id)] > revision.message_seq
                for ack in self._acks[: revision.ack_seq]
            ):
                raise InvalidChannelRevision(
                    f"channel revision {revision.model_dump()} acknowledges a message "
                    "it does not include"
                )
            acknowledged = {
                (str(ack.message_id), ack.actor_id)
                for ack in self._acks[: revision.ack_seq]
            }
            page: list[ChannelDelivery] = []
            for seq, message in enumerate(self._messages[: revision.message_seq], start=1):
                if not discoverable_by(message, actor_id):
                    continue
                if after is not None and (seq, str(message.message_id)) <= after:
                    continue
                page.append(
                    ChannelDelivery(
                        message_seq=seq,
                        message=message,
                        acknowledged=(str(message.message_id), actor_id) in acknowledged,
                    )
                )
                if len(page) == limit:
                    break
            return tuple(page)

    def _append(self, message: ChannelMessage) -> None:
        self._messages.append(message)
        self._by_id[str(message.message_id)] = message
        self._seq_by_id[str(message.message_id)] = len(self._messages)

    def _ack_key(
        self,
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> tuple[str, str]:
        """Validate an acknowledgement without recording it."""

        if str(message_id) not in self._by_id:
            raise ContractViolation(f"no channel message {message_id} to acknowledge")
        key = (str(message_id), actor_id)
        owner = self._ack_commands.get(command_id)
        if owner is not None and owner != key:
            raise JournalDamaged(
                f"command {command_id!r} already acknowledged a different message"
            )
        return key

    def _claim_acknowledgement(
        self,
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> ChannelAck:
        """One delivery fact, claimed by one command; a second command conflicts."""

        key = self._ack_key(message_id, actor_id, command_id)
        stored = self._ack_by_key.get(key)
        if stored is not None:
            if self._ack_commands.get(command_id) != key:
                raise ChannelAckConflict(
                    f"message {message_id} is already acknowledged for {actor_id!r} "
                    f"by another command; {command_id!r} may not claim it"
                )
            return stored
        return self._insert_ack(key, message_id, actor_id, command_id)

    def _imply_acknowledgement(
        self,
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> ChannelAck:
        """The request is acknowledged for this actor, whoever first recorded it.

        A reply does not *claim* a delivery fact, it implies one: an actor that
        answers a request plainly received it. Demanding that the reply's own
        command own that row would mean an actor who acknowledged a request
        before answering it could never answer it.
        """

        key = self._ack_key(message_id, actor_id, command_id)
        stored = self._ack_by_key.get(key)
        if stored is not None:
            return stored
        return self._insert_ack(key, message_id, actor_id, command_id)

    def _insert_ack(
        self,
        key: tuple[str, str],
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> ChannelAck:
        ack = ChannelAck(message_id=message_id, actor_id=actor_id, acked_at=self._now())
        self._acks.append(ack)
        self._ack_by_key[key] = ack
        self._ack_commands[command_id] = key
        return ack
