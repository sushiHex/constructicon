"""One exact SQLite boundary for a run's immutable creation world."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from constructicon.core.address import RunId
from constructicon.core.control import (
    ResolutionLock,
    ResolutionPin,
    RunCreationPlan,
    RunOrigin,
    RunRecord,
    run_id_for_command,
    validated_run_creation_command,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest, json_value
from constructicon.core.manifest import ExecutionManifest, parse_manifest_json
from constructicon.core.run import TERMINAL_EVENT_STATUSES, TERMINAL_STATUS_EVENTS, RunStatus
from constructicon.substrate.journal._sqlite_attestations import (
    ATTESTATION_FACT_FAMILY,
    LEGACY_ATTESTATION_FACT_FAMILY,
    attestation_from_json,
)
from constructicon.substrate.journal._sqlite_base import (
    _durable_digest,
    _durable_event_seq,
    _durable_json,
    _durable_model,
    _durable_run_fields,
    _durable_sequence,
    _durable_sqlite_boolean,
    _durable_text,
    _run_state_fields,
)
from constructicon.substrate.journal._sqlite_commands import (
    command_for_id,
)
from constructicon.substrate.journal._sqlite_execution_facts import (
    stored_event_from_row,
    validate_event_seal_inventory,
    validate_resume_attempt_provenance,
)
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    durable_fact_seal,
    require_durable_fact_seal,
    store_durable_fact_seal,
)
from constructicon.substrate.journal._sqlite_registry import (
    LEGACY_PROMOTION_FACT_FAMILY,
    PROMOTION_FACT_FAMILY,
)

RUN_WORLD_FACT_FAMILY = "run_world"
MANIFEST_FACT_FAMILY = "manifest"


@dataclass(frozen=True)
class ValidatedRunWorld:
    run_id: RunId
    manifest: ExecutionManifest
    inputs: dict[str, Any]
    origin: RunOrigin | None
    creation_plan: RunCreationPlan | None


def _run_world_fact_hash_values(
    run_id_value: object,
    manifest_hash_value: object,
    input_hash_value: object,
    inputs_json_value: object,
    created_at_value: object,
    creation_command_value: object,
    origin_value: object,
) -> Digest:
    run_id = _durable_text(run_id_value, fact="run world identity")
    return durable_fact_hash(
        RUN_WORLD_FACT_FAMILY,
        {
            "run_id": run_id,
            "manifest_hash": str(
                _durable_digest(
                    manifest_hash_value,
                    fact=f"run {run_id!r} sealed manifest identity",
                )
            ),
            "input_hash": str(
                _durable_digest(
                    input_hash_value,
                    fact=f"run {run_id!r} sealed input identity",
                )
            ),
            "inputs_json": _durable_text(
                inputs_json_value,
                fact=f"run {run_id!r} sealed input bytes",
            ),
            "created_at": _durable_text(
                created_at_value,
                fact=f"run {run_id!r} sealed creation time",
            ),
            "creation_command_id": (
                _durable_text(
                    creation_command_value,
                    fact=f"run {run_id!r} sealed creation command",
                )
                if creation_command_value is not None
                else None
            ),
            "origin_json": (
                _durable_text(
                    origin_value,
                    fact=f"run {run_id!r} sealed origin bytes",
                )
                if origin_value is not None
                else None
            ),
        },
    )


def run_world_fact_hash(row: sqlite3.Row) -> Digest:
    """Hash the exact immutable row fields observed by run creation."""

    return _run_world_fact_hash_values(
        row["run_id"],
        row["manifest_hash"],
        row["input_hash"],
        row["inputs_json"],
        row["created_at"],
        row["creation_command_id"],
        row["origin_json"],
    )


def _sqlite_run_world_fact_hash(
    run_id: object,
    manifest_hash: object,
    input_hash: object,
    inputs_json: object,
    created_at: object,
    creation_command_id: object,
    origin_json: object,
) -> str | None:
    try:
        return str(
            _run_world_fact_hash_values(
                run_id,
                manifest_hash,
                input_hash,
                inputs_json,
                created_at,
                creation_command_id,
                origin_json,
            )
        )
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return None


def seal_run_world(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    run_id = _durable_text(row["run_id"], fact="run world identity")
    store_durable_fact_seal(
        connection,
        family=RUN_WORLD_FACT_FAMILY,
        fact_key=run_id,
        selector=run_id,
        fact_hash=run_world_fact_hash(row),
    )


def require_run_world_seal(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    run_id = _durable_text(row["run_id"], fact="run world identity")
    require_durable_fact_seal(
        connection,
        family=RUN_WORLD_FACT_FAMILY,
        fact_key=run_id,
        selector=run_id,
        fact_hash=run_world_fact_hash(row),
    )


def manifest_fact_hash(row: sqlite3.Row) -> Digest:
    """Seal the exact retained bytes behind one content-addressed manifest."""

    manifest_hash = _durable_text(
        row["manifest_hash"],
        fact="retained manifest identity",
    )
    return durable_fact_hash(
        MANIFEST_FACT_FAMILY,
        {
            "manifest_hash": manifest_hash,
            "manifest_json": _durable_text(
                row["manifest_json"],
                fact=f"manifest {manifest_hash!r} retained bytes",
            ),
        },
    )


def seal_manifest(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    manifest_hash = _durable_text(
        row["manifest_hash"],
        fact="retained manifest identity",
    )
    store_durable_fact_seal(
        connection,
        family=MANIFEST_FACT_FAMILY,
        fact_key=manifest_hash,
        selector=manifest_hash,
        fact_hash=manifest_fact_hash(row),
    )


def require_manifest_seal(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    manifest_hash = _durable_text(
        row["manifest_hash"],
        fact="retained manifest identity",
    )
    require_durable_fact_seal(
        connection,
        family=MANIFEST_FACT_FAMILY,
        fact_key=manifest_hash,
        selector=manifest_hash,
        fact_hash=manifest_fact_hash(row),
    )


def _retained_manifest(
    connection: sqlite3.Connection,
    *,
    run_id: RunId,
    manifest_hash: Digest,
    input_hash: Digest,
) -> ExecutionManifest:
    stored = retained_manifest(
        connection,
        manifest_hash=manifest_hash,
        fact=f"run {run_id!r} retained manifest",
    )
    if stored is None:
        raise ValueError("run names no retained manifest")
    manifest, _raw = stored
    if manifest.input_hash != input_hash:
        raise ValueError("run world contradicts its retained manifest")
    return manifest


def _manifest_identity(raw: object) -> str | None:
    """Return a manifest's content-derived locator for identity-first SQL."""

    try:
        manifest_json = _durable_text(raw, fact="manifest bytes")
        return str(parse_manifest_json(manifest_json).manifest_hash)
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return None


