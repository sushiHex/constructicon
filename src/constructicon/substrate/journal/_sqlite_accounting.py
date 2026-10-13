"""One selected-run accounting snapshot through the canonical history laws."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Literal, cast

from constructicon.core.address import RunId
from constructicon.core.control import (
    CapabilityAccountingDetail,
    CapabilityAccountingItem,
    CapabilityAccountingSnapshot,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.journal import JournalEvent
from constructicon.substrate.journal._sqlite_capability_provenance import (
    CapabilityLeaseHistory,
    accounting_run_row,
    capability_lifecycle_at_cut,
    require_accounting_absence,
    require_accounting_era,
    validate_accounting_run,
)
from constructicon.substrate.journal._sqlite_execution import (
    _LEASE_EVENT_KINDS,
    _capability_lease_from_row,
    _lease_event_identity_from_payload,
    _lease_identity_from_columns,
)
from constructicon.substrate.journal._sqlite_execution_facts import stored_event_from_row
from constructicon.substrate.journal._sqlite_runs import run_projection_for_id


def capability_accounting_snapshot(
    connection: sqlite3.Connection,
    run_id: RunId,
    *,
    observe: Callable[[], datetime],
    through_event_seq: int | None = None,
) -> CapabilityAccountingSnapshot | None:
    """Batch identities once; project only this run, retaining foreign pair edges.

    The raw global prefetch is linear, not one whole-journal UDF scan per pair.
    Unrelated rows/events are not projected or used as authority for this run.
    """

    projection = run_projection_for_id(connection, run_id, observe=observe)
    rows = connection.execute("SELECT * FROM capability_leases").fetchall()
    seals = connection.execute("SELECT * FROM legacy_capability_lease_seals").fetchall()
    event_rows = connection.execute(
        "SELECT * FROM events WHERE kind IN (?, ?) ORDER BY seq ASC",
        _LEASE_EVENT_KINDS,
    ).fetchall()
    selected = [row for row in rows if row["run_id"] == run_id]
    selected_events = [row for row in event_rows if row["run_id"] == run_id]
    selected_seals = [row for row in seals if row["run_id"] == run_id]
    if projection is None:
        require_accounting_absence(connection, run_id)
        if selected or selected_events or selected_seals:
            raise JournalDamaged("capability accounting facts have no retained run")
        return None
    record, _world, latest, _kind = projection
    latest_seq = latest or 0
    cut = latest_seq if through_event_seq is None else through_event_seq
    era = require_accounting_era(connection, accounting_run_row(connection, run_id))
    by_identity: dict[str, sqlite3.Row] = {}
    for row in selected:
        identity = _lease_identity_from_columns(row["lease_id"], row["acquisition_epoch"])
        if identity is None or identity in by_identity:
            raise JournalDamaged("capability accounting has contradictory pair identities")
        by_identity[identity] = row
    for seal in selected_seals:
        identity = _lease_identity_from_columns(seal["lease_id"], seal["acquisition_epoch"])
        if identity not in by_identity:
            raise JournalDamaged("capability legacy accounting seal has no retained pair")
    for row in selected_events:
        identity = _lease_event_identity_from_payload(row["payload"])
        if identity not in by_identity:
            raise JournalDamaged("capability accounting event has no exact retained pair")
    events: dict[str, list[JournalEvent]] = {identity: [] for identity in by_identity}
    for row in event_rows:
        identity = _lease_event_identity_from_payload(row["payload"])
        if identity in events:
            assert identity is not None
            events[identity].append(stored_event_from_row(connection, row))
    histories: list[CapabilityLeaseHistory] = []
    for identity, row in by_identity.items():
        _capability_lease_from_row(
            row,
            connection=connection,
            expected_run_id=run_id,
            histories=histories,
            prefetched_events=tuple(events[identity]),
            accounting_era=era,
        )
    validate_accounting_run(connection, run_id, histories, through_event_seq=cut)
    items: list[CapabilityAccountingItem] = []
    for history in sorted(histories, key=lambda h: (h.lease.lease_id, h.lease.acquisition_epoch)):
        lifecycle = capability_lifecycle_at_cut(history, cut)
        if lifecycle is None:
            continue
        lease = history.lease
        lost = lifecycle.state == "lost"
        items.append(
            CapabilityAccountingItem(
                lease_id=lease.lease_id,
                acquisition_epoch=lease.acquisition_epoch,
                binding_id=lease.binding_id,
                path=lease.path,
                state=cast(Literal["active", "closed", "lost"], lifecycle.state),
                disposition=cast(Literal["released", "discarded"] | None, lifecycle.disposition),
                acquisition_event_seq=lifecycle.acquisition_event_seq,
                loss="opaque_lost" if lost else None,
                physical_cleanup="unknown" if lost else None,
                disposal_receipt=None,
            )
        )
    return CapabilityAccountingSnapshot(
        run=record,
        latest_event_seq=latest_seq,
        detail=CapabilityAccountingDetail(run_id=run_id, through_event_seq=cut, items=tuple(items)),
    )
