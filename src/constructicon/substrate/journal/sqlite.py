"""The authoritative journal: one transactional SQLite log, many projections.

SQLite is stdlib — zero packaging cost — and used only where files would force
re-engineering what it already solves: transactional completion records,
cross-process state, and queryable history. WAL mode + busy timeout make
concurrent writers wait instead of erroring (vendored discipline from
hardline-mcp). JSONL and every rendering are regenerable projections (M2).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.effect import Attestation, EffectReceipt, EffectRequest
from constructicon.core.envelope import utc_now
from constructicon.core.identity import Digest, canonical_json
from constructicon.core.journal import Checkpoint, JournalEvent, RunStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL,
    input_hash    TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL
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
"""


def _path_key(path: ExecutionPath) -> str:
    return canonical_json(path.model_dump(mode="json"))


class SqliteJournal:
    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    # -- runs ---------------------------------------------------------------

    def create_run(self, run_id: RunId, manifest_hash: Digest, input_hash: Digest) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, manifest_hash, input_hash, status, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (run_id, str(manifest_hash), str(input_hash), RunStatus.PENDING.value,
                 utc_now().isoformat()),
            )

    def set_run_status(self, run_id: RunId, status: RunStatus) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET status = ? WHERE run_id = ?", (status.value, run_id)
            )

    def run_status(self, run_id: RunId) -> RunStatus | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return RunStatus(row["status"]) if row else None

    def run_manifest_hash(self, run_id: RunId) -> Digest | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT manifest_hash FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return Digest(row["manifest_hash"]) if row else None

    def run_inputs(self, run_id: RunId) -> dict[str, Any] | None:
        for event in self.events(run_id, limit=5):
            if event.kind == "RunStarted" and event.payload is not None:
                inputs = event.payload.get("inputs")
                if isinstance(inputs, dict):
                    return inputs
        return None

    # -- events -------------------------------------------------------------

    def append_event(
        self,
        run_id: RunId,
        kind: str,
        *,
        path: ExecutionPath | None = None,
        payload: dict[str, Any] | None = None,
    ) -> JournalEvent:
        with self._connect() as conn:
            return self._append_event_in(conn, run_id, kind, path=path, payload=payload)

    def _append_event_in(
        self,
        conn: sqlite3.Connection,
        run_id: RunId,
        kind: str,
        *,
        path: ExecutionPath | None,
        payload: dict[str, Any] | None,
    ) -> JournalEvent:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        event = JournalEvent(
            run_id=run_id,
            seq=int(row["seq"]) + 1,
            kind=kind,
            path=path,
            created_at=utc_now(),
            payload=payload,
        )
        conn.execute(
            "INSERT INTO events (run_id, seq, kind, path_json, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                event.seq,
                kind,
                canonical_json(path.model_dump(mode="json")) if path else None,
                canonical_json(payload) if payload is not None else None,
                event.created_at.isoformat(),
            ),
        )
        return event

    def events(
        self, run_id: RunId, *, after_seq: int = 0, limit: int = 100
    ) -> list[JournalEvent]:
        import json

        with self._connect() as conn:
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

    # -- checkpoints (transactional completion) ----------------------------

    def record_completion(self, checkpoint: Checkpoint) -> None:
        """Checkpoint + NodeCompleted event commit in ONE transaction."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO checkpoints (run_id, path_key, checkpoint_json)"
                " VALUES (?, ?, ?)",
                (
                    checkpoint.run_id,
                    _path_key(checkpoint.path),
                    checkpoint.model_dump_json(),
                ),
            )
            self._append_event_in(
                conn,
                checkpoint.run_id,
                "NodeCompleted",
                path=checkpoint.path,
                payload={"input_hash": str(checkpoint.input_hash)},
            )
            conn.commit()

    def checkpoint(self, run_id: RunId, path: ExecutionPath) -> Checkpoint | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT checkpoint_json FROM checkpoints WHERE run_id = ? AND path_key = ?",
                (run_id, _path_key(path)),
            ).fetchone()
        return Checkpoint.model_validate_json(row["checkpoint_json"]) if row else None

    # -- manifests ----------------------------------------------------------

    def store_manifest(self, manifest_json: str, manifest_hash: Digest) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO manifests (manifest_hash, manifest_json)"
                " VALUES (?, ?)",
                (str(manifest_hash), manifest_json),
            )

    def load_manifest_json(self, manifest_hash: Digest) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT manifest_json FROM manifests WHERE manifest_hash = ?",
                (str(manifest_hash),),
            ).fetchone()
        return row["manifest_json"] if row else None

    # -- attestations (journal-minted authority, I2) ------------------------

    def mint_attestation(self, attestation: Attestation) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO attestations (attestation_id, attestation_json)"
                " VALUES (?, ?)",
                (attestation.attestation_id, attestation.model_dump_json()),
            )

    def load_attestation(self, attestation_id: str) -> Attestation | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
                (attestation_id,),
            ).fetchone()
        return Attestation.model_validate_json(row["attestation_json"]) if row else None

    # -- effects (idempotency records) --------------------------------------

    def record_effect_prepared(self, run_id: RunId, request: EffectRequest) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO effects"
                " (idempotency_key, run_id, request_json, prepared_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    str(request.idempotency_key),
                    run_id,
                    request.model_dump_json(),
                    utc_now().isoformat(),
                ),
            )

    def record_effect_receipt(
        self, run_id: RunId, request: EffectRequest, receipt: EffectReceipt
    ) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO effects"
                " (idempotency_key, run_id, request_json, prepared_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    str(request.idempotency_key),
                    run_id,
                    request.model_dump_json(),
                    utc_now().isoformat(),
                ),
            )
            conn.execute(
                "UPDATE effects SET receipt_json = ?, receipted_at = ?"
                " WHERE idempotency_key = ?",
                (
                    receipt.model_dump_json(),
                    utc_now().isoformat(),
                    str(request.idempotency_key),
                ),
            )
            conn.commit()

    def receipt_for(self, idempotency_key: Digest) -> EffectReceipt | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT receipt_json FROM effects WHERE idempotency_key = ?",
                (str(idempotency_key),),
            ).fetchone()
        if row is None or row["receipt_json"] is None:
            return None
        return EffectReceipt.model_validate_json(row["receipt_json"])

    def effect_prepared(self, idempotency_key: Digest) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT receipt_json FROM effects WHERE idempotency_key = ?",
                (str(idempotency_key),),
            ).fetchone()
        return row is not None and row["receipt_json"] is None
