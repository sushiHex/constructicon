# mypy: disable-error-code="attr-defined"
"""Durable run, event, checkpoint, effect, lease, and attestation operations."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.effect import (
    Attestation,
    AttestationDraft,
    EffectReceipt,
    EffectRequest,
    attestation_id_for,
)
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import Digest, canonical_json
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
from constructicon.substrate.journal._sqlite_base import (
    _checkpoint_identity,
    _manifest_semantically_equal,
    _path_key,
)


class _SqliteExecutionMixin:
    def _allocate_seq(self, conn: sqlite3.Connection, lease: RunLease) -> int:
        """THE fence: sequence allocation guarded by owner_id + epoch."""
        cur = conn.execute(
            "UPDATE runs SET next_event_seq = next_event_seq + 1"
            " WHERE run_id = ? AND owner_id = ? AND owner_epoch = ?",
            (lease.run_id, lease.owner_id, lease.epoch),
        )
        if cur.rowcount == 0:
            raise OwnershipLost(
                f"run {lease.run_id!r}: owner {lease.owner_id!r} epoch {lease.epoch} "
                "no longer holds the lease — a higher epoch owns this run; stop"
            )
        row = conn.execute(
            "SELECT next_event_seq FROM runs WHERE run_id = ?", (lease.run_id,)
        ).fetchone()
        return int(row["next_event_seq"])

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        run_id: RunId,
        seq: int,
        kind: str,
        path: ExecutionPath | None,
        payload: dict[str, Any] | None,
    ) -> JournalEvent:
        created_at = self._now()
        conn.execute(
            "INSERT INTO events (run_id, seq, kind, path_json, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                seq,
                kind,
                canonical_json(path.model_dump(mode="json")) if path else None,
                canonical_json(payload) if payload is not None else None,
                created_at.isoformat(),
            ),
        )
        return JournalEvent(
            run_id=run_id,
            seq=seq,
            kind=kind,
            path=path,
            created_at=created_at,
            payload=payload,
        )

    def create_run(
        self,
        run_id: RunId,
        *,
        manifest_json: str,
        manifest_hash: Digest,
        input_hash: Digest,
        inputs: dict[str, Any],
    ) -> None:
        with self._txn() as conn:
            existing = conn.execute(
                "SELECT manifest_json FROM manifests WHERE manifest_hash = ?",
                (str(manifest_hash),),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO manifests (manifest_hash, manifest_json) VALUES (?, ?)",
                    (str(manifest_hash), manifest_json),
                )
            elif existing["manifest_json"] != manifest_json and not _manifest_semantically_equal(
                existing["manifest_json"], manifest_json
            ):
                raise JournalDamaged(
                    f"manifest {manifest_hash} already stored with different semantics"
                )
            run = conn.execute(
                "SELECT manifest_hash, input_hash FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is not None:
                if run["manifest_hash"] == str(manifest_hash) and run["input_hash"] == str(
                    input_hash
                ):
                    return  # idempotent
                raise CheckpointConflict(
                    f"run {run_id!r} already exists with a different manifest/inputs"
                )
            conn.execute(
                "INSERT INTO runs (run_id, manifest_hash, input_hash, inputs_json,"
                " status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    str(manifest_hash),
                    str(input_hash),
                    canonical_json(inputs),
                    RunStatus.PENDING.value,
                    self._now_iso(),
                ),
            )
        self.fault_probe("create.after_commit")

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
            row = conn.execute(
                "SELECT status, owner_id, owner_epoch, lease_expires_at,"
                " next_event_seq FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ContractViolation(f"unknown run {run_id!r}")
            status = RunStatus(row["status"])
            event_seq = int(row["next_event_seq"])
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
                    f"run {run_id!r} is owned by {row['owner_id']!r} "
                    f"(epoch {row['owner_epoch']}, lease until "
                    f"{row['lease_expires_at']}); claim refused"
                )
            epoch_row = conn.execute(
                "SELECT owner_epoch FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return RunLease(
                run_id=run_id,
                owner_id=owner_id,
                epoch=int(epoch_row["owner_epoch"]),
                expires_at=expires,
            )

    def heartbeat(self, lease: RunLease, *, ttl_s: float) -> RunLease:
        from datetime import timedelta

        now = self._now()
        expires = now + timedelta(seconds=ttl_s)
        with self._txn() as conn:
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
            conn.execute("UPDATE runs SET cancel_requested = 1 WHERE run_id = ?", (run_id,))

    def cancel_requested(self, run_id: RunId) -> bool:
        with self._read() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

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
            seq = self._allocate_seq(conn, lease)
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
        identity = _checkpoint_identity(checkpoint)
        with self._txn() as conn:
            existing = conn.execute(
                "SELECT identity FROM checkpoints WHERE run_id = ? AND path_key = ?",
                (checkpoint.run_id, _path_key(checkpoint.path)),
            ).fetchone()
            if existing is not None:
                if existing["identity"] == identity:
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

    def record_effect_prepared(self, lease: RunLease, request: EffectRequest) -> None:
        with self._txn() as conn:
            fence = conn.execute(
                "SELECT 1 FROM runs WHERE run_id = ? AND owner_id = ? AND owner_epoch = ?",
                (lease.run_id, lease.owner_id, lease.epoch),
            ).fetchone()
            if fence is None:
                raise OwnershipLost(f"run {lease.run_id!r}: effect preparation fenced out")
            conn.execute(
                "INSERT OR IGNORE INTO effects"
                " (idempotency_key, run_id, request_json, prepared_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    str(request.idempotency_key),
                    lease.run_id,
                    request.model_dump_json(),
                    self._now_iso(),
                ),
            )
        self.fault_probe("effect.after_prepared_commit")

    def record_effect_outcome(
        self,
        lease: RunLease,
        request: EffectRequest,
        receipt: EffectReceipt,
        event_kind: str,
    ) -> None:
        self.fault_probe("effect.before_receipt_txn")
        with self._txn() as conn:
            existing = conn.execute(
                "SELECT receipt_json FROM effects WHERE idempotency_key = ?",
                (str(request.idempotency_key),),
            ).fetchone()
            if existing is not None and existing["receipt_json"] is not None:
                prior = EffectReceipt.model_validate_json(existing["receipt_json"])
                if prior == receipt:
                    return  # idempotent
                raise JournalDamaged(
                    f"effect {request.idempotency_key} already has a different receipt"
                )
            seq = self._allocate_seq(conn, lease)
            conn.execute(
                "INSERT OR IGNORE INTO effects"
                " (idempotency_key, run_id, request_json, prepared_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    str(request.idempotency_key),
                    lease.run_id,
                    request.model_dump_json(),
                    self._now_iso(),
                ),
            )
            conn.execute(
                "UPDATE effects SET receipt_json = ?, receipted_at = ? WHERE idempotency_key = ?",
                (receipt.model_dump_json(), self._now_iso(), str(request.idempotency_key)),
            )
            self.fault_probe("effect.after_receipt_update")
            self._insert_event(
                conn,
                lease.run_id,
                seq,
                event_kind,
                request.path,
                {"kind": request.kind},
            )
        self.fault_probe("effect.after_commit")

    def run_state(self, run_id: RunId) -> RunState | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT status, owner_id, lease_expires_at FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        status = RunStatus(row["status"])
        if status is not RunStatus.RUNNING:
            liveness = "not_applicable"
        elif (
            row["owner_id"] is not None
            and row["lease_expires_at"] is not None
            and row["lease_expires_at"] > self._now_iso()
        ):
            liveness = "live"
        else:
            liveness = "lost"
        return RunState(
            status=status,
            liveness=liveness,
            owner_id=row["owner_id"],
            lease_expires_at=row["lease_expires_at"],
        )

    def run_manifest_hash(self, run_id: RunId) -> Digest | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT manifest_hash FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return Digest(row["manifest_hash"]) if row else None

    def run_inputs(self, run_id: RunId) -> dict[str, Any] | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT inputs_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        loaded = json.loads(row["inputs_json"])
        return loaded if isinstance(loaded, dict) else None

    def load_manifest_json(self, manifest_hash: Digest) -> str | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT manifest_json FROM manifests WHERE manifest_hash = ?",
                (str(manifest_hash),),
            ).fetchone()
        return row["manifest_json"] if row else None

    def events(self, run_id: RunId, *, after_seq: int = 0, limit: int = 100) -> list[JournalEvent]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?",
                (run_id, after_seq, limit),
            ).fetchall()
        return [
            JournalEvent(
                run_id=RunId(row["run_id"]),
                seq=row["seq"],
                kind=row["kind"],
                path=(
                    ExecutionPath.model_validate_json(row["path_json"])
                    if row["path_json"]
                    else None
                ),
                created_at=row["created_at"],
                payload=json.loads(row["payload"]) if row["payload"] else None,
            )
            for row in rows
        ]

    def checkpoint(self, run_id: RunId, path: ExecutionPath) -> Checkpoint | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT checkpoint_json FROM checkpoints WHERE run_id = ? AND path_key = ?",
                (run_id, _path_key(path)),
            ).fetchone()
        return Checkpoint.model_validate_json(row["checkpoint_json"]) if row else None

    def receipt_for(self, idempotency_key: Digest) -> EffectReceipt | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT receipt_json FROM effects WHERE idempotency_key = ?",
                (str(idempotency_key),),
            ).fetchone()
        if row is None or row["receipt_json"] is None:
            return None
        return EffectReceipt.model_validate_json(row["receipt_json"])

    def effect_prepared(self, idempotency_key: Digest) -> bool:
        with self._read() as conn:
            row = conn.execute(
                "SELECT receipt_json FROM effects WHERE idempotency_key = ?",
                (str(idempotency_key),),
            ).fetchone()
        return row is not None and row["receipt_json"] is None

    def record_capability_lease(self, lease: RunLease, capability_lease: CapabilityLease) -> None:
        with self._txn() as conn:
            existing = conn.execute(
                "SELECT run_id, binding_id, scope_json, lifetime, state,"
                " disposition, resource_ref FROM capability_leases"
                " WHERE lease_id = ? AND acquisition_epoch = ?",
                (capability_lease.lease_id, capability_lease.acquisition_epoch),
            ).fetchone()
            if existing is not None:
                stored = CapabilityLease(
                    lease_id=capability_lease.lease_id,
                    acquisition_epoch=capability_lease.acquisition_epoch,
                    run_id=existing["run_id"],
                    binding_id=existing["binding_id"],
                    path=ExecutionPath.model_validate_json(existing["scope_json"]),
                    lifetime=existing["lifetime"],
                    state=existing["state"],
                    disposition=existing["disposition"],
                    resource_ref=existing["resource_ref"],
                )
                if stored == capability_lease:
                    return  # idempotent re-acquire after a mid-node crash
                raise CheckpointConflict(
                    f"capability lease {capability_lease.lease_id!r} epoch "
                    f"{capability_lease.acquisition_epoch} already recorded "
                    "with different content"
                )
            seq = self._allocate_seq(conn, lease)
            now = self._now_iso()
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
                },
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
            row = conn.execute(
                "SELECT state, disposition FROM capability_leases"
                " WHERE lease_id = ? AND acquisition_epoch = ?",
                (lease_id, acquisition_epoch),
            ).fetchone()
            if row is None:
                raise ContractViolation(
                    f"capability lease {lease_id!r} epoch {acquisition_epoch} is not recorded"
                )
            if row["state"] == target and row["disposition"] == disposition:
                return  # idempotent at-target: crash-interrupted closure re-runs
            if row["state"] not in expected:
                raise ContractViolation(
                    f"capability lease {lease_id!r}: transition to {target!r} "
                    f"expected {sorted(expected)}, found {row['state']!r}"
                )
            seq = self._allocate_seq(conn, lease)
            conn.execute(
                "UPDATE capability_leases SET state = ?, disposition = ?,"
                " updated_at = ? WHERE lease_id = ? AND acquisition_epoch = ?",
                (target, disposition, self._now_iso(), lease_id, acquisition_epoch),
            )
            self._insert_event(
                conn,
                lease.run_id,
                seq,
                "LeaseTransition",
                None,
                {
                    "lease_id": lease_id,
                    "acquisition_epoch": acquisition_epoch,
                    "from": row["state"],
                    "to": target,
                    "disposition": disposition,
                },
            )
        self.fault_probe("lease.after_transition_commit")

    def capability_leases(self, run_id: RunId) -> list[CapabilityLease]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT * FROM capability_leases WHERE run_id = ?"
                " ORDER BY created_at ASC, lease_id ASC",
                (run_id,),
            ).fetchall()
        return [
            CapabilityLease(
                lease_id=row["lease_id"],
                acquisition_epoch=row["acquisition_epoch"],
                run_id=row["run_id"],
                binding_id=row["binding_id"],
                path=ExecutionPath.model_validate_json(row["scope_json"]),
                lifetime=row["lifetime"],
                state=row["state"],
                disposition=row["disposition"],
                resource_ref=row["resource_ref"],
            )
            for row in rows
        ]

    def mint_attestation(self, lease: RunLease, draft: AttestationDraft) -> Attestation:
        with self._txn() as conn:
            fence = conn.execute(
                "SELECT 1 FROM runs WHERE run_id = ? AND owner_id = ? AND owner_epoch = ?",
                (lease.run_id, lease.owner_id, lease.epoch),
            ).fetchone()
            if fence is None:
                raise OwnershipLost(f"run {lease.run_id!r}: attestation minting fenced out")
            attestation = Attestation(
                attestation_id=attestation_id_for(draft),
                created_by_run=lease.run_id,
                created_at=self._now(),
                **draft.model_dump(),
            )
            self._insert_attestation(conn, attestation)
        return attestation

    def mint_policy_attestation(self, draft: AttestationDraft) -> Attestation:
        with self._txn() as conn:
            attestation = Attestation(
                attestation_id=attestation_id_for(draft),
                created_by_run=None,
                created_at=self._now(),
                **draft.model_dump(),
            )
            self._insert_attestation(conn, attestation)
        return attestation

    @staticmethod
    def _insert_attestation(conn: sqlite3.Connection, attestation: Attestation) -> None:
        existing = conn.execute(
            "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
            (attestation.attestation_id,),
        ).fetchone()
        payload = attestation.model_dump_json()
        if existing is not None:
            prior = Attestation.model_validate_json(existing["attestation_json"])
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

    def load_attestation(self, attestation_id: str) -> Attestation | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
                (attestation_id,),
            ).fetchone()
        return Attestation.model_validate_json(row["attestation_json"]) if row else None
