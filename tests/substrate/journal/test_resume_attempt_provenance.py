"""An explicit attempt receipt resolves to one exact durable resume command."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6
from tests.run_worlds import create_test_run

from constructicon.core.address import RunId
from constructicon.core.control import (
    OPERATE_SCOPE,
    RESUMABLE_RUN_STATUSES,
    AuthenticatedActor,
    CommandClaim,
    CommandRecord,
    ControlCode,
    ControlRejected,
    HistoricalResumePlanEvidence,
    ResumeCommandPlan,
    StoredResumeCommandPlan,
    command_id_for,
    command_request_hash,
    resume_attempt_kind,
    validated_resume_attempt_command,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import canonical_json
from constructicon.core.run import TERMINAL_STATUS_EVENTS, AttemptCause, RunStatus
from constructicon.substrate.journal._sqlite_commands import (
    RESUME_PLAN_ERA_FACT_FAMILY,
    command_claim_fact_hash,
    command_plan_fact_hash,
    command_terminal_fact_hash,
    resume_plan_era_fact_hash,
)
from constructicon.substrate.journal._sqlite_execution_facts import (
    RESUME_ATTEMPT_FACT_FAMILY,
    event_fact_hash,
)
from constructicon.substrate.journal._sqlite_runs import RUN_LIFECYCLE_ANOMALY
from constructicon.substrate.journal.sqlite import SqliteJournal

ACTOR = AuthenticatedActor(
    actor_id="static:resume-provenance",
    auth_method="static",
    scopes=frozenset({OPERATE_SCOPE}),
)


def _resume_command_record(
    *,
    run_id: RunId,
    plan: object,
) -> CommandRecord:
    request = {"run_id": str(run_id)}
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return CommandRecord(
        command_id="cmd-l0-resume-attempt",
        actor=ACTOR,
        operation="runs_resume",
        idempotency_key="l0-resume-attempt",
        request_hash=command_request_hash(request),
        request=request,
        state="prepared",
        plan=plan,
        response=None,
        owner_id="test:l0",
        owner_epoch=1,
        lease_expires_at=now + timedelta(seconds=30),
        created_at=now,
        updated_at=now,
        completed_at=None,
    )


@pytest.mark.parametrize(
    ("baseline", "baseline_kind", "status", "event_kind", "lawful"),
    (
        (0, None, RunStatus.PENDING, "RunStarted", True),
        (0, None, RunStatus.RUNNING, "RunReclaimed", False),
        (2, "RunFailed", RunStatus.FAILED, "RunResumed", True),
        (2, "RunParked", RunStatus.PARKED, "RunResumed", True),
        (2, "RunFailed", RunStatus.PARKED, "RunResumed", False),
        (2, "RunSucceeded", RunStatus.RUNNING, "RunReclaimed", False),
        (2, "RunCancelled", RunStatus.RUNNING, "RunReclaimed", False),
    ),
)
def test_l0_attempt_law_derives_status_from_the_exact_fence(
    baseline: int,
    baseline_kind: str | None,
    status: RunStatus,
    event_kind: str,
    lawful: bool,
) -> None:
    run_id = RunId("run-l0-resume-attempt")
    record = _resume_command_record(
        run_id=run_id,
        plan=StoredResumeCommandPlan(
            plan=ResumeCommandPlan(
                run_id=run_id,
                baseline_event_seq=baseline,
                submitted_status=status,
                terminal_rejection_policy="exact-v1",
            )
        ).model_dump(mode="json"),
    )
    def action() -> object:
        return validated_resume_attempt_command(
            record,
            run_id=run_id,
            event_seq=baseline + 1,
            event_kind=event_kind,
            baseline_event_kind=baseline_kind,
        )
    if lawful:
        assert action() is not None
    else:
        with pytest.raises(JournalDamaged):
            action()


def test_l0_resumable_statuses_are_exactly_the_attempt_kind_domain() -> None:
    assert frozenset(
        {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.FAILED, RunStatus.PARKED}
    ) == RESUMABLE_RUN_STATUSES
    for status in RunStatus:
        if status in RESUMABLE_RUN_STATUSES:
            assert resume_attempt_kind(status) in {
                "RunStarted",
                "RunResumed",
                "RunReclaimed",
            }
        else:
            with pytest.raises(ValueError, match="is not resumable"):
                resume_attempt_kind(status)


@pytest.mark.parametrize("kind", ("resume_command", "channel_reply"))
def test_l0_attempt_cause_has_one_lossless_payload_vocabulary(
    kind: Literal["resume_command", "channel_reply"],
) -> None:
    cause = AttemptCause(kind=kind, id="cause-1")
    assert AttemptCause.from_payload({"attempt": 1, **cause.payload()}) == cause
    with pytest.raises(ValueError, match="more than one cause"):
        AttemptCause.from_payload(
            {
                "resume_command_id": "command-1",
                "reply_message_id": "reply-1",
            }
        )


@pytest.mark.parametrize("identity", ("", " surrounded "))
def test_l0_attempt_cause_refuses_noncanonical_identity(identity: str) -> None:
    with pytest.raises(ValueError, match="non-empty and canonical"):
        AttemptCause(kind="resume_command", id=identity)


def test_sqlite_lifecycle_predicate_matches_the_complete_l0_terminal_map() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            next_event_seq INTEGER NOT NULL
        );
        CREATE TABLE events (
            run_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            kind TEXT NOT NULL
        );
        """
    )
    for status, expected_kind in TERMINAL_STATUS_EVENTS.items():
        for observed_kind in TERMINAL_STATUS_EVENTS.values():
            connection.execute("DELETE FROM events")
            connection.execute("DELETE FROM runs")
            connection.execute(
                "INSERT INTO runs(run_id, status, next_event_seq) VALUES (?, ?, 1)",
                ("run-terminal-map", status.value),
            )
            connection.execute(
                "INSERT INTO events(run_id, seq, kind) VALUES (?, 1, ?)",
                ("run-terminal-map", observed_kind),
            )
            row = connection.execute(
                "SELECT ("
                + RUN_LIFECYCLE_ANOMALY
                + ") FROM runs AS r LEFT JOIN events AS e"
                " ON e.run_id = r.run_id AND e.seq = r.next_event_seq"
            ).fetchone()
            assert row is not None
            assert bool(row[0]) is (observed_kind != expected_kind)


