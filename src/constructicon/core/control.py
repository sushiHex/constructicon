"""Durable control-plane contracts (M6).

MCP is only the first transport. These contracts remain when the transport is
removed: authenticated actors, one durable command identity for every
mutation, long-lived runs, stable pages, and immutable detail references.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self, runtime_checkable

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
    model_validator,
)

from constructicon.core.address import RunId, ScopePath
from constructicon.core.channel import ChannelInteraction, ChannelMessage
from constructicon.core.errors import JournalDamaged
from constructicon.core.graph import Graph, parse_graph_json
from constructicon.core.identity import (
    ActorId,
    Digest,
    JsonValue,
    canonical_json,
    digest,
    json_value,
)
from constructicon.core.manifest import ExecutionManifest, validated_manifest_identity
from constructicon.core.run import TERMINAL_EVENT_STATUSES, Liveness, RunStatus

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

    actor_id: ActorId
    auth_method: Literal["static", "oauth"]
    scopes: frozenset[str]
    display_name: str | None = None
    issuer: str | None = None
    subject: str | None = None
    client_id: str | None = None

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


class RunOrigin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["start", "reproduce", "counterfactual"]
    actor_id: ActorId
    command_id: str
    source_run_id: RunId | None = None
    overrides: dict[str, Digest] = Field(default_factory=dict)
    effects: Literal["live", "simulated"] = "live"
    capabilities: Literal["normal", "discard"] = "normal"


class SourceRunLock(BaseModel):
    """The immutable source world a clone command observed at planning."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_id: RunId
    manifest_hash: Digest
    input_hash: Digest
    source_graph_hash: Digest
    resolution_lock: ResolutionLock | None = None


class RunCreationPlan(BaseModel):
    """The one durable run-creation plan shared by control and recovery."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Literal["run_creation"] = "run_creation"
    run_id: RunId
    manifest: ExecutionManifest
    inputs: dict[str, JsonValue]
    origin: RunOrigin
    source_lock: SourceRunLock | None = None


class LegacyRunCreationPlan(BaseModel):
    """Exact pre-envelope run plan written before source-world locks."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_id: RunId
    manifest: ExecutionManifest
    inputs: dict[str, JsonValue]
    origin: RunOrigin


class StoredRunCreationPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    plan: RunCreationPlan


class CommandClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str
    actor_id: ActorId
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


class ResumeCommandPlan(BaseModel):
    """The exact current plan authorizing one explicit resume attempt.

    Attempt events name their causal command, so this plan belongs in L0 beside
    ``CommandRecord`` rather than in the API executor that happens to write it.
    Omitting the optional rejection policy preserves the bytes written by the
    first M6.2 implementation while current commands carry ``exact-v1``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Literal["resume"] = "resume"
    policy: Literal["resume-v1"] = "resume-v1"
    run_id: RunId
    baseline_event_seq: NonNegativeInt
    submitted_status: RunStatus
    terminal_rejection_policy: Literal["exact-v1"] | None = None

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        data = handler(self)
        if not isinstance(data, dict):
            raise TypeError("ResumeCommandPlan serializer expected an object")
        if self.terminal_rejection_policy is None:
            data.pop("terminal_rejection_policy", None)
        return data


class StoredResumeCommandPlan(BaseModel):
    """The current typed command-plan envelope for an explicit resume."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    plan: ResumeCommandPlan


class LegacyResumeCommandPlan(BaseModel):
    """The exact pre-envelope resume plan retained from M6.1/M6.2."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_id: RunId
    baseline_event_seq: NonNegativeInt | None = None

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        data = handler(self)
        if not isinstance(data, dict):
            raise TypeError("LegacyResumeCommandPlan serializer expected an object")
        if self.baseline_event_seq is None:
            data.pop("baseline_event_seq", None)
        return data


class HistoricalResumePlanEvidence(BaseModel):
    """Migration-only phase evidence for one retained weak resume plan."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    command_id: str
    phase_at_migration: Literal["prepared", "terminal"]


