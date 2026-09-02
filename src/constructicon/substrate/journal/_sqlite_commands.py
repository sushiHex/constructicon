"""The one projection from a durable command row to its L0 fact."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar, cast

from pydantic import ValidationError

from constructicon.core.control import (
    CommandRecord,
    HistoricalDomainPlanEvidence,
    HistoricalPlanEvidence,
    HistoricalResumePlanEvidence,
    command_id_for,
    command_request_hash,
    domain_plan_requires_historical_evidence,
    resume_plan_requires_historical_evidence,
    run_id_for_command,
    validate_idempotency_key,
    validated_new_domain_command_plan,
    validated_new_resume_command_plan,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json, parse_json_value
from constructicon.substrate.journal._sqlite_actors import durable_authenticated_actor
from constructicon.substrate.journal._sqlite_base import (
    _durable_datetime,
    _durable_digest,
    _durable_sequence,
    _durable_text,
)
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    durable_fact_seal,
    require_durable_fact_seal,
    sealed_fact_hash,
    store_durable_fact_seal,
)

_COMMAND_FACT_FAMILY = "command_claim"
_COMMAND_PLAN_FACT_FAMILY = "command_plan"
_COMMAND_TERMINAL_FACT_FAMILY = "command_terminal"
RESUME_PLAN_ERA_FACT_FAMILY = "resume_plan_pre_v7"
DOMAIN_PLAN_ERA_FACT_FAMILY = "domain_plan_pre_v7"

_EvidenceT = TypeVar("_EvidenceT", bound=HistoricalPlanEvidence)
# The descriptor only ever hands its witness type out, so it is covariant in
# it; the functions below take an era and a witness together, so they are not.
_EvidenceT_co = TypeVar("_EvidenceT_co", bound=HistoricalPlanEvidence, covariant=True)


@dataclass(frozen=True)
class _PlanEra(Generic[_EvidenceT_co]):
    """One family of plans older than a law, and how migration witnessed them.

    The mechanism is the same for every such family: the migration classifies
    each retained command from its bytes, writes one witness naming the phase
    it found the command in, and binds that witness to the claim, the plan, and
    — when the command had already finished — the exact response. What differs
    is only which bytes count as older than the law and which witness type says
    so, and that is all a family has to supply.
    """

    family: str
    label: str
    requires_evidence: Callable[[CommandRecord], bool]
    evidence: type[_EvidenceT_co]


_RESUME_PLAN_ERA: _PlanEra[HistoricalResumePlanEvidence] = _PlanEra(
    family=RESUME_PLAN_ERA_FACT_FAMILY,
    label="resume",
    requires_evidence=resume_plan_requires_historical_evidence,
    evidence=HistoricalResumePlanEvidence,
)
_DOMAIN_PLAN_ERA: _PlanEra[HistoricalDomainPlanEvidence] = _PlanEra(
    family=DOMAIN_PLAN_ERA_FACT_FAMILY,
    label="domain",
    requires_evidence=domain_plan_requires_historical_evidence,
    evidence=HistoricalDomainPlanEvidence,
)
_PLAN_ERAS: tuple[_PlanEra[HistoricalPlanEvidence], ...] = (
    _RESUME_PLAN_ERA,
    _DOMAIN_PLAN_ERA,
)


def _command_claim_fact_hash_from_values(
    command_id_raw: object,
    actor_id_raw: object,
    actor_json_raw: object,
    operation_raw: object,
    idempotency_key_raw: object,
    request_hash_raw: object,
    request_json_raw: object,
    created_at_raw: object,
) -> Digest:
    command_id = _durable_text(command_id_raw, fact="command identity")
    return durable_fact_hash(
        _COMMAND_FACT_FAMILY,
        {
            "command_id": command_id,
            "actor_id": _durable_text(
                actor_id_raw,
                fact=f"command {command_id!r} actor identity",
            ),
            "actor_json": _durable_text(
                actor_json_raw,
                fact=f"command {command_id!r} actor payload",
            ),
            "operation": _durable_text(
                operation_raw,
                fact=f"command {command_id!r} operation",
            ),
            "idempotency_key": _durable_text(
                idempotency_key_raw,
                fact=f"command {command_id!r} idempotency key",
            ),
            "request_hash": str(
                _durable_digest(
                    request_hash_raw,
                    fact=f"command {command_id!r} request hash",
                )
            ),
            "request_json": _durable_text(
                request_json_raw,
                fact=f"command {command_id!r} request payload",
            ),
            "created_at": _durable_text(
                created_at_raw,
                fact=f"command {command_id!r} creation time",
            ),
        },
    )


def command_claim_fact_hash(row: sqlite3.Row) -> Digest:
    """Identity of the immutable claim fields, retaining exact JSON bytes."""

    return _command_claim_fact_hash_from_values(
        row["command_id"],
        row["actor_id"],
        row["actor_json"],
        row["operation"],
        row["idempotency_key"],
        row["request_hash"],
        row["request_json"],
        row["created_at"],
    )


def _command_plan_fact_hash_from_values(
    command_id_raw: object,
    plan_json_raw: object,
) -> Digest:
    command_id = _durable_text(command_id_raw, fact="command identity")
    return durable_fact_hash(
        _COMMAND_PLAN_FACT_FAMILY,
        {
            "command_id": command_id,
            "plan_json": _durable_text(
                plan_json_raw,
                fact=f"command {command_id!r} plan payload",
            ),
        },
    )


def command_plan_fact_hash(row: sqlite3.Row) -> Digest:
    return _command_plan_fact_hash_from_values(row["command_id"], row["plan_json"])


def _plan_era_selector(evidence: HistoricalPlanEvidence) -> str:
    return canonical_json(evidence.model_dump(mode="json"))


def _plan_era_fact_hash(
    era: _PlanEra[_EvidenceT],
    row: sqlite3.Row,
    evidence: _EvidenceT,
) -> Digest:
    """Bind one pre-law plan and the exact phase observed at migration."""

    command_id = _durable_text(
        row["command_id"],
        fact=f"historical {era.label} command identity",
    )
    exact_fields = {
        "command_id": command_id,
        "command_claim_hash": str(command_claim_fact_hash(row)),
        "command_plan_hash": str(command_plan_fact_hash(row)),
        "command_terminal_hash": (
            str(command_terminal_fact_hash(row))
            if evidence.phase_at_migration == "terminal"
            else None
        ),
        "evidence": evidence.model_dump(mode="json"),
    }
    return durable_fact_hash(era.family, exact_fields)


def resume_plan_era_fact_hash(
    row: sqlite3.Row,
    *,
    evidence: HistoricalResumePlanEvidence,
) -> Digest:
    """Bind one weak/raw resume plan and the exact phase observed at migration."""

    return _plan_era_fact_hash(_RESUME_PLAN_ERA, row, evidence)


def domain_plan_era_fact_hash(
    row: sqlite3.Row,
    *,
    evidence: HistoricalDomainPlanEvidence,
) -> Digest:
    """Bind one pre-exact-proof domain plan and the phase observed at migration."""

    return _plan_era_fact_hash(_DOMAIN_PLAN_ERA, row, evidence)


def _command_terminal_fact_hash_from_values(
    command_id_raw: object,
    state_raw: object,
    response_json_raw: object,
    owner_id_raw: object,
    owner_epoch_raw: object,
    lease_expires_at_raw: object,
    updated_at_raw: object,
    completed_at_raw: object,
) -> Digest:
    command_id = _durable_text(command_id_raw, fact="command identity")
    owner_id = (
        _durable_text(owner_id_raw, fact=f"command {command_id!r} owner identity")
        if owner_id_raw is not None
        else None
    )
    lease_expires_at = (
        _durable_text(
            lease_expires_at_raw,
            fact=f"command {command_id!r} lease expiry",
        )
        if lease_expires_at_raw is not None
        else None
    )
    return durable_fact_hash(
        _COMMAND_TERMINAL_FACT_FAMILY,
        {
            "command_id": command_id,
            "state": _durable_text(state_raw, fact=f"command {command_id!r} state"),
            "response_json": _durable_text(
                response_json_raw,
                fact=f"command {command_id!r} response payload",
            ),
            "owner_id": owner_id,
            "owner_epoch": _durable_sequence(
                owner_epoch_raw,
                fact=f"command {command_id!r} owner epoch",
                allow_zero=True,
                kind="owner epoch",
            ),
            "lease_expires_at": lease_expires_at,
            "updated_at": _durable_text(
                updated_at_raw,
                fact=f"command {command_id!r} update time",
            ),
            "completed_at": _durable_text(
                completed_at_raw,
                fact=f"command {command_id!r} completion time",
            ),
        },
    )


def command_terminal_fact_hash(row: sqlite3.Row) -> Digest:
    return _command_terminal_fact_hash_from_values(
        row["command_id"],
        row["state"],
        row["response_json"],
        row["owner_id"],
        row["owner_epoch"],
        row["lease_expires_at"],
        row["updated_at"],
        row["completed_at"],
    )


def _command_seal_hash(family: str, command_id: object, fact: Digest) -> str:
    """The value the seal row stores, for a family keyed by command identity.

    SQL compares against the stored column, so it must bind the identity the
    same way the seal layer did on the way in — see `sealed_fact_hash`.
    """

    key = _durable_text(command_id, fact="command identity")
    return str(sealed_fact_hash(family=family, fact_key=key, selector=key, fact=fact))


def _sqlite_command_claim_fact_hash(
    command_id: object,
    actor_id: object,
    actor_json: object,
    operation: object,
    idempotency_key: object,
    request_hash: object,
    request_json: object,
    created_at: object,
) -> str | None:
    """SQLite UDF: hash exact immutable claim scalars or mark them invalid."""

    try:
        return _command_seal_hash(
            _COMMAND_FACT_FAMILY,
            command_id,
            _command_claim_fact_hash_from_values(
                command_id,
                actor_id,
                actor_json,
                operation,
                idempotency_key,
                request_hash,
                request_json,
                created_at,
            ),
        )
    except JournalDamaged:
        return None


def _sqlite_command_plan_fact_hash(
    command_id: object,
    plan_json: object,
) -> str | None:
    try:
        return _command_seal_hash(
            _COMMAND_PLAN_FACT_FAMILY,
            command_id,
            _command_plan_fact_hash_from_values(command_id, plan_json),
        )
    except JournalDamaged:
        return None


def _sqlite_command_terminal_fact_hash(
    command_id: object,
    state: object,
    response_json: object,
    owner_id: object,
    owner_epoch: object,
    lease_expires_at: object,
    updated_at: object,
    completed_at: object,
) -> str | None:
    try:
        return _command_seal_hash(
            _COMMAND_TERMINAL_FACT_FAMILY,
            command_id,
            _command_terminal_fact_hash_from_values(
                command_id,
                state,
                response_json,
                owner_id,
                owner_epoch,
                lease_expires_at,
                updated_at,
                completed_at,
            ),
        )
    except JournalDamaged:
        return None


def register_command_seal_hashes(connection: sqlite3.Connection) -> None:
    connection.create_function(
        "constructicon_command_claim_seal_hash",
        8,
        _sqlite_command_claim_fact_hash,
        deterministic=True,
    )
    connection.create_function(
        "constructicon_command_plan_seal_hash",
        2,
        _sqlite_command_plan_fact_hash,
        deterministic=True,
    )
    connection.create_function(
        "constructicon_command_terminal_seal_hash",
        8,
        _sqlite_command_terminal_fact_hash,
        deterministic=True,
    )


def _require_plan_era(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    record: CommandRecord,
    era: _PlanEra[_EvidenceT],
) -> _EvidenceT | None:
    """A witness where the bytes call for one, and none where they do not."""

    marker = durable_fact_seal(
        connection,
        family=era.family,
        fact_key=record.command_id,
    )
    requires_marker = era.requires_evidence(record)
    if not requires_marker:
        if marker is not None:
            raise JournalDamaged(
                f"command {record.command_id!r} carries historical era evidence"
                " outside its wire era"
            )
        return None
    if marker is None:
        raise JournalDamaged(
            f"durable {era.family!r} fact {record.command_id!r} has no positive seal"
        )
    try:
        evidence = era.evidence.model_validate_json(marker.selector)
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(
            f"historical {era.label} command {record.command_id!r} has an invalid era selector"
        ) from exc
    if (
        canonical_json(evidence.model_dump(mode="json")) != marker.selector
        or evidence.command_id != record.command_id
    ):
        raise JournalDamaged(
            f"historical {era.label} command {record.command_id!r} has a contradictory era"
            " selector"
        )
    if evidence.phase_at_migration == "terminal" and record.state == "prepared":
        raise JournalDamaged(
            f"historical {era.label} command {record.command_id!r} lost its migrated"
            " terminal phase"
        )
    require_durable_fact_seal(
        connection,
        family=era.family,
        fact_key=record.command_id,
        selector=marker.selector,
        fact_hash=_plan_era_fact_hash(era, row, evidence),
    )
    return evidence


def require_resume_plan_era(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    record: CommandRecord,
) -> HistoricalResumePlanEvidence | None:
    return _require_plan_era(connection, row, record, _RESUME_PLAN_ERA)


def require_domain_plan_era(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    record: CommandRecord,
) -> HistoricalDomainPlanEvidence | None:
    return _require_plan_era(connection, row, record, _DOMAIN_PLAN_ERA)


def _seal_plan_eras(connection: sqlite3.Connection, era: _PlanEra[_EvidenceT]) -> None:
    for row in connection.execute("SELECT * FROM commands ORDER BY command_id"):
        record = _sealed_command_phases_from_row(connection, row)
        if not era.requires_evidence(record):
            continue
        evidence = era.evidence(
            command_id=record.command_id,
            phase_at_migration=("prepared" if record.state == "prepared" else "terminal"),
        )
        store_durable_fact_seal(
            connection,
            family=era.family,
            fact_key=record.command_id,
            selector=_plan_era_selector(evidence),
            fact_hash=_plan_era_fact_hash(era, row, evidence),
        )


def seal_resume_plan_eras(connection: sqlite3.Connection) -> None:
    """Classify every retained historical resume-plan wire era during migration."""

    _seal_plan_eras(connection, _RESUME_PLAN_ERA)


def seal_domain_plan_eras(connection: sqlite3.Connection) -> None:
    """Witness every retained pre-exact-proof domain plan during migration.

    Sound only because it runs at migration and nowhere else. A command that is
    claimed but unplanned when the migration looks gets no witness, so a plan
    stored for it afterwards must carry the current shape — the witness binds
    the plan hash, and there was no plan to bind.
    """

    _seal_plan_eras(connection, _DOMAIN_PLAN_ERA)


def command_plan_exists(column: str) -> str:
    """The SQL spelling of ``record.plan is not None``, for one plan column.

    Whether a command carries a plan gets asked in two languages, and they must
    ask the same question of the same bytes. JSON ``null`` is the one value
    where they can part company: four bytes that are SQL-non-NULL and decode to
    nothing. A column test that stops at ``IS NOT NULL`` therefore claims a plan
    the decoder will deny, and the seal it demands was never written.

    The writer refuses those bytes outright, so no current store can hold them.
    This keeps every reading of an older one honest: unplanned, not damaged.
    """

    return f"({column} IS NOT NULL AND {column} != 'null')"


def validate_command_claim_integrity(connection: sqlite3.Connection) -> None:
    """No seal without its command, and no phase seal before its phase.

    One indexed join and no hashing at all. A bounded read keeps this, because
    its answer can depend on a row's absence: erase the newest command of an
    operation and the next key derivation is handed an older one, so a spent
    key could be spent again. The seal the erased row leaves behind is the only
    thing that says so, and finding it is a join.
    """

    orphan = connection.execute(
        "SELECT s.family, s.fact_key FROM durable_fact_seals AS s"
        " LEFT JOIN commands AS c ON c.command_id = s.fact_key"
        " WHERE s.family IN (?, ?, ?)"
        " AND (c.command_id IS NULL"
        f" OR (s.family = ? AND NOT {command_plan_exists('c.plan_json')})"
        " OR (s.family = ? AND c.state = 'prepared')) LIMIT 1",
        (
            _COMMAND_FACT_FAMILY,
            _COMMAND_PLAN_FACT_FAMILY,
            _COMMAND_TERMINAL_FACT_FAMILY,
            _COMMAND_PLAN_FACT_FAMILY,
            _COMMAND_TERMINAL_FACT_FAMILY,
        ),
    ).fetchone()
    if orphan is not None:
        fact_key = _durable_text(
            orphan["fact_key"],
            fact="orphaned command phase seal identity",
        )
        raise JournalDamaged(
            f"command {fact_key!r} is missing or precedes its sealed phase"
        )


def validate_command_content_inventory(connection: sqlite3.Connection) -> None:
    """Re-derive every retained command's phase hashes from its own columns.

    This re-hashes the whole table, so it is a whole-store claim and runs where
    whole-store claims are made — at open. A bounded read proves the rows it
    actually returns instead, through `sealed_command_from_row`; content damage
    to a row it never hands back is not that read's question to answer, and
    making it one charged every lookup for the whole store.
    """

    register_command_seal_hashes(connection)
    anomaly = connection.execute(
        "SELECT c.* FROM commands AS c"
        " LEFT JOIN durable_fact_seals AS claim"
        " ON claim.family = ? AND claim.fact_key = c.command_id"
        " AND claim.selector = c.command_id"
        " LEFT JOIN durable_fact_seals AS plan"
        " ON plan.family = ? AND plan.fact_key = c.command_id"
        " AND plan.selector = c.command_id"
        " LEFT JOIN durable_fact_seals AS terminal"
        " ON terminal.family = ? AND terminal.fact_key = c.command_id"
        " AND terminal.selector = c.command_id"
        " WHERE constructicon_command_claim_seal_hash("
        " c.command_id, c.actor_id, c.actor_json, c.operation,"
        " c.idempotency_key, c.request_hash, c.request_json, c.created_at"
        " ) IS NULL"
        " OR claim.fact_hash IS NULL"
        " OR claim.fact_hash IS NOT constructicon_command_claim_seal_hash("
        " c.command_id, c.actor_id, c.actor_json, c.operation,"
        " c.idempotency_key, c.request_hash, c.request_json, c.created_at"
        " )"
        f" OR (NOT {command_plan_exists('c.plan_json')} AND plan.fact_hash IS NOT NULL)"
        f" OR ({command_plan_exists('c.plan_json')} AND ("
        " plan.fact_hash IS NULL"
        " OR plan.fact_hash IS NOT constructicon_command_plan_seal_hash("
        " c.command_id, c.plan_json)))"
        " OR (c.state = 'prepared' AND terminal.fact_hash IS NOT NULL)"
        " OR (c.state != 'prepared' AND ("
        " terminal.fact_hash IS NULL"
        " OR terminal.fact_hash IS NOT constructicon_command_terminal_seal_hash("
        " c.command_id, c.state, c.response_json, c.owner_id, c.owner_epoch,"
        " c.lease_expires_at, c.updated_at, c.completed_at)"
        " )) LIMIT 1",
        (
            _COMMAND_FACT_FAMILY,
            _COMMAND_PLAN_FACT_FAMILY,
            _COMMAND_TERMINAL_FACT_FAMILY,
        ),
    ).fetchone()
    if anomaly is not None:
        # The canonical projector supplies precise identity/content diagnostics.
        sealed_command_from_row(connection, anomaly)
        raise JournalDamaged("command claim inventory is contradictory")


def _validate_plan_era_inventory(
    connection: sqlite3.Connection,
    era: _PlanEra[_EvidenceT],
) -> int:
    """Set equality between the commands that need a witness and the witnesses.

    A count could not tell a balanced substitution from the truth; the sets
    can. This decodes each command in turn and proves its phase seals, so its
    cost is the whole store however few rows a caller asked for — a whole-store
    claim, made where whole-store claims are made, at open.
    """

    expected_marker_keys: set[str] = set()
    for row in connection.execute("SELECT * FROM commands ORDER BY command_id"):
        record = sealed_command_from_row(connection, row)
        if era.requires_evidence(record):
            expected_marker_keys.add(record.command_id)
    marker_keys: set[str] = set()
    marker_count = 0
    for row in connection.execute(
        "SELECT fact_key FROM durable_fact_seals WHERE family = ?",
        (era.family,),
    ):
        marker_count += 1
        marker_keys.add(
            _durable_text(row["fact_key"], fact=f"{era.label}-plan era seal identity")
        )
    if marker_keys != expected_marker_keys or len(marker_keys) != marker_count:
        raise JournalDamaged(
            f"{era.label}-plan era seal inventory has an orphan or missing fact"
        )
    return marker_count


def validate_resume_plan_era_inventory(connection: sqlite3.Connection) -> int:
    return _validate_plan_era_inventory(connection, _RESUME_PLAN_ERA)


def validate_domain_plan_era_inventory(connection: sqlite3.Connection) -> int:
    return _validate_plan_era_inventory(connection, _DOMAIN_PLAN_ERA)


def validate_command_claim_inventory(connection: sqlite3.Connection) -> int:
    """Every whole-store command proof, for the open path that owes them.

    Returns how many migration witnesses the store holds across every plan era,
    which the global seal inventory adds to the primary facts it expects.
    """

    validate_command_claim_integrity(connection)
    validate_command_content_inventory(connection)
    return sum(_validate_plan_era_inventory(connection, era) for era in _PLAN_ERAS)


def seal_command_claim(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Write or reconcile the positive seal for one exact command claim."""

    record = command_from_row(row)
    store_durable_fact_seal(
        connection,
        family=_COMMAND_FACT_FAMILY,
        fact_key=record.command_id,
        selector=record.command_id,
        fact_hash=command_claim_fact_hash(row),
    )


