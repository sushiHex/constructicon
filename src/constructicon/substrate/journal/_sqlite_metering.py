# mypy: disable-error-code="attr-defined"
"""Fenced native executor observations in the run's existing event journal."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import RunId
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.executor import ExecutorOutcome
from constructicon.core.identity import Digest, canonical_json, parse_json_value
from constructicon.core.manifest import CapabilityBinding, CapabilityLease
from constructicon.core.metering import (
    MeteringAttempt,
    MeteringEvidence,
    MeteringGroup,
    MeteringIntent,
    MeteringOutcome,
    MeteringSnapshot,
    MeteringSource,
)
from constructicon.core.run import CheckpointConflict, OwnershipLost, RunLease, RunStatus
from constructicon.core.workspace import LeaseContext, acquisition_id_for, lease_id_for
from constructicon.substrate.journal._sqlite_base import _durable_run_fields, _durable_sequence
from constructicon.substrate.journal._sqlite_capability_provenance import (
    capability_lifecycle_at_cut,
)
from constructicon.substrate.journal._sqlite_execution_facts import (
    _event_fact_key_position,
    _stored_event_from_row_without_relationship,
    event_fact_hash,
    event_fact_key,
)
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    durable_fact_seal,
    require_durable_fact_seal,
    store_durable_fact_seal,
)
from constructicon.substrate.journal._sqlite_runs import (
    ValidatedRunWorld,
    validated_event_fence,
    validated_run_world,
)

METERING_EVENT = "ExecutorMetering"
ERA_FAMILY = "executor_metering_era"
RELATION_FAMILY = "executor_metering_relation"
METERING_FAMILIES = frozenset({ERA_FAMILY, RELATION_FAMILY})
METERING_PAGE_LIMIT = 101
_EVENT_BATCH = 128
_Era = Literal["legacy", "current"]
_Phase = Literal["intent", "outcome"]


class _IntentPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    phase: Literal["intent"] = "intent"
    intent: MeteringIntent


class _OutcomePayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    phase: Literal["outcome"] = "outcome"
    run_id: RunId
    acquisition_id: str
    intent_seq: int
    outcome: MeteringOutcome


_Payload = _IntentPayload | _OutcomePayload


@dataclass(frozen=True)
class _PhaseFact:
    payload: _Payload
    evidence: MeteringEvidence


def _selector(run_id: RunId, acquisition_id: str, phase: _Phase) -> str:
    return canonical_json([run_id, acquisition_id, phase])


def _era_selector(run_id: RunId, era: _Era) -> str:
    return canonical_json([run_id, era])


def _era_hash(run: sqlite3.Row, era: _Era) -> Digest:
    return durable_fact_hash(
        ERA_FAMILY, [run["run_id"], run["manifest_hash"], run["input_hash"], era],
    )


def mint_metering_era(connection: sqlite3.Connection, run: sqlite3.Row, era: _Era) -> None:
    run_id = RunId(run["run_id"])
    store_durable_fact_seal(
        connection, family=ERA_FAMILY, fact_key=run_id,
        selector=_era_selector(run_id, era), fact_hash=_era_hash(run, era),
    )


def require_metering_era(connection: sqlite3.Connection, run: sqlite3.Row) -> _Era:
    run_id = RunId(run["run_id"])
    present = durable_fact_seal(connection, family=ERA_FAMILY, fact_key=run_id)
    if present is None:
        raise JournalDamaged("executor metering run has no positive era")
    era: _Era
    if present.selector == _era_selector(run_id, "legacy"):
        era = "legacy"
    elif present.selector == _era_selector(run_id, "current"):
        era = "current"
    else:
        raise JournalDamaged("executor metering run has a contradictory era")
    require_durable_fact_seal(
        connection, family=ERA_FAMILY, fact_key=run_id,
        selector=_era_selector(run_id, era), fact_hash=_era_hash(run, era),
    )
    other: _Era = "current" if era == "legacy" else "legacy"
    if durable_fact_seal(
        connection, family=ERA_FAMILY, selector=_era_selector(run_id, other),
    ) is not None:
        raise JournalDamaged("executor metering run has two eras")
    return era


def require_metering_absence(connection: sqlite3.Connection, run_id: RunId) -> None:
    for era in ("legacy", "current"):
        if durable_fact_seal(
            connection, family=ERA_FAMILY, fact_key=run_id, selector=_era_selector(run_id, era),
        ) is not None:
            raise JournalDamaged("executor metering era has no retained run")
    if next(_event_rows(connection, run_id), None) or next(
        _relation_positions(connection, run_id), None,
    ):
        raise JournalDamaged("executor metering observation has no retained run")


def _run_row(connection: sqlite3.Connection, run_id: RunId) -> sqlite3.Row | None:
    row: sqlite3.Row | None = connection.execute(
        "SELECT r.*, o.origin_json FROM runs AS r"
        " LEFT JOIN run_origins AS o ON o.run_id = r.run_id WHERE r.run_id = ?", (run_id,),
    ).fetchone()
    return row


def _require_owner(
    run: sqlite3.Row | None, lease: RunLease, *, now: datetime, dispatch: bool,
) -> None:
    if run is None:
        raise OwnershipLost("executor metering run no longer exists")
    fields = _durable_run_fields(run)
    epoch = _durable_sequence(run["owner_epoch"], fact="metering owner epoch", allow_zero=True)
    if (fields.owner_id != lease.owner_id or epoch != lease.epoch
            or fields.lease_expires_at is None or fields.lease_expires_at <= now
            or fields.status is not RunStatus.RUNNING):
        raise OwnershipLost("executor metering requires the active run owner")
    if dispatch and fields.cancel_requested:
        raise ContractViolation("executor metering cannot dispatch on a cancelled run")


def _event_rows(
    connection: sqlite3.Connection, run_id: RunId, *, cut: int = 2**63 - 1,
) -> Iterator[sqlite3.Row]:
    after = 0
    while True:
        # End the SQL statement before canonical lease/world readers register
        # their connection-local functions. Only a bounded batch is retained.
        rows = connection.execute(
            "SELECT * FROM events WHERE run_id = ? AND kind = ? AND seq > ? AND seq <= ?"
            " ORDER BY seq LIMIT ?",
            (run_id, METERING_EVENT, after, cut, _EVENT_BATCH),
        ).fetchall()
        if not rows:
            return
        yield from rows
        after = rows[-1]["seq"]


def _relation_positions(
    connection: sqlite3.Connection, run_id: RunId, *, cut: int = 2**63 - 1,
    head: int = 2**63 - 1,
) -> Iterator[int]:
    # Both independently keyed identities select this run. A moved or
    # malformed key cannot conceal the fact from its other selector.
    key_prefix = event_fact_key(run_id, 1).removesuffix('1}')  # canonical keys sort run_id first
    selector_prefix = canonical_json([run_id])[:-1] + ","
    for row in connection.execute(
        "SELECT fact_key, selector FROM durable_fact_seals WHERE family = ?"
        " AND (substr(fact_key, 1, ?) = ? OR substr(selector, 1, ?) = ?)",
        (RELATION_FAMILY, len(key_prefix), key_prefix, len(selector_prefix), selector_prefix),
    ):
        key_run, seq = _event_fact_key_position(row["fact_key"])
        if key_run != run_id:
            raise JournalDamaged("executor metering relation moved to another run")
        if seq > head:
            raise JournalDamaged("executor metering relation lies beyond its run event head")
        if seq <= cut:
            yield seq


def _phase_payload(raw: str) -> _Payload:
    try:
        payload = parse_json_value(raw)
        if not isinstance(payload, dict):
            raise ValueError("not a phase object")
        if payload.get("phase") == "intent":
            parsed: _Payload = _IntentPayload.model_validate_json(raw)
        elif payload.get("phase") == "outcome":
            parsed = _OutcomePayload.model_validate_json(raw)
        else:
            raise ValueError("unknown phase")
        if canonical_json(parsed) != raw:
            raise ValueError("phase bytes are not canonical and complete")
        return parsed
    except (TypeError, ValueError) as exc:
        raise JournalDamaged("executor metering event has an invalid phase") from exc


def _identity(payload: _Payload) -> tuple[RunId, str, _Phase]:
    if isinstance(payload, _IntentPayload):
        return payload.intent.run_id, payload.intent.acquisition_id, "intent"
    return payload.run_id, payload.acquisition_id, "outcome"


def _binding(world: ValidatedRunWorld, acquisition: CapabilityLease) -> CapabilityBinding:
    bindings = [
        binding for binding in world.manifest.capability_bindings
        if binding.scope == acquisition.path.scope and binding.binding == acquisition.binding_id
    ]
    if len(bindings) != 1:
        raise JournalDamaged("executor metering acquisition has no unique sealed binding")
    return bindings[0]


def _acquisition(
    connection: sqlite3.Connection, run_id: RunId, lease_id: str, epoch: int,
) -> tuple[CapabilityLease, MeteringEvidence, int | None]:
    from constructicon.substrate.journal._sqlite_execution import (
        _capability_lease_history_from_row,
        _capability_lease_row,
    )

    raw = _capability_lease_row(connection, lease_id=lease_id, acquisition_epoch=epoch)
    if raw is None:
        raise JournalDamaged("executor metering has no retained acquisition")
    history = _capability_lease_history_from_row(
        raw, connection=connection, expected_run_id=run_id, expected_lease_id=lease_id,
        expected_acquisition_epoch=epoch,
    )
    lifecycle = capability_lifecycle_at_cut(history, 2**63 - 1)
    if lifecycle is None or lifecycle.acquisition_event_seq is None:
        raise JournalDamaged("executor metering requires a positive acquisition event")
    acquired = lifecycle.acquisition_event_seq
    event = connection.execute(
        "SELECT * FROM events WHERE run_id = ? AND seq = ?", (run_id, acquired),
    ).fetchone()
    if event is None:
        raise JournalDamaged("executor metering acquisition event disappeared")
    closed = next((event.seq for event in history.events if event.kind == "LeaseTransition"), None)
    evidence = MeteringEvidence(event_seq=acquired, event_digest=event_fact_hash(event))
    return history.lease, evidence, closed


def _require_intent_binding(
    intent: MeteringIntent, world: ValidatedRunWorld, acquisition: CapabilityLease,
) -> None:
    binding = _binding(world, acquisition)
    selected = binding.effective_grants.model_selection
    if (
        intent.run_id != world.run_id or intent.path != acquisition.path
        or intent.lease_id != acquisition.lease_id
        or intent.acquisition_epoch != acquisition.acquisition_epoch
        or intent.acquisition_id != acquisition_id_for(
            acquisition.lease_id, acquisition.acquisition_epoch,
        )
        or intent.binding_id != binding.binding or intent.revision != binding.revision
        or intent.manifest_hash != world.manifest.manifest_hash
        or selected.kind != "explicit" or selected.model != intent.requested_model
    ):
        raise JournalDamaged("executor metering intent contradicts its sealed acquisition")


def _relation_hash(
    evidence: MeteringEvidence, intent: MeteringIntent, acquired: MeteringEvidence,
    prior: MeteringEvidence | None,
) -> Digest:
    return durable_fact_hash(
        RELATION_FAMILY,
        {"event": evidence, "acquisition": intent, "acquisition_event": acquired,
         "prior_intent": prior},
    )


def _phase_at(
    connection: sqlite3.Connection, row: sqlite3.Row, *, world: ValidatedRunWorld, era: _Era,
) -> _PhaseFact:
    """Verify one position through its event, acquisition and independent relation."""
    event = _stored_event_from_row_without_relationship(connection, row)
    if event.kind != METERING_EVENT or era != "current":
        raise JournalDamaged("executor metering phase has the wrong kind or era")
    payload = _phase_payload(row["payload"])
    run_id, acquisition_id, phase = _identity(payload)
    if run_id != event.run_id or run_id != world.run_id:
        raise JournalDamaged("executor metering phase moved from its run")
    prior = None
    if isinstance(payload, _IntentPayload):
        intent = payload.intent
    else:
        if not 0 < payload.intent_seq < event.seq:
            raise JournalDamaged("executor metering outcome has no earlier intent position")
        intent_row = connection.execute(
            "SELECT * FROM events WHERE run_id = ? AND seq = ?", (run_id, payload.intent_seq),
        ).fetchone()
        if intent_row is None or _phase_payload(intent_row["payload"]).phase != "intent":
            raise JournalDamaged("executor metering outcome has no exact intent event")
        intent_fact = _phase_at(connection, intent_row, world=world, era=era)
        assert isinstance(intent_fact.payload, _IntentPayload)
        intent = intent_fact.payload.intent
        prior = intent_fact.evidence
    if acquisition_id != intent.acquisition_id or event.path != intent.path:
        raise JournalDamaged("executor metering phase contradicts its acquisition or path")
    acquisition, acquired, closed = _acquisition(
        connection, run_id, intent.lease_id, intent.acquisition_epoch,
    )
    _require_intent_binding(intent, world, acquisition)
    if event.seq <= acquired.event_seq or (closed is not None and event.seq >= closed):
        raise JournalDamaged("executor metering phase occurred outside its retained acquisition")
    evidence = MeteringEvidence(event_seq=event.seq, event_digest=event_fact_hash(row))
    require_durable_fact_seal(
        connection, family=RELATION_FAMILY, fact_key=event_fact_key(run_id, event.seq),
        selector=_selector(run_id, acquisition_id, phase),
        fact_hash=_relation_hash(evidence, intent, acquired, prior),
    )
    return _PhaseFact(payload, evidence)


def verify_metering_event(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    run = _run_row(connection, RunId(row["run_id"]))
    if run is None:
        raise JournalDamaged("executor metering event has no retained run")
    _phase_at(
        connection, row, world=validated_run_world(connection, run),
        era=require_metering_era(connection, run),
    )


def _point(
    connection: sqlite3.Connection, *, world: ValidatedRunWorld, era: _Era,
    acquisition_id: str, phase: _Phase, cut: int = 2**63 - 1,
    prove_absence: bool = False,
) -> _PhaseFact | None:
    run_id = world.run_id
    selector = _selector(run_id, acquisition_id, phase)
    relation = durable_fact_seal(connection, family=RELATION_FAMILY, selector=selector)
    if relation is None:
        if prove_absence:
            for row in _event_rows(connection, run_id, cut=cut):
                if _identity(_phase_payload(row["payload"])) == (run_id, acquisition_id, phase):
                    raise JournalDamaged("executor metering event has no relation")
        return None
    key_run, seq = _event_fact_key_position(relation.fact_key)
    if key_run != run_id:
        raise JournalDamaged("executor metering phase moved to another run")
    if seq > cut:
        return None
    row = connection.execute(
        "SELECT * FROM events WHERE run_id = ? AND seq = ?", (run_id, seq),
    ).fetchone()
    if row is None:
        raise JournalDamaged("executor metering relation has no event")
    fact = _phase_at(connection, row, world=world, era=era)
    if _identity(fact.payload) != (run_id, acquisition_id, phase):
        raise JournalDamaged("executor metering phase contradicts its independent selector")
    return fact


@dataclass
class _Subtotal:
    intent_only: int = 0
    unavailable: int = 0
    partial: int = 0
    observed: int = 0
    input: int | None = None
    output: int | None = None

    def add(self, outcome: MeteringOutcome | None) -> None:
        if outcome is None:
            self.intent_only += 1
            return
        if outcome.coverage == "unavailable":
            self.unavailable += 1
        elif outcome.coverage == "partial":
            self.partial += 1
        else:
            self.observed += 1
        if outcome.input_tokens is not None:
            self.input = (self.input or 0) + outcome.input_tokens
        if outcome.output_tokens is not None:
            self.output = (self.output or 0) + outcome.output_tokens

    def group(self, source: MeteringSource) -> MeteringGroup:
        return MeteringGroup(
            source=source, intent_only=self.intent_only, unavailable=self.unavailable,
            partial=self.partial, observed=self.observed, known_input_tokens=self.input,
            known_output_tokens=self.output,
        )


def _snapshot(
    connection: sqlite3.Connection, run: sqlite3.Row, *, cut: int, after: int, limit: int,
) -> MeteringSnapshot:
    world = validated_run_world(connection, run)
    run_id = world.run_id
    era = require_metering_era(connection, run)
    head = _durable_sequence(run["next_event_seq"], fact="metering run head", allow_zero=True)
    # Inventory both directions before projecting: a removed event or relation
    # cannot become an empty group or an intent with unknown outcome.
    event_count = 0
    groups: dict[MeteringSource, _Subtotal] = {}
    count = 0
    attempts: list[MeteringAttempt] = []
    for row in _event_rows(connection, run_id, cut=cut):
        fact = _phase_at(connection, row, world=world, era=era)
        seq = fact.evidence.event_seq
        event_count += 1
        if not isinstance(fact.payload, _IntentPayload):
            continue
        intent = fact.payload.intent
        paired = _point(
            connection, world=world, era=era, acquisition_id=intent.acquisition_id,
            phase="outcome", cut=cut,
        )
        outcome = None
        if paired is not None:
            if not isinstance(paired.payload, _OutcomePayload) or paired.payload.intent_seq != seq:
                raise JournalDamaged("executor metering outcome belongs to another intent")
            outcome = paired.payload.outcome
        groups.setdefault(intent.source, _Subtotal()).add(outcome)
        count += 1
        if seq > after and len(attempts) < limit:
            attempts.append(MeteringAttempt(
                intent=intent, intent_evidence=fact.evidence, outcome=outcome,
                outcome_evidence=None if paired is None else paired.evidence,
            ))
    # Each distinct event above proved its exact relation. Check reverse
    # cardinality using both selectors, without retaining the whole inventory.
    relation_count = sum(1 for _ in _relation_positions(connection, run_id, cut=cut, head=head))
    if event_count != relation_count:
        raise JournalDamaged("executor metering relations have no scoped events")
    return MeteringSnapshot(
        run_id=run_id, event_seq=cut,
        coverage="legacy_unmeasured" if era == "legacy" else
                 "supported_observations" if count else "unmeasured",
        groups=tuple(groups[source].group(source) for source in sorted(groups)),
        attempt_count=count, attempts=tuple(attempts),
    )


def validate_metering_inventory(connection: sqlite3.Connection) -> int:
    expected = 0
    runs = connection.execute("SELECT r.*, o.origin_json FROM runs AS r"
                              " LEFT JOIN run_origins AS o ON o.run_id = r.run_id").fetchall()
    for run in runs:
        cut = _durable_sequence(
            run["next_event_seq"], fact="metering run event cut", allow_zero=True,
        )
        _snapshot(connection, run, cut=cut, after=0, limit=0)
        expected += 1 + sum(1 for _ in _relation_positions(
            connection, RunId(run["run_id"]), cut=cut, head=cut,
        ))
    event_count = connection.execute(
        "SELECT COUNT(*) FROM events WHERE kind = ?", (METERING_EVENT,),
    ).fetchone()[0]
    era_count = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    if event_count + era_count != expected:
        raise JournalDamaged("executor metering has events outside the run inventory")
    return expected


class _SqliteMeteringMixin:
    def executor_metering_snapshot(
        self, run_id: RunId, *, through_event_seq: int, after_intent_seq: int = 0, limit: int = 0,
    ) -> MeteringSnapshot | None:
        if (not 0 <= through_event_seq < 2**63 or not 0 <= after_intent_seq <= through_event_seq
                or not 0 <= limit <= METERING_PAGE_LIMIT):
            raise ValueError("invalid executor metering cut or page bound")
        with self._read() as connection:
            run = _run_row(connection, run_id)
            if run is None:
                require_metering_absence(connection, run_id)
                return None
            head = _durable_sequence(
                run["next_event_seq"], fact="metering run event cut", allow_zero=True,
            )
            validated_event_fence(connection, run_id=run_id, next_event_seq=head)
            if through_event_seq > head:
                raise JournalDamaged("executor metering cut is outside the retained run")
            return _snapshot(
                connection, run, cut=through_event_seq, after=after_intent_seq, limit=limit,
            )

    def executor_meter(
        self, context: LeaseContext, *, revision: str, source: MeteringSource,
        configured_model: str,
    ) -> AcquisitionMeter:
        return AcquisitionMeter(self, context, revision, source, configured_model)

    def _check_metering_dispatch(self, lease: RunLease) -> None:
        with self._read() as connection:
            _require_owner(
                _run_row(connection, lease.run_id), lease, now=self._now(), dispatch=True,
            )

    def _write_metering_phase(
        self, context: LeaseContext, *, revision: str, source: MeteringSource,
        configured_model: str, outcome: MeteringOutcome | None,
    ) -> tuple[int | None, bool]:
        from constructicon.substrate.journal._sqlite_execution import _run_mutation_row

        lease = context.run_lease
        phase: _Phase = "intent" if outcome is None else "outcome"
        with self._txn() as connection:
            run = _run_row(connection, lease.run_id)
            if run is None:
                raise OwnershipLost("executor metering run no longer exists")
            world = validated_run_world(connection, run)
            era = require_metering_era(connection, run)
            _require_owner(run, lease, now=self._now(), dispatch=phase == "intent")
            if era == "legacy":
                return None, False
            logical = lease_id_for(lease.run_id, context.path, context.binding.binding)
            acquisition, acquired, closed = _acquisition(
                connection, lease.run_id, logical, lease.epoch,
            )
            if closed is not None or acquisition.state != "active":
                raise ContractViolation("executor metering requires the active acquisition")
            binding = _binding(world, acquisition)
            if (binding != context.binding or world.manifest.manifest_hash != context.manifest_hash
                    or binding.revision != revision
                    or binding.effective_grants.model_selection.model != configured_model):
                raise ContractViolation("executor meter differs from its assembled sealed route")
            intent = MeteringIntent(
                run_id=lease.run_id, acquisition_id=acquisition_id_for(logical, lease.epoch),
                lease_id=logical, acquisition_epoch=lease.epoch, path=acquisition.path,
                binding_id=binding.binding, revision=binding.revision,
                manifest_hash=world.manifest.manifest_hash, source=source, origin="actual",
                requested_model=configured_model,
            )
            _require_intent_binding(intent, world, acquisition)
            prior = None
            payload: _Payload
            if outcome is None:
                payload = _IntentPayload(intent=intent)
            else:
                retained = _point(
                    connection, world=world, era=era, acquisition_id=intent.acquisition_id,
                    phase="intent", prove_absence=True,
                )
                if retained is None or retained.payload != _IntentPayload(intent=intent):
                    raise ContractViolation("executor metering outcome has no matching intent")
                prior = retained.evidence
                payload = _OutcomePayload(
                    run_id=lease.run_id, acquisition_id=intent.acquisition_id,
                    intent_seq=prior.event_seq, outcome=outcome,
                )
            existing = _point(
                connection, world=world, era=era, acquisition_id=intent.acquisition_id,
                phase=phase, prove_absence=True,
            )
            if existing is not None:
                if existing.payload != payload:
                    raise CheckpointConflict("metering phase already retained different facts")
                return existing.evidence.event_seq, False
            if _run_mutation_row(connection, lease.run_id) is None:
                raise OwnershipLost("executor metering run no longer exists")
            self.fault_probe(f"metering.{phase}.before_event")
            seq = self._allocate_seq(connection, lease)
            self._insert_event_fact(
                connection, lease.run_id, seq, METERING_EVENT, intent.path,
                payload.model_dump(mode="json"),
            )
            row = connection.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq = ?", (lease.run_id, seq),
            ).fetchone()
            assert row is not None
            evidence = MeteringEvidence(event_seq=seq, event_digest=event_fact_hash(row))
            store_durable_fact_seal(
                connection, family=RELATION_FAMILY, fact_key=event_fact_key(lease.run_id, seq),
                selector=_selector(lease.run_id, intent.acquisition_id, phase),
                fact_hash=_relation_hash(evidence, intent, acquired, prior),
            )
            _phase_at(connection, row, world=world, era=era)
            self.fault_probe(f"metering.{phase}.before_commit")
            _require_owner(run, lease, now=self._now(), dispatch=phase == "intent")
        self.fault_probe(f"metering.{phase}.after_commit")
        return seq, True


class AcquisitionMeter:
    """Single-acquisition writer handed only to exact native route implementations."""

    def __init__(
        self, store: _SqliteMeteringMixin, context: LeaseContext, revision: str,
        source: MeteringSource, configured_model: str,
    ) -> None:
        self._store, self._context, self._revision = store, context, revision
        self._source, self._model = source, configured_model
        self._intended = False
        self._intent_called = False
        self._pending_dispatch = False

    def intend(self) -> None:
        if self._intent_called:
            raise ContractViolation("an acquisition may intend only one metered dispatch")
        self._intent_called = True
        seq, fresh = self._store._write_metering_phase(
            self._context, revision=self._revision, source=self._source,
            configured_model=self._model, outcome=None,
        )
        if seq is not None and not fresh:
            raise ContractViolation("replayed metering intent cannot authorize dispatch")
        self._intended = seq is not None
        self._pending_dispatch = True

    def check_dispatch(self) -> None:
        if not self._pending_dispatch:
            raise ContractViolation("dispatch has no fresh metering intent")
        self._pending_dispatch = False
        self._store._check_metering_dispatch(self._context.run_lease)

    def settle(self, outcome: ExecutorOutcome | None) -> None:
        if not self._intended:
            return
        if outcome is not None and outcome.requested_model not in (None, self._model):
            raise ContractViolation("executor observation names another requested model")
        usage = outcome.usage if outcome is not None else None
        def bounded(value: int | None) -> int | None:
            return value if type(value) is int and 0 <= value < 2**63 else None
        inp = bounded(usage.input_tokens) if usage is not None else None
        out = bounded(usage.output_tokens) if usage is not None else None
        result = outcome.status if outcome is not None else "failure"
        served = outcome.served_model if outcome is not None else None
        if served is not None and (
            not 0 < len(served) <= 128 or not served.isascii() or not served[0].isalnum()
            or not all(ch.isalnum() or ch in "_.:-" for ch in served)
        ):
            served = None
        dispatched = inp is not None or out is not None or served is not None or result == "success"
        observation = MeteringOutcome(
            coverage="observed" if result == "success" and inp is not None and out is not None
                     else "partial" if inp is not None or out is not None else "unavailable",
            served_model=served, input_tokens=inp, output_tokens=out, result=result,
            dispatch="dispatched" if dispatched else "possibly_dispatched",
        )
        self._store._write_metering_phase(
            self._context, revision=self._revision, source=self._source,
            configured_model=self._model, outcome=observation,
        )
