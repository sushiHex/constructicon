"""Typed message channels (M7, channel schema 1).

A channel carries one exact request from a sealed invocation to a participant on
another rhythm, and exactly one authenticated reply back. Both halves are
immutable facts; nothing here deletes, dequeues, or forgets.

Identity is derived, never authored. A request's id comes from its invocation
plus its sealed binding, so a reconstructed send after process death recomputes
the same id rather than inventing a second message. A reply's id comes from the
request it answers, so a parked component can compute the id it waits on without
consulting a live channel.

Delivery is honestly at-least-once. An acknowledgement is a delivery fact about
one actor; it never proves a component consumed the payload (I4) and never
removes history from runtime recovery.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)

from constructicon.core.address import ExecutionPath, RunId, invocation_id
from constructicon.core.envelope import Envelope
from constructicon.core.errors import ConstructiconError, ContractViolation
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest

CHANNEL_SCHEMA_VERSION = 1


class InvalidChannelRevision(ValueError):
    """A structurally valid requested channel cut is future or incoherent."""


class ChannelReplyConflict(ConstructiconError):
    """A request already carries a different reply — a lost race, not damage."""


class ChannelAckConflict(ConstructiconError):
    """This delivery fact belongs to another command — a duplicate, not damage."""

ChannelInteraction = Literal["advice", "approval"]
ChannelMessageKind = Literal["request", "reply"]
ChannelDurability = Literal["process", "sqlite_wal"]

MAX_INBOX_BATCH = 100


class _ChannelModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class _ManifestModel(BaseModel):
    """A channel fact that lives inside the manifest.

    Deliberately not ``strict``: ``parse_manifest_json`` validates a persisted
    manifest in Python mode, where a ``Digest`` arrives as a plain string. The
    manifest's own contracts are frozen and closed, and these match them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class ChannelEndpoint(_ManifestModel):
    """Where an admitted channel binding sends, and under whose authority.

    Routing is process assembly's to decide (I1) and execution's to consume as
    a sealed fact (I13), so it is compiled into the manifest rather than read
    off a live object. Two hosts that assemble the same manifest with different
    routing therefore produce different manifest identities and are caught,
    instead of silently deriving a second message under a changed lane.
    """

    lane: str
    interaction: ChannelInteraction
    recipient_actor_id: str | None


class ChannelBinding(_ManifestModel):
    """One admitted channel exchange: where it sends and exactly what crosses.

    Admission compiles this from assembly's endpoint plus the component's one
    declared input and output, so no part of the message is chosen at call
    time. Pinned source is not pinned behavior — a component that could name
    its own port on replay could derive a second request id and append a
    second message, which no equality fence would catch.
    """

    endpoint: ChannelEndpoint
    port: str
    contract: ChannelContract
    reply_port: str
    reply_contract: ChannelContract


class ChannelContract(_ManifestModel):
    """Nominal type identity of one message payload (I5).

    Exactly the repo's nominal identity pair, so a contract can be read
    straight off a declared ``Port``: ``schema_hash`` is a schema revision
    string, not a content digest.
    """

    type_id: str
    schema_hash: str


class ChannelSendIntent(_ChannelModel):
    """A timestamp-free request: everything the identity law needs, and no more.

    Wall-clock time is deliberately absent. The trusted transport stamps
    ``Envelope.created_at`` once, when it first appends the message, so a
    reconstructed send reconciles against the stored observation instead of
    inventing a new time.
    """

    schema_version: Literal[1] = 1
    message_id: Digest
    channel_id: str
    channel_revision: str
    lane: str
    interaction: ChannelInteraction
    recipient_actor_id: str | None
    contract: ChannelContract
    reply_contract: ChannelContract
    run_id: RunId
    path: ExecutionPath
    port: str
    reply_port: str
    payload: JsonValue

    @model_validator(mode="after")
    def _identity_is_derived(self) -> ChannelSendIntent:
        expected = request_message_id(
            run_id=self.run_id,
            path=self.path,
            channel_id=self.channel_id,
            channel_revision=self.channel_revision,
            lane=self.lane,
            interaction=self.interaction,
            port=self.port,
        )
        if self.message_id != expected:
            raise ValueError("channel send intent carries a non-derived message id")
        return self