_RESUME_ATTEMPT_KIND_BY_STATUS: dict[
    RunStatus,
    Literal["RunStarted", "RunResumed", "RunReclaimed"],
] = {
    RunStatus.PENDING: "RunStarted",
    RunStatus.RUNNING: "RunReclaimed",
    RunStatus.FAILED: "RunResumed",
    RunStatus.PARKED: "RunResumed",
}
RESUMABLE_RUN_STATUSES = frozenset(_RESUME_ATTEMPT_KIND_BY_STATUS)


def resume_attempt_kind(status: RunStatus) -> Literal["RunStarted", "RunResumed", "RunReclaimed"]:
    """Return the only first transition an attempt may write from ``status``."""

    try:
        return _RESUME_ATTEMPT_KIND_BY_STATUS[status]
    except KeyError as exc:
        raise ValueError(f"status {status.value!r} is not resumable") from exc


def resume_status_at_fence(
    baseline_event_seq: int,
    *,
    baseline_event_kind: str | None,
) -> RunStatus:
    """Recover the exact resumable status from immutable fence history."""

    if baseline_event_seq == 0:
        if baseline_event_kind is not None:
            raise ValueError("zero resume fence unexpectedly names an event")
        return RunStatus.PENDING
    if baseline_event_kind is None:
        raise ValueError("positive resume fence has no retained event")
    terminal_status = TERMINAL_EVENT_STATUSES.get(baseline_event_kind)
    if terminal_status in RESUMABLE_RUN_STATUSES:
        assert terminal_status is not None
        return terminal_status
    if terminal_status is not None:
        raise ValueError("terminal success or cancellation is not resumable")
    return RunStatus.RUNNING


def validated_resume_status_at_fence(
    plan: ResumeCommandPlan | LegacyResumeCommandPlan,
    *,
    baseline_event_kind: str | None,
) -> RunStatus:
    """Derive one plan's status from its fence and require typed agreement."""

    baseline = plan.baseline_event_seq
    if baseline is None:
        raise ValueError("resume plan has no attempt fence")
    status = resume_status_at_fence(
        baseline,
        baseline_event_kind=baseline_event_kind,
    )
    if isinstance(plan, ResumeCommandPlan) and plan.submitted_status != status:
        raise ValueError("resume plan submitted status contradicts its fence")
    return status


def validated_resume_command_plan(
    command: CommandRecord,
) -> ResumeCommandPlan | LegacyResumeCommandPlan:
    """Decode one resume plan and bind it to its immutable command request."""

    if command.operation != "runs_resume":
        raise JournalDamaged(
            f"command {command.command_id!r} is not a resume command"
        )
    raw = command.plan
    if not isinstance(raw, dict):
        raise JournalDamaged(
            f"resume command {command.command_id!r} has no object plan"
        )
    plan: ResumeCommandPlan | LegacyResumeCommandPlan
    try:
        if "schema_version" in raw:
            stored = StoredResumeCommandPlan.model_validate_json(canonical_json(raw))
            plan = stored.plan
            normalized = stored.model_dump(mode="json")
        else:
            plan = LegacyResumeCommandPlan.model_validate_json(canonical_json(raw))
            normalized = plan.model_dump(mode="json")
    except (TypeError, ValueError) as exc:
        raise JournalDamaged(
            f"resume command {command.command_id!r} has an invalid attempt plan"
        ) from exc
    if canonical_json(raw) != canonical_json(normalized):
        raise JournalDamaged(
            f"resume command {command.command_id!r} has a non-lossless attempt plan"
        )
    request = command.request
    if not isinstance(request, dict) or canonical_json(request) != canonical_json(
        {"run_id": str(plan.run_id)}
    ):
        raise JournalDamaged(
            f"resume command {command.command_id!r} request and plan target different runs"
        )
    return plan


