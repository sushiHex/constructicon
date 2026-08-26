"""Run ownership and execution state (M2).

Authority over a run is a **fenced renewable lease** — ``owner_id + epoch`` —
never PID metadata. Every owner-side write is guarded by the lease; a write
that matches zero rows means authority was lost to a higher epoch and the
stale worker must stop immediately (``OwnershipLost``), writing nothing else.

Liveness is not lifecycle: ``RunStatus`` keeps its six durable values and a
lost run is durably RUNNING with an expired lease — ``RunState`` reports that
as a read-time view, and ``claim_run`` reclaims it with a higher epoch.

One canonical ``InvocationStatus`` enum serves runtime, journal, API, and
renderings.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, PositiveInt

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.envelope import ArtifactRef
from constructicon.core.errors import ConstructiconError


class InvocationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST = "lost"
    BLOCKED = "blocked_by_dependency"
    SKIPPED = "skipped_run_terminated"
    PARKED = "parked"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARKED = "parked"


ParkedReason = Literal[
    "awaiting_approval",
    "awaiting_advisor",
    "policy_exhausted",
    "budget_exhausted",
    "operator_intervention",
]


class RunLease(BaseModel):
    """The authority to write a run. ``owner_id + epoch`` is the fence."""

    model_config = ConfigDict(frozen=True)

    run_id: RunId
    owner_id: str
    epoch: PositiveInt
    expires_at: AwareDatetime


Liveness = Literal["live", "lost", "not_applicable"]


class RunState(BaseModel):
    """Durable status plus read-time liveness — never a persisted LOST."""

    model_config = ConfigDict(frozen=True)

    status: RunStatus
    liveness: Liveness
    owner_id: str | None = None
    lease_expires_at: AwareDatetime | None = None


class OwnershipLost(ConstructiconError):
    """A fenced write matched zero rows: a higher epoch owns this run.

    The stale worker must stop and write nothing else."""


class CheckpointConflict(ConstructiconError):
    """A durable fact was re-written contradictorily at the same identity.

    Durable facts are write-once: identical repetition is idempotent;
    contradictory repetition is damage."""


class ProducerStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: ExecutionPath
    status: InvocationStatus
    error_ref: ArtifactRef | None = None


class DependencyReport(BaseModel):
    """Why a destination is BLOCKED: the complete recorded producer set —
    completed producers included, never only the failing one."""

    model_config = ConfigDict(frozen=True)

    destination: ExecutionPath
    producers: tuple[ProducerStatus, ...]