def seal_command_phases(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Seal each immutable phase the command has durably crossed."""

    record = command_from_row(row)
    if record.plan is not None:
        store_durable_fact_seal(
            connection,
            family=_COMMAND_PLAN_FACT_FAMILY,
            fact_key=record.command_id,
            selector=record.command_id,
            fact_hash=command_plan_fact_hash(row),
        )
    if record.state != "prepared":
        store_durable_fact_seal(
            connection,
            family=_COMMAND_TERMINAL_FACT_FAMILY,
            fact_key=record.command_id,
            selector=record.command_id,
            fact_hash=command_terminal_fact_hash(row),
        )


def sealed_command_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> CommandRecord:
    """Project one command through every phase and resume-era proof."""

    record = _sealed_command_phases_from_row(connection, row)
    for era in _PLAN_ERAS:
        _require_plan_era(connection, row, record, era)
    return record


def seal_current_command_plan(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> CommandRecord:
    """Seal and project one plan written by the current command store."""

    seal_command_phases(connection, row)
    record = _sealed_command_phases_from_row(connection, row)
    validated_new_resume_command_plan(record)
    validated_new_domain_command_plan(record)
    for era in _PLAN_ERAS:
        _require_plan_era(connection, row, record, era)
    return record


def _sealed_command_phases_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> CommandRecord:
    """Project sealed command phases while a migration-era seal is pending."""

    record = command_from_row(row)
    require_durable_fact_seal(
        connection,
        family=_COMMAND_FACT_FAMILY,
        fact_key=record.command_id,
        selector=record.command_id,
        fact_hash=command_claim_fact_hash(row),
    )
    plan_seal = durable_fact_seal(
        connection,
        family=_COMMAND_PLAN_FACT_FAMILY,
        fact_key=record.command_id,
        selector=record.command_id,
    )
    if record.plan is None:
        if plan_seal is not None:
            raise JournalDamaged(
                f"command {record.command_id!r} precedes its sealed plan phase"
            )
    else:
        require_durable_fact_seal(
            connection,
            family=_COMMAND_PLAN_FACT_FAMILY,
            fact_key=record.command_id,
            selector=record.command_id,
            fact_hash=command_plan_fact_hash(row),
        )
    terminal_seal = durable_fact_seal(
        connection,
        family=_COMMAND_TERMINAL_FACT_FAMILY,
        fact_key=record.command_id,
        selector=record.command_id,
    )
    if record.state == "prepared":
        if terminal_seal is not None:
            raise JournalDamaged(
                f"command {record.command_id!r} precedes its sealed terminal phase"
            )
    else:
        require_durable_fact_seal(
            connection,
            family=_COMMAND_TERMINAL_FACT_FAMILY,
            fact_key=record.command_id,
            selector=record.command_id,
            fact_hash=command_terminal_fact_hash(row),
        )
    return record


def command_for_id(
    connection: sqlite3.Connection,
    command_id: str,
) -> CommandRecord | None:
    """Select by relational or derived identity before deciding absence."""

    rows = connection.execute(
        "SELECT * FROM commands WHERE command_id = ?"
        " OR constructicon_command_id(actor_id, operation, idempotency_key) = ?"
        " OR constructicon_command_id(actor_id, operation, idempotency_key) IS NULL"
        " LIMIT 2",
        (command_id, command_id),
    ).fetchall()
    if len(rows) > 1:
        raise JournalDamaged(
            f"command {command_id!r} has contradictory durable selectors"
        )
    if rows:
        record = sealed_command_from_row(connection, rows[0])
        if record.command_id != command_id:
            raise JournalDamaged(
                f"command {command_id!r} contradicts its requested selector"
            )
        return record
    seal = durable_fact_seal(
        connection,
        family=_COMMAND_FACT_FAMILY,
        fact_key=command_id,
        selector=command_id,
    )
    if seal is not None:
        raise JournalDamaged(
            f"command {command_id!r} is missing behind its positive claim seal"
        )
    dependent = connection.execute(
        "SELECT 1 FROM durable_fact_seals"
        " WHERE family IN (?, ?, ?, ?) AND fact_key = ?"
        " UNION ALL SELECT 1 FROM runs WHERE creation_command_id = ?"
        " UNION ALL SELECT 1 FROM run_origins WHERE run_id = ?"
        " UNION ALL SELECT 1 FROM approvals WHERE command_id = ?"
        " UNION ALL SELECT 1 FROM channel_messages WHERE command_id = ?"
        " UNION ALL SELECT 1 FROM channel_acks"
        " WHERE command_id = ? AND ack_provenance_version = 1"
        " LIMIT 1",
        (
            _COMMAND_PLAN_FACT_FAMILY,
            _COMMAND_TERMINAL_FACT_FAMILY,
            RESUME_PLAN_ERA_FACT_FAMILY,
            # Cross-owner absence guard: execution facts own this persisted
            # family; command projection only refuses a missing dependency.
            "resume_attempt",
            command_id,
            command_id,
            str(run_id_for_command(command_id)),
            command_id,
            command_id,
            command_id,
        ),
    ).fetchone()
    if dependent is not None:
        raise JournalDamaged(
            f"command {command_id!r} is missing behind a dependent durable fact"
        )
    return None


def _historical_plan_evidence_for_id(
    connection: sqlite3.Connection,
    command_id: str,
    era: _PlanEra[_EvidenceT],
) -> _EvidenceT | None:
    """Project one migration-only era through the canonical command."""

    record = command_for_id(connection, command_id)
    if record is None:
        return None
    row = connection.execute(
        "SELECT * FROM commands WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    assert row is not None
    return _require_plan_era(connection, row, record, era)


def historical_resume_plan_evidence_for_id(
    connection: sqlite3.Connection,
    command_id: str,
) -> HistoricalResumePlanEvidence | None:
    return _historical_plan_evidence_for_id(connection, command_id, _RESUME_PLAN_ERA)


def historical_domain_plan_evidence_for_id(
    connection: sqlite3.Connection,
    command_id: str,
) -> HistoricalDomainPlanEvidence | None:
    return _historical_plan_evidence_for_id(connection, command_id, _DOMAIN_PLAN_ERA)


def command_from_row(row: sqlite3.Row) -> CommandRecord:
    """Decode a command while proving every redundant durable identity."""

    raw_command_id = row["command_id"]
    command_identity = repr(raw_command_id)
    try:
        command_id = _durable_text(raw_command_id, fact="command identity")
        command_identity = repr(command_id)
        actor_id = _durable_text(
            row["actor_id"],
            fact=f"command {command_id!r} actor identity",
        )
        operation = _durable_text(
            row["operation"],
            fact=f"command {command_id!r} operation",
        )
        idempotency_key = _durable_text(
            row["idempotency_key"],
            fact=f"command {command_id!r} idempotency key",
        )
        raw_state = _durable_text(
            row["state"],
            fact=f"command {command_id!r} state",
        )
        if raw_state not in {"prepared", "committed", "rejected"}:
            raise ValueError("command state is unknown")
        state = cast(Literal["prepared", "committed", "rejected"], raw_state)
        raw_actor = parse_json_value(row["actor_json"])
        request = parse_json_value(row["request_json"])
        raw_plan = row["plan_json"]
        plan = (
            parse_json_value(raw_plan)
            if raw_plan is not None
            else None
        )
        raw_response = row["response_json"]
        response = (
            parse_json_value(raw_response)
            if raw_response is not None
            else None
        )
        raw_owner_id = row["owner_id"]
        owner_id = (
            _durable_text(
                raw_owner_id,
                fact=f"command {command_id!r} owner identity",
            )
            if raw_owner_id is not None
            else None
        )
        record = CommandRecord(
            command_id=command_id,
            actor=durable_authenticated_actor(
                raw_actor,
                fact=f"command {command_id!r} actor payload",
            ),
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=_durable_digest(
                row["request_hash"],
                fact=f"command {command_id!r} request hash",
            ),
            request=request,
            state=state,
            plan=plan,
            response=response,
            owner_id=owner_id,
            owner_epoch=_durable_sequence(
                row["owner_epoch"],
                fact=f"command {command_id!r} owner epoch",
                allow_zero=True,
                kind="owner epoch",
            ),
            lease_expires_at=(
                _durable_datetime(
                    row["lease_expires_at"],
                    fact=f"command {command_id!r} lease expiry",
                )
                if row["lease_expires_at"] is not None
                else None
            ),
            created_at=_durable_datetime(
                row["created_at"],
                fact=f"command {command_id!r} creation time",
            ),
            updated_at=_durable_datetime(
                row["updated_at"],
                fact=f"command {command_id!r} update time",
            ),
            completed_at=(
                _durable_datetime(
                    row["completed_at"],
                    fact=f"command {command_id!r} completion time",
                )
                if row["completed_at"] is not None
                else None
            ),
        )
        if record.actor.actor_id != actor_id:
            raise ValueError("command actor columns disagree")
        if record.plan is not None:
            canonical_json(record.plan)
        if record.response is not None:
            canonical_json(record.response)
        if record.state == "prepared":
            if (
                row["response_json"] is not None
                or row["completed_at"] is not None
                or record.owner_id is None
                or record.lease_expires_at is None
            ):
                raise ValueError("prepared command carries terminal lifecycle columns")
        elif (
            record.response is None
            or record.plan is None
            or record.completed_at is None
            or record.owner_id is not None
            or record.lease_expires_at is not None
        ):
            raise ValueError("terminal command contradicts its lifecycle columns")
        validate_idempotency_key(record.idempotency_key)
        if record.command_id != command_id_for(
            record.actor.actor_id,
            record.operation,
            record.idempotency_key,
        ):
            raise ValueError("command id contradicts its canonical identity")
        if record.request_hash != command_request_hash(record.request):
            raise ValueError("command request hash contradicts its decoded request")
        return record
    except (JournalDamaged, TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(
            f"command row {command_identity} is not a valid durable record"
        ) from exc
