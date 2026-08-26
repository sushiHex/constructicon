"""Journal contracts (M2): one transactional log, transaction-shaped
operations, fenced writes, write-once durable facts.

Semantic commits replace call-pairs a caller must remember to combine:
creation stores the manifest, the PENDING run, and the exact inputs durably in
one transaction; lifecycle transitions commit the state change and its event
together; a node completion commits checkpoint + ``NodeCompleted`` in one
transaction; an effect receipt commits with its event.

Every owner-side write takes the ``RunLease`` and is fenced by
``owner_id + epoch`` — an operation that matches zero rows raises
``OwnershipLost`` and the stale worker stops.

Durable facts (runs, manifests, checkpoints, receipts, attestations) are
write-once: absent → insert; identical → idempotent; contradictory at the
same identity → ``CheckpointConflict``/``JournalDamaged``.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.effect import (
    Attestation,
    AttestationDraft,
    EffectReceipt,
    EffectRequest,
)
from constructicon.core.envelope import Envelope
from constructicon.core.identity import Digest
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunLease, RunState, RunStatus

JOURNAL_SCHEMA_VERSION = 1


class JournalEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = JOURNAL_SCHEMA_VERSION
    run_id: RunId
    seq: int  # per-run monotonic; allocated by the fenced counter in the run row
    kind: str  # RunStarted / NodeStarted / NodeCompleted / NodeBlocked / ...
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

    # -- creation (write-once; a crash after this leaves a resumable PENDING run)

    def create_run(
        self,
        run_id: RunId,
        *,
        manifest_json: str,
        manifest_hash: Digest,
        input_hash: Digest,
        inputs: dict[str, Any],
    ) -> None: ...

    # -- ownership (the fence)

    def claim_run(self, run_id: RunId, *, owner_id: str, ttl_s: float) -> RunLease:
        """Atomic: accepts PENDING/FAILED/PARKED, accepts RUNNING only with an
        expired lease; increments the epoch; two concurrent claims produce one
        winner. Raises OwnershipLost on a live foreign owner."""
        ...

    def heartbeat(self, lease: RunLease, *, ttl_s: float) -> RunLease:
        """Renew the lease. Updates ownership state only — never events."""
        ...

    def release_run(self, lease: RunLease) -> None: ...

    def request_cancel(self, run_id: RunId) -> None: ...

    def cancel_requested(self, run_id: RunId) -> bool: ...

    # -- fenced lifecycle and records

    def transition_run(
        self,
        lease: RunLease,
        *,
        expected: frozenset[RunStatus],
        target: RunStatus,
        event_kind: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Fenced state change + its event, one transaction."""
        ...

    def append_event(
        self,
        lease: RunLease,
        kind: str,
        *,
        path: ExecutionPath | None = None,
        payload: dict[str, Any] | None = None,
    ) -> JournalEvent: ...

    def record_completion(self, lease: RunLease, checkpoint: Checkpoint) -> None:
        """Checkpoint + NodeCompleted event, one transaction; write-once."""
        ...

    def record_effect_prepared(self, lease: RunLease, request: EffectRequest) -> None: ...

    def record_effect_outcome(
        self,
        lease: RunLease,
        request: EffectRequest,
        receipt: EffectReceipt,
        event_kind: str,
    ) -> None:
        """Receipt + its event (EffectCommitted/EffectReconciled), one
        transaction; the receipt is write-once."""
        ...

    # -- reads

    def run_state(self, run_id: RunId) -> RunState | None: ...

    def run_manifest_hash(self, run_id: RunId) -> Digest | None: ...

    def run_inputs(self, run_id: RunId) -> dict[str, Any] | None: ...

    def load_manifest_json(self, manifest_hash: Digest) -> str | None: ...

    def events(
        self, run_id: RunId, *, after_seq: int = 0, limit: int = 100
    ) -> list[JournalEvent]: ...

    def checkpoint(self, run_id: RunId, path: ExecutionPath) -> Checkpoint | None: ...

    def receipt_for(self, idempotency_key: Digest) -> EffectReceipt | None: ...

    def effect_prepared(self, idempotency_key: Digest) -> bool:
        """A prepared record without a receipt — the reconcile-first case."""
        ...

    # -- capability leases (physical acquisitions; the walker owns transitions)

    def record_capability_lease(
        self, lease: RunLease, capability_lease: CapabilityLease
    ) -> None:
        """Fenced, write-once on (lease_id, acquisition_epoch)."""
        ...

    def transition_capability_lease(
        self,
        lease: RunLease,
        *,
        lease_id: str,
        acquisition_epoch: int,
        expected: frozenset[str],
        target: str,
        disposition: str | None = None,
    ) -> None:
        """Fenced CAS + event, one transaction; idempotent when already at
        the target state (mirror of record_completion's identical-repetition
        rule, so crash-interrupted closure re-runs safely)."""
        ...

    def capability_leases(self, run_id: RunId) -> list[CapabilityLease]: ...

    # -- attestations (journal-minted authority, I2 — minting is literal)

    def mint_attestation(self, lease: RunLease, draft: AttestationDraft) -> Attestation:
        """Fenced minting: the journal verifies the run lease, derives
        created_by_run from it, assigns created_at, computes the
        content-derived id, and inserts write-once."""
        ...

    def mint_policy_attestation(self, draft: AttestationDraft) -> Attestation:
        """Run-less deterministic policies (bootstrap, rollback) — the one
        explicit path with no lease; never a nullable-lease blur."""
        ...

    def load_attestation(self, attestation_id: str) -> Attestation | None: ...
