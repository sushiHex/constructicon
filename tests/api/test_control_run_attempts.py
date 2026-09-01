"""A durable submission can authorize at most one run attempt."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.control import (
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    CommandClaim,
    ControlCode,
    ControlRejected,
    ResumeCommandPlan,
    RunSubmission,
    StoredResumeCommandPlan,
    command_id_for,
    command_request_hash,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import canonical_json
from constructicon.core.run import AttemptCause, ParkedUnit, RunStatus
from constructicon.runtime.walker import RunResult
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import (
    FakeClock,
    InjectedCrash,
    await_attempt_terminal,
    pipeline_graph,
)
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6

ACTOR = AuthenticatedActor(
    actor_id="static:attempt-fence",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
)
_POLICY_EXHAUSTED = ParkedUnit(
    path=ExecutionPath(scope=ScopePath(segments=("triage",))),
    reason="policy_exhausted",
    completed_iterations=1,
)
_PARKED_UNITS: dict[RunStatus, dict[str, Any]] = {
    RunStatus.FAILED: {},
    RunStatus.PARKED: {"parked": [_POLICY_EXHAUSTED.model_dump(mode="json")], "blocked": []},
}
TERMINAL_KINDS = {
    RunStatus.FAILED: "RunFailed",
    RunStatus.PARKED: "RunParked",
}


def _prepare_terminal(
    world: Any,
    journal: SqliteJournal,
    *,
    suffix: str,
    status: RunStatus,
) -> RunId:
    inputs = {"issue": {"title": suffix}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId(f"run-attempt-{suffix}")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    lease = journal.claim_run(run_id, owner_id=f"initial-{suffix}", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=status,
        event_kind=TERMINAL_KINDS[status],
        payload={"attempt": "initial", **_PARKED_UNITS[status]},
    )
    journal.release_run(lease)
    return run_id


def _install_terminal_worker(
    monkeypatch: pytest.MonkeyPatch,
    world: Any,
    journal: SqliteJournal,
    *,
    terminal_status: RunStatus,
) -> list[RunId]:
    attempts: list[RunId] = []

    async def terminal_worker(
        run_id: RunId,
        *,
        cancellation: str,
        expected_event_seq: int | None = None,
        expected_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> RunResult:
        assert cancellation == "abandon"
        attempt_number = len(attempts) + 1
        lease = journal.claim_run(
            run_id,
            owner_id=f"attempt-worker-{attempt_number}",
            ttl_s=30,
            expected_event_seq=expected_event_seq,
            expected_statuses=expected_statuses,
        )
        attempts.append(run_id)
        claimed = journal.run_record(run_id)
        assert claimed is not None
        journal.transition_run(
            lease,
            expected=frozenset({RunStatus.PENDING, RunStatus.FAILED, RunStatus.PARKED}),
            target=RunStatus.RUNNING,
            event_kind=("RunStarted" if claimed.status is RunStatus.PENDING else "RunResumed"),
            payload=(
                cause.payload() if cause is not None else None
            ),
        )
        journal.transition_run(
            lease,
            expected=frozenset({RunStatus.RUNNING}),
            target=terminal_status,
            event_kind=TERMINAL_KINDS[terminal_status],
            # A real park always records its units; a bare RunParked is a shape
            # the walker never writes.
            payload={"attempt": attempt_number, **_PARKED_UNITS[terminal_status]},
        )
        journal.release_run(lease)
        return RunResult(run_id=run_id, status=terminal_status, outputs={})

    monkeypatch.setattr(world, "_run_prepared", terminal_worker)
    return attempts


def _attempt_events(journal: SqliteJournal, run_id: RunId) -> tuple[str, ...]:
    return tuple(
        event.kind
        for event in journal.events(run_id, after_seq=0, limit=100)
        if event.kind in {"RunResumed", "RunFailed", "RunParked"}
    )


def _migrate_raw_resume_plan(
    db_path: Path,
    command_id: str,
    *,
    keep_fence: bool,
) -> None:
    """Model the exact schema-6 plan, then let migration seal that history."""

    _downgrade_v7_schema_to_v6(db_path)
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?", (command_id,)
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        plan = json.loads(row[0])
        assert isinstance(plan, dict)
        if "schema_version" in plan:
            typed = plan.get("plan")
            assert isinstance(typed, dict)
            plan = {"run_id": typed["run_id"]}
            if keep_fence:
                plan["baseline_event_seq"] = typed["baseline_event_seq"]
        elif not keep_fence:
            plan.pop("baseline_event_seq", None)
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (json.dumps(plan, sort_keys=True, separators=(",", ":")), command_id),
        )
        connection.commit()
    SqliteJournal(db_path)


def _damage_attempt_fence(db_path: Path, command_id: str) -> None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?", (command_id,)
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        plan = json.loads(row[0])
        assert isinstance(plan, dict)
        target = plan.get("plan") if "schema_version" in plan else plan
        assert isinstance(target, dict)
        target["baseline_event_seq"] = "damaged"
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (json.dumps(plan, sort_keys=True, separators=(",", ":")), command_id),
        )


def _damage_resume_recovery_selector(
    db_path: Path,
    command_id: str,
    mutation: Literal[
        "lifecycle",
        "operation",
        "timestamp_type",
        "timestamp_syntax",
    ],
) -> None:
    with sqlite3.connect(db_path) as connection:
        if mutation == "lifecycle":
            connection.execute(
                "UPDATE commands SET state = 'rejected' WHERE command_id = ?",
                (command_id,),
            )
        elif mutation == "operation":
            connection.execute(
                "UPDATE commands SET operation = 'runs_start' WHERE command_id = ?",
                (command_id,),
            )
        elif mutation == "timestamp_type":
            connection.execute(
                "UPDATE commands SET created_at = ? WHERE command_id = ?",
                (sqlite3.Binary(b"not-text"), command_id),
            )
        else:
            connection.execute(
                "UPDATE commands SET created_at = ? WHERE command_id = ?",
                ("2030-01-01 00:00:00+00:00", command_id),
            )


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.PARKED])
@pytest.mark.parametrize("legacy_plan", [False, True])
async def test_same_resume_command_replay_never_starts_a_second_attempt(
    status: RunStatus,
    legacy_plan: bool,
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix=f"resume-{status.value}",
        status=status,
    )
    attempts = _install_terminal_worker(monkeypatch, world, journal, terminal_status=status)
    host = RunHost(world, journal=journal, max_concurrency=1)
    control = ControlPlane(system=world, store=journal, run_host=host)
    baseline = journal.max_event_seq(run_id)

    first = await control.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key=f"resume-{status.value}",
    )
    assert isinstance(first, RunSubmission)
    terminal = await await_attempt_terminal(
        journal,
        run_id,
        baseline_event_seq=baseline,
        expected_resume_command_id=first.command.command_id,
    )
    assert terminal.kind == TERMINAL_KINDS[status]
    events_after_first = _attempt_events(journal, run_id)
    if legacy_plan:
        await control.shutdown()
        _migrate_raw_resume_plan(
            tmp_path / "journal.db",
            first.command.command_id,
            keep_fence=True,
        )
        host = RunHost(world, journal=journal, max_concurrency=1)
        control = ControlPlane(system=world, store=journal, run_host=host)

    replay = await control.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key=f"resume-{status.value}",
    )
    assert isinstance(replay, RunSubmission)
    assert replay.command.replayed is True
    for _ in range(20):
        await asyncio.sleep(0)

    assert attempts == [run_id]
    assert _attempt_events(journal, run_id) == events_after_first
    await control.shutdown()


async def test_resume_replay_after_completed_response_loss_starts_once(
    world: Any,
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix="resume-response-loss",
        status=RunStatus.FAILED,
    )
    attempts = _install_terminal_worker(
        monkeypatch, world, journal, terminal_status=RunStatus.FAILED
    )
    host = RunHost(world, journal=journal, max_concurrency=1)
    armed = True

    def crash(name: str) -> None:
        if armed and name == "runs_resume.after_command_completion":
            raise InjectedCrash(name)

    control = ControlPlane(
        system=world,
        store=journal,
        run_host=host,
        fault_probe=crash,
    )
    baseline = journal.max_event_seq(run_id)
    with pytest.raises(InjectedCrash):
        await control.runs_resume(
            ACTOR,
            run_id=run_id,
            idempotency_key="resume-response-loss",
        )

    armed = False
    replay = await control.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key="resume-response-loss",
    )
    assert isinstance(replay, RunSubmission)
    assert replay.command.replayed is True
    terminal = await await_attempt_terminal(
        journal,
        run_id,
        baseline_event_seq=baseline,
        expected_resume_command_id=replay.command.command_id,
    )
    assert terminal.kind == "RunFailed"
    assert attempts == [run_id]
    await host.shutdown()


async def test_raw_fenced_retry_freezes_status_from_the_attempt_receipt(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
    tmp_path: Path,
) -> None:
    inputs = {"issue": {"title": "raw-fenced-status"}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId("run-attempt-raw-fenced-status")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    key = "raw-fenced-status"
    request = {"run_id": str(run_id)}
    claimed = journal.claim_command(
        actor=ACTOR,
        operation="runs_resume",
        idempotency_key=key,
        request_hash=command_request_hash(request),
        request=request,
        owner_id="raw-fenced-status-a",
        ttl_s=30,
    )
    assert claimed.claim is not None
    command_id = claimed.claim.command_id
    journal.store_command_plan(
        claimed.claim,
        StoredResumeCommandPlan(
            plan=ResumeCommandPlan(
                run_id=run_id,
                baseline_event_seq=0,
                submitted_status=RunStatus.PENDING,
                terminal_rejection_policy="exact-v1",
            )
        ).model_dump(mode="json"),
    )

    _migrate_raw_resume_plan(
        tmp_path / "journal.db",
        command_id,
        keep_fence=True,
    )
    lease = journal.claim_run(run_id, owner_id="raw-fenced-worker", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
        payload={"resume_command_id": command_id},
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED,
        event_kind="RunFailed",
    )
    journal.release_run(lease)
    clock.advance(31)

    recovered_host = RunHost(world, journal=journal, max_concurrency=1)
    recovered = ControlPlane(
        system=world,
        store=journal,
        run_host=recovered_host,
        owner_id="raw-fenced-status-b",
        command_ttl_s=30,
    )
    response = await recovered.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(response, RunSubmission)
    assert response.run_status is RunStatus.PENDING
    current = journal.run_record(run_id)
    assert current is not None and current.status is RunStatus.FAILED
    replay = await recovered.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(replay, RunSubmission)
    assert replay.run_status is RunStatus.PENDING
    assert replay.command.replayed is True
    await recovered.shutdown()


async def test_prepared_resume_ignores_a_later_live_lease_without_an_event(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = {"issue": {"title": "prepared-live-owner"}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId("run-attempt-prepared-live-owner")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    initial = journal.claim_run(run_id, owner_id="prepared-live-initial", ttl_s=1)
    journal.transition_run(
        initial,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    clock.advance(2)
    baseline = journal.max_event_seq(run_id)
    abandoned_host = RunHost(world, journal=journal, max_concurrency=1)

    def suppress_ordinary_recovery(
        limit: int,
        *,
        now: datetime,
    ) -> tuple[tuple[tuple[RunId, object], ...], datetime | None]:
        del limit, now
        return (), None

    monkeypatch.setattr(abandoned_host, "_recoverable_batch", suppress_ordinary_recovery)

    def crash(name: str) -> None:
        if name == "runs_resume.after_plan":
            raise InjectedCrash(name)

    key = "prepared-live-owner"
    abandoned = ControlPlane(
        system=world,
        store=journal,
        run_host=abandoned_host,
        owner_id="prepared-live-command-a",
        command_ttl_s=30,
        fault_probe=crash,
    )
    with pytest.raises(InjectedCrash):
        await abandoned.runs_resume(ACTOR, run_id=run_id, idempotency_key=key)
    await abandoned.shutdown()

    foreign = journal.claim_run(run_id, owner_id="prepared-live-foreign", ttl_s=300)
    clock.advance(31)
    launched: list[tuple[int | None, AttemptCause | None]] = []
    recovered_host = RunHost(world, journal=journal, max_concurrency=1)

    def retain_exact_intent(
        launched_run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> Literal["queued"]:
        assert launched_run_id == run_id
        assert allowed_statuses is not None and RunStatus.RUNNING in allowed_statuses
        launched.append((expected_event_seq, cause))
        return "queued"

    monkeypatch.setattr(recovered_host, "launch", retain_exact_intent)
    recovered = ControlPlane(
        system=world,
        store=journal,
        run_host=recovered_host,
        owner_id="prepared-live-command-b",
        command_ttl_s=30,
    )
    response = await recovered.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(response, RunSubmission)
    assert response.run_status is RunStatus.RUNNING
    assert launched == [
        (
            baseline,
            AttemptCause(
                kind="resume_command",
                id=command_id_for(ACTOR.actor_id, "runs_resume", key),
            ),
        )
    ]
    journal.release_run(foreign)
    await recovered.shutdown()


async def test_event_advancing_immediately_after_plan_rejects_before_handoff(
    world: Any,
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix="advance-after-plan",
        status=RunStatus.FAILED,
    )
    baseline = journal.max_event_seq(run_id)
    host = RunHost(world, journal=journal, max_concurrency=1)

    def never_launch(*args: object, **kwargs: object) -> Literal["queued"]:
        del args, kwargs
        raise AssertionError("a superseded durable fence must not reach RunHost")

    monkeypatch.setattr(host, "launch", never_launch)
    advanced = False

    def advance(name: str) -> None:
        nonlocal advanced
        if name != "runs_resume.after_plan" or advanced:
            return
        advanced = True
        lease = journal.claim_run(run_id, owner_id="advance-after-plan", ttl_s=30)
        journal.transition_run(
            lease,
            expected=frozenset({RunStatus.FAILED}),
            target=RunStatus.RUNNING,
            event_kind="RunResumed",
        )
        journal.release_run(lease)

    control = ControlPlane(
        system=world,
        store=journal,
        run_host=host,
        fault_probe=advance,
    )
    key = "advance-after-plan"
    response = await control.runs_resume(ACTOR, run_id=run_id, idempotency_key=key)
    assert isinstance(response, ControlRejected)
    assert response.faults[0].code is ControlCode.RUN_NOT_RESUMABLE
    assert response.faults[0].details == {
        "reason": "attempt_superseded",
        "baseline_event_seq": baseline,
    }
    replay = await control.runs_resume(ACTOR, run_id=run_id, idempotency_key=key)
    assert replay == response
    assert journal.max_event_seq(run_id) == baseline + 1
    await control.shutdown()


async def test_resume_plan_uses_one_coherent_run_head_observation(
    world: Any,
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix="coherent-run-head",
        status=RunStatus.FAILED,
    )
    baseline = journal.max_event_seq(run_id)
    original_head = journal.run_head
    advanced = False

    def advance_after_snapshot(observed_run_id: RunId):
        nonlocal advanced
        head = original_head(observed_run_id)
        if observed_run_id == run_id and not advanced:
            advanced = True
            lease = journal.claim_run(run_id, owner_id="coherent-run-head", ttl_s=30)
            journal.transition_run(
                lease,
                expected=frozenset({RunStatus.FAILED}),
                target=RunStatus.RUNNING,
                event_kind="RunResumed",
            )
            journal.release_run(lease)
        return head

    monkeypatch.setattr(journal, "run_head", advance_after_snapshot)
    host = RunHost(world, journal=journal, max_concurrency=1)

    def never_launch(*args: object, **kwargs: object) -> Literal["queued"]:
        del args, kwargs
        raise AssertionError("the observed fence was durably superseded")

    monkeypatch.setattr(host, "launch", never_launch)
    control = ControlPlane(system=world, store=journal, run_host=host)
    key = "coherent-run-head"
    response = await control.runs_resume(ACTOR, run_id=run_id, idempotency_key=key)
    assert isinstance(response, ControlRejected)
    assert response.faults[0].details == {
        "reason": "attempt_superseded",
        "baseline_event_seq": baseline,
    }
    stored = journal.command(command_id_for(ACTOR.actor_id, "runs_resume", key))
    assert stored is not None and isinstance(stored.plan, dict)
    assert stored.plan["plan"]["baseline_event_seq"] == baseline
    assert stored.plan["plan"]["submitted_status"] == RunStatus.FAILED.value
    await control.shutdown()


async def test_committed_resume_losing_a_cross_host_fence_is_not_revived(
    world: Any,
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix="cross-host-resume-race",
        status=RunStatus.FAILED,
    )
    attempts = _install_terminal_worker(
        monkeypatch,
        world,
        journal,
        terminal_status=RunStatus.FAILED,
    )
    first_key = "cross-host-resume-race-first"
    first_command_id = command_id_for(ACTOR.actor_id, "runs_resume", first_key)
    first_host = RunHost(world, journal=journal, max_concurrency=1)

    def retain_first_handoff(
        launched_run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> Literal["queued"]:
        del launched_run_id, expected_event_seq, allowed_statuses, cause
        return "queued"

    monkeypatch.setattr(first_host, "launch", retain_first_handoff)

    def crash(name: str) -> None:
        if name == "runs_resume.after_command_completion":
            raise InjectedCrash(name)

    first_control = ControlPlane(
        system=world,
        store=journal,
        run_host=first_host,
        fault_probe=crash,
    )
    with pytest.raises(InjectedCrash):
        await first_control.runs_resume(
            ACTOR,
            run_id=run_id,
            idempotency_key=first_key,
        )
    await first_control.shutdown()

    second_host = RunHost(world, journal=journal, max_concurrency=1)
    launch_second = second_host.launch

    def let_the_competing_host_win(
        launched_run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> Literal["queued", "coalesced_exact", "superseded"]:
        if cause is not None and cause.id == first_command_id:
            return "queued"
        return launch_second(
            launched_run_id,
            expected_event_seq=expected_event_seq,
            allowed_statuses=allowed_statuses,
            cause=cause,
        )

    monkeypatch.setattr(second_host, "launch", let_the_competing_host_win)
    second_control = ControlPlane(system=world, store=journal, run_host=second_host)
    baseline = journal.max_event_seq(run_id)
    second = await second_control.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key="cross-host-resume-race-second",
    )
    assert isinstance(second, RunSubmission)
    terminal = await await_attempt_terminal(
        journal,
        run_id,
        baseline_event_seq=baseline,
        expected_resume_command_id=second.command.command_id,
    )
    assert terminal.kind == "RunFailed"
    await second_control.shutdown()

    recovered_host = RunHost(world, journal=journal, max_concurrency=1)
    recovered = ControlPlane(system=world, store=journal, run_host=recovered_host)
    await recovered.startup()
    for _ in range(20):
        await asyncio.sleep(0)

    assert attempts == [run_id]
    assert recovered_host.pump_failure is None
    await recovered.shutdown()


async def test_prepared_legacy_unfenced_resume_rejects_exactly(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix="legacy-prepared-resume",
        status=RunStatus.FAILED,
    )
    attempts = _install_terminal_worker(
        monkeypatch, world, journal, terminal_status=RunStatus.FAILED
    )
    abandoned_host = RunHost(world, journal=journal, max_concurrency=1)

    def crash(name: str) -> None:
        if name == "runs_resume.after_plan":
            raise InjectedCrash(name)

    abandoned = ControlPlane(
        system=world,
        store=journal,
        run_host=abandoned_host,
        owner_id="legacy-resume-a",
        command_ttl_s=30,
        fault_probe=crash,
    )
    baseline = journal.max_event_seq(run_id)
    with pytest.raises(InjectedCrash):
        await abandoned.runs_resume(
            ACTOR,
            run_id=run_id,
            idempotency_key="legacy-prepared-resume",
        )

    command_id = command_id_for(ACTOR.actor_id, "runs_resume", "legacy-prepared-resume")
    await abandoned.shutdown()
    _migrate_raw_resume_plan(
        tmp_path / "journal.db",
        command_id,
        keep_fence=False,
    )

    clock.advance(31)
    recovered_host = RunHost(world, journal=journal, max_concurrency=1)
    recovered = ControlPlane(
        system=world,
        store=journal,
        run_host=recovered_host,
        owner_id="legacy-resume-b",
        command_ttl_s=30,
    )
    response = await recovered.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key="legacy-prepared-resume",
    )
    assert isinstance(response, ControlRejected)
    assert len(response.faults) == 1
    assert response.faults[0].code is ControlCode.RUN_NOT_RESUMABLE
    assert response.faults[0].details == {"reason": "attempt_fence_missing"}
    stored = journal.command(command_id)
    assert stored is not None and stored.response is not None
    stored_response = stored.response

    replay = await recovered.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key="legacy-prepared-resume",
    )
    assert replay == response
    replayed = journal.command(command_id)
    assert replayed is not None and replayed.response == stored_response
    assert journal.max_event_seq(run_id) == baseline
    assert attempts == []
    await recovered.shutdown()


async def test_terminal_legacy_unfenced_resume_replays_without_a_new_intent(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix="legacy-terminal-unfenced",
        status=RunStatus.FAILED,
    )
    baseline = journal.max_event_seq(run_id)
    first_host = RunHost(world, journal=journal, max_concurrency=1)
    first_intents: list[tuple[int | None, AttemptCause | None]] = []

    def retain_first_intent(
        launched_run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> Literal["queued"]:
        del allowed_statuses
        assert launched_run_id == run_id
        first_intents.append((expected_event_seq, cause))
        return "queued"

    monkeypatch.setattr(first_host, "launch", retain_first_intent)
    key = "legacy-terminal-unfenced"
    first_control = ControlPlane(system=world, store=journal, run_host=first_host)
    first = await first_control.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(first, RunSubmission)
    assert first_intents == [
        (
            baseline,
            AttemptCause(
                kind="resume_command",
                id=command_id_for(ACTOR.actor_id, "runs_resume", key),
            ),
        )
    ]
    assert journal.max_event_seq(run_id) == baseline
    await first_control.shutdown()

    _migrate_raw_resume_plan(
        tmp_path / "journal.db",
        first.command.command_id,
        keep_fence=False,
    )
    recovered_host = RunHost(world, journal=journal, max_concurrency=1)

    def refuse_new_intent(
        launched_run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> Literal["queued"]:
        del launched_run_id, expected_event_seq, allowed_statuses, cause
        raise AssertionError("terminal unfenced history launched a new resume intent")

    monkeypatch.setattr(recovered_host, "launch", refuse_new_intent)
    recovered = ControlPlane(system=world, store=journal, run_host=recovered_host)
    replay = await recovered.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert replay == first.model_copy(
        update={"command": first.command.model_copy(update={"replayed": True})}
    )
    assert journal.max_event_seq(run_id) == baseline
    await recovered.shutdown()


async def test_prepared_weak_plan_must_match_its_immutable_fence_status(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix="weak-status-mismatch",
        status=RunStatus.FAILED,
    )
    baseline = journal.max_event_seq(run_id)
    abandoned_host = RunHost(world, journal=journal, max_concurrency=1)

    def crash(name: str) -> None:
        if name == "runs_resume.after_plan":
            raise InjectedCrash(name)

    key = "weak-status-mismatch"
    abandoned = ControlPlane(
        system=world,
        store=journal,
        run_host=abandoned_host,
        owner_id="weak-status-a",
        command_ttl_s=30,
        fault_probe=crash,
    )
    with pytest.raises(InjectedCrash):
        await abandoned.runs_resume(ACTOR, run_id=run_id, idempotency_key=key)
    command_id = command_id_for(ACTOR.actor_id, "runs_resume", key)
    await abandoned.shutdown()

    database = tmp_path / "journal.db"
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert stored is not None and isinstance(stored[0], str)
        weak = json.loads(stored[0])
        assert isinstance(weak, dict) and isinstance(weak.get("plan"), dict)
        weak["plan"].pop("terminal_rejection_policy")
        weak["plan"]["submitted_status"] = RunStatus.PARKED.value
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(weak), command_id),
        )
        connection.commit()
    SqliteJournal(database)
    clock.advance(31)

    recovered_host = RunHost(world, journal=journal, max_concurrency=1)

    def never_launch(*args: object, **kwargs: object) -> Literal["queued"]:
        del args, kwargs
        raise AssertionError("a contradictory plan must fail before RunHost")

    monkeypatch.setattr(recovered_host, "launch", never_launch)
    recovered = ControlPlane(
        system=world,
        store=journal,
        run_host=recovered_host,
        owner_id="weak-status-b",
        command_ttl_s=30,
    )
    with pytest.raises(JournalDamaged, match="exact fenced status"):
        await recovered.runs_resume(ACTOR, run_id=run_id, idempotency_key=key)
    retained = journal.command(command_id)
    assert retained is not None
    assert retained.state == "prepared"
    assert retained.response is None
    assert journal.max_event_seq(run_id) == baseline
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals"
            " WHERE family = 'resume_attempt' AND fact_key = ?",
            (command_id,),
        ).fetchone() == (0,)
    await recovered.shutdown()


@pytest.mark.parametrize("shape", ("raw", "weak_typed"))
@pytest.mark.parametrize("fault_count", (1, 2))
async def test_terminal_historical_resume_replays_its_literal_bound_response(
    shape: str,
    fault_count: int,
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix=f"terminal-{shape}-{fault_count}",
        status=RunStatus.FAILED,
    )
    abandoned_host = RunHost(world, journal=journal, max_concurrency=1)

    def crash(name: str) -> None:
        if name == "runs_resume.after_plan":
            raise InjectedCrash(name)

    key = f"terminal-{shape}-{fault_count}"
    abandoned = ControlPlane(
        system=world,
        store=journal,
        run_host=abandoned_host,
        fault_probe=crash,
    )
    with pytest.raises(InjectedCrash):
        await abandoned.runs_resume(ACTOR, run_id=run_id, idempotency_key=key)
    command_id = command_id_for(ACTOR.actor_id, "runs_resume", key)
    await abandoned.shutdown()

    first = ControlRejected.one_fault(
        ControlCode.AUTH_REQUIRED_SCOPE,
        "historical policy refusal",
        "consult the retained policy",
    )
    second = ControlRejected.one_fault(
        ControlCode.CHANNEL_WRONG_INTERACTION,
        "historical secondary refusal",
        "inspect the retained exchange",
    )
    response = ControlRejected(
        faults=first.faults + (second.faults if fault_count == 2 else ()),
    )
    database = tmp_path / "journal.db"
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT plan_json, updated_at FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert stored is not None and isinstance(stored[0], str)
        historical = json.loads(stored[0])
        assert isinstance(historical, dict) and isinstance(historical.get("plan"), dict)
        historical["plan"].pop("terminal_rejection_policy")
        if shape == "raw":
            historical = {
                "run_id": str(run_id),
                "baseline_event_seq": historical["plan"]["baseline_event_seq"],
            }
        literal_response = canonical_json(response.model_dump(mode="json"))
        connection.execute(
            "UPDATE commands SET plan_json = ?, state = 'rejected',"
            " response_json = ?, owner_id = NULL, lease_expires_at = NULL,"
            " completed_at = updated_at WHERE command_id = ?",
            (canonical_json(historical), literal_response, command_id),
        )
        connection.commit()
    SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT response_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
    assert before == (literal_response,)

    replay_host = RunHost(world, journal=journal, max_concurrency=1)
    replay_control = ControlPlane(system=world, store=journal, run_host=replay_host)
    replay = await replay_control.runs_resume(
        ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert replay == response
    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT response_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
    assert after == before
    await replay_control.shutdown()


async def test_prepared_historical_witness_cannot_authorize_retained_refusal_bytes(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix="prepared-historical-response",
        status=RunStatus.FAILED,
    )
    abandoned_host = RunHost(world, journal=journal, max_concurrency=1)

    def crash(name: str) -> None:
        if name == "runs_resume.after_plan":
            raise InjectedCrash(name)

    key = "prepared-historical-response"
    abandoned = ControlPlane(
        system=world,
        store=journal,
        run_host=abandoned_host,
        fault_probe=crash,
    )
    with pytest.raises(InjectedCrash):
        await abandoned.runs_resume(ACTOR, run_id=run_id, idempotency_key=key)
    command_id = command_id_for(ACTOR.actor_id, "runs_resume", key)
    await abandoned.shutdown()

    database = tmp_path / "journal.db"
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        weak = json.loads(row[0])
        assert isinstance(weak, dict) and isinstance(weak.get("plan"), dict)
        weak["plan"].pop("terminal_rejection_policy")
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(weak), command_id),
        )
        connection.commit()
    SqliteJournal(database)
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
    historical = ControlRejected.one_fault(
        ControlCode.AUTH_REQUIRED_SCOPE,
        "historical-looking refusal",
        "consult the retained policy",
    )
    journal.reject_command(claim, historical.model_dump(mode="json"))

    replay_host = RunHost(world, journal=journal, max_concurrency=1)
    replay_control = ControlPlane(system=world, store=journal, run_host=replay_host)
    with pytest.raises(JournalDamaged, match="exact planned refusal"):
        await replay_control.runs_resume(
            ACTOR,
            run_id=run_id,
            idempotency_key=key,
        )
    await replay_control.shutdown()


async def test_damaged_committed_resume_fence_is_never_treated_as_legacy(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    run_id = _prepare_terminal(
        world,
        journal,
        suffix="damaged-committed-resume",
        status=RunStatus.FAILED,
    )
    host = RunHost(world, journal=journal, max_concurrency=1)
    armed = True

    def crash(name: str) -> None:
        if armed and name == "runs_resume.after_command_completion":
            raise InjectedCrash(name)

    control = ControlPlane(
        system=world,
        store=journal,
        run_host=host,
        fault_probe=crash,
    )
    with pytest.raises(InjectedCrash):
        await control.runs_resume(
            ACTOR,
            run_id=run_id,
            idempotency_key="damaged-committed-resume",
        )
    command_id = command_id_for(ACTOR.actor_id, "runs_resume", "damaged-committed-resume")
    _damage_attempt_fence(tmp_path / "journal.db", command_id)

    armed = False
    with pytest.raises(JournalDamaged):
        await control.runs_resume(
            ACTOR,
            run_id=run_id,
            idempotency_key="damaged-committed-resume",
        )
    await host.shutdown()


@pytest.mark.parametrize(
    "mutation",
    ["lifecycle", "operation", "timestamp_type", "timestamp_syntax"],
)
async def test_resume_recovery_surfaces_an_older_selector_anomaly(
    mutation: Literal[
        "lifecycle",
        "operation",
        "timestamp_type",
        "timestamp_syntax",
    ],
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older_run = _prepare_terminal(
        world,
        journal,
        suffix=f"recovery-selector-{mutation}-older",
        status=RunStatus.FAILED,
    )
    later_run = _prepare_terminal(
        world,
        journal,
        suffix=f"recovery-selector-{mutation}-later",
        status=RunStatus.FAILED,
    )
    abandoned_host = RunHost(world, journal=journal, max_concurrency=1)

    def hold_launch(
        run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> Literal["queued"]:
        del run_id, expected_event_seq, allowed_statuses, cause
        return "queued"

    monkeypatch.setattr(abandoned_host, "launch", hold_launch)

    def crash(name: str) -> None:
        if name == "runs_resume.after_command_completion":
            raise InjectedCrash(name)

    abandoned = ControlPlane(
        system=world,
        store=journal,
        run_host=abandoned_host,
        fault_probe=crash,
    )
    with pytest.raises(InjectedCrash):
        await abandoned.runs_resume(
            ACTOR,
            run_id=older_run,
            idempotency_key=f"recovery-selector-{mutation}-older",
        )
    clock.advance(1)
    with pytest.raises(InjectedCrash):
        await abandoned.runs_resume(
            ACTOR,
            run_id=later_run,
            idempotency_key=f"recovery-selector-{mutation}-later",
        )
    await abandoned.shutdown()

    older_command_id = command_id_for(
        ACTOR.actor_id,
        "runs_resume",
        f"recovery-selector-{mutation}-older",
    )
    _damage_resume_recovery_selector(journal._db_path, older_command_id, mutation)

    recovered_host = RunHost(world, journal=journal, max_concurrency=1)
    recovered_launches: list[RunId] = []

    def record_launch(
        run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> Literal["queued"]:
        del expected_event_seq, allowed_statuses, cause
        recovered_launches.append(run_id)
        return "queued"

    monkeypatch.setattr(recovered_host, "launch", record_launch)
    recovered = ControlPlane(system=world, store=journal, run_host=recovered_host)
    with pytest.raises(JournalDamaged):
        await recovered.startup()
    assert recovered_launches == []
    await recovered.shutdown()


async def test_start_replay_after_failed_attempt_does_not_implicitly_resume(
    world: Any,
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = _install_terminal_worker(
        monkeypatch, world, journal, terminal_status=RunStatus.FAILED
    )
    host = RunHost(world, journal=journal, max_concurrency=1)
    control = ControlPlane(system=world, store=journal, run_host=host)
    inputs = {"issue": {"title": "start-fails-once"}}

    first = await control.runs_start(
        ACTOR,
        proposal=pipeline_graph(),
        inputs=inputs,
        idempotency_key="start-fails-once",
    )
    assert isinstance(first, RunSubmission)
    terminal = await await_attempt_terminal(journal, first.run_id, baseline_event_seq=0)
    assert terminal.kind == "RunFailed"
    events_after_first = _attempt_events(journal, first.run_id)

    replay = await control.runs_start(
        ACTOR,
        proposal=pipeline_graph(),
        inputs=inputs,
        idempotency_key="start-fails-once",
    )
    assert isinstance(replay, RunSubmission)
    assert replay.command.replayed is True
    for _ in range(20):
        await asyncio.sleep(0)

    assert attempts == [first.run_id]
    assert _attempt_events(journal, first.run_id) == events_after_first
    await host.shutdown()
