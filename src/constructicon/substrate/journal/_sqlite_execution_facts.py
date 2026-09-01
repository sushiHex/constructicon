"""Positive seals and canonical projections for execution history facts.

Events and checkpoints are append-only evidence, not self-authenticating rows.
Their table keys and payloads are useful selectors, but only an independent
write-once seal makes valid-to-valid rewrites and complete row erasure visible.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import cast

from pydantic import ValidationError

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.control import (
    CommandRecord,
    resume_domain_plan,
    validated_resume_attempt_command,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json, parse_json_value
from constructicon.core.journal import Checkpoint, JournalEvent
from constructicon.core.run import AttemptCause
from constructicon.substrate.journal._sqlite_base import (
    _checkpoint_identity,
    _durable_digest,
    _durable_model,
    _durable_sequence,
    _durable_text,
    _event_from_row,
    _path_key,
)
from constructicon.substrate.journal._sqlite_commands import (
    command_claim_fact_hash,
    command_for_id,
    command_plan_fact_hash,
    sealed_command_from_row,
)
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    durable_fact_seal,
    require_durable_fact_seal,
    store_durable_fact_seal,
)

EVENT_FACT_FAMILY = "event"
CHECKPOINT_FACT_FAMILY = "checkpoint"
RESUME_ATTEMPT_FACT_FAMILY = "resume_attempt"


def _event_position(run_id: str, seq: int) -> dict[str, object]:
    return {"run_id": run_id, "seq": seq}


def event_fact_key(run_id: RunId | str, seq: int) -> str:
    """Return the seal key for one relational event position."""

    return canonical_json(_event_position(str(run_id), seq))


def _event_position_from_row(row: sqlite3.Row) -> tuple[str, int]:
    raw_run_id = _durable_text(row["run_id"], fact="event seal run identity")
    seq = _durable_sequence(
        row["seq"],
        fact=f"event {raw_run_id!r} seal sequence",
        kind="event sequence",
    )
    return raw_run_id, seq


def _event_selector(run_id: str, seq: int) -> str:
    return canonical_json({"event": _event_position(run_id, seq)})


def _event_fact_key_position(raw: object) -> tuple[str, int]:
    """Decode an exact event seal key for reverse-inventory checks."""

    try:
        value = parse_json_value(_durable_text(raw, fact="event fact seal key"))
        if not isinstance(value, dict) or set(value) != {"run_id", "seq"}:
            raise ValueError("event fact seal key is not one exact position")
        run_id = value["run_id"]
        seq = value["seq"]
        if type(run_id) is not str or type(seq) is not int or seq <= 0:
            raise ValueError("event fact seal key has invalid scalar types")
        if canonical_json(value) != event_fact_key(run_id, seq):
            raise ValueError("event fact seal key is not canonical")
        return run_id, seq
    except JournalDamaged:
        raise
    except (TypeError, ValueError) as exc:
        raise JournalDamaged("event fact seal has an invalid position key") from exc


def event_fact_hash(row: sqlite3.Row) -> Digest:
    """Hash every exact immutable scalar in one event row."""

    run_id, seq = _event_position_from_row(row)
    identity = f"event {run_id!r}/{seq}"
    return durable_fact_hash(
        EVENT_FACT_FAMILY,
        {
            "run_id": run_id,
            "seq": seq,
            "kind": _durable_text(row["kind"], fact=f"{identity} kind"),
            "path_json": (
                _durable_text(row["path_json"], fact=f"{identity} path bytes")
                if row["path_json"] is not None
                else None
            ),
            "payload": (
                _durable_text(row["payload"], fact=f"{identity} payload bytes")
                if row["payload"] is not None
                else None
            ),
            "created_at": _durable_text(
                row["created_at"],
                fact=f"{identity} creation-time bytes",
            ),
        },
    )


def seal_event(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Write or reconcile one event's independent positive seal."""

    event = _event_from_row(row)
    run_id, seq = _event_position_from_row(row)
    if event.run_id != RunId(run_id) or event.seq != seq:
        raise JournalDamaged(f"event {run_id!r}/{seq} contradicts its row position")
    store_durable_fact_seal(
        connection,
        family=EVENT_FACT_FAMILY,
        fact_key=event_fact_key(run_id, seq),
        selector=_event_selector(run_id, seq),
        fact_hash=event_fact_hash(row),
    )


def stored_event_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> JournalEvent:
    """Project one event beside its exact seal and attempt relationship."""

    event = _stored_event_from_row_without_relationship(connection, row)
    attempt = _validated_resume_attempt(connection, row, event=event)
    _require_resume_attempt_relationship(connection, event, attempt)
    return event