def retained_manifest(
    connection: sqlite3.Connection,
    *,
    manifest_hash: Digest,
    fact: str,
) -> tuple[ExecutionManifest, str] | None:
    """Load one manifest by its content identity and prove its relational key."""

    connection.create_function(
        "constructicon_manifest_identity",
        1,
        _manifest_identity,
        deterministic=True,
    )
    rows = connection.execute(
        "SELECT manifest_hash, manifest_json FROM manifests"
        " WHERE manifest_hash = ?"
        " OR constructicon_manifest_identity(manifest_json) = ?"
        " OR constructicon_manifest_identity(manifest_json) IS NULL LIMIT 2",
        (str(manifest_hash), str(manifest_hash)),
    ).fetchall()
    if not rows:
        sealed = durable_fact_seal(
            connection,
            family=MANIFEST_FACT_FAMILY,
            fact_key=str(manifest_hash),
            selector=str(manifest_hash),
        )
        referenced = connection.execute(
            "SELECT 1 FROM runs WHERE manifest_hash = ? LIMIT 1",
            (str(manifest_hash),),
        ).fetchone()
        if sealed is not None:
            raise JournalDamaged(f"{fact} has a positive seal without its row")
        if referenced is not None:
            raise JournalDamaged(f"{fact} has an independent reference without its row")
        return None
    if len(rows) != 1:
        raise JournalDamaged(f"{fact} has more than one durable identity")
    row = rows[0]
    try:
        stored_hash = _durable_digest(
            row["manifest_hash"],
            fact=f"{fact} relational identity",
        )
        manifest_json = _durable_text(
            row["manifest_json"],
            fact=f"{fact} bytes",
        )
        manifest = parse_manifest_json(manifest_json)
        if stored_hash != manifest_hash or manifest.manifest_hash != manifest_hash:
            raise ValueError("manifest contradicts its relational identity")
        require_manifest_seal(connection, row)
        return manifest, manifest_json
    except JournalDamaged:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(f"{fact} is not a valid durable manifest") from exc