def resume_domain_plan(
    command: CommandRecord,
) -> ResumeCommandPlan | LegacyResumeCommandPlan | None:
    """Decode a resume domain plan, or identify another lawful plan family."""

    raw = command.plan
    if command.operation != "runs_resume" or not isinstance(raw, dict):
        return None
    if "schema_version" in raw:
        inner = raw.get("plan")
        if not isinstance(inner, dict) or inner.get("kind") != "resume":
            return None
    elif "run_id" not in raw:
        return None
    return validated_resume_command_plan(command)


def resume_plan_requires_historical_evidence(command: CommandRecord) -> bool:
    """Classify a resume plan's durable era from its wire shape alone."""

    raw = command.plan
    if command.operation != "runs_resume" or raw is None:
        return False
    if not isinstance(raw, dict) or "schema_version" not in raw:
        return True
    plan = resume_domain_plan(command)
    return isinstance(plan, ResumeCommandPlan) and (
        plan.terminal_rejection_policy is None
    )


def validated_new_resume_command_plan(
    command: CommandRecord,
) -> ResumeCommandPlan | None:
    """Require current writers to use the typed resume-plan envelope.

    Raw plans are retained history, never a shape a schema-7 writer may mint.
    Both control stores call this at their plan write boundary so the in-memory
    contract double and SQLite accept exactly the same current plans.
    """

    if resume_plan_requires_historical_evidence(command):
        raise JournalDamaged(
            f"resume command {command.command_id!r} cannot mint a historical plan era"
        )
    plan = resume_domain_plan(command)
    return plan if isinstance(plan, ResumeCommandPlan) else None


def validated_resume_attempt_command(
    command: CommandRecord,
    *,
    run_id: RunId,
    event_seq: int,
    event_kind: str,
    baseline_event_kind: str | None = None,
) -> ResumeCommandPlan | LegacyResumeCommandPlan:
    """Bind one command-attributed attempt event to its exact durable authority.

    Missing provenance is ordinary recovery and is handled by the caller. Once
    an event names ``resume_command_id``, however, the name is a relationship:
    it must resolve to a non-rejected ``runs_resume`` command for this run. A
    The plan pins the immediately preceding event fence.  The fence history is
    the authority for both its submitted status and transition kind; current
    typed plans must agree with it.  Unfenced history cannot authorize an
    attributed attempt.
    """

    if command.state == "rejected":
        raise JournalDamaged(
            f"command {command.command_id!r} cannot authorize a resume attempt"
        )
    plan = validated_resume_command_plan(command)
    if plan.run_id != run_id:
        raise JournalDamaged(
            f"resume command {command.command_id!r} plan targets another run"
        )
    baseline = plan.baseline_event_seq
    if baseline is None:
        raise JournalDamaged(
            f"resume command {command.command_id!r} has no attempt fence"
        )
    if event_seq != baseline + 1:
        raise JournalDamaged(
            f"resume command {command.command_id!r} receipt is not at its attempt fence"
        )
    try:
        baseline_status = validated_resume_status_at_fence(
            plan,
            baseline_event_kind=baseline_event_kind,
        )
    except ValueError as exc:
        raise JournalDamaged(
            f"resume command {command.command_id!r} has no lawful baseline status"
        ) from exc
    if resume_attempt_kind(baseline_status) != event_kind:
        raise JournalDamaged(
            f"resume command {command.command_id!r} receipt contradicts its baseline"
        )
    return plan


def validated_run_creation_command(command: CommandRecord) -> RunCreationPlan:
    """Decode and bind one durable plan to its command and authority mode."""

    raw = command.plan
    if not isinstance(raw, dict):
        raise JournalDamaged(
            f"run creation command {command.command_id!r} has no object plan"
        )
    current = "schema_version" in raw
    try:
        if current:
            stored = StoredRunCreationPlan.model_validate_json(canonical_json(raw))
            plan = stored.plan
            normalized = json_value(stored.model_dump(mode="json"))
        else:
            legacy = LegacyRunCreationPlan.model_validate_json(canonical_json(raw))
            normalized = json_value(legacy.model_dump(mode="json"))
            plan = RunCreationPlan(
                run_id=legacy.run_id,
                manifest=legacy.manifest,
                inputs=legacy.inputs,
                origin=legacy.origin,
            )
    except (TypeError, ValueError) as exc:
        raise JournalDamaged(
            f"run creation command {command.command_id!r} has an invalid plan"
        ) from exc
    if canonical_json(raw) != canonical_json(normalized):
        raise JournalDamaged(
            f"run creation command {command.command_id!r} has a non-lossless plan"
        )
    return _validated_run_creation_plan(command, plan, current=current)


