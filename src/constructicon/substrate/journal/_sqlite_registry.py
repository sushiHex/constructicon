# mypy: disable-error-code="attr-defined"
"""Durable component registration, exact snapshots, and promotions."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from typing import Literal, cast

from pydantic import ValidationError

from constructicon.core.address import RunId
from constructicon.core.component import ComponentDef, PromotionRecord
from constructicon.core.effect import ComponentProofSubject, promotion_attestation_faults
from constructicon.core.errors import AdmissionError, JournalDamaged
from constructicon.core.identity import (
    Digest,
    JsonValue,
    canonical_json,
    digest,
    parse_json_value,
)
from constructicon.core.registry import (
    InvalidRegistryRevision,
    RegistryRevision,
    RegistrySnapshot,
    StoredVersion,
)
from constructicon.substrate.journal._sqlite_attestations import (
    stored_attestation_for_id,
)
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
    store_durable_fact_seal,
)

_COMPONENT_FACT_FAMILY = "component_registration"
PROMOTION_FACT_FAMILY = "promotion"
LEGACY_PROMOTION_FACT_FAMILY = "legacy_promotion_pre_v7"


class _SqliteRegistryMixin:
    def snapshot(
        self,
        revision: RegistryRevision | None = None,
    ) -> RegistrySnapshot:
        with self._read() as conn:
            current = _current_registry_revision(conn)
            selected = revision or current
            if (
                selected.registration_seq > current.registration_seq
                or selected.promotion_seq > current.promotion_seq
            ):
                raise InvalidRegistryRevision(
                    f"future registry revision {selected.model_dump()} exceeds "
                    f"current {current.model_dump()}"
                )
            snapshot = _registry_snapshot_at_revision(
                conn,
                selected,
                incoherence=(
                    InvalidRegistryRevision if revision is not None else JournalDamaged
                ),
            )
        return snapshot

    def store_version(self, version: StoredVersion) -> None:
        with self._txn() as conn:
            _registry_sequence_max(
                conn,
                table="components",
                column="registration_seq",
            )
            _registry_sequence_max(
                conn,
                table="promotions",
                column="promotion_seq",
            )
            existing = _component_row_for_version(
                conn,
                name=version.definition.name,
                content_hash=version.content_hash,
            )
            payload = version.definition.model_dump_json()
            if existing is not None:
                retained = _stored_version_from_row(conn, existing)
                if retained.definition == version.definition:
                    return  # idempotent re-registration (startup re-registers)
                raise JournalDamaged(
                    f"component {version.definition.name!r}@{version.content_hash} "
                    "already stored with different definition bytes"
                )
            cursor = conn.execute(
                "INSERT INTO components (name, content_hash, definition_json, registered_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    version.definition.name,
                    str(version.content_hash),
                    payload,
                    version.registered_at.isoformat(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM components WHERE registration_seq = ?",
                (cursor.lastrowid,),
            ).fetchone()
            if row is None:
                raise JournalDamaged("new component registration disappeared before sealing")
            seal_component_registration(conn, row)
            stored = _stored_version_from_row(conn, row)
            if stored != version:
                raise JournalDamaged(
                    f"component {version.definition.name!r}@{version.content_hash}"
                    " changed while being stored"
                )

    def store_promotion(self, record: PromotionRecord) -> PromotionRecord:
        if record.channel != "stable":
            raise JournalDamaged(
                f"promotion {record.attestation_id!r} names unsupported channel {record.channel!r}"
            )
        with self._txn() as conn:
            _registry_sequence_max(
                conn,
                table="components",
                column="registration_seq",
            )
            _registry_sequence_max(
                conn,
                table="promotions",
                column="promotion_seq",
            )
            prior = _promotion_row_for_attestation(conn, record.attestation_id)
            if prior is not None:
                existing = _promotion_from_row(conn, prior)
                if existing.same_identity_as(record):
                    return existing
                raise JournalDamaged(
                    f"attestation {record.attestation_id!r} names contradictory promotion receipts"
                )
            _validate_promotion_authority(conn, record, historical=False)
            if _component_row_for_version(
                conn,
                name=record.component,
                content_hash=record.to_version,
            ) is None or (
                record.from_version is not None
                and _component_row_for_version(
                    conn,
                    name=record.component,
                    content_hash=record.from_version,
                )
                is None
            ):
                raise JournalDamaged(
                    f"promotion {record.attestation_id!r} names an unretained endpoint"
                )
            current = conn.execute(
                "SELECT * FROM promotions WHERE component = ?"
                " AND channel = 'stable' ORDER BY promotion_seq DESC LIMIT 1",
                (record.component,),
            ).fetchone()
            current_stable = (
                str(_promotion_from_row(conn, current).to_version) if current is not None else None
            )
            expected = str(record.from_version) if record.from_version else None
            if current_stable != expected:
                raise AdmissionError(
                    [
                        f"promotion of {record.component!r} refused: stable moved — "
                        f"expected {expected!r}, found {current_stable!r} "
                        "(compare-and-swap; re-evaluate against the current baseline)"
                    ]
                )
            cursor = conn.execute(
                "INSERT INTO promotions (component, channel, from_version, to_version,"
                " attestation_id, actor, source_run, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.component,
                    record.channel,
                    expected,
                    str(record.to_version),
                    record.attestation_id,
                    record.actor,
                    record.source_run,
                    record.created_at.isoformat(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM promotions WHERE promotion_seq = ?",
                (cursor.lastrowid,),
            ).fetchone()
            if row is None:
                raise JournalDamaged("new promotion disappeared before it could be sealed")
            seal_promotion(conn, row)
            stored = _promotion_from_row(conn, row)
            if not stored.same_identity_as(record):
                raise JournalDamaged(
                    f"promotion {record.attestation_id!r} changed while being stored"
                )
            return stored

    def promotion_for_attestation(self, attestation_id: str) -> PromotionRecord | None:
        with self._read() as conn:
            _registry_sequence_max(
                conn,
                table="components",
                column="registration_seq",
            )
            _registry_sequence_max(
                conn,
                table="promotions",
                column="promotion_seq",
            )
            row = _promotion_row_for_attestation(conn, attestation_id)
            return _promotion_from_row(conn, row) if row else None


def promotion_fact_hash(row: sqlite3.Row, *, family: str) -> Digest:
    """Hash every exact scalar in one immutable promotion receipt."""

    sequence = _durable_sequence(
        row["promotion_seq"],
        fact="promotion seal sequence",
    )
    identity = f"promotion {sequence}"
    return durable_fact_hash(
        family,
        {
            "promotion_seq": sequence,
            "component": _durable_text(
                row["component"], fact=f"{identity} component"
            ),
            "channel": _durable_text(row["channel"], fact=f"{identity} channel"),
            "from_version": (
                _durable_text(row["from_version"], fact=f"{identity} baseline")
                if row["from_version"] is not None
                else None
            ),
            "to_version": _durable_text(
                row["to_version"], fact=f"{identity} target"
            ),
            "attestation_id": _durable_text(
                row["attestation_id"], fact=f"{identity} attestation identity"
            ),
            "actor": _durable_text(row["actor"], fact=f"{identity} actor"),
            "source_run": (
                _durable_text(row["source_run"], fact=f"{identity} source run")
                if row["source_run"] is not None
                else None
            ),
            "created_at": _durable_text(
                row["created_at"], fact=f"{identity} creation time"
            ),
        },
    )


def _component_selector(*, name: str, content_hash: object) -> str:
    return canonical_json({"name": name, "content_hash": str(content_hash)})


def component_registration_fact_hash(row: sqlite3.Row) -> Digest:
    """Hash every exact scalar in one immutable component registration."""

    sequence = _durable_sequence(
        row["registration_seq"],
        fact="component registration seal sequence",
    )
    identity = f"component registration {sequence}"
    return durable_fact_hash(
        _COMPONENT_FACT_FAMILY,
        {
            "registration_seq": sequence,
            "name": _durable_text(row["name"], fact=f"{identity} name"),
            "content_hash": _durable_text(
                row["content_hash"], fact=f"{identity} content hash"
            ),
            "definition_json": _durable_text(
                row["definition_json"], fact=f"{identity} definition"
            ),
            "registered_at": _durable_text(
                row["registered_at"], fact=f"{identity} registration time"
            ),
        },
    )


def seal_component_registration(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> None:
    """Write or reconcile the independent seal for one registration."""

    stored = _stored_version_record_from_row(row)
    sequence = _durable_sequence(
        row["registration_seq"],
        fact=f"component {stored.definition.name!r} registration sequence",
    )
    store_durable_fact_seal(
        connection,
        family=_COMPONENT_FACT_FAMILY,
        fact_key=str(sequence),
        selector=_component_selector(
            name=stored.definition.name,
            content_hash=stored.content_hash,
        ),
        fact_hash=component_registration_fact_hash(row),
    )


def seal_promotion(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    historical: bool = False,
) -> None:
    """Write or reconcile the independent positive seal for one receipt."""

    promotion = _promotion_record_payload_from_row(row)
    _validate_promotion_authority(
        connection,
        promotion,
        historical=historical,
    )
    sequence = _durable_sequence(
        row["promotion_seq"],
        fact=f"promotion {promotion.attestation_id!r} sequence",
    )
    family = (
        LEGACY_PROMOTION_FACT_FAMILY if historical else PROMOTION_FACT_FAMILY
    )
    other_family = (
        PROMOTION_FACT_FAMILY
        if historical
        else LEGACY_PROMOTION_FACT_FAMILY
    )
    if durable_fact_seal(
        connection,
        family=other_family,
        fact_key=str(sequence),
        selector=promotion.attestation_id,
    ) is not None:
        raise JournalDamaged(
            f"promotion {promotion.attestation_id!r} has contradictory provenance seals"
        )
    store_durable_fact_seal(
        connection,
        family=family,
        fact_key=str(sequence),
        selector=promotion.attestation_id,
        fact_hash=promotion_fact_hash(row, family=family),
    )


def _promotion_row_for_attestation(
    connection: sqlite3.Connection,
    attestation_id: str,
) -> sqlite3.Row | None:
    """Select by both receipt and independently sealed authority identity."""

    rows = connection.execute(
        "SELECT DISTINCT p.* FROM promotions AS p"
        " LEFT JOIN durable_fact_seals AS s"
        " ON s.family IN (?, ?) AND s.fact_key = CAST(p.promotion_seq AS TEXT)"
        " WHERE p.attestation_id = ? OR s.selector = ? LIMIT 2",
        (
            PROMOTION_FACT_FAMILY,
            LEGACY_PROMOTION_FACT_FAMILY,
            attestation_id,
            attestation_id,
        ),
    ).fetchall()
    if len(rows) > 1:
        raise JournalDamaged(
            f"attestation {attestation_id!r} selects contradictory promotion receipts"
        )
    if rows:
        promotion = _promotion_from_row(connection, rows[0])
        if promotion.attestation_id != attestation_id:
            raise JournalDamaged(
                f"promotion selector {attestation_id!r} contradicts its sealed receipt"
            )
        return cast(sqlite3.Row, rows[0])
    for family in (PROMOTION_FACT_FAMILY, LEGACY_PROMOTION_FACT_FAMILY):
        seal = durable_fact_seal(
            connection,
            family=family,
            selector=attestation_id,
        )
        if seal is not None:
            raise JournalDamaged(
                f"promotion {attestation_id!r} is missing behind its positive seal"
            )
    return None


def _promotion_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> PromotionRecord:
    promotion = _promotion_record_payload_from_row(row)
    sequence = _durable_sequence(
        row["promotion_seq"],
        fact=f"promotion {promotion.attestation_id!r} sequence",
    )
    family = _promotion_fact_family(
        connection,
        sequence=sequence,
        attestation_id=promotion.attestation_id,
    )
    _validate_promotion_authority(
        connection,
        promotion,
        historical=family == LEGACY_PROMOTION_FACT_FAMILY,
    )
    require_durable_fact_seal(
        connection,
        family=family,
        fact_key=str(sequence),
        selector=promotion.attestation_id,
        fact_hash=promotion_fact_hash(row, family=family),
    )
    return promotion


def _promotion_record_payload_from_row(row: sqlite3.Row) -> PromotionRecord:
    identity = f"promotion {row['promotion_seq']!r}/{row['attestation_id']!r}"
    try:
        _durable_sequence(row["promotion_seq"], fact=identity)
        component = _durable_text(row["component"], fact=f"{identity} component")
        channel = _durable_text(row["channel"], fact=f"{identity} channel")
        if channel != "stable":
            raise ValueError("promotion channel is not 'stable'")
        from_version = (
            _durable_digest(row["from_version"], fact=f"{identity} baseline")
            if row["from_version"] is not None
            else None
        )
        to_version = _durable_digest(row["to_version"], fact=f"{identity} target")
        attestation_id = _durable_text(
            row["attestation_id"],
            fact=f"{identity} attestation identity",
        )
        actor = _durable_text(row["actor"], fact=f"{identity} actor")
        source_run = (
            RunId(_durable_text(row["source_run"], fact=f"{identity} source run"))
            if row["source_run"] is not None
            else None
        )
        promotion = PromotionRecord(
            component=component,
            channel="stable",
            from_version=from_version,
            to_version=to_version,
            attestation_id=attestation_id,
            actor=actor,
            source_run=source_run,
            created_at=_durable_datetime(
                row["created_at"],
                fact=f"{identity} creation time",
            ),
        )
        return promotion
    except JournalDamaged:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(f"{identity} is not a valid durable record") from exc


def _promotion_fact_family(
    connection: sqlite3.Connection,
    *,
    sequence: int,
    attestation_id: str,
) -> str:
    seals = [
        family
        for family in (PROMOTION_FACT_FAMILY, LEGACY_PROMOTION_FACT_FAMILY)
        if durable_fact_seal(
            connection,
            family=family,
            fact_key=str(sequence),
            selector=attestation_id,
        )
        is not None
    ]
    if len(seals) != 1:
        raise JournalDamaged(
            f"promotion {attestation_id!r} has no single positive seal for its provenance"
        )
    return seals[0]


def _validate_promotion_authority(
    connection: sqlite3.Connection,
    promotion: PromotionRecord,
    *,
    historical: bool,
) -> None:
    """Bind one receipt to the exact journal-minted edge that authorized it."""

    stored = stored_attestation_for_id(connection, promotion.attestation_id)
    if stored is None:
        raise JournalDamaged(
            f"promotion {promotion.attestation_id!r} has no durable authority fact"
        )
    attestation = stored.attestation
    if historical:
        faults: list[str] = []
        if attestation.action != "promote":
            faults.append("historical authority does not authorize promotion")
        subject = attestation.subject
        if not isinstance(subject, ComponentProofSubject):
            faults.append("historical promotion authority has no component subject")
        elif (
            subject.component != promotion.component
            or subject.version != promotion.to_version
        ):
            faults.append("historical promotion authority names another target")
        if not attestation.ok:
            faults.append("historical promotion authority did not pass")
    elif stored.provenance != "content-derived":
        faults = [
            "M1/M2 caller-selected attestation identity cannot authorize a current move"
        ]
    else:
        faults = list(
            promotion_attestation_faults(
                attestation,
                component=promotion.component,
                version=promotion.to_version,
                baseline=promotion.from_version,
                source_run=promotion.source_run,
            )
        )
    if faults:
        raise JournalDamaged(
            f"promotion {promotion.attestation_id!r} contradicts its authority fact: "
            + "; ".join(faults)
        )


def _stored_version_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> StoredVersion:
    stored = _stored_version_record_from_row(row)
    sequence = _durable_sequence(
        row["registration_seq"],
        fact=f"component {stored.definition.name!r} registration sequence",
    )
    require_durable_fact_seal(
        connection,
        family=_COMPONENT_FACT_FAMILY,
        fact_key=str(sequence),
        selector=_component_selector(
            name=stored.definition.name,
            content_hash=stored.content_hash,
        ),
        fact_hash=component_registration_fact_hash(row),
    )
    return stored


def _current_registry_revision(connection: sqlite3.Connection) -> RegistryRevision:
    """Return the exact append-only bounds of both registry fact streams."""

    return RegistryRevision(
        registration_seq=_registry_sequence_max(
            connection,
            table="components",
            column="registration_seq",
        ),
        promotion_seq=_registry_sequence_max(
            connection,
            table="promotions",
            column="promotion_seq",
        ),
    )


def _registry_snapshot_at_revision(
    connection: sqlite3.Connection,
    revision: RegistryRevision,
    *,
    incoherence: type[InvalidRegistryRevision] | type[JournalDamaged],
) -> RegistrySnapshot:
    """Project one registry cut through the canonical stored-fact laws."""

    versions: dict[str, dict[str, StoredVersion]] = {}
    order: dict[str, list[str]] = {}
    for row in connection.execute(
        "SELECT registration_seq, name, content_hash, definition_json, registered_at"
        " FROM components WHERE registration_seq <= ?"
        " ORDER BY registration_seq ASC",
        (revision.registration_seq,),
    ).fetchall():
        stored = _stored_version_from_row(connection, row)
        name = stored.definition.name
        content_hash = str(stored.content_hash)
        versions.setdefault(name, {})[content_hash] = stored
        order.setdefault(name, []).append(content_hash)

    stable: dict[str, str] = {}
    history: dict[str, list[tuple[str | None, str]]] = {}
    for row in connection.execute(
        "SELECT * FROM promotions WHERE promotion_seq <= ? ORDER BY promotion_seq ASC",
        (revision.promotion_seq,),
    ).fetchall():
        promotion = _promotion_from_row(connection, row)
        component = promotion.component
        before = (
            str(promotion.from_version)
            if promotion.from_version is not None
            else None
        )
        target = str(promotion.to_version)
        retained = versions.get(component, {})
        if target not in retained or (before is not None and before not in retained):
            raise incoherence(
                "registry cut exposes promotion endpoints outside its registration cut"
            )
        if stable.get(component) != before:
            raise incoherence("registry cut contains discontinuous promotion history")
        stable[component] = target
        history.setdefault(component, []).append((before, target))

    return RegistrySnapshot(
        revision=revision,
        versions=versions,
        order={name: tuple(hashes) for name, hashes in order.items()},
        stable=stable,
        history={name: tuple(pairs) for name, pairs in history.items()},
    )


def validate_registry_seal_inventory(connection: sqlite3.Connection) -> None:
    """Project the complete current registry through its one canonical law."""

    current = _current_registry_revision(connection)
    _registry_snapshot_at_revision(
        connection,
        current,
        incoherence=JournalDamaged,
    )


def _normalized_legacy_set_arrays(raw: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Normalize only collection order known to vary in historical writers."""

    normalized = deepcopy(raw)
    metadata = normalized.get("metadata")
    if not isinstance(metadata, dict):
        return normalized
    labels = metadata.get("labels")
    if isinstance(labels, list):
        if any(type(item) is not str for item in labels) or len(labels) != len(set(labels)):
            raise ValueError("component labels are not a unique string set")
        metadata["labels"] = sorted(labels)
    learning = metadata.get("learning")
    if isinstance(learning, dict):
        surfaces = learning.get("change_surfaces")
        if isinstance(surfaces, list):
            if any(type(item) is not str for item in surfaces) or len(surfaces) != len(
                set(surfaces)
            ):
                raise ValueError("component change surfaces are not a unique string set")
            learning["change_surfaces"] = sorted(surfaces)
    requirements = normalized.get("capability_requirements")
    if isinstance(requirements, list):
        if any(
            not isinstance(item, dict)
            or type(item.get("alias")) is not str
            or type(item.get("kind")) is not str
            for item in requirements
        ):
            raise ValueError("component capability requirements are not exact objects")
        aliases = [cast(str, item["alias"]) for item in requirements]
        if len(aliases) != len(set(aliases)):
            raise ValueError("component capability requirement aliases are not unique")
        normalized["capability_requirements"] = sorted(
            requirements,
            key=lambda item: (cast(str, item["alias"]), cast(str, item["kind"])),
        )
    return normalized


