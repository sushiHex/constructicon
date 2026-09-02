"""Prepared effects are exact durable facts, not best-effort markers."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.run_worlds import create_test_run, sealed_test_manifest, start_test_run

from constructicon.core.address import ExecutionPath, IterationFrame, RunId, ScopePath
from constructicon.core.effect import (
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
    EffectReceipt,
    EffectRequest,
    idempotency_key,
    request_hash,
)
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import canonical_json, digest
from constructicon.core.run import RunLease
from constructicon.substrate.journal._sqlite_effects import legacy_effect_seal
from constructicon.substrate.journal._sqlite_execution_facts import event_fact_key, seal_event
from constructicon.substrate.journal.sqlite import SqliteJournal

RUN_ID = RunId("run-effect-preparation")
PATH = ExecutionPath(scope=ScopePath(segments=("effect",)))
_MANIFEST = sealed_test_manifest()
MANIFEST_HASH = _MANIFEST.manifest_hash
INPUT_HASH = digest("inputs", 1, {})
SUBJECT = {"announcement": "ship"}


class RefusingClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)
        self.refuse = False

    def now(self) -> datetime:
        if self.refuse:
            raise AssertionError("an exact prepared-effect retry observed time")
        return self.value


def _prepared(
    tmp_path: Path,
    *,
    path: ExecutionPath = PATH,
) -> tuple[SqliteJournal, RefusingClock, EffectRequest, RunLease, Path]:
    clock = RefusingClock()
    database = tmp_path / "effects.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    create_test_run(journal, RUN_ID)
    lease = start_test_run(journal, RUN_ID, owner_id="effect-owner")
    request = EffectRequest(
        run_id=RUN_ID,
        manifest_hash=MANIFEST_HASH,
        path=path,
        kind="announce",
        subject=SUBJECT,
        idempotency_key=idempotency_key(
            MANIFEST_HASH,
            path,
            "announce",
            SUBJECT,
        ),
    )
    assert journal.record_effect_prepared(lease, request) == request
    return journal, clock, request, lease, database


def _receipt(request: EffectRequest) -> EffectReceipt:
    return EffectReceipt(
        request_hash=request_hash(request),
        status="committed",
        external_reference="announcement/1",
        observed_state={"announcement": "ship"},
    )


def _downgrade_effect_table_to_v6(database: Path) -> None:
    """Construct the exact pre-provenance effect table for migration tests."""

    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE effects RENAME TO effects_v7")
        connection.execute(
            "CREATE TABLE effects ("
            " idempotency_key TEXT PRIMARY KEY, run_id TEXT NOT NULL,"
            " request_json TEXT NOT NULL, receipt_json TEXT,"
            " prepared_at TEXT NOT NULL, receipted_at TEXT)"
        )
        connection.execute(
            "INSERT INTO effects SELECT idempotency_key, run_id, request_json,"
            " receipt_json, prepared_at, receipted_at FROM effects_v7"
        )
        connection.execute("DROP TABLE effects_v7")
        connection.execute("DROP TABLE legacy_effect_seals")
        connection.execute("PRAGMA user_version = 6")
        connection.commit()


def test_an_exact_prepared_effect_retry_needs_no_new_observation(tmp_path: Path) -> None:
    journal, clock, request, lease, _database = _prepared(tmp_path)
    clock.refuse = True

    assert journal.record_effect_prepared(lease, request) == request


def test_an_effect_fact_key_does_not_invent_an_absent_command(tmp_path: Path) -> None:
    journal, _clock, request, _lease, _database = _prepared(tmp_path)

    assert journal.command(str(request.idempotency_key)) is None


def test_current_schema_never_recreates_a_missing_effect_table(tmp_path: Path) -> None:
    _journal, clock, _request, _lease, database = _prepared(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE effects")

    with pytest.raises(JournalDamaged, match="durable tables are missing: effects"):
        SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'effects'"
        ).fetchone() is None


def test_effect_preparation_requires_the_leased_runs_exact_manifest(tmp_path: Path) -> None:
    journal, clock, request, lease, _database = _prepared(tmp_path)
    foreign_manifest = digest("manifest", 1, {"effect": "foreign-world"})
    foreign = request.model_copy(
        update={
            "manifest_hash": foreign_manifest,
            "idempotency_key": idempotency_key(
                foreign_manifest,
                request.path,
                request.kind,
                request.subject,
            ),
        }
    )
    clock.refuse = True

    with pytest.raises(ContractViolation, match="contradicts its run manifest"):
        journal.record_effect_prepared(lease, foreign)

    assert journal.receipt_for(foreign.idempotency_key) is None


def test_every_run_world_boundary_types_durable_manifest_identity(tmp_path: Path) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    draft = AttestationDraft(
        action="promote",
        subject=ComponentProofSubject(
            component="test/candidate",
            version=digest("component", 1, {"candidate": 1}),
            baseline_version=None,
        ),
        checks=(
            CheckResult(
                name="candidate",
                status="passed",
                detail="candidate passed",
                elapsed_s=0.0,
            ),
        ),
        check_set_hash=digest("check-set", 1, {"policy": "test"}),
        manifest_hash=MANIFEST_HASH,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE runs SET manifest_hash = 'not-a-digest' WHERE run_id = ?",
            (str(RUN_ID),),
        )
        connection.commit()
    clock.refuse = True

    boundaries = (
        lambda: journal.run_manifest_hash(RUN_ID),
        lambda: journal.run_record(RUN_ID),
        lambda: journal.record_effect_prepared(lease, request),
        lambda: journal.mint_attestation(lease, draft),
    )
    for project in boundaries:
        with pytest.raises(JournalDamaged, match=r"immutable world|manifest identity"):
            project()

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE runs SET manifest_hash = ?, input_hash = 'not-a-digest' WHERE run_id = ?",
            (str(MANIFEST_HASH), str(RUN_ID)),
        )
        connection.commit()
    with pytest.raises(JournalDamaged, match=r"immutable world|input identity"):
        journal.run_record(RUN_ID)


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("status", "bogus"),
        ("created_at", "not-a-timestamp"),
        ("lease_expires_at", "not-a-timestamp"),
        ("cancel_requested", 2),
    ),
)
def test_run_projection_never_leaks_or_coerces_durable_lifecycle_damage(
    column: str,
    value: object,
    tmp_path: Path,
) -> None:
    journal, _clock, _request, _lease, database = _prepared(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE runs SET {column} = ? WHERE run_id = ?",
            (value, str(RUN_ID)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable") as damaged:
        journal.run_record(RUN_ID)
    assert isinstance(damaged.value.__cause__, ValueError)


def test_a_tampered_prepared_effect_request_is_journal_damage(tmp_path: Path) -> None:
    journal, _clock, request, lease, database = _prepared(tmp_path)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT request_json FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["kind"] = "redirected"
        connection.execute(
            "UPDATE effects SET request_json = ? WHERE idempotency_key = ?",
            (json.dumps(payload), str(request.idempotency_key)),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=r"(not a valid durable request|positive seal)",
    ):
        journal.record_effect_prepared(lease, request)


def test_a_prepared_effect_request_must_decode_losslessly(tmp_path: Path) -> None:
    path = ExecutionPath(
        scope=PATH.scope,
        iterations=(IterationFrame(loop=PATH.scope, index=1),),
    )
    journal, _clock, request, lease, database = _prepared(tmp_path, path=path)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT request_json FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["path"]["iterations"][0]["index"] = True
        connection.execute(
            "UPDATE effects SET request_json = ? WHERE idempotency_key = ?",
            (json.dumps(payload), str(request.idempotency_key)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable request"):
        journal.record_effect_prepared(lease, request)
    with pytest.raises(JournalDamaged, match="not a valid durable request"):
        journal.receipt_for(request.idempotency_key)


def test_a_current_effect_cannot_erase_its_additive_mode(tmp_path: Path) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT request_json FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        assert payload.pop("mode") == "live"
        connection.execute(
            "UPDATE effects SET request_json = ? WHERE idempotency_key = ?",
            (json.dumps(payload), str(request.idempotency_key)),
        )
        connection.commit()

    clock.refuse = True
    for read in (
        lambda: journal.record_effect_prepared(lease, request),
        lambda: journal.receipt_for(request.idempotency_key),
    ):
        with pytest.raises(JournalDamaged, match="positive seal"):
            read()


def test_an_exact_terminal_effect_retry_needs_no_new_observation(tmp_path: Path) -> None:
    journal, clock, request, lease, _database = _prepared(tmp_path)
    receipt = _receipt(request)
    journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")

    clock.refuse = True
    journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")

    assert journal.receipt_for(request.idempotency_key) == receipt


@pytest.mark.parametrize(
    ("first", "second"),
    ((1, True), (1, 1.0), (True, 1.0)),
)
def test_receipt_scalar_types_are_distinct_durable_observations(
    tmp_path: Path,
    first: int | float | bool,
    second: int | float | bool,
) -> None:
    journal, clock, request, lease, _database = _prepared(tmp_path)
    receipt = _receipt(request).model_copy(update={"observed_state": {"value": first}})
    journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")

    clock.refuse = True
    contradiction = receipt.model_copy(update={"observed_state": {"value": second}})
    with pytest.raises(JournalDamaged, match="different receipt"):
        journal.record_effect_outcome(
            lease,
            request,
            contradiction,
            "EffectCommitted",
        )

    assert journal.receipt_for(request.idempotency_key) == receipt


def test_a_terminal_effect_cannot_hide_a_tampered_prepared_request(tmp_path: Path) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    receipt = _receipt(request)
    journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    terminal_fence = journal.max_event_seq(RUN_ID)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT request_json FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["kind"] = "redirected"
        connection.execute(
            "UPDATE effects SET request_json = ? WHERE idempotency_key = ?",
            (json.dumps(payload), str(request.idempotency_key)),
        )
        connection.commit()

    clock.refuse = True
    with pytest.raises(JournalDamaged, match="not a valid durable request"):
        journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    assert journal.max_event_seq(RUN_ID) == terminal_fence

    with pytest.raises(JournalDamaged, match="not a valid durable request"):
        journal.receipt_for(request.idempotency_key)


def test_a_terminal_receipt_must_name_its_prepared_request(tmp_path: Path) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    receipt = _receipt(request)
    journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    terminal_fence = journal.max_event_seq(RUN_ID)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT receipt_json FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["request_hash"] = str(digest("effect-request", 1, {"forged": True}))
        connection.execute(
            "UPDATE effects SET receipt_json = ? WHERE idempotency_key = ?",
            (json.dumps(payload), str(request.idempotency_key)),
        )
        connection.commit()

    clock.refuse = True
    with pytest.raises(JournalDamaged, match="no valid durable receipt"):
        journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    assert journal.max_event_seq(RUN_ID) == terminal_fence

    with pytest.raises(JournalDamaged, match="no valid durable receipt"):
        journal.receipt_for(request.idempotency_key)


def test_a_terminal_effect_receipt_must_decode_losslessly(tmp_path: Path) -> None:
    journal, _clock, request, lease, database = _prepared(tmp_path)
    receipt = _receipt(request)
    journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    terminal_fence = journal.max_event_seq(RUN_ID)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT receipt_json FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["unknown"] = True
        connection.execute(
            "UPDATE effects SET receipt_json = ? WHERE idempotency_key = ?",
            (json.dumps(payload), str(request.idempotency_key)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="no valid durable receipt"):
        journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    assert journal.max_event_seq(RUN_ID) == terminal_fence
    with pytest.raises(JournalDamaged, match="no valid durable receipt"):
        journal.receipt_for(request.idempotency_key)


@pytest.mark.parametrize("terminal", (False, True))
def test_an_effect_row_must_have_one_coherent_receipt_lifecycle(
    tmp_path: Path,
    terminal: bool,
) -> None:
    journal, _clock, request, lease, database = _prepared(tmp_path)
    if terminal:
        journal.record_effect_outcome(
            lease,
            request,
            _receipt(request),
            "EffectCommitted",
        )

    with sqlite3.connect(database) as connection:
        if terminal:
            connection.execute(
                "UPDATE effects SET receipted_at = NULL WHERE idempotency_key = ?",
                (str(request.idempotency_key),),
            )
        else:
            connection.execute(
                "UPDATE effects SET receipted_at = ? WHERE idempotency_key = ?",
                (datetime(2026, 1, 1, tzinfo=UTC).isoformat(), str(request.idempotency_key)),
            )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable request"):
        journal.record_effect_prepared(lease, request)
    with pytest.raises(JournalDamaged, match="not a valid durable request"):
        journal.receipt_for(request.idempotency_key)


@pytest.mark.parametrize("column", ("prepared_at", "receipted_at"))
def test_effect_observation_times_use_the_exact_durable_timestamp_law(
    column: str,
    tmp_path: Path,
) -> None:
    journal, _clock, request, lease, database = _prepared(tmp_path)
    if column == "receipted_at":
        journal.record_effect_outcome(
            lease,
            request,
            _receipt(request),
            "EffectCommitted",
        )
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE effects SET {column} = ? WHERE idempotency_key = ?",
            ("2026-01-01 00:00:00+00:00", str(request.idempotency_key)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable timestamp"):
        journal.record_effect_prepared(lease, request)
    with pytest.raises(JournalDamaged, match="not a valid durable timestamp"):
        journal.receipt_for(request.idempotency_key)


def test_effect_receipt_time_is_bound_to_its_exact_outcome_event(tmp_path: Path) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    receipt = _receipt(request)
    journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    fence = journal.max_event_seq(RUN_ID)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE effects SET receipted_at = ? WHERE idempotency_key = ?",
            ("2026-02-02T00:00:00+00:00", str(request.idempotency_key)),
        )
        connection.commit()
    clock.refuse = True

    with pytest.raises(JournalDamaged, match="exact outcome event"):
        journal.receipt_for(request.idempotency_key)
    with pytest.raises(JournalDamaged, match="exact outcome event"):
        journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    assert journal.max_event_seq(RUN_ID) == fence


def test_effect_relational_text_is_never_normalized_from_a_sqlite_integer(
    tmp_path: Path,
) -> None:
    journal, _clock, request, _lease, database = _prepared(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE effects RENAME TO effects_typed")
        connection.execute(
            "CREATE TABLE effects ("
            " idempotency_key TEXT PRIMARY KEY, run_id, request_json TEXT NOT NULL,"
            " receipt_json TEXT, prepared_at TEXT NOT NULL, receipted_at TEXT,"
            " outcome_run_id TEXT, outcome_event_seq INTEGER)"
        )
        connection.execute(
            "INSERT INTO effects SELECT idempotency_key, 7, request_json,"
            " receipt_json, prepared_at, receipted_at, outcome_run_id,"
            " outcome_event_seq FROM effects_typed"
        )
        connection.execute("DROP TABLE effects_typed")
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"run identity.*durable text"):
        journal.receipt_for(request.idempotency_key)


def test_two_runs_close_one_canonical_first_preparation(tmp_path: Path) -> None:
    journal, clock, first, first_lease, _database = _prepared(tmp_path)
    second_run = RunId("run-effect-contender")
    create_test_run(journal, second_run)
    second_lease = journal.claim_run(
        second_run,
        owner_id="effect-contender",
        ttl_s=30,
    )
    contender = first.model_copy(update={"run_id": second_run})

    clock.refuse = True
    canonical = journal.record_effect_prepared(second_lease, contender)

    assert canonical == first
    clock.refuse = False
    receipt = _receipt(canonical)
    assert (
        journal.record_effect_outcome(
            first_lease,
            canonical,
            receipt,
            "EffectCommitted",
        )
        == "recorded"
    )

    clock.refuse = True
    assert (
        journal.record_effect_outcome(
            second_lease,
            canonical,
            receipt,
            "EffectReconciled",
        )
        == "already_recorded"
    )
    assert journal.receipt_for(first.idempotency_key) == receipt
    assert journal.events(second_run) == []


def test_a_deleted_preparation_cannot_be_healed_or_completed(tmp_path: Path) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    fence = journal.max_event_seq(RUN_ID)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        )
        connection.commit()

    clock.refuse = True
    with pytest.raises(JournalDamaged, match="positive seal remains"):
        journal.record_effect_outcome(
            lease,
            request,
            _receipt(request),
            "EffectCommitted",
        )
    with pytest.raises(JournalDamaged, match="positive seal remains"):
        journal.receipt_for(request.idempotency_key)
    with pytest.raises(JournalDamaged, match="positive seal remains"):
        journal.record_effect_prepared(lease, request)
    assert journal.max_event_seq(RUN_ID) == fence
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone() == (0,)


def test_an_effect_prevents_reminting_its_deleted_attestation_without_seals(
    tmp_path: Path,
) -> None:
    clock = RefusingClock()
    database = tmp_path / "effect-dependent-attestation.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    create_test_run(journal, RUN_ID)
    lease = start_test_run(journal, RUN_ID, owner_id="effect-attestation-owner")
    draft = AttestationDraft(
        action="promote",
        subject=ComponentProofSubject(
            component="test/effect-authority",
            version=digest("component", 1, {"effect-authority": True}),
            baseline_version=None,
        ),
        checks=(
            CheckResult(
                name="effect-authority",
                status="passed",
                detail="test authority",
                elapsed_s=0.0,
            ),
        ),
        check_set_hash=digest("check-set", 1, {"effect-authority": True}),
        manifest_hash=MANIFEST_HASH,
    )
    authority = journal.mint_policy_attestation(draft)
    request = EffectRequest(
        run_id=RUN_ID,
        manifest_hash=MANIFEST_HASH,
        path=PATH,
        kind="announce",
        subject=SUBJECT,
        idempotency_key=idempotency_key(MANIFEST_HASH, PATH, "announce", SUBJECT),
        attestation_id=authority.attestation_id,
    )
    assert journal.record_effect_prepared(lease, request) == request
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM attestations WHERE attestation_id = ?",
            (authority.attestation_id,),
        )
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE family IN ('attestation', 'legacy_attestation_m1_m2')"
            " AND fact_key = ?",
            (authority.attestation_id,),
        )

    clock.refuse = True
    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        journal.load_attestation(authority.attestation_id)
    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        journal.mint_policy_attestation(draft)
    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        SqliteJournal(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attestations").fetchone() == (0,)
        assert connection.execute(
            "SELECT idempotency_key FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        ).fetchone() == (str(request.idempotency_key),)


def test_schema_7_reopen_refuses_an_outcome_event_without_its_effect(
    tmp_path: Path,
) -> None:
    journal, _clock, request, lease, database = _prepared(tmp_path)
    journal.record_effect_outcome(
        lease,
        request,
        _receipt(request),
        "EffectCommitted",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        )
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE family = 'effect_preparation' AND fact_key = ?",
            (str(request.idempotency_key),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"outcome event.*no exact retained effect"):
        SqliteJournal(database)


def test_a_current_outcome_cannot_masquerade_as_opaque_history(
    tmp_path: Path,
) -> None:
    journal, _clock, request, lease, database = _prepared(tmp_path)
    journal.record_effect_outcome(
        lease,
        request,
        _receipt(request),
        "EffectCommitted",
    )
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        outcome = connection.execute(
            "SELECT outcome_run_id, outcome_event_seq FROM effects"
            " WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        ).fetchone()
        assert outcome is not None
        outcome_key = event_fact_key(outcome["outcome_run_id"], outcome["outcome_event_seq"])
        connection.execute(
            "UPDATE events SET payload = ? WHERE run_id = ? AND seq = ?",
            (
                canonical_json({"kind": request.kind}),
                outcome["outcome_run_id"],
                outcome["outcome_event_seq"],
            ),
        )
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE family = 'event' AND fact_key = ?",
            (outcome_key,),
        )
        event_row = connection.execute(
            "SELECT * FROM events WHERE run_id = ? AND seq = ?",
            (outcome["outcome_run_id"], outcome["outcome_event_seq"]),
        ).fetchone()
        assert event_row is not None
        seal_event(connection, event_row)
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE family = 'effect_preparation' AND fact_key = ?",
            (str(request.idempotency_key),),
        )
        connection.execute(
            "DELETE FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="current effect outcome event"):
        SqliteJournal(database)


def test_a_relocated_preparation_fails_closed_for_both_effect_keys(
    tmp_path: Path,
) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    foreign_key = digest("idempotency", 1, {"relocated": True})
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE effects SET idempotency_key = ? WHERE idempotency_key = ?",
            (str(foreign_key), str(request.idempotency_key)),
        )
        connection.commit()
    clock.refuse = True

    with pytest.raises(JournalDamaged, match="effect"):
        journal.receipt_for(request.idempotency_key)
    with pytest.raises(JournalDamaged, match="effect"):
        journal.receipt_for(foreign_key)
    with pytest.raises(JournalDamaged, match="effect"):
        journal.record_effect_prepared(lease, request)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone() == (1,)


def test_a_current_outcome_event_cannot_outlive_its_effect_row(tmp_path: Path) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    journal.record_effect_outcome(lease, request, _receipt(request), "EffectCommitted")
    fence = journal.max_event_seq(RUN_ID)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        )
        connection.commit()
    clock.refuse = True

    with pytest.raises(JournalDamaged, match="outcome proof without its row"):
        journal.receipt_for(request.idempotency_key)
    with pytest.raises(JournalDamaged, match="outcome proof without its row"):
        journal.record_effect_prepared(lease, request)
    assert journal.max_event_seq(RUN_ID) == fence


def test_a_terminal_effect_cannot_be_erased_back_to_prepared(tmp_path: Path) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    journal.record_effect_outcome(lease, request, _receipt(request), "EffectCommitted")
    fence = journal.max_event_seq(RUN_ID)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE effects SET receipt_json = NULL, receipted_at = NULL,"
            " outcome_run_id = NULL, outcome_event_seq = NULL"
            " WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        )
        connection.commit()
    clock.refuse = True

    with pytest.raises(JournalDamaged, match="prepared lifecycle has terminal proof"):
        journal.receipt_for(request.idempotency_key)
    with pytest.raises(JournalDamaged, match="prepared lifecycle has terminal proof"):
        journal.record_effect_prepared(lease, request)
    assert journal.max_event_seq(RUN_ID) == fence


def test_a_prepared_effect_cannot_fabricate_a_terminal_receipt(tmp_path: Path) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    receipt = _receipt(request)
    fence = journal.max_event_seq(RUN_ID)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE effects SET receipt_json = ?, receipted_at = ?"
            " WHERE idempotency_key = ?",
            (
                receipt.model_dump_json(),
                datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                str(request.idempotency_key),
            ),
        )
        connection.commit()
    clock.refuse = True

    with pytest.raises(JournalDamaged, match="terminal lifecycle has no exact event pointer"):
        journal.receipt_for(request.idempotency_key)
    with pytest.raises(JournalDamaged, match="terminal lifecycle has no exact event pointer"):
        journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    assert journal.max_event_seq(RUN_ID) == fence


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("kind", "redirected"),
        ("idempotency_key", str(digest("idempotency", 1, {"foreign": True}))),
        ("request_hash", str(digest("effect-request", 1, {"foreign": True}))),
        ("receipt_hash", str(digest("effect-receipt", 1, {"foreign": True}))),
    ),
)
def test_a_current_effect_event_binds_every_outcome_identity(
    field: str,
    replacement: str,
    tmp_path: Path,
) -> None:
    journal, clock, request, lease, database = _prepared(tmp_path)
    receipt = _receipt(request)
    journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    fence = journal.max_event_seq(RUN_ID)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT payload FROM events WHERE kind = 'EffectCommitted'"
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload[field] = replacement
        connection.execute(
            "UPDATE events SET payload = ? WHERE kind = 'EffectCommitted'",
            (json.dumps(payload),),
        )
        connection.commit()
    clock.refuse = True

    with pytest.raises(JournalDamaged, match=r"exact outcome event|positive seal"):
        journal.receipt_for(request.idempotency_key)
    with pytest.raises(JournalDamaged, match=r"exact outcome event|positive seal"):
        journal.record_effect_outcome(lease, request, receipt, "EffectCommitted")
    # The corrupted event intentionally has no public projection. Inspect the
    # allocation scalar directly to prove neither refused retry advanced it.
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT next_event_seq FROM runs WHERE run_id = ?",
            (str(RUN_ID),),
        ).fetchone() == (fence,)


def test_v6_terminal_effect_is_sealed_and_never_healed(tmp_path: Path) -> None:
    _journal, clock, request, _lease, database = _prepared(tmp_path)
    receipt = _receipt(request)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE effects SET receipt_json = ?, receipted_at = ?"
            " WHERE idempotency_key = ?",
            (
                receipt.model_dump_json(),
                datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                str(request.idempotency_key),
            ),
        )
        connection.commit()
    _downgrade_effect_table_to_v6(database)

    migrated = SqliteJournal(database, now_fn=clock.now)
    assert migrated.receipt_for(request.idempotency_key) == receipt
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE effects SET receipted_at = ? WHERE idempotency_key = ?",
            (datetime(2026, 1, 2, tzinfo=UTC).isoformat(), str(request.idempotency_key)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="terminal seal"):
        migrated.receipt_for(request.idempotency_key)


def test_v6_prepared_effect_closes_with_current_exact_provenance(tmp_path: Path) -> None:
    _journal, clock, request, lease, database = _prepared(tmp_path)
    _downgrade_effect_table_to_v6(database)
    migrated = SqliteJournal(database, now_fn=clock.now)
    receipt = _receipt(request)

    assert (
        migrated.record_effect_outcome(lease, request, receipt, "EffectCommitted")
        == "recorded"
    )
    assert migrated.receipt_for(request.idempotency_key) == receipt
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT outcome_run_id, outcome_event_seq FROM effects"
        ).fetchone()
        seal_count = connection.execute(
            "SELECT COUNT(*) FROM legacy_effect_seals"
        ).fetchone()[0]
    assert row == (str(RUN_ID), 2)
    assert seal_count == 0


@pytest.mark.parametrize("damage", ("seal_table", "outcome_column"))
def test_schema_7_never_reconstructs_erased_effect_provenance(
    damage: str,
    tmp_path: Path,
) -> None:
    _journal, clock, _request, _lease, database = _prepared(tmp_path)
    with sqlite3.connect(database) as connection:
        if damage == "seal_table":
            connection.execute("DROP TABLE legacy_effect_seals")
        else:
            connection.execute("ALTER TABLE effects DROP COLUMN outcome_event_seq")

    with pytest.raises(
        JournalDamaged,
        match=r"(?:effect outcome provenance is missing|"
        r"durable tables are missing: legacy_effect_seals)",
    ):
        SqliteJournal(database, now_fn=clock.now)

    with sqlite3.connect(database) as connection:
        if damage == "seal_table":
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table'"
                " AND name = 'legacy_effect_seals'"
            ).fetchone() is None
        else:
            assert "outcome_event_seq" not in {
                row[1] for row in connection.execute("PRAGMA table_info(effects)")
            }


@pytest.mark.parametrize("damage", ("orphan", "prepared"))
def test_schema_7_reopen_refuses_ineligible_legacy_effect_seals(
    damage: str,
    tmp_path: Path,
) -> None:
    _journal, clock, request, _lease, database = _prepared(tmp_path)
    with sqlite3.connect(database) as connection:
        if damage == "orphan":
            key = str(digest("idempotency", 1, {"orphan": True}))
        else:
            key = str(request.idempotency_key)
        connection.execute(
            "INSERT INTO legacy_effect_seals"
            " (idempotency_key, terminal_fact_hash) VALUES (?, ?)",
            (key, str(digest("legacy-effect-terminal-seal", 1, {"forged": damage}))),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="effect seal inventory"):
        SqliteJournal(database, now_fn=clock.now)


def test_schema_7_reopen_refuses_a_missing_legacy_effect_seal(
    tmp_path: Path,
) -> None:
    _journal, clock, request, _lease, database = _prepared(tmp_path)
    receipt = _receipt(request)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE effects SET receipt_json = ?, receipted_at = ?"
            " WHERE idempotency_key = ?",
            (
                receipt.model_dump_json(),
                datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                str(request.idempotency_key),
            ),
        )
        connection.commit()
    _downgrade_effect_table_to_v6(database)
    SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM legacy_effect_seals WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="effect seal inventory"):
        SqliteJournal(database, now_fn=clock.now)


def test_a_partly_climbed_v6_effect_schema_reconciles_only_in_migration(
    tmp_path: Path,
) -> None:
    _journal, clock, request, _lease, database = _prepared(tmp_path)
    receipt = _receipt(request)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE effects SET receipt_json = ?, receipted_at = ?"
            " WHERE idempotency_key = ?",
            (
                receipt.model_dump_json(),
                datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                str(request.idempotency_key),
            ),
        )
    _downgrade_effect_table_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("ALTER TABLE effects ADD COLUMN outcome_run_id TEXT")
        connection.execute(
            "CREATE TABLE legacy_effect_seals ("
            " idempotency_key TEXT PRIMARY KEY, terminal_fact_hash TEXT NOT NULL)"
        )
        row = connection.execute("SELECT * FROM effects").fetchone()
        assert row is not None
        connection.execute(
            "INSERT INTO legacy_effect_seals VALUES (?, ?)",
            (str(request.idempotency_key), str(legacy_effect_seal(row))),
        )

    migrated = SqliteJournal(database, now_fn=clock.now)
    assert migrated.receipt_for(request.idempotency_key) == receipt
    with sqlite3.connect(database) as connection:
        assert {row[1] for row in connection.execute("PRAGMA table_info(effects)")} >= {
            "outcome_run_id",
            "outcome_event_seq",
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_effect_seals"
        ).fetchone() == (1,)


def test_v6_migration_refuses_current_provenance_on_a_prepared_effect(
    tmp_path: Path,
) -> None:
    _journal, clock, request, _lease, database = _prepared(tmp_path)
    _downgrade_effect_table_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE effects ADD COLUMN outcome_run_id TEXT")
        connection.execute("ALTER TABLE effects ADD COLUMN outcome_event_seq INTEGER")
        connection.execute(
            "UPDATE effects SET outcome_run_id = ?, outcome_event_seq = 99"
            " WHERE idempotency_key = ?",
            (str(RUN_ID), str(request.idempotency_key)),
        )
        connection.execute(
            "CREATE TABLE legacy_effect_seals ("
            " idempotency_key TEXT PRIMARY KEY, terminal_fact_hash TEXT NOT NULL)"
        )

    with pytest.raises(JournalDamaged, match="carries current provenance"):
        SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert connection.execute(
            "SELECT outcome_run_id, outcome_event_seq FROM effects"
        ).fetchone() == (str(RUN_ID), 99)


def test_v6_migration_refuses_an_orphan_legacy_effect_seal_atomically(
    tmp_path: Path,
) -> None:
    _journal, clock, _request, _lease, database = _prepared(tmp_path)
    _downgrade_effect_table_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE legacy_effect_seals ("
            " idempotency_key TEXT PRIMARY KEY, terminal_fact_hash TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO legacy_effect_seals VALUES (?, ?)",
            ("sha256:" + "1" * 64, str(digest("orphan-effect-seal", 1, {}))),
        )

    with pytest.raises(JournalDamaged, match="effect seal inventory"):
        SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_effect_seals"
        ).fetchone() == (1,)
        assert "outcome_run_id" not in {
            row[1] for row in connection.execute("PRAGMA table_info(effects)")
        }
