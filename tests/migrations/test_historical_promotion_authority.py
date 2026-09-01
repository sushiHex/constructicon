"""Exact promotion-authority boundaries retained across historical eras."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.effect import (
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import digest
from constructicon.core.registry import StoredVersion
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import BRIEF, ISSUE, FakeClock, atomic, triage_impl
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6
from tests.run_attestations import mint_run_attestation
from tests.run_worlds import sealed_test_manifest


def test_exact_early_m6_creator_source_mismatch_remains_readable(
    tmp_path: Path,
) -> None:
    """Early M6 receipts did not yet bind report ``source_run`` to creator."""

    database = tmp_path / "m6-creator-source-mismatch.db"
    clock = FakeClock()
    journal = SqliteJournal(database, now_fn=clock.now)
    definition, _implementation = atomic(
        "migration/m6-promotion",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    version = definition.content_hash()
    journal.store_version(
        StoredVersion(
            definition=definition,
            content_hash=version,
            registered_at=clock.now(),
        )
    )
    creator = RunId("run-m6-attestation-creator")
    manifest_hash = sealed_test_manifest().manifest_hash
    attestation = mint_run_attestation(
        journal,
        creator,
        AttestationDraft(
            action="promote",
            subject=ComponentProofSubject(
                component=definition.name,
                version=version,
                baseline_version=None,
            ),
            checks=(
                CheckResult(
                    name="m6-proof",
                    status="passed",
                    detail="exact early-M6 run proof",
                    elapsed_s=0.0,
                ),
            ),
            check_set_hash=digest("check-set", 1, {"m6": "proof"}),
            manifest_hash=manifest_hash,
        ),
    )
    _downgrade_v7_schema_to_v6(database)
    historical_source = RunId("run-m6-report-source")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO promotions"
            " (component, channel, from_version, to_version, attestation_id,"
            " actor, source_run, created_at) VALUES (?, 'stable', NULL, ?, ?, ?, ?, ?)",
            (
                definition.name,
                str(version),
                attestation.attestation_id,
                "m6:operator",
                str(historical_source),
                clock.now().isoformat(),
            ),
        )
        connection.commit()

    migrated = SqliteJournal(database, now_fn=clock.now)
    assert migrated.load_attestation(attestation.attestation_id) == attestation
    promotion = migrated.promotion_for_attestation(attestation.attestation_id)
    assert promotion is not None
    assert promotion.source_run == historical_source
    assert promotion.source_run != attestation.created_by_run
    assert migrated.run_record(historical_source) is None
    assert [record.run_id for record in migrated.run_records()] == [creator]


def test_migration_never_classifies_a_status_erased_send_as_legacy(
    tmp_path: Path,
) -> None:
    """M1/M2 compatibility is not a generic ``ok``-only escape hatch."""

    database = tmp_path / "v6-forged-legacy-send.db"
    SqliteJournal(database)
    _downgrade_v7_schema_to_v6(database)
    draft = {
        "action": "send",
        "subject": {
            "kind": "channel_send",
            "message_id": str(digest("channel-message", 1, {"legacy": "forged"})),
            "channel_id": "channel/forged",
            "channel_revision": "1",
            "lane": "review",
            "interaction": "advice",
            "recipient_actor_id": "static:reviewer",
            "run_id": "run-forged-send",
            "path": ExecutionPath(
                scope=ScopePath(segments=("forged", "send"))
            ).model_dump(mode="json"),
            "port": "request",
            "contract": {"type_id": "test/Ask", "schema_hash": "ask-v1"},
            "reply_port": "reply",
            "reply_contract": {
                "type_id": "test/Answer",
                "schema_hash": "answer-v1",
            },
            "payload_digest": str(digest("channel-payload", 1, {"ask": "ship?"})),
        },
        "checks": [
            {
                "name": "erased-current-status",
                "ok": True,
                "detail": "not a historical send writer",
                "elapsed_s": 0.0,
            }
        ],
        "check_set_hash": str(digest("check-set", 1, {"forged": "send"})),
        "evidence": [],
        "manifest_hash": str(digest("manifest", 1, {"forged": "send"})),
        "workspace_id": None,
    }
    forged_id = "att-" + str(digest("attestation", 1, draft)).removeprefix(
        "sha256:"
    )
    payload = {
        "attestation_id": forged_id,
        **draft,
        "created_by_run": None,
        "created_at": "2026-01-06T00:00:00Z",
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO attestations VALUES (?, ?)",
            (forged_id, json.dumps(payload, separators=(",", ":"))),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="attestation"):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (6,)
