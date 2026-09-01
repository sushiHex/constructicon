"""The one projection from a durable approval row to its L0 fact."""

from __future__ import annotations

import sqlite3

from pydantic import TypeAdapter, ValidationError

from constructicon.core.address import RunId
from constructicon.core.control import CommandRecord
from constructicon.core.effect import ApprovalRecord, ProofSubject
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import validated_command_approval
from constructicon.core.identity import Digest, canonical_json, json_value, parse_json_value
from constructicon.substrate.journal._sqlite_actors import durable_authenticated_actor
from constructicon.substrate.journal._sqlite_base import (
    _durable_datetime,
    _durable_text,
)
from constructicon.substrate.journal._sqlite_commands import command_for_id
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    durable_fact_seal,
    require_durable_fact_seal,
    store_durable_fact_seal,
)

_SUBJECT_ADAPTER: TypeAdapter[ProofSubject] = TypeAdapter(ProofSubject)
_APPROVAL_FACT_FAMILY = "approval"


def approval_fact_hash(row: sqlite3.Row) -> Digest:
    """Hash every exact scalar in one immutable approval receipt."""

    approval_id = _durable_text(row["approval_id"], fact="approval identity")
    identity = f"approval {approval_id!r}"
    raw_reason = row["reason"]
    return durable_fact_hash(
        _APPROVAL_FACT_FAMILY,
        {
            "approval_id": approval_id,
            "run_id": _durable_text(row["run_id"], fact=f"{identity} run identity"),
            "subject_json": _durable_text(
                row["subject_json"],
                fact=f"{identity} subject payload",
            ),
            "decision": _durable_text(row["decision"], fact=f"{identity} decision"),
            "reason": (
                _durable_text(raw_reason, fact=f"{identity} reason")
                if raw_reason is not None
                else None
            ),
            "actor_json": _durable_text(
                row["actor_json"],
                fact=f"{identity} actor payload",
            ),
            "command_id": _durable_text(
                row["command_id"],
                fact=f"{identity} command identity",
            ),
            "created_at": _durable_text(
                row["created_at"],
                fact=f"{identity} creation time",
            ),
        },
    )


def approval_from_row(
    row: sqlite3.Row,
    *,
    command: CommandRecord,
) -> ApprovalRecord:
    """Decode an approval only beside the command that authored it."""

    try:
        raw_approval_id = row["approval_id"]
        approval_id = _durable_text(raw_approval_id, fact="approval identity")
        command_id = _durable_text(
            row["command_id"],
            fact=f"approval {approval_id!r} command identity",
        )
        if command_id != command.command_id:
            raise ValueError("approval row and command projection disagree")
        raw_subject = parse_json_value(row["subject_json"])
        stored_subject = canonical_json(raw_subject)
        subject = _SUBJECT_ADAPTER.validate_python(raw_subject)
        if stored_subject != canonical_json(
            json_value(subject.model_dump(mode="json"))
        ):
            raise ValueError("approval subject parsing is not lossless")
        raw_actor = parse_json_value(row["actor_json"])
        actor = durable_authenticated_actor(
            raw_actor,
            fact=f"approval {approval_id!r} actor payload",
        )
        raw_reason = row["reason"]
        reason = (
            _durable_text(raw_reason, fact=f"approval {approval_id!r} reason")
            if raw_reason is not None
            else None
        )
        approval = ApprovalRecord(
            approval_id=approval_id,
            subject=subject,
            decision=_durable_text(
                row["decision"],
                fact=f"approval {approval_id!r} decision",
            ),
            reason=reason,
            actor=actor,
            run_id=RunId(
                _durable_text(
                    row["run_id"],
                    fact=f"approval {approval_id!r} run identity",
                )
            ),
            created_at=_durable_datetime(
                row["created_at"],
                fact=f"approval {row['approval_id']!r} creation time",
            ),
        )
        return validated_command_approval(command, approval)
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(
            f"approval row {row['approval_id']!r} is not a valid durable record"
        ) from exc


def seal_approval(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Write or reconcile one approval's positive presence/content seal."""

    command_id = _durable_text(
        row["command_id"],
        fact=f"approval {row['approval_id']!r} command identity",
    )
    command = command_for_id(connection, command_id)
    if command is None:
        raise JournalDamaged(
            f"approval {row['approval_id']!r} names missing command {command_id!r}"
        )
    approval = approval_from_row(row, command=command)
    store_durable_fact_seal(
        connection,
        family=_APPROVAL_FACT_FAMILY,
        fact_key=approval.approval_id,
        selector=command.command_id,
        fact_hash=approval_fact_hash(row),
    )


def _sealed_approval_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[CommandRecord, ApprovalRecord]:
    command_id = _durable_text(
        row["command_id"],
        fact=f"approval {row['approval_id']!r} command identity",
    )
    command = command_for_id(connection, command_id)
    if command is None:
        raise JournalDamaged(
            f"approval {row['approval_id']!r} names missing command {command_id!r}"
        )
    approval = approval_from_row(row, command=command)
    require_durable_fact_seal(
        connection,
        family=_APPROVAL_FACT_FAMILY,
        fact_key=approval.approval_id,
        selector=command.command_id,
        fact_hash=approval_fact_hash(row),
    )
    return command, approval


def approval_fact(
    connection: sqlite3.Connection,
    *,
    approval_id: str | None = None,
    command_id: str | None = None,
) -> tuple[CommandRecord, ApprovalRecord] | None:
    """Select by either redundant identity before deciding fact absence."""

    if approval_id is None and command_id is None:
        raise ValueError("an approval lookup needs an approval or command identity")
    seal = durable_fact_seal(
        connection,
        family=_APPROVAL_FACT_FAMILY,
        fact_key=approval_id,
        selector=command_id,
    )
    clauses: list[str] = []
    parameters: list[str] = []
    if approval_id is not None:
        clauses.append("approval_id = ?")
        parameters.append(approval_id)
    if command_id is not None:
        clauses.append("command_id = ?")
        parameters.append(command_id)
    if seal is not None:
        clauses.extend(("approval_id = ?", "command_id = ?"))
        parameters.extend((seal.fact_key, seal.selector))
    rows = connection.execute(
        "SELECT * FROM approvals WHERE "
        + " OR ".join(clauses)
        + " LIMIT 2",
        tuple(parameters),
    ).fetchall()
    if len(rows) > 1:
        raise JournalDamaged("approval identities select contradictory durable facts")
    if not rows:
        if seal is not None:
            raise JournalDamaged(
                f"approval {seal.fact_key!r} is missing behind its positive seal"
            )
        return None
    command, approval = _sealed_approval_from_row(connection, rows[0])
    if approval_id is not None and approval.approval_id != approval_id:
        raise JournalDamaged(
            f"approval selector {approval_id!r} contradicts its sealed fact"
        )
    if command_id is not None and command.command_id != command_id:
        raise JournalDamaged(
            f"approval command selector {command_id!r} contradicts its sealed fact"
        )
    return command, approval


def stored_approval_fact_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[CommandRecord, ApprovalRecord]:
    """Project one approval while retaining the command that proves it."""

    return _sealed_approval_from_row(connection, row)
