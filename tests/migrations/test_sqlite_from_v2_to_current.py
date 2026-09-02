"""Exact schema-v2 registry authority survives the current migration chain."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from constructicon.core.address import RunId
from constructicon.core.component import PromotionRecord
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, digest
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.conftest import BRIEF, ISSUE, atomic, review_impl, triage_impl
from tests.migrations.historical_sqlite import M2_SCHEMA, historical_json

TS = "2026-01-02T00:00:00+00:00"
M2_ATTESTATION_ID = "att-m2-policy-random-id"
M2_UNUSED_ATTESTATION_ID = "att-m2-unused-policy-random-id"


def _build_exact_m2_database(
    database: Path,
) -> tuple[str, Digest, Digest, str, str]:
    """Write only facts and columns the merged M2 writer understood."""

    definition, _implementation = atomic(
        "migration/m2-policy",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    version = definition.content_hash()
    definition_json = definition.model_dump_json()
    next_definition, _next_implementation = atomic(
        definition.name,
        (ISSUE,),
        (BRIEF,),
        review_impl,
    )
    next_version = next_definition.content_hash()
    historical_baseline = digest("component", 1, {"m2": "unrelated-baseline"})
    attestation = {
        "attestation_id": M2_ATTESTATION_ID,
        "action": "promote",
        "subject": {
            "kind": "component",
            "component": definition.name,
            "version": str(version),
            # M2 checked component/target/checks, but not this baseline.
            "baseline_version": str(historical_baseline),
        },
        "checks": [
            {
                "name": "bootstrap-initial",
                "ok": True,
                "detail": "exact M2 policy authority",
                "elapsed_s": 0.0,
            }
        ],
        "check_set_hash": str(digest("check-set", 1, {"policy": "m2"})),
        "evidence": [],
        "manifest_hash": str(digest("manifest", 1, {"policy": "m2"})),
        "created_by_run": None,
        "workspace_id": None,
        "created_at": TS.replace("+00:00", "Z"),
    }
    attestation_json = historical_json(attestation)
    unused_attestation = {
        **attestation,
        "attestation_id": M2_UNUSED_ATTESTATION_ID,
        "subject": {
            **attestation["subject"],
            "version": str(next_version),
        },
        "check_set_hash": str(digest("check-set", 1, {"policy": "m2-unused"})),
    }

    with sqlite3.connect(database) as connection:
        connection.executescript(M2_SCHEMA)
        connection.execute(
            "INSERT INTO components"
            " (name, content_hash, definition_json, registered_at)"
            " VALUES (?, ?, ?, ?)",
            (definition.name, str(version), definition_json, TS),
        )
        connection.execute(
            "INSERT INTO components"
            " (name, content_hash, definition_json, registered_at)"
            " VALUES (?, ?, ?, ?)",
            (
                next_definition.name,
                str(next_version),
                next_definition.model_dump_json(),
                TS,
            ),
        )
        connection.execute(
            "INSERT INTO attestations VALUES (?, ?)",
            (M2_ATTESTATION_ID, attestation_json),
        )
        connection.execute(
            "INSERT INTO attestations VALUES (?, ?)",
            (M2_UNUSED_ATTESTATION_ID, historical_json(unused_attestation)),
        )
        connection.execute(
            "INSERT INTO promotions"
            " (component, channel, from_version, to_version, attestation_id,"
            " actor, source_run, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                definition.name,
                "stable",
                None,
                str(version),
                M2_ATTESTATION_ID,
                "m2:bootstrap",
                # M2 did not bind receipt metadata to created_by_run either.
                "run-m2-unrelated-observer",
                TS,
            ),
        )
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    return definition.name, version, next_version, definition_json, attestation_json


def test_exact_m2_policy_authority_and_promotion_survive_upgrade(
    tmp_path: Path,
) -> None:
    database = tmp_path / "m2.db"
    component, version, next_version, definition_json, attestation_json = (
        _build_exact_m2_database(database)
    )

    migrated = SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        retained_definition = connection.execute(
            "SELECT definition_json FROM components WHERE name = ?",
            (component,),
        ).fetchone()[0]
        retained_attestation = connection.execute(
            "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
            (M2_ATTESTATION_ID,),
        ).fetchone()[0]
    assert retained_definition == definition_json
    assert retained_attestation == attestation_json

    attestation = migrated.load_attestation(M2_ATTESTATION_ID)
    assert attestation is not None
    assert attestation.attestation_id == M2_ATTESTATION_ID
    assert attestation.created_by_run is None
    snapshot = migrated.snapshot()
    assert snapshot.get(component, version) is not None
    assert snapshot.stable_version(component) == version
    promotion = migrated.promotion_for_attestation(M2_ATTESTATION_ID)
    assert promotion is not None
    assert promotion.from_version is None
    assert promotion.source_run == RunId("run-m2-unrelated-observer")
    # An exact retry reconciles the already-sealed historical receipt before
    # applying today's stronger authority law.
    assert migrated.store_promotion(promotion) == promotion

    unused = migrated.load_attestation(M2_UNUSED_ATTESTATION_ID)
    assert unused is not None
    with pytest.raises(JournalDamaged, match="caller-selected attestation identity"):
        migrated.store_promotion(
            PromotionRecord(
                component=component,
                channel="stable",
                from_version=version,
                to_version=next_version,
                attestation_id=M2_UNUSED_ATTESTATION_ID,
                actor="current:operator",
                source_run=RunId("run-current-new-edge"),
                created_at=promotion.created_at + timedelta(seconds=1),
            )
        )
    assert migrated.run_record(RunId("run-m2-unrelated-observer")) is None
    assert migrated.run_records() == []
