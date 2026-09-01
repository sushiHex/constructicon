# mypy: disable-error-code="attr-defined"
"""SQLite connection ownership, transaction boundaries, and shared identities."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.control import command_id_for
from constructicon.core.envelope import utc_now
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import (
    Digest,
    JsonValue,
    actor_id_is_canonical,
    canonical_json,
    digest,
    parse_json_value,
)
from constructicon.core.journal import Checkpoint, JournalEvent
from constructicon.core.manifest import parse_manifest_json
from constructicon.core.run import Liveness, RunStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    manifest_hash    TEXT NOT NULL,
    input_hash       TEXT NOT NULL,
    inputs_json      TEXT NOT NULL,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    owner_id         TEXT,
    owner_epoch      INTEGER NOT NULL DEFAULT 0,
    owner_pid        INTEGER,
    heartbeat_at     TEXT,
    lease_expires_at TEXT,
    next_event_seq   INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    creation_command_id TEXT
);
CREATE TABLE IF NOT EXISTS events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    path_json  TEXT,
    payload    TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id          TEXT NOT NULL,
    path_key        TEXT NOT NULL,
    identity        TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    PRIMARY KEY (run_id, path_key)
);
CREATE TABLE IF NOT EXISTS manifests (
    manifest_hash TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attestations (
    attestation_id   TEXT PRIMARY KEY,
    attestation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS effects (
    idempotency_key TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    request_json    TEXT NOT NULL,
    receipt_json    TEXT,
    prepared_at     TEXT NOT NULL,
    receipted_at    TEXT,
    outcome_run_id  TEXT,
    outcome_event_seq INTEGER
);
CREATE TABLE IF NOT EXISTS components (
    registration_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    definition_json  TEXT NOT NULL,
    registered_at    TEXT NOT NULL,
    UNIQUE (name, content_hash)
);
CREATE TABLE IF NOT EXISTS promotions (
    promotion_seq  INTEGER PRIMARY KEY AUTOINCREMENT,
    component      TEXT NOT NULL,
    channel        TEXT NOT NULL,
    from_version   TEXT,
    to_version     TEXT NOT NULL,
    attestation_id TEXT NOT NULL UNIQUE,
    actor          TEXT NOT NULL,
    source_run     TEXT,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capability_leases (
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
);
"""

_ModelT = TypeVar("_ModelT", bound=BaseModel)
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class _DurableRunFields:
    run_id: RunId
    status: RunStatus
    created_at: datetime
    owner_id: str | None
    lease_expires_at: datetime | None
    cancel_requested: bool


@dataclass(frozen=True)
class _RunStateFields(_DurableRunFields):
    liveness: Liveness


def _durable_datetime(raw: object, *, fact: str) -> datetime:
    """Decode one stored aware timestamp without accepting scalar coercion."""

    try:
        if type(raw) is not str:
            raise ValueError("timestamp is not text")
        value = datetime.fromisoformat(raw)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp has no UTC offset")
        if raw != value.isoformat():
            raise ValueError("timestamp is not in the canonical writer format")
        return value
    except (TypeError, ValueError) as exc:
        raise JournalDamaged(f"{fact} is not a valid durable timestamp") from exc


def _durable_text(raw: object, *, fact: str) -> str:
    """Decode one SQLite text value without Python scalar coercion."""

    if type(raw) is not str:
        raise JournalDamaged(f"{fact} is not valid durable text")
    return raw


def _utc_microseconds(value: datetime) -> int:
    normalized = value.astimezone(UTC) - _UNIX_EPOCH
    return (
        normalized.days * 86_400_000_000
        + normalized.seconds * 1_000_000
        + normalized.microseconds
    )


def _sqlite_utc_microseconds(raw: object) -> int | None:
    """SQLite UDF: exact typed timestamp ordering, NULL for invalid bytes."""

    try:
        return _utc_microseconds(_durable_datetime(raw, fact="SQLite timestamp"))
    except JournalDamaged:
        return None


def _sqlite_command_id(
    actor_id: object,
    operation: object,
    idempotency_key: object,
) -> str | None:
    """SQLite UDF: derive a command identity only from exact text scalars."""

    if any(type(value) is not str for value in (actor_id, operation, idempotency_key)):
        return None
    try:
        return command_id_for(
            cast(str, actor_id),
            cast(str, operation),
            cast(str, idempotency_key),
        )
    except (TypeError, ValueError):
        return None