def test_l0_attempt_law_never_attributes_an_unfenced_raw_plan() -> None:
    run_id = RunId("run-l0-unfenced-resume")
    record = _resume_command_record(run_id=run_id, plan={"run_id": str(run_id)})
    with pytest.raises(JournalDamaged, match="has no attempt fence"):
        validated_resume_attempt_command(
            record,
            run_id=run_id,
            event_seq=1,
            event_kind="RunStarted",
        )


def _prepare_attempt(
    database: Path,
    *,
    suffix: str,
    operation: str = "runs_resume",
    planned_run_id: RunId | None = None,
    baseline_event_seq: int = 0,
    submitted_status: RunStatus = RunStatus.PENDING,
) -> tuple[RunId, str]:
    journal = SqliteJournal(database)
    run_id = RunId(f"run-resume-provenance-{suffix}")
    create_test_run(journal, run_id)
    request = {"run_id": str(run_id)}
    claimed = journal.claim_command(
        actor=ACTOR,
        operation=operation,
        idempotency_key=f"resume-provenance-{suffix}",
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:resume-provenance",
        ttl_s=30,
    )
    assert claimed.claim is not None
    claim = claimed.claim
    if operation == "runs_resume":
        plan: object = StoredResumeCommandPlan(
            plan=ResumeCommandPlan(
                run_id=planned_run_id or run_id,
                baseline_event_seq=baseline_event_seq,
                submitted_status=submitted_status,
                terminal_rejection_policy="exact-v1",
            )
        ).model_dump(mode="json")
    else:
        # A valid immutable command fact, but not authority for an attempt.
        plan = {"kind": "cancel", "run_id": str(run_id)}
    journal.store_command_plan(claim, plan)
    lease = journal.claim_run(run_id, owner_id="test:attempt-worker", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
        payload={"resume_command_id": claim.command_id},
    )
    return run_id, claim.command_id


def _rewrite_primary_seal(
    connection: sqlite3.Connection,
    *,
    family: Literal["command_claim", "command_plan", "command_terminal", "event"],
    fact_key: str,
    fact_hash: str,
) -> None:
    connection.execute(
        "UPDATE durable_fact_seals SET fact_hash = ?"
        " WHERE family = ? AND fact_key = ?",
        (fact_hash, family, fact_key),
    )


