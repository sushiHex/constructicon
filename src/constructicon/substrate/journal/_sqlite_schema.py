# mypy: disable-error-code="attr-defined"
"""SQLite schema ownership and atomic migrations through schema 7."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.control import RunOrigin, run_id_for_command
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.journal import Checkpoint
from constructicon.core.manifest import parse_manifest_json
from constructicon.core.run import CheckpointConflict, RunStatus
from constructicon.substrate.journal._sqlite_approvals import (
    seal_approval,
    stored_approval_fact_from_row,
)
from constructicon.substrate.journal._sqlite_attestations import (
    seal_attestation,
    validate_attestation_seal_inventory,
)
from constructicon.substrate.journal._sqlite_base import (
    _SCHEMA,
    _checkpoint_identity,
    _durable_json,
    _durable_model,
    _durable_sequence,
    _durable_text,
    _manifest_semantically_equal,
    read_snapshot,
)
from constructicon.substrate.journal._sqlite_channels import (
    CHANNEL_ACK_FACT_FAMILY,
    CHANNEL_MESSAGE_FACT_FAMILY,
    CHANNEL_PROVENANCE_FACT_FAMILY,
    seal_channel_ack,
    seal_channel_message,
    seal_channel_provenance,
    validate_channel_fact_seal_inventory,
)
from constructicon.substrate.journal._sqlite_commands import (
    RESUME_PLAN_ERA_FACT_FAMILY,
    command_plan_exists,
    seal_command_claim,
    seal_command_phases,
    seal_resume_plan_eras,
    validate_command_claim_inventory,
)
from constructicon.substrate.journal._sqlite_effects import (
    EFFECT_PREPARATION_FACT_FAMILY,
    legacy_effect_seal,
    seal_effect_preparation,
    validate_legacy_effect_seal_inventory,
)
from constructicon.substrate.journal._sqlite_execution import (
    LEGACY_EFFECT_OUTCOME_FACT_FAMILY,
    seal_legacy_effect_outcomes,
    validate_capability_lease_inventory,
    validate_effect_fact_inventory,
)
from constructicon.substrate.journal._sqlite_execution_facts import (
    CHECKPOINT_FACT_FAMILY,
    EVENT_FACT_FAMILY,
    RESUME_ATTEMPT_FACT_FAMILY,
    seal_checkpoint,
    seal_event,
    seal_migrated_resume_attempts,
    validate_checkpoint_seal_inventory,
    validate_event_seal_inventory,
)
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_seal,
    validate_durable_fact_seal_inventory,
)
from constructicon.substrate.journal._sqlite_leases import (
    legacy_lease_base_hash,
    legacy_lease_initial_lifecycle_json,
    validate_legacy_lease_seal_inventory,
)
from constructicon.substrate.journal._sqlite_registry import (
    seal_component_registration,
    seal_promotion,
    validate_registry_seal_inventory,
)
from constructicon.substrate.journal._sqlite_runs import (
    MANIFEST_FACT_FAMILY,
    RUN_WORLD_FACT_FAMILY,
    register_run_origin_guard,
    require_manifest_seal,
    retained_manifest,
    seal_manifest,
    seal_run_world,
    validate_no_orphan_run_facts,
    validate_run_fact_inventory,
    validated_run_world,
)

SCHEMA_VERSION = 7

_CURRENT_V7_TABLES = frozenset(
    {
        "approvals",
        "attestations",
        "capability_leases",
        "channel_acks",
        "channel_messages",
        "channel_provenance",
        "checkpoints",
        "commands",
        "components",
        "durable_fact_seals",
        "effects",
        "events",
        "legacy_capability_lease_seals",
        "legacy_effect_seals",
        "manifests",
        "promotions",
        "run_origins",
        "runs",
    }
)

_DURABLE_FACT_SEAL_FAMILIES = frozenset(
    {
        "approval",
        "attestation",
        "command_claim",
        "command_plan",
        "command_terminal",
        "component_registration",
        CHANNEL_ACK_FACT_FAMILY,
        CHANNEL_MESSAGE_FACT_FAMILY,
        CHANNEL_PROVENANCE_FACT_FAMILY,
        CHECKPOINT_FACT_FAMILY,
        EFFECT_PREPARATION_FACT_FAMILY,
        EVENT_FACT_FAMILY,
        "legacy_attestation_m1_m2",
        LEGACY_EFFECT_OUTCOME_FACT_FAMILY,
        "legacy_promotion_pre_v7",
        RESUME_PLAN_ERA_FACT_FAMILY,
        MANIFEST_FACT_FAMILY,
        "promotion",
        RESUME_ATTEMPT_FACT_FAMILY,
        RUN_WORLD_FACT_FAMILY,
    }
)


def _channel_ack_sequence_max(connection: sqlite3.Connection) -> int:
    """Read a migration cutoff without normalizing damaged row scalars."""

    row = connection.execute(
        "SELECT COALESCE(MAX(ack_seq), 0) AS maximum,"
        " COALESCE(MAX(CASE WHEN typeof(ack_seq) != 'integer'"
        " OR ack_seq <= 0 THEN 1 ELSE 0 END), 0) AS damaged"
        " FROM channel_acks"
    ).fetchone()
    damaged = _durable_sequence(
        row["damaged"],
        fact="channel acknowledgement migration integrity flag",
        allow_zero=True,
        kind="acknowledgement sequence",
    )
    if damaged != 0:
        raise JournalDamaged("channel acknowledgement sequence history is damaged")
    return _durable_sequence(
        row["maximum"],
        fact="maximum channel acknowledgement position",
        allow_zero=True,
        kind="acknowledgement sequence",
    )


def _channel_message_sequence_max(connection: sqlite3.Connection) -> int:
    """Read the companion message-era cutoff without SQLite coercion."""

    row = connection.execute(
        "SELECT COALESCE(MAX(message_seq), 0) AS maximum,"
        " COALESCE(MAX(CASE WHEN typeof(message_seq) != 'integer'"
        " OR message_seq <= 0 THEN 1 ELSE 0 END), 0) AS damaged"
        " FROM channel_messages"
    ).fetchone()
    damaged = _durable_sequence(
        row["damaged"],
        fact="channel message migration integrity flag",
        allow_zero=True,
        kind="message sequence",
    )
    if damaged != 0:
        raise JournalDamaged("channel message sequence history is damaged")
    return _durable_sequence(
        row["maximum"],
        fact="maximum channel message position",
        allow_zero=True,
        kind="message sequence",
    )


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


def _has_legacy_runs_table(connection: sqlite3.Connection) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone()
        is not None
    )


def _ddl_statements(*scripts: str) -> tuple[str, ...]:
    """One schema script as statements that can run inside a transaction.

    `executescript` commits whatever transaction is open before it runs, so a
    create that must be atomic with the `user_version` it publishes cannot use
    it. These scripts are plain `CREATE` statements with no string literals, so
    the statement boundary is exactly the semicolon.
    """

    return tuple(
        statement
        for script in scripts
        for raw in script.split(";")
        if (statement := raw.strip())
    )


_CURRENT_SCHEMA_DDL = _ddl_statements(_SCHEMA, _V5_SCHEMA, _V6_SCHEMA)


class _SqliteSchemaMixin:
    def _create_current_schema(self, connection: sqlite3.Connection) -> bool:
        """Create an empty store at the current version, or say who won.

        Tables become visible to other openers the moment they commit, so a
        create that publishes them before its `user_version` invites a
        concurrent opener to read a brand-new database as a version-0 legacy
        one and run the M1 ladder over it — or to trip over half a schema. One
        transaction publishes both, and the version is re-read inside it
        because another process may have created the store in the meantime.

        Returns whether this process is the one that created it.
        """

        connection.execute("BEGIN IMMEDIATE")
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) != 0 or (
            _has_legacy_runs_table(connection)
        ):
            connection.rollback()
            return False
        for statement in _CURRENT_SCHEMA_DDL:
            connection.execute(statement)
        self._ensure_v7_channel_schema(connection, mode="fresh")
        self._ensure_v7_effect_schema(connection, mode="fresh")
        self._ensure_v7_lease_schema(connection, mode="fresh")
        self._ensure_v7_run_schema(connection, mode="fresh")
        self._ensure_v7_fact_seal_schema(connection, mode="fresh")
        self._validate_v7_fact_inventory(connection)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
        return True

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
            if version == SCHEMA_VERSION:
                self._require_current_v7_tables(connection)
            connection.execute("PRAGMA journal_mode=WAL")
            has_runs = _has_legacy_runs_table(connection)
            if version == 0 and not has_runs:
                if self._create_current_schema(connection):
                    return
                # Another process created the store between the read above and
                # the lock. Ask again: whatever it left behind is what this
                # opener must now climb from and validate.
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                has_runs = _has_legacy_runs_table(connection)
            if version == 0 and has_runs:
                self._migrate_m1_to_m2(connection)
                version = 2
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
                self._ensure_v7_channel_schema(connection, mode="current")
                self._ensure_v7_effect_schema(connection, mode="current")
                self._ensure_v7_lease_schema(connection, mode="current")
                self._ensure_v7_run_schema(connection, mode="current")
                self._ensure_v7_fact_seal_schema(connection, mode="current")
                connection.commit()
                # Opening compares every primary fact against its seal across
                # many statements. Without one snapshot a writer committing
                # between two of them makes a healthy store fail to open, and
                # ADR 0016 forbids healing on open — so that refusal is final.
                with read_snapshot(connection):
                    self._validate_v7_fact_inventory(connection)
        finally:
            connection.close()

    @staticmethod
    def _require_current_v7_tables(connection: sqlite3.Connection) -> None:
        retained = {
            _durable_text(row["name"], fact="schema 7 table identity")
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = sorted(_CURRENT_V7_TABLES - retained)
        if missing:
            raise JournalDamaged("schema 7 durable tables are missing: " + ", ".join(missing))

    @staticmethod
    def _migrate_m4_to_m5(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        connection.executescript(_V5_SCHEMA)
        connection.execute("PRAGMA user_version = 5")
        connection.commit()

    @staticmethod
    def _ensure_v7_channel_schema(
        connection: sqlite3.Connection,
        *,
        mode: Literal["fresh", "migrate", "current"],
        legacy_ack_through: int | None = None,
        legacy_message_through: int | None = None,
    ) -> None:
        """Define channel-command provenance once, for fresh and climbing alike.

        Idempotent by inspection rather than by swallowing an error: a database
        whose ``user_version`` sits below a column it already carries is walking
        a ladder it has partly climbed, and that is not damage. Historical
        content stays untouched; the v6→v7 migration alone populates the new
        acknowledgement marker. The partial unique index makes one command's
        one reply a physical law for every current row.
        """

        columns = {row[1] for row in connection.execute("PRAGMA table_info(channel_messages)")}
        missing_message_columns = {
            "command_id",
            "reply_provenance_version",
        } - columns
        acknowledgement_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(channel_acks)")
        }
        missing_ack_columns = {"ack_provenance_version"} - acknowledgement_columns
        has_provenance_table = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'channel_provenance'"
            ).fetchone()
            is not None
        )
        if mode == "current" and (
            missing_message_columns or missing_ack_columns or not has_provenance_table
        ):
            raise JournalDamaged("schema 7 channel provenance structure is missing")
        if "command_id" not in columns:
            connection.execute("ALTER TABLE channel_messages ADD COLUMN command_id TEXT")
        if "reply_provenance_version" not in columns:
            connection.execute(
                "ALTER TABLE channel_messages ADD COLUMN reply_provenance_version INTEGER"
            )
        if "ack_provenance_version" not in acknowledgement_columns:
            connection.execute("ALTER TABLE channel_acks ADD COLUMN ack_provenance_version INTEGER")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS channel_provenance ("
            " singleton INTEGER PRIMARY KEY CHECK (singleton = 1),"
            " legacy_ack_through INTEGER NOT NULL CHECK (legacy_ack_through >= 0),"
            " legacy_message_through INTEGER NOT NULL"
            " CHECK (legacy_message_through >= 0)"
            ")"
        )
        provenance_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(channel_provenance)")
        }
        required_provenance_columns = {
            "singleton",
            "legacy_ack_through",
            "legacy_message_through",
        }
        if mode == "current" and not required_provenance_columns.issubset(provenance_columns):
            raise JournalDamaged("schema 7 channel provenance cutoff is missing")
        if "legacy_message_through" not in provenance_columns:
            if mode == "current":
                raise JournalDamaged("schema 7 channel provenance cutoff is missing")
            connection.execute(
                "ALTER TABLE channel_provenance ADD COLUMN legacy_message_through INTEGER"
            )
            if legacy_message_through is None:
                raise JournalDamaged("schema 7 channel messages have no provenance cutoff")
            connection.execute(
                "UPDATE channel_provenance SET legacy_message_through = ?",
                (legacy_message_through,),
            )
        provenance = connection.execute(
            "SELECT singleton, legacy_ack_through, legacy_message_through FROM channel_provenance"
        ).fetchall()
        if not provenance:
            if mode == "current":
                raise JournalDamaged("schema 7 channel provenance cutoff is missing")
            maximum_ack = _channel_ack_sequence_max(connection)
            maximum_message = _channel_message_sequence_max(connection)
            if legacy_ack_through is None and maximum_ack != 0:
                raise JournalDamaged("schema 7 channel acknowledgements have no provenance cutoff")
            if legacy_message_through is None and maximum_message != 0:
                raise JournalDamaged("schema 7 channel messages have no provenance cutoff")
            ack_cutoff = legacy_ack_through if legacy_ack_through is not None else 0
            message_cutoff = legacy_message_through if legacy_message_through is not None else 0
            connection.execute(
                "INSERT INTO channel_provenance"
                " (singleton, legacy_ack_through, legacy_message_through)"
                " VALUES (1, ?, ?)",
                (ack_cutoff, message_cutoff),
            )
        elif (
            len(provenance) != 1
            or type(provenance[0][0]) is not int
            or provenance[0][0] != 1
            or type(provenance[0][1]) is not int
            or provenance[0][1] < 0
            or type(provenance[0][2]) is not int
            or provenance[0][2] < 0
            or (legacy_ack_through is not None and provenance[0][1] != legacy_ack_through)
            or (legacy_message_through is not None and provenance[0][2] != legacy_message_through)
        ):
            raise JournalDamaged("channel provenance cutoff is invalid")
        if mode == "migrate":
            current_reply = connection.execute(
                "SELECT 1 FROM channel_messages"
                " WHERE command_id IS NOT NULL"
                " OR reply_provenance_version IS NOT NULL LIMIT 1"
            ).fetchone()
            if current_reply is not None:
                raise JournalDamaged("schema 6 channel reply carries current provenance")
        index = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index'"
            " AND name = 'channel_reply_command_unique'"
        ).fetchone()
        if mode == "current" and index is None:
            raise JournalDamaged("schema 7 channel reply provenance index is missing")
        try:
            if index is None:
                connection.execute(
                    "CREATE UNIQUE INDEX channel_reply_command_unique"
                    " ON channel_messages(command_id) WHERE command_id IS NOT NULL"
                )
        except sqlite3.IntegrityError as exc:
            raise JournalDamaged("one channel command wrote more than one reply") from exc
        index = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index'"
            " AND name = 'channel_reply_command_unique'"
        ).fetchone()
        index_rows = connection.execute("PRAGMA index_list(channel_messages)").fetchall()
        index_metadata = next(
            (row for row in index_rows if row[1] == "channel_reply_command_unique"),
            None,
        )
        index_columns = [
            row[2] for row in connection.execute("PRAGMA index_info(channel_reply_command_unique)")
        ]
        if (
            index_metadata is None
            or index_metadata[2] != 1
            or index_metadata[4] != 1
            or index_columns != ["command_id"]
            or index is None
            or not _durable_text(index["sql"], fact="channel reply provenance index").endswith(
                "WHERE command_id IS NOT NULL"
            )
        ):
            raise JournalDamaged("schema 7 channel reply provenance index is invalid")

    @staticmethod
    def _ensure_v7_effect_schema(
        connection: sqlite3.Connection,
        *,
        mode: Literal["fresh", "migrate", "current"],
    ) -> None:
        """Add exact outcome pointers and seal pre-v7 terminal effect facts."""

        columns = {row[1] for row in connection.execute("PRAGMA table_info(effects)")}
        missing_provenance = not {
            "outcome_run_id",
            "outcome_event_seq",
        }.issubset(columns)
        had_seal_table = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'legacy_effect_seals'"
            ).fetchone()
            is not None
        )
        if mode == "current":
            if missing_provenance:
                raise JournalDamaged("schema 7 effect outcome provenance is missing")
            if not had_seal_table:
                raise JournalDamaged("schema 7 legacy effect seals are missing")
            validate_legacy_effect_seal_inventory(connection)
            return
        if "outcome_run_id" not in columns:
            connection.execute("ALTER TABLE effects ADD COLUMN outcome_run_id TEXT")
        if "outcome_event_seq" not in columns:
            connection.execute("ALTER TABLE effects ADD COLUMN outcome_event_seq INTEGER")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS legacy_effect_seals ("
            " idempotency_key TEXT PRIMARY KEY,"
            " terminal_fact_hash TEXT NOT NULL"
            ")"
        )
        if mode != "migrate":
            return
        rows = connection.execute("SELECT * FROM effects").fetchall()
        terminal_count = 0
        for row in rows:
            has_receipt = row["receipt_json"] is not None
            has_receipt_time = row["receipted_at"] is not None
            if has_receipt != has_receipt_time:
                raise JournalDamaged(
                    f"legacy effect {row['idempotency_key']!r} has a torn terminal fact"
                )
            if row["outcome_run_id"] is not None or row["outcome_event_seq"] is not None:
                raise JournalDamaged(
                    f"legacy effect {row['idempotency_key']!r} carries current provenance"
                )
            if not has_receipt:
                continue
            terminal_count += 1
            seal = str(legacy_effect_seal(row))
            prior = connection.execute(
                "SELECT * FROM legacy_effect_seals WHERE idempotency_key = ?",
                (row["idempotency_key"],),
            ).fetchone()
            if prior is None:
                connection.execute(
                    "INSERT INTO legacy_effect_seals"
                    " (idempotency_key, terminal_fact_hash) VALUES (?, ?)",
                    (row["idempotency_key"], seal),
                )
            elif (
                _durable_text(
                    prior["idempotency_key"],
                    fact="legacy effect sealed identity",
                )
                != _durable_text(
                    row["idempotency_key"],
                    fact="legacy effect row identity",
                )
                or _durable_text(
                    prior["terminal_fact_hash"],
                    fact="legacy effect terminal seal",
                )
                != seal
            ):
                raise JournalDamaged(
                    f"legacy effect {row['idempotency_key']!r} seal is contradictory"
                )
        seal_count = _durable_sequence(
            connection.execute("SELECT COUNT(*) AS retained FROM legacy_effect_seals").fetchone()[
                "retained"
            ],
            fact="legacy effect seal count",
            allow_zero=True,
            kind="count",
        )
        if seal_count != terminal_count:
            raise JournalDamaged(
                "legacy effect seal inventory has an orphan or ineligible primary fact"
            )
        validate_legacy_effect_seal_inventory(connection)

    @staticmethod
    def _ensure_v7_lease_schema(
        connection: sqlite3.Connection,
        *,
        mode: Literal["fresh", "migrate", "current"],
    ) -> None:
        """Seal the exact base and initial lifecycle of every pre-v7 lease."""

        had_seal_table = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table'"
                " AND name = 'legacy_capability_lease_seals'"
            ).fetchone()
            is not None
        )
        if mode == "current" and not had_seal_table:
            raise JournalDamaged("schema 7 capability lease seals are missing")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS legacy_capability_lease_seals ("
            " lease_id TEXT NOT NULL,"
            " acquisition_epoch INTEGER NOT NULL,"
            " run_id TEXT NOT NULL,"
            " base_hash TEXT NOT NULL,"
            " initial_lifecycle_json TEXT NOT NULL,"
            " PRIMARY KEY (lease_id, acquisition_epoch)"
            ")"
        )
        if mode == "current":
            validate_legacy_lease_seal_inventory(connection)
            return
        if mode != "migrate":
            return
        rows = connection.execute("SELECT * FROM capability_leases").fetchall()
        for row in rows:
            lease_id = _durable_text(
                row["lease_id"],
                fact="legacy capability lease identity",
            )
            acquisition_epoch = _durable_sequence(
                row["acquisition_epoch"],
                fact=f"legacy capability lease {lease_id!r} acquisition epoch",
            )
            base_hash = str(legacy_lease_base_hash(row))
            lifecycle = legacy_lease_initial_lifecycle_json(row)
            run_id = _durable_text(
                row["run_id"],
                fact=(
                    f"legacy capability lease {row['lease_id']!r}/"
                    f"{row['acquisition_epoch']!r} run identity"
                ),
            )
            prior = connection.execute(
                "SELECT * FROM legacy_capability_lease_seals"
                " WHERE lease_id = ? AND acquisition_epoch = ?",
                (lease_id, acquisition_epoch),
            ).fetchone()
            if prior is None:
                connection.execute(
                    "INSERT INTO legacy_capability_lease_seals"
                    " (lease_id, acquisition_epoch, run_id, base_hash,"
                    " initial_lifecycle_json) VALUES (?, ?, ?, ?, ?)",
                    (
                        lease_id,
                        acquisition_epoch,
                        run_id,
                        base_hash,
                        lifecycle,
                    ),
                )
                continue
            if (
                _durable_text(prior["lease_id"], fact="legacy lease sealed identity") != lease_id
                or _durable_sequence(
                    prior["acquisition_epoch"],
                    fact=f"legacy lease {lease_id!r} sealed acquisition epoch",
                )
                != acquisition_epoch
                or _durable_text(prior["run_id"], fact="legacy lease sealed run identity") != run_id
                or _durable_text(prior["base_hash"], fact="legacy lease sealed base") != base_hash
                or _durable_text(
                    prior["initial_lifecycle_json"],
                    fact="legacy lease sealed initial lifecycle",
                )
                != lifecycle
            ):
                raise JournalDamaged(
                    f"legacy capability lease {lease_id!r}/"
                    f"{acquisition_epoch!r} seal is contradictory"
                )
        seal_count = _durable_sequence(
            connection.execute(
                "SELECT COUNT(*) AS retained FROM legacy_capability_lease_seals"
            ).fetchone()["retained"],
            fact="legacy capability lease seal count",
            allow_zero=True,
            kind="count",
        )
        if seal_count != len(rows):
            raise JournalDamaged(
                "legacy capability lease seal inventory has an orphan primary fact"
            )
        validate_legacy_lease_seal_inventory(connection)

    @staticmethod
    def _ensure_v7_run_schema(
        connection: sqlite3.Connection,
        *,
        mode: Literal["fresh", "migrate", "current"],
    ) -> None:
        """Make command ownership of every origin-bearing run positive."""

        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        if "creation_command_id" not in columns:
            if mode == "current":
                raise JournalDamaged("schema 7 runs have no creation-command provenance column")
            connection.execute("ALTER TABLE runs ADD COLUMN creation_command_id TEXT")
        origins = connection.execute(
            "SELECT r.run_id, r.creation_command_id, o.origin_json"
            " FROM runs AS r LEFT JOIN run_origins AS o ON o.run_id = r.run_id"
        ).fetchall()
        for row in origins:
            run_id = RunId(_durable_text(row["run_id"], fact="run identity"))
            raw_origin = row["origin_json"]
            raw_marker = row["creation_command_id"]
            if raw_origin is None:
                if raw_marker is not None:
                    raise JournalDamaged(
                        f"run {run_id!r} names a creation command without an origin"
                    )
                continue
            origin = _durable_model(
                RunOrigin,
                _durable_text(raw_origin, fact=f"run {run_id!r} origin"),
                fact=f"run {run_id!r} origin",
            )
            if run_id_for_command(origin.command_id) != run_id:
                raise JournalDamaged(f"run {run_id!r} origin has a non-derived creation command")
            if raw_marker is None:
                if mode != "migrate":
                    raise JournalDamaged(f"run {run_id!r} origin has no creation command marker")
                connection.execute(
                    "UPDATE runs SET creation_command_id = ? WHERE run_id = ?",
                    (origin.command_id, run_id),
                )
                continue
            marker = _durable_text(
                raw_marker,
                fact=f"run {run_id!r} creation command identity",
            )
            if marker != origin.command_id:
                raise JournalDamaged(
                    f"run {run_id!r} origin contradicts its creation command marker"
                )

    @staticmethod
    def _ensure_v7_fact_seal_schema(
        connection: sqlite3.Connection,
        *,
        mode: Literal["fresh", "migrate", "current"],
    ) -> None:
        """Create the shared mechanical seal table and stamp pre-v7 facts."""

        had_seal_table = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'durable_fact_seals'"
            ).fetchone()
            is not None
        )
        if mode == "current" and not had_seal_table:
            raise JournalDamaged("schema 7 durable fact seals are missing")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS durable_fact_seals ("
            " family TEXT NOT NULL,"
            " fact_key TEXT NOT NULL,"
            " selector TEXT NOT NULL,"
            " fact_hash TEXT NOT NULL,"
            " PRIMARY KEY (family, fact_key),"
            " UNIQUE (family, selector)"
            ")"
        )
        if mode == "migrate":
            # Seal in dependency order: later facts may prove their authority
            # through the canonical projection of an earlier durable world.
            for row in connection.execute("SELECT * FROM commands").fetchall():
                seal_command_claim(connection, row)
                seal_command_phases(connection, row)
            seal_resume_plan_eras(connection)
            for row in connection.execute("SELECT * FROM manifests").fetchall():
                seal_manifest(connection, row)
            for row in connection.execute(
                "SELECT r.*, o.origin_json FROM runs AS r"
                " LEFT JOIN run_origins AS o ON o.run_id = r.run_id"
            ).fetchall():
                seal_run_world(connection, row)
            for row in connection.execute("SELECT * FROM attestations").fetchall():
                seal_attestation(connection, row)
            for row in connection.execute("SELECT * FROM approvals").fetchall():
                seal_approval(connection, row)
            for row in connection.execute("SELECT * FROM components").fetchall():
                seal_component_registration(connection, row)
            for row in connection.execute("SELECT * FROM promotions").fetchall():
                seal_promotion(connection, row, historical=True)
            for row in connection.execute("SELECT * FROM effects").fetchall():
                seal_effect_preparation(connection, row)
            for row in connection.execute("SELECT * FROM events").fetchall():
                seal_event(connection, row)
            seal_legacy_effect_outcomes(connection)
            seal_migrated_resume_attempts(connection)
            for row in connection.execute("SELECT * FROM checkpoints").fetchall():
                seal_checkpoint(connection, row)
            # The row-era cut is independent evidence used while decoding
            # every migrated acknowledgement and reply, so seal it first.
            seal_channel_provenance(connection)
            for row in connection.execute(
                "SELECT * FROM channel_messages ORDER BY message_seq"
            ).fetchall():
                seal_channel_message(connection, row)
            for row in connection.execute(
                "SELECT * FROM channel_acks ORDER BY ack_seq"
            ).fetchall():
                seal_channel_ack(connection, row)
        if mode == "fresh":
            seal_channel_provenance(connection)

    @staticmethod
    def _validate_v7_fact_inventory(connection: sqlite3.Connection) -> None:
        """Prove the complete current graph after every migration seal exists."""

        resume_plan_era_count = validate_command_claim_inventory(connection)
        for row in connection.execute("SELECT * FROM manifests").fetchall():
            require_manifest_seal(connection, row)
        validate_event_seal_inventory(connection)
        validate_checkpoint_seal_inventory(connection)
        validate_attestation_seal_inventory(connection)
        resume_provenance_count = validate_run_fact_inventory(connection)
        for row in connection.execute("SELECT * FROM approvals").fetchall():
            stored_approval_fact_from_row(connection, row)
        validate_registry_seal_inventory(connection)
        legacy_effect_outcome_count = validate_effect_fact_inventory(connection)
        validate_capability_lease_inventory(connection)
        validate_channel_fact_seal_inventory(connection)
        planned = command_plan_exists("plan_json")
        expected_count = _durable_sequence(
            connection.execute(
                "SELECT"
                " (SELECT COUNT(*) FROM attestations)"
                " + (SELECT COUNT(*) FROM commands)"
                f" + (SELECT COUNT(*) FROM commands WHERE {planned})"
                " + (SELECT COUNT(*) FROM commands"
                "    WHERE state IN ('committed', 'rejected'))"
                " + (SELECT COUNT(*) FROM approvals)"
                " + (SELECT COUNT(*) FROM components)"
                " + (SELECT COUNT(*) FROM promotions)"
                " + (SELECT COUNT(*) FROM effects)"
                " + (SELECT COUNT(*) FROM manifests)"
                " + (SELECT COUNT(*) FROM runs)"
                " + (SELECT COUNT(*) FROM events)"
                " + (SELECT COUNT(*) FROM checkpoints)"
                " + (SELECT COUNT(*) FROM channel_messages)"
                " + (SELECT COUNT(*) FROM channel_acks)"
                " + 1 AS expected"
            ).fetchone()["expected"],
            fact="durable fact seal expected count",
            allow_zero=True,
            kind="count",
        ) + legacy_effect_outcome_count + resume_plan_era_count + resume_provenance_count
        validate_durable_fact_seal_inventory(
            connection,
            known_families=_DURABLE_FACT_SEAL_FAMILIES,
            expected_count=expected_count,
        )

    @staticmethod
    def _migrate_m6_to_m7(connection: sqlite3.Connection) -> None:
        """Add schema-7 provenance columns, era cutoffs, and positive seals.

        A request already records the attestation that admitted it. A reply now
        records the command that did, so an exact retry of one command can be
        told apart from a second command that lost the race — ADR 0014 admits
        one reply and owes the loser a typed conflict, identical bytes included.

        Existing replies keep both NULLs. Existing acknowledgements receive
        the additive marker ``0`` and the migration records the maximum legacy
        message and acknowledgement sequences independently. The same atomic
        climb seals every retained immutable fact and records the legacy effect
        and lease eras. Current replies write command identity plus
        provenance version 1 above the message cutoff. Only two NULLs at or
        below that cutoff beside a legacy acknowledgement therefore prove a
        schema-6 reply; erasing a current command link cannot mimic history.
        Current acknowledgements write
        provenance version 1 above that fixed sequence cutoff and require their
        named command; version 0 at or below the cutoff is the positive
        schema-6 history shape whether its command row survives or not. A v6
        reply's writer remains recoverable from the request acknowledgement
        that its reply path atomically claimed.
        """

        connection.execute("BEGIN IMMEDIATE")
        # The version that chose this step was read before the write lock was
        # held, so another process may have climbed the same rung in between.
        # This migration stamps every row it finds as legacy; re-running it on
        # a database that is already current would call current provenance a
        # partly migrated schema-6 contradiction, and the loser of an ordinary
        # race would condemn a healthy store. Re-reading under the lock is what
        # makes the ladder a ladder rather than a hope.
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) != 6:
            connection.rollback()
            return
        legacy_ack_through = _channel_ack_sequence_max(connection)
        legacy_message_through = _channel_message_sequence_max(connection)
        _SqliteSchemaMixin._ensure_v7_channel_schema(
            connection,
            mode="migrate",
            legacy_ack_through=legacy_ack_through,
            legacy_message_through=legacy_message_through,
        )
        invalid = connection.execute(
            "SELECT 1 FROM channel_acks WHERE ack_provenance_version"
            " IS NOT NULL AND ack_provenance_version != 0 LIMIT 1"
        ).fetchone()
        if invalid is not None:
            raise JournalDamaged(
                "partly migrated schema-6 acknowledgements carry current provenance"
            )
        # The migration stamps every pre-v7 acknowledgement with a positive
        # era before hashing it.  Current rows are version 1; NULL is never a
        # durable compatibility signal after the climb.
        connection.execute(
            "UPDATE channel_acks SET ack_provenance_version = 0"
            " WHERE ack_provenance_version IS NULL"
        )
        _SqliteSchemaMixin._ensure_v7_effect_schema(
            connection,
            mode="migrate",
        )
        _SqliteSchemaMixin._ensure_v7_run_schema(
            connection,
            mode="migrate",
        )
        _SqliteSchemaMixin._ensure_v7_fact_seal_schema(
            connection,
            mode="migrate",
        )
        # Legacy lease classification reads its acquisition events through the
        # canonical sealed projector, so event seals precede lease-era seals.
        _SqliteSchemaMixin._ensure_v7_lease_schema(
            connection,
            mode="migrate",
        )
        _SqliteSchemaMixin._validate_v7_fact_inventory(connection)
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

        try:
            manifest = parse_manifest_json(manifest_json)
            observed_input_hash = digest("inputs", 1, inputs)
        except (TypeError, ValueError) as exc:
            raise ContractViolation("run creation requires one valid sealed manifest") from exc
        if (
            manifest.manifest_hash != manifest_hash
            or manifest.input_hash != input_hash
            or observed_input_hash != input_hash
        ):
            raise ContractViolation("run creation manifest, identity, and exact inputs contradict")

        with self._txn() as connection:
            existing_manifest = retained_manifest(
                connection,
                manifest_hash=manifest_hash,
                fact=f"manifest {manifest_hash}",
            )
            if existing_manifest is None:
                connection.execute(
                    "INSERT INTO manifests (manifest_hash, manifest_json) VALUES (?, ?)",
                    (str(manifest_hash), manifest_json),
                )
                retained = connection.execute(
                    "SELECT manifest_hash, manifest_json FROM manifests WHERE manifest_hash = ?",
                    (str(manifest_hash),),
                ).fetchone()
                if retained is None:
                    raise JournalDamaged(f"manifest {manifest_hash} disappeared during retention")
                seal_manifest(connection, retained)
            elif existing_manifest[1] != manifest_json and not _manifest_semantically_equal(
                existing_manifest[1], manifest_json
            ):
                raise JournalDamaged(
                    f"manifest {manifest_hash} already stored with different semantics"
                )
            run = connection.execute(
                "SELECT r.*, o.origin_json FROM runs AS r"
                " LEFT JOIN run_origins AS o ON o.run_id = r.run_id"
                " WHERE r.run_id = ?",
                (run_id,),
            ).fetchone()
            if run is not None:
                validated_run_world(connection, run)
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
                expected_command = origin.command_id if origin is not None else None
                if run["creation_command_id"] != expected_command:
                    raise JournalDamaged(
                        f"run {run_id!r} already exists with different command provenance"
                    )
                return
            if (
                durable_fact_seal(
                    connection,
                    family=RUN_WORLD_FACT_FAMILY,
                    fact_key=str(run_id),
                    selector=str(run_id),
                )
                is not None
            ):
                raise JournalDamaged(f"run {run_id!r} has an immutable-world seal without its row")
            register_run_origin_guard(connection)
            validate_no_orphan_run_facts(connection)
            connection.execute(
                "INSERT INTO runs (run_id, manifest_hash, input_hash, inputs_json,"
                " status, created_at, creation_command_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    str(manifest_hash),
                    str(input_hash),
                    canonical_json(inputs),
                    RunStatus.PENDING.value,
                    self._now_iso(),
                    origin.command_id if origin is not None else None,
                ),
            )
            if origin is not None:
                connection.execute(
                    "INSERT INTO run_origins (run_id, origin_json) VALUES (?, ?)",
                    (run_id, origin.model_dump_json()),
                )
            created = connection.execute(
                "SELECT r.*, o.origin_json FROM runs AS r"
                " LEFT JOIN run_origins AS o ON o.run_id = r.run_id"
                " WHERE r.run_id = ?",
                (run_id,),
            ).fetchone()
            if created is None:
                raise JournalDamaged(f"run {run_id!r} disappeared during creation")
            seal_run_world(connection, created)
            validated_run_world(connection, created)
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
                checkpoint = _durable_model(
                    Checkpoint,
                    row["checkpoint_json"],
                    fact=f"checkpoint {row['run_id']!r}/{row['path_key']!r}",
                )
                conn.execute(
                    "UPDATE checkpoints SET identity = ? WHERE run_id = ? AND path_key = ?",
                    (_checkpoint_identity(checkpoint), row["run_id"], row["path_key"]),
                )
        conn.executescript(_SCHEMA)  # creates the tables M1 lacked
        # backfill durable inputs from RunStarted events (M1's archaeology, once)
        for row in conn.execute("SELECT run_id FROM runs").fetchall():
            run_id = _durable_text(
                row["run_id"],
                fact=f"M1 run identity {row['run_id']!r}",
            )
            event = conn.execute(
                "SELECT payload FROM events WHERE run_id = ? AND kind = 'RunStarted'"
                " ORDER BY seq ASC LIMIT 1",
                (run_id,),
            ).fetchone()
            if event is not None and event["payload"] is not None:
                payload = _durable_json(
                    event["payload"],
                    fact=f"RunStarted event for {run_id!r}",
                )
                if not isinstance(payload, dict):
                    raise JournalDamaged(
                        f"RunStarted event for {run_id!r} carries a non-object payload"
                    )
                inputs = payload.get("inputs")
                if isinstance(inputs, dict):
                    conn.execute(
                        "UPDATE runs SET inputs_json = ? WHERE run_id = ?",
                        (canonical_json(inputs), run_id),
                    )
            seq_row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq,"
                " COALESCE(MAX(CASE WHEN typeof(seq) != 'integer' OR seq <= 0"
                " THEN 1 ELSE 0 END), 0) AS damaged"
                " FROM events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if type(seq_row["damaged"]) is not int or seq_row["damaged"] not in (0, 1):
                raise JournalDamaged(
                    f"M1 event sequence damage probe for run {run_id!r} is invalid"
                )
            if seq_row["damaged"] == 1:
                raise JournalDamaged(
                    f"M1 run {run_id!r} contains an invalid durable event sequence"
                )
            maximum = _durable_sequence(
                seq_row["seq"],
                fact=f"M1 run {run_id!r} maximum event sequence",
                allow_zero=True,
                kind="event sequence",
            )
            conn.execute(
                "UPDATE runs SET next_event_seq = ? WHERE run_id = ?",
                (maximum, run_id),
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
            payload = _durable_json(
                row["scope_json"],
                fact=(
                    f"capability lease {row['lease_id']!r} epoch {row['acquisition_epoch']} scope"
                ),
            )
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
