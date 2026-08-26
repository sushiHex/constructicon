"""Journal contracts: one transactional log, many projections.

SQLite is authoritative for runs, events, checkpoints, effects, attestations,
and promotions; JSONL and every rendering are regenerable projections. A node
completion commits checkpoint + event in one transaction.

One canonical ``InvocationStatus`` enum is used everywhere — runtime, journal,
API, renderings.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.effect import Attestation, EffectReceipt, EffectRequest
from constructicon.core.envelope import Envelope
from constructicon.core.identity import Digest

JOURNAL_SCHEMA_VERSION = 1


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


class JournalEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = JOURNAL_SCHEMA_VERSION
    run_id: RunId
    seq: int  # per-run monotonic, allocated by the journal
    kind: str  # RunStarted / NodeStarted / NodeCompleted / EffectCommitted / ...
    path: ExecutionPath | None = None
    created_at: AwareDatetime
    payload: dict[str, Any] | None = None  # size-capped; large outputs by reference


class Checkpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: RunId
    path: ExecutionPath
    input_hash: Digest
    resolved_version: Digest | None
    outputs: dict[str, Envelope[Any]]
    # no workspace field: lease state belongs to CapabilityLease records,
    # never to a node-output checkpoint


class Journal(Protocol):
    """The authoritative store. Every mutation is transactional."""

    def create_run(self, run_id: RunId, manifest_hash: Digest, input_hash: Digest) -> None: ...

    def set_run_status(self, run_id: RunId, status: RunStatus) -> None: ...

    def run_status(self, run_id: RunId) -> RunStatus | None: ...

    def run_manifest_hash(self, run_id: RunId) -> Digest | None: ...

    def append_event(
        self,
        run_id: RunId,
        kind: str,
        *,
        path: ExecutionPath | None = None,
        payload: dict[str, Any] | None = None,
    ) -> JournalEvent: ...

    def events(
        self, run_id: RunId, *, after_seq: int = 0, limit: int = 100
    ) -> list[JournalEvent]: ...

    def record_completion(self, checkpoint: Checkpoint) -> None:
        """Commit checkpoint + NodeCompleted event in ONE transaction."""
        ...

    def checkpoint(self, run_id: RunId, path: ExecutionPath) -> Checkpoint | None: ...

    def store_manifest(self, manifest_json: str, manifest_hash: Digest) -> None: ...

    def load_manifest_json(self, manifest_hash: Digest) -> str | None: ...

    def mint_attestation(self, attestation: Attestation) -> None: ...

    def load_attestation(self, attestation_id: str) -> Attestation | None: ...

    def record_effect_prepared(self, run_id: RunId, request: EffectRequest) -> None: ...

    def record_effect_receipt(
        self, run_id: RunId, request: EffectRequest, receipt: EffectReceipt
    ) -> None: ...

    def receipt_for(self, idempotency_key: Digest) -> EffectReceipt | None: ...

    def effect_prepared(self, idempotency_key: Digest) -> bool:
        """A prepared record without a receipt — the reconcile-first case."""
        ...

    def run_inputs(self, run_id: RunId) -> dict[str, Any] | None: ...
