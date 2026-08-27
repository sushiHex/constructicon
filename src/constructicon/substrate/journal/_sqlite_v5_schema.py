# mypy: disable-error-code="attr-defined"
"""Internal SQLite v5 schema and atomic run-origin migration."""

from __future__ import annotations

import sqlite3
from typing import Any

from constructicon.core.address import RunId
from constructicon.core.control import RunOrigin
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json
from constructicon.core.run import CheckpointConflict, RunStatus
from constructicon.substrate.journal.sqlite_legacy import _SCHEMA as _LEGACY_SCHEMA
from constructicon.substrate.journal.sqlite_legacy import _manifest_semantically_equal

SCHEMA_VERSION = 5

_V5_SCHEMA = """
CREATE TABLE IF NOT EXISTS commands (
    command_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, actor_json TEXT NOT NULL,
    operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
    request_json TEXT NOT NULL, plan_json TEXT, state TEXT NOT NULL, response_json TEXT,
    owner_id TEXT, owner_epoch INTEGER NOT NULL DEFAULT 0, lease_expires_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT,
    UNIQUE(actor_id, operation, idempotency_key)
);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, subject_json TEXT NOT NULL,
    decision TEXT NOT NULL, reason TEXT, actor_json TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_origins (
    run_id TEXT PRIMARY KEY, origin_json TEXT NOT NULL
);
"""


class _M6SchemaMixin:
    def _migrate(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            has_runs = (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
                ).fetchone()
                is not None
            )
            if version > SCHEMA_VERSION:
                raise JournalDamaged(
                    f"database schema version {version} is newer than this build "
                    f"understands ({SCHEMA_VERSION}); refusing to touch it"
                )
            if version == 0 and has_runs:
                self._migrate_m1_to_m2(connection)
                version = 2
            elif version == 0:
                connection.executescript(_LEGACY_SCHEMA)
                connection.executescript(_V5_SCHEMA)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
                return
            if version == 2:
                self._migrate_m2_to_m3(connection)
                version = 3
            if version == 3:
                self._migrate_m3_to_m4(connection)
                version = 4
            if version == 4:
                self._migrate_m4_to_m5(connection)
                version = 5
            if version == SCHEMA_VERSION:
                connection.executescript(_LEGACY_SCHEMA)
                connection.executescript(_V5_SCHEMA)
                connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _migrate_m4_to_m5(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        connection.executescript(_V5_SCHEMA)
        connection.execute("PRAGMA user_version = 5")
        connection.commit()

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
        """Manifest + PENDING run + exact inputs + origin, one transaction."""

        with self._txn() as connection:
            existing = connection.execute(
                "SELECT manifest_json FROM manifests WHERE manifest_hash = ?",
                (str(manifest_hash),),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO manifests (manifest_hash, manifest_json) VALUES (?, ?)",
                    (str(manifest_hash), manifest_json),
                )
            elif (
                existing["manifest_json"] != manifest_json
                and not _manifest_semantically_equal(existing["manifest_json"], manifest_json)
            ):
                raise JournalDamaged(
                    f"manifest {manifest_hash} already stored with different semantics"
                )
            run = connection.execute(
                "SELECT manifest_hash, input_hash, inputs_json FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is not None:
                if (
                    run["manifest_hash"] != str(manifest_hash)
                    or run["input_hash"] != str(input_hash)
                    or run["inputs_json"] != canonical_json(inputs)
                ):
                    raise CheckpointConflict(
                        f"run {run_id!r} already exists with a different manifest/inputs"
                    )
                existing_origin = connection.execute(
                    "SELECT origin_json FROM run_origins WHERE run_id = ?", (run_id,)
                ).fetchone()
                expected_origin = origin.model_dump_json() if origin else None
                observed_origin = existing_origin["origin_json"] if existing_origin else None
                if expected_origin != observed_origin:
                    raise JournalDamaged(
                        f"run {run_id!r} already exists with a different origin"
                    )
                return
            connection.execute(
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
            if origin is not None:
                connection.execute(
                    "INSERT INTO run_origins (run_id, origin_json) VALUES (?, ?)",
                    (run_id, origin.model_dump_json()),
                )
        self.fault_probe("create.after_commit")