def _durable_json(raw: str, *, fact: str) -> JsonValue:
    """Decode stored JSON and translate every byte-law failure into damage."""

    try:
        return parse_json_value(raw)
    except (TypeError, ValueError) as exc:
        raise JournalDamaged(f"{fact} is not valid durable JSON") from exc


def _durable_model(model: type[_ModelT], raw: str, *, fact: str) -> _ModelT:
    """Decode one stored model without accepting typed normalization."""

    try:
        return _lossless_model(model, _durable_json(raw, fact=fact))
    except JournalDamaged:
        raise
    except (TypeError, ValueError) as exc:
        raise JournalDamaged(f"{fact} is not a valid durable record") from exc


def _lossless_model(model: type[_ModelT], raw: JsonValue) -> _ModelT:
    """Type a JSON value only when its canonical wire fact is unchanged.

    The raw canonical form is captured before validation because compatibility
    validators may update their input mapping in-place.  This is the shared
    law for both standalone JSON models and models nested inside larger rows.
    """

    stored_canonical = canonical_json(raw)
    value = model.model_validate(raw)
    if stored_canonical != canonical_json(value.model_dump(mode="json")):
        raise ValueError(f"{model.__name__} parsing is not lossless")
    return value


def _durable_digest(raw: object, *, fact: str) -> Digest:
    """Decode one stored digest without leaking Pydantic validation errors."""

    try:
        return Digest(_durable_text(raw, fact=fact))
    except (JournalDamaged, TypeError, ValueError) as exc:
        raise JournalDamaged(f"{fact} is not a valid durable digest") from exc


def _durable_sequence(
    raw: object,
    *,
    fact: str,
    allow_zero: bool = False,
    kind: str = "sequence",
) -> int:
    """Decode one SQLite sequence without Python scalar coercion."""

    minimum = 0 if allow_zero else 1
    if type(raw) is not int or raw < minimum:
        raise JournalDamaged(f"{fact} is not a valid durable {kind}")
    return raw


def _durable_event_seq(
    raw: object,
    *,
    fact: str,
    allow_zero: bool = False,
) -> int:
    """Backward-compatible name for the shared durable-sequence law."""

    return _durable_sequence(
        raw,
        fact=fact,
        allow_zero=allow_zero,
        kind="event sequence",
    )


def _durable_sqlite_boolean(raw: object, *, fact: str) -> bool:
    """Decode one SQLite 0/1 flag without Python truthiness coercion."""

    try:
        if type(raw) is not int or raw not in (0, 1):
            raise ValueError("SQLite boolean is not the integer 0 or 1")
        return raw == 1
    except ValueError as exc:
        raise JournalDamaged(f"{fact} is not a valid durable SQLite boolean") from exc


def _event_from_row(row: sqlite3.Row) -> JournalEvent:
    """Project one durable event through a single typed, lossless boundary."""

    identity = f"{row['run_id']!r}/{row['seq']!r}"
    try:
        raw_run_id = row["run_id"]
        if type(raw_run_id) is not str:
            raise ValueError("event run identity is not text")
        raw_seq = _durable_event_seq(
            row["seq"],
            fact=f"event {identity}",
        )
        raw_path = (
            _durable_json(row["path_json"], fact=f"event {identity} path")
            if row["path_json"] is not None
            else None
        )
        path = ExecutionPath.model_validate(raw_path) if raw_path is not None else None
        if raw_path is not None and canonical_json(raw_path) != canonical_json(path):
            raise ValueError("event path parsing is not lossless")
        payload = (
            _durable_json(row["payload"], fact=f"event {identity} payload")
            if row["payload"] is not None
            else None
        )
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("event payload is not an object")
        return JournalEvent(
            run_id=RunId(raw_run_id),
            seq=raw_seq,
            kind=_durable_text(row["kind"], fact=f"event {identity} kind"),
            path=path,
            created_at=_durable_datetime(
                row["created_at"],
                fact=f"event {identity} creation time",
            ),
            payload=payload,
        )
    except JournalDamaged:
        raise
    except (TypeError, ValueError) as exc:
        raise JournalDamaged(f"event {identity} is not a valid durable record") from exc


