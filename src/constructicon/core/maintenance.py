"""Closed data contracts for the two fixed maintenance tasks.

The tasks form a fixed two-case table selected by the authorization's purpose
literal: ``plan-manifest-maintenance`` (one absent data file) and
``channel-stored-reply`` (one exact helper extraction). There is no registry.

The exam is never caller-selected: it is installed code, pinned by the check
set. The instruction is the reviewed base commit's file at a path fixed by the
task's purpose. Its SHA-256 is in the request the owner approves, and the
writer refuses any other bytes. Nothing at run time selects it (owner decision
2026-11-12, docs/designs/INSTRUCTION_BINDING.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from constructicon.core.address import ExecutionPath, GitSha, RunId, ScopePath
from constructicon.core.control import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    command_id_for,
    run_id_for_command,
)
from constructicon.core.envelope import GitRef
from constructicon.core.gates import MergeEvaluation
from constructicon.core.grants import EffectiveGrants, Posture
from constructicon.core.identity import Digest, canonical_json

VECTOR_PATH = "tests/vectors/plan_manifest.json"
TARGET_PATH = "scripts/regen_plan_manifest.py"
CHANNEL_TARGET_PATH = "src/constructicon/substrate/channels/in_process.py"
INSTRUCTION_BYTES = 8192


def instruction_path(purpose: str) -> str:
    """Where the base commit holds one fixed task's instruction."""
    return f"maintenance/{purpose}.txt"


class _Request(BaseModel):
    """Two eras of one request. Era 1 names no instruction and is history only.

    Era 2 pins the instruction by digest, as ``target_sha256`` pins the target.
    Era-1 bytes decode and serialize exactly as they always did; assembly builds
    era 2, and the maintenance entry and its writer refuse a request without a
    digest, so that entry admits no era-1 authorization.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    @model_validator(mode="after")
    def _era(self) -> Self:
        version = getattr(self, "schema_version", None)
        if (version == 2) != (getattr(self, "instruction_sha256", None) is not None):
            raise ValueError("exactly a version-2 request pins its instruction")
        return self

    @model_serializer(mode="wrap")
    def _era_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        wire: dict[str, object] = handler(self)
        if wire.get("instruction_sha256") is None:
            wire.pop("instruction_sha256", None)
        return wire


class PlanManifestRequest(_Request):
    """Trusted assembly data; the exam is never caller-selected (module docstring)."""

    schema_version: Literal[1, 2] = 1
    repository: str = Field(min_length=1, max_length=4096)
    target_ref: str = Field(pattern=r"^refs/heads/[A-Za-z0-9/_-]+$", max_length=256)
    base_commit: GitSha = Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")
    target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_set_hash: Digest
    vector_path: Literal["tests/vectors/plan_manifest.json"] = "tests/vectors/plan_manifest.json"
    instruction_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class PlanManifestResult(BaseModel):
    """Application acceptance proves one base parent plus the gated data tree.

    This does not claim installation, merge, or durable rendered-artifact storage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    candidate: GitRef
    evaluation: MergeEvaluation
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ChannelReplyRequest(_Request):
    """Trusted assembly data for the channel stored-reply extraction task.

    The base target blob is pinned during preparation; the exam is never
    caller-selected. Its shape is disjoint from ``PlanManifestRequest``.
    """

    schema_version: Literal[1, 2] = 1
    repository: str = Field(min_length=1, max_length=4096)
    target_ref: str = Field(pattern=r"^refs/heads/[A-Za-z0-9/_-]+$", max_length=256)
    base_commit: GitSha = Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")
    target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_set_hash: Digest
    target_path: Literal["src/constructicon/substrate/channels/in_process.py"] = (
        "src/constructicon/substrate/channels/in_process.py"
    )
    instruction_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ChannelReplyResult(BaseModel):
    """Acceptance proves one base parent plus one exact in-place modification.

    Its own type and meaning: never a plan-manifest result. This does not claim
    installation, merge, or general semantic equivalence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    candidate: GitRef
    evaluation: MergeEvaluation
    base_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MaintenanceCapabilityPin(BaseModel):
    """An exact application provider descriptor checked by trusted assembly."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(strict=True, min_length=1, max_length=256)
    revision: Digest