def _component_definition_from_json(raw: object) -> tuple[ComponentDef, Digest]:
    """Decode current bytes or the named historical collection-order shapes.

    The historical writer used one in-process frozenset iteration order both
    when storing ``definition_json`` and when hashing the semantic payload.
    Replaying that payload from the retained arrays proves its old identity;
    today's sorted serializer is never allowed to re-version the retained row.
    """

    raw_text = _durable_text(raw, fact="component definition")
    parsed = parse_json_value(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError("component definition is not an object")
    normalized = _normalized_legacy_set_arrays(parsed)
    definition = ComponentDef.model_validate(parsed)
    if canonical_json(normalized) != canonical_json(
        definition.model_dump(mode="json")
    ):
        raise ValueError("component definition parsing is not lossless")
    metadata = parsed.get("metadata")
    learning = metadata.get("learning") if isinstance(metadata, dict) else None
    identity_payload: dict[str, JsonValue] = {
        "role": parsed.get("role"),
        "body": parsed.get("body"),
        "inputs": parsed.get("inputs"),
        "outputs": parsed.get("outputs"),
        # Pre-sort writers hashed the same retained frozenset order they wrote.
        "learning": learning,
    }
    if "capability_requirements" in parsed:
        identity_payload["capability_requirements"] = normalized[
            "capability_requirements"
        ]
        content_hash = digest("component", 2, identity_payload)
    else:
        content_hash = digest("component", 1, identity_payload)
    return definition, content_hash


def _stored_version_record_from_row(row: sqlite3.Row) -> StoredVersion:
    identity = f"component {row['name']!r} version {row['content_hash']!r}"
    try:
        _durable_sequence(row["registration_seq"], fact=f"{identity} registration")
        name = _durable_text(row["name"], fact=f"{identity} name")
        definition, derived_hash = _component_definition_from_json(
            row["definition_json"]
        )
        content_hash = _durable_digest(
            row["content_hash"],
            fact=f"{identity} content hash",
        )
        if definition.name != name:
            raise ValueError("component definition contradicts its relational name")
        if derived_hash != content_hash:
            raise ValueError("component definition contradicts its relational content hash")
        return StoredVersion(
            definition=definition,
            content_hash=content_hash,
            registered_at=_durable_datetime(
                row["registered_at"],
                fact=f"{identity} registration time",
            ),
        )
    except JournalDamaged:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(f"{identity} is not a valid durable record") from exc


def _component_identity_from_json(raw: object) -> str | None:
    """SQLite UDF: derive one registration identity from exact definition bytes."""

    try:
        definition, content_hash = _component_definition_from_json(raw)
        return _component_selector(name=definition.name, content_hash=content_hash)
    except (JournalDamaged, TypeError, ValueError, ValidationError):
        return None


def _component_row_for_version(
    connection: sqlite3.Connection,
    *,
    name: str,
    content_hash: object,
) -> sqlite3.Row | None:
    """Select by relational or definition-derived identity before absence."""

    expected_hash = str(content_hash)
    expected_identity = _component_selector(name=name, content_hash=expected_hash)
    connection.create_function(
        "constructicon_component_identity",
        1,
        _component_identity_from_json,
        deterministic=True,
    )
    rows = connection.execute(
        "SELECT DISTINCT c.* FROM components AS c"
        " LEFT JOIN durable_fact_seals AS s"
        " ON s.family = ? AND s.fact_key = CAST(c.registration_seq AS TEXT)"
        " WHERE (name = ? AND content_hash = ?)"
        " OR constructicon_component_identity(definition_json) = ?"
        " OR s.selector = ?"
        " OR constructicon_component_identity(definition_json) IS NULL"
        " LIMIT 2",
        (
            _COMPONENT_FACT_FAMILY,
            name,
            expected_hash,
            expected_identity,
            expected_identity,
        ),
    ).fetchall()
    if len(rows) > 1:
        raise JournalDamaged(
            f"component {name!r}@{expected_hash} has contradictory durable selectors"
        )
    if not rows:
        seal = durable_fact_seal(
            connection,
            family=_COMPONENT_FACT_FAMILY,
            selector=expected_identity,
        )
        if seal is not None:
            raise JournalDamaged(
                f"component {name!r}@{expected_hash} is missing behind its positive seal"
            )
        return None
    stored = _stored_version_from_row(connection, rows[0])
    if stored.definition.name != name or stored.content_hash != content_hash:
        raise JournalDamaged(
            f"component {name!r}@{expected_hash} contradicts its requested identity"
        )
    return cast(sqlite3.Row, rows[0])


def _registry_sequence_max(
    connection: sqlite3.Connection,
    *,
    table: Literal["components", "promotions"],
    column: Literal["registration_seq", "promotion_seq"],
) -> int:
    """Read one append-only registry bound without SQLite scalar coercion."""

    expected = {
        "components": "registration_seq",
        "promotions": "promotion_seq",
    }
    if expected[table] != column:
        raise AssertionError("registry sequence table and column disagree")
    row = connection.execute(
        f"SELECT COALESCE(MAX({column}), 0) AS maximum,"
        f" COUNT(*) AS retained,"
        f" COALESCE(MAX(CASE WHEN typeof({column}) != 'integer' OR {column} <= 0"
        f" THEN 1 ELSE 0 END), 0) AS damaged FROM {table}"
    ).fetchone()
    if type(row["damaged"]) is not int or row["damaged"] not in (0, 1):
        raise JournalDamaged(f"{table} sequence damage probe is invalid")
    if row["damaged"] == 1:
        raise JournalDamaged(f"{table} contains an invalid durable {column}")
    maximum = _durable_sequence(
        row["maximum"],
        fact=f"maximum {table} sequence",
        allow_zero=True,
    )
    retained = _durable_sequence(
        row["retained"],
        fact=f"retained {table} fact count",
        allow_zero=True,
        kind="count",
    )
    high_water_row = connection.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = ?",
        (table,),
    ).fetchone()
    high_water = (
        _durable_sequence(
            high_water_row["seq"],
            fact=f"{table} append high-water mark",
            allow_zero=True,
        )
        if high_water_row is not None
        else 0
    )
    if maximum != high_water or retained != maximum:
        raise JournalDamaged(f"{table} append-only sequence history is incomplete")
    return maximum
