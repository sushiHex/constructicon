"""Wake recovery reads durable domain facts, never command state."""

from __future__ import annotations

from typing import Any

import pytest
from tests.conftest import pipeline_graph

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, digest
from constructicon.core.run import ParkedUnit, RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal

PATH = ExecutionPath(scope=ScopePath(segments=("review",)))


def _request(name: str) -> Digest:
    return digest("channel-message", 1, {"request": name})


def _park(
    world: Any,
    journal: SqliteJournal,
    suffix: str,
    *,
    units: tuple[ParkedUnit, ...],
    event_kind: str = "RunParked",
) -> RunId:
    inputs = {"issue": {"title": suffix}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId(f"run-parked-{suffix}")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    lease = journal.claim_run(run_id, owner_id=f"owner-{suffix}", ttl_s=300)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.PARKED,
        event_kind=event_kind,
        payload={
            "parked": [unit.model_dump(mode="json") for unit in units],
            "blocked": [],
        },
    )
    journal.release_run(lease)
    return run_id


def test_parked_waits_projects_each_waiting_request_at_its_parking_fence(
    world: Any,
    journal: SqliteJournal,
) -> None:
    advice, approval = _request("advice"), _request("approval")
    run_id = _park(
        world,
        journal,
        "two-waits",
        units=(
            ParkedUnit(path=PATH, reason="awaiting_advisor", waiting_on=advice),
            ParkedUnit(
                path=ExecutionPath(scope=ScopePath(segments=("approve",))),
                reason="awaiting_approval",
                waiting_on=approval,
            ),
        ),
    )

    waits = journal.parked_waits()
    assert [wait.run_id for wait in waits] == [run_id]
    assert set(waits[0].requests) == {advice, approval}
    assert waits[0].event_seq == journal.max_event_seq(run_id)  # the exact fence


def test_a_policy_exhausted_park_projects_no_request_to_wake_on(
    world: Any,
    journal: SqliteJournal,
) -> None:
    """M4 parking is not waiting for anyone; only a reply may wake a wait."""

    _park(
        world,
        journal,
        "exhausted",
        units=(
            ParkedUnit(path=PATH, reason="policy_exhausted", completed_iterations=3),
        ),
    )
    waits = journal.parked_waits()
    assert len(waits) == 1
    assert waits[0].requests == ()


def test_only_parked_runs_are_projected(world: Any, journal: SqliteJournal) -> None:
    _park(
        world,
        journal,
        "waiting",
        units=(ParkedUnit(path=PATH, reason="awaiting_advisor", waiting_on=_request("a")),),
    )
    inputs = {"issue": {"title": "running"}}
    manifest = world.validate(pipeline_graph(), inputs)
    live = RunId("run-still-running")
    world._prepare_run(manifest, run_id=live, inputs=inputs)
    lease = journal.claim_run(live, owner_id="owner-live", ttl_s=300)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    assert [wait.run_id for wait in journal.parked_waits()] == [RunId("run-parked-waiting")]


def test_a_parked_run_whose_latest_event_is_not_a_park_is_damage(
    world: Any,
    journal: SqliteJournal,
) -> None:
    """Fail closed: a wake that guessed a fence could revive the wrong attempt."""

    _park(
        world,
        journal,
        "mislabelled",
        units=(ParkedUnit(path=PATH, reason="awaiting_advisor", waiting_on=_request("a")),),
        event_kind="RunFailed",
    )
    with pytest.raises(JournalDamaged, match="no latest RunParked event"):
        journal.parked_waits()


def test_a_parking_event_with_invalid_units_is_damage(
    world: Any,
    journal: SqliteJournal,
) -> None:
    inputs = {"issue": {"title": "damaged"}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId("run-parked-damaged")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    lease = journal.claim_run(run_id, owner_id="owner-damaged", ttl_s=300)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.PARKED,
        event_kind="RunParked",
        payload={"parked": [{"reason": "awaiting_advisor"}], "blocked": []},
    )
    with pytest.raises(JournalDamaged, match="invalid parked units"):
        journal.parked_waits()


def test_parked_waits_pages_and_refuses_a_nonpositive_bound(
    world: Any,
    journal: SqliteJournal,
) -> None:
    for index in range(3):
        _park(
            world,
            journal,
            f"page-{index}",
            units=(
                ParkedUnit(
                    path=PATH,
                    reason="awaiting_advisor",
                    waiting_on=_request(f"page-{index}"),
                ),
            ),
        )
    first = journal.parked_waits(limit=2)
    assert len(first) == 2
    record = journal.run_record(first[-1].run_id)
    assert record is not None
    rest = journal.parked_waits(
        after=(record.created_at.isoformat(), str(record.run_id)),
        limit=2,
    )
    assert len(rest) == 1
    assert {wait.run_id for wait in (*first, *rest)} == {
        RunId(f"run-parked-page-{index}") for index in range(3)
    }
    with pytest.raises(ValueError, match="limit must be positive"):
        journal.parked_waits(limit=0)
