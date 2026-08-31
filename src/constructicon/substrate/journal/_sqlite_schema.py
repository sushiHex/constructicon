# mypy: disable-error-code="attr-defined"
"""SQLite schema ownership and atomic migrations through schema 6."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.control import RunOrigin
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json
from constructicon.core.journal import Checkpoint
from constructicon.core.run import CheckpointConflict, RunStatus
from constructicon.substrate.journal._sqlite_base import (
    _SCHEMA,
    _checkpoint_identity,
    _manifest_semantically_equal,
)

SCHEMA_VERSION = 7

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

# Append-only channel facts. A message is never updated or deleted, and an
# acknowledgement is a delivery fact that never hides history from recovery.
# ``UNIQUE(reply_to)`` is what enforces one reply per request; SQLite allows
# many NULLs, so requests are unconstrained by it.
_V6_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_messages (
    message_seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id         TEXT NOT NULL UNIQUE,
    channel_id         TEXT NOT NULL,
    lane               TEXT NOT NULL,
    interaction        TEXT NOT NULL,
    kind               TEXT NOT NULL,
    reply_to           TEXT,
    recipient_actor_id TEXT,
    sender_actor_id    TEXT,
    run_id             TEXT NOT NULL,
    path_json          TEXT NOT NULL,
    port               TEXT NOT NULL,
    type_id            TEXT NOT NULL,
    schema_hash        TEXT NOT NULL,
    reply_port         TEXT,
    reply_type_id      TEXT,
    reply_schema_hash  TEXT,
    envelope_json      TEXT NOT NULL,
    attestation_id     TEXT,
    UNIQUE(reply_to)
);
CREATE TABLE IF NOT EXISTS channel_acks (
    ack_seq    INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    actor_id   TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE,
    acked_at   TEXT NOT NULL,
    UNIQUE(message_id, actor_id)
);
"""


class _SqliteSchemaMixin:
    def _migrate(self) -> None:
        connection = self._connect()
        try:
            # Refuse BEFORE any pragma writes: "refusing to touch it" must be
            # literally true, and journal_mode is itself a durable change.
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise JournalDamaged(
                    f"database schema version {version} is newer than this build "
                    f"understands ({SCHEMA_VERSION}); refusing to touch it"
                )
            connection.execute("PRAGMA journal_mode=WAL")
            has_runs = (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
                ).fetchone()
                is not None
            )
            if version == 0 and has_runs:
                self._migrate_m1_to_m2(connection)
                version = 2
            elif version == 0:
                connection.executescript(_SCHEMA)
                connection.executescript(_V5_SCHEMA)
                connection.executescript(_V6_SCHEMA)
                self._add_v7_columns(connection)
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
            if version == 5:
                self._migrate_m5_to_m6(connection)
                version = 6
            if version == 6:
                self._migrate_m6_to_m7(connection)
                version = 7
            if version == SCHEMA_VERSION:
                connection.executescript(_SCHEMA)
                connection.executescript(_V5_SCHEMA)
                connection.executescript(_V6_SCHEMA)
                connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _migrate_m4_to_m5(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        connection.executescript(_V5_SCHEMA)
        connection.execute("PRAGMA user_version = 5")
        connection.commit()

    @staticmethod
    def _add_v7_columns(connection: sqlite3.Connection) -> None:
        """The one place the v7 column is defined, for fresh and climbing alike.

        Idempotent by inspection rather than by swallowing an error: a database
        whose ``user_version`` sits below a column it already carries is walking
        a ladder it has partly climbed, and that is not damage. No row is read
        or rewritten on either path.
        """

        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(channel_messages)")
        }
        if "command_id" not in columns:
            connection.execute("ALTER TABLE channel_messages ADD COLUMN command_id TEXT")

    @staticmethod
    def _migrate_m6_to_m7(connection: sqlite3.Connection) -> None:
        """Additive only: one nullable column and a version bump.

        A request already records the attestation that admitted it. A reply now
        records the command that did, so an exact retry of one command can be
        told apart from a second command that lost the race — ADR 0014 admits
        one reply and owes the loser a typed conflict, identical bytes included.

        Existing rows keep NULL and are never read or rewritten. A NULL is not
        "some command": it is a reply written before this build, which no live
        command may claim.
        """

        connection.execute("BEGIN IMMEDIATE")
        _SqliteSchemaMixin._add_v7_columns(connection)
        connection.execute("PRAGMA user_version = 7")
        connection.commit()

    @staticmethod
    def _migrate_m5_to_m6(connection: sqlite3.Connection) -> None:
        """Additive only: two empty channel tables and a version bump.

        No run, command, approval, effect, event, manifest, component, or
        promotion row is read or rewritten.
        """

        connection.execute("BEGIN IMMEDIATE")
        connection.executescript(_V6_SCHEMA)
        connection.execute("PRAGMA user_version = 6")
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
            elif existing["manifest_json"] != manifest_json and not _manifest_semantically_equal(
                existing["manifest_json"], manifest_json
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
                    raise JournalDamaged(f"run {run_id!r} already exists with a different origin")
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
        checkpoint_columns = {row[1] for row in conn.execute("PRAGMA table_info(checkpoints)")}
        if "identity" not in checkpoint_columns:
            conn.execute("ALTER TABLE checkpoints ADD COLUMN identity TEXT NOT NULL DEFAULT ''")
            for row in conn.execute(
                "SELECT run_id, path_key, checkpoint_json FROM checkpoints"
            ).fetchall():
                checkpoint = Checkpoint.model_validate_json(row["checkpoint_json"])
                conn.execute(
                    "UPDATE checkpoints SET identity = ? WHERE run_id = ? AND path_key = ?",
                    (_checkpoint_identity(checkpoint), row["run_id"], row["path_key"]),
                )
        conn.executescript(_SCHEMA)  # creates the tables M1 lacked
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
        conn.execute("PRAGMA user_version = 2")
        conn.commit()

    def _migrate_m2_to_m3(self, conn: sqlite3.Connection) -> None:
        """Add the historical M3 capability lease table (static scope)."""
        conn.execute(
            """CREATE TABLE IF NOT EXISTS capability_leases (
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
            )"""
        )
        conn.execute("PRAGMA user_version = 3")
        conn.commit()

    def _migrate_m3_to_m4(self, conn: sqlite3.Connection) -> None:
        """Rewrite static lease scopes as frame-aware execution paths in place.

        The historical ``scope_json`` column name is retained to avoid a table
        rebuild. Its v4 payload is an ``ExecutionPath``. Old lease ids and
        resource refs remain byte-identical for row-driven reconciliation.
        """

        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT lease_id, acquisition_epoch, scope_json, lifetime, state,"
            " disposition FROM capability_leases"
        ).fetchall()
        for row in rows:
            payload = json.loads(row["scope_json"])
            if isinstance(payload, dict) and "scope" in payload:
                path = ExecutionPath.model_validate(payload)
            else:
                scope = ScopePath.model_validate(payload)
                path = ExecutionPath(scope=scope)
            state = "closed" if row["state"] == "suspended" else row["state"]
            disposition = row["disposition"]
            if disposition == "retained":
                disposition = "released"
            conn.execute(
                "UPDATE capability_leases SET scope_json = ?, lifetime = ?,"
                " state = ?, disposition = ? WHERE lease_id = ?"
                " AND acquisition_epoch = ?",
                (
                    canonical_json(path.model_dump(mode="json")),
                    "invocation",
                    state,
                    disposition,
                    row["lease_id"],
                    row["acquisition_epoch"],
                ),
            )
        conn.execute("PRAGMA user_version = 4")
        conn.commit()
