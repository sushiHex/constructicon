"""The authoritative store (M2): one transactional SQLite log; the SQLite
store owns the database and every transaction boundary.

- **Fencing**: every owner-side write allocates its event sequence with
  ``UPDATE runs SET next_event_seq = next_event_seq + 1 WHERE run_id=? AND
  owner_id=? AND owner_epoch=?`` inside the same ``BEGIN IMMEDIATE``
  transaction — the sequence allocation *is* the fence. Zero rows means a
  higher epoch owns the run: ``OwnershipLost``, and the stale worker stops.
- **Write-once**: durable facts (runs, manifests, checkpoints, receipts,
  attestations, component versions) are insert-only. Identical repetition is
  idempotent; contradictory repetition raises ``CheckpointConflict`` /
  ``JournalDamaged``.
- **Migrations**: ``PRAGMA user_version`` marks the schema; an M1 database
  (user_version 0) is migrated in place, including backfilling durable run
  inputs from its ``RunStarted`` events.
- **Fault probes**: ``fault_probe(name)`` is a no-op hook tests arm to die at
  named intra-transaction points — a wrapper cannot reach these seams.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.component import PromotionRecord
from constructicon.core.effect import Attestation, EffectReceipt, EffectRequest
from constructicon.core.envelope import utc_now
from constructicon.core.errors import AdmissionError, ContractViolation, JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.journal import Checkpoint, JournalEvent
from constructicon.core.registry import RegistrySnapshot, StoredVersion
from constructicon.core.run import (
    CheckpointConflict,
    OwnershipLost,
    RunLease,
    RunState,
    RunStatus,
)

SCHEMA_VERSION = 2

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    manifest_hash    TEXT NOT NULL,
    input_hash       TEXT NOT NULL,
    inputs_json      TEXT NOT NULL,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    owner_id         TEXT,
    owner_epoch      INTEGER NOT NULL DEFAULT 0,
    owner_pid        INTEGER,
    heartbeat_at     TEXT,
    lease_expires_at TEXT,
    next_event_seq   INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    path_json  TEXT,
    payload    TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id          TEXT NOT NULL,
    path_key        TEXT NOT NULL,
    identity        TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    PRIMARY KEY (run_id, path_key)
);
CREATE TABLE IF NOT EXISTS manifests (
    manifest_hash TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attestations (
    attestation_id   TEXT PRIMARY KEY,
    attestation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS effects (
    idempotency_key TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    request_json    TEXT NOT NULL,
    receipt_json    TEXT,
    prepared_at     TEXT NOT NULL,
    receipted_at    TEXT
);
CREATE TABLE IF NOT EXISTS components (
    registration_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    definition_json  TEXT NOT NULL,
    registered_at    TEXT NOT NULL,
    UNIQUE (name, content_hash)
);
CREATE TABLE IF NOT EXISTS promotions (
    promotion_seq  INTEGER PRIMARY KEY AUTOINCREMENT,
    component      TEXT NOT NULL,
    channel        TEXT NOT NULL,
    from_version   TEXT,
    to_version     TEXT NOT NULL,
    attestation_id TEXT NOT NULL UNIQUE,
    actor          TEXT NOT NULL,
    source_run     TEXT,
    created_at     TEXT NOT NULL
);
"""


def _path_key(path: ExecutionPath) -> str:
    return canonical_json(path.model_dump(mode="json"))


def _checkpoint_identity(checkpoint: Checkpoint) -> str:
    """Semantic identity of a completion — envelope timestamps excluded, so a
    legitimately identical re-record is idempotent while a different result at
    the same (run, path) is damage."""
    return str(
        digest(
            "checkpoint-identity",
            1,
            {
                "input_hash": str(checkpoint.input_hash),
                "resolved_version": (
                    str(checkpoint.resolved_version)
                    if checkpoint.resolved_version
                    else None
                ),
                "outputs": {
                    port: env.payload for port, env in sorted(checkpoint.outputs.items())
                },
            },
        )
    )