class ChannelMessage(_ChannelModel):
    """One immutable request or reply.

    ``contract`` and ``port`` always type this message's own envelope. A request
    additionally pins the exchange's other half in ``reply_contract`` and
    ``reply_port``, so a reply's admissible type is a sealed value on the request
    rather than something inferred from a lane or live configuration.
    """

    schema_version: Literal[1] = 1
    message_id: Digest
    channel_id: str
    lane: str
    interaction: ChannelInteraction
    kind: ChannelMessageKind
    reply_to: Digest | None
    recipient_actor_id: str | None
    sender_actor_id: str | None
    contract: ChannelContract
    reply_contract: ChannelContract | None
    reply_port: str | None
    envelope: Envelope[JsonValue]

    @model_validator(mode="after")
    def _one_of_two_legal_shapes(self) -> ChannelMessage:
        if self.kind == "request":
            if self.reply_to is not None or self.sender_actor_id is not None:
                raise ValueError("a channel request has no reply_to and no sender actor")
            if self.reply_contract is None or self.reply_port is None:
                raise ValueError("a channel request must pin its reply contract and port")
            return self
        if self.reply_to is None or self.sender_actor_id is None:
            raise ValueError("a channel reply names one request and its authenticated sender")
        if self.reply_contract is not None or self.reply_port is not None:
            raise ValueError("a channel reply does not pin a further reply")
        return self


class ChannelRevision(_ChannelModel):
    """One vector cut over retained history: no page can shift beneath a reader."""

    message_seq: NonNegativeInt
    ack_seq: NonNegativeInt


class ChannelDelivery(_ChannelModel):
    """One retained message as one actor sees it, plus its continuation key.

    ``message_seq`` is durable position, not position within this page: an
    actor's messages are sparse in a shared history, so a caller that counted
    rows instead would redeliver. It is the only value ``inbox(after=...)``
    accepts, so the page that produced it must hand it back.
    """

    message_seq: NonNegativeInt
    message: ChannelMessage
    acknowledged: bool


class ChannelAck(_ChannelModel):
    """A delivery fact about one actor — never proof of component consumption."""

    message_id: Digest
    actor_id: str
    acked_at: AwareDatetime


class ChannelProfile(_ChannelModel):
    """What a transport honestly guarantees; published through ``describe()``."""

    durability: ChannelDurability
    delivery: Literal["at_least_once"] = "at_least_once"
    history: Literal["retained"] = "retained"
    max_batch: PositiveInt


def request_message_id(
    *,
    run_id: RunId,
    path: ExecutionPath,
    channel_id: str,
    channel_revision: str,
    lane: str,
    interaction: ChannelInteraction,
    port: str,
) -> Digest:
    """Derive one request identity from its invocation and its sealed binding.

    One invocation may therefore send at most one request per bound channel,
    lane, and port. More messages require explicit ports or more invocations and
    loop frames; there is no unstable ordinal or caller-authored token.
    """

    return digest(
        "channel-message",
        1,
        {
            "invocation_id": str(invocation_id(run_id, path)),
            "channel_id": channel_id,
            "channel_revision": channel_revision,
            "lane": lane,
            "interaction": interaction,
            "port": port,
            "kind": "request",
        },
    )


def reply_message_id(*, request_id: Digest, reply_port: str) -> Digest:
    """Derive the reply identity from the request that pinned it."""

    return digest(
        "channel-reply",
        1,
        {"request_id": str(request_id), "port": reply_port},
    )


def same_message(left: ChannelMessage, right: ChannelMessage) -> bool:
    """Compare canonical bytes, never Python equality.

    ``BaseModel.__eq__`` compares payloads with Python semantics, where
    ``1 == True`` and ``1 == 1.0``. Those are distinct canonical JSON facts, so
    model equality would accept a genuinely different intent as an idempotent
    retry and hand back the wrong stored payload. Identity is a bytes law.
    """

    return canonical_json(left.model_dump(mode="json")) == canonical_json(
        right.model_dump(mode="json")
    )