def _prepare_other_command(
    database: Path,
    *,
    run_id: RunId,
    operation: Literal["runs_cancel", "runs_resume"],
    suffix: str,
) -> str:
    journal = SqliteJournal(database)
    request = {"run_id": str(run_id)}
    claimed = journal.claim_command(
        actor=ACTOR,
        operation=operation,
        idempotency_key=suffix,
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:other-command",
        ttl_s=30,
    )
    assert claimed.claim is not None
    if operation == "runs_resume":
        plan: object = StoredResumeCommandPlan(
            plan=ResumeCommandPlan(
                run_id=run_id,
                baseline_event_seq=0,
                submitted_status=RunStatus.PENDING,
                terminal_rejection_policy="exact-v1",
            )
        ).model_dump(mode="json")
    else:
        plan = {"kind": "cancel", "run_id": str(run_id)}
    journal.store_command_plan(claimed.claim, plan)
    return claimed.claim.command_id


def _prepare_failed_attempt(database: Path, *, suffix: str) -> tuple[RunId, str]:
    journal = SqliteJournal(database)
    run_id = RunId(f"run-resume-provenance-{suffix}")
    create_test_run(journal, run_id)
    initial = journal.claim_run(run_id, owner_id="test:initial-attempt", ttl_s=30)
    journal.transition_run(
        initial,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        initial,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED,
        event_kind="RunFailed",
    )
    journal.release_run(initial)
    request = {"run_id": str(run_id)}
    claimed = journal.claim_command(
        actor=ACTOR,
        operation="runs_resume",
        idempotency_key=f"resume-provenance-{suffix}",
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:resume-provenance",
        ttl_s=30,
    )
    assert claimed.claim is not None
    journal.store_command_plan(
        claimed.claim,
        StoredResumeCommandPlan(
            plan=ResumeCommandPlan(
                run_id=run_id,
                baseline_event_seq=2,
                submitted_status=RunStatus.FAILED,
                terminal_rejection_policy="exact-v1",
            )
        ).model_dump(mode="json"),
    )
    resumed = journal.claim_run(run_id, owner_id="test:resumed-attempt", ttl_s=30)
    journal.transition_run(
        resumed,
        expected=frozenset({RunStatus.FAILED}),
        target=RunStatus.RUNNING,
        event_kind="RunResumed",
        payload={"resume_command_id": claimed.claim.command_id},
    )
    return run_id, claimed.claim.command_id


@pytest.mark.parametrize(
    "mutation",
    ("missing_command", "wrong_operation", "wrong_run", "wrong_fence", "wrong_status"),
)
def test_current_attempt_writer_requires_its_exact_resume_command(
    mutation: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"current-{mutation}.db"
    foreign_run = RunId("run-resume-provenance-foreign")
    operation = "runs_cancel" if mutation == "wrong_operation" else "runs_resume"
    if mutation != "missing_command":
        with pytest.raises(JournalDamaged, match=r"resume command|attempt event|attempt fence"):
            _prepare_attempt(
                database,
                suffix=mutation,
                operation=operation,
                planned_run_id=foreign_run if mutation == "wrong_run" else None,
                baseline_event_seq=1 if mutation == "wrong_fence" else 0,
                submitted_status=(
                    RunStatus.FAILED if mutation == "wrong_status" else RunStatus.PENDING
                ),
            )
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM events").fetchone() == (0,)
        return

    run_id, command_id = _prepare_attempt(database, suffix=mutation)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM commands WHERE command_id = ?", (command_id,))
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE family IN ('command_claim', 'command_plan') AND fact_key = ?",
            (command_id,),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=r"(?:resume command|attempt event|cannot authorize|dependent durable fact)",
    ):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT payload FROM events WHERE run_id = ? AND seq = 1",
            (str(run_id),),
        ).fetchone() is not None


def test_attempt_writer_refuses_two_causal_facts_atomically(tmp_path: Path) -> None:
    database = tmp_path / "two-attempt-causes.db"
    journal = SqliteJournal(database)
    run_id = RunId("run-two-attempt-causes")
    create_test_run(journal, run_id)
    command_id = _prepare_other_command(
        database,
        run_id=run_id,
        operation="runs_resume",
        suffix="two-attempt-causes",
    )
    lease = journal.claim_run(run_id, owner_id="test:two-causes", ttl_s=30)
    with pytest.raises(JournalDamaged, match="contradictory cause facts"):
        journal.transition_run(
            lease,
            expected=frozenset({RunStatus.PENDING}),
            target=RunStatus.RUNNING,
            event_kind="RunStarted",
            payload={
                "resume_command_id": command_id,
                "reply_message_id": "sha256:" + "f" * 64,
            },
        )
    assert journal.max_event_seq(run_id) == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals WHERE family IN ('event', ?)",
            (RESUME_ATTEMPT_FACT_FAMILY,),
        ).fetchone() == (0,)