class SqliteJournal:
    """Implements both the ``Journal`` and ``RegistryStore`` contracts over
    one database; sharing the file does not merge the concepts (I8) — the two
    protocols live in ``core.journal`` and ``core.registry``."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        now_fn: Callable[[], datetime] = utc_now,
    ) -> None:
        self._db_path = str(db_path)
        self._now = now_fn
        # No-op hook tests arm to simulate death at named points.
        self.fault_probe: Callable[[str], None] = lambda name: None
        self._migrate()

    # -- connections and transactions ---------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    # -- migrations ----------------------------------------------------------

    def _migrate(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            has_runs = (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
                ).fetchone()
                is not None
            )
            if version == 0 and has_runs:
                self._migrate_m1_to_m2(conn)
            elif version == 0:
                conn.executescript(_SCHEMA_V2)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                conn.commit()
            elif version == SCHEMA_VERSION:
                conn.executescript(_SCHEMA_V2)  # idempotent completeness check
                conn.commit()
            else:
                raise JournalDamaged(
                    f"database schema version {version} is newer than this build "
                    f"understands ({SCHEMA_VERSION}); refusing to touch it"
                )
        finally:
            conn.close()

    def _migrate_m1_to_m2(self, conn: sqlite3.Connection) -> None:
        """In-place M1 -> M2: additive columns, new tables, inputs backfilled
        from each run's RunStarted event, sequence counters backfilled."""
        conn.execute("BEGIN IMMEDIATE")
        run_columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
        additions = {
            "inputs_json": "TEXT NOT NULL DEFAULT '{}'",
            "owner_id": "TEXT",
            "owner_epoch": "INTEGER NOT NULL DEFAULT 0",
            "owner_pid": "INTEGER",
            "heartbeat_at": "TEXT",
            "lease_expires_at": "TEXT",
            "next_event_seq": "INTEGER NOT NULL DEFAULT 0",
            "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, decl in additions.items():
            if name not in run_columns:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {decl}")
        checkpoint_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(checkpoints)")
        }
        if "identity" not in checkpoint_columns:
            conn.execute(
                "ALTER TABLE checkpoints ADD COLUMN identity TEXT NOT NULL DEFAULT ''"
            )
            for row in conn.execute(
                "SELECT run_id, path_key, checkpoint_json FROM checkpoints"
            ).fetchall():
                checkpoint = Checkpoint.model_validate_json(row["checkpoint_json"])
                conn.execute(
                    "UPDATE checkpoints SET identity = ? WHERE run_id = ? AND path_key = ?",
                    (_checkpoint_identity(checkpoint), row["run_id"], row["path_key"]),
                )
        conn.executescript(_SCHEMA_V2)  # creates the tables M1 lacked
        # backfill durable inputs from RunStarted events (M1's archaeology, once)
        for row in conn.execute("SELECT run_id FROM runs").fetchall():
            run_id = row["run_id"]
            event = conn.execute(
                "SELECT payload FROM events WHERE run_id = ? AND kind = 'RunStarted'"
                " ORDER BY seq ASC LIMIT 1",
                (run_id,),
            ).fetchone()
            if event and event["payload"]:
                payload = json.loads(event["payload"])
                inputs = payload.get("inputs")
                if isinstance(inputs, dict):
                    conn.execute(
                        "UPDATE runs SET inputs_json = ? WHERE run_id = ?",
                        (canonical_json(inputs), run_id),
                    )
            seq_row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            conn.execute(
                "UPDATE runs SET next_event_seq = ? WHERE run_id = ?",
                (int(seq_row["seq"]), run_id),
            )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

    # -- internal helpers ----------------------------------------------------

    def _now_iso(self) -> str:
        return self._now().isoformat()

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
            run_id=run_id, seq=seq, kind=kind, path=path,
            created_at=created_at, payload=payload,
        )

    # -- creation (write-once) ----------------------------------------------

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
            elif existing["manifest_json"] != manifest_json:
                raise JournalDamaged(
                    f"manifest {manifest_hash} already stored with different bytes"
                )
            run = conn.execute(
                "SELECT manifest_hash, input_hash FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is not None:
                if (
                    run["manifest_hash"] == str(manifest_hash)
                    and run["input_hash"] == str(input_hash)
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

    # -- ownership -----------------------------------------------------------

    def claim_run(self, run_id: RunId, *, owner_id: str, ttl_s: float) -> RunLease:
        from datetime import timedelta

        now = self._now()
        expires = now + timedelta(seconds=ttl_s)
        with self._txn() as conn:
            row = conn.execute(
                "SELECT status, owner_id, owner_epoch, lease_expires_at FROM runs"
                " WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ContractViolation(f"unknown run {run_id!r}")
            status = RunStatus(row["status"])
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
                (expires.isoformat(), now.isoformat(), lease.run_id,
                 lease.owner_id, lease.epoch),
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
            conn.execute(
                "UPDATE runs SET cancel_requested = 1 WHERE run_id = ?", (run_id,)
            )

    def cancel_requested(self, run_id: RunId) -> bool:
        with self._read() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    # -- fenced lifecycle ----------------------------------------------------

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

    # -- effects -------------------------------------------------------------

    def record_effect_prepared(self, lease: RunLease, request: EffectRequest) -> None:
        with self._txn() as conn:
            fence = conn.execute(
                "SELECT 1 FROM runs WHERE run_id = ? AND owner_id = ? AND owner_epoch = ?",
                (lease.run_id, lease.owner_id, lease.epoch),
            ).fetchone()
            if fence is None:
                raise OwnershipLost(
                    f"run {lease.run_id!r}: effect preparation fenced out"
                )
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
                "UPDATE effects SET receipt_json = ?, receipted_at = ?"
                " WHERE idempotency_key = ?",
                (receipt.model_dump_json(), self._now_iso(),
                 str(request.idempotency_key)),
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

    # -- reads ---------------------------------------------------------------

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

    def events(
        self, run_id: RunId, *, after_seq: int = 0, limit: int = 100
    ) -> list[JournalEvent]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq > ?"
                " ORDER BY seq ASC LIMIT ?",
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

    # -- attestations --------------------------------------------------------

    def mint_attestation(self, attestation: Attestation) -> None:
        with self._txn() as conn:
            existing = conn.execute(
                "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
                (attestation.attestation_id,),
            ).fetchone()
            payload = attestation.model_dump_json()
            if existing is not None:
                if existing["attestation_json"] == payload:
                    return
                raise JournalDamaged(
                    f"attestation {attestation.attestation_id!r} already minted "
                    "with different content"
                )
            conn.execute(
                "INSERT INTO attestations (attestation_id, attestation_json)"
                " VALUES (?, ?)",
                (attestation.attestation_id, payload),
            )

    def load_attestation(self, attestation_id: str) -> Attestation | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
                (attestation_id,),
            ).fetchone()
        return Attestation.model_validate_json(row["attestation_json"]) if row else None

    # -- RegistryStore (rows are receipts) -----------------------------------

    def snapshot(self) -> RegistrySnapshot:
        with self._read() as conn:
            conn.execute("BEGIN")  # one WAL read snapshot for both tables
            versions: dict[str, dict[str, StoredVersion]] = {}
            order: dict[str, list[str]] = {}
            for row in conn.execute(
                "SELECT name, content_hash, definition_json, registered_at"
                " FROM components ORDER BY registration_seq ASC"
            ).fetchall():
                stored = StoredVersion(
                    definition=json.loads(row["definition_json"]),
                    content_hash=Digest(row["content_hash"]),
                    registered_at=row["registered_at"],
                )
                versions.setdefault(row["name"], {})[row["content_hash"]] = stored
                order.setdefault(row["name"], []).append(row["content_hash"])
            stable: dict[str, str] = {}
            history: dict[str, list[tuple[str | None, str]]] = {}
            for row in conn.execute(
                "SELECT component, from_version, to_version FROM promotions"
                " WHERE channel = 'stable' ORDER BY promotion_seq ASC"
            ).fetchall():
                stable[row["component"]] = row["to_version"]
                history.setdefault(row["component"], []).append(
                    (row["from_version"], row["to_version"])
                )
            conn.execute("COMMIT")
        return RegistrySnapshot(
            versions=versions,
            order={name: tuple(hashes) for name, hashes in order.items()},
            stable=stable,
            history={name: tuple(pairs) for name, pairs in history.items()},
        )

    def store_version(self, version: StoredVersion) -> None:
        with self._txn() as conn:
            existing = conn.execute(
                "SELECT definition_json FROM components WHERE name = ? AND content_hash = ?",
                (version.definition.name, str(version.content_hash)),
            ).fetchone()
            payload = version.definition.model_dump_json()
            if existing is not None:
                if existing["definition_json"] == payload:
                    return  # idempotent re-registration (startup re-registers)
                raise JournalDamaged(
                    f"component {version.definition.name!r}@{version.content_hash} "
                    "already stored with different definition bytes"
                )
            conn.execute(
                "INSERT INTO components (name, content_hash, definition_json, registered_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    version.definition.name,
                    str(version.content_hash),
                    payload,
                    version.registered_at.isoformat(),
                ),
            )

    def store_promotion(self, record: PromotionRecord) -> PromotionRecord:
        with self._txn() as conn:
            prior = conn.execute(
                "SELECT * FROM promotions WHERE attestation_id = ?",
                (record.attestation_id,),
            ).fetchone()
            if prior is not None:
                return _promotion_from_row(prior)  # one attestation, one move
            current = conn.execute(
                "SELECT to_version FROM promotions WHERE component = ?"
                " AND channel = 'stable' ORDER BY promotion_seq DESC LIMIT 1",
                (record.component,),
            ).fetchone()
            current_stable = current["to_version"] if current else None
            expected = str(record.from_version) if record.from_version else None
            if current_stable != expected:
                raise AdmissionError(
                    [
                        f"promotion of {record.component!r} refused: stable moved — "
                        f"expected {expected!r}, found {current_stable!r} "
                        "(compare-and-swap; re-evaluate against the current baseline)"
                    ]
                )
            conn.execute(
                "INSERT INTO promotions (component, channel, from_version, to_version,"
                " attestation_id, actor, source_run, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.component,
                    record.channel,
                    expected,
                    str(record.to_version),
                    record.attestation_id,
                    record.actor,
                    record.source_run,
                    record.created_at.isoformat(),
                ),
            )
            return record


def _promotion_from_row(row: sqlite3.Row) -> PromotionRecord:
    return PromotionRecord(
        component=row["component"],
        channel=row["channel"],
        from_version=Digest(row["from_version"]) if row["from_version"] else None,
        to_version=Digest(row["to_version"]),
        attestation_id=row["attestation_id"],
        actor=row["actor"],
        source_run=RunId(row["source_run"]) if row["source_run"] else None,
        created_at=row["created_at"],
    )
