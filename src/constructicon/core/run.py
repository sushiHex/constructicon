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

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.envelope import ArtifactRef
from constructicon.core.errors import ConstructiconError
from constructicon.core.identity import Digest


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


class ParkedUnit(BaseModel):
    """One root execution unit that stopped without failing.

    A parked unit carries the evidence its own reason needs, and nothing else:
    an exhausted policy records how far it got, and a wait records the exact
    request it is waiting on. ``waiting_on`` is what lets recovery reconstruct
    a wake from durable facts alone, so it must never be set for a reason that
    is not actually waiting for a reply.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: ExecutionPath
    reason: ParkedReason
    completed_iterations: PositiveInt | None = None
    waiting_on: Digest | None = None

    @model_validator(mode="after")
    def _reason_carries_its_own_evidence(self) -> ParkedUnit:
        if self.reason == "policy_exhausted" and self.completed_iterations is None:
            raise ValueError("policy_exhausted parking records completed_iterations")
        waiting = self.reason in {"awaiting_advisor", "awaiting_approval"}
        if waiting and self.waiting_on is None:
            raise ValueError(f"{self.reason} parking records the request it waits on")
        if not waiting and self.waiting_on is not None:
            raise ValueError(f"{self.reason} parking is not waiting on a request")
        return self


class ParkedWait(BaseModel):
    """One PARKED run and the exact requests a reply would wake it at.

    Derived from existing rows — a projection, never a table, an outbox, or a
    second authority.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    event_seq: NonNegativeInt
    requests: tuple[Digest, ...]


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


class RunAttemptSuperseded(ConstructiconError):
    """The durable run changed after a host selected one exact attempt.

    This is an admission fence, not ownership loss: no lease was mutated and
    the host must rescan durable state before deciding whether to try again.
    """


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
