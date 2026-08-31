"""Journal contracts: one transactional log and fenced, write-once facts.

M6 extends run creation with optional immutable origin and adds bounded run/event
reads for the control plane. Commands and approvals remain a separate
``ControlStore`` contract even when SQLite implements both over one WAL file.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.channel import (
    ActorInboxRevision,
    ChannelDelivery,
    ChannelInteraction,
)
from constructicon.core.control import RunOrigin, RunRecord
from constructicon.core.effect import (
    Attestation,
    AttestationDraft,
    EffectReceipt,
    EffectRequest,
)
from constructicon.core.envelope import Envelope
from constructicon.core.identity import Digest
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import ParkedWait, RunLease, RunState, RunStatus

JOURNAL_SCHEMA_VERSION = 1


class JournalEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = JOURNAL_SCHEMA_VERSION
    run_id: RunId
    seq: int
    kind: str
    path: ExecutionPath | None = None
    created_at: AwareDatetime
    payload: dict[str, Any] | None = None


class Checkpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: RunId
    path: ExecutionPath
    input_hash: Digest
    resolved_version: Digest | None
    outputs: dict[str, Envelope[Any]]


class Journal(Protocol):
    """The authoritative execution store. Every mutation is transactional."""

    def create_run(
        self,
        run_id: RunId,
        *,
        manifest_json: str,
        manifest_hash: Digest,
        input_hash: Digest,
        inputs: dict[str, Any],
        origin: RunOrigin | None = None,
    ) -> None:
        """Manifest + PENDING run + inputs + optional origin, one transaction."""
        ...

    def claim_run(
        self,
        run_id: RunId,
        *,
        owner_id: str,
        ttl_s: float,
        expected_event_seq: int | None = None,
        expected_statuses: frozenset[RunStatus] | None = None,
    ) -> RunLease: ...

    def heartbeat(self, lease: RunLease, *, ttl_s: float) -> RunLease: ...

    def release_run(self, lease: RunLease) -> None: ...

    def request_cancel(self, run_id: RunId) -> None: ...

    def cancel_requested(self, run_id: RunId) -> bool: ...

    def transition_run(
        self,
        lease: RunLease,
        *,
        expected: frozenset[RunStatus],
        target: RunStatus,
        event_kind: str,
        payload: dict[str, Any] | None = None,
    ) -> None: ...

    def append_event(
        self,
        lease: RunLease,
        kind: str,
        *,
        path: ExecutionPath | None = None,
        payload: dict[str, Any] | None = None,
    ) -> JournalEvent: ...

    def record_completion(self, lease: RunLease, checkpoint: Checkpoint) -> None: ...

    def record_effect_prepared(self, lease: RunLease, request: EffectRequest) -> None: ...

    def record_effect_outcome(
        self,
        lease: RunLease,
        request: EffectRequest,
        receipt: EffectReceipt,
        event_kind: str,
    ) -> None: ...

    def run_state(self, run_id: RunId) -> RunState | None: ...

    def run_record(self, run_id: RunId) -> RunRecord | None: ...

    def run_records(
        self,
        *,
        statuses: tuple[RunStatus, ...] | None = None,
        after: tuple[str, str] | None = None,
        through: tuple[str, str] | None = None,
        limit: int = 100,
    ) -> list[RunRecord]: ...

    def recoverable_runs(self, *, limit: int = 100) -> list[RunId]:
        """PENDING plus RUNNING whose ownership lease is lost."""
        ...

    def latest_run_key(
        self, *, statuses: tuple[RunStatus, ...] | None = None
    ) -> tuple[str, str] | None:
        """The final (created_at, run_id) key in one read snapshot."""
        ...

    def run_manifest_hash(self, run_id: RunId) -> Digest | None: ...

    def run_inputs(self, run_id: RunId) -> dict[str, Any] | None: ...

    def run_origin(self, run_id: RunId) -> RunOrigin | None: ...

    def load_manifest_json(self, manifest_hash: Digest) -> str | None: ...

    def events(
        self, run_id: RunId, *, after_seq: int = 0, limit: int = 100
    ) -> list[JournalEvent]: ...

    def event(self, run_id: RunId, seq: int) -> JournalEvent | None: ...

    def latest_terminal_event(self, run_id: RunId) -> JournalEvent | None:
        """Return the newest terminal-attempt event with one bounded store read."""
        ...

    def parked_waits(
        self,
        *,
        after: tuple[str, str] | None = None,
        through: tuple[str, str] | None = None,
        limit: int = 100,
    ) -> list[ParkedWait]:
        """Bounded page of PARKED runs and the requests that would wake them."""
        ...

    def channel_delivery(
        self,
        *,
        message_id: Digest,
        actor_id: str,
    ) -> ChannelDelivery | None:
        """One channel message by identity, with its position and this actor's ack."""
        ...

    def channel_actor_revision(self, *, actor_id: str) -> ActorInboxRevision:
        """The cut over all retained history this actor's inbox is read at."""
        ...

    def channel_actor_inbox(
        self,
        *,
        actor_id: str,
        revision: ActorInboxRevision,
        interactions: frozenset[ChannelInteraction],
        after: tuple[int, str] | None,
        limit: int,
    ) -> tuple[ChannelDelivery, ...]:
        """Bounded page of this actor's retained messages it may read, at one cut."""
        ...

    def answered_requests(self, requests: Sequence[Digest]) -> dict[Digest, Digest]:
        """Map each request that already has a stored reply to that reply's id."""
        ...

    def max_event_seq(self, run_id: RunId) -> int: ...

    def checkpoint(self, run_id: RunId, path: ExecutionPath) -> Checkpoint | None: ...

    def receipt_for(self, idempotency_key: Digest) -> EffectReceipt | None: ...

    def effect_prepared(self, idempotency_key: Digest) -> bool: ...

    def record_capability_lease(
        self, lease: RunLease, capability_lease: CapabilityLease
    ) -> None: ...

    def transition_capability_lease(
        self,
        lease: RunLease,
        *,
        lease_id: str,
        acquisition_epoch: int,
        expected: frozenset[str],
        target: str,
        disposition: str | None = None,
    ) -> None: ...

    def capability_leases(self, run_id: RunId) -> list[CapabilityLease]: ...

    def mint_attestation(self, lease: RunLease, draft: AttestationDraft) -> Attestation: ...

    def mint_policy_attestation(self, draft: AttestationDraft) -> Attestation: ...

    def load_attestation(self, attestation_id: str) -> Attestation | None: ...