def _validate_clone_source_world(
    connection: sqlite3.Connection,
    *,
    plan: RunCreationPlan,
) -> None:
    source_lock = plan.source_lock
    if source_lock is None:
        return  # the exact historical bare plan shape predates source locks
    source_row = connection.execute(
        "SELECT r.*, o.origin_json FROM runs AS r LEFT JOIN run_origins AS o"
        " ON o.run_id = r.run_id WHERE r.run_id = ?",
        (source_lock.run_id,),
    ).fetchone()
    if source_row is None:
        raise ValueError("clone source run disappeared")
    require_run_world_seal(connection, source_row)
    source_manifest_hash = _durable_digest(
        source_row["manifest_hash"],
        fact=f"clone source {source_lock.run_id!r} manifest identity",
    )
    source_input_hash = _durable_digest(
        source_row["input_hash"],
        fact=f"clone source {source_lock.run_id!r} input identity",
    )
    raw_source_inputs = _durable_json(
        source_row["inputs_json"],
        fact=f"clone source {source_lock.run_id!r} inputs",
    )
    if not isinstance(raw_source_inputs, dict):
        raise ValueError("clone source inputs are not an object")
    source_inputs = {str(name): value for name, value in raw_source_inputs.items()}
    if (
        set(source_inputs) != set(raw_source_inputs)
        or digest("inputs", 1, source_inputs) != source_input_hash
    ):
        raise ValueError("clone source inputs contradict their identity")
    source_manifest = _retained_manifest(
        connection,
        run_id=source_lock.run_id,
        manifest_hash=source_manifest_hash,
        input_hash=source_input_hash,
    )
    expected_graph_hash = digest(
        "graph-proposal",
        1,
        source_manifest.source_graph.model_dump(mode="json"),
    )
    if (
        source_lock.manifest_hash != source_manifest_hash
        or source_lock.input_hash != source_input_hash
        or source_lock.source_graph_hash != expected_graph_hash
        or canonical_json(plan.inputs) != canonical_json(source_inputs)
        or canonical_json(json_value(plan.manifest.source_graph.model_dump(mode="json")))
        != canonical_json(json_value(source_manifest.source_graph.model_dump(mode="json")))
    ):
        raise ValueError("clone plan contradicts its immutable source world")
    expected_pins = tuple(
        ResolutionPin(
            scope=resolution.scope,
            component=resolution.component,
            version=plan.origin.overrides.get(
                resolution.component,
                resolution.resolved_version,
            ),
        )
        for resolution in source_manifest.resolved_components
    )
    plan_pins = tuple(
        ResolutionPin(
            scope=resolution.scope,
            component=resolution.component,
            version=resolution.resolved_version,
        )
        for resolution in plan.manifest.resolved_components
    )
    if plan.origin.kind == "reproduce":
        if (
            plan.origin.overrides
            or source_lock.resolution_lock is not None
            or canonical_json(json_value(plan.manifest.model_dump(mode="json")))
            != canonical_json(json_value(source_manifest.model_dump(mode="json")))
        ):
            raise ValueError("reproduce plan changed its immutable source world")
        return
    expected_lock = ResolutionLock(
        source_manifest_hash=source_manifest.manifest_hash,
        pins=expected_pins,
    )
    plan_lock = ResolutionLock(
        source_manifest_hash=source_manifest.manifest_hash,
        pins=plan_pins,
    )
    if source_lock.resolution_lock != expected_lock or plan_lock != expected_lock:
        raise ValueError("counterfactual plan contradicts its exact source lock")


def run_origin_from_json(origin_json: object, *, run_id: RunId) -> RunOrigin:
    """Decode one origin and prove its command-derived run identity."""

    try:
        origin = _durable_model(
            RunOrigin,
            _durable_text(origin_json, fact=f"run origin for {run_id!r}"),
            fact=f"run origin for {run_id!r}",
        )
        if run_id_for_command(origin.command_id) != run_id:
            raise ValueError("run origin command does not derive this run identity")
        return origin
    except JournalDamaged:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(f"run origin for {run_id!r} is not a valid durable record") from exc


RUN_LIFECYCLE_EVENT_COLUMNS = (
    " e.seq AS lifecycle_event_seq,"
    " e.kind AS lifecycle_event_kind,"
    " e.path_json AS lifecycle_event_path_json,"
    " e.payload AS lifecycle_event_payload,"
    " e.created_at AS lifecycle_event_created_at,"
    " EXISTS (SELECT 1 FROM events AS newer"
    " WHERE newer.run_id = r.run_id AND newer.seq > r.next_event_seq)"
    " AS lifecycle_has_newer_event"
)