def validated_new_run_creation_plan(
    command: CommandRecord,
    plan: RunCreationPlan,
) -> RunCreationPlan:
    """Validate a current plan before its durable command-plan write."""

    return _validated_run_creation_plan(command, plan, current=True)


def _validated_run_creation_plan(
    command: CommandRecord,
    plan: RunCreationPlan,
    *,
    current: bool,
) -> RunCreationPlan:
    try:
        validated_manifest_identity(plan.manifest)
    except ValueError as exc:
        raise JournalDamaged(
            f"run creation command {command.command_id!r} carries an invalid manifest"
        ) from exc
    if command.operation not in {
        "runs_start",
        "runs_reproduce",
        "runs_counterfactual",
    } or command.state == "rejected":
        raise JournalDamaged(
            f"command {command.command_id!r} cannot own a created run"
        )
    if (
        plan.run_id != run_id_for_command(command.command_id)
        or digest("inputs", 1, plan.inputs) != plan.manifest.input_hash
        or plan.origin.actor_id != command.actor.actor_id
        or plan.origin.command_id != command.command_id
    ):
        raise JournalDamaged(
            f"run creation command {command.command_id!r} contradicts its durable plan"
        )
    request = command.request
    if not isinstance(request, dict):
        raise JournalDamaged(
            f"run creation command {command.command_id!r} has no object request"
        )
    if command.operation == "runs_start":
        if set(request) != {"proposal", "inputs"} or plan.source_lock is not None:
            raise JournalDamaged("start plan contradicts its canonical request")
        proposal = request["proposal"]
        try:
            graph = (
                parse_graph_json(proposal)
                if isinstance(proposal, str)
                else Graph.model_validate(proposal)
            )
        except (TypeError, ValueError) as exc:
            raise JournalDamaged("stored start request is not a valid graph") from exc
        expected_origin = RunOrigin(
            kind="start",
            actor_id=command.actor.actor_id,
            command_id=command.command_id,
        )
        try:
            exact_request = canonical_json(request["inputs"])
        except (TypeError, ValueError) as exc:
            raise JournalDamaged("start request has invalid inputs") from exc
        if (
            canonical_json(json_value(graph.model_dump(mode="json")))
            != canonical_json(json_value(plan.manifest.source_graph.model_dump(mode="json")))
            or exact_request != canonical_json(plan.inputs)
            or canonical_json(json_value(plan.origin.model_dump(mode="json")))
            != canonical_json(json_value(expected_origin.model_dump(mode="json")))
        ):
            raise JournalDamaged("start plan contradicts its canonical request")
        return plan

    if set(request) != {"source_run_id", "overrides"}:
        raise JournalDamaged("clone plan contradicts its canonical request")
    source = request["source_run_id"]
    raw_overrides = request["overrides"]
    if type(source) is not str or not isinstance(raw_overrides, dict) or not all(
        type(name) is str and type(value) is str
        for name, value in raw_overrides.items()
    ):
        raise JournalDamaged("clone request has invalid source or overrides")
    try:
        source_run_id = RunId(source)
        overrides = {name: Digest(value) for name, value in raw_overrides.items()}
    except (TypeError, ValueError) as exc:
        raise JournalDamaged("clone request has invalid source or overrides") from exc
    counterfactual = command.operation == "runs_counterfactual"
    expected_origin = RunOrigin(
        kind="counterfactual" if counterfactual else "reproduce",
        actor_id=command.actor.actor_id,
        command_id=command.command_id,
        source_run_id=source_run_id,
        overrides=overrides if counterfactual else {},
        effects="simulated" if counterfactual else "live",
        capabilities="discard" if counterfactual else "normal",
    )
    source_lock = plan.source_lock
    if (
        canonical_json(json_value(plan.origin.model_dump(mode="json")))
        != canonical_json(json_value(expected_origin.model_dump(mode="json")))
        or (current and source_lock is None)
        or (source_lock is not None and source_lock.run_id != source_run_id)
        or (
            source_lock is not None
            and ((source_lock.resolution_lock is not None) != counterfactual)
        )
    ):
        raise JournalDamaged("clone plan contradicts its canonical request")
    return plan


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
        interaction for interaction, scope in INTERACTION_SCOPES.items() if actor.allows(scope)
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

    There is deliberately no administrator escape from the recipient test. This
    predicate must not be wider than `message_for_reply`, which admits only the
    sealed recipient: an actor this admitted and the domain refused would raise
    after its command was claimed and planned, stranding it forever. Making the
    two one also settles the read/act asymmetry — an addressed request is no
    more discoverable in an administrator's inbox than answerable by one.
    """

    if not actor.allows(INTERACTION_SCOPES[request.interaction]):
        return False
    return request.recipient_actor_id is None or request.recipient_actor_id == actor.actor_id


class CommandClaimResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["claimed", "replayed", "in_progress", "conflict"]
    claim: CommandClaim | None = None
    record: CommandRecord | None = None


class CommandMeta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str
    replayed: bool


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


class RunHead(BaseModel):
    """One run row and its latest retained event in one read snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: RunRecord
    event_seq: NonNegativeInt
    event_kind: str | None

    @model_validator(mode="after")
    def _event_position_is_complete(self) -> RunHead:
        if (self.event_seq == 0) != (self.event_kind is None):
            raise ValueError("run head event sequence and kind disagree")
        return self


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
    actor_id: ActorId
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
    actor_id: ActorId
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


