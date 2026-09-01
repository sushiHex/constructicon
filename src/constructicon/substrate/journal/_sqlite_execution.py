# mypy: disable-error-code="attr-defined"
"""Durable run, event, checkpoint, effect, lease, and attestation operations."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import ValidationError

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.channel import CHANNEL_SEND_EFFECT, ChannelSendIntent
from constructicon.core.effect import (
    Attestation,
    AttestationDraft,
    ChannelSendSubject,
    ComponentProofSubject,
    EffectReceipt,
    EffectRequest,
    attestation_id_for,
)
from constructicon.core.effect import idempotency_key as effect_idempotency_key
from constructicon.core.effect import request_hash as effect_request_hash
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import Digest, canonical_json, parse_json_value
from constructicon.core.journal import Checkpoint, JournalEvent
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import (
    CheckpointConflict,
    OwnershipLost,
    RunAttemptSuperseded,
    RunLease,
    RunState,
    RunStatus,
)
from constructicon.core.workspace import lease_id_for
from constructicon.substrate.journal._sqlite_attestations import (
    attestation_for_id,
    seal_attestation,
)
from constructicon.substrate.journal._sqlite_base import (
    _checkpoint_identity,
    _durable_datetime,
    _durable_digest,
    _durable_model,
    _durable_run_fields,
    _durable_sequence,
    _durable_sqlite_boolean,
    _durable_text,
    _path_key,
)
from constructicon.substrate.journal._sqlite_effects import (
    EFFECT_PREPARATION_FACT_FAMILY,
    StoredEffectRequest,
    effect_receipt_hash,
    effect_request_identity_from_json,
    legacy_effect_seal,
    require_effect_preparation_seal,
    seal_effect_preparation,
    stored_effect_request,
)
from constructicon.substrate.journal._sqlite_execution_facts import (
    event_fact_hash,
    event_fact_key,
    seal_checkpoint,
    seal_event,
    seal_resume_attempt_relationship,
    stored_checkpoint_for,
    stored_event_from_row,
)
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    durable_fact_seal,
    require_durable_fact_seal,
    store_durable_fact_seal,
)
from constructicon.substrate.journal._sqlite_leases import (
    LegacyLeaseSeal,
    legacy_lease_seal_for,
    validate_legacy_lease_seal_inventory,
)
from constructicon.substrate.journal._sqlite_runs import (
    retained_manifest,
    run_facts_for_id,
    run_projection_for_id,
)


def _run_mutation_row(
    connection: sqlite3.Connection,
    run_id: RunId,
) -> sqlite3.Row | None:
    """Return a mutable run row only after its complete durable world is proven."""

    try:
        facts = run_facts_for_id(connection, run_id)
    except sqlite3.Error as exc:
        raise JournalDamaged(
            f"run {run_id!r} cannot prove its durable world from the current schema"
        ) from exc
    if facts is None:
        return None
    row = connection.execute(
        "SELECT * FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise JournalDamaged(f"run {run_id!r} disappeared behind its proven world")
    return cast(sqlite3.Row, row)


class _SqliteExecutionMixin:
    def _allocate_seq(
        self,
        conn: sqlite3.Connection,
        lease: RunLease,
        *,
        expected_statuses: frozenset[RunStatus] = frozenset({RunStatus.RUNNING}),
    ) -> int:
        """THE fence: sequence allocation guarded by owner_id + epoch."""
        row = _run_mutation_row(conn, lease.run_id)
        if row is None:
            raise OwnershipLost(
                f"run {lease.run_id!r}: owner {lease.owner_id!r} epoch {lease.epoch} "
                "no longer holds the lease — the run no longer exists; stop"
            )
        fields = _durable_run_fields(row)
        owner_epoch = _durable_sequence(
            row["owner_epoch"],
            fact=f"run {fields.run_id!r} owner epoch",
            allow_zero=True,
        )
        current = _durable_sequence(
            row["next_event_seq"],
            fact=f"run {fields.run_id!r} next event sequence",
            allow_zero=True,
            kind="event sequence",
        )
        if fields.status not in expected_statuses:
            allowed = ", ".join(sorted(status.value for status in expected_statuses))
            raise ContractViolation(
                f"run {lease.run_id!r}: event allocation requires status in"
                f" [{allowed}], found {fields.status.value!r}"
            )
        if (
            fields.run_id != lease.run_id
            or fields.owner_id != lease.owner_id
            or owner_epoch != lease.epoch
        ):
            raise OwnershipLost(
                f"run {lease.run_id!r}: owner {lease.owner_id!r} epoch {lease.epoch} "
                "no longer holds the lease — a higher epoch owns this run; stop"
            )
        allocated = current + 1
        cur = conn.execute(
            "UPDATE runs SET next_event_seq = ?"
            " WHERE run_id = ? AND owner_id = ? AND owner_epoch = ?"
            " AND next_event_seq = ?",
            (allocated, lease.run_id, lease.owner_id, lease.epoch, current),
        )
        if cur.rowcount == 0:
            raise OwnershipLost(
                f"run {lease.run_id!r}: owner {lease.owner_id!r} epoch {lease.epoch} "
                "no longer holds the lease — a higher epoch owns this run; stop"
            )
        return allocated

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        run_id: RunId,
        seq: int,
        kind: str,
        path: ExecutionPath | None,
        payload: dict[str, Any] | None,
        *,
        created_at: datetime | None = None,
    ) -> JournalEvent:
        observed_at = created_at if created_at is not None else self._now()
        conn.execute(
            "INSERT INTO events (run_id, seq, kind, path_json, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                seq,
                kind,
                canonical_json(path.model_dump(mode="json")) if path else None,
                canonical_json(payload) if payload is not None else None,
                observed_at.isoformat(),
            ),
        )
        row = conn.execute(
            "SELECT * FROM events WHERE run_id = ? AND seq = ?",
            (run_id, seq),
        ).fetchone()
        if row is None:
            raise JournalDamaged(f"event {run_id!r}/{seq} disappeared before sealing")
        seal_event(conn, row)
        seal_resume_attempt_relationship(conn, row)
        return stored_event_from_row(conn, row)

    def claim_run(
        self,
        run_id: RunId,
        *,
        owner_id: str,
        ttl_s: float,
        expected_event_seq: int | None = None,
        expected_statuses: frozenset[RunStatus] | None = None,
    ) -> RunLease:
        from datetime import timedelta

        now = self._now()
        expires = now + timedelta(seconds=ttl_s)
        with self._txn() as conn:
            row = _run_mutation_row(conn, run_id)
            if row is None:
                raise ContractViolation(f"unknown run {run_id!r}")
            fields = _durable_run_fields(row)
            owner_epoch = _durable_sequence(
                row["owner_epoch"],
                fact=f"run {fields.run_id!r} owner epoch",
                allow_zero=True,
            )
            event_seq = _durable_sequence(
                row["next_event_seq"],
                fact=f"run {fields.run_id!r} next event sequence",
                allow_zero=True,
                kind="event sequence",
            )
            if fields.run_id != run_id:
                raise JournalDamaged(
                    f"run state for {fields.run_id!r} contradicts requested run {run_id!r}"
                )
            status = fields.status
            mismatches: list[str] = []
            if expected_event_seq is not None and event_seq != expected_event_seq:
                mismatches.append(
                    f"event sequence expected {expected_event_seq}, observed {event_seq}"
                )
            if expected_statuses is not None and status not in expected_statuses:
                expected = ", ".join(
                    item.value for item in sorted(expected_statuses, key=lambda item: item.value)
                )
                mismatches.append(f"status expected one of [{expected}], observed {status.value}")
            if mismatches:
                raise RunAttemptSuperseded(
                    f"run {run_id!r} changed before claim: {'; '.join(mismatches)}"
                )
            if status in (RunStatus.SUCCEEDED, RunStatus.CANCELLED):
                raise ContractViolation(
                    f"run {run_id!r} is terminally {status.value}; nothing to claim"
                )
            cur = conn.execute(
                "UPDATE runs SET owner_id = ?, owner_epoch = owner_epoch + 1,"
                " lease_expires_at = ?, heartbeat_at = ?, owner_pid = ?"
                " WHERE run_id = ? AND status IN (?, ?, ?, ?)"
                " AND (owner_id IS NULL"
                "      OR lease_expires_at IS NULL OR lease_expires_at <= ?)",
                (
                    owner_id,
                    expires.isoformat(),
                    now.isoformat(),
                    os.getpid(),
                    run_id,
                    RunStatus.PENDING.value,
                    RunStatus.RUNNING.value,
                    RunStatus.FAILED.value,
                    RunStatus.PARKED.value,
                    now.isoformat(),
                ),
            )
            if cur.rowcount == 0:
                raise OwnershipLost(
                    f"run {run_id!r} is owned by {fields.owner_id!r} "
                    f"(epoch {owner_epoch}, lease until "
                    f"{fields.lease_expires_at}); claim refused"
                )
            return RunLease(
                run_id=run_id,
                owner_id=owner_id,
                epoch=owner_epoch + 1,
                expires_at=expires,
            )

    def heartbeat(self, lease: RunLease, *, ttl_s: float) -> RunLease:
        from datetime import timedelta

        now = self._now()
        expires = now + timedelta(seconds=ttl_s)
        with self._txn() as conn:
            if _run_mutation_row(conn, lease.run_id) is None:
                raise OwnershipLost(
                    f"run {lease.run_id!r}: heartbeat fenced out; the run is missing"
                )
            cur = conn.execute(
                "UPDATE runs SET lease_expires_at = ?, heartbeat_at = ?"
                " WHERE run_id = ? AND owner_id = ? AND owner_epoch = ?",
                (expires.isoformat(), now.isoformat(), lease.run_id, lease.owner_id, lease.epoch),
            )
            if cur.rowcount == 0:
                raise OwnershipLost(
                    f"run {lease.run_id!r}: heartbeat fenced out at epoch {lease.epoch}"
                )
        return lease.model_copy(update={"expires_at": expires})

    def release_run(self, lease: RunLease) -> None:
        with self._txn() as conn:
            if _run_mutation_row(conn, lease.run_id) is None:
                raise OwnershipLost(f"run {lease.run_id!r}: release fenced out; the run is missing")
            cur = conn.execute(
                "UPDATE runs SET owner_id = NULL, lease_expires_at = NULL"
                " WHERE run_id = ? AND owner_id = ? AND owner_epoch = ?",
                (lease.run_id, lease.owner_id, lease.epoch),
            )
            if cur.rowcount == 0:
                raise OwnershipLost(
                    f"run {lease.run_id!r}: release fenced out at epoch {lease.epoch}"
                )

    def request_cancel(self, run_id: RunId) -> None:
        with self._txn() as conn:
            if _run_mutation_row(conn, run_id) is None:
                raise ContractViolation(f"unknown run {run_id!r}")
            updated = conn.execute(
                "UPDATE runs SET cancel_requested = 1 WHERE run_id = ?",
                (run_id,),
            )
            if updated.rowcount != 1:
                raise JournalDamaged(f"run {run_id!r} disappeared during cancellation")

    def cancel_requested(self, run_id: RunId) -> bool:
        with self._read() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return (
            _durable_sqlite_boolean(
                row["cancel_requested"],
                fact=f"run {run_id!r} cancellation flag",
            )
            if row is not None
            else False
        )

    def transition_run(
        self,
        lease: RunLease,
        *,
        expected: frozenset[RunStatus],
        target: RunStatus,
        event_kind: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._txn() as conn:
            seq = self._allocate_seq(conn, lease, expected_statuses=expected)
            placeholders = ", ".join("?" for _ in expected)
            cur = conn.execute(
                f"UPDATE runs SET status = ? WHERE run_id = ? AND status IN ({placeholders})",
                (target.value, lease.run_id, *(s.value for s in expected)),
            )
            if cur.rowcount == 0:
                current = conn.execute(
                    "SELECT status FROM runs WHERE run_id = ?", (lease.run_id,)
                ).fetchone()
                raise ContractViolation(
                    f"run {lease.run_id!r}: transition to {target.value!r} expected "
                    f"{sorted(s.value for s in expected)}, found {current['status']!r}"
                )
            self.fault_probe("transition.after_status_update")
            self._insert_event(conn, lease.run_id, seq, event_kind, None, payload)
        self.fault_probe("transition.after_commit")

    def append_event(
        self,
        lease: RunLease,
        kind: str,
        *,
        path: ExecutionPath | None = None,
        payload: dict[str, Any] | None = None,
    ) -> JournalEvent:
        with self._txn() as conn:
            seq = self._allocate_seq(conn, lease)
            return self._insert_event(conn, lease.run_id, seq, kind, path, payload)

    def record_completion(self, lease: RunLease, checkpoint: Checkpoint) -> None:
        if checkpoint.run_id != lease.run_id:
            raise ContractViolation(
                f"checkpoint for {checkpoint.run_id!r} contradicts run lease {lease.run_id!r}"
            )
        identity = _checkpoint_identity(checkpoint)
        with self._txn() as conn:
            existing = stored_checkpoint_for(
                conn,
                run_id=checkpoint.run_id,
                path=checkpoint.path,
            )
            if existing is not None:
                if _checkpoint_identity(existing) == identity:
                    return  # idempotent repetition of the same durable fact
                raise CheckpointConflict(
                    f"run {checkpoint.run_id!r} {checkpoint.path.render()}: a "
                    "different completion is already durable at this invocation"
                )
            seq = self._allocate_seq(conn, lease)
            conn.execute(
                "INSERT INTO checkpoints (run_id, path_key, identity, checkpoint_json)"
                " VALUES (?, ?, ?, ?)",
                (
                    checkpoint.run_id,
                    _path_key(checkpoint.path),
                    identity,
                    checkpoint.model_dump_json(),
                ),
            )
            stored_row = conn.execute(
                "SELECT * FROM checkpoints WHERE run_id = ? AND path_key = ?",
                (checkpoint.run_id, _path_key(checkpoint.path)),
            ).fetchone()
            if stored_row is None:
                raise JournalDamaged(
                    f"checkpoint {checkpoint.run_id!r}/{checkpoint.path.render()}"
                    " disappeared before sealing"
                )
            seal_checkpoint(conn, stored_row)
            self.fault_probe("completion.after_checkpoint_insert")
            self._insert_event(
                conn,
                checkpoint.run_id,
                seq,
                "NodeCompleted",
                checkpoint.path,
                {"input_hash": str(checkpoint.input_hash)},
            )
            self.fault_probe("completion.after_event_insert")
        self.fault_probe("completion.after_commit")

    def record_effect_prepared(
        self,
        lease: RunLease,
        request: EffectRequest,
    ) -> EffectRequest:
        """Prepare one global effect key and return its first exact request.

        Run and proof provenance deliberately do not participate in the effect
        key.  A second run asking for the same transition therefore recovers
        the first prepared request; replacing it with the contender's request
        would make one key name two receipt hashes and two authorities.
        """

        if request.run_id != lease.run_id or request.idempotency_key != _effect_request_key(
            request
        ):
            raise ContractViolation(
                f"effect request {request.idempotency_key} contradicts its run or derived identity"
            )
        with self._txn() as conn:
            fence = _run_mutation_row(conn, lease.run_id)
            if (
                fence is None
                or fence["owner_id"] != lease.owner_id
                or fence["owner_epoch"] != lease.epoch
            ):
                raise OwnershipLost(f"run {lease.run_id!r}: effect preparation fenced out")
            if request.manifest_hash != _durable_digest(
                fence["manifest_hash"],
                fact=f"run {lease.run_id!r} manifest identity",
            ):
                raise ContractViolation(
                    f"effect request {request.idempotency_key} contradicts its run manifest"
                )
            existing = _effect_row(conn, request.idempotency_key)
            if existing is not None:
                return _effect_request_from_row(existing, connection=conn).request
            _require_no_channel_send_fact(conn, request)
            conn.execute(
                "INSERT INTO effects"
                " (idempotency_key, run_id, request_json, prepared_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    str(request.idempotency_key),
                    lease.run_id,
                    request.model_dump_json(),
                    self._now_iso(),
                ),
            )
            prepared = conn.execute(
                "SELECT * FROM effects WHERE idempotency_key = ?",
                (str(request.idempotency_key),),
            ).fetchone()
            if prepared is None:
                raise JournalDamaged(
                    f"effect {request.idempotency_key} disappeared during preparation"
                )
            seal_effect_preparation(conn, prepared)
            stored = _effect_request_from_row(prepared, connection=conn)
            if canonical_json(stored.request) != canonical_json(request):
                raise JournalDamaged(
                    f"effect {request.idempotency_key} preparation changed while committing"
                )
        self.fault_probe("effect.after_prepared_commit")
        return stored.request

    def record_effect_outcome(
        self,
        lease: RunLease,
        request: EffectRequest,
        receipt: EffectReceipt,
        event_kind: str,
    ) -> Literal["recorded", "already_recorded"]:
        if request.idempotency_key != _effect_request_key(
            request
        ) or receipt.request_hash != effect_request_hash(request):
            raise ContractViolation(
                f"effect outcome {request.idempotency_key} contradicts its request identity"
            )
        expected_event_kind = _effect_event_kind(receipt)
        if event_kind not in {expected_event_kind, "EffectReconciled"}:
            raise ContractViolation(
                f"effect outcome {request.idempotency_key} status {receipt.status!r}"
                f" cannot write {event_kind!r}"
            )
        self.fault_probe("effect.before_receipt_txn")
        with self._txn() as conn:
            existing = _effect_row(conn, request.idempotency_key)
            if existing is None:
                raise JournalDamaged(f"effect {request.idempotency_key} has no durable preparation")
            stored = _effect_request_from_row(existing, connection=conn)
            if canonical_json(stored.request) != canonical_json(request):
                raise JournalDamaged(
                    f"effect {request.idempotency_key} outcome contradicts its "
                    "canonical preparation"
                )
            if existing["receipt_json"] is not None:
                prior = _effect_receipt_from_row(existing, stored)
                if canonical_json(prior) == canonical_json(receipt):
                    return "already_recorded"
                raise JournalDamaged(
                    f"effect {request.idempotency_key} already has a different receipt"
                )
            seq = self._allocate_seq(conn, lease)
            observed_at = self._now()
            conn.execute(
                "UPDATE effects SET receipt_json = ?, receipted_at = ?,"
                " outcome_run_id = ?, outcome_event_seq = ?"
                " WHERE idempotency_key = ?",
                (
                    receipt.model_dump_json(),
                    observed_at.isoformat(),
                    lease.run_id,
                    seq,
                    str(request.idempotency_key),
                ),
            )
            self.fault_probe("effect.after_receipt_update")
            self._insert_event(
                conn,
                lease.run_id,
                seq,
                event_kind,
                request.path,
                _effect_outcome_payload(request, receipt),
                created_at=observed_at,
            )
        self.fault_probe("effect.after_commit")
        return "recorded"

    def run_state(self, run_id: RunId) -> RunState | None:
        with self._read() as conn:
            projection = run_projection_for_id(conn, run_id, observe=self._now)
            if projection is None:
                return None
            record, _world, _event_seq, _event_kind = projection
            return RunState(
                status=record.status,
                liveness=record.liveness,
                owner_id=record.owner_id,
                lease_expires_at=record.lease_expires_at,
            )

    def run_manifest_hash(self, run_id: RunId) -> Digest | None:
        with self._read() as conn:
            projection = run_facts_for_id(conn, run_id)
            if projection is None:
                return None
            world, _event_seq, _event_kind = projection
            return world.manifest.manifest_hash

    def run_inputs(self, run_id: RunId) -> dict[str, Any] | None:
        with self._read() as conn:
            projection = run_facts_for_id(conn, run_id)
            if projection is None:
                return None
            world, _event_seq, _event_kind = projection
            return world.inputs

    def load_manifest_json(self, manifest_hash: Digest) -> str | None:
        with self._read() as conn:
            stored = retained_manifest(
                conn,
                manifest_hash=manifest_hash,
                fact=f"manifest {manifest_hash}",
            )
            if stored is None:
                return None
            _manifest, manifest_json = stored
            return manifest_json

    def events(self, run_id: RunId, *, after_seq: int = 0, limit: int = 100) -> list[JournalEvent]:
        with self._read() as conn:
            projection = run_facts_for_id(conn, run_id)
            if projection is None:
                return []
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?",
                (run_id, after_seq, limit),
            ).fetchall()
            events = [stored_event_from_row(conn, row) for row in rows]
            if any(event.run_id != run_id for event in events):
                raise JournalDamaged(
                    f"event page for run {run_id!r} contradicts its requested identity"
                )
            return events

    def checkpoint(self, run_id: RunId, path: ExecutionPath) -> Checkpoint | None:
        with self._read() as conn:
            return stored_checkpoint_for(conn, run_id=run_id, path=path)

    def receipt_for(self, idempotency_key: Digest) -> EffectReceipt | None:
        with self._read() as conn:
            row = _effect_row(conn, idempotency_key)
            if row is None:
                return None
            stored = _effect_request_from_row(row, connection=conn)
            if stored.request.idempotency_key != idempotency_key:
                raise JournalDamaged(
                    f"effect row {idempotency_key} contradicts the requested identity"
                )
            if row["receipt_json"] is None:
                return None
            return _effect_receipt_from_row(row, stored)

    def record_capability_lease(self, lease: RunLease, capability_lease: CapabilityLease) -> None:
        if (
            capability_lease.run_id != lease.run_id
            or capability_lease.acquisition_epoch != lease.epoch
            or capability_lease.lease_id
            != lease_id_for(
                capability_lease.run_id,
                capability_lease.path,
                capability_lease.binding_id,
            )
            or capability_lease.lifetime != "invocation"
            or capability_lease.state != "active"
            or capability_lease.disposition is not None
        ):
            raise ContractViolation(
                f"capability lease {capability_lease.lease_id!r} contradicts "
                f"run lease {lease.run_id!r} epoch {lease.epoch}"
            )
        with self._txn() as conn:
            existing = _capability_lease_row(
                conn,
                lease_id=capability_lease.lease_id,
                acquisition_epoch=capability_lease.acquisition_epoch,
            )
            if existing is not None:
                stored = _capability_lease_from_row(
                    existing,
                    connection=conn,
                    expected_lease_id=capability_lease.lease_id,
                    expected_acquisition_epoch=capability_lease.acquisition_epoch,
                )
                if stored == capability_lease:
                    return  # idempotent re-acquire after a mid-node crash
                raise CheckpointConflict(
                    f"capability lease {capability_lease.lease_id!r} epoch "
                    f"{capability_lease.acquisition_epoch} already recorded "
                    "with different content"
                )
            seq = self._allocate_seq(conn, lease)
            observed_at = self._now()
            now = observed_at.isoformat()
            conn.execute(
                "INSERT INTO capability_leases (lease_id, acquisition_epoch,"
                " run_id, binding_id, scope_json, lifetime, state, disposition,"
                " resource_ref, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    capability_lease.lease_id,
                    capability_lease.acquisition_epoch,
                    capability_lease.run_id,
                    capability_lease.binding_id,
                    canonical_json(capability_lease.path.model_dump(mode="json")),
                    capability_lease.lifetime,
                    capability_lease.state,
                    capability_lease.disposition,
                    capability_lease.resource_ref,
                    now,
                    now,
                ),
            )
            self._insert_event(
                conn,
                lease.run_id,
                seq,
                "LeaseAcquired",
                None,
                {
                    "lease_id": capability_lease.lease_id,
                    "acquisition_epoch": capability_lease.acquisition_epoch,
                    "binding": capability_lease.binding_id,
                    "resource_ref": capability_lease.resource_ref,
                    "observed_at": now,
                },
                created_at=observed_at,
            )
        self.fault_probe("lease.after_record_commit")

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
        with self._txn() as conn:
            row = _capability_lease_row(
                conn,
                lease_id=lease_id,
                acquisition_epoch=acquisition_epoch,
            )
            if row is None:
                raise ContractViolation(
                    f"capability lease {lease_id!r} epoch {acquisition_epoch} is not recorded"
                )
            stored = _capability_lease_from_row(
                row,
                connection=conn,
                expected_run_id=lease.run_id,
                expected_lease_id=lease_id,
                expected_acquisition_epoch=acquisition_epoch,
            )
            if stored.state == target and stored.disposition == disposition:
                return  # idempotent at-target: crash-interrupted closure re-runs
            if stored.state not in expected:
                raise ContractViolation(
                    f"capability lease {lease_id!r}: transition to {target!r} "
                    f"expected {sorted(expected)}, found {stored.state!r}"
                )
            legacy_seal = legacy_lease_seal_for(conn, row)
            seq = self._allocate_seq(conn, lease)
            observed_at = self._now()
            observed_at_iso = observed_at.isoformat()
            conn.execute(
                "UPDATE capability_leases SET state = ?, disposition = ?,"
                " updated_at = ? WHERE lease_id = ? AND acquisition_epoch = ?",
                (target, disposition, observed_at_iso, lease_id, acquisition_epoch),
            )
            payload: dict[str, Any] = {
                "lease_id": lease_id,
                "acquisition_epoch": acquisition_epoch,
                "from": stored.state,
                "to": target,
                "disposition": disposition,
                "observed_at": observed_at_iso,
            }
            if legacy_seal is not None:
                payload["legacy_base_hash"] = str(legacy_seal.base_hash)
            self._insert_event(
                conn,
                lease.run_id,
                seq,
                "LeaseTransition",
                None,
                payload,
                created_at=observed_at,
            )
        self.fault_probe("lease.after_transition_commit")

    def capability_leases(self, run_id: RunId) -> list[CapabilityLease]:
        with self._read() as conn:
            rows = _capability_lease_rows(conn, run_id=run_id)
            return [
                _capability_lease_from_row(
                    row,
                    connection=conn,
                    expected_run_id=run_id,
                )
                for row in rows
            ]

    def mint_attestation(self, lease: RunLease, draft: AttestationDraft) -> Attestation:
        with self._txn() as conn:
            fence = _run_mutation_row(conn, lease.run_id)
            if (
                fence is None
                or fence["owner_id"] != lease.owner_id
                or fence["owner_epoch"] != lease.epoch
            ):
                raise OwnershipLost(f"run {lease.run_id!r}: attestation minting fenced out")
            if draft.manifest_hash != _durable_digest(
                fence["manifest_hash"],
                fact=f"run {lease.run_id!r} manifest identity",
            ):
                raise ContractViolation(
                    f"run {lease.run_id!r}: attestation contradicts its run manifest"
                )
            if draft.action == "send" and (
                not isinstance(draft.subject, ChannelSendSubject)
                or draft.subject.run_id != lease.run_id
            ):
                raise ContractViolation(f"run {lease.run_id!r}: send attestation names another run")
            stored = self._stored_attestation_for_draft(
                conn,
                draft,
                created_by_run=lease.run_id,
            )
            if stored is None:
                attestation = Attestation(
                    attestation_id=attestation_id_for(draft),
                    created_by_run=lease.run_id,
                    created_at=self._now(),
                    **draft.model_dump(),
                )
                self._insert_attestation(conn, attestation)
            else:
                attestation = stored
        self.fault_probe("attestation.after_commit")
        return attestation

    def mint_policy_attestation(self, draft: AttestationDraft) -> Attestation:
        if draft.action != "promote" or not isinstance(
            draft.subject,
            ComponentProofSubject,
        ):
            raise ContractViolation(
                "run-less policy attestations authorize component promotion only"
            )
        with self._txn() as conn:
            stored = self._stored_attestation_for_draft(
                conn,
                draft,
                created_by_run=None,
            )
            if stored is None:
                attestation = Attestation(
                    attestation_id=attestation_id_for(draft),
                    created_by_run=None,
                    created_at=self._now(),
                    **draft.model_dump(),
                )
                self._insert_attestation(conn, attestation)
            else:
                attestation = stored
        return attestation

    @staticmethod
    def _stored_attestation_for_draft(
        conn: sqlite3.Connection,
        draft: AttestationDraft,
        *,
        created_by_run: RunId | None,
    ) -> Attestation | None:
        """Return the exact prior mint before a retry observes wall time."""

        attestation_id = attestation_id_for(draft)
        stored = attestation_for_id(conn, attestation_id)
        if stored is None:
            return None
        expected = Attestation(
            attestation_id=attestation_id,
            created_by_run=created_by_run,
            created_at=stored.created_at,
            **draft.model_dump(),
        )
        if stored != expected:
            raise JournalDamaged(
                f"attestation {attestation_id!r} already minted with different content"
            )
        return stored

    @staticmethod
    def _insert_attestation(conn: sqlite3.Connection, attestation: Attestation) -> None:
        prior = attestation_for_id(conn, attestation.attestation_id)
        payload = attestation.model_dump_json()
        if prior is not None:
            # the id is content-derived, so identity means identical drafts;
            # only provenance timing may differ across a crash-and-retry
            if prior.model_copy(update={"created_at": attestation.created_at}) == attestation:
                return
            raise JournalDamaged(
                f"attestation {attestation.attestation_id!r} already minted with different content"
            )
        conn.execute(
            "INSERT INTO attestations (attestation_id, attestation_json) VALUES (?, ?)",
            (attestation.attestation_id, payload),
        )
        row = conn.execute(
            "SELECT * FROM attestations WHERE attestation_id = ?",
            (attestation.attestation_id,),
        ).fetchone()
        assert row is not None
        seal_attestation(conn, row)

    def load_attestation(self, attestation_id: str) -> Attestation | None:
        with self._read() as conn:
            return attestation_for_id(conn, attestation_id)


def _effect_request_key(request: EffectRequest) -> Digest:
    return effect_idempotency_key(
        request.manifest_hash,
        request.path,
        request.kind,
        request.subject,
        mode=request.mode,
    )


def _require_no_channel_send_fact(
    connection: sqlite3.Connection,
    request: EffectRequest,
) -> None:
    """Refuse to recreate a preparation behind its already-applied channel fact."""

    if request.kind != CHANNEL_SEND_EFFECT:
        return
    try:
        intent = ChannelSendIntent.model_validate(request.subject)
        if canonical_json(intent) != canonical_json(request.subject):
            raise ValueError("channel send intent parsing is not lossless")
    except (TypeError, ValueError, ValidationError) as exc:
        raise ContractViolation("channel send effect preparation has no exact intent") from exc
    applied = connection.execute(
        "SELECT 1 FROM channel_messages WHERE message_id = ? LIMIT 1",
        (str(intent.message_id),),
    ).fetchone()
    if applied is not None:
        raise JournalDamaged(
            f"channel send effect {request.idempotency_key} has a durable message"
            " without its preparation"
        )


_EFFECT_OUTCOME_EVENT_KINDS = (
    "EffectCommitted",
    "EffectRejected",
    "EffectSimulated",
    "EffectUnresolved",
    "EffectReconciled",
)
LEGACY_EFFECT_OUTCOME_FACT_FAMILY = "legacy_effect_outcome_pre_v7"


def _effect_event_kind(receipt: EffectReceipt) -> str:
    return {
        "committed": "EffectCommitted",
        "rejected": "EffectRejected",
        "simulated": "EffectSimulated",
        "unknown": "EffectUnresolved",
    }[receipt.status]


def _effect_outcome_payload(
    request: EffectRequest,
    receipt: EffectReceipt,
) -> dict[str, Any]:
    return {
        "kind": request.kind,
        "idempotency_key": str(request.idempotency_key),
        "request_hash": str(effect_request_hash(request)),
        "receipt_hash": str(effect_receipt_hash(receipt)),
    }


def _effect_key_from_request_json(raw: object) -> str | None:
    """SQLite UDF: derive an effect key only from an exact request payload."""

    try:
        return str(effect_request_identity_from_json(raw))
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return None


def _effect_key_from_event_payload(raw: object) -> str | None:
    """SQLite UDF: recover a current outcome identity from its exact payload."""

    try:
        payload = parse_json_value(_durable_text(raw, fact="effect outcome payload"))
        if not isinstance(payload, dict):
            return None
        key = payload.get("idempotency_key")
        if type(key) is not str:
            return None
        return str(Digest(key))
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return None


def _register_effect_identity_functions(connection: sqlite3.Connection) -> None:
    connection.create_function(
        "constructicon_effect_key",
        1,
        _effect_key_from_request_json,
        deterministic=True,
    )
    connection.create_function(
        "constructicon_effect_event_key",
        1,
        _effect_key_from_event_payload,
        deterministic=True,
    )


def _legacy_effect_outcome_fact_hash(row: sqlite3.Row) -> Digest:
    return durable_fact_hash(
        LEGACY_EFFECT_OUTCOME_FACT_FAMILY,
        {"event_hash": str(event_fact_hash(row))},
    )


def seal_legacy_effect_outcomes(connection: sqlite3.Connection) -> None:
    """Classify only the opaque effect outcomes observed during migration."""

    placeholders = ", ".join("?" for _kind in _EFFECT_OUTCOME_EVENT_KINDS)
    rows = connection.execute(
        f"SELECT * FROM events WHERE kind IN ({placeholders})",
        _EFFECT_OUTCOME_EVENT_KINDS,
    ).fetchall()
    for row in rows:
        if _effect_key_from_event_payload(row["payload"]) is not None:
            continue
        event = stored_event_from_row(connection, row)
        key = event_fact_key(event.run_id, event.seq)
        store_durable_fact_seal(
            connection,
            family=LEGACY_EFFECT_OUTCOME_FACT_FAMILY,
            fact_key=key,
            selector=key,
            fact_hash=_legacy_effect_outcome_fact_hash(row),
        )


def _effect_event_rows(
    connection: sqlite3.Connection,
    key: Digest,
) -> list[sqlite3.Row]:
    _register_effect_identity_functions(connection)
    return connection.execute(
        "SELECT * FROM events WHERE constructicon_effect_event_key(payload) = ? LIMIT 2",
        (str(key),),
    ).fetchall()


def _effect_row(
    connection: sqlite3.Connection,
    key: Digest,
) -> sqlite3.Row | None:
    """Select by relational or request-derived identity before deciding absence."""

    _register_effect_identity_functions(connection)
    rows = connection.execute(
        "SELECT * FROM effects WHERE idempotency_key = ?"
        " OR constructicon_effect_key(request_json) = ?"
        " OR constructicon_effect_key(request_json) IS NULL LIMIT 2",
        (str(key), str(key)),
    ).fetchall()
    if len(rows) > 1:
        raise JournalDamaged(f"effect {key} has contradictory durable selectors")
    if not rows:
        legacy_terminal = connection.execute(
            "SELECT 1 FROM legacy_effect_seals WHERE idempotency_key = ? LIMIT 1",
            (str(key),),
        ).fetchone()
        preparation = durable_fact_seal(
            connection,
            family=EFFECT_PREPARATION_FACT_FAMILY,
            fact_key=str(key),
            selector=str(key),
        )
        if legacy_terminal is not None or _effect_event_rows(connection, key):
            raise JournalDamaged(f"effect {key} has durable outcome proof without its row")
        if preparation is not None:
            raise JournalDamaged(
                f"effect {key} has no durable preparation row; its positive seal remains"
            )
        return None
    return cast(sqlite3.Row, rows[0])


def _effect_request_from_row(
    row: sqlite3.Row,
    *,
    connection: sqlite3.Connection,
) -> StoredEffectRequest:
    """Decode and prove the identity and lifecycle of one durable effect."""

    key = _durable_text(
        row["idempotency_key"],
        fact=f"effect key {row['idempotency_key']!r}",
    )
    try:
        _durable_datetime(
            row["prepared_at"],
            fact=f"effect {key!r} preparation time",
        )
        if (row["receipt_json"] is None) != (row["receipted_at"] is None):
            raise ValueError("effect receipt bytes and observation time disagree")
        if row["receipted_at"] is not None:
            _durable_datetime(
                row["receipted_at"],
                fact=f"effect {key!r} receipt time",
            )
        stored_run_id = _durable_text(
            row["run_id"],
            fact=f"effect {key!r} run identity",
        )
        run_id = RunId(stored_run_id)
        run_facts = run_facts_for_id(connection, run_id)
        if run_facts is None:
            raise ValueError("effect names a missing retained run world")
        world, _event_seq, _event_kind = run_facts
        stored = stored_effect_request(
            row["request_json"],
            run_id=run_id,
            manifest_hash=world.manifest.manifest_hash,
        )
        request = stored.request
        if str(request.idempotency_key) != key:
            raise ValueError("effect key column and request payload disagree")
        if str(request.run_id) != stored_run_id:
            raise ValueError("effect run column and request payload disagree")
        if request.idempotency_key != _effect_request_key(request):
            raise ValueError("effect request does not carry its derived identity")
        if (
            request.attestation_id is not None
            and attestation_for_id(connection, request.attestation_id) is None
        ):
            raise ValueError("effect request names a missing retained attestation")
        require_effect_preparation_seal(connection, row)
        receipt = _effect_receipt_from_row(row, stored) if row["receipt_json"] is not None else None
        _validate_effect_lifecycle(connection, row, stored, receipt)
        return stored
    except JournalDamaged:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(f"effect row {key!r} is not a valid durable request") from exc


def validate_effect_fact_inventory(connection: sqlite3.Connection) -> int:
    """Project the complete retained effect graph in both directions."""

    retained: set[str] = set()
    for row in connection.execute("SELECT * FROM effects").fetchall():
        stored = _effect_request_from_row(row, connection=connection)
        retained.add(str(stored.request.idempotency_key))

    placeholders = ", ".join("?" for _kind in _EFFECT_OUTCOME_EVENT_KINDS)
    legacy_rows: set[str] = set()
    for row in connection.execute(
        f"SELECT * FROM events WHERE kind IN ({placeholders})",
        _EFFECT_OUTCOME_EVENT_KINDS,
    ).fetchall():
        event = stored_event_from_row(connection, row)
        key = _effect_key_from_event_payload(row["payload"])
        event_key = event_fact_key(event.run_id, event.seq)
        legacy = durable_fact_seal(
            connection,
            family=LEGACY_EFFECT_OUTCOME_FACT_FAMILY,
            fact_key=event_key,
            selector=event_key,
        )
        if key is None:
            if legacy is None:
                raise JournalDamaged(
                    f"current effect outcome event {event.run_id!r}/{event.seq}"
                    " has no exact effect identity"
                )
            require_durable_fact_seal(
                connection,
                family=LEGACY_EFFECT_OUTCOME_FACT_FAMILY,
                fact_key=event_key,
                selector=event_key,
                fact_hash=_legacy_effect_outcome_fact_hash(row),
            )
            legacy_rows.add(event_key)
            continue
        if legacy is not None:
            raise JournalDamaged(
                f"effect outcome event {event.run_id!r}/{event.seq}"
                " has contradictory provenance eras"
            )
        if key not in retained:
            raise JournalDamaged(
                f"effect outcome event {event.run_id!r}/{event.seq}"
                " has no exact retained effect"
            )
    legacy_seals = {
        _durable_text(row["fact_key"], fact="legacy effect outcome fact key")
        for row in connection.execute(
            "SELECT fact_key FROM durable_fact_seals WHERE family = ?",
            (LEGACY_EFFECT_OUTCOME_FACT_FAMILY,),
        ).fetchall()
    }
    if legacy_seals != legacy_rows:
        raise JournalDamaged(
            "legacy effect outcome seal inventory has an orphan or missing fact"
        )
    return len(legacy_rows)


def _effect_receipt_from_row(
    row: sqlite3.Row,
    stored: StoredEffectRequest,
) -> EffectReceipt:
    """Decode one receipt only when it proves the stored request it closes."""

    key = _durable_text(
        row["idempotency_key"],
        fact=f"effect key {row['idempotency_key']!r}",
    )
    try:
        raw_receipt = parse_json_value(row["receipt_json"])
        receipt = EffectReceipt.model_validate(raw_receipt)
        if canonical_json(raw_receipt) != canonical_json(receipt):
            raise ValueError("effect receipt parsing is not lossless")
        expected_hash = (
            stored.persisted_request_hash
            if row["outcome_run_id"] is None
            else effect_request_hash(stored.request)
        )
        if receipt.request_hash != expected_hash:
            raise ValueError("effect receipt does not name its prepared request")
        return receipt
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(f"effect row {key!r} has no valid durable receipt") from exc


def _validate_effect_lifecycle(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    stored: StoredEffectRequest,
    receipt: EffectReceipt | None,
) -> None:
    """Require exactly one prepared, current-terminal, or sealed-legacy shape."""

    request = stored.request
    key = request.idempotency_key
    raw_outcome_run_id = row["outcome_run_id"]
    raw_outcome_event_seq = row["outcome_event_seq"]
    if (raw_outcome_run_id is None) != (raw_outcome_event_seq is None):
        raise JournalDamaged(f"effect {key} has a torn outcome event pointer")
    outcome_pointer: tuple[RunId, int] | None = None
    if raw_outcome_run_id is not None:
        try:
            outcome_pointer = (
                RunId(
                    _durable_text(
                        raw_outcome_run_id,
                        fact=f"effect {key} outcome run identity",
                    )
                ),
                _durable_sequence(
                    raw_outcome_event_seq,
                    fact=f"effect {key} outcome event sequence",
                ),
            )
        except (TypeError, ValueError) as exc:
            raise JournalDamaged(f"effect {key} has an invalid outcome event pointer") from exc

    seal_row = connection.execute(
        "SELECT * FROM legacy_effect_seals WHERE idempotency_key = ?",
        (str(key),),
    ).fetchone()
    sealed = seal_row is not None
    if seal_row is not None:
        sealed_key = _durable_text(
            seal_row["idempotency_key"],
            fact=f"legacy effect {key} sealed identity",
        )
        sealed_hash = _durable_digest(
            seal_row["terminal_fact_hash"],
            fact=f"legacy effect {key} terminal seal",
        )
        if sealed_key != str(key) or sealed_hash != legacy_effect_seal(row):
            raise JournalDamaged(f"legacy effect {key} contradicts its terminal seal")

    event_rows = _effect_event_rows(connection, key)
    if len(event_rows) > 1:
        raise JournalDamaged(f"effect {key} has duplicate current outcome events")
    if receipt is None:
        if outcome_pointer is not None or sealed or event_rows:
            raise JournalDamaged(f"effect {key} prepared lifecycle has terminal proof")
        return
    if sealed:
        if outcome_pointer is not None or event_rows:
            raise JournalDamaged(f"legacy effect {key} mixes terminal provenance eras")
        return
    if outcome_pointer is None:
        raise JournalDamaged(f"effect {key} terminal lifecycle has no exact event pointer")
    receipted_at = _durable_datetime(
        row["receipted_at"],
        fact=f"effect {key} receipt time",
    )
    outcome_run_id, outcome_event_seq = outcome_pointer
    event_row = connection.execute(
        "SELECT * FROM events WHERE run_id = ? AND seq = ?",
        (outcome_run_id, outcome_event_seq),
    ).fetchone()
    if event_row is None:
        raise JournalDamaged(f"effect {key} outcome event pointer is orphaned")
    event = stored_event_from_row(connection, event_row)
    expected_kinds = {_effect_event_kind(receipt), "EffectReconciled"}
    if (
        len(event_rows) != 1
        or event_rows[0]["run_id"] != event_row["run_id"]
        or event_rows[0]["seq"] != event_row["seq"]
        or event.run_id != outcome_run_id
        or event.seq != outcome_event_seq
        or event.kind not in expected_kinds
        or event.path != request.path
        or event.created_at != receipted_at
        or canonical_json(event.payload)
        != canonical_json(_effect_outcome_payload(request, receipt))
    ):
        raise JournalDamaged(f"effect {key} contradicts its exact outcome event")


_LEASE_EVENT_KINDS = ("LeaseAcquired", "LeaseTransition")


def _lease_event_identity(lease_id: str, acquisition_epoch: int) -> str:
    return canonical_json(
        {
            "lease_id": lease_id,
            "acquisition_epoch": acquisition_epoch,
        }
    )


def _lease_event_identity_from_payload(raw: object) -> str | None:
    """SQLite UDF: recover the exact lease identity carried by an event."""

    try:
        payload = parse_json_value(_durable_text(raw, fact="capability lease event payload"))
        if not isinstance(payload, dict):
            return None
        lease_id = payload.get("lease_id")
        acquisition_epoch = payload.get("acquisition_epoch")
        if type(lease_id) is not str or type(acquisition_epoch) is not int:
            return None
        if acquisition_epoch <= 0:
            return None
        return _lease_event_identity(lease_id, acquisition_epoch)
    except (JournalDamaged, TypeError, ValueError):
        return None


def _lease_identity_from_columns(
    lease_id: object,
    acquisition_epoch: object,
) -> str | None:
    if type(lease_id) is not str or type(acquisition_epoch) is not int:
        return None
    if acquisition_epoch <= 0:
        return None
    return _lease_event_identity(lease_id, acquisition_epoch)


def _register_lease_identity_functions(connection: sqlite3.Connection) -> None:
    connection.create_function(
        "constructicon_lease_event_identity",
        1,
        _lease_event_identity_from_payload,
        deterministic=True,
    )
    connection.create_function(
        "constructicon_lease_identity",
        2,
        _lease_identity_from_columns,
        deterministic=True,
    )


def _capability_lease_row(
    connection: sqlite3.Connection,
    *,
    lease_id: str,
    acquisition_epoch: int,
) -> sqlite3.Row | None:
    """Resolve one lease through its row and independent acquisition proofs."""

    _register_lease_identity_functions(connection)
    identity = _lease_event_identity(lease_id, acquisition_epoch)
    rows = connection.execute(
        "SELECT * FROM capability_leases"
        " WHERE (lease_id = ? AND acquisition_epoch = ?)"
        " OR constructicon_lease_identity(lease_id, acquisition_epoch) = ?"
        " LIMIT 2",
        (lease_id, acquisition_epoch, identity),
    ).fetchall()
    if len(rows) > 1:
        raise JournalDamaged(
            f"capability lease {lease_id!r} epoch {acquisition_epoch}"
            " has contradictory durable selectors"
        )
    if rows:
        return cast(sqlite3.Row, rows[0])
    lifecycle = connection.execute(
        "SELECT 1 FROM events WHERE kind IN (?, ?)"
        " AND constructicon_lease_event_identity(payload) = ? LIMIT 1",
        (*_LEASE_EVENT_KINDS, identity),
    ).fetchone()
    legacy = connection.execute(
        "SELECT 1 FROM legacy_capability_lease_seals"
        " WHERE lease_id = ? AND acquisition_epoch = ? LIMIT 1",
        (lease_id, acquisition_epoch),
    ).fetchone()
    if lifecycle is not None or legacy is not None:
        raise JournalDamaged(
            f"capability lease {lease_id!r} epoch {acquisition_epoch}"
            " has durable lifecycle proof without its row"
        )
    return None


def _capability_lease_rows(
    connection: sqlite3.Connection,
    *,
    run_id: RunId,
) -> list[sqlite3.Row]:
    """Select leases by row, current acquisition proof, or legacy seal owner."""

    _register_lease_identity_functions(connection)
    orphaned_acquisition = connection.execute(
        "SELECT 1 FROM events AS acquired"
        " LEFT JOIN capability_leases AS leases"
        " ON constructicon_lease_event_identity(acquired.payload)"
        " = constructicon_lease_identity("
        " leases.lease_id, leases.acquisition_epoch)"
        " WHERE acquired.kind = 'LeaseAcquired' AND acquired.run_id = ?"
        " AND leases.lease_id IS NULL LIMIT 1",
        (run_id,),
    ).fetchone()
    orphaned_seal = connection.execute(
        "SELECT 1 FROM legacy_capability_lease_seals AS sealed"
        " LEFT JOIN capability_leases AS leases"
        " ON leases.lease_id = sealed.lease_id"
        " AND leases.acquisition_epoch = sealed.acquisition_epoch"
        " WHERE sealed.run_id = ? AND leases.lease_id IS NULL LIMIT 1",
        (run_id,),
    ).fetchone()
    if orphaned_acquisition is not None or orphaned_seal is not None:
        raise JournalDamaged(
            f"run {run_id!r} has durable capability lease proof without its exact row;"
            " identity or acquisition epoch is damaged"
        )
    return connection.execute(
        "SELECT DISTINCT leases.* FROM capability_leases AS leases"
        " LEFT JOIN events AS acquired"
        " ON acquired.kind = 'LeaseAcquired'"
        " AND constructicon_lease_event_identity(acquired.payload)"
        " = constructicon_lease_identity("
        " leases.lease_id, leases.acquisition_epoch)"
        " LEFT JOIN legacy_capability_lease_seals AS sealed"
        " ON sealed.lease_id = leases.lease_id"
        " AND sealed.acquisition_epoch = leases.acquisition_epoch"
        " WHERE leases.run_id = ? OR acquired.run_id = ? OR sealed.run_id = ?"
        " ORDER BY leases.created_at ASC, leases.lease_id ASC",
        (run_id, run_id, run_id),
    ).fetchall()


def _validate_capability_lease_history(
    connection: sqlite3.Connection,
    lease: CapabilityLease,
    *,
    legacy_seal: LegacyLeaseSeal | None,
    created_at: datetime,
    updated_at: datetime,
    updated_at_text: str,
) -> None:
    """Prove a lease row is the final state of its exact append-only event chain."""

    _register_lease_identity_functions(connection)
    identity = _lease_event_identity(lease.lease_id, lease.acquisition_epoch)
    rows = connection.execute(
        "SELECT * FROM events WHERE kind IN (?, ?)"
        " AND constructicon_lease_event_identity(payload) = ?"
        " ORDER BY seq ASC",
        (*_LEASE_EVENT_KINDS, identity),
    ).fetchall()
    events = [stored_event_from_row(connection, row) for row in rows]
    if legacy_seal is not None:
        legacy_state = legacy_seal.state
        legacy_disposition = legacy_seal.disposition
        current_events = [
            event
            for event in events
            if isinstance(event.payload, dict) and "legacy_base_hash" in event.payload
        ]
        if not current_events and updated_at_text != legacy_seal.updated_at:
            raise JournalDamaged(
                f"capability lease {lease.lease_id!r} changed its sealed lifecycle"
            )
        for event in current_events:
            if event.kind != "LeaseTransition":
                raise JournalDamaged(
                    f"capability lease {lease.lease_id!r} has a contradictory "
                    "post-migration acquisition event"
                )
            payload = event.payload
            assert isinstance(payload, dict)
            target = payload.get("to")
            next_disposition = payload.get("disposition")
            expected_payload = {
                "lease_id": lease.lease_id,
                "acquisition_epoch": lease.acquisition_epoch,
                "from": legacy_state,
                "to": target,
                "disposition": next_disposition,
                "observed_at": event.created_at.isoformat(),
                "legacy_base_hash": str(legacy_seal.base_hash),
            }
            if (
                event.run_id != lease.run_id
                or event.path is not None
                or target not in {"active", "closed", "lost"}
                or next_disposition not in {None, "released", "discarded"}
                or canonical_json(payload) != canonical_json(expected_payload)
            ):
                raise JournalDamaged(
                    f"capability lease {lease.lease_id!r} has a contradictory "
                    "post-migration transition event"
                )
            legacy_state = target
            legacy_disposition = next_disposition
        if (
            lease.state != legacy_state
            or lease.disposition != legacy_disposition
            or (current_events and updated_at != current_events[-1].created_at)
        ):
            raise JournalDamaged(
                f"capability lease {lease.lease_id!r} lifecycle contradicts its sealed history"
            )
        return
    if not events or events[0].kind != "LeaseAcquired":
        raise JournalDamaged(f"capability lease {lease.lease_id!r} has no exact acquisition event")
    acquired = events[0]
    acquired_payload = {
        "lease_id": lease.lease_id,
        "acquisition_epoch": lease.acquisition_epoch,
        "binding": lease.binding_id,
        "resource_ref": lease.resource_ref,
        "observed_at": acquired.created_at.isoformat(),
    }
    if (
        acquired.run_id != lease.run_id
        or acquired.path is not None
        or created_at != acquired.created_at
        or canonical_json(acquired.payload) != canonical_json(acquired_payload)
    ):
        raise JournalDamaged(
            f"capability lease {lease.lease_id!r} contradicts its acquisition event"
        )

    state = "active"
    disposition: str | None = None
    last_observed_at = acquired.created_at
    for event in events[1:]:
        if event.kind != "LeaseTransition":
            raise JournalDamaged(
                f"capability lease {lease.lease_id!r} has duplicate acquisition events"
            )
        payload = event.payload
        if not isinstance(payload, dict):
            raise JournalDamaged(
                f"capability lease {lease.lease_id!r} has invalid transition payload"
            )
        target = payload.get("to")
        next_disposition = payload.get("disposition")
        expected_payload = {
            "lease_id": lease.lease_id,
            "acquisition_epoch": lease.acquisition_epoch,
            "from": state,
            "to": target,
            "disposition": next_disposition,
            "observed_at": event.created_at.isoformat(),
        }
        if (
            event.run_id != lease.run_id
            or event.path is not None
            or target not in {"active", "closed", "lost"}
            or next_disposition not in {None, "released", "discarded"}
            or canonical_json(payload) != canonical_json(expected_payload)
        ):
            raise JournalDamaged(
                f"capability lease {lease.lease_id!r} has a contradictory transition event"
            )
        state = target
        disposition = next_disposition
        last_observed_at = event.created_at
    if lease.state != state or lease.disposition != disposition or updated_at != last_observed_at:
        raise JournalDamaged(
            f"capability lease {lease.lease_id!r} lifecycle contradicts its event chain"
        )


def _capability_lease_from_row(
    row: sqlite3.Row,
    *,
    connection: sqlite3.Connection,
    expected_run_id: RunId | None = None,
    expected_lease_id: str | None = None,
    expected_acquisition_epoch: int | None = None,
) -> CapabilityLease:
    """Project one lease row without normalizing any durable relational fact."""

    identity = f"capability lease {row['lease_id']!r} epoch {row['acquisition_epoch']!r}"
    try:
        lease_id = _durable_text(row["lease_id"], fact=f"{identity} identity")
        acquisition_epoch = _durable_sequence(
            row["acquisition_epoch"],
            fact=f"{identity} acquisition epoch",
        )
        run_id = RunId(_durable_text(row["run_id"], fact=f"{identity} run identity"))
        binding_id = _durable_text(row["binding_id"], fact=f"{identity} binding")
        lifetime = _durable_text(row["lifetime"], fact=f"{identity} lifetime")
        state = _durable_text(row["state"], fact=f"{identity} state")
        disposition = (
            _durable_text(row["disposition"], fact=f"{identity} disposition")
            if row["disposition"] is not None
            else None
        )
        resource_ref = (
            _durable_text(row["resource_ref"], fact=f"{identity} resource reference")
            if row["resource_ref"] is not None
            else None
        )
        created_at = _durable_datetime(
            row["created_at"],
            fact=f"{identity} creation time",
        )
        updated_at_text = _durable_text(
            row["updated_at"],
            fact=f"{identity} update time",
        )
        updated_at = _durable_datetime(updated_at_text, fact=f"{identity} update time")
        stored = CapabilityLease(
            lease_id=lease_id,
            acquisition_epoch=acquisition_epoch,
            run_id=run_id,
            binding_id=binding_id,
            path=_durable_model(
                ExecutionPath,
                row["scope_json"],
                fact=f"{identity} scope",
            ),
            lifetime=lifetime,
            state=state,
            disposition=disposition,
            resource_ref=resource_ref,
        )
        legacy_seal = legacy_lease_seal_for(connection, row)
        if stored.lifetime != "invocation" or (
            legacy_seal is None
            and stored.lease_id
            != lease_id_for(
                stored.run_id,
                stored.path,
                stored.binding_id,
            )
        ):
            raise ValueError("lease identity is not derived from its run, path, and binding")
        if expected_run_id is not None and stored.run_id != expected_run_id:
            raise ValueError("lease run column contradicts its query or mutation run")
        if expected_lease_id is not None and stored.lease_id != expected_lease_id:
            raise ValueError("lease identity column contradicts its selected identity")
        if (
            expected_acquisition_epoch is not None
            and stored.acquisition_epoch != expected_acquisition_epoch
        ):
            raise ValueError("lease epoch column contradicts its selected epoch")
        _validate_capability_lease_history(
            connection,
            stored,
            legacy_seal=legacy_seal,
            created_at=created_at,
            updated_at=updated_at,
            updated_at_text=updated_at_text,
        )
        return stored
    except JournalDamaged:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(f"{identity} is not a valid durable record") from exc


def validate_capability_lease_inventory(connection: sqlite3.Connection) -> None:
    """Project every lease and every event-to-lease edge through one law."""

    validate_legacy_lease_seal_inventory(connection)
    retained: set[str] = set()
    for row in connection.execute("SELECT * FROM capability_leases").fetchall():
        lease = _capability_lease_from_row(row, connection=connection)
        retained.add(_lease_event_identity(lease.lease_id, lease.acquisition_epoch))

    for row in connection.execute(
        "SELECT * FROM events WHERE kind IN (?, ?)",
        _LEASE_EVENT_KINDS,
    ).fetchall():
        event = stored_event_from_row(connection, row)
        identity = _lease_event_identity_from_payload(row["payload"])
        if identity is None or identity not in retained:
            raise JournalDamaged(
                f"capability lease event {event.run_id!r}/{event.seq}"
                " has no exact retained lease"
            )
