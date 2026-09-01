"""One exact SQLite projection and selector for durable attestations."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from constructicon.core.effect import (
    Attestation,
    AttestationDraft,
    ComponentProofSubject,
    HistoricalGitProofSubject,
    attestation_id_for,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json, parse_json_value
from constructicon.substrate.journal._sqlite_base import _durable_text
from constructicon.substrate.journal._sqlite_effects import (
    effect_attestation_id_from_json,
)
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    durable_fact_seal,
    require_durable_fact_seal,
    store_durable_fact_seal,
)

ATTESTATION_FACT_FAMILY = "attestation"
LEGACY_ATTESTATION_FACT_FAMILY = "legacy_attestation_m1_m2"

AttestationProvenance = Literal["m1-m2", "content-derived"]


@dataclass(frozen=True)
class StoredAttestation:
    attestation: Attestation
    provenance: AttestationProvenance


def _stored_attestation_from_json(raw: object) -> StoredAttestation:
    """Decode either current bytes or the exact M1/M2 authority shape.

    M1/M2 checks carried ``ok`` but not ``status`` and their attestation ids
    were random/caller-selected.  The missing status is the only normalized
    field; the retained bytes and random identity stay independently sealed as
    historical provenance and can never enter today's minting path.
    """

    raw_attestation = parse_json_value(_durable_text(raw, fact="attestation payload"))
    if not isinstance(raw_attestation, dict):
        raise ValueError("attestation payload is not an object")
    normalized = deepcopy(raw_attestation)
    checks = normalized.get("checks")
    if not isinstance(checks, list):
        raise ValueError("attestation checks are not an array")
    status_presence = {
        "status" in check for check in checks if isinstance(check, dict)
    }
    if len(status_presence) > 1:
        raise ValueError("attestation mixes historical and current check shapes")
    legacy_check_shape = bool(checks) and status_presence == {False}
    if status_presence == {False}:
        for check in checks:
            if not isinstance(check, dict) or type(check.get("ok")) is not bool:
                raise ValueError("historical attestation check has no exact outcome")
            check["status"] = "passed" if check["ok"] else "failed"
    stored_canonical = canonical_json(normalized)
    attestation = Attestation.model_validate(normalized)
    if stored_canonical != canonical_json(attestation.model_dump(mode="json")):
        raise ValueError("attestation parsing is not lossless")

    subject = attestation.subject
    derived_id: str | None = None
    if not isinstance(subject, HistoricalGitProofSubject):
        try:
            derived_id = attestation_id_for(
                AttestationDraft(
                    action=attestation.action,
                    subject=subject,
                    checks=attestation.checks,
                    check_set_hash=attestation.check_set_hash,
                    evidence=attestation.evidence,
                    manifest_hash=attestation.manifest_hash,
                    workspace_id=attestation.workspace_id,
                )
            )
        except ValidationError:
            derived_id = None
    legacy_subject = isinstance(
        subject,
        (ComponentProofSubject, HistoricalGitProofSubject),
    )
    if legacy_check_shape:
        if attestation.action in {"merge", "promote"} and legacy_subject:
            return StoredAttestation(attestation=attestation, provenance="m1-m2")
        raise ValueError("current attestation cannot use the M1/M2 check shape")
    if derived_id == attestation.attestation_id:
        return StoredAttestation(
            attestation=attestation,
            provenance="content-derived",
        )
    if (
        not checks
        and attestation.action in {"merge", "promote"}
        and legacy_subject
    ):
        return StoredAttestation(attestation=attestation, provenance="m1-m2")
    raise ValueError("attestation id does not derive from its durable content")


def _fact_family(stored: StoredAttestation) -> str:
    return (
        LEGACY_ATTESTATION_FACT_FAMILY
        if stored.provenance == "m1-m2"
        else ATTESTATION_FACT_FAMILY
    )


def _require_current_creator(
    connection: sqlite3.Connection,
    stored: StoredAttestation,
) -> None:
    attestation = stored.attestation
    if stored.provenance != "content-derived" or attestation.created_by_run is None:
        return
    # Local import keeps the dependency graph acyclic while making the
    # canonical attestation boundary reuse the canonical retained-world law.
    from constructicon.substrate.journal._sqlite_runs import validated_run_world

    row = connection.execute(
        "SELECT r.*, o.origin_json FROM runs AS r"
        " LEFT JOIN run_origins AS o ON o.run_id = r.run_id"
        " WHERE r.run_id = ?",
        (str(attestation.created_by_run),),
    ).fetchone()
    creator = validated_run_world(connection, row) if row is not None else None
    if (
        creator is None
        or creator.run_id != attestation.created_by_run
        or creator.manifest.manifest_hash != attestation.manifest_hash
    ):
        raise JournalDamaged(
            f"attestation {attestation.attestation_id!r} contradicts its creator run world"
        )


def attestation_from_json(
    raw: object,
    *,
    expected_attestation_id: str | None = None,
) -> Attestation:
    try:
        attestation = _stored_attestation_from_json(raw).attestation
        if (
            expected_attestation_id is not None
            and attestation.attestation_id != expected_attestation_id
        ):
            raise ValueError("attestation payload contradicts its expected identity")
        return attestation
    except (JournalDamaged, TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged("attestation payload is not a valid durable record") from exc


def _attestation_id_from_json(raw: object) -> str | None:
    """SQLite UDF: read the exact identity under its named provenance law."""

    try:
        return attestation_from_json(raw).attestation_id
    except JournalDamaged:
        return None


def _effect_attestation_id(raw: object) -> str | None:
    try:
        return effect_attestation_id_from_json(raw)
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return None


def attestation_from_row(
    row: sqlite3.Row,
    *,
    expected_attestation_id: str | None = None,
) -> Attestation:
    """Project one row while proving relational, payload, and derived identity."""

    return stored_attestation_from_row(
        row,
        expected_attestation_id=expected_attestation_id,
    ).attestation


def stored_attestation_from_row(
    row: sqlite3.Row,
    *,
    expected_attestation_id: str | None = None,
) -> StoredAttestation:
    """Project one row together with the authority law that wrote it."""

    raw_identity = row["attestation_id"]
    try:
        row_identity = _durable_text(raw_identity, fact="attestation identity")
        stored = _stored_attestation_from_json(row["attestation_json"])
        if stored.attestation.attestation_id != row_identity:
            raise ValueError("attestation key and payload identity disagree")
        if expected_attestation_id is not None and row_identity != expected_attestation_id:
            raise ValueError("attestation identity contradicts its requested selector")
        return stored
    except JournalDamaged:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(
            f"attestation {raw_identity!r} is not a valid durable record"
        ) from exc


def attestation_fact_hash(row: sqlite3.Row, *, family: str) -> Digest:
    """Hash the exact append-only row bytes independently of its derived id."""

    attestation_id = _durable_text(
        row["attestation_id"],
        fact="attestation identity",
    )
    return durable_fact_hash(
        family,
        {
            "attestation_id": attestation_id,
            "attestation_json": _durable_text(
                row["attestation_json"],
                fact=f"attestation {attestation_id!r} payload",
            ),
        },
    )


def seal_attestation(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Write or reconcile one attestation's positive presence/content seal."""

    stored = stored_attestation_from_row(row)
    attestation = stored.attestation
    _require_current_creator(connection, stored)
    family = _fact_family(stored)
    other_family = (
        ATTESTATION_FACT_FAMILY
        if family == LEGACY_ATTESTATION_FACT_FAMILY
        else LEGACY_ATTESTATION_FACT_FAMILY
    )
    if durable_fact_seal(
        connection,
        family=other_family,
        fact_key=attestation.attestation_id,
        selector=attestation.attestation_id,
    ) is not None:
        raise JournalDamaged(
            f"attestation {attestation.attestation_id!r} has contradictory provenance seals"
        )
    store_durable_fact_seal(
        connection,
        family=family,
        fact_key=attestation.attestation_id,
        selector=attestation.attestation_id,
        fact_hash=attestation_fact_hash(row, family=family),
    )


