"""Closed data contracts for the fixed plan-manifest maintenance application."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

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


class PlanManifestRequest(BaseModel):
    """Trusted assembly data, never a caller-selected instruction or exam."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    repository: str = Field(min_length=1, max_length=4096)
    target_ref: str = Field(pattern=r"^refs/heads/[A-Za-z0-9/_-]+$", max_length=256)
    base_commit: GitSha = Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")
    target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_set_hash: Digest
    vector_path: Literal["tests/vectors/plan_manifest.json"] = "tests/vectors/plan_manifest.json"


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


class MaintenanceCapabilityPin(BaseModel):
    """An exact application provider descriptor checked by trusted assembly."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(strict=True, min_length=1, max_length=256)
    revision: Digest


class MaintenanceAttemptAuthorization(BaseModel):
    """Owner configuration for one application attempt while the executor stays unavailable.

    Assembly proves the request, application and companion provider pins before
    admission or recovery. Acquisition independently checks its exact executor
    invocation and reserves the existing exclusive attempt record. Reservation
    alone is not dispatch evidence. This is separate from N5 qualification.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    purpose: Literal["plan-manifest-maintenance"] = "plan-manifest-maintenance"
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
    request: PlanManifestRequest
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
    def _write_grants(self) -> MaintenanceAttemptAuthorization:
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