def message_for_intent(
    intent: ChannelSendIntent,
    *,
    created_at: datetime,
) -> ChannelMessage:
    """The one request message an intent becomes.

    Transports differ in how they store a message, never in what a message is,
    so both derive it here. ``created_at`` is the transport's single stamp: a
    reconstructed send passes the stored observation time back in and gets the
    original fact, rather than inventing a second one.
    """

    derived = request_message_id(
        run_id=intent.run_id,
        path=intent.path,
        channel_id=intent.channel_id,
        channel_revision=intent.channel_revision,
        lane=intent.lane,
        interaction=intent.interaction,
        port=intent.port,
    )
    if derived != intent.message_id:
        # `model_copy(update=...)` and `model_construct` skip validators, so an
        # intent can reach a transport carrying a stale id for changed routing.
        raise ContractViolation(
            f"channel send intent carries id {intent.message_id}, "
            f"but its own fields derive {derived}"
        )
    return ChannelMessage(
        message_id=intent.message_id,
        channel_id=intent.channel_id,
        lane=intent.lane,
        interaction=intent.interaction,
        kind="request",
        reply_to=None,
        recipient_actor_id=intent.recipient_actor_id,
        sender_actor_id=None,
        contract=intent.contract,
        reply_contract=intent.reply_contract,
        reply_port=intent.reply_port,
        envelope=Envelope(
            run_id=intent.run_id,
            path=intent.path,
            port=intent.port,
            created_at=created_at,
            payload=intent.payload,
        ),
    )


def message_for_reply(
    request: ChannelMessage,
    *,
    actor_id: str,
    payload: JsonValue,
    created_at: datetime,
) -> ChannelMessage:
    """The one reply message a request admits, typed by what the request pinned.

    Only the sealed recipient may answer an addressed request. One reply per
    request is a hard constraint, so an unchecked actor who learned a request
    id could answer first and lock the intended recipient out permanently.
    """

    if request.kind != "request":
        raise ContractViolation("only a channel request can be replied to")
    if request.reply_contract is None or request.reply_port is None:
        raise ContractViolation("channel request does not pin a reply contract and port")
    if request.recipient_actor_id is not None and actor_id != request.recipient_actor_id:
        raise ContractViolation(
            f"channel request {request.message_id} is addressed to "
            f"{request.recipient_actor_id!r}; actor {actor_id!r} may not answer it"
        )
    return ChannelMessage(
        message_id=reply_message_id(
            request_id=request.message_id,
            reply_port=request.reply_port,
        ),
        channel_id=request.channel_id,
        lane=request.lane,
        interaction=request.interaction,
        kind="reply",
        reply_to=request.message_id,
        recipient_actor_id=None,
        sender_actor_id=actor_id,
        contract=request.reply_contract,
        reply_contract=None,
        reply_port=None,
        envelope=Envelope(
            run_id=request.envelope.run_id,
            path=request.envelope.path,
            port=request.reply_port,
            created_at=created_at,
            payload=payload,
        ),
    )


class Channel(Protocol):
    """One transport contract, defined by observable behavior rather than SQLite.

    Only a transport may construct a durable message: it accepts the
    timestamp-free intent and stamps the observation time once.
    """

    @property
    def profile(self) -> ChannelProfile: ...

    def append_request(
        self,
        intent: ChannelSendIntent,
        attestation_id: str,
    ) -> ChannelMessage:
        """Append one request, or return the exact stored fact for a retry."""
        ...

    def message(self, message_id: Digest) -> ChannelMessage | None: ...

    def reply_for(self, request_id: Digest) -> ChannelMessage | None: ...

    def reply(
        self,
        *,
        request_id: Digest,
        actor_id: str,
        payload: JsonValue,
        command_id: str,
    ) -> ChannelMessage:
        """Append the one authenticated reply and acknowledge its request."""
        ...

    def acknowledge(
        self,
        *,
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> ChannelAck: ...

    def latest_revision(self, actor_id: str) -> ChannelRevision: ...

    def inbox(
        self,
        *,
        actor_id: str,
        revision: ChannelRevision,
        after: tuple[int, str] | None,
        limit: int,
    ) -> tuple[ChannelDelivery, ...]:
        """One bounded page of this actor's retained messages at one cut."""
        ...
