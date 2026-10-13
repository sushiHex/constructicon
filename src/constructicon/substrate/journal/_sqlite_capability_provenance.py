"""Accounting era commitments and exact migration-only capability loss facts."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from pydantic import ValidationError

from constructicon.core.address import RunId
from constructicon.core.control import (
    CapabilityAccountingEra,
    HistoricalCapabilityInitialLostEvidence,
    HistoricalCapabilityLostEvidence,
)
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.journal import JournalEvent
from constructicon.core.manifest import CapabilityLease
from constructicon.substrate.journal._sqlite_base import (
    _durable_digest,
    _durable_sequence,
    _durable_text,
)
from constructicon.substrate.journal._sqlite_execution_facts import (
    event_fact_hash,
    event_fact_key,
    stored_event_from_row,
)
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    durable_fact_seal,
    require_durable_fact_seal,
    store_durable_fact_seal,
)
from constructicon.substrate.journal._sqlite_leases import LegacyLeaseSeal
from constructicon.substrate.journal._sqlite_runs import (
    run_world_fact_hash,
    validated_event_fence,
    validated_run_world,
)

ACCOUNTING_ERA_FAMILY = "capability_accounting_era"
LOST_PRE_V8_FAMILY = "capability_lost_pre_v8"
INITIAL_LOST_PRE_V8_FAMILY = "capability_initial_lost_pre_v8"
CAPABILITY_PROVENANCE_FAMILIES = frozenset(
    {ACCOUNTING_ERA_FAMILY, LOST_PRE_V8_FAMILY, INITIAL_LOST_PRE_V8_FAMILY}
)

ERA_DDL = (
    "CREATE TABLE capability_accounting_eras ("
    " run_id TEXT PRIMARY KEY, world_hash TEXT NOT NULL, source TEXT NOT NULL,"
    " floor INTEGER NOT NULL, inventory_hash TEXT NOT NULL)"
)


@dataclass(frozen=True)
class CapabilityLeaseHistory:
    """Already validated row and its exact historical chain, within one snapshot."""

    row: sqlite3.Row
    lease: CapabilityLease
    events: tuple[JournalEvent, ...]
    legacy: LegacyLeaseSeal | None


def accounting_inventory_hash(histories: Sequence[CapabilityLeaseHistory], floor: int) -> Digest:
    inventory: list[dict[str, object]] = []
    for history in sorted(
        histories, key=lambda item: (item.lease.lease_id, item.lease.acquisition_epoch)
    ):
        row, lease, legacy = history.row, history.lease, history.legacy
        events = history.events
        if legacy is None:
            acquired = events[0]
            if acquired.seq > floor:
                continue
            state, disposition, updated_at = "active", None, row["created_at"]
            applicable = events[1:]
            initial: object = {"event_seq": acquired.seq, "payload": acquired.payload}
        else:
            state, disposition, updated_at = legacy.state, legacy.disposition, legacy.updated_at
            applicable = tuple(
                event
                for event in events
                if isinstance(event.payload, dict) and "legacy_base_hash" in event.payload
            )
            initial = {
                "base_hash": str(legacy.base_hash),
                "state": legacy.state,
                "disposition": legacy.disposition,
                "updated_at": legacy.updated_at,
            }
        for event in applicable:
            if event.seq <= floor:
                assert isinstance(event.payload, dict)
                state = str(event.payload["to"])
                disposition = event.payload["disposition"]
                updated_at = event.created_at.isoformat()
        inventory.append(
            {
                "lease_id": lease.lease_id,
                "acquisition_epoch": lease.acquisition_epoch,
                "run_id": str(lease.run_id),
                "binding_id": row["binding_id"],
                "scope_json": row["scope_json"],
                "lifetime": row["lifetime"],
                "resource_ref": row["resource_ref"],
                "created_at": row["created_at"],
                "initial": initial,
                "state": state,
                "disposition": disposition,
                "updated_at": updated_at,
                "events": [
                    {
                        "seq": event.seq,
                        "kind": event.kind,
                        "payload": event.payload,
                        "created_at": event.created_at.isoformat(),
                    }
                    for event in events
                    if event.seq <= floor
                ],
            }
        )
    return digest("capability-accounting-inventory", 1, inventory)


def capability_run_world_row(connection: sqlite3.Connection, run_id: RunId) -> sqlite3.Row:
    """Prove the immutable world used by a capability's point era projection.

    A writer may already have allocated its next event inside this transaction.
    Point authority does not require that staged event to have been inserted;
    external accounting separately proves the complete committed event extent.
    """

    row = connection.execute(
        "SELECT r.*, o.origin_json FROM runs AS r"
        " LEFT JOIN run_origins AS o ON o.run_id = r.run_id WHERE r.run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise JournalDamaged(f"capability accounting run {run_id!r} has no retained world")
    validated_run_world(connection, row)
    return cast(sqlite3.Row, row)


def accounting_run_row(connection: sqlite3.Connection, run_id: RunId) -> sqlite3.Row:
    """Prove the run world and complete event extent for coherent accounting."""

    row = capability_run_world_row(connection, run_id)
    validated_event_fence(connection, run_id=run_id, next_event_seq=row["next_event_seq"])
    return row


def require_accounting_absence(connection: sqlite3.Connection, run_id: RunId) -> None:
    row = connection.execute(
        "SELECT 1 FROM capability_accounting_eras WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if (
        row is not None
        or durable_fact_seal(
            connection,
            family=ACCOUNTING_ERA_FAMILY,
            fact_key=str(run_id),
            selector=str(run_id),
        )
        is not None
    ):
        raise JournalDamaged("capability accounting era has no retained run")


def accounting_era_fact_hash(era: CapabilityAccountingEra) -> Digest:
    return durable_fact_hash(ACCOUNTING_ERA_FAMILY, era.model_dump(mode="json"))


def require_accounting_era(
    connection: sqlite3.Connection, run: sqlite3.Row
) -> CapabilityAccountingEra:
    run_id = RunId(_durable_text(run["run_id"], fact="capability accounting run identity"))
    try:
        rows = connection.execute(
            "SELECT * FROM capability_accounting_eras WHERE run_id = ? LIMIT 2",
            (run_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise JournalDamaged("capability accounting era cannot prove its current schema") from exc
    if not rows:
        raise JournalDamaged(f"capability accounting era for run {run_id!r} is missing")
    if len(rows) != 1 or set(rows[0].keys()) != {
        "run_id",
        "world_hash",
        "source",
        "floor",
        "inventory_hash",
    }:
        raise JournalDamaged("capability accounting era has contradictory rows or fields")
    row = rows[0]
    try:
        era = CapabilityAccountingEra(
            run_id=RunId(_durable_text(row["run_id"], fact="accounting era run")),
            world_hash=_durable_digest(row["world_hash"], fact="accounting era world"),
            source=_durable_text(row["source"], fact="accounting era source"),  # type: ignore[arg-type]
            floor=_durable_sequence(row["floor"], fact="accounting era floor", allow_zero=True),
            inventory_hash=_durable_digest(row["inventory_hash"], fact="accounting era inventory"),
        )
    except (ValueError, ValidationError) as exc:
        raise JournalDamaged(f"capability accounting era for run {run_id!r} is invalid") from exc
    require_durable_fact_seal(
        connection,
        family=ACCOUNTING_ERA_FAMILY,
        fact_key=str(run_id),
        selector=str(run_id),
        fact_hash=accounting_era_fact_hash(era),
    )
    fence = _durable_sequence(
        run["next_event_seq"], fact="capability accounting run fence", allow_zero=True,
    )
    if era.world_hash != run_world_fact_hash(run) or era.floor > fence:
        raise JournalDamaged(
            f"capability accounting era for run {run_id!r} contradicts its world/floor"
        )
    if era.source == "schema8-creation" and era.inventory_hash != accounting_inventory_hash((), 0):
        raise JournalDamaged(f"capability creation era for run {run_id!r} has a nonempty inventory")
    return era


def _store_era(connection: sqlite3.Connection, era: CapabilityAccountingEra) -> None:
    connection.execute(
        "INSERT INTO capability_accounting_eras (run_id, world_hash, source, floor, inventory_hash)"
        " VALUES (?, ?, ?, ?, ?)",
        (era.run_id, str(era.world_hash), era.source, era.floor, str(era.inventory_hash)),
    )
    store_durable_fact_seal(
        connection,
        family=ACCOUNTING_ERA_FAMILY,
        fact_key=str(era.run_id),
        selector=str(era.run_id),
        fact_hash=accounting_era_fact_hash(era),
    )


def mint_creation_accounting_era(connection: sqlite3.Connection, run: sqlite3.Row) -> None:
    if run["status"] != "pending" or run["next_event_seq"] != 0 or run["owner_epoch"] != 0:
        raise JournalDamaged("capability creation era requires an actual initial run")
    _store_era(
        connection,
        CapabilityAccountingEra(
            run_id=RunId(run["run_id"]),
            world_hash=run_world_fact_hash(run),
            source="schema8-creation",
            floor=0,
            inventory_hash=accounting_inventory_hash((), 0),
        ),
    )


def _initial_lost_key(lease_id: str, epoch: int) -> str:
    return canonical_json({"lease_id": lease_id, "acquisition_epoch": epoch})


def _initial_lost_fact(history: CapabilityLeaseHistory) -> Digest:
    assert history.legacy is not None
    return durable_fact_hash(
        INITIAL_LOST_PRE_V8_FAMILY,
        {
            "run_id": str(history.lease.run_id),
            "lease_id": history.lease.lease_id,
            "acquisition_epoch": history.lease.acquisition_epoch,
            "base_hash": str(history.legacy.base_hash),
            "state": history.legacy.state,
            "disposition": history.legacy.disposition,
            "updated_at": history.legacy.updated_at,
        },
    )


def _lost_event_fact(connection: sqlite3.Connection, event: JournalEvent) -> Digest:
    row = connection.execute(
        "SELECT * FROM events WHERE run_id = ? AND seq = ?",
        (event.run_id, event.seq),
    ).fetchone()
    if row is None or stored_event_from_row(connection, row) != event:
        raise JournalDamaged("historical capability lost witness has no exact event")
    return durable_fact_hash(LOST_PRE_V8_FAMILY, {"event": str(event_fact_hash(row))})


def _lost_events(history: CapabilityLeaseHistory) -> tuple[JournalEvent, ...]:
    return tuple(
        event
        for event in history.events
        if event.kind == "LeaseTransition"
        and isinstance(event.payload, dict)
        and event.payload.get("to") == "lost"
    )


def _lost_evidence(
    history: CapabilityLeaseHistory, event: JournalEvent
) -> HistoricalCapabilityLostEvidence:
    return HistoricalCapabilityLostEvidence(
        run_id=history.lease.run_id,
        event_seq=event.seq,
        lease_id=history.lease.lease_id,
        acquisition_epoch=history.lease.acquisition_epoch,
    )


def _initial_evidence(history: CapabilityLeaseHistory) -> HistoricalCapabilityInitialLostEvidence:
    return HistoricalCapabilityInitialLostEvidence(
        run_id=history.lease.run_id,
        lease_id=history.lease.lease_id,
        acquisition_epoch=history.lease.acquisition_epoch,
    )


def mint_migrated_capability_provenance(
    connection: sqlite3.Connection,
    histories: dict[RunId, list[CapabilityLeaseHistory]],
) -> None:
    if (
        connection.execute("PRAGMA user_version").fetchone()[0] != 7
        or not connection.in_transaction
    ):
        raise JournalDamaged("historical capability provenance is migration-only")
    runs = connection.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()
    for raw in runs:
        run_id = RunId(raw["run_id"])
        run = accounting_run_row(connection, run_id)
        floor = run["next_event_seq"]
        members = histories.get(run_id, [])
        _store_era(
            connection,
            CapabilityAccountingEra(
                run_id=run_id,
                world_hash=run_world_fact_hash(run),
                source="schema7-migration",
                floor=floor,
                inventory_hash=accounting_inventory_hash(members, floor),
            ),
        )
        for history in members:
            for event in _lost_events(history):
                if event.run_id != run_id or event.seq > floor:
                    raise JournalDamaged(
                        "historical capability lost event contradicts migration floor"
                    )
                store_durable_fact_seal(
                    connection,
                    family=LOST_PRE_V8_FAMILY,
                    fact_key=event_fact_key(run_id, event.seq),
                    selector=canonical_json(_lost_evidence(history, event).model_dump(mode="json")),
                    fact_hash=_lost_event_fact(connection, event),
                )
            if history.legacy is not None and history.legacy.state == "lost":
                store_durable_fact_seal(
                    connection,
                    family=INITIAL_LOST_PRE_V8_FAMILY,
                    fact_key=_initial_lost_key(
                        history.lease.lease_id, history.lease.acquisition_epoch
                    ),
                    selector=canonical_json(_initial_evidence(history).model_dump(mode="json")),
                    fact_hash=_initial_lost_fact(history),
                )


def require_capability_lost_provenance(
    connection: sqlite3.Connection,
    history: CapabilityLeaseHistory,
) -> int:
    lost_events = _lost_events(history)
    initial_lost = history.legacy is not None and history.legacy.state == "lost"
    era = require_accounting_era(
        connection, capability_run_world_row(connection, history.lease.run_id),
    )
    if not lost_events and not initial_lost and history.legacy is None:
        return 0
    if era.source != "schema7-migration":
        raise JournalDamaged(
            "capability lost facts have no historical migration era or disposal receipt"
        )
    if history.legacy is not None and any(
        event.seq > era.floor
        and (not isinstance(event.payload, dict) or "legacy_base_hash" not in event.payload)
        for event in history.events
    ):
        raise JournalDamaged(
            "current capability event cannot imitate an opaque historical lease event"
        )
    for event in lost_events:
        if event.run_id != history.lease.run_id or event.seq > era.floor:
            raise JournalDamaged("capability lost witness lies outside its historical floor")
        require_durable_fact_seal(
            connection,
            family=LOST_PRE_V8_FAMILY,
            fact_key=event_fact_key(event.run_id, event.seq),
            selector=canonical_json(_lost_evidence(history, event).model_dump(mode="json")),
            fact_hash=_lost_event_fact(connection, event),
        )
    if initial_lost:
        require_durable_fact_seal(
            connection,
            family=INITIAL_LOST_PRE_V8_FAMILY,
            fact_key=_initial_lost_key(history.lease.lease_id, history.lease.acquisition_epoch),
            selector=canonical_json(_initial_evidence(history).model_dump(mode="json")),
            fact_hash=_initial_lost_fact(history),
        )
    return len(lost_events) + int(initial_lost)


def validate_accounting_run(
    connection: sqlite3.Connection,
    run_id: RunId,
    histories: Sequence[CapabilityLeaseHistory],
    *,
    through_event_seq: int | None = None,
) -> CapabilityAccountingEra:
    run = accounting_run_row(connection, run_id)
    era = require_accounting_era(connection, run)
    if any(history.lease.run_id != run_id for history in histories):
        raise JournalDamaged("capability accounting inventory crosses run identities")
    if accounting_inventory_hash(histories, era.floor) != era.inventory_hash:
        raise JournalDamaged(
            f"capability accounting inventory for run {run_id!r} changed at its floor"
        )
    if through_event_seq is not None:
        cut = _durable_sequence(
            through_event_seq,
            fact="capability accounting cut",
            allow_zero=True,
        )
        if cut < era.floor or cut > run["next_event_seq"]:
            raise ContractViolation(
                "capability accounting cut lies outside its proven floor/extent"
            )
    return era


def validate_capability_provenance_inventory(
    connection: sqlite3.Connection,
    histories: dict[RunId, list[CapabilityLeaseHistory]],
) -> int:
    required: dict[str, set[str]] = {family: set() for family in CAPABILITY_PROVENANCE_FAMILIES}
    for raw in connection.execute("SELECT run_id FROM runs").fetchall():
        run_id = RunId(raw["run_id"])
        validate_accounting_run(connection, run_id, histories.get(run_id, []))
        required[ACCOUNTING_ERA_FAMILY].add(str(run_id))
    for members in histories.values():
        for history in members:
            require_capability_lost_provenance(connection, history)
            required[LOST_PRE_V8_FAMILY].update(
                event_fact_key(event.run_id, event.seq) for event in _lost_events(history)
            )
            if history.legacy is not None and history.legacy.state == "lost":
                required[INITIAL_LOST_PRE_V8_FAMILY].add(
                    _initial_lost_key(history.lease.lease_id, history.lease.acquisition_epoch)
                )
    for row in connection.execute("SELECT run_id FROM capability_accounting_eras").fetchall():
        if row["run_id"] not in required[ACCOUNTING_ERA_FAMILY]:
            raise JournalDamaged("capability accounting era has no retained run")
    for family, keys in required.items():
        seals = connection.execute(
            "SELECT fact_key FROM durable_fact_seals WHERE family = ?",
            (family,),
        ).fetchall()
        if {row["fact_key"] for row in seals} != keys:
            raise JournalDamaged(f"capability provenance {family!r} inventory is not bidirectional")
    return sum(len(keys) for keys in required.values())
