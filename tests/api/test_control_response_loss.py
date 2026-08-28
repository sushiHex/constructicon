"""M6 command recovery at every durable response-loss seam."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.core.address import RunId
from constructicon.core.control import (
    ADMIN_SCOPE,
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    READ_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    CancellationResult,
    ControlCode,
    ControlRejected,
    PromotionCommandResult,
    RegistrationCommandResult,
    RunSubmission,
    command_id_for,
)
from constructicon.core.effect import (
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.run import RunStatus
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import (
    BRIEF,
    ISSUE,
    FakeClock,
    InjectedCrash,
    atomic,
    await_attempt_terminal,
    pipeline_graph,
    triage_impl,
)

RUN_ACTOR = AuthenticatedActor(
    actor_id="static:response-loss-runner",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
)
AUTHORITY_ACTOR = AuthenticatedActor(
    actor_id="static:response-loss-authority",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, APPROVE_SCOPE, PROMOTE_SCOPE}),
)
LOCAL_ADMIN = AuthenticatedActor(
    actor_id="static:response-loss-admin",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, ADMIN_SCOPE}),
)

SEAMS = (
    "after_plan",
    "after_domain_mutation",
    "after_command_completion",
)


class _PassiveHost:
    """A host boundary that records handoffs without scheduling graph units."""

    def __init__(self) -> None:
        self.launches: list[tuple[RunId, dict[str, Any]]] = []

    def _configure_committed_resumes(self, store: Any, decoder: Any) -> None:
        self.store = store
        self.decoder = decoder

    async def startup(self) -> None:
        return None

    async def abort_startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def launch(self, run_id: RunId, **kwargs: Any) -> str:
        self.launches.append((run_id, kwargs))
        return "queued"


def _crash_at(operation: str, seam: str):
    target = f"{operation}.{seam}"

    def crash(name: str) -> None:
        if name == target:
            raise InjectedCrash(name)

    return crash


async def _expect_crash(call) -> None:
    with pytest.raises(InjectedCrash):
        await call()


def _fresh_control(
    world,
    journal: SqliteJournal,
    owner: str,
    *,
    fault_probe=None,
    run_host: RunHost | None = None,
) -> ControlPlane:
    return ControlPlane(
        system=world,
        store=journal,
        run_host=run_host or RunHost(world, journal=journal, max_concurrency=1),
        owner_id=owner,
        command_ttl_s=30,
        fault_probe=fault_probe,
    )


def _terminal_response_bytes(journal: SqliteJournal, operation: str) -> str:
    key = journal.latest_command_key(operation=operation)
    assert key is not None
    command = journal.command(key[1])
    assert command is not None and command.response is not None
    return canonical_json(command.response)


def _prepare_live_run(world: Any, journal: SqliteJournal, suffix: str) -> RunId:
    inputs = {"issue": {"title": suffix}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId(f"run-response-loss-{suffix}")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    lease = journal.claim_run(run_id, owner_id=f"live-{suffix}", ttl_s=300)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    return run_id


def _prepare_failed_run(world: Any, journal: SqliteJournal, suffix: str) -> RunId:
    inputs = {"issue": {"title": suffix}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId(f"run-response-loss-{suffix}")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    lease = journal.claim_run(run_id, owner_id=f"failed-{suffix}", ttl_s=300)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED,
        event_kind="RunFailed",
    )
    journal.release_run(lease)
    return run_id


def _candidate(world, component: str) -> tuple[Digest, Digest, str]:
    definition, impl = atomic(component, (ISSUE,), (BRIEF,), triage_impl)
    v1 = world._register(definition, impl)
    world._promote_initial(component=component, version=v1)
    changed = definition.model_copy(update={"role": "component"})
    v2 = world._register(changed, impl)
    draft = AttestationDraft(
        action="promote",
        subject=ComponentProofSubject(
            component=component,
            version=v2,
            baseline_version=v1,
        ),
        checks=(
            CheckResult(
                name="response-loss-evaluation",
                status="passed",
                detail="candidate passed its pinned evaluation",
                elapsed_s=0.0,
            ),
        ),
        check_set_hash=digest("check-set", 1, {"policy": "response-loss", "v": 1}),
        evidence=(),
        manifest_hash=digest("manifest", 1, {"response-loss": component}),
        workspace_id=None,
    )
    attestation = world._journal.mint_policy_attestation(draft)
    return v1, v2, attestation.attestation_id


@pytest.mark.parametrize("seam", SEAMS)
async def test_runs_start_recovers_each_response_loss_seam(
    seam: str,
    world,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    control_a = _fresh_control(
        world,
        journal,
        "control-start-a",
        fault_probe=_crash_at("runs_start", seam),
    )

    async def invoke_a():
        return await control_a.runs_start(
            RUN_ACTOR,
            proposal=pipeline_graph(),
            inputs={"issue": {"title": f"start-{seam}"}},
            idempotency_key=f"start-{seam}",
        )

    await _expect_crash(invoke_a)
    clock.advance(31)
    control_b = _fresh_control(world, journal, "control-start-b")
    recovered = await control_b.runs_start(
        RUN_ACTOR,
        proposal=pipeline_graph(),
        inputs={"issue": {"title": f"start-{seam}"}},
        idempotency_key=f"start-{seam}",
    )
    assert isinstance(recovered, RunSubmission)
    assert recovered.command.replayed is (seam == "after_command_completion")
    terminal = await await_attempt_terminal(journal, recovered.run_id, baseline_event_seq=0)
    assert terminal.kind == "RunSucceeded"
    assert [record.run_id for record in journal.run_records(limit=100)].count(recovered.run_id) == 1

    replay = await control_b.runs_start(
        RUN_ACTOR,
        proposal=pipeline_graph(),
        inputs={"issue": {"title": f"start-{seam}"}},
        idempotency_key=f"start-{seam}",
    )
    assert isinstance(replay, RunSubmission)
    assert replay.run_id == recovered.run_id
    assert replay.command.replayed is True
    await control_a.shutdown()
    await control_b.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_approval_recovers_each_response_loss_seam(
    seam: str,
    world,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    manifest = world.validate(pipeline_graph(), {"issue": {"title": f"approve-{seam}"}})
    run_id = RunId(f"run-approve-{seam.replace('_', '-')}")
    world._prepare_run(manifest, run_id=run_id, inputs={"issue": {"title": f"approve-{seam}"}})
    stable = world._registry.stable_version("test/triage")
    assert stable is not None
    subject = ComponentProofSubject(
        component="test/triage",
        version=stable,
        baseline_version=stable,
    )

    control_a = _fresh_control(
        world,
        journal,
        "control-approval-a",
        fault_probe=_crash_at("runs_approve", seam),
    )

    async def invoke_a():
        return await control_a.runs_approve(
            AUTHORITY_ACTOR,
            run_id=run_id,
            subject=subject,
            decision="approved",
            reason="response-loss test",
            idempotency_key=f"approve-{seam}",
        )

    await _expect_crash(invoke_a)
    clock.advance(31)
    control_b = _fresh_control(world, journal, "control-approval-b")
    recovered = await control_b.runs_approve(
        AUTHORITY_ACTOR,
        run_id=run_id,
        subject=subject,
        decision="approved",
        reason="response-loss test",
        idempotency_key=f"approve-{seam}",
    )
    assert isinstance(recovered, ApprovalCommandResult)
    assert recovered.command.replayed is (seam == "after_command_completion")
    approval = journal.approval(recovered.approval_id)
    assert approval is not None and approval.decision == "approved"

    replay = await control_b.runs_approve(
        AUTHORITY_ACTOR,
        run_id=run_id,
        subject=subject,
        decision="approved",
        reason="response-loss test",
        idempotency_key=f"approve-{seam}",
    )
    assert isinstance(replay, ApprovalCommandResult)
    assert replay.approval_id == recovered.approval_id
    assert replay.command.replayed is True
    await control_a.shutdown()
    await control_b.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_promotion_recovers_each_response_loss_seam(
    seam: str,
    world,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    component = f"control/promotion-{seam.replace('_', '-')}"
    v1, v2, attestation_id = _candidate(world, component)
    control_a = _fresh_control(
        world,
        journal,
        "control-promotion-a",
        fault_probe=_crash_at("registry_promote", seam),
    )

    async def invoke_a():
        return await control_a.registry_promote(
            AUTHORITY_ACTOR,
            component=component,
            version=v2,
            attestation_id=attestation_id,
            idempotency_key=f"promote-{seam}",
        )

    await _expect_crash(invoke_a)
    clock.advance(31)
    control_b = _fresh_control(world, journal, "control-promotion-b")
    recovered = await control_b.registry_promote(
        AUTHORITY_ACTOR,
        component=component,
        version=v2,
        attestation_id=attestation_id,
        idempotency_key=f"promote-{seam}",
    )
    assert isinstance(recovered, PromotionCommandResult)
    assert recovered.status == "promoted"
    assert recovered.command.replayed is (seam == "after_command_completion")
    assert world._registry.stable_version(component) == v2
    assert world._registry.snapshot().history[component] == ((None, str(v1)), (str(v1), str(v2)))

    replay = await control_b.registry_promote(
        AUTHORITY_ACTOR,
        component=component,
        version=v2,
        attestation_id=attestation_id,
        idempotency_key=f"promote-{seam}",
    )
    assert isinstance(replay, PromotionCommandResult)
    assert replay.command.replayed is True
    await control_a.shutdown()
    await control_b.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_rollback_recovers_each_response_loss_seam(
    seam: str,
    world,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    component = f"control/rollback-{seam.replace('_', '-')}"
    v1, v2, attestation_id = _candidate(world, component)
    world._promote_version(
        component=component,
        version=v2,
        attestation_id=attestation_id,
        actor="setup",
    )
    control_a = _fresh_control(
        world,
        journal,
        "control-rollback-a",
        fault_probe=_crash_at("registry_rollback", seam),
    )

    async def invoke_a():
        return await control_a.registry_rollback(
            AUTHORITY_ACTOR,
            component=component,
            expected_stable=v2,
            idempotency_key=f"rollback-{seam}",
        )

    await _expect_crash(invoke_a)
    clock.advance(31)
    control_b = _fresh_control(world, journal, "control-rollback-b")
    recovered = await control_b.registry_rollback(
        AUTHORITY_ACTOR,
        component=component,
        expected_stable=v2,
        idempotency_key=f"rollback-{seam}",
    )
    assert isinstance(recovered, PromotionCommandResult)
    assert recovered.status == "rolled_back"
    assert recovered.command.replayed is (seam == "after_command_completion")
    assert world._registry.stable_version(component) == v1
    assert len(world._registry.snapshot().history[component]) == 3

    replay = await control_b.registry_rollback(
        AUTHORITY_ACTOR,
        component=component,
        expected_stable=v2,
        idempotency_key=f"rollback-{seam}",
    )
    assert isinstance(replay, PromotionCommandResult)
    assert replay.to_version == v1
    assert replay.command.replayed is True
    await control_a.shutdown()
    await control_b.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_cancel_recovers_each_response_loss_seam(
    seam: str,
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    run_id = _prepare_live_run(world, journal, f"cancel-{seam}")
    host_a = cast(RunHost, _PassiveHost())
    control_a = _fresh_control(
        world,
        journal,
        "control-cancel-a",
        fault_probe=_crash_at("runs_cancel", seam),
        run_host=host_a,
    )
    with pytest.raises(InjectedCrash):
        await control_a.runs_cancel(
            RUN_ACTOR,
            run_id=run_id,
            idempotency_key=f"cancel-{seam}",
        )

    clock.advance(31)
    host_b = cast(RunHost, _PassiveHost())
    control_b = _fresh_control(
        world,
        journal,
        "control-cancel-b",
        run_host=host_b,
    )
    recovered = await control_b.runs_cancel(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=f"cancel-{seam}",
    )
    assert isinstance(recovered, CancellationResult)
    assert recovered.status == "cancel_requested"
    assert journal.cancel_requested(run_id)
    stored = _terminal_response_bytes(journal, "runs_cancel")
    replay = await control_b.runs_cancel(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=f"cancel-{seam}",
    )
    assert isinstance(replay, CancellationResult)
    assert replay.command.replayed
    assert _terminal_response_bytes(journal, "runs_cancel") == stored
    await control_a.shutdown()
    await control_b.shutdown()


@pytest.mark.parametrize("operation", ("runs_reproduce", "runs_counterfactual"))
@pytest.mark.parametrize("seam", SEAMS)
async def test_clone_operations_recover_each_response_loss_seam(
    operation: str,
    seam: str,
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    source_run_id = _prepare_live_run(world, journal, f"source-{operation}-{seam}")
    host_a = cast(RunHost, _PassiveHost())
    control_a = _fresh_control(
        world,
        journal,
        f"control-{operation}-a",
        fault_probe=_crash_at(operation, seam),
        run_host=host_a,
    )

    async def invoke(control: ControlPlane) -> RunSubmission | Any:
        if operation == "runs_reproduce":
            return await control.runs_reproduce(
                RUN_ACTOR,
                source_run_id=source_run_id,
                idempotency_key=f"{operation}-{seam}",
            )
        return await control.runs_counterfactual(
            RUN_ACTOR,
            source_run_id=source_run_id,
            overrides={},
            idempotency_key=f"{operation}-{seam}",
        )

    with pytest.raises(InjectedCrash):
        await invoke(control_a)
    clock.advance(31)
    host_b = cast(RunHost, _PassiveHost())
    control_b = _fresh_control(
        world,
        journal,
        f"control-{operation}-b",
        run_host=host_b,
    )
    recovered = await invoke(control_b)
    assert isinstance(recovered, RunSubmission)
    assert recovered.run_id != source_run_id
    origin = journal.run_origin(recovered.run_id)
    assert origin is not None and origin.source_run_id == source_run_id
    assert origin.kind == ("counterfactual" if operation == "runs_counterfactual" else "reproduce")
    assert [item.run_id for item in journal.run_records(limit=100)].count(recovered.run_id) == 1
    stored = _terminal_response_bytes(journal, operation)
    replay = await invoke(control_b)
    assert isinstance(replay, RunSubmission) and replay.command.replayed
    assert _terminal_response_bytes(journal, operation) == stored
    await control_a.shutdown()
    await control_b.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_registration_recovers_each_response_loss_seam(
    seam: str,
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    definition, implementation = atomic(
        f"control/register-{seam.replace('_', '-')}",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    bundle = DefinitionBundle(definition, implementation)
    control_a = _fresh_control(
        world,
        journal,
        "control-register-a",
        fault_probe=_crash_at("registry_register", seam),
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(InjectedCrash):
        await control_a.registry_register(
            LOCAL_ADMIN,
            definition=bundle,
            idempotency_key=f"register-{seam}",
        )
    clock.advance(31)
    control_b = _fresh_control(
        world,
        journal,
        "control-register-b",
        run_host=cast(RunHost, _PassiveHost()),
    )
    recovered = await control_b.registry_register(
        LOCAL_ADMIN,
        definition=definition,
        idempotency_key=f"register-{seam}",
    )
    assert isinstance(recovered, RegistrationCommandResult)
    assert world._registry.snapshot().get(definition.name, recovered.version) is not None
    stored = _terminal_response_bytes(journal, "registry_register")
    replay = await control_b.registry_register(
        LOCAL_ADMIN,
        definition=definition,
        idempotency_key=f"register-{seam}",
    )
    assert isinstance(replay, RegistrationCommandResult) and replay.command.replayed
    assert _terminal_response_bytes(journal, "registry_register") == stored
    await control_a.shutdown()
    await control_b.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_initial_promotion_recovers_each_response_loss_seam(
    seam: str,
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    definition, implementation = atomic(
        f"control/bootstrap-{seam.replace('_', '-')}",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    version = world._register(definition, implementation)
    control_a = _fresh_control(
        world,
        journal,
        "control-bootstrap-a",
        fault_probe=_crash_at("registry_promote_initial", seam),
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(InjectedCrash):
        await control_a.registry_promote_initial(
            LOCAL_ADMIN,
            component=definition.name,
            version=version,
            idempotency_key=f"bootstrap-{seam}",
        )
    clock.advance(31)
    control_b = _fresh_control(
        world,
        journal,
        "control-bootstrap-b",
        run_host=cast(RunHost, _PassiveHost()),
    )
    recovered = await control_b.registry_promote_initial(
        LOCAL_ADMIN,
        component=definition.name,
        version=version,
        idempotency_key=f"bootstrap-{seam}",
    )
    assert isinstance(recovered, PromotionCommandResult)
    assert recovered.from_version is None and recovered.to_version == version
    assert world._registry.stable_version(definition.name) == version
    assert len(world._registry.snapshot().history[definition.name]) == 1
    stored = _terminal_response_bytes(journal, "registry_promote_initial")
    replay = await control_b.registry_promote_initial(
        LOCAL_ADMIN,
        component=definition.name,
        version=version,
        idempotency_key=f"bootstrap-{seam}",
    )
    assert isinstance(replay, PromotionCommandResult) and replay.command.replayed
    assert _terminal_response_bytes(journal, "registry_promote_initial") == stored
    await control_a.shutdown()
    await control_b.shutdown()


async def test_initial_promotion_recovers_exact_attestation_before_receipt_loss(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    definition, implementation = atomic(
        "control/bootstrap-attestation-seam",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    version = world._register(definition, implementation)
    control_a = _fresh_control(
        world,
        journal,
        "control-bootstrap-attestation-a",
        fault_probe=_crash_at("registry_promote_initial", "after_attestation"),
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(InjectedCrash):
        await control_a.registry_promote_initial(
            LOCAL_ADMIN,
            component=definition.name,
            version=version,
            idempotency_key="bootstrap-attestation-seam",
        )
    key = journal.latest_command_key(operation="registry_promote_initial")
    assert key is not None
    command = journal.command(key[1])
    assert command is not None and isinstance(command.plan, dict)
    planned = command.plan.get("plan")
    assert isinstance(planned, dict)
    attestation_id = planned.get("attestation_id")
    assert isinstance(attestation_id, str)
    attestation = journal.load_attestation(attestation_id)
    assert attestation is not None
    assert journal.promotion_for_attestation(attestation_id) is None

    clock.advance(31)
    control_b = _fresh_control(
        world,
        journal,
        "control-bootstrap-attestation-b",
        run_host=cast(RunHost, _PassiveHost()),
    )
    recovered = await control_b.registry_promote_initial(
        LOCAL_ADMIN,
        component=definition.name,
        version=version,
        idempotency_key="bootstrap-attestation-seam",
    )
    assert isinstance(recovered, PromotionCommandResult)
    receipt = journal.promotion_for_attestation(attestation_id)
    assert receipt is not None and receipt.to_version == version
    assert journal.load_attestation(attestation_id) == attestation
    assert len(world._registry.snapshot().history[definition.name]) == 1
    await control_a.shutdown()
    await control_b.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_resume_recovers_each_response_loss_seam_with_one_attempt(
    seam: str,
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    run_id = _prepare_failed_run(world, journal, f"resume-{seam}")
    baseline = journal.max_event_seq(run_id)
    key = f"resume-{seam}"
    expected_command_id = command_id_for(RUN_ACTOR.actor_id, "runs_resume", key)
    control_a = _fresh_control(
        world,
        journal,
        "control-resume-a",
        fault_probe=_crash_at("runs_resume", seam),
    )
    with pytest.raises(InjectedCrash):
        await control_a.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)

    if seam != "after_plan":
        await await_attempt_terminal(
            journal,
            run_id,
            baseline_event_seq=baseline,
            expected_resume_command_id=expected_command_id,
        )
    clock.advance(31)
    control_b = _fresh_control(world, journal, "control-resume-b")
    recovered = await control_b.runs_resume(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(recovered, RunSubmission)
    await await_attempt_terminal(
        journal,
        run_id,
        baseline_event_seq=baseline,
        expected_resume_command_id=expected_command_id,
    )
    attempt_events = [
        event
        for event in journal.events(run_id, after_seq=baseline, limit=100)
        if event.kind in {"RunStarted", "RunReclaimed", "RunResumed"}
        and event.payload is not None
        and event.payload.get("resume_command_id") == expected_command_id
    ]
    assert len(attempt_events) == 1
    stored = _terminal_response_bytes(journal, "runs_resume")
    replay = await control_b.runs_resume(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(replay, RunSubmission) and replay.command.replayed
    assert _terminal_response_bytes(journal, "runs_resume") == stored
    await asyncio.sleep(0)
    await control_a.shutdown()
    await control_b.shutdown()


def _stored_plan_kind(journal: SqliteJournal, command_id: str) -> str:
    command = journal.command(command_id)
    assert command is not None and isinstance(command.plan, dict)
    plan = command.plan["plan"]
    assert isinstance(plan, dict)
    return str(plan["kind"])


def _rewrite_terminal_fault_code(
    db_path: Path,
    command_id: str,
    code: ControlCode,
) -> None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT response_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        payload = json.loads(row[0])
        assert isinstance(payload, dict)
        faults = payload.get("faults")
        assert isinstance(faults, list) and len(faults) == 1
        fault = faults[0]
        assert isinstance(fault, dict)
        fault["code"] = code.value
        connection.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), command_id),
        )


async def test_resume_rejected_after_its_domain_plan_replays(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """Refusing at apply time is lawful: the domain plan is already durable.

    ``runs_resume`` commits its ``resume`` plan before it can observe a live
    owner, so the rejection lands over a domain plan rather than over a
    rejection plan. Replay must return that recorded refusal, not a fault.
    """

    run_id = _prepare_live_run(world, journal, "resume-rejected-after-plan")
    key = "resume-rejected-after-plan"
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_resume", key)
    control = _fresh_control(world, journal, "control-resume-rejected")

    rejected = await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    assert isinstance(rejected, ControlRejected)
    assert [fault.code for fault in rejected.faults] == [ControlCode.RUN_LIVE_OWNER]
    assert _stored_plan_kind(journal, command_id) == "resume"

    stored = _terminal_response_bytes(journal, "runs_resume")
    clock.advance(31)
    replay = await _fresh_control(world, journal, "control-resume-replay").runs_resume(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert replay == rejected
    assert _terminal_response_bytes(journal, "runs_resume") == stored
    await control.shutdown()


async def test_initial_promotion_rejected_after_its_domain_plan_replays(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """The same law across a second command family: stable moved after planning."""

    definition, implementation = atomic(
        "control/bootstrap-rejected-after-plan",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    planned_version = world._register(definition, implementation)
    other_version = world._register(definition.model_copy(update={"role": "component"}))
    key = "bootstrap-rejected-after-plan"
    command_id = command_id_for(LOCAL_ADMIN.actor_id, "registry_promote_initial", key)
    control_a = _fresh_control(
        world,
        journal,
        "control-bootstrap-rejected-a",
        fault_probe=_crash_at("registry_promote_initial", "after_plan"),
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(InjectedCrash):
        await control_a.registry_promote_initial(
            LOCAL_ADMIN,
            component=definition.name,
            version=planned_version,
            idempotency_key=key,
        )
    assert _stored_plan_kind(journal, command_id) == "initial_promotion"

    # The world moves stable elsewhere while the planned command is unfinished.
    world._promote_initial(component=definition.name, version=other_version)
    clock.advance(31)
    control_b = _fresh_control(
        world,
        journal,
        "control-bootstrap-rejected-b",
        run_host=cast(RunHost, _PassiveHost()),
    )
    rejected = await control_b.registry_promote_initial(
        LOCAL_ADMIN,
        component=definition.name,
        version=planned_version,
        idempotency_key=key,
    )
    assert isinstance(rejected, ControlRejected)
    assert [fault.code for fault in rejected.faults] == [ControlCode.REGISTRY_STABLE_MOVED]
    assert _stored_plan_kind(journal, command_id) == "initial_promotion"

    stored = _terminal_response_bytes(journal, "registry_promote_initial")
    replay = await control_b.registry_promote_initial(
        LOCAL_ADMIN,
        component=definition.name,
        version=planned_version,
        idempotency_key=key,
    )
    assert replay == rejected
    assert _terminal_response_bytes(journal, "registry_promote_initial") == stored
    assert world._registry.stable_version(definition.name) == other_version
    await control_a.shutdown()
    await control_b.shutdown()


async def test_domain_plan_replay_refuses_an_unlawful_rejection_family(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    """Apply-time refusal support must not turn off relational validation."""

    run_id = _prepare_live_run(world, journal, "resume-damaged-rejection")
    key = "resume-damaged-rejection"
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_resume", key)
    control = _fresh_control(world, journal, "control-resume-damaged")
    rejected = await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    assert isinstance(rejected, ControlRejected)
    assert _stored_plan_kind(journal, command_id) == "resume"

    _rewrite_terminal_fault_code(
        tmp_path / "journal.db",
        command_id,
        ControlCode.REGISTRY_STABLE_MOVED,
    )
    with pytest.raises(JournalDamaged, match="not lawful"):
        await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    await control.shutdown()
