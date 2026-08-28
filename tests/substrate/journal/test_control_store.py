"""One synchronized ControlStore contract for memory and SQLite."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from constructicon.core.address import RunId
from constructicon.core.control import (
    OPERATE_SCOPE,
    AuthenticatedActor,
    CommandClaim,
    ControlStore,
    command_id_for,
)
from constructicon.core.effect import ApprovalRecord, ComponentProofSubject
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import digest
from constructicon.core.run import OwnershipLost
from constructicon.substrate.control import InMemoryControlStore
from constructicon.substrate.journal.sqlite import SqliteJournal

ACTOR = AuthenticatedActor(
    actor_id="static:control-contract",
    auth_method="static",
    scopes=frozenset({OPERATE_SCOPE}),
)
REQUEST = {"run_id": "run-control-contract"}
REQUEST_HASH = digest("control-request", 1, REQUEST)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def control_clock() -> MutableClock:
    return MutableClock()


@pytest.fixture(params=("memory", "sqlite"))
def control_store(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    control_clock: MutableClock,
) -> ControlStore:
    if request.param == "memory":
        return InMemoryControlStore(now_fn=control_clock.now)
    return SqliteJournal(tmp_path / "control-store.db", now_fn=control_clock.now)


def _claim(
    store: ControlStore,
    *,
    owner: str,
    key: str = "same-key",
    operation: str = "runs_resume",
    request: dict[str, str] = REQUEST,
):
    return store.claim_command(
        actor=ACTOR,
        operation=operation,
        idempotency_key=key,
        request_hash=digest("control-request", 1, request),
        request=request,
        owner_id=owner,
        ttl_s=30,
    )


@pytest.mark.parametrize("same_owner", [False, True])
def test_simultaneous_claims_produce_one_live_owner(
    control_store: ControlStore,
    same_owner: bool,
) -> None:
    barrier = threading.Barrier(2)

    def contend(index: int):
        barrier.wait()
        return _claim(
            control_store,
            owner="owner-one" if same_owner else f"owner-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(contend, (1, 2)))
    assert sorted(result.status for result in results) == ["claimed", "in_progress"]
    winner = next(result.claim for result in results if result.claim is not None)
    stored = control_store.command(winner.command_id)
    assert stored is not None
    assert stored.owner_id == winner.owner_id
    assert stored.owner_epoch == 1


def test_conflict_and_live_claim_never_reclaim(control_store: ControlStore) -> None:
    first = _claim(control_store, owner="owner-a")
    assert first.claim is not None
    live = _claim(control_store, owner="owner-b")
    assert live.status == "in_progress"
    conflict = _claim(
        control_store,
        owner="owner-b",
        request={"run_id": "run-other"},
    )
    assert conflict.status == "conflict"
    assert conflict.record is not None
    assert conflict.record.command_id == first.claim.command_id


def test_expired_claim_race_fences_old_epoch(
    control_store: ControlStore,
    control_clock: MutableClock,
) -> None:
    first = _claim(control_store, owner="owner-old")
    assert first.claim is not None
    control_clock.advance(31)
    barrier = threading.Barrier(2)

    def contend(owner: str):
        barrier.wait()
        return _claim(control_store, owner=owner)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(contend, ("owner-a", "owner-b")))
    assert sorted(result.status for result in results) == ["claimed", "in_progress"]
    winner = next(result.claim for result in results if result.claim is not None)
    assert winner.epoch == 2
    with pytest.raises(OwnershipLost):
        control_store.store_command_plan(first.claim, {"kind": "stale"})
    with pytest.raises(OwnershipLost):
        control_store.complete_command(first.claim, {"status": "stale"})
    with pytest.raises(OwnershipLost):
        control_store.store_approval(first.claim, _approval(first.claim))


def _approval(claim: CommandClaim) -> ApprovalRecord:
    subject = ComponentProofSubject(
        component="test/component",
        version=digest("version", 1, {"value": 1}),
        baseline_version=None,
    )
    return ApprovalRecord(
        approval_id=f"approval-{claim.command_id}",
        subject=subject,
        decision="approved",
        actor=ACTOR,
        run_id=RunId("run-control-contract"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_plan_terminal_and_approval_are_write_once(control_store: ControlStore) -> None:
    claimed = _claim(control_store, owner="owner")
    assert claimed.claim is not None
    claim = claimed.claim
    plan = {"a": 1, "b": [2, 3]}
    control_store.store_command_plan(claim, plan)
    control_store.store_command_plan(claim, {"b": [2, 3], "a": 1})
    with pytest.raises(JournalDamaged):
        control_store.store_command_plan(claim, {"a": 2})

    approval = _approval(claim)
    assert control_store.store_approval(claim, approval) == approval
    assert control_store.store_approval(claim, approval) == approval
    with pytest.raises(JournalDamaged):
        control_store.store_approval(
            claim,
            approval.model_copy(update={"decision": "rejected"}),
        )

    response = {"status": "committed", "value": 1}
    committed = control_store.complete_command(claim, response)
    assert control_store.complete_command(claim, response) == committed
    with pytest.raises(JournalDamaged):
        control_store.complete_command(claim, {"status": "committed", "value": 2})
    with pytest.raises(JournalDamaged):
        control_store.reject_command(claim, response)


def test_rejected_terminal_is_write_once(control_store: ControlStore) -> None:
    claimed = _claim(control_store, owner="owner", key="rejected")
    assert claimed.claim is not None
    response = {"status": "rejected", "faults": []}
    rejected = control_store.reject_command(claimed.claim, response)
    assert control_store.reject_command(claimed.claim, response) == rejected
    with pytest.raises(JournalDamaged):
        control_store.reject_command(claimed.claim, {"status": "rejected"})


def test_committed_command_keyset_is_bounded_and_filtered(
    control_store: ControlStore,
) -> None:
    committed_ids: list[str] = []
    for index in range(4):
        claimed = _claim(control_store, owner="owner", key=f"resume-{index}")
        assert claimed.claim is not None
        control_store.complete_command(claimed.claim, {"index": index})
        committed_ids.append(claimed.claim.command_id)
    rejected = _claim(control_store, owner="owner", key="resume-rejected")
    assert rejected.claim is not None
    control_store.reject_command(rejected.claim, {"status": "rejected"})
    other = _claim(
        control_store,
        owner="owner",
        key="cancel",
        operation="runs_cancel",
    )
    assert other.claim is not None
    control_store.complete_command(other.claim, {"status": "committed"})
    prepared = _claim(control_store, owner="owner", key="resume-prepared")
    assert prepared.claim is not None

    through = control_store.latest_command_key(operation="runs_resume")
    assert through is not None
    assert through[1] == max(
        prepared.claim.command_id,
        rejected.claim.command_id,
        *committed_ids,
    )
    first = control_store.committed_commands(
        operation="runs_resume", after=None, through=through, limit=2
    )
    after = (first[-1].created_at.isoformat(), first[-1].command_id)
    second = control_store.committed_commands(
        operation="runs_resume", after=after, through=through, limit=2
    )
    assert [record.command_id for record in (*first, *second)] == sorted(committed_ids)
    assert all(record.state == "committed" for record in (*first, *second))
    with pytest.raises(ValueError):
        control_store.committed_commands(
            operation="runs_resume", after=None, through=through, limit=0
        )


def test_sqlite_reopen_preserves_canonical_models(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    path = tmp_path / "reopen.db"
    first = SqliteJournal(path, now_fn=control_clock.now)
    claimed = _claim(first, owner="owner", key="reopen")
    assert claimed.claim is not None
    first.store_command_plan(claimed.claim, {"kind": "exact", "values": [1, 2]})
    expected = first.complete_command(claimed.claim, {"status": "committed"})
    reopened = SqliteJournal(path, now_fn=control_clock.now)
    assert reopened.command(claimed.claim.command_id) == expected
    through = reopened.latest_command_key(operation="runs_resume")
    assert through is not None
    assert reopened.committed_commands(
        operation="runs_resume", after=None, through=through, limit=1
    ) == (expected,)


def test_command_identity_remains_actor_operation_key_derived() -> None:
    assert command_id_for(ACTOR.actor_id, "runs_resume", "same-key").startswith("cmd-")
    assert digest("control-request", 1, REQUEST) == REQUEST_HASH