TERMINAL_EVENT_KINDS = tuple(TERMINAL_EVENT_STATUSES)
RUN_LIFECYCLE_ANOMALY = (
    "typeof(r.status) != 'text'"
    " OR r.status NOT IN ('pending', 'running', 'parked', 'failed',"
    " 'succeeded', 'cancelled')"
    " OR typeof(r.next_event_seq) != 'integer' OR r.next_event_seq < 0"
    " OR EXISTS (SELECT 1 FROM events AS newer"
    " WHERE newer.run_id = r.run_id AND newer.seq > r.next_event_seq)"
    " OR (r.status = 'pending' AND (r.next_event_seq != 0 OR e.seq IS NOT NULL))"
    " OR (r.status = 'running' AND (r.next_event_seq = 0 OR e.seq IS NULL"
    " OR typeof(e.kind) != 'text'"
    " OR e.kind IN ('RunParked', 'RunFailed', 'RunSucceeded', 'RunCancelled')))"
    " OR (r.status = 'parked' AND (e.seq IS NULL OR typeof(e.kind) != 'text'"
    " OR e.kind != 'RunParked'))"
    " OR (r.status = 'failed' AND (e.seq IS NULL OR typeof(e.kind) != 'text'"
    " OR e.kind != 'RunFailed'))"
    " OR (r.status = 'succeeded' AND (e.seq IS NULL OR typeof(e.kind) != 'text'"
    " OR e.kind != 'RunSucceeded'))"
    " OR (r.status = 'cancelled' AND (e.seq IS NULL OR typeof(e.kind) != 'text'"
    " OR e.kind != 'RunCancelled'))"
)
_RUN_ORIGIN_RELATION_ANOMALY = (
    "EXISTS (SELECT 1 FROM runs AS integrity_run"
    " LEFT JOIN run_origins AS integrity_origin"
    " ON integrity_origin.run_id = integrity_run.run_id"
    " WHERE constructicon_run_origin_matches("
    "integrity_run.run_id, integrity_run.creation_command_id,"
    " integrity_origin.origin_json) != 1)"
    " OR EXISTS (SELECT 1 FROM run_origins AS orphan_origin"
    " LEFT JOIN runs AS origin_run ON origin_run.run_id = orphan_origin.run_id"
    " WHERE origin_run.run_id IS NULL)"
)
RUN_WORLD_ANOMALY = (
    "EXISTS (SELECT 1 FROM runs AS sealed_candidate"
    " LEFT JOIN run_origins AS sealed_origin"
    " ON sealed_origin.run_id = sealed_candidate.run_id"
    " LEFT JOIN durable_fact_seals AS sealed_fact"
    " ON sealed_fact.family = 'run_world'"
    " AND sealed_fact.fact_key = sealed_candidate.run_id"
    " WHERE constructicon_run_world_fact_hash("
    " sealed_candidate.run_id, sealed_candidate.manifest_hash,"
    " sealed_candidate.input_hash, sealed_candidate.inputs_json,"
    " sealed_candidate.created_at, sealed_candidate.creation_command_id,"
    " sealed_origin.origin_json) IS NULL"
    " OR sealed_fact.selector IS NOT sealed_candidate.run_id"
    " OR sealed_fact.fact_hash IS NOT constructicon_run_world_fact_hash("
    " sealed_candidate.run_id, sealed_candidate.manifest_hash,"
    " sealed_candidate.input_hash, sealed_candidate.inputs_json,"
    " sealed_candidate.created_at, sealed_candidate.creation_command_id,"
    " sealed_origin.origin_json))"
)
RUN_ORIGIN_ANOMALY = _RUN_ORIGIN_RELATION_ANOMALY
RUN_IMMUTABLE_ANOMALY = f"({RUN_ORIGIN_ANOMALY}) OR ({RUN_WORLD_ANOMALY})"
_RUN_CHILD_REFERENCES = (
    ("events", "run_id", False),
    ("checkpoints", "run_id", False),
    ("effects", "run_id", False),
    ("effects", "outcome_run_id", True),
    ("capability_leases", "run_id", False),
    ("run_origins", "run_id", False),
    ("approvals", "run_id", False),
    ("channel_messages", "run_id", False),
)
_RELATIONAL_RUN_CHILD_ORPHAN_ANOMALY = " OR ".join(
    "EXISTS (SELECT 1 FROM "
    f"{table} AS child LEFT JOIN runs AS parent ON parent.run_id = child.{column} "
    + (f"WHERE child.{column} IS NOT NULL AND " if nullable else "WHERE ")
    + "parent.run_id IS NULL)"
    for table, column, nullable in _RUN_CHILD_REFERENCES
)
RUN_CREATION_ORPHAN_ANOMALY = (
    "EXISTS (SELECT 1 FROM commands AS creator"
    " LEFT JOIN runs AS created_run"
    " ON created_run.run_id = constructicon_run_id_for_command(creator.command_id)"
    " WHERE creator.operation IN ('runs_start', 'runs_reproduce',"
    " 'runs_counterfactual') AND creator.state = 'committed'"
    " AND (created_run.run_id IS NULL"
    " OR created_run.creation_command_id IS NOT creator.command_id))"
)
RUN_CHILD_ORPHAN_ANOMALY = (
    f"({_RELATIONAL_RUN_CHILD_ORPHAN_ANOMALY})"
    f" OR ({RUN_CREATION_ORPHAN_ANOMALY})"
    " OR EXISTS (SELECT 1 FROM durable_fact_seals AS run_seal"
    " LEFT JOIN runs AS sealed_run ON sealed_run.run_id = run_seal.fact_key"
    " WHERE run_seal.family = 'run_world' AND sealed_run.run_id IS NULL)"
    " OR EXISTS (SELECT 1 FROM attestations AS child"
    " LEFT JOIN runs AS parent"
    " ON parent.run_id = constructicon_attestation_created_by_run("
    "child.attestation_json)"
    " LEFT JOIN durable_fact_seals AS legacy_attestation"
    f" ON legacy_attestation.family = '{LEGACY_ATTESTATION_FACT_FAMILY}'"
    " AND legacy_attestation.fact_key = child.attestation_id"
    " AND legacy_attestation.selector = child.attestation_id"
    " LEFT JOIN durable_fact_seals AS current_attestation"
    f" ON current_attestation.family = '{ATTESTATION_FACT_FAMILY}'"
    " AND current_attestation.fact_key = child.attestation_id"
    " AND current_attestation.selector = child.attestation_id"
    " WHERE constructicon_attestation_is_valid(child.attestation_json) != 1"
    " OR (constructicon_attestation_created_by_run(child.attestation_json)"
    " IS NOT NULL AND parent.run_id IS NULL"
    " AND (legacy_attestation.fact_key IS NULL"
    " OR current_attestation.fact_key IS NOT NULL)))"
    " OR EXISTS (SELECT 1 FROM promotions AS child"
    " LEFT JOIN runs AS parent ON parent.run_id = child.source_run"
    " LEFT JOIN durable_fact_seals AS legacy_promotion"
    f" ON legacy_promotion.family = '{LEGACY_PROMOTION_FACT_FAMILY}'"
    " AND legacy_promotion.fact_key = CAST(child.promotion_seq AS TEXT)"
    " AND legacy_promotion.selector = child.attestation_id"
    " LEFT JOIN durable_fact_seals AS current_promotion"
    f" ON current_promotion.family = '{PROMOTION_FACT_FAMILY}'"
    " AND current_promotion.fact_key = CAST(child.promotion_seq AS TEXT)"
    " AND current_promotion.selector = child.attestation_id"
    " WHERE child.source_run IS NOT NULL AND parent.run_id IS NULL"
    " AND (legacy_promotion.fact_key IS NULL"
    " OR current_promotion.fact_key IS NOT NULL))"
)