def require_attestation_seal(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> StoredAttestation:
    """Project one attestation only beside its one provenance-family seal."""

    stored = stored_attestation_from_row(row)
    attestation_id = stored.attestation.attestation_id
    family = _fact_family(stored)
    require_durable_fact_seal(
        connection,
        family=family,
        fact_key=attestation_id,
        selector=attestation_id,
        fact_hash=attestation_fact_hash(row, family=family),
    )
    other_family = (
        ATTESTATION_FACT_FAMILY
        if family == LEGACY_ATTESTATION_FACT_FAMILY
        else LEGACY_ATTESTATION_FACT_FAMILY
    )
    if durable_fact_seal(
        connection,
        family=other_family,
        fact_key=attestation_id,
        selector=attestation_id,
    ) is not None:
        raise JournalDamaged(
            f"attestation {attestation_id!r} has contradictory provenance seals"
        )
    _require_current_creator(connection, stored)
    return stored


def validate_attestation_seal_inventory(connection: sqlite3.Connection) -> None:
    """Require one exact provenance seal for every retained attestation row."""

    for row in connection.execute("SELECT * FROM attestations").fetchall():
        require_attestation_seal(connection, row)


def attestation_for_id(
    connection: sqlite3.Connection,
    attestation_id: str,
) -> Attestation | None:
    stored = stored_attestation_for_id(connection, attestation_id)
    return stored.attestation if stored is not None else None


def stored_attestation_for_id(
    connection: sqlite3.Connection,
    attestation_id: str,
) -> StoredAttestation | None:
    """Select by relational or proof-derived id before deciding absence."""

    connection.create_function(
        "constructicon_attestation_id",
        1,
        _attestation_id_from_json,
        deterministic=True,
    )
    rows = connection.execute(
        "SELECT * FROM attestations"
        " WHERE attestation_id = ?"
        " OR constructicon_attestation_id(attestation_json) = ?"
        " OR constructicon_attestation_id(attestation_json) IS NULL"
        " LIMIT 2",
        (attestation_id, attestation_id),
    ).fetchall()
    if len(rows) > 1:
        raise JournalDamaged(
            f"attestation {attestation_id!r} has contradictory durable selectors"
        )
    if rows:
        expected = stored_attestation_from_row(
            rows[0],
            expected_attestation_id=attestation_id,
        )
        stored = require_attestation_seal(connection, rows[0])
        if stored != expected:
            raise JournalDamaged(
                f"attestation {attestation_id!r} contradicts its requested selector"
            )
        return stored
    for family in (ATTESTATION_FACT_FAMILY, LEGACY_ATTESTATION_FACT_FAMILY):
        seal = durable_fact_seal(
            connection,
            family=family,
            fact_key=attestation_id,
            selector=attestation_id,
        )
        if seal is not None:
            raise JournalDamaged(
                f"attestation {attestation_id!r} is missing behind its positive seal"
            )
    connection.create_function(
        "constructicon_effect_attestation_id",
        1,
        _effect_attestation_id,
        deterministic=True,
    )
    dependent = connection.execute(
        "SELECT 1 FROM promotions WHERE attestation_id = ?"
        " UNION ALL SELECT 1 FROM channel_messages WHERE attestation_id = ?"
        " UNION ALL SELECT 1 FROM effects"
        " WHERE constructicon_effect_attestation_id(request_json) = ?"
        " LIMIT 1",
        (attestation_id, attestation_id, attestation_id),
    ).fetchone()
    if dependent is not None:
        raise JournalDamaged(
            f"attestation {attestation_id!r} is missing behind a dependent durable fact"
        )
    return None
