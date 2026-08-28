# mypy: disable-error-code="attr-defined"
"""Durable component registration, exact snapshots, and promotions."""

from __future__ import annotations

import json
import sqlite3

from constructicon.core.address import RunId
from constructicon.core.component import PromotionRecord
from constructicon.core.errors import AdmissionError, JournalDamaged
from constructicon.core.identity import Digest
from constructicon.core.registry import (
    InvalidRegistryRevision,
    RegistryRevision,
    RegistrySnapshot,
    StoredVersion,
)


class _SqliteRegistryMixin:
    def snapshot(
        self,
        revision: RegistryRevision | None = None,
    ) -> RegistrySnapshot:
        with self._read() as conn:
            conn.execute("BEGIN")  # one WAL read snapshot for both tables
            registration_seq = int(
                conn.execute(
                    "SELECT COALESCE(MAX(registration_seq), 0) FROM components"
                ).fetchone()[0]
            )
            promotion_seq = int(
                conn.execute("SELECT COALESCE(MAX(promotion_seq), 0) FROM promotions").fetchone()[0]
            )
            current = RegistryRevision(
                registration_seq=registration_seq,
                promotion_seq=promotion_seq,
            )
            selected = revision or current
            if (
                selected.registration_seq > current.registration_seq
                or selected.promotion_seq > current.promotion_seq
            ):
                conn.execute("ROLLBACK")
                raise InvalidRegistryRevision(
                    f"future registry revision {selected.model_dump()} exceeds "
                    f"current {current.model_dump()}"
                )
            versions: dict[str, dict[str, StoredVersion]] = {}
            order: dict[str, list[str]] = {}
            for row in conn.execute(
                "SELECT name, content_hash, definition_json, registered_at"
                " FROM components WHERE registration_seq <= ?"
                " ORDER BY registration_seq ASC",
                (selected.registration_seq,),
            ).fetchall():
                stored = StoredVersion(
                    definition=json.loads(row["definition_json"]),
                    content_hash=Digest(row["content_hash"]),
                    registered_at=row["registered_at"],
                )
                versions.setdefault(row["name"], {})[row["content_hash"]] = stored
                order.setdefault(row["name"], []).append(row["content_hash"])
            stable: dict[str, str] = {}
            history: dict[str, list[tuple[str | None, str]]] = {}
            for row in conn.execute(
                "SELECT component, from_version, to_version FROM promotions"
                " WHERE channel = 'stable' AND promotion_seq <= ?"
                " ORDER BY promotion_seq ASC",
                (selected.promotion_seq,),
            ).fetchall():
                component = row["component"]
                before = row["from_version"]
                target = row["to_version"]
                retained = versions.get(component, {})
                if target not in retained or (before is not None and before not in retained):
                    conn.execute("ROLLBACK")
                    error = InvalidRegistryRevision if revision is not None else JournalDamaged
                    raise error(
                        "registry cut exposes promotion endpoints outside its registration cut"
                    )
                if stable.get(component) != before:
                    conn.execute("ROLLBACK")
                    error = InvalidRegistryRevision if revision is not None else JournalDamaged
                    raise error("registry cut contains discontinuous promotion history")
                stable[component] = target
                history.setdefault(row["component"], []).append((before, target))
            conn.execute("COMMIT")
        return RegistrySnapshot(
            revision=selected,
            versions=versions,
            order={name: tuple(hashes) for name, hashes in order.items()},
            stable=stable,
            history={name: tuple(pairs) for name, pairs in history.items()},
        )

    def store_version(self, version: StoredVersion) -> None:
        with self._txn() as conn:
            existing = conn.execute(
                "SELECT definition_json FROM components WHERE name = ? AND content_hash = ?",
                (version.definition.name, str(version.content_hash)),
            ).fetchone()
            payload = version.definition.model_dump_json()
            if existing is not None:
                if existing["definition_json"] == payload:
                    return  # idempotent re-registration (startup re-registers)
                raise JournalDamaged(
                    f"component {version.definition.name!r}@{version.content_hash} "
                    "already stored with different definition bytes"
                )
            conn.execute(
                "INSERT INTO components (name, content_hash, definition_json, registered_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    version.definition.name,
                    str(version.content_hash),
                    payload,
                    version.registered_at.isoformat(),
                ),
            )

    def store_promotion(self, record: PromotionRecord) -> PromotionRecord:
        with self._txn() as conn:
            prior = conn.execute(
                "SELECT * FROM promotions WHERE attestation_id = ?",
                (record.attestation_id,),
            ).fetchone()
            if prior is not None:
                existing = _promotion_from_row(prior)
                if _same_promotion_identity(existing, record):
                    return existing
                raise JournalDamaged(
                    f"attestation {record.attestation_id!r} names contradictory promotion receipts"
                )
            current = conn.execute(
                "SELECT to_version FROM promotions WHERE component = ?"
                " AND channel = 'stable' ORDER BY promotion_seq DESC LIMIT 1",
                (record.component,),
            ).fetchone()
            current_stable = current["to_version"] if current else None
            expected = str(record.from_version) if record.from_version else None
            if current_stable != expected:
                raise AdmissionError(
                    [
                        f"promotion of {record.component!r} refused: stable moved — "
                        f"expected {expected!r}, found {current_stable!r} "
                        "(compare-and-swap; re-evaluate against the current baseline)"
                    ]
                )
            conn.execute(
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
            return record

    def promotion_for_attestation(self, attestation_id: str) -> PromotionRecord | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT * FROM promotions WHERE attestation_id = ?",
                (attestation_id,),
            ).fetchone()
        return _promotion_from_row(row) if row else None


def _promotion_from_row(row: sqlite3.Row) -> PromotionRecord:
    return PromotionRecord(
        component=row["component"],
        channel=row["channel"],
        from_version=Digest(row["from_version"]) if row["from_version"] else None,
        to_version=Digest(row["to_version"]),
        attestation_id=row["attestation_id"],
        actor=row["actor"],
        source_run=RunId(row["source_run"]) if row["source_run"] else None,
        created_at=row["created_at"],
    )


def _same_promotion_identity(left: PromotionRecord, right: PromotionRecord) -> bool:
    return (
        left.component == right.component
        and left.channel == right.channel
        and left.from_version == right.from_version
        and left.to_version == right.to_version
        and left.attestation_id == right.attestation_id
        and left.source_run == right.source_run
    )