def _run_origin_matches(
    raw_run_id: object,
    raw_command_id: object,
    raw_origin: object,
) -> int:
    try:
        run_id = RunId(_durable_text(raw_run_id, fact="run origin identity"))
        if raw_command_id is None and raw_origin is None:
            return 1
        if raw_command_id is None or raw_origin is None:
            return 0
        command_id = _durable_text(
            raw_command_id,
            fact=f"run {run_id!r} creation command identity",
        )
        origin = run_origin_from_json(raw_origin, run_id=run_id)
        if origin.command_id != command_id:
            return 0
        return 1
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return 0


def _attestation_is_valid(raw: object) -> int:
    try:
        attestation_from_json(raw)
        return 1
    except JournalDamaged:
        return 0


def _attestation_created_by_run(raw: object) -> str | None:
    try:
        creator = attestation_from_json(raw).created_by_run
        return str(creator) if creator is not None else None
    except JournalDamaged:
        return None


def _run_id_for_creation_command(raw: object) -> str | None:
    try:
        return str(run_id_for_command(_durable_text(raw, fact="run creation command identity")))
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return None


def register_run_origin_guard(connection: sqlite3.Connection) -> None:
    connection.create_function(
        "constructicon_run_origin_matches",
        3,
        _run_origin_matches,
        deterministic=True,
    )
    connection.create_function(
        "constructicon_run_world_fact_hash",
        7,
        _sqlite_run_world_fact_hash,
        deterministic=True,
    )
    connection.create_function(
        "constructicon_attestation_is_valid",
        1,
        _attestation_is_valid,
        deterministic=True,
    )
    connection.create_function(
        "constructicon_attestation_created_by_run",
        1,
        _attestation_created_by_run,
        deterministic=True,
    )
    connection.create_function(
        "constructicon_run_id_for_command",
        1,
        _run_id_for_creation_command,
        deterministic=True,
    )


