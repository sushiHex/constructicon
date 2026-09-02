"""Exact effect facts and the three historical request-wire eras."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.effect import EffectReceipt, EffectRequest
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest, parse_json_value
from constructicon.substrate.journal._sqlite_base import _durable_digest, _durable_text
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    require_durable_fact_seal,
    store_durable_fact_seal,
)

EFFECT_PREPARATION_FACT_FAMILY = "effect_preparation"


class _EffectRequestV1(BaseModel):
    """M1/M2 request bytes, before the active run-world was carried."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: ExecutionPath
    kind: str
    subject: dict[str, Any]
    idempotency_key: Digest
    attestation_id: str | None = None


class _EffectRequestV3(BaseModel):
    """M3--M5 request bytes, before simulation added ``mode``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    manifest_hash: Digest
    path: ExecutionPath
    kind: str
    subject: dict[str, Any]
    idempotency_key: Digest
    attestation_id: str | None = None


EffectRequestEra = Literal["m1-m2", "m3-m5", "current"]


@dataclass(frozen=True)
class StoredEffectRequest:
    """One retained wire fact and its lossless current execution view."""

    request: EffectRequest
    persisted_request_hash: Digest
    era: EffectRequestEra


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _exact_model(raw: dict[str, Any], model: type[_ModelT]) -> _ModelT:
    stored = canonical_json(raw)
    value = model.model_validate(raw)
    if stored != canonical_json(value.model_dump(mode="json")):
        raise ValueError(f"{model.__name__} parsing is not lossless")
    return value


def effect_request_identity_from_json(raw: object) -> Digest:
    """Read the carried identity from an exact request of any known era.

    M1/M2 bytes cannot re-derive their key without the relational run and its
    retained manifest.  This selector therefore proves only the exact wire
    shape and extracts its carried key; the row projector independently binds
    that key to the retained run world before the fact can be used.
    """

    stored = parse_json_value(_durable_text(raw, fact="effect request"))
    if not isinstance(stored, dict):
        raise ValueError("effect request is not an object")
    keys = stored.keys()
    if "run_id" not in keys and "manifest_hash" not in keys and "mode" not in keys:
        return _exact_model(stored, _EffectRequestV1).idempotency_key
    if "run_id" in keys and "manifest_hash" in keys and "mode" not in keys:
        return _exact_model(stored, _EffectRequestV3).idempotency_key
    if "run_id" in keys and "manifest_hash" in keys and "mode" in keys:
        return _exact_model(stored, EffectRequest).idempotency_key
    raise ValueError("effect request mixes fields from different wire eras")


def effect_attestation_id_from_json(raw: object) -> str | None:
    """Read the optional authority identity from an exact request of any era."""

    stored = parse_json_value(_durable_text(raw, fact="effect request"))
    if not isinstance(stored, dict):
        raise ValueError("effect request is not an object")
    keys = stored.keys()
    if "run_id" not in keys and "manifest_hash" not in keys and "mode" not in keys:
        return _exact_model(stored, _EffectRequestV1).attestation_id
    if "run_id" in keys and "manifest_hash" in keys and "mode" not in keys:
        return _exact_model(stored, _EffectRequestV3).attestation_id
    if "run_id" in keys and "manifest_hash" in keys and "mode" in keys:
        return _exact_model(stored, EffectRequest).attestation_id
    raise ValueError("effect request mixes fields from different wire eras")


def stored_effect_request(
    raw: object,
    *,
    run_id: RunId,
    manifest_hash: Digest,
) -> StoredEffectRequest:
    """Decode one exact historical/current wire fact without rewriting it."""

    stored = parse_json_value(_durable_text(raw, fact="effect request"))
    if not isinstance(stored, dict):
        raise ValueError("effect request is not an object")
    keys = stored.keys()
    if "run_id" not in keys and "manifest_hash" not in keys and "mode" not in keys:
        v1 = _exact_model(stored, _EffectRequestV1)
        request = EffectRequest(
            run_id=run_id,
            manifest_hash=manifest_hash,
            path=v1.path,
            kind=v1.kind,
            subject=v1.subject,
            idempotency_key=v1.idempotency_key,
            attestation_id=v1.attestation_id,
            mode="live",
        )
        era: EffectRequestEra = "m1-m2"
        persisted_dump = v1.model_dump(mode="json")
    elif "run_id" in keys and "manifest_hash" in keys and "mode" not in keys:
        v3 = _exact_model(stored, _EffectRequestV3)
        if v3.run_id != run_id or v3.manifest_hash != manifest_hash:
            raise ValueError("effect request contradicts its retained run world")
        request = EffectRequest(**v3.model_dump(mode="python"), mode="live")
        era = "m3-m5"
        persisted_dump = v3.model_dump(mode="json")
    elif "run_id" in keys and "manifest_hash" in keys and "mode" in keys:
        current = _exact_model(stored, EffectRequest)
        assert isinstance(current, EffectRequest)
        if current.run_id != run_id or current.manifest_hash != manifest_hash:
            raise ValueError("effect request contradicts its retained run world")
        request = current
        era = "current"
        persisted_dump = current.model_dump(mode="json")
    else:
        raise ValueError("effect request mixes fields from different wire eras")
    return StoredEffectRequest(
        request=request,
        persisted_request_hash=digest(
            "effect-request",
            1,
            persisted_dump,
        ),
        era=era,
    )


def effect_receipt_hash(receipt: EffectReceipt) -> Digest:
    return digest("effect-receipt", 1, receipt.model_dump(mode="json"))


def effect_preparation_fact_hash(row: sqlite3.Row) -> Digest:
    """Seal the exact immutable base shared by every effect lifecycle era."""

    key = _durable_text(row["idempotency_key"], fact="effect preparation key")
    return durable_fact_hash(
        EFFECT_PREPARATION_FACT_FAMILY,
        {
            "idempotency_key": key,
            "run_id": _durable_text(
                row["run_id"],
                fact=f"effect {key!r} preparation run identity",
            ),
            "request_json": _durable_text(
                row["request_json"],
                fact=f"effect {key!r} preparation request bytes",
            ),
            "prepared_at": _durable_text(
                row["prepared_at"],
                fact=f"effect {key!r} preparation time bytes",
            ),
        },
    )


def seal_effect_preparation(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Record one independent, write-once observation of a prepared effect."""

    key = _durable_text(row["idempotency_key"], fact="effect preparation key")
    store_durable_fact_seal(
        connection,
        family=EFFECT_PREPARATION_FACT_FAMILY,
        fact_key=key,
        selector=key,
        fact_hash=effect_preparation_fact_hash(row),
    )


