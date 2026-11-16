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
    REPLY_CONSUMES,
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
from constructicon.core.human import (
    ChannelReplyProof,
    canonical_exchange_fault,
    channel_reply_proof,
    validated_channel_reply_proof,
)
from constructicon.core.identity import Digest, JsonValue


class InProcessChannel:
    """``kind="channel.in_process"`` — append-only history for one process.

    The live effect adapter authenticates a send before either transport sees
    it. This process-local profile retains the attestation identity plus an
    independent, timestamp-free intent snapshot, enough to detect mutation of
    its retained request without pretending to own durable attestation state.
    The mailbox profile additionally revalidates that durable attestation on
    every read because either SQLite row can be damaged while the process is
    absent.
    """

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
        self._request_intent_by_message: dict[str, ChannelSendIntent] = {}
        self._ack_by_key: dict[tuple[str, str], ChannelAck] = {}
        self._ack_commands: dict[str, tuple[str, str]] = {}
        # Which command wrote each reply, so an exact retry of that command
        # is told apart from a second command that lost the race. The
        # mailbox transport keeps the same fact in a durable column.
        self._reply_command_by_message: dict[str, str] = {}
        self._reply_message_by_command: dict[str, str] = {}
        self._reply_proof_by_message: dict[str, ChannelReplyProof] = {}

    @property
    def channel_id(self) -> str:
        return self._channel_id

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
            self._validate_history()
            stored = self._by_id.get(str(intent.message_id))
            if stored is not None:
                stored = self._complete_request(stored)
                # A reconstructed send reconciles against the stored observation
                # time rather than inventing a second one.
                expected = message_for_intent(intent, created_at=stored.envelope.created_at)
                if (
                    not same_message(stored, expected)
                    or self._attestations.get(str(intent.message_id)) != attestation_id
                ):
                    raise JournalDamaged(
                        f"channel message {intent.message_id} already stored with "
                        "a different logical intent"
                    )
                return _detached_message(stored)
            proof = intent.model_copy(deep=True)
            message = message_for_intent(proof, created_at=self._now())
            self._append(message)
            self._attestations[str(message.message_id)] = attestation_id
            self._request_intent_by_message[str(message.message_id)] = proof
            return _detached_message(message)

    def message(self, message_id: Digest) -> ChannelMessage | None:
        with self._lock:
            self._validate_history()
            stored = self._by_id.get(str(message_id))
            return (
                _detached_message(self._complete_message(stored))
                if stored is not None
                else None
            )

    def reply_for(self, request_id: Digest) -> ChannelMessage | None:
        with self._lock:
            self._validate_history()
            request = self._by_id.get(str(request_id))
            if request is None:
                return None
            request = self._complete_request(request)
            if request.reply_port is None:
                raise JournalDamaged(f"channel request {request_id} pins no reply port")
            reply_id = reply_message_id(
                request_id=request.message_id,
                reply_port=request.reply_port,
            )
            stored = self._by_id.get(str(reply_id))
            if stored is None:
                return None
            return _detached_message(self._complete_reply(request, stored))

    def reply(
        self,
        *,
        request_id: Digest,
        actor_id: str,
        payload: JsonValue,
        command_id: str,
    ) -> ChannelMessage:
        with self._lock:
            self._validate_history()
            request = self._by_id.get(str(request_id))
            if request is not None:
                request = self._complete_request(request)
            if (
                request is None
                or request.kind != "request"
                or request.reply_port is None
                or request.reply_contract is None
            ):
                raise ContractViolation(f"no channel request {request_id} to reply to")
            if request.interaction not in REPLY_CONSUMES:
                raise ContractViolation(
                    "an approval request can only be answered by the request-bound "
                    "approval operation"
                )
            incoherence = canonical_exchange_fault(
                request.contract,
                request.reply_contract,
                request.interaction,
            )
            if incoherence is not None:
                raise ContractViolation(
                    f"channel request {request_id} carries an incoherent exchange: {incoherence}"
                )
            reply_id = reply_message_id(
                request_id=request.message_id,
                reply_port=request.reply_port,
            )
            owned_reply = self._reply_message_by_command.get(command_id)
            if owned_reply is not None and owned_reply != str(reply_id):
                raise JournalDamaged(
                    f"command {command_id!r} already replied to a different request"
                )
            stored = self._by_id.get(str(reply_id))
            if stored is not None:
                complete = self._complete_reply(request, stored)
                if self._reply_command_by_message.get(str(reply_id)) != command_id:
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
                return _detached_message(complete)
            ack_key = (str(request.message_id), actor_id)
            if ack_key in self._ack_by_key and self._ack_commands.get(command_id) == ack_key:
                raise JournalDamaged(
                    f"command {command_id!r} owns a request acknowledgement without its reply"
                )
            # A reply atomically acknowledges its request for that actor, so the
            # acknowledgement and reply are both constructed before either is
            # appended. One observation time makes a clock failure an all-or-none
            # failure just as SQLite's transaction does.
            key = self._ack_key(request.message_id, actor_id, command_id)
            observed_at = self._now()
            reply = message_for_reply(
                request,
                actor_id=actor_id,
                payload=payload,
                created_at=observed_at,
            )
            proof = channel_reply_proof(request, reply)
            implied_ack = (
                None
                if key in self._ack_by_key
                else ChannelAck(
                    message_id=request.message_id,
                    actor_id=actor_id,
                    acked_at=observed_at,
                )
            )
            self._append(reply)
            self._reply_command_by_message[str(reply.message_id)] = command_id
            self._reply_message_by_command[command_id] = str(reply.message_id)
            self._reply_proof_by_message[str(reply.message_id)] = proof
            if implied_ack is not None:
                self._append_ack(key, implied_ack, command_id)
            return _detached_message(reply)

    def acknowledge(
        self,
        *,
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> ChannelAck:
        with self._lock:
            self._validate_history()
            request = self._by_id.get(str(message_id))
            if request is not None and request.kind == "request":
                request = self._complete_request(request)
                if request.reply_port is None:
                    raise JournalDamaged(
                        f"channel request {message_id} pins no reply port"
                    )
                reply_id = reply_message_id(
                    request_id=request.message_id,
                    reply_port=request.reply_port,
                )
                reply = self._by_id.get(str(reply_id))
                if reply is not None:
                    # Never let an explicit delivery observation heal the
                    # atomic acknowledgement missing from a torn reply.
                    self._complete_reply(request, reply)
            return self._claim_acknowledgement(message_id, actor_id, command_id)

    def latest_revision(self, actor_id: str) -> ChannelRevision:
        del actor_id  # the cut is over retained history, not over one actor
        with self._lock:
            self._validate_history()
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
            self._validate_history()
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
                (str(ack.message_id), ack.actor_id) for ack in self._acks[: revision.ack_seq]
            }
            page: list[ChannelDelivery] = []
            for seq, message in enumerate(self._messages[: revision.message_seq], start=1):
                message = self._complete_message(message)
                if not discoverable_by(message, actor_id):
                    continue
                if after is not None and (seq, str(message.message_id)) <= after:
                    continue
                page.append(
                    ChannelDelivery(
                        message_seq=seq,
                        message=_detached_message(message),
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

    def _validate_history(self) -> None:
        """Prove every retained index and first-write proof is append-only."""

        message_ids = [str(message.message_id) for message in self._messages]
        if (
            len(message_ids) != len(set(message_ids))
            or set(message_ids) != set(self._by_id)
            or set(message_ids) != set(self._seq_by_id)
        ):
            raise JournalDamaged("in-process channel message history is damaged")
        for sequence, message in enumerate(self._messages, start=1):
            message_id = str(message.message_id)
            if self._by_id.get(message_id) is not message or self._seq_by_id.get(
                message_id
            ) != sequence:
                raise JournalDamaged("in-process channel message history is damaged")

        request_ids = {
            str(message.message_id) for message in self._messages if message.kind == "request"
        }
        reply_ids = set(message_ids) - request_ids
        if request_ids != set(self._attestations) or request_ids != set(
            self._request_intent_by_message
        ):
            raise JournalDamaged("in-process channel request history is damaged")
        if (
            reply_ids != set(self._reply_command_by_message)
            or reply_ids != set(self._reply_proof_by_message)
            or reply_ids != set(self._reply_message_by_command.values())
            or len(self._reply_message_by_command) != len(reply_ids)
        ):
            raise JournalDamaged("in-process channel reply history is damaged")
        for reply_id, command_id in self._reply_command_by_message.items():
            if self._reply_message_by_command.get(command_id) != reply_id:
                raise JournalDamaged("in-process channel reply history is damaged")

        acknowledgement_keys = [
            (str(ack.message_id), ack.actor_id) for ack in self._acks
        ]
        if (
            len(acknowledgement_keys) != len(set(acknowledgement_keys))
            or set(acknowledgement_keys) != set(self._ack_by_key)
            or set(acknowledgement_keys) != set(self._ack_commands.values())
            or len(self._ack_commands) != len(acknowledgement_keys)
        ):
            raise JournalDamaged("in-process channel acknowledgement history is damaged")
        for key, ack in zip(acknowledgement_keys, self._acks, strict=True):
            if self._ack_by_key.get(key) is not ack or key[0] not in self._by_id:
                raise JournalDamaged(
                    "in-process channel acknowledgement history is damaged"
                )

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
        reply_id = self._reply_message_by_command.get(command_id)
        if reply_id is not None:
            reply = self._by_id.get(reply_id)
            if reply is None or reply.reply_to is None or reply.sender_actor_id is None:
                raise JournalDamaged(f"command {command_id!r} owns an invalid channel reply")
            if (str(reply.reply_to), reply.sender_actor_id) != key:
                raise JournalDamaged(
                    f"command {command_id!r} already replied to a different request"
                )
        owner = self._ack_commands.get(command_id)
        if owner is not None and owner != key:
            raise JournalDamaged(f"command {command_id!r} already acknowledged a different message")
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

    def _insert_ack(
        self,
        key: tuple[str, str],
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> ChannelAck:
        ack = ChannelAck(message_id=message_id, actor_id=actor_id, acked_at=self._now())
        self._append_ack(key, ack, command_id)
        return ack

    def _append_ack(
        self,
        key: tuple[str, str],
        ack: ChannelAck,
        command_id: str,
    ) -> None:
        self._acks.append(ack)
        self._ack_by_key[key] = ack
        self._ack_commands[command_id] = key

    def _complete_reply(
        self,
        request: ChannelMessage,
        reply: ChannelMessage,
    ) -> ChannelMessage:
        """Return one reply only when its atomic acknowledgement is present."""

        request = self._complete_request(request)
        validated = validated_reply(request, reply)
        sender = validated.sender_actor_id
        if sender is None or (str(request.message_id), sender) not in self._ack_by_key:
            raise JournalDamaged(
                f"channel reply {validated.message_id} exists without its request acknowledgement"
            )
        proof = self._reply_proof_by_message.get(str(validated.message_id))
        if proof is None:
            raise JournalDamaged(
                f"channel reply {validated.message_id} has no independent payload proof"
            )
        validated_channel_reply_proof(proof, request, validated)
        return validated

    def _complete_request(self, request: ChannelMessage) -> ChannelMessage:
        """Project one request only beside its independent intent snapshot."""

        if request.kind != "request":
            raise JournalDamaged(f"channel message {request.message_id} is not a request")
        proof = self._request_intent_by_message.get(str(request.message_id))
        if proof is None:
            raise JournalDamaged(
                f"channel request {request.message_id} has no independent intent proof"
            )
        expected = message_for_intent(proof, created_at=request.envelope.created_at)
        if not same_message(request, expected):
            raise JournalDamaged(
                f"channel request {request.message_id} contradicts its independent intent proof"
            )
        return request

    def _complete_message(self, message: ChannelMessage) -> ChannelMessage:
        """Project one complete request or reply through its independent proof."""

        if message.kind == "request":
            return self._complete_request(message)
        if message.reply_to is None:
            raise JournalDamaged(f"channel reply {message.message_id} names no request")
        request = self._by_id.get(str(message.reply_to))
        if request is None:
            raise JournalDamaged(
                f"reply {message.message_id} names request {message.reply_to}, which is not stored"
            )
        return self._complete_reply(request, message)


def _detached_message(message: ChannelMessage) -> ChannelMessage:
    """Return a caller-owned snapshot, never the retained mutable JSON tree."""

    return message.model_copy(deep=True)
