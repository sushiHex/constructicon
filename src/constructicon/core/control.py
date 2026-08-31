"""Durable control-plane contracts (M6).

MCP is only the first transport. These contracts remain when the transport is
removed: authenticated actors, one durable command identity for every
mutation, long-lived runs, stable pages, and immutable detail references.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    SerializerFunctionWrapHandler,
    field_serializer,
    field_validator,
    model_serializer,
)

from constructicon.core.address import RunId, ScopePath
from constructicon.core.channel import ChannelInteraction, ChannelMessage
from constructicon.core.identity import Digest, JsonValue, digest
from constructicon.core.run import Liveness, RunStatus

if TYPE_CHECKING:
    from constructicon.core.effect import ApprovalRecord

CONTROL_SCHEMA_VERSION = 3
IDEMPOTENCY_KEY_MAX_LENGTH = 200

READ_SCOPE = "constructicon:read"
OPERATE_SCOPE = "constructicon:operate"
ADVISE_SCOPE = "constructicon:advise"
APPROVE_SCOPE = "constructicon:approve"
PROMOTE_SCOPE = "constructicon:promote"
ADMIN_SCOPE = "constructicon:admin"
CONTROL_SCOPES = frozenset(
    {
        READ_SCOPE,
        OPERATE_SCOPE,
        ADVISE_SCOPE,
        APPROVE_SCOPE,
        PROMOTE_SCOPE,
        ADMIN_SCOPE,
    }
)
# Advising is not approving. Which one a message needs is sealed on the request
# as its interaction, never chosen by whoever answers it. Typed by the
# interaction rather than by `str`, so the mapping is total by construction and
# a new interaction cannot reach a surface without naming its scope.
INTERACTION_SCOPES: dict[ChannelInteraction, str] = {
    "advice": ADVISE_SCOPE,
    "approval": APPROVE_SCOPE,
}


class ControlCode(StrEnum):
    AUTH_LOCAL_STATIC_REQUIRED = "control.auth.local_static_required"
    AUTH_REQUIRED_SCOPE = "control.auth.required_scope"
    IDEMPOTENCY_CONFLICT = "control.idempotency.conflict"
    COMMAND_IN_PROGRESS = "control.command.in_progress"
    COMMAND_UNKNOWN = "control.command.unknown"
    CURSOR_INVALID = "control.cursor.invalid"
    CURSOR_QUERY_MISMATCH = "control.cursor.query_mismatch"
    DETAIL_NOT_FOUND = "control.detail.not_found"
    DETAIL_NOT_IMMUTABLE = "control.detail.not_immutable"
    DETAIL_DIGEST_MISMATCH = "control.detail.digest_mismatch"
    RUN_UNKNOWN = "control.run.unknown"
    RUN_LIVE_OWNER = "control.run.live_owner"
    RUN_TERMINAL = "control.run.terminal"
    RUN_NOT_RESUMABLE = "control.run.not_resumable"
    COUNTERFACTUAL_LOCK_MISMATCH = "control.counterfactual.lock_mismatch"
    REGISTRY_STABLE_MOVED = "control.registry.stable_moved"
    REGISTRY_VERSION_UNKNOWN = "control.registry.version_unknown"
    APPROVAL_INVALID_SUBJECT = "control.approval.invalid_subject"
    APPROVAL_RUN_MISMATCH = "control.approval.run_mismatch"
    CHANNEL_MESSAGE_UNKNOWN = "control.channel.message_unknown"
    CHANNEL_REQUEST_REQUIRED = "control.channel.request_required"
    CHANNEL_WRONG_INTERACTION = "control.channel.wrong_interaction"
    CHANNEL_ALREADY_REPLIED = "control.channel.already_replied"
    REQUEST_INVALID = "control.request.invalid"
    COUNTERFACTUAL_OVERRIDE_INVALID = "control.counterfactual.override_invalid"


class AuthenticatedActor(BaseModel):
    """A transport-minted principal. Tool arguments can never construct one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_id: str
    auth_method: Literal["static", "oauth"]
    scopes: frozenset[str]
    display_name: str | None = None
    issuer: str | None = None
    subject: str | None = None
    client_id: str | None = None

    @field_validator("actor_id")
    @classmethod
    def _actor_id_is_canonical(cls, value: str) -> str:
        if not value or value.strip() != value or any(ch.isspace() for ch in value):
            raise ValueError("actor_id must be a non-empty canonical token")
        if ":" not in value:
            raise ValueError("actor_id must be namespaced, for example 'static:local'")
        return value

    @field_validator("scopes")
    @classmethod
    def _scopes_are_known(cls, value: frozenset[str]) -> frozenset[str]:
        unknown = sorted(set(value) - CONTROL_SCOPES)
        if unknown:
            raise ValueError(f"unknown Constructicon scopes: {unknown}")
        return value

    @field_serializer("scopes")
    def _serialize_scopes(self, value: frozenset[str]) -> list[str]:
        """Keep actor-bearing durable records and detail digests process-stable."""

        return sorted(value)

    def allows(self, scope: str) -> bool:
        return ADMIN_SCOPE in self.scopes or scope in self.scopes


