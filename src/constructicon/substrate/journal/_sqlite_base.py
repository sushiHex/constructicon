# mypy: disable-error-code="attr-defined"
"""SQLite connection ownership, transaction boundaries, and shared identities."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from constructicon.core.address import ExecutionPath
from constructicon.core.envelope import utc_now
from constructicon.core.identity import canonical_json, digest
from constructicon.core.journal import Checkpoint
from constructicon.core.manifest import parse_manifest_json

_SCHEMA = """
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
CREATE TABLE IF NOT EXISTS capability_leases (
    lease_id          TEXT NOT NULL,
    acquisition_epoch INTEGER NOT NULL,
    run_id            TEXT NOT NULL,
    binding_id        TEXT NOT NULL,
    scope_json        TEXT NOT NULL,
    lifetime          TEXT NOT NULL,
    state             TEXT NOT NULL,
    disposition       TEXT,
    resource_ref      TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (lease_id, acquisition_epoch)
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
                    str(checkpoint.resolved_version) if checkpoint.resolved_version else None
                ),
                "outputs": {port: env.payload for port, env in sorted(checkpoint.outputs.items())},
            },
        )
    )


def _manifest_semantically_equal(left_json: str, right_json: str) -> bool:
    """Compare historical manifests by declared-schema semantics, never bytes."""

    try:
        left = parse_manifest_json(left_json)
        right = parse_manifest_json(right_json)
    except (ValueError, TypeError):
        return False
    return left == right


class _SqliteBase:
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

    def _now_iso(self) -> str:
        return self._now().isoformat()