def _stored_event_from_row_without_relationship(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> JournalEvent:
    """Project the base event while its co-transactional relation is pending."""

    event = _event_from_row(row)
    run_id, seq = _event_position_from_row(row)
    if event.run_id != RunId(run_id) or event.seq != seq:
        raise JournalDamaged(f"event {run_id!r}/{seq} contradicts its row position")
    require_durable_fact_seal(
        connection,
        family=EVENT_FACT_FAMILY,
        fact_key=event_fact_key(run_id, seq),
        selector=_event_selector(run_id, seq),
        fact_hash=event_fact_hash(row),
    )
    return event


def _resume_attempt_baseline_hash(
    connection: sqlite3.Connection,
    *,
    run_id: RunId,
    event_seq: int,
) -> tuple[Digest, str | None]:
    if event_seq == 1:
        return (
            durable_fact_hash(
                "resume_attempt_baseline",
                {
                    "run_id": str(run_id),
                    "event_seq": 0,
                    "before_first_event": True,
                },
            ),
            None,
        )
    row = connection.execute(
        "SELECT * FROM events WHERE run_id = ? AND seq = ?",
        (str(run_id), event_seq - 1),
    ).fetchone()
    if row is None:
        raise JournalDamaged(
            f"resume attempt {run_id!r}/{event_seq} lost its exact baseline event"
        )
    event = _stored_event_from_row_without_relationship(connection, row)
    return event_fact_hash(row), event.kind


@dataclass(frozen=True)
class _ValidatedResumeAttempt:
    command_id: str
    selector: str
    fact_hash: Digest


def _validated_resume_attempt(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    event: JournalEvent,
) -> _ValidatedResumeAttempt | None:
    """Build the sole immutable projection of one optional resume relation."""

    try:
        cause = AttemptCause.from_payload(event.payload)
    except ValueError as exc:
        raise JournalDamaged(
            f"attempt event {event.run_id!r}/{event.seq} has contradictory cause facts"
        ) from exc
    if cause is None or cause.kind != "resume_command":
        return None
    command_id = cause.id
    command_row = connection.execute(
        "SELECT * FROM commands WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    if command_row is None:
        command_for_id(connection, command_id)
        raise JournalDamaged(
            f"attempt event {event.run_id!r}/{event.seq} names no retained resume command"
        )
    command = sealed_command_from_row(connection, command_row)
    if command.command_id != command_id or command_row["plan_json"] is None:
        raise JournalDamaged(f"resume command {command_id!r} lost its exact plan")
    baseline_hash, baseline_kind = _resume_attempt_baseline_hash(
        connection,
        run_id=event.run_id,
        event_seq=event.seq,
    )
    validated_resume_attempt_command(
        command,
        run_id=event.run_id,
        event_seq=event.seq,
        event_kind=event.kind,
        baseline_event_kind=baseline_kind,
    )
    return _ValidatedResumeAttempt(
        command_id=command_id,
        selector=event_fact_key(event.run_id, event.seq),
        fact_hash=durable_fact_hash(
            RESUME_ATTEMPT_FACT_FAMILY,
            {
                "command_id": command_id,
                "run_id": str(event.run_id),
                "event_seq": event.seq,
                "command_claim_hash": str(command_claim_fact_hash(command_row)),
                "command_plan_hash": str(command_plan_fact_hash(command_row)),
                "baseline_event_hash": str(baseline_hash),
                "event_hash": str(event_fact_hash(row)),
            },
        ),
    )


def _require_resume_attempt_relationship(
    connection: sqlite3.Connection,
    event: JournalEvent,
    attempt: _ValidatedResumeAttempt | None,
) -> None:
    """Require both halves of one optional event-to-command relationship."""

    if attempt is None:
        seal = durable_fact_seal(
            connection,
            family=RESUME_ATTEMPT_FACT_FAMILY,
            selector=event_fact_key(event.run_id, event.seq),
        )
        if seal is not None:
            raise JournalDamaged(
                f"event {event.run_id!r}/{event.seq} lost its resume-attempt claim"
            )
        return
    require_durable_fact_seal(
        connection,
        family=RESUME_ATTEMPT_FACT_FAMILY,
        fact_key=attempt.command_id,
        selector=attempt.selector,
        fact_hash=attempt.fact_hash,
    )


def seal_resume_attempt_relationship(
    connection: sqlite3.Connection,
    event_row: sqlite3.Row,
) -> None:
    """Seal one exact command-attributed event in the event's transaction."""

    event = _stored_event_from_row_without_relationship(connection, event_row)
    attempt = _validated_resume_attempt(connection, event_row, event=event)
    if attempt is None:
        return
    store_durable_fact_seal(
        connection,
        family=RESUME_ATTEMPT_FACT_FAMILY,
        fact_key=attempt.command_id,
        selector=attempt.selector,
        fact_hash=attempt.fact_hash,
    )


def seal_migrated_resume_attempts(connection: sqlite3.Connection) -> None:
    """Seal every lawful attempt relationship retained by schema 6."""

    for row in connection.execute("SELECT * FROM events ORDER BY run_id, seq"):
        seal_resume_attempt_relationship(connection, row)


def validate_resume_attempt_provenance(
    connection: sqlite3.Connection,
    *,
    run_id: RunId | None = None,
) -> int:
    """Require a bijection between command-attributed events and their seals."""

    where = "" if run_id is None else " WHERE run_id = ?"
    parameters: tuple[object, ...] = () if run_id is None else (str(run_id),)
    observed: set[str] = set()
    for row in connection.execute(
        "SELECT * FROM events" + where + " ORDER BY run_id, seq",
        parameters,
    ):
        event = _stored_event_from_row_without_relationship(connection, row)
        attempt = _validated_resume_attempt(connection, row, event=event)
        _require_resume_attempt_relationship(connection, event, attempt)
        if attempt is None:
            continue
        if attempt.command_id in observed:
            raise JournalDamaged(
                f"resume command {attempt.command_id!r} has more than one attempt receipt"
            )
        observed.add(attempt.command_id)
    if run_id is not None:
        return len(observed)
    sealed: set[str] = set()
    seal_count = 0
    for row in connection.execute(
        "SELECT fact_key FROM durable_fact_seals WHERE family = ?",
        (RESUME_ATTEMPT_FACT_FAMILY,),
    ):
        seal_count += 1
        sealed.add(_durable_text(row["fact_key"], fact="resume-attempt seal identity"))
    if sealed != observed or len(sealed) != seal_count:
        raise JournalDamaged("resume-attempt seal inventory has an orphan or missing fact")
    return len(observed)


def resume_attempt_owned_by(
    connection: sqlite3.Connection,
    command: CommandRecord,
) -> bool:
    """Project any attempt fact before permitting its command to reject."""

    plan = resume_domain_plan(command)

    def has_owned_seal() -> bool:
        return (
            durable_fact_seal(
                connection,
                family=RESUME_ATTEMPT_FACT_FAMILY,
                fact_key=command.command_id,
            )
            is not None
        )

    if plan is None:
        if has_owned_seal():
            raise JournalDamaged(
                f"non-resume command {command.command_id!r} owns a resume attempt"
            )
        return False
    if plan.baseline_event_seq is None:
        if has_owned_seal():
            raise JournalDamaged(
                f"unfenced resume command {command.command_id!r} owns an attempt"
            )
        return False
    row = connection.execute(
        "SELECT * FROM events WHERE run_id = ? AND seq = ?",
        (str(plan.run_id), plan.baseline_event_seq + 1),
    ).fetchone()
    if row is None:
        if has_owned_seal():
            raise JournalDamaged(
                f"resume command {command.command_id!r} lost its fenced attempt event"
            )
        return False
    event = _stored_event_from_row_without_relationship(connection, row)
    attempt = _validated_resume_attempt(connection, row, event=event)
    _require_resume_attempt_relationship(connection, event, attempt)
    if attempt is not None and attempt.command_id == command.command_id:
        return True
    if has_owned_seal():
        raise JournalDamaged(
            f"resume command {command.command_id!r} owns a fact outside its fence"
        )
    return False


def validate_event_seal_inventory(connection: sqlite3.Connection) -> None:
    """Require a bijection between every retained event row and its seal.

    One pass over the whole store, at the one moment that pass is affordable.
    It deliberately takes no run scope: a per-run variant existed, read every
    event seal in the database to answer about one run, and was called once per
    run — so opening a store proved every seal once globally and then again N
    times over. Inventory is a whole-store act or it is not inventory.
    """

    row_keys: set[str] = set()
    row_count = 0
    for row in connection.execute("SELECT * FROM events"):
        row_count += 1
        event = _stored_event_from_row_without_relationship(connection, row)
        row_keys.add(event_fact_key(event.run_id, event.seq))
    seal_count = 0
    seal_keys: set[str] = set()
    for seal_row in connection.execute(
        "SELECT fact_key FROM durable_fact_seals WHERE family = ?",
        (EVENT_FACT_FAMILY,),
    ):
        seal_count += 1
        seal_keys.add(_durable_text(seal_row["fact_key"], fact="event fact seal key"))
    if (
        row_keys != seal_keys
        or len(row_keys) != row_count
        or len(seal_keys) != seal_count
    ):
        raise JournalDamaged("durable event seal inventory has an orphan or missing fact")


def _checkpoint_position(run_id: str, path_key: str) -> dict[str, str]:
    return {"run_id": run_id, "path_key": path_key}


def checkpoint_fact_key(run_id: RunId | str, path: ExecutionPath) -> str:
    """Return the relational seal key for one checkpoint invocation."""

    return canonical_json({"checkpoint_row": _checkpoint_position(str(run_id), _path_key(path))})


def _checkpoint_payload_selector(run_id: RunId | str, path: ExecutionPath) -> str:
    return canonical_json(
        {"checkpoint_payload": _checkpoint_position(str(run_id), _path_key(path))}
    )


def checkpoint_fact_hash(row: sqlite3.Row) -> Digest:
    """Hash every exact immutable scalar in one checkpoint row."""

    run_id = _durable_text(row["run_id"], fact="checkpoint seal run identity")
    path_key = _durable_text(
        row["path_key"],
        fact=f"checkpoint {run_id!r} seal path identity",
    )
    identity = f"checkpoint {run_id!r}/{path_key!r}"
    return durable_fact_hash(
        CHECKPOINT_FACT_FAMILY,
        {
            "run_id": run_id,
            "path_key": path_key,
            "identity": _durable_text(
                row["identity"],
                fact=f"{identity} content-identity bytes",
            ),
            "checkpoint_json": _durable_text(
                row["checkpoint_json"],
                fact=f"{identity} payload bytes",
            ),
        },
    )


def _checkpoint_from_row_unsealed(
    row: sqlite3.Row,
    *,
    expected_run_id: RunId | None = None,
    expected_path: ExecutionPath | None = None,
) -> Checkpoint:
    """Decode one row while proving its redundant identities losslessly."""

    identity = f"checkpoint {row['run_id']!r}/{row['path_key']!r}"
    try:
        row_run_id = RunId(_durable_text(row["run_id"], fact=f"{identity} run identity"))
        row_path_key = _durable_text(
            row["path_key"],
            fact=f"{identity} path identity",
        )
        row_identity = _durable_digest(
            row["identity"],
            fact=f"{identity} content identity",
        )
        checkpoint = _durable_model(
            Checkpoint,
            row["checkpoint_json"],
            fact=identity,
        )
        if (
            checkpoint.run_id != row_run_id
            or _path_key(checkpoint.path) != row_path_key
            or _checkpoint_identity(checkpoint) != str(row_identity)
            or (expected_run_id is not None and checkpoint.run_id != expected_run_id)
            or (expected_path is not None and checkpoint.path != expected_path)
        ):
            raise ValueError("checkpoint relational and payload identities disagree")
        return checkpoint
    except JournalDamaged:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(f"{identity} is not a valid durable record") from exc


def seal_checkpoint(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Write or reconcile one checkpoint's independent positive seal."""

    checkpoint = _checkpoint_from_row_unsealed(row)
    store_durable_fact_seal(
        connection,
        family=CHECKPOINT_FACT_FAMILY,
        fact_key=checkpoint_fact_key(
            _durable_text(row["run_id"], fact="checkpoint seal run identity"),
            checkpoint.path,
        ),
        selector=_checkpoint_payload_selector(checkpoint.run_id, checkpoint.path),
        fact_hash=checkpoint_fact_hash(row),
    )


def stored_checkpoint_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    expected_run_id: RunId,
    expected_path: ExecutionPath,
) -> Checkpoint:
    """Project one checkpoint only beside its exact positive seal."""

    checkpoint = _checkpoint_from_row_unsealed(
        row,
        expected_run_id=expected_run_id,
        expected_path=expected_path,
    )
    require_durable_fact_seal(
        connection,
        family=CHECKPOINT_FACT_FAMILY,
        fact_key=checkpoint_fact_key(
            _durable_text(row["run_id"], fact="checkpoint seal run identity"),
            expected_path,
        ),
        selector=_checkpoint_payload_selector(checkpoint.run_id, checkpoint.path),
        fact_hash=checkpoint_fact_hash(row),
    )
    return checkpoint


def _checkpoint_selector(run_id: RunId, path: ExecutionPath) -> str:
    return canonical_json(_checkpoint_position(str(run_id), _path_key(path)))


def _checkpoint_selector_from_json(raw: object) -> str | None:
    try:
        checkpoint = _durable_model(
            Checkpoint,
            _durable_text(raw, fact="checkpoint selector payload"),
            fact="checkpoint selector payload",
        )
        return _checkpoint_selector(checkpoint.run_id, checkpoint.path)
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return None


def _checkpoint_event_selector(run_id: object, raw_path: object) -> str | None:
    try:
        durable_run_id = RunId(_durable_text(run_id, fact="checkpoint event run identity"))
        path = _durable_model(
            ExecutionPath,
            _durable_text(raw_path, fact="checkpoint event path"),
            fact="checkpoint event path",
        )
        return _checkpoint_selector(durable_run_id, path)
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return None


def stored_checkpoint_for(
    connection: sqlite3.Connection,
    *,
    run_id: RunId,
    path: ExecutionPath,
) -> Checkpoint | None:
    """Select one checkpoint by every identity before deciding absence."""

    selector = _checkpoint_selector(run_id, path)
    fact_key = checkpoint_fact_key(run_id, path)
    fact_selector = _checkpoint_payload_selector(run_id, path)
    seal = durable_fact_seal(
        connection,
        family=CHECKPOINT_FACT_FAMILY,
        fact_key=fact_key,
        selector=fact_selector,
    )
    connection.create_function(
        "constructicon_checkpoint_selector",
        1,
        _checkpoint_selector_from_json,
        deterministic=True,
    )
    connection.create_function(
        "constructicon_checkpoint_event_selector",
        2,
        _checkpoint_event_selector,
        deterministic=True,
    )
    rows = connection.execute(
        "SELECT * FROM checkpoints"
        " WHERE (run_id = ? AND path_key = ?)"
        " OR constructicon_checkpoint_selector(checkpoint_json) = ?"
        " OR constructicon_checkpoint_selector(checkpoint_json) IS NULL"
        " LIMIT 2",
        (run_id, _path_key(path), selector),
    ).fetchall()
    if len(rows) > 1:
        raise JournalDamaged(
            f"checkpoint {run_id!r}/{path.render()} has contradictory durable selectors"
        )
    completion_rows = connection.execute(
        "SELECT * FROM events WHERE kind = 'NodeCompleted' AND ("
        " constructicon_checkpoint_event_selector(run_id, path_json) = ?"
        " OR (run_id = ? AND"
        " constructicon_checkpoint_event_selector(run_id, path_json) IS NULL))"
        " LIMIT 2",
        (selector, run_id),
    ).fetchall()
    if len(completion_rows) > 1:
        raise JournalDamaged(
            f"checkpoint {run_id!r}/{path.render()} has duplicate completion events"
        )
    if bool(rows) != bool(completion_rows):
        raise JournalDamaged(
            f"checkpoint {run_id!r}/{path.render()} row and completion event disagree"
        )
    if not rows:
        if seal is not None:
            raise JournalDamaged(
                f"checkpoint {run_id!r}/{path.render()} is missing behind its positive seal"
            )
        return None
    checkpoint = stored_checkpoint_from_row(
        connection,
        cast(sqlite3.Row, rows[0]),
        expected_run_id=run_id,
        expected_path=path,
    )
    event = stored_event_from_row(connection, cast(sqlite3.Row, completion_rows[0]))
    if event.kind != "NodeCompleted" or event.run_id != run_id or event.path != path:
        raise JournalDamaged(
            f"checkpoint {run_id!r}/{path.render()} has a contradictory completion event"
        )
    return checkpoint


def validate_checkpoint_seal_inventory(connection: sqlite3.Connection) -> None:
    """Require a sealed one-to-one checkpoint/completion-event inventory."""

    checkpoint_positions: list[str] = []
    for row in connection.execute("SELECT * FROM checkpoints").fetchall():
        checkpoint = _checkpoint_from_row_unsealed(row)
        checkpoint_positions.append(checkpoint_fact_key(checkpoint.run_id, checkpoint.path))
        stored_checkpoint_for(
            connection,
            run_id=checkpoint.run_id,
            path=checkpoint.path,
        )
    completion_positions: list[str] = []
    for row in connection.execute("SELECT * FROM events WHERE kind = 'NodeCompleted'").fetchall():
        event = stored_event_from_row(connection, row)
        if event.path is None:
            raise JournalDamaged(
                f"completion event {event.run_id!r}/{event.seq} has no invocation path"
            )
        completion_positions.append(checkpoint_fact_key(event.run_id, event.path))
    if (
        len(checkpoint_positions) != len(set(checkpoint_positions))
        or len(completion_positions) != len(set(completion_positions))
        or set(checkpoint_positions) != set(completion_positions)
    ):
        raise JournalDamaged("checkpoint rows and completion events are not a one-to-one inventory")