def run_origin_anomaly_column() -> str:
    return f" ({RUN_ORIGIN_ANOMALY}) AS run_origin_anomaly"


def run_world_anomaly_column() -> str:
    return f" ({RUN_WORLD_ANOMALY}) AS run_world_anomaly"


def run_child_anomaly_column() -> str:
    return f" ({RUN_CHILD_ORPHAN_ANOMALY}) AS run_child_anomaly"


RUN_PROJECTION_COLUMNS = (
    "r.*, o.origin_json,"
    + RUN_LIFECYCLE_EVENT_COLUMNS
    + ","
    + run_origin_anomaly_column()
    + ","
    + run_world_anomaly_column()
    + ","
    + run_child_anomaly_column()
)
RUN_PROJECTION_JOINS = (
    " FROM runs AS r LEFT JOIN run_origins AS o ON o.run_id = r.run_id"
    " LEFT JOIN events AS e"
    " ON e.run_id = r.run_id AND e.seq = r.next_event_seq"
)


def validate_no_orphan_run_facts(connection: sqlite3.Connection) -> None:
    row = connection.execute(f"SELECT ({RUN_CHILD_ORPHAN_ANOMALY}) AS damaged").fetchone()
    if _durable_sqlite_boolean(
        row["damaged"],
        fact="run child-integrity flag",
    ):
        raise JournalDamaged("durable run child facts name no retained run")


def lifecycle_damage(run_id: RunId, status: RunStatus) -> JournalDamaged:
    if status is RunStatus.PARKED:
        return JournalDamaged(f"PARKED run {run_id!r} has no latest RunParked event")
    return JournalDamaged(f"run {run_id!r} contradicts its durable lifecycle")


def validated_run_lifecycle(
    row: sqlite3.Row,
    *,
    run_id: RunId,
    status: RunStatus,
) -> tuple[int | None, str | None]:
    """Prove one run status against the event at its durable sequence fence."""

    next_event_seq = _durable_sequence(
        row["next_event_seq"],
        fact=f"run {run_id!r} lifecycle event sequence",
        allow_zero=True,
        kind="event sequence",
    )
    has_newer_event = _durable_sqlite_boolean(
        row["lifecycle_has_newer_event"],
        fact=f"run {run_id!r} newer-event integrity flag",
    )
    raw_event_seq = row["lifecycle_event_seq"]
    if status is RunStatus.PENDING:
        if next_event_seq != 0 or raw_event_seq is not None or has_newer_event:
            raise lifecycle_damage(run_id, status)
        return None, None
    if raw_event_seq is None:
        raise lifecycle_damage(run_id, status)
    event_seq = _durable_event_seq(
        raw_event_seq,
        fact=f"run {run_id!r} lifecycle event",
    )
    event_kind = _durable_text(
        row["lifecycle_event_kind"],
        fact=f"run {run_id!r} lifecycle event kind",
    )
    if event_seq != next_event_seq or has_newer_event:
        raise lifecycle_damage(run_id, status)
    expected_terminal = TERMINAL_STATUS_EVENTS.get(status)
    if status is RunStatus.RUNNING:
        lawful = next_event_seq > 0 and event_kind not in TERMINAL_EVENT_KINDS
    else:
        lawful = event_kind == expected_terminal
    if not lawful:
        raise lifecycle_damage(run_id, status)
    return event_seq, event_kind