def _durable_run_fields(row: sqlite3.Row) -> _DurableRunFields:
    """Decode one run row's stored lifecycle scalars without observing time."""

    raw_run_id = row["run_id"]
    try:
        if type(raw_run_id) is not str:
            raise ValueError("run identity is not text")
        run_id = RunId(raw_run_id)
        status = RunStatus(row["status"])
        created_at = _durable_datetime(
            row["created_at"],
            fact=f"run {run_id!r} creation time",
        )
        owner_id = row["owner_id"]
        if owner_id is not None and not isinstance(owner_id, str):
            raise ValueError("run owner is not text")
        raw_lease_expires_at = row["lease_expires_at"]
        lease_expires_at = (
            _durable_datetime(
                raw_lease_expires_at,
                fact=f"run {run_id!r} lease expiry",
            )
            if raw_lease_expires_at is not None
            else None
        )
        cancel_requested = _durable_sqlite_boolean(
            row["cancel_requested"],
            fact=f"run {run_id!r} cancellation flag",
        )
        return _DurableRunFields(
            run_id=run_id,
            status=status,
            created_at=created_at,
            owner_id=owner_id,
            lease_expires_at=lease_expires_at,
            cancel_requested=cancel_requested,
        )
    except (TypeError, ValueError) as exc:
        raise JournalDamaged(
            f"run state for {raw_run_id!r} is not a valid durable record"
        ) from exc


def _run_state_fields(
    row: sqlite3.Row,
    *,
    observe: Callable[[], datetime],
) -> _RunStateFields:
    """Decode durable run lifecycle scalars, then apply read-time liveness."""

    fields = _durable_run_fields(row)
    if fields.status is not RunStatus.RUNNING:
        liveness: Liveness = "not_applicable"
    elif fields.owner_id is not None and fields.lease_expires_at is not None:
        liveness = "live" if fields.lease_expires_at > observe() else "lost"
    else:
        liveness = "lost"
    return _RunStateFields(
        run_id=fields.run_id,
        status=fields.status,
        liveness=liveness,
        created_at=fields.created_at,
        owner_id=fields.owner_id,
        lease_expires_at=fields.lease_expires_at,
        cancel_requested=fields.cancel_requested,
    )


def _path_key(path: ExecutionPath) -> str:
    return canonical_json(path.model_dump(mode="json"))


def _checkpoint_identity(checkpoint: Checkpoint) -> str:
    """Semantic identity of a completion — envelope timestamps excluded, so a
    legitimately identical re-record is idempotent while a different result at
    the same (run, path) is damage."""
    return str(
        digest(
            "checkpoint-identity",
            1,
            {
                "input_hash": str(checkpoint.input_hash),
                "resolved_version": (
                    str(checkpoint.resolved_version) if checkpoint.resolved_version else None
                ),
                "outputs": {port: env.payload for port, env in sorted(checkpoint.outputs.items())},
            },
        )
    )


def _manifest_semantically_equal(left_json: str, right_json: str) -> bool:
    """Compare historical manifests by declared-schema semantics, never bytes."""

    try:
        left = parse_manifest_json(left_json)
        right = parse_manifest_json(right_json)
    except (ValueError, TypeError):
        return False
    return left == right


class _SqliteBase:
    def __init__(
        self,
        db_path: Path | str,
        *,
        now_fn: Callable[[], datetime] = utc_now,
    ) -> None:
        self._db_path = str(db_path)
        self._now = now_fn
        # No-op hook tests arm to simulate death at named points.
        self.fault_probe: Callable[[str], None] = lambda name: None
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.create_function(
            "constructicon_utc_microseconds",
            1,
            _sqlite_utc_microseconds,
            deterministic=True,
        )
        conn.create_function(
            "constructicon_actor_id_is_canonical",
            1,
            actor_id_is_canonical,
            deterministic=True,
        )
        conn.create_function(
            "constructicon_command_id",
            3,
            _sqlite_command_id,
            deterministic=True,
        )
        return conn

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _now_iso(self) -> str:
        return self._now().isoformat()
