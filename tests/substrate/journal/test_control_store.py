"""One synchronized ControlStore contract for memory and SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.run_worlds import sealed_test_manifest

from constructicon.core.address import RunId
from constructicon.core.channel import reply_message_id
from constructicon.core.control import (
    APPROVE_SCOPE,
    IDEMPOTENCY_KEY_MAX_LENGTH,
    OPERATE_SCOPE,
    AuthenticatedActor,
    CommandClaim,
    ControlPlaneStore,
    ControlStore,
    ResumeCommandPlan,
    RunCreationPlan,
    RunOrigin,
    StoredResumeCommandPlan,
    StoredRunCreationPlan,
    approval_id_for_command,
    command_id_for,
    command_request_hash,
    run_id_for_command,
)
from constructicon.core.effect import ApprovalRecord, ComponentProofSubject
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import (
    ApprovalPlan,
    ChannelApprovalPlan,
    StoredApprovalPlan,
    approval_decision_payload,
)
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest, json_value
from constructicon.core.run import OwnershipLost, RunStatus
from constructicon.substrate.control import InMemoryControlStore
from constructicon.substrate.journal._sqlite_commands import seal_command_phases
from constructicon.substrate.journal._sqlite_runs import run_world_fact_hash
from constructicon.substrate.journal.sqlite import SqliteJournal

ACTOR = AuthenticatedActor(
    actor_id="static:control-contract",
    auth_method="static",
    scopes=frozenset({OPERATE_SCOPE, APPROVE_SCOPE}),
)
APPROVAL_SUBJECT = ComponentProofSubject(
    component="test/component",
    version=digest("version", 1, {"value": 1}),
    baseline_version=None,
)
REQUEST: dict[str, JsonValue] = {"run_id": "run-control-contract"}
APPROVAL_REQUEST: dict[str, JsonValue] = {
    "run_id": "run-control-contract",
    "subject": APPROVAL_SUBJECT.model_dump(mode="json"),
    "decision": "approved",
    "reason": None,
}
REQUEST_HASH = command_request_hash(REQUEST)


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


def test_only_a_colocated_store_advertises_the_full_control_plane_transaction(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    assert not isinstance(InMemoryControlStore(now_fn=control_clock.now), ControlPlaneStore)
    assert isinstance(
        SqliteJournal(tmp_path / "control-plane-store.db", now_fn=control_clock.now),
        ControlPlaneStore,
    )


def _claim(
    store: ControlStore,
    *,
    owner: str,
    key: str = "same-key",
    operation: str = "runs_resume",
    request: dict[str, JsonValue] | None = None,
):
    canonical_request = (
        APPROVAL_REQUEST if operation == "runs_approve" else REQUEST
    ) if request is None else request
    return store.claim_command(
        actor=ACTOR,
        operation=operation,
        idempotency_key=key,
        request_hash=command_request_hash(canonical_request),
        request=canonical_request,
        owner_id=owner,
        ttl_s=30,
    )


def _store_test_plan(store: ControlStore, claim: CommandClaim) -> None:
    store.store_command_plan(
        claim,
        _typed_test_plan({"kind": "test", "command_id": claim.command_id}),
    )


def _typed_test_plan(plan: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {"schema_version": 1, "plan": plan}


@pytest.mark.parametrize(
    "era",
    ("raw", "raw_rejection", "raw_garbage", "weak_typed", "exact_v1"),
)
def test_resume_plan_write_boundary_accepts_only_current_exact_v1(
    control_store: ControlStore,
    era: str,
) -> None:
    claimed = _claim(control_store, owner="resume-plan-era", key=f"resume-plan-{era}")
    assert claimed.claim is not None
    run_id = RunId("run-control-contract")
    exact = StoredResumeCommandPlan(
        plan=ResumeCommandPlan(
            run_id=run_id,
            baseline_event_seq=0,
            submitted_status=RunStatus.PENDING,
            terminal_rejection_policy="exact-v1",
        )
    ).model_dump(mode="json")
    if era == "raw":
        plan: JsonValue = {"run_id": str(run_id), "baseline_event_seq": 0}
    elif era == "raw_rejection":
        plan = {"rejection": {"status": "historical"}}
    elif era == "raw_garbage":
        plan = "historical-garbage"
    else:
        plan = StoredResumeCommandPlan(
            plan=ResumeCommandPlan(
                run_id=run_id,
                baseline_event_seq=0,
                submitted_status=RunStatus.PENDING,
                terminal_rejection_policy=("exact-v1" if era == "exact_v1" else None),
            )
        ).model_dump(mode="json")

    if era != "exact_v1":
        with pytest.raises(JournalDamaged, match="historical plan era"):
            control_store.store_command_plan(claimed.claim, plan)
        stored = control_store.command(claimed.claim.command_id)
        assert stored is not None and stored.plan is None
        plan = exact

    control_store.store_command_plan(claimed.claim, plan)
    stored = control_store.command(claimed.claim.command_id)
    assert stored is not None and stored.plan == plan


def _delete_command_and_phase_seals(database: Path, command_id: str) -> None:
    """Test-only removal of a command and every independent phase proof."""

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM commands WHERE command_id = ?", (command_id,))
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE fact_key = ?"
            " AND family IN ('command_claim', 'command_plan', 'command_terminal')",
            (command_id,),
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


@pytest.mark.parametrize("terminal", [False, True])
def test_a_deleted_command_claim_cannot_vanish_from_reads_or_recovery(
    terminal: bool,
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / f"deleted-command-{'terminal' if terminal else 'prepared'}.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    key = f"deleted-command-{'terminal' if terminal else 'prepared'}"
    claimed = _claim(journal, owner="command-seal-owner", key=key)
    assert claimed.claim is not None
    if terminal:
        _store_test_plan(journal, claimed.claim)
        journal.complete_command(claimed.claim, {"status": "committed"})
    record = journal.command(claimed.claim.command_id)
    assert record is not None
    through = (record.created_at.isoformat(), record.command_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM commands WHERE command_id = ?",
            (record.command_id,),
        )

    reads = (
        lambda: journal.command(record.command_id),
        lambda: journal.latest_command_key(operation=record.operation),
        lambda: journal.command_records(
            operation=record.operation,
            after=None,
            through=through,
            limit=10,
        ),
        lambda: journal.committed_commands(
            operation=record.operation,
            after=None,
            through=through,
            limit=10,
        ),
        lambda: _claim(journal, owner="healing-owner", key=key),
    )
    for read in reads:
        with pytest.raises(JournalDamaged, match=r"positive claim seal|sealed phase"):
            read()

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM commands").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals"
            " WHERE family = 'command_claim' AND fact_key = ?",
            (record.command_id,),
        ).fetchone() == (1,)


@pytest.mark.parametrize("phase", ("plan", "terminal"))
def test_an_immutable_command_phase_cannot_be_rewritten_consistently(
    phase: str,
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / f"command-{phase}-seal.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(
        journal,
        owner=f"command-{phase}-seal",
        key=f"command-{phase}-seal",
    )
    assert claimed.claim is not None
    journal.store_command_plan(claimed.claim, _typed_test_plan({"kind": "original"}))
    if phase == "terminal":
        journal.reject_command(claimed.claim, {"status": "original"})
    with sqlite3.connect(database) as connection:
        if phase == "plan":
            connection.execute(
                "UPDATE commands SET plan_json = ? WHERE command_id = ?",
                (
                    canonical_json(_typed_test_plan({"kind": "rewritten"})),
                    claimed.claim.command_id,
                ),
            )
        else:
            connection.execute(
                "UPDATE commands SET response_json = ? WHERE command_id = ?",
                (
                    canonical_json({"status": "rewritten"}),
                    claimed.claim.command_id,
                ),
            )

    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.command(claimed.claim.command_id)
    with pytest.raises(JournalDamaged, match="positive seal"):
        _claim(
            journal,
            owner="command-phase-replay",
            key=f"command-{phase}-seal",
        )


def test_a_mismatched_request_hash_is_refused_before_any_command_row(
    control_store: ControlStore,
) -> None:
    key = "mismatched-request-hash"
    command_id = command_id_for(ACTOR.actor_id, "runs_resume", key)

    with pytest.raises(ValueError, match="does not match the canonical command request"):
        control_store.claim_command(
            actor=ACTOR,
            operation="runs_resume",
            idempotency_key=key,
            request_hash=command_request_hash({"run_id": "run-foreign"}),
            request=REQUEST,
            owner_id="owner",
            ttl_s=30,
        )

    assert control_store.command(command_id) is None


@pytest.mark.parametrize(
    "key",
    ("", " surrounded ", "x" * (IDEMPOTENCY_KEY_MAX_LENGTH + 1)),
)
def test_an_invalid_idempotency_key_is_refused_before_any_command_row(
    control_store: ControlStore,
    key: str,
) -> None:
    command_id = command_id_for(ACTOR.actor_id, "runs_resume", key)

    with pytest.raises(ValueError, match="idempotency_key"):
        _claim(control_store, owner="owner", key=key)

    assert control_store.command(command_id) is None


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
    return ApprovalRecord(
        approval_id=approval_id_for_command(
            claim.command_id,
            APPROVAL_SUBJECT.model_dump(mode="json"),
        ),
        subject=APPROVAL_SUBJECT,
        decision="approved",
        actor=ACTOR,
        run_id=RunId("run-control-contract"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _standalone_approval_plan(approval: ApprovalRecord) -> JsonValue:
    return json_value(
        StoredApprovalPlan(plan=ApprovalPlan(approval=approval)).model_dump(mode="json")
    )


def test_a_current_run_blocks_reclaim_even_after_its_command_proofs_are_deleted(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "run-dependent-command.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    manifest = sealed_test_manifest()
    request: dict[str, JsonValue] = {
        "proposal": manifest.source_graph.model_dump(mode="json"),
        "inputs": {},
    }
    key = "run-dependent-command"
    claimed = _claim(
        journal,
        owner="run-dependent-command",
        key=key,
        operation="runs_start",
        request=request,
    )
    assert claimed.claim is not None
    run_id = run_id_for_command(claimed.claim.command_id)
    origin = RunOrigin(
        kind="start",
        actor_id=ACTOR.actor_id,
        command_id=claimed.claim.command_id,
    )
    plan = RunCreationPlan(
        run_id=run_id,
        manifest=manifest,
        inputs={},
        origin=origin,
    )
    journal.store_command_plan(
        claimed.claim,
        StoredRunCreationPlan(plan=plan).model_dump(mode="json"),
    )
    journal.create_run(
        run_id,
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs={},
        origin=origin,
    )
    _delete_command_and_phase_seals(database, claimed.claim.command_id)

    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        _claim(
            journal,
            owner="run-dependent-healer",
            key=key,
            operation="runs_start",
            request=request,
        )

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM commands").fetchone() == (0,)
        assert connection.execute(
            "SELECT creation_command_id FROM runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone() == (claimed.claim.command_id,)


def test_an_approval_blocks_reclaim_even_after_its_command_proofs_are_deleted(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "approval-dependent-command.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    key = "approval-dependent-command"
    claimed = _claim(
        journal,
        owner="approval-dependent-command",
        key=key,
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    journal.store_command_plan(claimed.claim, _standalone_approval_plan(approval))
    journal.store_approval(claimed.claim, approval)
    _delete_command_and_phase_seals(database, claimed.claim.command_id)

    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        _claim(
            journal,
            owner="approval-dependent-healer",
            key=key,
            operation="runs_approve",
        )

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM commands").fetchone() == (0,)
        assert connection.execute(
            "SELECT command_id FROM approvals WHERE approval_id = ?",
            (approval.approval_id,),
        ).fetchone() == (claimed.claim.command_id,)


def test_plan_terminal_and_approval_are_write_once(control_store: ControlStore) -> None:
    claimed = _claim(control_store, owner="owner", operation="runs_approve")
    assert claimed.claim is not None
    claim = claimed.claim
    approval = _approval(claim)
    plan = _standalone_approval_plan(approval)
    control_store.store_command_plan(claim, plan)
    control_store.store_command_plan(claim, plan)
    with pytest.raises(JournalDamaged):
        control_store.store_command_plan(
            claim,
            _standalone_approval_plan(approval.model_copy(update={"decision": "rejected"})),
        )

    assert control_store.store_approval(claim, approval) == approval
    assert control_store.store_approval(claim, approval) == approval
    assert control_store.approval_for_command(claim.command_id) == approval
    with pytest.raises(JournalDamaged):
        control_store.store_approval(
            claim,
            approval.model_copy(update={"decision": "rejected"}),
        )
    with pytest.raises(JournalDamaged, match="was not minted by command"):
        control_store.store_approval(
            claim,
            approval.model_copy(update={"approval_id": "approval-other"}),
        )

    response = {"status": "committed", "value": 1}
    committed = control_store.complete_command(claim, response)
    assert control_store.complete_command(claim, response) == committed
    with pytest.raises(JournalDamaged):
        control_store.complete_command(claim, {"status": "committed", "value": 2})
    with pytest.raises(JournalDamaged):
        control_store.reject_command(claim, response)


@pytest.mark.parametrize(
    ("first", "second"),
    ((1, True), (1, 1.0), (True, 1.0)),
)
def test_json_scalar_types_are_distinct_durable_command_facts(
    control_store: ControlStore,
    first: JsonValue,
    second: JsonValue,
) -> None:
    planned = _claim(
        control_store,
        owner="typed-plan",
        key=f"typed-plan-{type(first).__name__}-{type(second).__name__}",
    )
    assert planned.claim is not None
    control_store.store_command_plan(
        planned.claim,
        _typed_test_plan({"value": first}),
    )
    with pytest.raises(JournalDamaged, match="different plan"):
        control_store.store_command_plan(
            planned.claim,
            _typed_test_plan({"value": second}),
        )

    completed = _claim(
        control_store,
        owner="typed-response",
        key=f"typed-response-{type(first).__name__}-{type(second).__name__}",
    )
    assert completed.claim is not None
    _store_test_plan(control_store, completed.claim)
    control_store.complete_command(completed.claim, {"value": first})
    with pytest.raises(JournalDamaged, match="terminal response"):
        control_store.complete_command(completed.claim, {"value": second})


def test_mutable_command_json_is_detached_at_every_store_boundary(
    control_store: ControlStore,
) -> None:
    request: dict[str, JsonValue] = {"items": ["requested"]}
    claimed = _claim(
        control_store,
        owner="detached-json",
        key="detached-json",
        request=request,
    )
    assert claimed.claim is not None
    request["items"] = ["mutated"]
    initial = control_store.command(claimed.claim.command_id)
    assert initial is not None and isinstance(initial.request, dict)
    initial.request["items"] = ["mutated-through-read"]

    payload: dict[str, JsonValue] = {"items": ["planned"]}
    plan = _typed_test_plan(payload)
    control_store.store_command_plan(claimed.claim, plan)
    payload["items"] = ["mutated"]
    projected = control_store.command(claimed.claim.command_id)
    assert projected is not None and isinstance(projected.plan, dict)
    projected.plan["items"] = ["mutated-through-read"]

    response: dict[str, JsonValue] = {"items": ["completed"]}
    terminal = control_store.complete_command(claimed.claim, response)
    response["items"] = ["mutated"]
    assert isinstance(terminal.response, dict)
    terminal.response["items"] = ["mutated-through-result"]

    stored = control_store.command(claimed.claim.command_id)
    assert stored is not None
    assert stored.request == {"items": ["requested"]}
    assert stored.plan == _typed_test_plan({"items": ["planned"]})
    assert stored.response == {"items": ["completed"]}


def test_the_exact_historical_standalone_approval_plan_remains_readable(
    control_store: ControlStore,
) -> None:
    claimed = _claim(
        control_store,
        owner="legacy-approval",
        key="legacy-approval",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    legacy_plan = {"approval": approval.model_dump(mode="json")}

    control_store.store_command_plan(claimed.claim, legacy_plan)
    assert control_store.store_approval(claimed.claim, approval) == approval
    assert control_store.approval_for_command(claimed.claim.command_id) == approval


def test_a_durable_approval_requires_an_aware_creation_time(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "approval-naive-created-at.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(
        journal,
        owner="approval-time",
        key="approval-time",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    journal.store_command_plan(claimed.claim, _standalone_approval_plan(approval))
    journal.store_approval(claimed.claim, approval)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE approvals SET created_at = ? WHERE approval_id = ?",
            ("2026-01-01T00:00:00", approval.approval_id),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="durable timestamp") as damaged:
        journal.approval(approval.approval_id)
    assert isinstance(damaged.value.__cause__, ValueError)


def test_an_approval_run_identity_cannot_be_projected_from_a_blob(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "approval-blob-run-id.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(
        journal,
        owner="approval-run-identity",
        key="approval-run-identity",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    journal.store_command_plan(claimed.claim, _standalone_approval_plan(approval))
    journal.store_approval(claimed.claim, approval)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE approvals SET run_id = ? WHERE approval_id = ?",
            (sqlite3.Binary(str(approval.run_id).encode()), approval.approval_id),
        )
        storage = connection.execute(
            "SELECT typeof(run_id) FROM approvals WHERE approval_id = ?",
            (approval.approval_id,),
        ).fetchone()
        assert storage == ("blob",)

    with pytest.raises(JournalDamaged, match="run identity is not valid durable text"):
        journal.approval(approval.approval_id)
    with pytest.raises(JournalDamaged, match="run identity is not valid durable text"):
        journal.approval_for_command(claimed.claim.command_id)


def test_a_command_cannot_reject_after_writing_its_approval(
    control_store: ControlStore,
) -> None:
    claimed = _claim(
        control_store,
        owner="reject-after-approval",
        key="reject-after-approval",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    control_store.store_command_plan(
        claimed.claim,
        _standalone_approval_plan(approval),
    )
    control_store.store_approval(claimed.claim, approval)

    with pytest.raises(
        JournalDamaged,
        match=r"cannot be rejected after writing an approval|belongs to a rejected command",
    ):
        control_store.reject_command(claimed.claim, {"status": "rejected"})

    command = control_store.command(claimed.claim.command_id)
    assert command is not None and command.state == "prepared"
    assert control_store.approval(approval.approval_id) == approval
    assert control_store.approval_for_command(claimed.claim.command_id) == approval


def test_rejection_finds_an_approval_by_its_plan_derived_identity(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "relocated-approval-owner.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(
        journal,
        owner="relocated-approval-owner",
        key="relocated-approval-owner",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    journal.store_command_plan(claimed.claim, _standalone_approval_plan(approval))
    journal.store_approval(claimed.claim, approval)
    foreign = _claim(
        journal,
        owner="relocated-approval-foreign",
        key="relocated-approval-foreign",
        operation="runs_approve",
    )
    assert foreign.claim is not None
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE approvals SET command_id = ? WHERE approval_id = ?",
            (foreign.claim.command_id, approval.approval_id),
        )
        connection.commit()

    for read in (
        lambda: journal.approval(approval.approval_id),
        lambda: journal.approval_for_command(claimed.claim.command_id),
    ):
        with pytest.raises(
            JournalDamaged,
            match=r"positive seal|sealed fact|valid durable record|minted by command",
        ):
            read()

    with pytest.raises(
        JournalDamaged,
        match=r"positive seal|sealed fact|valid durable record|minted by command",
    ):
        journal.reject_command(claimed.claim, {"status": "rejected"})

    command = journal.command(claimed.claim.command_id)
    assert command is not None
    assert command.state == "prepared"
    assert command.response is None


def test_a_deleted_approval_cannot_vanish_or_be_recreated_by_its_command(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "deleted-approval.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(
        journal,
        owner="deleted-approval",
        key="deleted-approval",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    journal.store_command_plan(claimed.claim, _standalone_approval_plan(approval))
    journal.store_approval(claimed.claim, approval)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM approvals WHERE approval_id = ?",
            (approval.approval_id,),
        )

    for read in (
        lambda: journal.approval(approval.approval_id),
        lambda: journal.approval_for_command(claimed.claim.command_id),
        lambda: journal.store_approval(claimed.claim, approval),
    ):
        with pytest.raises(JournalDamaged, match="positive seal"):
            read()

    command = journal.command(claimed.claim.command_id)
    assert command is not None and command.state == "prepared"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM approvals").fetchone() == (0,)


def test_a_valid_approval_identity_relocation_fails_from_both_selectors(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "relocated-approval-identity.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(
        journal,
        owner="approval-identity-owner",
        key="approval-identity-owner",
        operation="runs_approve",
    )
    foreign = _claim(
        journal,
        owner="approval-identity-foreign",
        key="approval-identity-foreign",
        operation="runs_approve",
    )
    assert claimed.claim is not None and foreign.claim is not None
    approval = _approval(claimed.claim)
    journal.store_command_plan(claimed.claim, _standalone_approval_plan(approval))
    journal.store_approval(claimed.claim, approval)
    foreign_id = approval_id_for_command(
        foreign.claim.command_id,
        APPROVAL_SUBJECT.model_dump(mode="json"),
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE approvals SET approval_id = ? WHERE approval_id = ?",
            (foreign_id, approval.approval_id),
        )

    for read in (
        lambda: journal.approval(approval.approval_id),
        lambda: journal.approval(foreign_id),
        lambda: journal.approval_for_command(claimed.claim.command_id),
    ):
        with pytest.raises(
            JournalDamaged,
            match=r"valid durable record|sealed fact|minted by command",
        ):
            read()


def test_an_impossible_rejected_approval_cannot_replay_as_lawful(
    control_store: ControlStore,
    control_clock: MutableClock,
) -> None:
    claimed = _claim(
        control_store,
        owner="reject-approval-replay",
        key="reject-approval-replay",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    control_store.store_command_plan(
        claimed.claim,
        _standalone_approval_plan(approval),
    )
    control_store.store_approval(claimed.claim, approval)
    response: dict[str, JsonValue] = {"status": "rejected"}

    if isinstance(control_store, InMemoryControlStore):
        record = control_store._commands[claimed.claim.command_id]
        control_store._commands[claimed.claim.command_id] = record.model_copy(
            update={
                "state": "rejected",
                "response": response,
                "owner_id": None,
                "lease_expires_at": None,
                "updated_at": control_clock.now(),
                "completed_at": control_clock.now(),
            }
        )
    else:
        assert isinstance(control_store, SqliteJournal)
        with sqlite3.connect(control_store._db_path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute(
                "UPDATE commands SET state = 'rejected', response_json = ?,"
                " owner_id = NULL, lease_expires_at = NULL, updated_at = ?,"
                " completed_at = ? WHERE command_id = ?",
                (
                    canonical_json(response),
                    control_clock.now().isoformat(),
                    control_clock.now().isoformat(),
                    claimed.claim.command_id,
                ),
            )
            impossible = connection.execute(
                "SELECT * FROM commands WHERE command_id = ?",
                (claimed.claim.command_id,),
            ).fetchone()
            assert impossible is not None
            # Test-only impossible history: retain an internally coherent
            # terminal phase so this regression reaches the independent
            # approval-vs-rejection contradiction it is meant to exercise.
            seal_command_phases(connection, impossible)
            connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=r"cannot be rejected after writing an approval|belongs to a rejected command",
    ):
        control_store.reject_command(claimed.claim, response)


def test_in_memory_approval_reads_revalidate_their_command_provenance(
    control_clock: MutableClock,
) -> None:
    store = InMemoryControlStore(now_fn=control_clock.now)
    claimed = _claim(
        store,
        owner="damaged-approval-projection",
        key="damaged-approval-projection",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    store.store_command_plan(claimed.claim, _standalone_approval_plan(approval))
    store.store_approval(claimed.claim, approval)
    command = store.command(claimed.claim.command_id)
    assert command is not None
    store._commands[command.command_id] = command.model_copy(update={"state": "rejected"})

    with pytest.raises(JournalDamaged, match="belongs to a rejected command"):
        store.approval(approval.approval_id)
    with pytest.raises(JournalDamaged, match="belongs to a rejected command"):
        store.approval_for_command(command.command_id)


def test_an_explicit_null_cannot_turn_a_bound_request_key_into_absence(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "null-request-message-id.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(
        journal,
        owner="null-request-message-id",
        key="null-request-message-id",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    journal.store_command_plan(claimed.claim, _standalone_approval_plan(approval))
    journal.store_approval(claimed.claim, approval)
    tampered = {**APPROVAL_REQUEST, "request_message_id": None}

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET request_json = ?, request_hash = ? WHERE command_id = ?",
            (
                canonical_json(tampered),
                str(command_request_hash(tampered)),
                claimed.claim.command_id,
            ),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"request-bound plan|positive seal"):
        journal.approval(approval.approval_id)


def test_the_standalone_writer_refuses_a_request_bound_approval(
    control_store: ControlStore,
) -> None:
    request_id = Digest("sha256:" + "a" * 64)
    claimed = _claim(
        control_store,
        owner="bound-through-standalone-writer",
        key="bound-through-standalone-writer",
        operation="runs_approve",
        request={**APPROVAL_REQUEST, "request_message_id": str(request_id)},
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    reply_port = "decision"
    plan = ChannelApprovalPlan(
        approval=approval,
        channel_id="channel/approval",
        request_id=request_id,
        reply_id=reply_message_id(request_id=request_id, reply_port=reply_port),
        reply_port=reply_port,
        payload=approval_decision_payload(approval),
        ack_actor_id=ACTOR.actor_id,
        run_id=approval.run_id,
        parked_event_seq=1,
    )
    control_store.store_command_plan(
        claimed.claim,
        StoredApprovalPlan(plan=plan).model_dump(mode="json"),
    )

    with pytest.raises(JournalDamaged, match="must be written as one channel exchange"):
        control_store.store_approval(claimed.claim, approval)

    assert control_store.approval(approval.approval_id) is None


def test_an_approval_cannot_claim_another_authenticated_actor(
    control_store: ControlStore,
) -> None:
    claimed = _claim(
        control_store,
        owner="approval-actor",
        key="approval-actor",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    forged = approval.model_copy(
        update={
            "actor": approval.actor.model_copy(
                update={"display_name": "a different authenticated principal"}
            )
        }
    )

    with pytest.raises(JournalDamaged, match="actor contradicts its authenticated command"):
        control_store.store_approval(claimed.claim, forged)

    assert control_store.approval(forged.approval_id) is None
    assert control_store.approval_for_command(claimed.claim.command_id) is None


def test_an_approval_id_must_be_minted_by_its_command_and_subject(
    control_store: ControlStore,
) -> None:
    claimed = _claim(
        control_store,
        owner="approval-identity",
        key="approval-identity",
        operation="runs_approve",
    )
    assert claimed.claim is not None
    forged = _approval(claimed.claim).model_copy(update={"approval_id": "approval-forged"})

    with pytest.raises(JournalDamaged, match="was not minted by command"):
        control_store.store_approval(claimed.claim, forged)

    assert control_store.approval(forged.approval_id) is None
    assert control_store.approval_for_command(claimed.claim.command_id) is None


def test_only_an_exact_runs_approve_claim_can_store_an_approval(
    control_store: ControlStore,
) -> None:
    claimed = _claim(control_store, owner="wrong-operation", key="wrong-operation")
    assert claimed.claim is not None
    approval = _approval(claimed.claim)

    with pytest.raises(JournalDamaged, match="command other than runs_approve"):
        control_store.store_approval(claimed.claim, approval)

    forged = claimed.claim.model_copy(update={"operation": "runs_approve"})
    with pytest.raises(JournalDamaged, match="contradicts its durable identity"):
        control_store.store_command_plan(forged, {"kind": "forged"})
    assert control_store.approval(approval.approval_id) is None
    assert control_store.approval_for_command(claimed.claim.command_id) is None


def test_rejected_terminal_is_write_once(control_store: ControlStore) -> None:
    claimed = _claim(control_store, owner="owner", key="rejected")
    assert claimed.claim is not None
    _store_test_plan(control_store, claimed.claim)
    response = {"status": "rejected", "faults": []}
    rejected = control_store.reject_command(claimed.claim, response)
    assert control_store.reject_command(claimed.claim, response) == rejected
    with pytest.raises(JournalDamaged):
        control_store.reject_command(claimed.claim, {"status": "rejected"})


@pytest.mark.parametrize("terminal", ("committed", "rejected"))
def test_a_command_cannot_become_terminal_without_an_immutable_plan(
    control_store: ControlStore,
    terminal: str,
) -> None:
    claimed = _claim(
        control_store,
        owner=f"planless-{terminal}",
        key=f"planless-{terminal}",
    )
    assert claimed.claim is not None
    finish = (
        control_store.complete_command
        if terminal == "committed"
        else control_store.reject_command
    )

    with pytest.raises(JournalDamaged, match="without an immutable plan"):
        finish(claimed.claim, {"status": terminal})

    stored = control_store.command(claimed.claim.command_id)
    assert stored is not None
    assert stored.state == "prepared"
    assert stored.plan is None
    assert stored.response is None
    assert stored.completed_at is None


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
@pytest.mark.parametrize("terminal", ("committed", "rejected"))
def test_an_exact_terminal_retry_needs_no_new_observation(
    kind: str,
    terminal: str,
    tmp_path: Path,
) -> None:
    class RefusingClock(MutableClock):
        refuse = False

        def now(self) -> datetime:
            if self.refuse:
                raise RuntimeError("timestamp unavailable")
            return super().now()

    clock = RefusingClock()
    store: ControlStore = (
        InMemoryControlStore(now_fn=clock.now)
        if kind == "memory"
        else SqliteJournal(tmp_path / f"terminal-{terminal}.db", now_fn=clock.now)
    )
    claimed = _claim(store, owner="owner", key=f"terminal-{terminal}")
    assert claimed.claim is not None
    _store_test_plan(store, claimed.claim)
    response = {"status": terminal}
    finish = store.complete_command if terminal == "committed" else store.reject_command
    first = finish(claimed.claim, response)

    clock.refuse = True
    replayed = finish(claimed.claim, response)

    assert replayed == first


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_claiming_an_exact_terminal_command_needs_no_new_observation(
    kind: str,
    tmp_path: Path,
) -> None:
    class RefusingClock(MutableClock):
        refuse = False

        def now(self) -> datetime:
            if self.refuse:
                raise RuntimeError("timestamp unavailable")
            return super().now()

    clock = RefusingClock()
    store: ControlStore = (
        InMemoryControlStore(now_fn=clock.now)
        if kind == "memory"
        else SqliteJournal(tmp_path / "terminal-claim.db", now_fn=clock.now)
    )
    claimed = _claim(store, owner="owner", key="terminal-claim")
    assert claimed.claim is not None
    _store_test_plan(store, claimed.claim)
    terminal = store.complete_command(claimed.claim, {"status": "committed"})

    clock.refuse = True
    replayed = _claim(store, owner="other-owner", key="terminal-claim")
    conflict = _claim(
        store,
        owner="other-owner",
        key="terminal-claim",
        request={"run_id": "run-other"},
    )

    assert replayed.status == "replayed"
    assert replayed.record == terminal
    assert conflict.status == "conflict"
    assert conflict.record == terminal


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_a_prepared_claim_observes_each_lease_decision(
    kind: str,
    tmp_path: Path,
) -> None:
    class CountingClock(MutableClock):
        calls = 0

        def now(self) -> datetime:
            self.calls += 1
            return super().now()

    clock = CountingClock()
    store: ControlStore = (
        InMemoryControlStore(now_fn=clock.now)
        if kind == "memory"
        else SqliteJournal(tmp_path / "prepared-claim-clock.db", now_fn=clock.now)
    )
    first = _claim(store, owner="owner-a", key="prepared-clock")
    assert first.status == "claimed"
    assert clock.calls == 1

    live = _claim(store, owner="owner-b", key="prepared-clock")
    assert live.status == "in_progress"
    assert clock.calls == 2

    clock.advance(31)
    reclaimed = _claim(store, owner="owner-b", key="prepared-clock")
    assert reclaimed.status == "claimed"
    assert reclaimed.claim is not None and reclaimed.claim.epoch == 2
    assert clock.calls == 3


def test_committed_command_keyset_is_bounded_and_filtered(
    control_store: ControlStore,
) -> None:
    committed_ids: list[str] = []
    for index in range(4):
        claimed = _claim(control_store, owner="owner", key=f"resume-{index}")
        assert claimed.claim is not None
        _store_test_plan(control_store, claimed.claim)
        control_store.complete_command(claimed.claim, {"index": index})
        committed_ids.append(claimed.claim.command_id)
    rejected = _claim(control_store, owner="owner", key="resume-rejected")
    assert rejected.claim is not None
    _store_test_plan(control_store, rejected.claim)
    control_store.reject_command(rejected.claim, {"status": "rejected"})
    other = _claim(
        control_store,
        owner="owner",
        key="cancel",
        operation="runs_cancel",
    )
    assert other.claim is not None
    _store_test_plan(control_store, other.claim)
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
    first.store_command_plan(
        claimed.claim,
        _typed_test_plan({"kind": "exact", "values": [1, 2]}),
    )
    expected = first.complete_command(claimed.claim, {"status": "committed"})
    reopened = SqliteJournal(path, now_fn=control_clock.now)
    assert reopened.command(claimed.claim.command_id) == expected
    through = reopened.latest_command_key(operation="runs_resume")
    assert through is not None
    assert reopened.committed_commands(
        operation="runs_resume", after=None, through=through, limit=1
    ) == (expected,)


def test_a_corrupt_persisted_command_actor_is_durable_journal_damage(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "corrupt-command-actor.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(journal, owner="owner", key="corrupt-command-actor")
    assert claimed.claim is not None
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT actor_json FROM commands WHERE command_id = ?",
            (claimed.claim.command_id,),
        ).fetchone()
        assert row is not None
        actor = json.loads(row[0])
        actor["actor_id"] = "control-contract"
        connection.execute(
            "UPDATE commands SET actor_json = ? WHERE command_id = ?",
            (json.dumps(actor), claimed.claim.command_id),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=rf"command row {claimed.claim.command_id!r} is not a valid durable record",
    ) as damaged:
        SqliteJournal(database, now_fn=control_clock.now)
    assert isinstance(damaged.value.__cause__, ValidationError)


def test_a_persisted_command_actor_is_projected_losslessly(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "lossy-command-actor.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(journal, owner="owner", key="lossy-command-actor")
    assert claimed.claim is not None
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT actor_json FROM commands WHERE command_id = ?",
            (claimed.claim.command_id,),
        ).fetchone()
        assert row is not None
        actor = json.loads(row[0])
        actor["scopes"].append(actor["scopes"][0])
        connection.execute(
            "UPDATE commands SET actor_json = ? WHERE command_id = ?",
            (json.dumps(actor), claimed.claim.command_id),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.command(claimed.claim.command_id)
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "parsing is not lossless" in str(damaged.value.__cause__)


def test_a_command_text_column_cannot_be_projected_from_a_blob(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "command-blob-operation.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(journal, owner="owner", key="command-blob-operation")
    assert claimed.claim is not None
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET operation = ? WHERE command_id = ?",
            (sqlite3.Binary(b"runs_resume"), claimed.claim.command_id),
        )
        storage = connection.execute(
            "SELECT typeof(operation) FROM commands WHERE command_id = ?",
            (claimed.claim.command_id,),
        ).fetchone()
        assert storage == ("blob",)

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.command(claimed.claim.command_id)
    assert isinstance(damaged.value.__cause__, JournalDamaged)
    assert "operation is not valid durable text" in str(damaged.value.__cause__)


def test_a_command_digest_cannot_be_projected_from_a_blob(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "command-blob-request-hash.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(journal, owner="owner", key="command-blob-request-hash")
    assert claimed.claim is not None
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT request_hash FROM commands WHERE command_id = ?",
            (claimed.claim.command_id,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        connection.execute(
            "UPDATE commands SET request_hash = ? WHERE command_id = ?",
            (sqlite3.Binary(row[0].encode()), claimed.claim.command_id),
        )
        storage = connection.execute(
            "SELECT typeof(request_hash) FROM commands WHERE command_id = ?",
            (claimed.claim.command_id,),
        ).fetchone()
        assert storage == ("blob",)

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.command(claimed.claim.command_id)
    assert isinstance(damaged.value.__cause__, JournalDamaged)
    assert "request hash is not a valid durable digest" in str(damaged.value.__cause__)


def test_a_command_sequence_cannot_be_normalized_from_a_real_column(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "command-real-owner-epoch.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(journal, owner="owner", key="command-real-owner-epoch")
    assert claimed.claim is not None
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE rebuilt_commands AS SELECT command_id, actor_id, actor_json,"
            " operation, idempotency_key, request_hash, request_json, plan_json, state,"
            " response_json, owner_id, CAST(owner_epoch AS REAL) AS owner_epoch,"
            " lease_expires_at, created_at, updated_at, completed_at FROM commands"
        )
        connection.execute("DROP TABLE commands")
        connection.execute("ALTER TABLE rebuilt_commands RENAME TO commands")
        storage = connection.execute(
            "SELECT typeof(owner_epoch) FROM commands WHERE command_id = ?",
            (claimed.claim.command_id,),
        ).fetchone()
        assert storage == ("real",)

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.command(claimed.claim.command_id)
    assert isinstance(damaged.value.__cause__, JournalDamaged)
    assert "owner epoch is not a valid durable owner epoch" in str(damaged.value.__cause__)


@pytest.mark.parametrize(
    ("field", "terminal"),
    (
        ("created_at", False),
        ("updated_at", False),
        ("lease_expires_at", False),
        ("completed_at", True),
    ),
)
def test_command_timestamps_are_strictly_aware_durable_facts(
    field: str,
    terminal: bool,
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / f"command-naive-{field}.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(journal, owner="owner", key=f"command-naive-{field}")
    assert claimed.claim is not None
    if terminal:
        _store_test_plan(journal, claimed.claim)
        journal.complete_command(claimed.claim, {"status": "committed"})
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE commands SET {field} = ? WHERE command_id = ?",
            ("2026-01-01T00:00:00", claimed.claim.command_id),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.command(claimed.claim.command_id)
    assert isinstance(damaged.value.__cause__, JournalDamaged)
    assert "durable timestamp" in str(damaged.value.__cause__)


def test_a_malformed_command_time_cannot_become_a_cursor_cut(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "command-cursor-time.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(journal, owner="owner", key="command-cursor-time")
    assert claimed.claim is not None
    _store_test_plan(journal, claimed.claim)
    journal.complete_command(claimed.claim, {"status": "committed"})
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET created_at = ? WHERE command_id = ?",
            ("not-a-timestamp", claimed.claim.command_id),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable record"):
        journal.latest_command_key(operation="runs_resume")


@pytest.mark.parametrize(
    ("terminal", "field", "value"),
    (
        (False, "response_json", "null"),
        (False, "completed_at", "2026-01-01T00:00:00+00:00"),
        (False, "owner_id", None),
        (False, "lease_expires_at", None),
        (True, "response_json", None),
        (True, "response_json", "null"),
        (True, "plan_json", None),
        (True, "plan_json", "null"),
        (True, "completed_at", None),
        (True, "owner_id", "foreign-owner"),
        (True, "lease_expires_at", "2026-01-01T00:00:00+00:00"),
    ),
)
def test_a_command_row_must_have_one_coherent_lifecycle_shape(
    terminal: bool,
    field: str,
    value: str | None,
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / f"command-lifecycle-{terminal}-{field}.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(
        journal,
        owner="lifecycle-owner",
        key=f"lifecycle-{terminal}-{field}",
    )
    assert claimed.claim is not None
    if terminal:
        _store_test_plan(journal, claimed.claim)
        journal.complete_command(claimed.claim, {"status": "committed"})

    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE commands SET {field} = ? WHERE command_id = ?",
            (value, claimed.claim.command_id),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=rf"command row {claimed.claim.command_id!r} is not a valid durable record",
    ) as damaged:
        journal.command(claimed.claim.command_id)
    assert isinstance(damaged.value.__cause__, ValueError)


@pytest.mark.parametrize("field", ("plan_json", "response_json"))
def test_a_command_row_cannot_project_nonfinite_json(
    field: str,
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / f"command-nonfinite-{field}.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(
        journal,
        owner="nonfinite-owner",
        key=f"nonfinite-{field}",
    )
    assert claimed.claim is not None
    _store_test_plan(journal, claimed.claim)
    journal.complete_command(claimed.claim, {"status": "committed"})

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            f"SELECT {field} FROM commands WHERE command_id = ?",
            (claimed.claim.command_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        assert isinstance(payload, dict)
        payload["nonfinite"] = float("nan")
        connection.execute(
            f"UPDATE commands SET {field} = ? WHERE command_id = ?",
            (json.dumps(payload), claimed.claim.command_id),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=rf"command row {claimed.claim.command_id!r} is not a valid durable record",
    ) as damaged:
        journal.command(claimed.claim.command_id)
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "NaN" in str(damaged.value.__cause__)


@pytest.mark.parametrize(
    ("field", "key", "shadow"),
    (
        ("actor_json", "actor_id", "static:shadow"),
        ("plan_json", "kind", "shadow-plan"),
    ),
)
def test_a_command_row_cannot_collapse_duplicate_json_authority(
    field: str,
    key: str,
    shadow: str,
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    """Even equal projected content cannot excuse contradictory source bytes."""

    database = tmp_path / f"command-duplicate-{field}.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(journal, owner="duplicate-owner", key=f"duplicate-{field}")
    assert claimed.claim is not None
    _store_test_plan(journal, claimed.claim)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            f"SELECT {field} FROM commands WHERE command_id = ?",
            (claimed.claim.command_id,),
        ).fetchone()
        assert row is not None
        raw = str(row[0])
        duplicated = raw.replace(
            f'"{key}":',
            f'"{key}":{json.dumps(shadow)},"{key}":',
            1,
        )
        assert duplicated != raw
        connection.execute(
            f"UPDATE commands SET {field} = ? WHERE command_id = ?",
            (duplicated, claimed.claim.command_id),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=rf"command row {claimed.claim.command_id!r} is not a valid durable record",
    ) as damaged:
        journal.command(claimed.claim.command_id)
    assert isinstance(damaged.value.__cause__, ValueError)
    assert f"repeats key {key!r}" in str(damaged.value.__cause__)


@pytest.mark.parametrize("field", ("idempotency_key", "request_hash"))
def test_a_loser_cannot_replay_a_command_with_tampered_durable_identity(
    field: str,
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / f"corrupt-command-{field}.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    key = f"corrupt-{field}"
    claimed = _claim(journal, owner="winner", key=key)
    assert claimed.claim is not None
    replacement = (
        "foreign-idempotency-key"
        if field == "idempotency_key"
        else str(digest("control-request", 1, {"run_id": "run-foreign"}))
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE commands SET {field} = ? WHERE command_id = ?",
            (replacement, claimed.claim.command_id),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=rf"command row {claimed.claim.command_id!r} is not a valid durable record",
    ):
        _claim(journal, owner="loser", key=key)


def test_a_durable_command_with_a_noncanonical_key_is_journal_damage(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "corrupt-command-key-shape.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    claimed = _claim(journal, owner="owner", key="canonical-key")
    assert claimed.claim is not None
    invalid_key = " surrounded "
    invalid_id = command_id_for(ACTOR.actor_id, "runs_resume", invalid_key)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET command_id = ?, idempotency_key = ? WHERE command_id = ?",
            (invalid_id, invalid_key, claimed.claim.command_id),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=rf"command row {invalid_id!r} is not a valid durable record",
    ):
        journal.command(invalid_id)


def test_a_corrupt_persisted_run_origin_actor_is_durable_journal_damage(
    tmp_path: Path,
    control_clock: MutableClock,
) -> None:
    database = tmp_path / "corrupt-origin-actor.db"
    journal = SqliteJournal(database, now_fn=control_clock.now)
    manifest = sealed_test_manifest()
    request = {
        "proposal": manifest.source_graph.model_dump(mode="json"),
        "inputs": {},
    }
    claimed = _claim(
        journal,
        owner="owner",
        key="corrupt-origin-actor",
        operation="runs_start",
        request=request,
    )
    assert claimed.claim is not None
    run_id = run_id_for_command(claimed.claim.command_id)
    origin = RunOrigin(
        kind="start",
        actor_id=ACTOR.actor_id,
        command_id=claimed.claim.command_id,
    )
    plan = RunCreationPlan(
        run_id=run_id,
        manifest=manifest,
        inputs={},
        origin=origin,
    )
    journal.store_command_plan(
        claimed.claim,
        StoredRunCreationPlan(plan=plan).model_dump(mode="json"),
    )
    journal.create_run(
        run_id,
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs={},
        origin=origin,
    )
    reopened = SqliteJournal(database, now_fn=control_clock.now)
    damaged_origin = origin.model_dump(mode="json")
    damaged_origin["actor_id"] = "control-contract"
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "UPDATE run_origins SET origin_json = ? WHERE run_id = ?",
            (json.dumps(damaged_origin), run_id),
        )
        row = connection.execute(
            "SELECT r.*, o.origin_json FROM runs AS r"
            " JOIN run_origins AS o ON o.run_id = r.run_id WHERE r.run_id = ?",
            (run_id,),
        ).fetchone()
        assert row is not None
        # Explicitly construct impossible history whose outer immutable-world
        # seal agrees. The independent origin identity must still refuse the
        # actor rewrite before any caller can observe a normalized origin.
        connection.execute(
            "UPDATE durable_fact_seals SET fact_hash = ?"
            " WHERE family = 'run_world' AND fact_key = ?",
            (str(run_world_fact_hash(row)), run_id),
        )
        connection.commit()

    for read in (reopened.run_origin, reopened.run_record):
        with pytest.raises(
            JournalDamaged,
            match="run origin history contradicts its derived identity",
        ):
            read(run_id)


def test_command_identity_remains_actor_operation_key_derived() -> None:
    assert command_id_for(ACTOR.actor_id, "runs_resume", "same-key").startswith("cmd-")
    assert digest("control-request", 1, REQUEST) == REQUEST_HASH


class OffsetClock:
    """Rising instants whose ISO text falls — a legal aware-datetime stream."""

    def __init__(self) -> None:
        self._instant = datetime(2026, 1, 1, 10, tzinfo=UTC)
        self._calls = 0

    def now(self) -> datetime:
        self._instant += timedelta(minutes=30)
        self._calls += 1
        # Claim and completion each read the clock, so flip the offset every
        # second call: consecutive commands then disagree on instant vs text.
        zone = UTC if (self._calls - 1) // 2 % 2 == 0 else timezone(timedelta(hours=-5))
        return self._instant.astimezone(zone)


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_committed_paging_orders_on_the_key_it_bounds_on(
    kind: str,
    tmp_path: Path,
) -> None:
    """Both stores page committed commands in one order: the ISO text key.

    `after` and `through` are compared as ISO text, so ordering by the
    underlying instant instead would let a record fall between two watermarks
    and never be delivered — the run host would silently never launch its
    resume.
    """

    clock = OffsetClock()
    store: ControlStore = (
        InMemoryControlStore(now_fn=clock.now)
        if kind == "memory"
        else SqliteJournal(tmp_path / "offsets.db", now_fn=clock.now)
    )
    for index in range(6):
        claimed = _claim(store, owner="owner", key=f"resume-offset-{index}")
        assert claimed.claim is not None
        _store_test_plan(store, claimed.claim)
        store.complete_command(claimed.claim, {"index": index})
    through = store.latest_command_key(operation="runs_resume")
    assert through is not None

    delivered: list[tuple[str, str]] = []
    after: tuple[str, str] | None = None
    for _ in range(6):
        page = store.committed_commands(
            operation="runs_resume", after=after, through=through, limit=2
        )
        if not page:
            break
        delivered.extend((record.created_at.isoformat(), record.command_id) for record in page)
        after = delivered[-1]

    assert delivered == sorted(delivered)
    assert len(delivered) == len(set(delivered)) == 6