def validated_event_history(
    connection: sqlite3.Connection,
    *,
    run_id: RunId,
    next_event_seq: object,
) -> int:
    """Prove the append-only event sequence against the run's allocation fence."""

    fence = _durable_sequence(
        next_event_seq,
        fact=f"run {run_id!r} event allocation fence",
        allow_zero=True,
        kind="event sequence",
    )
    row = connection.execute(
        "SELECT COUNT(*) AS event_count, COALESCE(MIN(seq), 0) AS minimum_seq,"
        " COALESCE(MAX(seq), 0) AS maximum_seq,"
        " COALESCE(MAX(CASE WHEN typeof(run_id) != 'text'"
        " OR typeof(seq) != 'integer' OR seq <= 0 THEN 1 ELSE 0 END), 0)"
        " AS damaged FROM events WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    try:
        event_count = _durable_sequence(
            row["event_count"],
            fact=f"run {run_id!r} event count",
            allow_zero=True,
            kind="event count",
        )
        minimum = _durable_sequence(
            row["minimum_seq"],
            fact=f"run {run_id!r} minimum event sequence",
            allow_zero=True,
            kind="event sequence",
        )
        maximum = _durable_sequence(
            row["maximum_seq"],
            fact=f"run {run_id!r} maximum event sequence",
            allow_zero=True,
            kind="event sequence",
        )
        damaged = _durable_sqlite_boolean(
            row["damaged"],
            fact=f"run {run_id!r} event-history integrity flag",
        )
    except JournalDamaged as exc:
        raise JournalDamaged(f"event sequence history for run {run_id!r} is damaged") from exc
    expected_minimum = 1 if fence else 0
    if damaged or event_count != fence or minimum != expected_minimum or maximum != fence:
        raise JournalDamaged(
            f"event sequence history for run {run_id!r} contradicts its allocation fence"
        )
    validate_event_seal_inventory(connection, run_id=run_id)
    return fence


def run_record_from_row(
    row: sqlite3.Row,
    *,
    observe: Callable[[], datetime],
) -> RunRecord:
    """Decode one run row after its relational selectors have been surfaced."""

    raw_run_id = row["run_id"]
    try:
        fields = _run_state_fields(row, observe=observe)
        origin_json = row["origin_json"]
        return RunRecord(
            run_id=fields.run_id,
            manifest_hash=_durable_digest(
                row["manifest_hash"],
                fact=f"run {fields.run_id!r} manifest identity",
            ),
            input_hash=_durable_digest(
                row["input_hash"],
                fact=f"run {fields.run_id!r} input identity",
            ),
            status=fields.status,
            liveness=fields.liveness,
            created_at=fields.created_at,
            owner_id=fields.owner_id,
            lease_expires_at=fields.lease_expires_at,
            cancel_requested=fields.cancel_requested,
            origin=(
                run_origin_from_json(origin_json, run_id=fields.run_id)
                if origin_json is not None
                else None
            ),
        )
    except JournalDamaged:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(f"run row {raw_run_id!r} is not a valid durable record") from exc


def _validate_run_integrity_flags(row: sqlite3.Row) -> None:
    if _durable_sqlite_boolean(
        row["run_origin_anomaly"],
        fact="run-origin integrity flag",
    ):
        raise JournalDamaged("run origin history contradicts its derived identity")
    if _durable_sqlite_boolean(
        row["run_world_anomaly"],
        fact="run-world integrity flag",
    ):
        raise JournalDamaged("run immutable world contradicts its positive seal")
    if _durable_sqlite_boolean(
        row["run_child_anomaly"],
        fact="run child-integrity flag",
    ):
        raise JournalDamaged("durable run child facts name no retained run")


def validated_run_facts(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[ValidatedRunWorld, int | None, str | None]:
    """Prove immutable world, lifecycle, and resume provenance for one run."""

    facts = _validated_run_facts_before_resume_inventory(connection, row)
    validate_resume_attempt_provenance(connection, run_id=facts[0].run_id)
    return facts


def _validated_run_facts_before_resume_inventory(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[ValidatedRunWorld, int | None, str | None]:
    """Project run facts while the enclosing inventory proves relations once."""

    durable = _durable_run_fields(row)
    _validate_run_integrity_flags(row)
    world = validated_run_world(connection, row)
    if world.run_id != durable.run_id:
        raise JournalDamaged(f"run {durable.run_id!r} contradicts its immutable world")
    validated_event_history(
        connection,
        run_id=durable.run_id,
        next_event_seq=row["next_event_seq"],
    )
    if durable.status is not RunStatus.PENDING:
        latest = connection.execute(
            "SELECT * FROM events WHERE run_id = ? AND seq = ?",
            (durable.run_id, row["next_event_seq"]),
        ).fetchone()
        if latest is None:
            raise lifecycle_damage(durable.run_id, durable.status)
        event = stored_event_from_row(connection, latest)
        if event.run_id != durable.run_id or event.seq != row["next_event_seq"]:
            raise JournalDamaged(
                f"latest event for run {durable.run_id!r} contradicts its identity"
            )
    event_seq, event_kind = validated_run_lifecycle(
        row,
        run_id=durable.run_id,
        status=durable.status,
    )
    return world, event_seq, event_kind


def validate_run_fact_inventory(connection: sqlite3.Connection) -> int:
    """Project the complete retained run graph through its canonical law."""

    register_run_origin_guard(connection)
    validate_no_orphan_run_facts(connection)
    resume_attempt_count = validate_resume_attempt_provenance(connection)
    # Materialize the outer inventory before nested owner projections install
    # their SQLite identity functions. SQLite cannot change a connection's UDF
    # registry while an outer statement on that connection is still active.
    rows = connection.execute(
        "SELECT " + RUN_PROJECTION_COLUMNS + RUN_PROJECTION_JOINS + " ORDER BY r.run_id"
    ).fetchall()
    for row in rows:
        _validated_run_facts_before_resume_inventory(connection, row)
    return resume_attempt_count


def validated_run_projection(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    observe: Callable[[], datetime],
    decode_record: Callable[[sqlite3.Row], RunRecord] | None = None,
) -> tuple[RunRecord, ValidatedRunWorld, int | None, str | None]:
    """Project one run through world, relational, and lifecycle proof once."""

    world, event_seq, event_kind = validated_run_facts(connection, row)
    record = (
        decode_record(row)
        if decode_record is not None
        else run_record_from_row(row, observe=observe)
    )
    if world.run_id != record.run_id:
        raise JournalDamaged(f"run {record.run_id!r} contradicts its immutable world")
    return record, world, event_seq, event_kind


def run_projection_for_id(
    connection: sqlite3.Connection,
    run_id: RunId,
    *,
    observe: Callable[[], datetime],
) -> tuple[RunRecord, ValidatedRunWorld, int | None, str | None] | None:
    """Identity-first exact run lookup through the shared world projector."""

    register_run_origin_guard(connection)
    row = connection.execute(
        "SELECT " + RUN_PROJECTION_COLUMNS + RUN_PROJECTION_JOINS + " WHERE r.run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        validate_no_orphan_run_facts(connection)
        return None
    return validated_run_projection(connection, row, observe=observe)


def run_facts_for_id(
    connection: sqlite3.Connection,
    run_id: RunId,
) -> tuple[ValidatedRunWorld, int | None, str | None] | None:
    """Identity-first exact run proof without a new liveness observation."""

    register_run_origin_guard(connection)
    row = connection.execute(
        "SELECT " + RUN_PROJECTION_COLUMNS + RUN_PROJECTION_JOINS + " WHERE r.run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        validate_no_orphan_run_facts(connection)
        return None
    return validated_run_facts(connection, row)


def validated_run_world(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> ValidatedRunWorld:
    """Prove run columns, retained manifest, inputs, origin, and command plan."""

    try:
        require_run_world_seal(connection, row)
        run_id = RunId(_durable_text(row["run_id"], fact="run identity"))
        manifest_hash = _durable_digest(
            row["manifest_hash"],
            fact=f"run {run_id!r} manifest identity",
        )
        input_hash = _durable_digest(
            row["input_hash"],
            fact=f"run {run_id!r} input identity",
        )
        raw_inputs = _durable_json(
            row["inputs_json"],
            fact=f"run {run_id!r} inputs",
        )
        if not isinstance(raw_inputs, dict):
            raise ValueError("run inputs are not an object")
        inputs = {str(name): value for name, value in raw_inputs.items()}
        if set(inputs) != set(raw_inputs) or digest("inputs", 1, inputs) != input_hash:
            raise ValueError("run input bytes contradict their identity")

        raw_origin = row["origin_json"]
        raw_creation_command = row["creation_command_id"]
        manifest = _retained_manifest(
            connection,
            run_id=run_id,
            manifest_hash=manifest_hash,
            input_hash=input_hash,
        )
        if raw_origin is None:
            if raw_creation_command is not None:
                raise ValueError("legacy run carries a creation command marker")
            return ValidatedRunWorld(
                run_id=run_id,
                manifest=manifest,
                inputs=inputs,
                origin=None,
                creation_plan=None,
            )
        origin = run_origin_from_json(raw_origin, run_id=run_id)
        creation_command = _durable_text(
            raw_creation_command,
            fact=f"run {run_id!r} creation command identity",
        )
        if creation_command != origin.command_id:
            raise ValueError("run origin contradicts its creation command marker")
        command = command_for_id(connection, origin.command_id)
        if command is None:
            raise ValueError("run origin names no retained creation command")
        plan = validated_run_creation_command(command)
        _validate_clone_source_world(connection, plan=plan)
        if (
            plan.run_id != run_id
            or plan.manifest.manifest_hash != manifest_hash
            or plan.manifest.input_hash != input_hash
            or canonical_json(json_value(plan.manifest.model_dump(mode="json")))
            != canonical_json(json_value(manifest.model_dump(mode="json")))
            or canonical_json(plan.inputs) != canonical_json(inputs)
            or canonical_json(json_value(plan.origin.model_dump(mode="json")))
            != canonical_json(json_value(origin.model_dump(mode="json")))
        ):
            raise ValueError("run world contradicts its creation command plan")
        return ValidatedRunWorld(
            run_id=run_id,
            manifest=manifest,
            inputs=inputs,
            origin=origin,
            creation_plan=plan,
        )
    except JournalDamaged:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        columns = row.keys()
        identity = row["run_id"] if "run_id" in columns else "unknown"
        raise JournalDamaged(f"run {identity!r} has no exact immutable creation world") from exc