class ActorSource(Protocol):
    """Transport-owned actor derivation; callers never author principals."""

    async def actor(self) -> AuthenticatedActor: ...


class ResolutionPin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ScopePath
    component: str
    version: Digest


class ResolutionLock(BaseModel):
    """One exact source-world lock for contract-compatible counterfactuals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_manifest_hash: Digest
    pins: tuple[ResolutionPin, ...]

    @field_validator("pins")
    @classmethod
    def _unique_scopes(cls, value: tuple[ResolutionPin, ...]) -> tuple[ResolutionPin, ...]:
        ordered = tuple(sorted(value, key=lambda pin: pin.scope.segments))
        scopes = [pin.scope.segments for pin in ordered]
        if len(scopes) != len(set(scopes)):
            raise ValueError("resolution lock contains duplicate scopes")
        return ordered


class ControlFault(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ControlCode
    message: str
    repair: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ControlRejected(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[3] = 3
    status: Literal["rejected"] = "rejected"
    faults: tuple[ControlFault, ...]

    @classmethod
    def one_fault(
        cls,
        code: ControlCode,
        message: str,
        repair: str,
        details: dict[str, JsonValue] | None = None,
    ) -> Self:
        """Construct the common exact-one-fault control refusal."""

        return cls(
            faults=(
                ControlFault(
                    code=code,
                    message=message,
                    repair=repair,
                    details=details or {},
                ),
            )
        )


class DetailRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    uri: str
    media_type: Literal["application/json"] = "application/json"
    digest: Digest


class DetailChunk(BaseModel):
    """One exact slice of canonical detail bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    uri: str
    media_type: Literal["application/json"]
    digest: Digest
    text: str
    offset: NonNegativeInt
    total_bytes: NonNegativeInt
    next_cursor: str | None = None


class PageInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    next_cursor: str | None
    snapshot_digest: Digest
    count: NonNegativeInt


class CommandClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str
    actor_id: str
    operation: str
    owner_id: str
    epoch: PositiveInt
    expires_at: AwareDatetime


class CommandRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str
    actor: AuthenticatedActor
    operation: str
    idempotency_key: str
    request_hash: Digest
    request: JsonValue
    state: Literal["prepared", "committed", "rejected"]
    plan: JsonValue | None
    response: JsonValue | None
    owner_id: str | None
    owner_epoch: NonNegativeInt
    lease_expires_at: AwareDatetime | None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None


def command_visible_to(record: CommandRecord, actor: AuthenticatedActor) -> bool:
    """One command visibility law shared by status, detail, and transport resources."""

    return record.actor.actor_id == actor.actor_id or actor.allows(ADMIN_SCOPE)


def scope_refusal(
    actor: AuthenticatedActor,
    required: str | frozenset[str],
) -> ControlRejected | None:
    """One scope door for every surface: an exact scope, or any one of several.

    A set is not a weaker door. It is the honest one when the exact scope is
    sealed on the target rather than chosen by the call — acknowledging an
    approval needs approve and acknowledging advice needs advise, and which
    applies is the request's to say. The operation then re-derives the exact
    scope from that request; this only refuses an actor with no way in at all.
    """

    if isinstance(required, str):
        if actor.allows(required):
            return None
        return ControlRejected.one_fault(
            ControlCode.AUTH_REQUIRED_SCOPE,
            f"actor {actor.actor_id!r} lacks required scope {required!r}",
            f"authenticate with {required} or {ADMIN_SCOPE}",
            {"required_scope": required},
        )
    if any(actor.allows(scope) for scope in required):
        return None
    names = sorted(required)
    return ControlRejected.one_fault(
        ControlCode.AUTH_REQUIRED_SCOPE,
        f"actor {actor.actor_id!r} holds none of the required scopes {names}",
        f"authenticate with one of {', '.join(names)}, or {ADMIN_SCOPE}",
        {"required_scopes": names},
    )