@pytest.mark.parametrize("downgrade", ("raw", "weak_typed"))
def test_current_attempt_cannot_masquerade_as_a_historical_plan_era(
    downgrade: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / "current-downgrade.db"
    run_id, command_id = _prepare_attempt(database, suffix="current-downgrade")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        if downgrade == "raw":
            rewritten = {"run_id": str(run_id), "baseline_event_seq": 0}
        else:
            stored = connection.execute(
                "SELECT plan_json FROM commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            assert stored is not None and isinstance(stored[0], str)
            rewritten = json.loads(stored[0])
            del rewritten["plan"]["terminal_rejection_policy"]
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(rewritten), command_id),
        )
        row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None
        _rewrite_primary_seal(
            connection,
            family="command_plan",
            fact_key=command_id,
            fact_hash=str(command_plan_fact_hash(row)),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=r"resume_plan_pre_v7.*no positive seal",
    ):
        SqliteJournal(database)


def test_current_exact_plan_refuses_even_valid_historical_evidence(
    tmp_path: Path,
) -> None:
    database = tmp_path / "current-with-historical-evidence.db"
    _run_id, command_id = _prepare_attempt(database, suffix="current-with-evidence")
    journal = SqliteJournal(database)
    evidence = HistoricalResumePlanEvidence(
        command_id=command_id,
        phase_at_migration="prepared",
    )
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None
        connection.execute(
            "INSERT INTO durable_fact_seals (family, fact_key, selector, fact_hash)"
            " VALUES (?, ?, ?, ?)",
            (
                RESUME_PLAN_ERA_FACT_FAMILY,
                command_id,
                canonical_json(evidence.model_dump(mode="json")),
                str(resume_plan_era_fact_hash(row, evidence=evidence)),
            ),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="carries historical era evidence"):
        journal.command(command_id)


def test_resume_plan_era_inventory_refuses_an_orphan_marker(tmp_path: Path) -> None:
    database = tmp_path / "orphan-resume-plan-era.db"
    SqliteJournal(database)
    command_id = "cmd-orphan-resume-plan-era"
    evidence = HistoricalResumePlanEvidence(
        command_id=command_id,
        phase_at_migration="prepared",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO durable_fact_seals (family, fact_key, selector, fact_hash)"
            " VALUES (?, ?, ?, ?)",
            (
                RESUME_PLAN_ERA_FACT_FAMILY,
                command_id,
                canonical_json(evidence.model_dump(mode="json")),
                str(command_request_hash({"orphan": command_id})),
            ),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match="resume-plan era seal inventory has an orphan or missing fact",
    ):
        SqliteJournal(database)


def test_attempt_relationship_cannot_be_repointed_to_an_equally_valid_command(
    tmp_path: Path,
) -> None:
    database = tmp_path / "current-repoint.db"
    run_id, _winner = _prepare_attempt(database, suffix="current-repoint")
    contender = _prepare_other_command(
        database,
        run_id=run_id,
        operation="runs_resume",
        suffix="equally-valid-contender",
    )
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "UPDATE events SET payload = ? WHERE run_id = ? AND seq = 1",
            (canonical_json({"resume_command_id": contender}), str(run_id)),
        )
        event_row = connection.execute(
            "SELECT * FROM events WHERE run_id = ? AND seq = 1",
            (str(run_id),),
        ).fetchone()
        assert event_row is not None
        _rewrite_primary_seal(
            connection,
            family="event",
            fact_key=canonical_json({"run_id": str(run_id), "seq": 1}),
            fact_hash=str(event_fact_hash(event_row)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"resume_attempt.*(?:key|selector)"):
        SqliteJournal(database)


def test_point_reads_refuse_an_event_whose_attempt_claim_was_erased(
    tmp_path: Path,
) -> None:
    database = tmp_path / "erased-event-claim.db"
    run_id, _command_id = _prepare_attempt(database, suffix="erased-event-claim")
    journal = SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "UPDATE events SET payload = ? WHERE run_id = ? AND seq = 1",
            (canonical_json({}), str(run_id)),
        )
        row = connection.execute(
            "SELECT * FROM events WHERE run_id = ? AND seq = 1",
            (str(run_id),),
        ).fetchone()
        assert row is not None
        _rewrite_primary_seal(
            connection,
            family="event",
            fact_key=canonical_json({"run_id": str(run_id), "seq": 1}),
            fact_hash=str(event_fact_hash(row)),
        )
        connection.commit()

    for read in (
        lambda: journal.event(run_id, 1),
        lambda: journal.events(run_id, after_seq=0, limit=10),
        lambda: journal.run_record(run_id),
    ):
        with pytest.raises(JournalDamaged, match="lost its resume-attempt claim"):
            read()


