"""Journal contracts: one transactional log and fenced, write-once facts.

M6 extends run creation with optional immutable origin and adds bounded run/event
reads for the control plane. Commands and approvals remain a separate
``ControlStore`` contract even when SQLite implements both over one WAL file.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.channel import (
    ActorInboxRevision,
    Channel,
    ChannelAck,
    ChannelAckRecord,
    ChannelDelivery,
    ChannelInteraction,
    ChannelMessage,
    ChannelMessageWriter,
)
from constructicon.core.control import RunHead, RunOrigin, RunRecord
from constructicon.core.effect import (
    Attestation,
    AttestationDraft,
    EffectReceipt,
    EffectRequest,
)
from constructicon.core.envelope import Envelope
from constructicon.core.identity import Digest, JsonValue
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

    def record_effect_prepared(
        self,
        lease: RunLease,
        request: EffectRequest,
    ) -> EffectRequest:
        """Prepare this key once and return its canonical first request."""
        ...

    def record_effect_outcome(
        self,
        lease: RunLease,
        request: EffectRequest,
        receipt: EffectReceipt,
        event_kind: str,
    ) -> Literal["recorded", "already_recorded"]: ...

    def run_state(self, run_id: RunId) -> RunState | None: ...

    def run_record(self, run_id: RunId) -> RunRecord | None: ...

    def run_head(self, run_id: RunId) -> RunHead | None:
        """Read a run row and latest event position from one snapshot."""
        ...

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

    def channel_message_writer(self, *, message_id: Digest) -> ChannelMessageWriter | None:
        """Who wrote this message, and in which provenance era they wrote it."""
        ...

    def channel_reply_for(
        self,
        *,
        channel_id: str,
        request_id: Digest,
    ) -> ChannelMessage | None:
        """The complete reply, validated with its request and atomic sender ack."""
        ...

    def channel_reply(
        self,
        *,
        channel_id: str,
        request_id: Digest,
        actor_id: str,
        payload: JsonValue,
        command_id: str,
    ) -> ChannelMessage:
        """Append the one authenticated reply and its request ack, atomically."""
        ...

    def channel_acknowledge(
        self,
        *,
        channel_id: str,
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> ChannelAck:
        """One delivery fact about one actor, owned by one command."""
        ...

    def channel_ack(
        self,
        *,
        message_id: Digest,
        actor_id: str,
    ) -> ChannelAckRecord | None:
        """Read one acknowledgement and the command that recorded it."""
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
        """Map parked requests with replies; a missing/non-request wait is damage."""
        ...

    def max_event_seq(self, run_id: RunId) -> int: ...

    def checkpoint(self, run_id: RunId, path: ExecutionPath) -> Checkpoint | None: ...

    def receipt_for(self, idempotency_key: Digest) -> EffectReceipt | None: ...

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


@runtime_checkable
class JournalBackedChannel(Channel, Protocol):
    """A durable channel that can prove which journal owns its history.

    Structural rather than concrete: a new SQLite-backed transport remains
    extensible, but ``durability='sqlite_wal'`` is a claim about one exact
    durable world and therefore owes this assembly proof.
    """

    def is_assembled_from(self, journal: Journal) -> bool: ...