def require_effect_preparation_seal(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> None:
    """Prove a prepared effect against its independent immutable base seal."""

    key = _durable_text(row["idempotency_key"], fact="effect preparation key")
    require_durable_fact_seal(
        connection,
        family=EFFECT_PREPARATION_FACT_FAMILY,
        fact_key=key,
        selector=key,
        fact_hash=effect_preparation_fact_hash(row),
    )


def legacy_effect_seal(row: sqlite3.Row) -> Digest:
    """Seal every byte of the terminal effect fact a legacy writer retained."""

    key = _durable_text(row["idempotency_key"], fact="legacy effect key")
    receipt = _durable_text(
        row["receipt_json"],
        fact=f"legacy effect {key!r} receipt",
    )
    receipted_at = _durable_text(
        row["receipted_at"],
        fact=f"legacy effect {key!r} receipt time",
    )
    return digest(
        "legacy-effect-terminal-seal",
        1,
        {
            "idempotency_key": key,
            "run_id": _durable_text(
                row["run_id"],
                fact=f"legacy effect {key!r} run identity",
            ),
            "request_json": _durable_text(
                row["request_json"],
                fact=f"legacy effect {key!r} request",
            ),
            "receipt_json": receipt,
            "prepared_at": _durable_text(
                row["prepared_at"],
                fact=f"legacy effect {key!r} preparation time",
            ),
            "receipted_at": receipted_at,
        },
    )


def validate_legacy_effect_seal_inventory(connection: sqlite3.Connection) -> None:
    """Prove an exact bijection between legacy terminal rows and their seals."""

    seals = connection.execute("SELECT * FROM legacy_effect_seals").fetchall()
    sealed_keys: set[str] = set()
    for seal in seals:
        key = _durable_text(
            seal["idempotency_key"],
            fact="legacy effect seal identity",
        )
        if key in sealed_keys:
            raise JournalDamaged(
                f"legacy effect seal inventory stores {key!r} more than once"
            )
        sealed_keys.add(key)
        row = connection.execute(
            "SELECT * FROM effects WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            raise JournalDamaged(
                f"legacy effect seal inventory for {key!r} has no terminal primary fact"
            )
        if (
            row["receipt_json"] is None
            or row["receipted_at"] is None
            or row["outcome_run_id"] is not None
            or row["outcome_event_seq"] is not None
            or _durable_digest(
                seal["terminal_fact_hash"],
                fact=f"legacy effect {key!r} terminal seal",
            )
            != legacy_effect_seal(row)
        ):
            raise JournalDamaged(
                f"legacy effect seal inventory for {key!r} is contradictory"
            )

    for row in connection.execute("SELECT * FROM effects").fetchall():
        key = _durable_text(row["idempotency_key"], fact="effect identity")
        has_receipt = row["receipt_json"] is not None
        has_receipt_time = row["receipted_at"] is not None
        has_outcome_run = row["outcome_run_id"] is not None
        has_outcome_event = row["outcome_event_seq"] is not None
        if has_receipt != has_receipt_time or has_outcome_run != has_outcome_event:
            raise JournalDamaged(f"effect {key!r} has torn terminal provenance")
        legacy_terminal = has_receipt and not has_outcome_run
        if legacy_terminal != (key in sealed_keys):
            raise JournalDamaged(
                f"legacy effect seal inventory contradicts {key!r} terminal era"
            )