class _AttemptAuthorization(BaseModel):
    """The exact-attempt law both closed tasks share; only its two subclasses are used.

    Each subclass narrows ``purpose`` to its own literal and ``request`` to its
    own model. Redeclaring a field keeps its position, so the plan-manifest
    wire and field order are unchanged.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    purpose: str
    authorization_id: str = Field(strict=True, min_length=1, max_length=256)
    actor_id: str = Field(strict=True, min_length=1, max_length=256)
    idempotency_key: str = Field(strict=True, min_length=1, max_length=IDEMPOTENCY_KEY_MAX_LENGTH)
    scope: ScopePath
    binding: str = Field(strict=True, min_length=1, max_length=256)
    source_graph_hash: Digest
    capability_id: str = Field(strict=True, min_length=1, max_length=256)
    revision: str = Field(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")
    operator_binding_digest: Digest
    journal: str = Field(strict=True, min_length=1, max_length=4096)
    max_epoch: Literal[1]
    not_after: AwareDatetime
    grants: EffectiveGrants
    attempt_record: str = Field(strict=True, min_length=1, max_length=4096)
    request: BaseModel
    application_revision: Digest
    workspace: MaintenanceCapabilityPin
    gate: MaintenanceCapabilityPin

    @field_validator("max_epoch", mode="before")
    @classmethod
    def _exact_epoch(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("maintenance authorizes exactly epoch one")
        return value

    @model_validator(mode="after")
    def _write_grants(self) -> Self:
        grants = self.grants
        if (
            grants.posture is not Posture.WRITE
            or grants.model_selection.kind != "explicit"
            or not (grants.model_selection.model or "").strip()
            or not (grants.effort or "").strip()
            or grants.allowed_tools != ("contained_python",)
            or grants.env_allowlist != ()
            or grants.network != "allow"
            or grants.timeout_s != 300
        ):
            raise ValueError("maintenance requires the bounded WRITE grant shape")
        return self

    @property
    def run_id(self) -> RunId:
        return run_id_for_command(command_id_for(self.actor_id, "runs_start", self.idempotency_key))

    def admits(self, *, source_graph_hash: Digest, capability_id: str, revision: str) -> bool:
        """Timeless exact admission; acquisition enforces the window and attempt."""
        return (
            source_graph_hash == self.source_graph_hash
            and capability_id == self.capability_id
            and revision == self.revision
        )

    def acquisition_faults(
        self, *, run_id: RunId, path: ExecutionPath, binding: str,
        source_graph_hash: Digest | None, capability_id: str, revision: str,
        operator_binding_digest: Digest, grants: EffectiveGrants, epoch: int, now: datetime,
    ) -> tuple[str, ...]:
        checks = (
            (run_id == self.run_id, "a different run"),
            (path == ExecutionPath(scope=self.scope), "a different invocation"),
            (binding == self.binding, "a different binding"),
            (source_graph_hash == self.source_graph_hash, "a different source graph"),
            (capability_id == self.capability_id, "a different capability"),
            (revision == self.revision, "a different adapter revision"),
            (
                operator_binding_digest == self.operator_binding_digest,
                "a different operator binding",
            ),
            (canonical_json(grants) == canonical_json(self.grants), "other grants"),
            (type(epoch) is int and epoch == 1, "an acquisition outside the authorized epoch"),
            (now < self.not_after, "an expired authorization"),
        )
        return tuple(f"maintenance refuses {fault}" for held, fault in checks if not held)


class MaintenanceAttemptAuthorization(_AttemptAuthorization):
    """Owner configuration for one application attempt while the executor stays unavailable.

    Assembly proves the request, application and companion provider pins before
    admission or recovery. Acquisition independently checks its exact executor
    invocation and reserves the existing exclusive attempt record. Reservation
    alone is not dispatch evidence. This is separate from N5 qualification.
    """

    purpose: Literal["plan-manifest-maintenance"] = "plan-manifest-maintenance"
    request: PlanManifestRequest


class ChannelReplyAttemptAuthorization(_AttemptAuthorization):
    """The same exact-attempt law for the channel stored-reply task only.

    A distinct closed type: it never admits the plan-manifest task, and a
    plan-manifest authorization never admits this one.
    """

    purpose: Literal["channel-stored-reply"] = "channel-stored-reply"
    request: ChannelReplyRequest


# The fixed two-case table's authorization types, in no extensible registry.
MaintenanceAuthorization = MaintenanceAttemptAuthorization | ChannelReplyAttemptAuthorization
MAINTENANCE_AUTHORIZATIONS: tuple[
    type[MaintenanceAttemptAuthorization], type[ChannelReplyAttemptAuthorization],
] = (MaintenanceAttemptAuthorization, ChannelReplyAttemptAuthorization)