@pytest.mark.parametrize("erase_relationship", (False, True))
def test_resume_attempt_prevents_its_command_from_rejecting(
    erase_relationship: bool,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"reject-after-attempt-{erase_relationship}.db"
    _run_id, command_id = _prepare_attempt(
        database,
        suffix=f"reject-after-attempt-{erase_relationship}",
    )
    journal = SqliteJournal(database)
    record = journal.command(command_id)
    assert (
        record is not None
        and record.owner_id is not None
        and record.lease_expires_at is not None
    )
    claim = CommandClaim(
        command_id=command_id,
        actor_id=record.actor.actor_id,
        operation=record.operation,
        owner_id=record.owner_id,
        epoch=record.owner_epoch,
        expires_at=record.lease_expires_at,
    )
    if erase_relationship:
        with sqlite3.connect(database) as connection:
            connection.execute(
                "DELETE FROM durable_fact_seals WHERE family = ? AND fact_key = ?",
                (RESUME_ATTEMPT_FACT_FAMILY, command_id),
            )
            connection.commit()

    with pytest.raises(JournalDamaged, match=r"resume attempt|positive seal"):
        journal.reject_command(claim, {"status": "rejected"})
    retained = journal.command(command_id)
    assert retained is not None
    assert retained.state == "prepared"
    assert retained.response is None


def test_attempt_relationship_binds_the_exact_baseline_event(
    tmp_path: Path,
) -> None:
    database = tmp_path / "baseline-rewrite.db"
    run_id, command_id = _prepare_failed_attempt(database, suffix="baseline-rewrite")
    journal = SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "UPDATE events SET kind = 'RunParked' WHERE run_id = ? AND seq = 2",
            (str(run_id),),
        )
        row = connection.execute(
            "SELECT * FROM events WHERE run_id = ? AND seq = 2",
            (str(run_id),),
        ).fetchone()
        assert row is not None
        _rewrite_primary_seal(
            connection,
            family="event",
            fact_key=canonical_json({"run_id": str(run_id), "seq": 2}),
            fact_hash=str(event_fact_hash(row)),
        )
        command_row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert command_row is not None and isinstance(command_row["plan_json"], str)
        plan = json.loads(command_row["plan_json"])
        plan["plan"]["submitted_status"] = "parked"
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(plan), command_id),
        )
        command_row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert command_row is not None
        _rewrite_primary_seal(
            connection,
            family="command_plan",
            fact_key=command_id,
            fact_hash=str(command_plan_fact_hash(command_row)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"resume_attempt.*positive seal"):
        journal.event(run_id, 3)


def _migrated_legacy_attempt(
    database: Path,
    *,
    suffix: str,
) -> tuple[RunId, str]:
    run_id, command_id = _prepare_attempt(database, suffix=suffix)
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (
                canonical_json({"run_id": str(run_id), "baseline_event_seq": 0}),
                command_id,
            ),
        )
        connection.commit()
    SqliteJournal(database)
    return run_id, command_id