def command_request_hash(request: JsonValue) -> Digest:
    """The one canonical digest sealing a durable command request."""

    return digest("control-request", 1, request)


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

    def historical_resume_plan_evidence(
        self,
        command_id: str,
    ) -> HistoricalResumePlanEvidence | None:
        """Return explicit pre-v7 phase evidence for one resume domain plan."""
        ...

    def latest_command_key(self, *, operation: str) -> tuple[str, str] | None: ...

    def committed_commands(
        self,
        *,
        operation: str,
        after: tuple[str, str] | None,
        through: tuple[str, str],
        limit: PositiveInt,
    ) -> tuple[CommandRecord, ...]: ...

    def command_records(
        self,
        *,
        operation: str,
        after: tuple[str, str] | None,
        through: tuple[str, str],
        limit: PositiveInt,
    ) -> tuple[CommandRecord, ...]:
        """Page every command in one created-time cut, without state prefiltering."""
        ...

    def store_approval(self, claim: CommandClaim, approval: ApprovalRecord) -> ApprovalRecord: ...

    def approval_for_command(self, command_id: str) -> ApprovalRecord | None:
        """The approval one command wrote, if it wrote one."""
        ...

    def approval(self, approval_id: str) -> ApprovalRecord | None: ...


@runtime_checkable
class ControlPlaneStore(ControlStore, Protocol):
    """A control ledger co-located with the channel facts it must commit."""

    def store_approval_exchange(
        self,
        claim: CommandClaim,
        approval: ApprovalRecord,
        *,
        channel_id: str,
        request_id: Digest,
        payload: JsonValue,
    ) -> ChannelMessage:
        """Persist one complete approval exchange in one transaction.

        A request-bound decision is one fact in three places. A new
        acknowledgement commits with the approval and reply; an equal earlier
        acknowledgement remains immutable while the approval and reply commit
        together. Composing separate operations would let a death between them
        leave an approval authorizing an exchange nobody answered.
        """
        ...
