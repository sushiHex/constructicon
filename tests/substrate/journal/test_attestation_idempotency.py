"""Attestation retries return one durable observation without bypassing fences."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.run_worlds import create_test_run, sealed_test_manifest

from constructicon.core.address import RunId
from constructicon.core.effect import (
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
    attestation_id_for,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, digest
from constructicon.core.run import OwnershipLost
from constructicon.substrate.journal.sqlite import SqliteJournal

RUN_ID = RunId("run-attestation-retry")
_MANIFEST = sealed_test_manifest()
MANIFEST_HASH = _MANIFEST.manifest_hash
INPUT_HASH = _MANIFEST.input_hash
_ATTESTATION_IDENTITY_FIELDS = (
    "action",
    "subject",
    "checks",
    "check_set_hash",
    "evidence",
    "manifest_hash",
    "workspace_id",
)


class RefusingClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)
        self.refuse = False

    def now(self) -> datetime:
        if self.refuse:
            raise AssertionError("an exact attestation retry observed time")
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def _draft() -> AttestationDraft:
    return AttestationDraft(
        action="promote",
        subject=ComponentProofSubject(
            component="test/candidate",
            version=Digest("sha256:" + "1" * 64),
            baseline_version=None,
        ),
        checks=(
            CheckResult(
                name="evaluated",
                status="passed",
                ok=True,
                detail="candidate passed",
                elapsed_s=0.0,
            ),
        ),
        check_set_hash=digest("check-set", 1, {"policy": "test"}),
        evidence=(),
        manifest_hash=MANIFEST_HASH,
        workspace_id=None,
    )


def _journal(tmp_path: Path, clock: RefusingClock) -> SqliteJournal:
    return SqliteJournal(tmp_path / "attestations.db", now_fn=clock.now)


def test_an_exact_policy_attestation_retry_needs_no_new_observation(
    tmp_path: Path,
) -> None:
    clock = RefusingClock()
    journal = _journal(tmp_path, clock)
    draft = _draft()
    first = journal.mint_policy_attestation(draft)

    clock.refuse = True
    replayed = journal.mint_policy_attestation(draft)

    assert replayed == first


def test_an_exact_run_attestation_retry_needs_no_time_but_still_needs_its_fence(
    tmp_path: Path,
) -> None:
    clock = RefusingClock()
    journal = _journal(tmp_path, clock)
    create_test_run(journal, RUN_ID)
    stale = journal.claim_run(RUN_ID, owner_id="first-owner", ttl_s=30)
    draft = _draft()
    first = journal.mint_attestation(stale, draft)

    clock.refuse = True
    replayed = journal.mint_attestation(stale, draft)
    assert replayed == first

    clock.refuse = False
    clock.advance(31)
    journal.claim_run(RUN_ID, owner_id="successor", ttl_s=30)
    clock.refuse = True

    with pytest.raises(OwnershipLost, match="fenced out"):
        journal.mint_attestation(stale, draft)


@pytest.mark.parametrize(
    "field",
    _ATTESTATION_IDENTITY_FIELDS,
)
def test_a_loaded_attestation_recomputes_every_content_derived_identity_field(
    field: str,
    tmp_path: Path,
) -> None:
    clock = RefusingClock()
    journal = _journal(tmp_path, clock)
    attestation = journal.mint_policy_attestation(_draft())
    assert set(_ATTESTATION_IDENTITY_FIELDS) == set(AttestationDraft.model_fields)
    database = tmp_path / "attestations.db"
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
            (attestation.attestation_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        if field == "action":
            payload["action"] = "merge"
        elif field == "subject":
            payload["subject"]["component"] = "test/redirected"
        elif field == "checks":
            payload["checks"][0]["detail"] = "redirected result"
        elif field == "check_set_hash":
            payload["check_set_hash"] = str(digest("check-set", 1, {"policy": "other"}))
        elif field == "evidence":
            payload["evidence"] = [
                {
                    "digest": str(digest("artifact", 1, {"evidence": "other"})),
                    "media_type": "application/json",
                    "size": 1,
                    "locator": None,
                }
            ]
        elif field == "manifest_hash":
            payload["manifest_hash"] = str(digest("manifest", 1, {"world": "other"}))
        else:
            assert field == "workspace_id"
            payload["workspace_id"] = "workspace/other"
        connection.execute(
            "UPDATE attestations SET attestation_json = ? WHERE attestation_id = ?",
            (json.dumps(payload), attestation.attestation_id),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.load_attestation(attestation.attestation_id)
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "does not derive from its durable content" in str(damaged.value.__cause__)


def test_a_loaded_attestation_never_collapses_duplicate_subject_authority(
    tmp_path: Path,
) -> None:
    clock = RefusingClock()
    journal = _journal(tmp_path, clock)
    attestation = journal.mint_policy_attestation(_draft())
    database = tmp_path / "attestations.db"
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
            (attestation.attestation_id,),
        ).fetchone()
        assert row is not None
        raw = str(row[0])
        duplicated = raw.replace(
            '"component":',
            '"component":"test/forged","component":',
            1,
        )
        assert duplicated != raw
        connection.execute(
            "UPDATE attestations SET attestation_json = ? WHERE attestation_id = ?",
            (duplicated, attestation.attestation_id),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.load_attestation(attestation.attestation_id)
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "repeats key 'component'" in str(damaged.value.__cause__)


def test_a_loaded_attestation_never_coerces_a_stored_check_boolean(
    tmp_path: Path,
) -> None:
    """The content identity cannot authenticate bytes the model normalized."""

    clock = RefusingClock()
    journal = _journal(tmp_path, clock)
    attestation = journal.mint_policy_attestation(_draft())
    database = tmp_path / "attestations.db"
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
            (attestation.attestation_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        assert payload["checks"][0]["ok"] is True
        payload["checks"][0]["ok"] = 1
        connection.execute(
            "UPDATE attestations SET attestation_json = ? WHERE attestation_id = ?",
            (json.dumps(payload), attestation.attestation_id),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.load_attestation(attestation.attestation_id)
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "parsing is not lossless" in str(damaged.value.__cause__)


@pytest.mark.parametrize("run_bound", [False, True])
def test_a_relocated_attestation_cannot_hide_or_be_reminted(
    run_bound: bool,
    tmp_path: Path,
) -> None:
    clock = RefusingClock()
    journal = _journal(tmp_path, clock)
    draft = _draft()
    lease = None
    if run_bound:
        create_test_run(journal, RUN_ID)
        lease = journal.claim_run(RUN_ID, owner_id="attestation-owner", ttl_s=30)
        attestation = journal.mint_attestation(lease, draft)
    else:
        attestation = journal.mint_policy_attestation(draft)

    foreign_draft = draft.model_copy(
        update={
            "subject": draft.subject.model_copy(
                update={"component": "test/foreign-candidate"}
            )
        }
    )
    foreign_id = attestation_id_for(foreign_draft)
    database = tmp_path / "attestations.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE attestations SET attestation_id = ? WHERE attestation_id = ?",
            (foreign_id, attestation.attestation_id),
        )

    clock.refuse = True
    with pytest.raises(JournalDamaged, match="attestation"):
        journal.load_attestation(attestation.attestation_id)
    with pytest.raises(JournalDamaged, match="attestation"):
        journal.load_attestation(foreign_id)
    with pytest.raises(JournalDamaged, match="attestation"):
        if lease is None:
            journal.mint_policy_attestation(draft)
        else:
            journal.mint_attestation(lease, draft)

    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM attestations").fetchone()
    assert count == (1,)


def test_a_deleted_unreferenced_attestation_cannot_be_reminted(
    tmp_path: Path,
) -> None:
    clock = RefusingClock()
    journal = _journal(tmp_path, clock)
    draft = _draft()
    attestation = journal.mint_policy_attestation(draft)
    database = tmp_path / "attestations.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM attestations WHERE attestation_id = ?",
            (attestation.attestation_id,),
        )

    clock.refuse = True
    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.load_attestation(attestation.attestation_id)
    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.mint_policy_attestation(draft)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attestations").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals"
            " WHERE family = 'attestation' AND fact_key = ?",
            (attestation.attestation_id,),
        ).fetchone() == (1,)


def test_an_attestation_creation_time_cannot_float_outside_its_seal(
    tmp_path: Path,
) -> None:
    clock = RefusingClock()
    journal = _journal(tmp_path, clock)
    attestation = journal.mint_policy_attestation(_draft())
    database = tmp_path / "attestations.db"
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
            (attestation.attestation_id,),
        ).fetchone()
        assert row is not None
        payload = attestation.model_copy(
            update={"created_at": attestation.created_at + timedelta(seconds=1)}
        ).model_dump(mode="json")
        connection.execute(
            "UPDATE attestations SET attestation_json = ? WHERE attestation_id = ?",
            (json.dumps(payload), attestation.attestation_id),
        )

    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.load_attestation(attestation.attestation_id)


def test_a_schema_7_database_cannot_rederive_a_deleted_fact_seal_table(
    tmp_path: Path,
) -> None:
    clock = RefusingClock()
    journal = _journal(tmp_path, clock)
    attestation = journal.mint_policy_attestation(_draft())
    database = tmp_path / "attestations.db"
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE durable_fact_seals")
        connection.execute(
            "UPDATE attestations SET attestation_json = json_set("
            "attestation_json, '$.created_at', ?) WHERE attestation_id = ?",
            (
                (attestation.created_at + timedelta(seconds=1)).isoformat(),
                attestation.attestation_id,
            ),
        )

    with pytest.raises(JournalDamaged, match=r"durable tables are missing.*fact_seals"):
        SqliteJournal(database, now_fn=clock.now)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table'"
            " AND name = 'durable_fact_seals'"
        ).fetchone() is None