def test_migrated_resume_projection_is_bounded_past_python_recursion_depth(
    tmp_path: Path,
) -> None:
    database = tmp_path / "bounded-resume-projection.db"
    journal = SqliteJournal(database)
    run_id = RunId("run-bounded-resume-projection")
    create_test_run(journal, run_id)
    _downgrade_v7_schema_to_v6(database)

    event_count = sys.getrecursionlimit() + 50
    now = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    actor_json = canonical_json(ACTOR.model_dump(mode="json"))
    commands: list[tuple[object, ...]] = []
    events: list[tuple[object, ...]] = []
    for seq in range(1, event_count + 1):
        key = f"bounded-resume-{seq}"
        command_id = command_id_for(ACTOR.actor_id, "runs_resume", key)
        request = {"run_id": str(run_id)}
        submitted_status = "pending" if seq == 1 else "running"
        commands.append(
            (
                command_id,
                ACTOR.actor_id,
                actor_json,
                "runs_resume",
                key,
                str(command_request_hash(request)),
                canonical_json(request),
                canonical_json(
                    {
                        "schema_version": 1,
                        "plan": {
                            "kind": "resume",
                            "policy": "resume-v1",
                            "run_id": str(run_id),
                            "baseline_event_seq": seq - 1,
                            "submitted_status": submitted_status,
                        },
                    }
                ),
                "prepared",
                None,
                "test:bounded-resume",
                1,
                datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                now,
                now,
                None,
            )
        )
        events.append(
            (
                str(run_id),
                seq,
                "RunStarted" if seq == 1 else "RunReclaimed",
                None,
                canonical_json({"resume_command_id": command_id}),
                now,
            )
        )

    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            commands,
        )
        connection.executemany(
            "INSERT INTO events(run_id, seq, kind, path_json, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            events,
        )
        connection.execute(
            "UPDATE runs SET status = 'running', next_event_seq = ? WHERE run_id = ?",
            (event_count, str(run_id)),
        )
        connection.commit()

    migrated = SqliteJournal(database)
    latest = migrated.event(run_id, event_count)
    assert latest is not None
    assert latest.kind == "RunReclaimed"
    assert latest.payload == {
        "resume_command_id": command_id_for(
            ACTOR.actor_id,
            "runs_resume",
            f"bounded-resume-{event_count}",
        )
    }


@pytest.mark.parametrize("shape", ("raw", "weak_typed"))
@pytest.mark.parametrize("phase", ("prepared", "terminal"))
def test_v6_migration_classifies_every_historical_resume_plan_era(
    shape: str,
    phase: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"plan-era-{shape}-{phase}.db"
    journal = SqliteJournal(database)
    run_id = RunId(f"run-plan-era-{shape}-{phase}")
    request = {"run_id": str(run_id)}
    claimed = journal.claim_command(
        actor=ACTOR,
        operation="runs_resume",
        idempotency_key=f"plan-era-{shape}-{phase}",
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:plan-era",
        ttl_s=30,
    )
    assert claimed.claim is not None
    current = StoredResumeCommandPlan(
        plan=ResumeCommandPlan(
            run_id=run_id,
            baseline_event_seq=0,
            submitted_status=RunStatus.PENDING,
            terminal_rejection_policy="exact-v1",
        )
    ).model_dump(mode="json")
    journal.store_command_plan(claimed.claim, current)
    if phase == "terminal":
        journal.complete_command(claimed.claim, {"historical": "response"})
    _downgrade_v7_schema_to_v6(database)
    if shape == "raw":
        historical: object = {"run_id": str(run_id), "baseline_event_seq": 0}
    else:
        historical = json.loads(canonical_json(current))
        del historical["plan"]["terminal_rejection_policy"]
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(historical), claimed.claim.command_id),
        )
        connection.commit()

    migrated = SqliteJournal(database)
    evidence = migrated.historical_resume_plan_evidence(claimed.claim.command_id)
    assert evidence is not None
    assert evidence.command_id == claimed.claim.command_id
    assert evidence.phase_at_migration == phase