def channel_reach(actor: AuthenticatedActor) -> frozenset[ChannelInteraction]:
    """The interactions this actor may act on — the whole of its channel reach.

    An advisor is its own role, not an observer with extra rights (I9), so this
    is derived from the interaction scopes alone. Holding ``constructicon:read``
    neither grants nor is granted by it.
    """

    return frozenset(
        interaction
        for interaction, scope in INTERACTION_SCOPES.items()
        if actor.allows(scope)
    )


def channel_authority_holder(request: ChannelMessage, actor: AuthenticatedActor) -> bool:
    """One channel authority law shared by inbox, message, detail, reply, and ack.

    ``request`` is always the *governing* request, never the message actually
    addressed: a reply carries no recipient of its own, so reading authority off
    it would let anyone act on an answer. Two sealed facts decide together — the
    interaction says which scope answers this kind of question, and the
    recipient says whose question it is. An unaddressed request admits any
    holder of the scope, exactly as ``message_for_reply`` already admits any
    sender when no recipient was sealed.

    One predicate, one refusal: a caller is never told which half failed, so a
    scopeless actor cannot use the surface to discover that it is the recipient.
    """

    if not actor.allows(INTERACTION_SCOPES[request.interaction]):
        return False
    return (
        request.recipient_actor_id is None
        or request.recipient_actor_id == actor.actor_id
        or actor.allows(ADMIN_SCOPE)
    )


class CommandClaimResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["claimed", "replayed", "in_progress", "conflict"]
    claim: CommandClaim | None = None
    record: CommandRecord | None = None


class CommandMeta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str
    replayed: bool


class RunOrigin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["start", "reproduce", "counterfactual"]
    actor_id: str
    command_id: str
    source_run_id: RunId | None = None
    overrides: dict[str, Digest] = Field(default_factory=dict)
    effects: Literal["live", "simulated"] = "live"
    capabilities: Literal["normal", "discard"] = "normal"


class RunRecord(BaseModel):
    """One durable run row plus read-time liveness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    manifest_hash: Digest
    input_hash: Digest
    status: RunStatus
    liveness: Liveness
    created_at: AwareDatetime
    owner_id: str | None = None
    lease_expires_at: AwareDatetime | None = None
    cancel_requested: bool = False
    origin: RunOrigin | None = None


class RunSubmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[3] = 3
    status: Literal["submitted"] = "submitted"
    run_id: RunId
    run_status: RunStatus
    command: CommandMeta
    origin: RunOrigin | None


class CancellationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[3] = 3
    status: Literal["cancel_requested", "already_terminal"]
    run_id: RunId
    run_status: RunStatus
    command: CommandMeta


class RunSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    status: RunStatus
    liveness: Liveness
    created_at: AwareDatetime
    manifest_hash: Digest
    input_hash: Digest
    origin: RunOrigin | None
    manifest_ref: DetailRef
    result_ref: DetailRef | None = None


class RunPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[RunSummary, ...]
    page: PageInfo


class EventSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    seq: NonNegativeInt
    kind: str
    path: str | None
    created_at: AwareDatetime
    payload: dict[str, JsonValue] | None
    detail: DetailRef


class EventPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    items: tuple[EventSummary, ...]
    through_seq: NonNegativeInt
    page: PageInfo


class RunResultPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    status: RunStatus
    outputs: dict[str, JsonValue] = Field(default_factory=dict)
    failures: dict[str, str] = Field(default_factory=dict)
    detail: DetailRef | None = None


class VersionSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    component: str
    version: Digest
    stable: bool
    registered_at: AwareDatetime
    detail: DetailRef


class ChannelMessageSummary(BaseModel):
    """One retained message as one actor sees it, payload by reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: Digest
    message_seq: NonNegativeInt
    channel_id: str
    lane: str
    interaction: Literal["advice", "approval"]
    kind: Literal["request", "reply"]
    reply_to: Digest | None
    run_id: RunId
    port: str
    type_id: str
    schema_hash: str
    created_at: AwareDatetime
    acknowledged: bool
    detail: DetailRef

    @property
    def cursor_key(self) -> tuple[int, str]:
        """The exact continuation key ``Channel.inbox(after=...)`` accepts."""

        return (self.message_seq, str(self.message_id))


class ChannelMessagePage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[ChannelMessageSummary, ...]
    page: PageInfo


