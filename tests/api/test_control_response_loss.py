"""M6 command recovery at every durable response-loss seam."""

from __future__ import annotations

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.core.address import RunId
from constructicon.core.control import (
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    READ_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    PromotionCommandResult,
    RunSubmission,
)
from constructicon.core.effect import (
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
)
from constructicon.core.identity import Digest, digest
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import (
    BRIEF,
    ISSUE,
    FakeClock,
    InjectedCrash,
    atomic,
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

SEAMS = (
    "after_plan",
    "after_domain_mutation",
    "after_command_completion",
)


def _arm(control: ControlPlane, operation: str, seam: str) -> None:
    target = f"{operation}.{seam}"

    def crash(name: str) -> None:
        if name == target:
            raise InjectedCrash(name)

    control.fault_probe = crash


async def _expect_crash(call) -> None:
    with pytest.raises(InjectedCrash):
        await call()


def _fresh_control(world, journal: SqliteJournal, owner: str) -> ControlPlane:
    return ControlPlane(
        system=world,
        store=journal,
        run_host=RunHost(world, max_concurrency=1),
        owner_id=owner,
        command_ttl_s=30,
    )


def _candidate(world, component: str) -> tuple[Digest, Digest, str]:
    definition, impl = atomic(component, (ISSUE,), (BRIEF,), triage_impl)
    v1 = world.register(definition, impl)
    world.promote_initial(component=component, version=v1)
    changed = definition.model_copy(update={"role": "component"})
    v2 = world.register(changed, impl)
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
    attestation = world.journal.mint_policy_attestation(draft)
    return v1, v2, attestation.attestation_id


@pytest.mark.parametrize("seam", SEAMS)
async def test_runs_start_recovers_each_response_loss_seam(
    seam: str,
    world,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    control_a = _fresh_control(world, journal, "control-start-a")
    _arm(control_a, "runs_start", seam)

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
    result = await control_b.run_host.wait(recovered.run_id)
    assert result is not None and result.status is RunStatus.SUCCEEDED
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
    await control_a.run_host.shutdown()
    await control_b.run_host.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_approval_recovers_each_response_loss_seam(
    seam: str,
    world,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    manifest = world.validate(pipeline_graph(), {"issue": {"title": f"approve-{seam}"}})
    run_id = RunId(f"run-approve-{seam.replace('_', '-')}")
    world.prepare(manifest, run_id=run_id, inputs={"issue": {"title": f"approve-{seam}"}})
    stable = world.registry.stable_version("test/triage")
    assert stable is not None
    subject = ComponentProofSubject(
        component="test/triage",
        version=stable,
        baseline_version=stable,
    )

    control_a = _fresh_control(world, journal, "control-approval-a")
    _arm(control_a, "runs_approve", seam)

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
    await control_a.run_host.shutdown()
    await control_b.run_host.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_promotion_recovers_each_response_loss_seam(
    seam: str,
    world,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    component = f"control/promotion-{seam.replace('_', '-')}"
    v1, v2, attestation_id = _candidate(world, component)
    control_a = _fresh_control(world, journal, "control-promotion-a")
    _arm(control_a, "registry_promote", seam)

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
    assert world.registry.stable_version(component) == v2
    assert world.registry.snapshot().history[component] == ((None, str(v1)), (str(v1), str(v2)))

    replay = await control_b.registry_promote(
        AUTHORITY_ACTOR,
        component=component,
        version=v2,
        attestation_id=attestation_id,
        idempotency_key=f"promote-{seam}",
    )
    assert isinstance(replay, PromotionCommandResult)
    assert replay.command.replayed is True
    await control_a.run_host.shutdown()
    await control_b.run_host.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_rollback_recovers_each_response_loss_seam(
    seam: str,
    world,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    component = f"control/rollback-{seam.replace('_', '-')}"
    v1, v2, attestation_id = _candidate(world, component)
    world.promote(
        component=component,
        version=v2,
        attestation_id=attestation_id,
        actor="setup",
    )
    control_a = _fresh_control(world, journal, "control-rollback-a")
    _arm(control_a, "registry_rollback", seam)

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
    assert world.registry.stable_version(component) == v1
    assert len(world.registry.snapshot().history[component]) == 3

    replay = await control_b.registry_rollback(
        AUTHORITY_ACTOR,
        component=component,
        expected_stable=v2,
        idempotency_key=f"rollback-{seam}",
    )
    assert isinstance(replay, PromotionCommandResult)
    assert replay.to_version == v1
    assert replay.command.replayed is True
    await control_a.run_host.shutdown()
    await control_b.run_host.shutdown()