@pytest.mark.parametrize("shape", ("raw", "weak_typed"))
def test_terminal_resume_era_binds_the_exact_migrated_response_bytes(
    shape: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"terminal-response-{shape}.db"
    journal = SqliteJournal(database)
    run_id = RunId(f"run-terminal-response-{shape}")
    request = {"run_id": str(run_id)}
    claimed = journal.claim_command(
        actor=ACTOR,
        operation="runs_resume",
        idempotency_key=f"terminal-response-{shape}",
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:terminal-response",
        ttl_s=30,
    )
    assert claimed.claim is not None
    current = StoredResumeCommandPlan(
        plan=ResumeCommandPlan(
            run_id=run_id,
            baseline_event_seq=0,
            submitted_status=RunStatus.PENDING,
            terminal_rejection_policy="exact-v1",
        )
    ).model_dump(mode="json")
    journal.store_command_plan(claimed.claim, current)
    original = ControlRejected.one_fault(
        ControlCode.RUN_NOT_RESUMABLE,
        "historical terminal refusal",
        "submit a fresh command",
    ).model_dump(mode="json")
    journal.reject_command(claimed.claim, original)
    _downgrade_v7_schema_to_v6(database)
    historical: object
    if shape == "raw":
        historical = {"run_id": str(run_id), "baseline_event_seq": 0}
    else:
        historical = json.loads(canonical_json(current))
        del historical["plan"]["terminal_rejection_policy"]
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(historical), claimed.claim.command_id),
        )
        connection.commit()

    migrated = SqliteJournal(database)
    replacement = ControlRejected.one_fault(
        ControlCode.RUN_NOT_RESUMABLE,
        "different but structurally valid historical refusal",
        "submit a different fresh command",
    ).model_dump(mode="json")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (canonical_json(replacement), claimed.claim.command_id),
        )
        row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (claimed.claim.command_id,),
        ).fetchone()
        assert row is not None
        _rewrite_primary_seal(
            connection,
            family="command_terminal",
            fact_key=claimed.claim.command_id,
            fact_hash=str(command_terminal_fact_hash(row)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"resume_plan_pre_v7.*positive seal"):
        migrated.command(claimed.claim.command_id)


@pytest.mark.parametrize("phase", ("prepared", "terminal"))
def test_v6_migration_classifies_raw_resume_rejection_plans(
    phase: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"raw-rejection-{phase}.db"
    journal = SqliteJournal(database)
    run_id = RunId(f"run-raw-rejection-{phase}")
    request = {"run_id": str(run_id)}
    claimed = journal.claim_command(
        actor=ACTOR,
        operation="runs_resume",
        idempotency_key=f"raw-rejection-{phase}",
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:raw-rejection",
        ttl_s=30,
    )
    assert claimed.claim is not None
    response = ControlRejected.one_fault(
        ControlCode.RUN_NOT_RESUMABLE,
        "historical refusal",
        "submit a fresh command",
    ).model_dump(mode="json")
    current = {
        "schema_version": 1,
        "plan": {
            "kind": "control_reject",
            "command_id": claimed.claim.command_id,
            "operation": "runs_resume",
            "request_hash": str(command_request_hash(request)),
            "response": response,
        },
    }
    journal.store_command_plan(claimed.claim, current)
    if phase == "terminal":
        journal.reject_command(claimed.claim, response)
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (
                canonical_json({"rejection": response}),
                claimed.claim.command_id,
            ),
        )
        connection.commit()

    migrated = SqliteJournal(database)
    evidence = migrated.historical_resume_plan_evidence(claimed.claim.command_id)
    assert evidence is not None
    assert evidence.phase_at_migration == phase


def test_current_raw_resume_rejection_cannot_masquerade_as_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "current-raw-rejection.db"
    journal = SqliteJournal(database)
    run_id = RunId("run-current-raw-rejection")
    request = {"run_id": str(run_id)}
    claimed = journal.claim_command(
        actor=ACTOR,
        operation="runs_resume",
        idempotency_key="current-raw-rejection",
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:current-raw-rejection",
        ttl_s=30,
    )
    assert claimed.claim is not None
    response = ControlRejected.one_fault(
        ControlCode.RUN_NOT_RESUMABLE,
        "current refusal",
        "submit a fresh command",
    ).model_dump(mode="json")
    journal.store_command_plan(
        claimed.claim,
        {
            "schema_version": 1,
            "plan": {
                "kind": "control_reject",
                "command_id": claimed.claim.command_id,
                "operation": "runs_resume",
                "request_hash": str(command_request_hash(request)),
                "response": response,
            },
        },
    )
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (
                canonical_json({"rejection": response}),
                claimed.claim.command_id,
            ),
        )
        row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (claimed.claim.command_id,),
        ).fetchone()
        assert row is not None
        _rewrite_primary_seal(
            connection,
            family="command_plan",
            fact_key=claimed.claim.command_id,
            fact_hash=str(command_plan_fact_hash(row)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"resume_plan_pre_v7.*no positive seal"):
        journal.command(claimed.claim.command_id)


def test_v6_migration_classifies_an_exact_legacy_attempt_relationship(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-migration.db"
    run_id, command_id = _migrated_legacy_attempt(database, suffix="legacy-migration")

    with sqlite3.connect(database) as connection:
        markers = connection.execute(
            "SELECT family, fact_key, selector FROM durable_fact_seals"
            " WHERE family IN (?, ?) ORDER BY family",
            (RESUME_PLAN_ERA_FACT_FAMILY, RESUME_ATTEMPT_FACT_FAMILY),
        ).fetchall()
    assert markers == [
        (
            RESUME_ATTEMPT_FACT_FAMILY,
            command_id,
            canonical_json({"run_id": str(run_id), "seq": 1}),
        ),
        (
            RESUME_PLAN_ERA_FACT_FAMILY,
            command_id,
            canonical_json(
                {
                    "command_id": command_id,
                    "phase_at_migration": "prepared",
                }
            ),
        ),
    ]
    SqliteJournal(database)


def test_v6_migration_refuses_an_unfenced_plan_with_an_attributed_attempt(
    tmp_path: Path,
) -> None:
    database = tmp_path / "unfenced-attributed-attempt.db"
    run_id, command_id = _prepare_attempt(database, suffix="unfenced-attributed")
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json({"run_id": str(run_id)}), command_id),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="has no attempt fence"):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (6,)


