"""Migration seals for capability leases written before exact event provenance."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.substrate.journal._sqlite_base import (
    _durable_datetime,
    _durable_digest,
    _durable_json,
    _durable_sequence,
    _durable_text,
)
from constructicon.substrate.journal._sqlite_execution_facts import stored_event_from_row


@dataclass(frozen=True)
class LegacyLeaseSeal:
    """The independently sealed base and initial lifecycle of one old lease."""

    base_hash: Digest
    run_id: str
    state: str
    disposition: str | None
    updated_at: str


def legacy_lease_base_hash(row: sqlite3.Row) -> Digest:
    """Hash the immutable acquisition fields without normalizing their bytes."""

    identity = f"legacy capability lease {row['lease_id']!r}/{row['acquisition_epoch']!r}"
    lease_id = _durable_text(row["lease_id"], fact=f"{identity} identity")
    epoch = _durable_sequence(
        row["acquisition_epoch"],
        fact=f"{identity} acquisition epoch",
    )
    run_id = _durable_text(row["run_id"], fact=f"{identity} run identity")
    created_at = _durable_text(row["created_at"], fact=f"{identity} creation time")
    _durable_datetime(created_at, fact=f"{identity} creation time")
    resource_ref = (
        _durable_text(row["resource_ref"], fact=f"{identity} resource reference")
        if row["resource_ref"] is not None
        else None
    )
    return digest(
        "legacy-capability-lease-base",
        1,
        {
            "lease_id": lease_id,
            "acquisition_epoch": epoch,
            "run_id": run_id,
            "binding_id": _durable_text(
                row["binding_id"],
                fact=f"{identity} binding",
            ),
            "scope_json": _durable_text(
                row["scope_json"],
                fact=f"{identity} scope",
            ),
            "lifetime": _durable_text(
                row["lifetime"],
                fact=f"{identity} lifetime",
            ),
            "resource_ref": resource_ref,
            "created_at": created_at,
        },
    )


def legacy_lease_initial_lifecycle_json(row: sqlite3.Row) -> str:
    """Retain the exact lifecycle from which current transitions must start."""

    identity = f"legacy capability lease {row['lease_id']!r}/{row['acquisition_epoch']!r}"
    updated_at = _durable_text(row["updated_at"], fact=f"{identity} update time")
    _durable_datetime(updated_at, fact=f"{identity} update time")
    return canonical_json(
        {
            "state": _durable_text(row["state"], fact=f"{identity} state"),
            "disposition": (
                _durable_text(
                    row["disposition"],
                    fact=f"{identity} disposition",
                )
                if row["disposition"] is not None
                else None
            ),
            "updated_at": updated_at,
        }
    )


def legacy_lease_seal_for(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> LegacyLeaseSeal | None:
    """Load and validate the migration seal for one retained legacy lease."""

    identity = f"legacy capability lease {row['lease_id']!r}/{row['acquisition_epoch']!r}"
    seal = connection.execute(
        "SELECT * FROM legacy_capability_lease_seals WHERE lease_id = ? AND acquisition_epoch = ?",
        (row["lease_id"], row["acquisition_epoch"]),
    ).fetchone()
    if seal is None:
        return None
    try:
        lease_id = _durable_text(seal["lease_id"], fact=f"{identity} sealed identity")
        epoch = _durable_sequence(
            seal["acquisition_epoch"],
            fact=f"{identity} sealed acquisition epoch",
        )
        run_id = _durable_text(
            seal["run_id"],
            fact=f"{identity} sealed run identity",
        )
        base_hash = _durable_digest(
            seal["base_hash"],
            fact=f"{identity} sealed base",
        )
        lifecycle = _durable_json(
            seal["initial_lifecycle_json"],
            fact=f"{identity} sealed initial lifecycle",
        )
        if (
            lease_id != row["lease_id"]
            or epoch != row["acquisition_epoch"]
            or not isinstance(lifecycle, dict)
            or set(lifecycle) != {"state", "disposition", "updated_at"}
            or type(lifecycle["state"]) is not str
            or (lifecycle["disposition"] is not None and type(lifecycle["disposition"]) is not str)
            or type(lifecycle["updated_at"]) is not str
        ):
            raise ValueError("legacy lease seal is not an exact lifecycle fact")
        _durable_datetime(
            lifecycle["updated_at"],
            fact=f"{identity} sealed initial update time",
        )
        if canonical_json(lifecycle) != seal["initial_lifecycle_json"]:
            raise ValueError("legacy lease lifecycle bytes are not canonical")
        if base_hash != legacy_lease_base_hash(row) or run_id != row["run_id"]:
            raise ValueError("legacy lease base contradicts its migration seal")
        return LegacyLeaseSeal(
            base_hash=base_hash,
            run_id=run_id,
            state=lifecycle["state"],
            disposition=lifecycle["disposition"],
            updated_at=lifecycle["updated_at"],
        )
    except JournalDamaged:
        raise
    except (TypeError, ValueError) as exc:
        raise JournalDamaged(f"{identity} has an invalid migration seal") from exc


def validate_legacy_lease_seal_inventory(connection: sqlite3.Connection) -> None:
    """Prove every lease has exactly its historical or current acquisition proof."""

    seals = connection.execute(
        "SELECT lease_id, acquisition_epoch FROM legacy_capability_lease_seals"
    ).fetchall()
    sealed: set[tuple[str, int]] = set()
    for seal in seals:
        lease_id = _durable_text(
            seal["lease_id"],
            fact="legacy capability lease seal identity",
        )
        acquisition_epoch = _durable_sequence(
            seal["acquisition_epoch"],
            fact=f"legacy capability lease {lease_id!r} sealed acquisition epoch",
        )
        identity = (lease_id, acquisition_epoch)
        if identity in sealed:
            raise JournalDamaged(
                "legacy capability lease seal inventory stores one fact more than once"
            )
        sealed.add(identity)
        row = connection.execute(
            "SELECT * FROM capability_leases WHERE lease_id = ? AND acquisition_epoch = ?",
            (lease_id, acquisition_epoch),
        ).fetchone()
        if row is None or legacy_lease_seal_for(connection, row) is None:
            raise JournalDamaged("legacy capability lease seal inventory has no exact primary fact")
    for row in connection.execute("SELECT * FROM capability_leases").fetchall():
        lease_id = _durable_text(row["lease_id"], fact="capability lease identity")
        acquisition_epoch = _durable_sequence(
            row["acquisition_epoch"],
            fact=f"capability lease {lease_id!r} acquisition epoch",
        )
        is_legacy = (lease_id, acquisition_epoch) in sealed
        has_current_acquisition = _has_current_lease_acquisition(connection, row)
        if is_legacy == has_current_acquisition:
            raise JournalDamaged(
                "legacy capability lease seal inventory contradicts acquisition provenance"
            )


def _has_current_lease_acquisition(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> bool:
    """Recognize only the exact acquisition event written by schema 7."""

    lease_id = _durable_text(row["lease_id"], fact="capability lease identity")
    epoch = _durable_sequence(
        row["acquisition_epoch"],
        fact=f"capability lease {lease_id!r} acquisition epoch",
    )
    run_id = _durable_text(
        row["run_id"],
        fact=f"capability lease {lease_id!r} run identity",
    )
    created_at = _durable_datetime(
        row["created_at"],
        fact=f"capability lease {lease_id!r} creation time",
    )
    resource_ref = (
        _durable_text(
            row["resource_ref"],
            fact=f"capability lease {lease_id!r} resource reference",
        )
        if row["resource_ref"] is not None
        else None
    )
    expected_payload = canonical_json(
        {
            "lease_id": lease_id,
            "acquisition_epoch": epoch,
            "binding": _durable_text(
                row["binding_id"],
                fact=f"capability lease {lease_id!r} binding",
            ),
            "resource_ref": resource_ref,
            "observed_at": created_at.isoformat(),
        }
    )
    matches = 0
    for event_row in connection.execute(
        "SELECT * FROM events WHERE run_id = ? AND kind = 'LeaseAcquired'",
        (run_id,),
    ).fetchall():
        event = stored_event_from_row(connection, event_row)
        if (
            event.path is None
            and event.created_at == created_at
            and canonical_json(event.payload) == expected_payload
        ):
            matches += 1
    if matches > 1:
        raise JournalDamaged(
            f"capability lease {lease_id!r} has duplicate current acquisition proof"
        )
    return matches == 1
