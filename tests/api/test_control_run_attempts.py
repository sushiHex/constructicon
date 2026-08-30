"""A durable submission can authorize at most one run attempt."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.control import (
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    RunSubmission,
    command_id_for,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.run import AttemptCause, ParkedUnit, RunStatus
from constructicon.runtime.walker import RunResult
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import (
    FakeClock,
    InjectedCrash,
    await_attempt_terminal,
    pipeline_graph,
)

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


def _remove_attempt_fence(db_path: Path, command_id: str) -> None:
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
        else:
            plan.pop("baseline_event_seq", None)
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (json.dumps(plan, sort_keys=True, separators=(",", ":")), command_id),
        )


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
        _remove_attempt_fence(tmp_path / "journal.db", first.command.command_id)

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
    await host.shutdown()


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


async def test_prepared_legacy_resume_plan_recovers_with_a_current_attempt_fence(
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
    _remove_attempt_fence(tmp_path / "journal.db", command_id)

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
    assert isinstance(response, RunSubmission)
    terminal = await await_attempt_terminal(
        journal,
        run_id,
        baseline_event_seq=baseline,
        expected_resume_command_id=response.command.command_id,
    )
    assert terminal.kind == "RunFailed"
    assert attempts == [run_id]
    await abandoned_host.shutdown()
    await recovered_host.shutdown()


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