class ChannelReplyResult(BaseModel):
    """The one reply a request admits, named by both halves of the exchange."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: Digest
    message_id: Digest
    command: CommandMeta
    detail: DetailRef


class ChannelAckResult(BaseModel):
    """A delivery fact about one actor — never proof of component consumption."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: Digest
    actor_id: str
    acked_at: AwareDatetime
    command: CommandMeta


class VersionPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    component: str
    items: tuple[VersionSummary, ...]
    page: PageInfo


class NamePage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    items: tuple[str, ...]
    page: PageInfo


class ComponentComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    component: str
    left: Digest
    right: Digest
    changes: dict[str, JsonValue]
    reverse_dependencies: tuple[str, ...]


class ApprovalCommandResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[3] = 3
    status: Literal["recorded"] = "recorded"
    approval_id: str
    decision: Literal["approved", "rejected"]
    command: CommandMeta
    detail: DetailRef
    reply: Digest | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Keep a standalone decision's durable bytes exactly as M6 wrote them."""

        data = handler(self)
        if not isinstance(data, dict):
            raise TypeError("ApprovalCommandResult serializer expected an object")
        if self.reply is None:
            data.pop("reply", None)
        return data


class PromotionCommandResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[3] = 3
    status: Literal["promoted", "rolled_back"]
    component: str
    from_version: Digest | None
    to_version: Digest
    command: CommandMeta
    detail: DetailRef


class RegistrationCommandResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[3] = 3
    status: Literal["registered"] = "registered"
    component: str
    version: Digest
    command: CommandMeta
    detail: DetailRef


class CommandSummary(BaseModel):
    """Bounded command lifecycle; complete request/plan/response live by reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str
    operation: str
    state: Literal["prepared", "committed", "rejected"]
    actor_id: str
    request_hash: Digest
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None
    detail: DetailRef | None = None


def command_id_for(actor_id: str, operation: str, idempotency_key: str) -> str:
    body = digest(
        "control-command",
        1,
        {
            "actor_id": actor_id,
            "operation": operation,
            "idempotency_key": idempotency_key,
        },
    )
    return f"cmd-{str(body).removeprefix('sha256:')}"


def run_id_for_command(command_id: str) -> RunId:
    body = digest("run-from-command", 1, {"command_id": command_id})
    return RunId(f"run-{str(body).removeprefix('sha256:')[:32]}")


def approval_id_for_command(command_id: str, subject: JsonValue) -> str:
    body = digest(
        "approval-from-command",
        1,
        {"command_id": command_id, "subject": subject},
    )
    return f"approval-{str(body).removeprefix('sha256:')[:32]}"


def validate_idempotency_key(value: str) -> str:
    if not value or value.strip() != value:
        raise ValueError("idempotency_key must be non-empty and canonical")
    if len(value) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise ValueError(f"idempotency_key exceeds {IDEMPOTENCY_KEY_MAX_LENGTH} characters")
    return value


class ControlStore(Protocol):
    """Durable command and human-decision storage, transaction-shaped."""

    def claim_command(
        self,
        *,
        actor: AuthenticatedActor,
        operation: str,
        idempotency_key: str,
        request_hash: Digest,
        request: JsonValue,
        owner_id: str,
        ttl_s: float,
    ) -> CommandClaimResult: ...

    def store_command_plan(self, claim: CommandClaim, plan: JsonValue) -> None: ...

    def complete_command(self, claim: CommandClaim, response: JsonValue) -> CommandRecord: ...

    def reject_command(self, claim: CommandClaim, response: JsonValue) -> CommandRecord: ...

    def command(self, command_id: str) -> CommandRecord | None: ...

    def latest_command_key(self, *, operation: str) -> tuple[str, str] | None: ...

    def committed_commands(
        self,
        *,
        operation: str,
        after: tuple[str, str] | None,
        through: tuple[str, str],
        limit: PositiveInt,
    ) -> tuple[CommandRecord, ...]: ...

    def store_approval(self, claim: CommandClaim, approval: ApprovalRecord) -> ApprovalRecord: ...

    def store_approval_exchange(
        self,
        claim: CommandClaim,
        approval: ApprovalRecord,
        *,
        channel_id: str,
        request_id: Digest,
        payload: JsonValue,
    ) -> ChannelMessage:
        """The approval record, its reply, and its request ack — one commit.

        A request-bound decision is one fact in three places. Composing two
        committed operations would let a death between them leave an approval
        authorizing an exchange nobody answered.
        """
        ...

    def approval_for_command(self, command_id: str) -> ApprovalRecord | None:
        """The approval one command wrote, if it wrote one."""
        ...

    def approval(self, approval_id: str) -> ApprovalRecord | None: ...
