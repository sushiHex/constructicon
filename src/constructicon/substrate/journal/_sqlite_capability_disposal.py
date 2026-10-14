"""One administrative disposal relationship above sealed facts and exact histories."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import cast

from constructicon.core.address import RunId
from constructicon.core.control import (
    ADMIN_SCOPE,
    CapabilityAccountingEra,
    CapabilityAcquisitionPair,
    CapabilityDisposalRecorded,
    CapabilityDisposalRow,
    CapabilityDisposalSnapshot,
    capability_disposal_reference,
    validated_capability_disposal_command,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest, json_value
from constructicon.core.journal import JournalEvent
from constructicon.substrate.journal._sqlite_accounting import capability_lease_histories
from constructicon.substrate.journal._sqlite_capability_provenance import (
    CapabilityLeaseHistory,
    accounting_run_row,
    capability_lifecycle_at_cut,
    capability_run_world_row,
    require_accounting_absence,
    require_capability_lost_provenance,
    require_historical_initial_lost,
    require_historical_lost_event,
    validate_accounting_point,
    validate_accounting_run,
)
from constructicon.substrate.journal._sqlite_commands import (
    _sealed_command_phases_from_row,
    command_claim_fact_hash,
    command_plan_fact_hash,
)
from constructicon.substrate.journal._sqlite_execution import _capability_lease_row
from constructicon.substrate.journal._sqlite_execution_facts import (
    _stored_event_from_row_without_relationship,
    event_fact_hash,
    event_fact_key,
)
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_seal,
    require_durable_fact_seal,
)
from constructicon.substrate.journal._sqlite_runs import run_projection_for_id, run_world_fact_hash

DISPOSAL_FAMILY = "capability_disposal"
DISPOSAL_EVENT = "CapabilityDisposalRecorded"


@dataclass
class DisposalReadProofs:
    """Operation-local memo of canonical proofs in one owned read transaction.

    Never retained across an await or writer; memoization changes work, not law.
    Point callers omit this context and independently run the same projector.
    """

    connection: sqlite3.Connection
    histories: dict[RunId, list[CapabilityLeaseHistory]] = field(default_factory=dict)
    receipts: dict[str, CapabilityDisposalRecorded | None] = field(default_factory=dict)
    audits: dict[str, list[sqlite3.Row]] | None = None
    eras: dict[RunId, CapabilityAccountingEra] = field(default_factory=dict)

    def run_histories(
        self, connection: sqlite3.Connection, run_id: RunId
    ) -> list[CapabilityLeaseHistory]:
        if connection is not self.connection:
            raise JournalDamaged("disposal proof context crosses owned SQLite snapshots")
        if run_id not in self.histories:
            self.histories[run_id] = capability_lease_histories(connection, run_id)
        return self.histories[run_id]

    def run_era(self, connection: sqlite3.Connection, run_id: RunId) -> CapabilityAccountingEra:
        if connection is not self.connection:
            raise JournalDamaged("disposal proof context crosses owned SQLite snapshots")
        if run_id not in self.eras:
            self.eras[run_id] = validate_accounting_point(
                connection,
                run_id,
                self.run_histories(connection, run_id),
            )
        return self.eras[run_id]


def disposal_baseline_fact(history: CapabilityLeaseHistory, cut: int) -> dict[str, JsonValue]:
    lifecycle = capability_lifecycle_at_cut(history, cut)
    if lifecycle is None:
        raise JournalDamaged("disposal baseline acquisition did not exist at its planned cut")
    return cast(
        dict[str, JsonValue],
        json_value(
            {
                "lease": {
                    **history.lease.model_dump(mode="json"),
                    "state": lifecycle.state,
                    "disposition": lifecycle.disposition,
                },
                "created_at": history.row["created_at"],
                "updated_at": lifecycle.updated_at,
                "initial": lifecycle.initial,
                "history": [
                    event.model_dump(mode="json") for event in history.events if event.seq <= cut
                ],
            }
        ),
    )


def disposal_relationship_hash(
    command_row: sqlite3.Row,
    audit: sqlite3.Row,
    transitions: tuple[sqlite3.Row, ...],
) -> Digest:
    """Private complete reason-bearing command and plan bindings never enter public bytes."""

    return digest(
        DISPOSAL_FAMILY,
        1,
        {
            "command": str(command_claim_fact_hash(command_row)),
            "plan": str(command_plan_fact_hash(command_row)),
            "audit": str(event_fact_hash(audit)),
            "transitions": [str(event_fact_hash(row)) for row in transitions],
        },
    )


def _audit_candidates(
    connection: sqlite3.Connection,
    command_id: str,
    proofs: DisposalReadProofs | None,
) -> list[sqlite3.Row]:
    if proofs is not None:
        if connection is not proofs.connection:
            raise JournalDamaged("disposal proof context crosses owned SQLite snapshots")
        if proofs.audits is None:
            proofs.audits = {}
            for row in connection.execute("SELECT * FROM events WHERE kind = ?", (DISPOSAL_EVENT,)):
                event = _stored_event_from_row_without_relationship(connection, row)
                owner = event.payload.get("command_id") if isinstance(event.payload, dict) else None
                if not isinstance(owner, str):
                    raise JournalDamaged("disposal audit has no exact command identity")
                proofs.audits.setdefault(owner, []).append(row)
        return proofs.audits.get(command_id, [])
    selected = []
    for row in connection.execute("SELECT * FROM events WHERE kind = ?", (DISPOSAL_EVENT,)):
        event = _stored_event_from_row_without_relationship(connection, row)
        if isinstance(event.payload, dict) and event.payload.get("command_id") == command_id:
            selected.append(row)
    return selected


def project_disposal_receipt(
    connection: sqlite3.Connection,
    command_id: str,
    *,
    proofs: DisposalReadProofs | None = None,
) -> CapabilityDisposalRecorded | None:
    """Command/event/pair point and batch readers use this one independent projector."""

    if proofs is None:
        proofs = DisposalReadProofs(connection)
    if connection is not proofs.connection:
        raise JournalDamaged("disposal proof context crosses owned SQLite snapshots")
    if command_id not in proofs.receipts:
        proofs.receipts[command_id] = _project_disposal_receipt(connection, command_id, proofs)
    return proofs.receipts[command_id]


def _project_disposal_receipt(
    connection: sqlite3.Connection,
    command_id: str,
    proofs: DisposalReadProofs | None,
) -> CapabilityDisposalRecorded | None:

    relationship = durable_fact_seal(connection, family=DISPOSAL_FAMILY, fact_key=command_id)
    candidates = _audit_candidates(connection, command_id, proofs)
    command_row = connection.execute(
        "SELECT * FROM commands WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    if relationship is None and not candidates:
        # Erasing both ownership links is not a proof of absence. The immutable
        # plan independently names every possible co-transactional lost fact.
        if command_row is not None:
            command = _sealed_command_phases_from_row(connection, command_row)
            raw_plan = command.plan.get("plan") if isinstance(command.plan, dict) else None
            if isinstance(raw_plan, dict) and raw_plan.get("kind") == "capability_disposal":
                plan = validated_capability_disposal_command(command)
                histories = None
                for offset, planned in enumerate(plan.rows, 1):
                    row = connection.execute(
                        "SELECT * FROM events WHERE run_id = ? AND seq = ?",
                        (plan.run_id, plan.baseline_event_seq + offset),
                    ).fetchone()
                    if row is None:
                        continue
                    event = _stored_event_from_row_without_relationship(connection, row)
                    if (
                        event.kind == "LeaseTransition"
                        and isinstance(event.payload, dict)
                        and event.payload.get("to") == "lost"
                        and event.payload.get("lease_id") == planned.pair.lease_id
                        and event.payload.get("acquisition_epoch") == planned.pair.acquisition_epoch
                    ):
                        # An occupied audit slot proves nothing. A genuine
                        # competing batch may own this exact transition, even
                        # if its smaller audit precedes our would-be slot.
                        if histories is None:
                            histories = (
                                capability_lease_histories(connection, plan.run_id)
                                if proofs is None
                                else proofs.run_histories(connection, plan.run_id)
                            )
                        history = next(
                            (
                                item for item in histories
                                if item.lease.lease_id == planned.pair.lease_id
                                and item.lease.acquisition_epoch == planned.pair.acquisition_epoch
                            ),
                            None,
                        )
                        if history is None:
                            raise JournalDamaged("planned lost fact has no retained acquisition")
                        disposal_for_transition(connection, history, event, proofs=proofs)
        return None
    return _present_disposal_receipt(connection, command_id, proofs)


def _present_disposal_receipt(
    connection: sqlite3.Connection, command_id: str, proofs: DisposalReadProofs | None,
) -> CapabilityDisposalRecorded:
    """Memo the positive validator only; attribution never enters absence proof."""

    if proofs is not None:
        if connection is not proofs.connection:
            raise JournalDamaged("disposal proof context crosses owned SQLite snapshots")
        if command_id in proofs.receipts:
            receipt = proofs.receipts[command_id]
            if receipt is None:
                raise JournalDamaged("disposal audit contradicts its proven receipt absence")
            return receipt
    receipt = _project_present_disposal_receipt(connection, command_id, proofs)
    if proofs is not None:
        proofs.receipts[command_id] = receipt
    return receipt


def _project_present_disposal_receipt(
    connection: sqlite3.Connection, command_id: str, proofs: DisposalReadProofs | None,
) -> CapabilityDisposalRecorded:
    """The one positive relationship law, above sealed facts and structural history."""

    relationship = durable_fact_seal(connection, family=DISPOSAL_FAMILY, fact_key=command_id)
    candidates = _audit_candidates(connection, command_id, proofs)
    command_row = connection.execute(
        "SELECT * FROM commands WHERE command_id = ?", (command_id,),
    ).fetchone()
    if command_row is None or relationship is None or len(candidates) != 1:
        raise JournalDamaged("disposal relationship has no exact command and unique public audit")
    command = _sealed_command_phases_from_row(connection, command_row)
    plan = validated_capability_disposal_command(command)
    if command.state == "rejected" or ADMIN_SCOPE not in command.actor.scopes:
        raise JournalDamaged("disposed command contradicts its authorized lifecycle")
    audit_row = candidates[0]
    audit = _stored_event_from_row_without_relationship(connection, audit_row)
    try:
        receipt = CapabilityDisposalRecorded.model_validate_json(canonical_json(audit.payload))
    except (TypeError, ValueError) as exc:
        raise JournalDamaged("disposal public audit has no strict receipt payload") from exc
    expected_seq = plan.baseline_event_seq + len(plan.rows) + 1
    if (
        canonical_json(audit.payload) != canonical_json(receipt)
        or audit.path is not None
        or audit.run_id != plan.run_id
        or audit.seq != expected_seq
        or receipt.command_id != command_id
        or receipt.run_id != plan.run_id
        or receipt.manifest_hash != plan.manifest_hash
        or receipt.owner_epoch != plan.owner_epoch
        or receipt.before_event_seq != plan.baseline_event_seq
        or receipt.audit_event_seq != expected_seq
        or receipt.pairs != tuple(row.pair for row in plan.rows)
        or receipt.row_baseline_hashes != tuple(row.baseline_hash for row in plan.rows)
    ):
        raise JournalDamaged("disposal audit contradicts the exact command plan and event position")
    run = capability_run_world_row(connection, plan.run_id)
    if run_world_fact_hash(run) != plan.world_hash or run["manifest_hash"] != str(
        plan.manifest_hash
    ):
        raise JournalDamaged("disposal receipt contradicts its retained immutable run world")
    histories = (
        capability_lease_histories(connection, plan.run_id)
        if proofs is None
        else proofs.run_histories(connection, plan.run_id)
    )
    era = (
        validate_accounting_point(connection, plan.run_id, histories)
        if proofs is None
        else proofs.run_era(connection, plan.run_id)
    )
    by_pair = {
        (history.lease.lease_id, history.lease.acquisition_epoch): history for history in histories
    }
    transitions: list[sqlite3.Row] = []
    for planned, seq in zip(plan.rows, receipt.transition_event_seqs, strict=True):
        history = by_pair.get((planned.pair.lease_id, planned.pair.acquisition_epoch))
        if (
            history is None
            or history.lease.state != "lost"
            or history.lease.disposition is not None
        ):
            raise JournalDamaged("disposal receipt has no exact final lost/None acquisition")
        baseline = disposal_baseline_fact(history, plan.baseline_event_seq)
        if canonical_json(baseline) != canonical_json(planned.fact):
            raise JournalDamaged(
                "disposal receipt acquisition baseline differs from its sealed plan"
            )
        transition = connection.execute(
            "SELECT * FROM events WHERE run_id = ? AND seq = ?",
            (plan.run_id, seq),
        ).fetchone()
        if transition is None:
            raise JournalDamaged("disposal receipt lost a planned transition")
        event = _stored_event_from_row_without_relationship(connection, transition)
        payload: dict[str, JsonValue] = {
            "lease_id": planned.pair.lease_id,
            "acquisition_epoch": planned.pair.acquisition_epoch,
            "from": "active",
            "to": "lost",
            "disposition": None,
            "observed_at": event.created_at.isoformat(),
        }
        if history.legacy is not None:
            payload["legacy_base_hash"] = str(history.legacy.base_hash)
        if (
            event.kind != "LeaseTransition"
            or event.path is not None
            or canonical_json(event.payload) != canonical_json(payload)
            or event.created_at != audit.created_at
        ):
            raise JournalDamaged("disposal transition is not its exact canonical planned fact")
        # Prefix losses can only be witnessed pre-v8 history: current lost pairs cannot reactivate.
        if history.legacy is not None and history.legacy.state == "lost":
            require_historical_initial_lost(connection, history, era)
        for earlier in history.events:
            if (
                earlier.seq < seq
                and isinstance(earlier.payload, dict)
                and earlier.kind == "LeaseTransition"
                and earlier.payload.get("to") == "lost"
            ):
                require_historical_lost_event(connection, history, earlier, era)
        transitions.append(transition)
    require_durable_fact_seal(
        connection,
        family=DISPOSAL_FAMILY,
        fact_key=command_id,
        selector=event_fact_key(plan.run_id, expected_seq),
        fact_hash=disposal_relationship_hash(command_row, audit_row, tuple(transitions)),
    )
    return receipt


def disposal_for_transition(
    connection: sqlite3.Connection,
    history: CapabilityLeaseHistory,
    transition: JournalEvent,
    *,
    proofs: DisposalReadProofs | None = None,
) -> CapabilityDisposalRecorded:
    candidates = []
    # A bounded batch has at most 100 transitions; its public audit immediately follows it.
    for row in connection.execute(
        "SELECT * FROM events WHERE run_id = ? AND seq > ? AND seq <= ? AND kind = ?",
        (
            history.lease.run_id,
            transition.seq,
            min(transition.seq + 100, 2**63 - 1),
            DISPOSAL_EVENT,
        ),
    ).fetchall():
        event = _stored_event_from_row_without_relationship(connection, row)
        if not isinstance(event.payload, dict) or type(event.payload.get("command_id")) is not str:
            raise JournalDamaged("disposal audit has no exact command identity")
        receipt = _present_disposal_receipt(connection, event.payload["command_id"], proofs)
        for pair, seq in zip(receipt.pairs, receipt.transition_event_seqs, strict=True):
            if (
                pair.lease_id == history.lease.lease_id
                and pair.acquisition_epoch == history.lease.acquisition_epoch
                and seq == transition.seq
            ):
                candidates.append(receipt)
    if len(candidates) != 1:
        raise JournalDamaged("lost transition has no unique administrative disposal receipt")
    return candidates[0]


def disposal_snapshot(
    connection: sqlite3.Connection,
    run_id: RunId,
    pairs: tuple[CapabilityAcquisitionPair, ...],
    *,
    observe: Callable[[], datetime],
) -> CapabilityDisposalSnapshot:
    proofs = DisposalReadProofs(connection)
    members = proofs.run_histories(connection, run_id)
    projection = run_projection_for_id(
        connection,
        run_id,
        observe=observe,
        disposal_proofs=proofs,
    )
    raw_run = accounting_run_row(connection, run_id) if projection is not None else None
    if projection is not None:
        validate_accounting_run(connection, run_id, members)
        for member in members:
            require_capability_lost_provenance(connection, member, proofs=proofs)
    else:
        require_accounting_absence(connection, run_id)
        if members:
            raise JournalDamaged("disposal acquisition facts have no retained run")
    owners: dict[RunId, list[CapabilityLeaseHistory]] = {}
    observations: list[CapabilityDisposalRow] = []
    for pair in pairs:
        selected = _capability_lease_row(
            connection,
            lease_id=pair.lease_id,
            acquisition_epoch=pair.acquisition_epoch,
        )
        if selected is None:
            observations.append(
                CapabilityDisposalRow(
                    pair=pair,
                    run_id=None,
                    state=None,
                    disposition=None,
                    fact=None,
                    baseline_hash=None,
                )
            )
            continue
        owner = RunId(selected["run_id"])
        if owner not in owners:
            owners[owner] = proofs.run_histories(connection, owner)
            validate_accounting_run(connection, owner, owners[owner])
            for member in owners[owner]:
                require_capability_lost_provenance(connection, member, proofs=proofs)
        history = next(
            (
                item
                for item in owners[owner]
                if item.lease.lease_id == pair.lease_id
                and item.lease.acquisition_epoch == pair.acquisition_epoch
            ),
            None,
        )
        if history is None:
            raise JournalDamaged("disposal selector has no canonical acquisition history")
        cut = accounting_run_row(connection, owner)["next_event_seq"]
        fact = disposal_baseline_fact(history, cut)
        reference = None
        if history.lease.state == "lost":
            for event in reversed(history.events):
                if (
                    event.kind == "LeaseTransition"
                    and event.payload
                    and event.payload.get("to") == "lost"
                ):
                    era = validate_accounting_run(connection, owner, owners[owner])
                    if era.source != "schema7-migration" or event.seq > era.floor:
                        reference = capability_disposal_reference(
                            disposal_for_transition(connection, history, event, proofs=proofs),
                        )
                    break
        observations.append(
            CapabilityDisposalRow(
                pair=pair,
                run_id=owner,
                state=history.lease.state,
                disposition=history.lease.disposition,
                fact=fact,
                baseline_hash=digest("capability-disposal-baseline", 1, fact),
                disposal_receipt=reference,
            )
        )
    return CapabilityDisposalSnapshot(
        run=projection[0] if projection is not None else None,
        world_hash=run_world_fact_hash(raw_run) if raw_run is not None else None,
        owner_epoch=raw_run["owner_epoch"] if raw_run is not None else None,
        event_seq=raw_run["next_event_seq"] if raw_run is not None else None,
        rows=tuple(observations),
    )


def disposal_receipt_at_cut(
    connection: sqlite3.Connection,
    history: CapabilityLeaseHistory,
    cut: int,
    *,
    proofs: DisposalReadProofs | None = None,
) -> CapabilityDisposalRecorded | None:
    """Absence means witnessed opaque loss or a nonlost lifecycle at this cut."""

    era = validate_accounting_run(
        connection,
        history.lease.run_id,
        capability_lease_histories(connection, history.lease.run_id)
        if proofs is None
        else proofs.run_histories(connection, history.lease.run_id),
        through_event_seq=cut,
    )
    for event in reversed(history.events):
        if event.seq > cut or event.kind != "LeaseTransition" or not event.payload:
            continue
        if event.payload.get("to") != "lost":
            return None
        if era.source == "schema7-migration" and event.seq <= era.floor:
            require_historical_lost_event(connection, history, event, era)
            return None
        return disposal_for_transition(connection, history, event, proofs=proofs)
    return None


def validate_disposal_inventory(connection: sqlite3.Connection) -> int:
    identities = []
    for row in connection.execute(
        "SELECT * FROM events WHERE kind = ?",
        (DISPOSAL_EVENT,),
    ).fetchall():
        event = _stored_event_from_row_without_relationship(connection, row)
        if not event.payload or type(event.payload.get("command_id")) is not str:
            raise JournalDamaged("disposal audit has no canonical command identity")
        command_id = event.payload["command_id"]
        if project_disposal_receipt(connection, command_id) is None:
            raise JournalDamaged("disposal audit has no relationship")
        identities.append(command_id)
    seals = connection.execute(
        "SELECT fact_key FROM durable_fact_seals WHERE family = ?",
        (DISPOSAL_FAMILY,),
    ).fetchall()
    if len(set(identities)) != len(identities) or set(identities) != {row[0] for row in seals}:
        raise JournalDamaged("disposal relationship inventory is not bidirectional")
    return len(identities)
