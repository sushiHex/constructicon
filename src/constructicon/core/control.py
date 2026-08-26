"""Durable control-plane contracts (M6).

MCP is only the first transport. These contracts remain when the transport is
removed: authenticated actors, one durable command identity for every
mutation, long-lived runs, stable pages, and immutable detail references.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    field_validator,
)

from constructicon.core.address import RunId
from constructicon.core.identity import Digest, JsonValue, digest
from constructicon.core.run import Liveness, RunStatus

if TYPE_CHECKING:
    from constructicon.core.effect import ApprovalRecord

CONTROL_SCHEMA_VERSION = 1
IDEMPOTENCY_KEY_MAX_LENGTH = 200

READ_SCOPE = "constructicon:read"
OPERATE_SCOPE = "constructicon:operate"
APPROVE_SCOPE = "constructicon:approve"
PROMOTE_SCOPE = "constructicon:promote"
ADMIN_SCOPE = "constructicon:admin"
CONTROL_SCOPES = frozenset(
    {READ_SCOPE, OPERATE_SCOPE, APPROVE_SCOPE, PROMOTE_SCOPE, ADMIN_SCOPE}
)


class ControlCode(StrEnum):
    AUTH_REQUIRED_SCOPE = "control.auth.required_scope"
    IDEMPOTENCY_CONFLICT = "control.idempotency.conflict"
    COMMAND_IN_PROGRESS = "control.command.in_progress"
    COMMAND_UNKNOWN = "control.command.unknown"
    CURSOR_INVALID = "control.cursor.invalid"
    CURSOR_QUERY_MISMATCH = "control.cursor.query_mismatch"
    DETAIL_NOT_FOUND = "control.detail.not_found"
    RUN_UNKNOWN = "control.run.unknown"
    RUN_LIVE_OWNER = "control.run.live_owner"
    RUN_TERMINAL = "control.run.terminal"
    RUN_NOT_RESUMABLE = "control.run.not_resumable"
    COUNTERFACTUAL_LOCK_MISMATCH = "control.counterfactual.lock_mismatch"
    COUNTERFACTUAL_EFFECT_UNSUPPORTED = "control.counterfactual.effect_unsupported"
    REGISTRY_STABLE_MOVED = "control.registry.stable_moved"
    REGISTRY_VERSION_UNKNOWN = "control.registry.version_unknown"
    APPROVAL_INVALID_SUBJECT = "control.approval.invalid_subject"
    REQUEST_INVALID = "control.request.invalid"


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

    def allows(self, scope: str) -> bool:
        return ADMIN_SCOPE in self.scopes or scope in self.scopes


class ControlFault(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ControlCode
    message: str
    repair: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ControlRejected(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    status: Literal["rejected"] = "rejected"
    faults: tuple[ControlFault, ...]


class DetailRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    uri: str
    media_type: str = "application/json"
    digest: Digest | None = None


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

    schema_version: Literal[1] = 1
    status: Literal["submitted"] = "submitted"
    run_id: RunId
    run_status: RunStatus
    command: CommandMeta
    origin: RunOrigin
    status_ref: DetailRef


class CancellationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
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
    result_ref: DetailRef


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
    detail: DetailRef


class VersionSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    component: str
    version: Digest
    stable: bool
    registered_at: AwareDatetime
    detail: DetailRef


class VersionPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    component: str
    items: tuple[VersionSummary, ...]
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

    schema_version: Literal[1] = 1
    status: Literal["recorded"] = "recorded"
    approval_id: str
    decision: Literal["approved", "rejected"]
    command: CommandMeta
    detail: DetailRef


class PromotionCommandResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    status: Literal["promoted", "rolled_back"]
    component: str
    from_version: Digest | None
    to_version: Digest
    command: CommandMeta
    detail: DetailRef


class CommandView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record: CommandRecord
    detail: DetailRef


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
        raise ValueError(
            f"idempotency_key exceeds {IDEMPOTENCY_KEY_MAX_LENGTH} characters"
        )
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

    def store_approval(self, claim: CommandClaim, approval: ApprovalRecord) -> ApprovalRecord: ...

    def approval(self, approval_id: str) -> ApprovalRecord | None: ...