@pytest.mark.parametrize("mutation", ("missing_command", "wrong_operation"))
def test_v6_migration_refuses_a_resume_receipt_without_exact_authority(
    mutation: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"legacy-refusal-{mutation}.db"
    run_id, command_id = _prepare_attempt(
        database,
        suffix=f"legacy-refusal-{mutation}",
    )
    wrong_command_id = (
        _prepare_other_command(
            database,
            run_id=run_id,
            operation="runs_cancel",
            suffix="legacy-wrong-operation",
        )
        if mutation == "wrong_operation"
        else None
    )
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        if mutation == "missing_command":
            connection.execute("DELETE FROM commands WHERE command_id = ?", (command_id,))
        else:
            assert wrong_command_id is not None
            connection.execute(
                "UPDATE events SET payload = ? WHERE run_id = ? AND seq = 1",
                (
                    canonical_json({"resume_command_id": wrong_command_id}),
                    str(run_id),
                ),
            )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=r"(?:attempt event|cannot authorize|not a resume command)",
    ):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (6,)


@pytest.mark.parametrize("mutation", ("claim", "plan", "event"))
def test_legacy_attempt_marker_binds_the_exact_migrated_relationship(
    mutation: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"legacy-marker-{mutation}.db"
    run_id, command_id = _migrated_legacy_attempt(database, suffix=f"marker-{mutation}")

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        if mutation == "claim":
            row = connection.execute(
                "SELECT actor_json FROM commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            assert row is not None
            actor = json.loads(row["actor_json"])
            actor["display_name"] = "historically renamed"
            connection.execute(
                "UPDATE commands SET actor_json = ? WHERE command_id = ?",
                (canonical_json(actor), command_id),
            )
            command_row = connection.execute(
                "SELECT * FROM commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            assert command_row is not None
            _rewrite_primary_seal(
                connection,
                family="command_claim",
                fact_key=command_id,
                fact_hash=str(command_claim_fact_hash(command_row)),
            )
        elif mutation == "plan":
            connection.execute(
                "UPDATE commands SET plan_json = ? WHERE command_id = ?",
                (
                    canonical_json({"run_id": str(run_id)}),
                    command_id,
                ),
            )
            command_row = connection.execute(
                "SELECT * FROM commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            assert command_row is not None
            _rewrite_primary_seal(
                connection,
                family="command_plan",
                fact_key=command_id,
                fact_hash=str(command_plan_fact_hash(command_row)),
            )
        else:
            event_row = connection.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq = 1",
                (str(run_id),),
            ).fetchone()
            assert event_row is not None
            changed = datetime.fromisoformat(event_row["created_at"]).astimezone(UTC) + timedelta(
                seconds=1
            )
            connection.execute(
                "UPDATE events SET created_at = ? WHERE run_id = ? AND seq = 1",
                (changed.isoformat(), str(run_id)),
            )
            event_row = connection.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq = 1",
                (str(run_id),),
            ).fetchone()
            assert event_row is not None
            _rewrite_primary_seal(
                connection,
                family="event",
                fact_key=canonical_json({"run_id": str(run_id), "seq": 1}),
                fact_hash=str(event_fact_hash(event_row)),
            )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=r"(?:resume_plan_pre_v7|resume_attempt).*positive seal",
    ):
        SqliteJournal(database)
