"""M6 command recovery at every durable response-loss seam."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import LaunchDisposition, RunHost
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
    command_request_hash,
    run_id_for_command,
)
from constructicon.core.effect import (
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.run import AttemptCause, RunStatus
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.journal._sqlite_commands import (
    command_claim_fact_hash,
    command_plan_fact_hash,
    command_terminal_fact_hash,
)
from constructicon.substrate.journal._sqlite_registry import (
    component_registration_fact_hash,
)
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
from tests.durable_seals import reseal_primary_fact

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


class _PassiveHost(RunHost):
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

    def launch(
        self,
        run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> LaunchDisposition:
        self.launches.append(
            (
                run_id,
                {
                    "expected_event_seq": expected_event_seq,
                    "allowed_statuses": allowed_statuses,
                    "cause": cause,
                },
            )
        )
        return "queued"


class _SupersedingHost(_PassiveHost):
    """A process-local fence that already carries a newer resume intent."""

    def launch(
        self,
        run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> LaunchDisposition:
        self.launches.append(
            (
                run_id,
                {
                    "expected_event_seq": expected_event_seq,
                    "allowed_statuses": allowed_statuses,
                    "cause": cause,
                },
            )
        )
        return "superseded"


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
    if isinstance(run_host, _PassiveHost):
        run_host._system = world
        run_host._journal = journal
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


def _replace_positive_seal(
    connection: sqlite3.Connection,
    *,
    family: str,
    fact_key: str,
    fact_hash: Digest,
) -> None:
    """Make an explicitly impossible test fact internally seal-consistent.

    Current rows are rejected at their positive seal before any cross-fact law
    runs.  A test that targets a deeper relationship must therefore corrupt
    both independent observations deliberately; ordinary tamper tests must not
    call this helper.
    """

    reseal_primary_fact(
        connection,
        family=family,
        fact_key=fact_key,
        fact=fact_hash,
    )


def _reseal_command_phases(
    connection: sqlite3.Connection,
    command_id: str,
    *,
    claim: bool = False,
    plan: bool = False,
    terminal: bool = False,
) -> None:
    """Advance only the named impossible command observations for a test."""

    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM commands WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    assert row is not None
    if claim:
        _replace_positive_seal(
            connection,
            family="command_claim",
            fact_key=command_id,
            fact_hash=command_claim_fact_hash(row),
        )
    if plan:
        assert row["plan_json"] is not None
        _replace_positive_seal(
            connection,
            family="command_plan",
            fact_key=command_id,
            fact_hash=command_plan_fact_hash(row),
        )
    if terminal:
        assert row["state"] != "prepared"
        _replace_positive_seal(
            connection,
            family="command_terminal",
            fact_key=command_id,
            fact_hash=command_terminal_fact_hash(row),
        )


def _reseal_component_registration(
    connection: sqlite3.Connection,
    *,
    name: str,
    content_hash: Digest,
) -> None:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM components WHERE name = ? AND content_hash = ?",
        (name, str(content_hash)),
    ).fetchone()
    assert row is not None
    sequence = row["registration_seq"]
    assert type(sequence) is int and sequence > 0
    _replace_positive_seal(
        connection,
        family="component_registration",
        fact_key=str(sequence),
        fact_hash=component_registration_fact_hash(row),
    )


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


def _prepare_terminal_run(
    world: Any,
    journal: SqliteJournal,
    suffix: str,
    status: Literal[RunStatus.SUCCEEDED, RunStatus.CANCELLED],
) -> RunId:
    inputs = {"issue": {"title": suffix}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId(f"run-response-loss-{suffix}")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    lease = journal.claim_run(run_id, owner_id=f"terminal-{suffix}", ttl_s=300)
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
        event_kind="RunSucceeded" if status is RunStatus.SUCCEEDED else "RunCancelled",
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


def _competing_candidate(
    world: Any,
    component: str,
    *,
    baseline: Digest,
    role: Literal["component", "harness", "workflow"],
) -> tuple[Digest, str]:
    stored = world._registry.snapshot().get(component, baseline)
    assert stored is not None
    changed = stored.definition.model_copy(update={"role": role})
    target = world._register(changed, triage_impl)
    draft = AttestationDraft(
        action="promote",
        subject=ComponentProofSubject(
            component=component,
            version=target,
            baseline_version=baseline,
        ),
        checks=(
            CheckResult(
                name="response-loss-competing-evaluation",
                status="passed",
                detail="competing candidate passed its pinned evaluation",
                elapsed_s=0.0,
            ),
        ),
        check_set_hash=digest(
            "check-set",
            1,
            {"policy": "response-loss-competing", "component": component},
        ),
        evidence=(),
        manifest_hash=digest("manifest", 1, {"competing": component}),
        workspace_id=None,
    )
    attestation = world._journal.mint_policy_attestation(draft)
    return target, attestation.attestation_id


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


def _rewrite_terminal_fault(
    db_path: str | Path,
    command_id: str,
    *,
    code: ControlCode | None = None,
    message: str | None = None,
    repair: str | None = None,
    details: dict[str, Any] | None = None,
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
        if code is not None:
            fault["code"] = code.value
        if message is not None:
            fault["message"] = message
        if repair is not None:
            fault["repair"] = repair
        if details is not None:
            fault["details"] = details
        connection.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (canonical_json(payload), command_id),
        )
        _reseal_command_phases(connection, command_id, terminal=True)


def _rewrite_resume_as_legacy_rejection(
    db_path: str | Path,
    command_id: str,
    response: ControlRejected,
) -> None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        plan = json.loads(row[0])
        inner = plan.get("plan")
        assert isinstance(inner, dict)
        assert inner.pop("terminal_rejection_policy") == "exact-v1"
        payload = response.model_dump(mode="json")
        payload["schema_version"] = 2
        connection.execute(
            "UPDATE commands SET plan_json = ?, response_json = ? WHERE command_id = ?",
            (canonical_json(plan), canonical_json(payload), command_id),
        )
        _reseal_command_phases(connection, command_id, plan=True, terminal=True)


_NO_DOMAIN_PLAN_WITNESS = "'domain_plan_pre_v7' fact .* has no positive seal"


def _strip_terminal_rejection_policy(
    db_path: str | Path,
    command_id: str,
    *,
    response_json: str,
) -> None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        plan = json.loads(row[0])
        inner = plan.get("plan")
        assert isinstance(inner, dict)
        assert inner.pop("terminal_rejection_policy") == "exact-v1"
        connection.execute(
            "UPDATE commands SET plan_json = ?, response_json = ? WHERE command_id = ?",
            (canonical_json(plan), response_json, command_id),
        )
        _reseal_command_phases(connection, command_id, plan=True, terminal=True)


async def test_terminal_command_state_is_bound_to_its_response_family(
    world: Any,
    journal: SqliteJournal,
) -> None:
    control = _fresh_control(
        world,
        journal,
        "control-terminal-state-family",
        run_host=cast(RunHost, _PassiveHost()),
    )
    successful_run = _prepare_failed_run(world, journal, "terminal-state-success")
    success_key = "terminal-state-success"
    success = await control.runs_cancel(
        RUN_ACTOR,
        run_id=successful_run,
        idempotency_key=success_key,
    )
    assert isinstance(success, CancellationResult)

    missing_run = RunId("run-terminal-state-rejection-missing")
    rejection_key = "terminal-state-rejection"
    rejection = await control.runs_cancel(
        RUN_ACTOR,
        run_id=missing_run,
        idempotency_key=rejection_key,
    )
    assert isinstance(rejection, ControlRejected)

    success_id = command_id_for(RUN_ACTOR.actor_id, "runs_cancel", success_key)
    rejection_id = command_id_for(RUN_ACTOR.actor_id, "runs_cancel", rejection_key)
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE commands SET state = 'rejected' WHERE command_id = ?",
            (success_id,),
        )
        connection.execute(
            "UPDATE commands SET state = 'committed' WHERE command_id = ?",
            (rejection_id,),
        )
        _reseal_command_phases(connection, success_id, terminal=True)
        _reseal_command_phases(connection, rejection_id, terminal=True)

    with pytest.raises(JournalDamaged, match="lifecycle contradicts its response family"):
        await control.runs_cancel(
            RUN_ACTOR,
            run_id=successful_run,
            idempotency_key=success_key,
        )
    with pytest.raises(JournalDamaged, match="lifecycle contradicts its response family"):
        await control.runs_cancel(
            RUN_ACTOR,
            run_id=missing_run,
            idempotency_key=rejection_key,
        )
    await control.shutdown()


@pytest.mark.parametrize(
    "damaged_fact",
    ("manifest_hash", "input_hash", "inputs", "origin"),
)
async def test_run_creation_success_replays_only_beside_its_exact_run_fact(
    damaged_fact: str,
    world: Any,
    journal: SqliteJournal,
) -> None:
    key = f"created-run-fact-{damaged_fact}"
    inputs = {"issue": {"title": key}}
    graph = pipeline_graph()
    control = _fresh_control(
        world,
        journal,
        f"control-{key}",
        run_host=cast(RunHost, _PassiveHost()),
    )
    created = await control.runs_start(
        RUN_ACTOR,
        proposal=graph,
        inputs=inputs,
        idempotency_key=key,
    )
    assert isinstance(created, RunSubmission)

    with sqlite3.connect(journal._db_path) as connection:
        if damaged_fact == "manifest_hash":
            connection.execute(
                "UPDATE runs SET manifest_hash = ? WHERE run_id = ?",
                (str(digest("manifest", 1, {"foreign": key})), created.run_id),
            )
        elif damaged_fact == "input_hash":
            connection.execute(
                "UPDATE runs SET input_hash = ? WHERE run_id = ?",
                (str(digest("inputs", 1, {"foreign": key})), created.run_id),
            )
        elif damaged_fact == "inputs":
            connection.execute(
                "UPDATE runs SET inputs_json = ? WHERE run_id = ?",
                (canonical_json({"issue": {"title": "foreign"}}), created.run_id),
            )
        else:
            row = connection.execute(
                "SELECT origin_json FROM run_origins WHERE run_id = ?",
                (created.run_id,),
            ).fetchone()
            assert row is not None and isinstance(row[0], str)
            origin = json.loads(row[0])
            origin["actor_id"] = "static:foreign-run-author"
            connection.execute(
                "UPDATE run_origins SET origin_json = ? WHERE run_id = ?",
                (canonical_json(origin), created.run_id),
            )

    # These are valid-to-valid row rewrites, so the immutable-world seal is the
    # first and strongest exact-run proof. Cross-plan replay validation is only
    # reachable for an internally coherent, independently sealed run world.
    with pytest.raises(JournalDamaged, match="positive seal"):
        await control.runs_start(
            RUN_ACTOR,
            proposal=graph,
            inputs=inputs,
            idempotency_key=key,
        )
    await control.shutdown()


async def test_cancel_success_replays_only_beside_its_durable_request(
    world: Any,
    journal: SqliteJournal,
) -> None:
    run_id = RunId("run-cancel-request-fact")
    inputs = {"issue": {"title": "cancel request fact"}}
    world._prepare_run(
        world.validate(pipeline_graph(), inputs),
        run_id=run_id,
        inputs=inputs,
    )
    control = _fresh_control(
        world,
        journal,
        "control-cancel-request-fact",
        run_host=cast(RunHost, _PassiveHost()),
    )
    result = await control.runs_cancel(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key="cancel-request-fact",
    )
    assert isinstance(result, CancellationResult)
    assert result.status == "cancel_requested"

    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE runs SET cancel_requested = 0 WHERE run_id = ?",
            (run_id,),
        )

    with pytest.raises(JournalDamaged, match="durable request"):
        await control.runs_cancel(
            RUN_ACTOR,
            run_id=run_id,
            idempotency_key="cancel-request-fact",
        )
    await control.shutdown()


async def test_already_terminal_cancel_replays_only_with_its_exact_status_event(
    world: Any,
    journal: SqliteJournal,
) -> None:
    run_id = _prepare_terminal_run(
        world,
        journal,
        "cancel-terminal-observation",
        RunStatus.SUCCEEDED,
    )
    key = "cancel-terminal-observation"
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_cancel", key)
    control = _fresh_control(
        world,
        journal,
        "control-cancel-terminal-observation",
        run_host=cast(RunHost, _PassiveHost()),
    )
    result = await control.runs_cancel(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(result, CancellationResult)
    assert result.status == "already_terminal"

    with sqlite3.connect(journal._db_path) as connection:
        row = connection.execute(
            "SELECT plan_json, response_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str) and isinstance(row[1], str)
        plan = json.loads(row[0])
        response = json.loads(row[1])
        inner = plan.get("plan")
        assert isinstance(inner, dict)
        assert isinstance(inner.get("observed_event_seq"), int)
        inner["observed_status"] = RunStatus.CANCELLED.value
        inner["response_status"] = RunStatus.CANCELLED.value
        response["run_status"] = RunStatus.CANCELLED.value
        connection.execute(
            "UPDATE commands SET plan_json = ?, response_json = ? WHERE command_id = ?",
            (canonical_json(plan), canonical_json(response), command_id),
        )
        _reseal_command_phases(connection, command_id, plan=True, terminal=True)

    with pytest.raises(JournalDamaged, match="exact terminal observation"):
        await control.runs_cancel(
            RUN_ACTOR,
            run_id=run_id,
            idempotency_key=key,
        )
    await control.shutdown()


async def test_already_terminal_cancel_remains_replayable_after_a_later_resume(
    world: Any,
    journal: SqliteJournal,
) -> None:
    run_id = _prepare_failed_run(world, journal, "cancel-before-later-resume")
    key = "cancel-before-later-resume"
    control = _fresh_control(
        world,
        journal,
        "control-cancel-before-later-resume",
        run_host=cast(RunHost, _PassiveHost()),
    )
    result = await control.runs_cancel(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(result, CancellationResult)
    assert result.status == "already_terminal"
    assert result.run_status is RunStatus.FAILED

    lease = journal.claim_run(run_id, owner_id="later-resume", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.FAILED}),
        target=RunStatus.RUNNING,
        event_kind="RunResumed",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED,
        event_kind="RunFailed",
    )
    journal.release_run(lease)

    replay = await control.runs_cancel(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert replay == result.model_copy(
        update={"command": result.command.model_copy(update={"replayed": True})}
    )
    await control.shutdown()


@pytest.mark.parametrize("status", [RunStatus.SUCCEEDED, RunStatus.FAILED])
async def test_a_stripped_cancel_observation_is_a_forgery_not_history(
    status: RunStatus,
    world: Any,
    journal: SqliteJournal,
) -> None:
    """The pre-marker shape is history only when the migration witnessed it.

    Strip `observed_event_seq` from a current plan and the bytes match a plan
    written before that field existed — but no migration saw this plan in that
    shape, so no witness exists, and the seal boundary refuses it whatever the
    run's status. The genuine pre-v7 shape, witnessed at migration, replays for
    both statuses: see tests/api/test_pre_v7_plan_replay.py.
    """
    run_id = (
        _prepare_terminal_run(world, journal, f"legacy-cancel-{status.value}", status)
        if status is RunStatus.SUCCEEDED
        else _prepare_failed_run(world, journal, f"legacy-cancel-{status.value}")
    )
    key = f"legacy-cancel-{status.value}"
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_cancel", key)
    control = _fresh_control(
        world,
        journal,
        f"control-legacy-cancel-{status.value}",
        run_host=cast(RunHost, _PassiveHost()),
    )
    result = await control.runs_cancel(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(result, CancellationResult)

    with sqlite3.connect(journal._db_path) as connection:
        row = connection.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        plan = json.loads(row[0])
        inner = plan.get("plan")
        assert isinstance(inner, dict)
        assert isinstance(inner.pop("observed_event_seq"), int)
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(plan), command_id),
        )
        _reseal_command_phases(connection, command_id, plan=True)

    with pytest.raises(JournalDamaged, match=_NO_DOMAIN_PLAN_WITNESS):
        await control.runs_cancel(
            RUN_ACTOR,
            run_id=run_id,
            idempotency_key=key,
        )
    await control.shutdown()


@pytest.mark.parametrize("damage", ("baseline", "cause"))
async def test_resume_success_refuses_rewritten_attempt_evidence(
    damage: str,
    world: Any,
    journal: SqliteJournal,
) -> None:
    run_id = _prepare_failed_run(world, journal, f"resume-attempt-{damage}")
    baseline = journal.max_event_seq(run_id)
    key = f"resume-attempt-{damage}"
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_resume", key)
    control = _fresh_control(world, journal, f"control-{key}")
    resumed = await control.runs_resume(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(resumed, RunSubmission)
    await await_attempt_terminal(
        journal,
        run_id,
        baseline_event_seq=baseline,
        expected_resume_command_id=command_id,
    )

    with sqlite3.connect(journal._db_path) as connection:
        if damage == "baseline":
            row = connection.execute(
                "SELECT plan_json FROM commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            assert row is not None and isinstance(row[0], str)
            plan = json.loads(row[0])
            plan["plan"]["baseline_event_seq"] = baseline + 1
            connection.execute(
                "UPDATE commands SET plan_json = ? WHERE command_id = ?",
                (canonical_json(plan), command_id),
            )
        else:
            row = connection.execute(
                "SELECT payload FROM events WHERE run_id = ? AND seq = ?",
                (run_id, baseline + 1),
            ).fetchone()
            assert row is not None and isinstance(row[0], str)
            payload = json.loads(row[0])
            payload["resume_command_id"] = "cmd-foreign-resume"
            connection.execute(
                "UPDATE events SET payload = ? WHERE run_id = ? AND seq = ?",
                (canonical_json(payload), run_id, baseline + 1),
            )

    # A committed response may lawfully be superseded by a later attempt. What
    # cannot change is either stored side of its original attempt evidence.
    with pytest.raises(JournalDamaged, match="positive seal"):
        await control.runs_resume(
            RUN_ACTOR,
            run_id=run_id,
            idempotency_key=key,
        )
    await control.shutdown()


async def test_registration_success_replays_only_with_its_exact_row_timestamp(
    world: Any,
    journal: SqliteJournal,
) -> None:
    definition, implementation = atomic(
        "control/registration-timestamp",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    control = _fresh_control(
        world,
        journal,
        "control-registration-timestamp",
        run_host=cast(RunHost, _PassiveHost()),
    )
    key = "registration-timestamp"
    registered = await control.registry_register(
        LOCAL_ADMIN,
        definition=DefinitionBundle(definition, implementation),
        idempotency_key=key,
    )
    assert isinstance(registered, RegistrationCommandResult)

    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE components SET registered_at = ?"
            " WHERE name = ? AND content_hash = ?",
            (
                "2030-01-01T00:00:00+00:00",
                definition.name,
                str(registered.version),
            ),
        )
        _reseal_component_registration(
            connection,
            name=definition.name,
            content_hash=registered.version,
        )

    with pytest.raises(JournalDamaged, match="registration response contradicts"):
        await control.registry_register(
            LOCAL_ADMIN,
            definition=definition,
            idempotency_key=key,
        )
    await control.shutdown()


async def test_current_terminal_response_is_decoded_without_scalar_coercion(
    world: Any,
    journal: SqliteJournal,
) -> None:
    key = "current-response-lossless"
    inputs = {"issue": {"title": key}}
    graph = pipeline_graph()
    control = _fresh_control(
        world,
        journal,
        "control-current-response-lossless",
        run_host=cast(RunHost, _PassiveHost()),
    )
    created = await control.runs_start(
        RUN_ACTOR,
        proposal=graph,
        inputs=inputs,
        idempotency_key=key,
    )
    assert isinstance(created, RunSubmission)

    with sqlite3.connect(journal._db_path) as connection:
        row = connection.execute(
            "SELECT response_json FROM commands WHERE command_id = ?",
            (created.command.command_id,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        response = json.loads(row[0])
        response["command"]["replayed"] = 0
        connection.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (canonical_json(response), created.command.command_id),
        )
        _reseal_command_phases(
            connection,
            created.command.command_id,
            terminal=True,
        )

    with pytest.raises(JournalDamaged, match="matches none of the operation models"):
        await control.runs_start(
            RUN_ACTOR,
            proposal=graph,
            inputs=inputs,
            idempotency_key=key,
        )
    await control.shutdown()


async def test_rejection_plan_and_response_compare_canonical_json_scalars(
    world: Any,
    journal: SqliteJournal,
) -> None:
    key = "rejection-json-scalars"
    run_id = RunId("run-rejection-json-scalars-missing")
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_resume", key)
    control = _fresh_control(
        world,
        journal,
        "control-rejection-json-scalars",
        run_host=cast(RunHost, _PassiveHost()),
    )
    rejected = await control.runs_resume(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert isinstance(rejected, ControlRejected)

    with sqlite3.connect(journal._db_path) as connection:
        row = connection.execute(
            "SELECT plan_json, response_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None
        plan = json.loads(row[0])
        response = json.loads(row[1])
        plan["plan"]["response"]["faults"][0]["details"]["scalar"] = True
        response["faults"][0]["details"]["scalar"] = 1
        connection.execute(
            "UPDATE commands SET plan_json = ?, response_json = ? WHERE command_id = ?",
            (canonical_json(plan), canonical_json(response), command_id),
        )
        _reseal_command_phases(connection, command_id, plan=True, terminal=True)

    with pytest.raises(JournalDamaged, match="rejection contradicts"):
        await control.runs_resume(
            RUN_ACTOR,
            run_id=run_id,
            idempotency_key=key,
        )
    await control.shutdown()


async def test_start_recovery_compares_request_and_plan_inputs_by_canonical_bytes(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    key = "start-input-json-scalars"
    graph = pipeline_graph()
    original_inputs = {"issue": {"title": "scalar", "rank": 1}}
    abandoned = _fresh_control(
        world,
        journal,
        "control-start-input-json-scalars-a",
        fault_probe=_crash_at("runs_start", "after_plan"),
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(InjectedCrash):
        await abandoned.runs_start(
            RUN_ACTOR,
            proposal=graph,
            inputs=original_inputs,
            idempotency_key=key,
        )

    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_start", key)
    changed_inputs = {"issue": {"title": "scalar", "rank": True}}
    changed_request = {
        "proposal": graph.model_dump(mode="json"),
        "inputs": changed_inputs,
    }
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE commands SET request_json = ?, request_hash = ? WHERE command_id = ?",
            (
                canonical_json(changed_request),
                str(command_request_hash(changed_request)),
                command_id,
            ),
        )
        _reseal_command_phases(connection, command_id, claim=True)

    clock.advance(31)
    recovered = _fresh_control(
        world,
        journal,
        "control-start-input-json-scalars-b",
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(JournalDamaged, match="start plan contradicts"):
        await recovered.runs_start(
            RUN_ACTOR,
            proposal=graph,
            inputs=changed_inputs,
            idempotency_key=key,
        )

    stored = journal.command(command_id)
    assert stored is not None and stored.state == "prepared"
    assert journal.run_record(run_id_for_command(command_id)) is None
    await abandoned.shutdown()
    await recovered.shutdown()


async def test_resume_live_refusal_precedes_domain_plan_and_replays_exactly(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """A complete live-owner observation is refusal evidence, not resume intent."""

    run_id = _prepare_live_run(world, journal, "resume-rejected-after-plan")
    key = "resume-rejected-after-plan"
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_resume", key)
    control = _fresh_control(world, journal, "control-resume-rejected")

    rejected = await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    assert isinstance(rejected, ControlRejected)
    assert [fault.code for fault in rejected.faults] == [ControlCode.RUN_LIVE_OWNER]
    assert _stored_plan_kind(journal, command_id) == "control_reject"

    stored = _terminal_response_bytes(journal, "runs_resume")
    clock.advance(31)
    replay = await _fresh_control(world, journal, "control-resume-replay").runs_resume(
        RUN_ACTOR,
        run_id=run_id,
        idempotency_key=key,
    )
    assert replay == rejected
    assert _terminal_response_bytes(journal, "runs_resume") == stored

    _rewrite_terminal_fault(
        journal._db_path,
        command_id,
        message="forged live-owner refusal",
    )
    with pytest.raises(JournalDamaged, match="control rejection contradicts"):
        await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    await control.shutdown()


@pytest.mark.parametrize("status", [RunStatus.SUCCEEDED, RunStatus.CANCELLED])
async def test_resume_terminal_refusal_precedes_domain_plan(
    status: Literal[RunStatus.SUCCEEDED, RunStatus.CANCELLED],
    world: Any,
    journal: SqliteJournal,
) -> None:
    run_id = _prepare_terminal_run(world, journal, f"resume-terminal-{status.value}", status)
    key = f"resume-terminal-{status.value}"
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_resume", key)
    control = _fresh_control(
        world,
        journal,
        f"control-resume-terminal-{status.value}",
        run_host=cast(RunHost, _PassiveHost()),
    )

    rejected = await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    assert isinstance(rejected, ControlRejected)
    assert rejected.faults[0].code is ControlCode.RUN_TERMINAL
    assert rejected.faults[0].message == f"run {run_id!r} is terminal at {status.value}"
    assert _stored_plan_kind(journal, command_id) == "control_reject"
    replay = await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    assert replay == rejected
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

    _rewrite_terminal_fault(
        journal._db_path,
        command_id,
        repair="forged repair under the lawful registry code",
    )
    with pytest.raises(JournalDamaged, match="exact planned edge"):
        await control_b.registry_promote_initial(
            LOCAL_ADMIN,
            component=definition.name,
            version=planned_version,
            idempotency_key=key,
        )
    assert world._registry.stable_version(definition.name) == other_version

    # A legacy shape with no migration witness is not history but a downgrade,
    # and the seal boundary refuses it before any replay law is consulted.
    _strip_terminal_rejection_policy(
        journal._db_path,
        command_id,
        response_json=stored,
    )
    with pytest.raises(JournalDamaged, match=_NO_DOMAIN_PLAN_WITNESS):
        await control_b.registry_promote_initial(
            LOCAL_ADMIN,
            component=definition.name,
            version=planned_version,
            idempotency_key=key,
        )
    await control_a.shutdown()
    await control_b.shutdown()


async def test_evaluated_promotion_domain_rejection_is_exact(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    component = "control/promotion-rejected-after-plan"
    v1, planned_version, planned_attestation = _candidate(world, component)
    key = "promotion-rejected-after-plan"
    command_id = command_id_for(AUTHORITY_ACTOR.actor_id, "registry_promote", key)
    control_a = _fresh_control(
        world,
        journal,
        "control-promotion-rejected-a",
        fault_probe=_crash_at("registry_promote", "after_plan"),
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(InjectedCrash):
        await control_a.registry_promote(
            AUTHORITY_ACTOR,
            component=component,
            version=planned_version,
            attestation_id=planned_attestation,
            idempotency_key=key,
        )
    assert _stored_plan_kind(journal, command_id) == "promotion"

    other_version, other_attestation = _competing_candidate(
        world,
        component,
        baseline=v1,
        role="harness",
    )
    world._promote_version(
        component=component,
        version=other_version,
        attestation_id=other_attestation,
        actor="competing-promotion",
    )
    clock.advance(31)
    control_b = _fresh_control(
        world,
        journal,
        "control-promotion-rejected-b",
        run_host=cast(RunHost, _PassiveHost()),
    )
    rejected = await control_b.registry_promote(
        AUTHORITY_ACTOR,
        component=component,
        version=planned_version,
        attestation_id=planned_attestation,
        idempotency_key=key,
    )
    assert isinstance(rejected, ControlRejected)
    assert rejected.faults[0].details == {
        "component": component,
        "planned_from": str(v1),
        "planned_to": str(planned_version),
    }
    replay = await control_b.registry_promote(
        AUTHORITY_ACTOR,
        component=component,
        version=planned_version,
        attestation_id=planned_attestation,
        idempotency_key=key,
    )
    assert replay == rejected

    _rewrite_terminal_fault(
        journal._db_path,
        command_id,
        details={"component": component},
    )
    with pytest.raises(JournalDamaged, match="exact planned edge"):
        await control_b.registry_promote(
            AUTHORITY_ACTOR,
            component=component,
            version=planned_version,
            attestation_id=planned_attestation,
            idempotency_key=key,
        )
    assert world._registry.stable_version(component) == other_version
    await control_a.shutdown()
    await control_b.shutdown()


async def test_rollback_domain_rejection_is_exact(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    component = "control/rollback-rejected-after-plan"
    v1, v2, v2_attestation = _candidate(world, component)
    world._promote_version(
        component=component,
        version=v2,
        attestation_id=v2_attestation,
        actor="rollback-setup",
    )
    key = "rollback-rejected-after-plan"
    command_id = command_id_for(AUTHORITY_ACTOR.actor_id, "registry_rollback", key)
    control_a = _fresh_control(
        world,
        journal,
        "control-rollback-rejected-a",
        fault_probe=_crash_at("registry_rollback", "after_plan"),
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(InjectedCrash):
        await control_a.registry_rollback(
            AUTHORITY_ACTOR,
            component=component,
            expected_stable=v2,
            idempotency_key=key,
        )
    assert _stored_plan_kind(journal, command_id) == "rollback"

    other_version, other_attestation = _competing_candidate(
        world,
        component,
        baseline=v2,
        role="harness",
    )
    world._promote_version(
        component=component,
        version=other_version,
        attestation_id=other_attestation,
        actor="competing-rollback",
    )
    clock.advance(31)
    control_b = _fresh_control(
        world,
        journal,
        "control-rollback-rejected-b",
        run_host=cast(RunHost, _PassiveHost()),
    )
    rejected = await control_b.registry_rollback(
        AUTHORITY_ACTOR,
        component=component,
        expected_stable=v2,
        idempotency_key=key,
    )
    assert isinstance(rejected, ControlRejected)
    assert rejected.faults[0].details == {
        "component": component,
        "planned_from": str(v2),
        "planned_to": str(v1),
    }
    replay = await control_b.registry_rollback(
        AUTHORITY_ACTOR,
        component=component,
        expected_stable=v2,
        idempotency_key=key,
    )
    assert replay == rejected

    _rewrite_terminal_fault(
        journal._db_path,
        command_id,
        message="forged rollback race",
    )
    with pytest.raises(JournalDamaged, match="exact planned edge"):
        await control_b.registry_rollback(
            AUTHORITY_ACTOR,
            component=component,
            expected_stable=v2,
            idempotency_key=key,
        )
    assert world._registry.stable_version(component) == other_version
    await control_a.shutdown()
    await control_b.shutdown()


async def test_resume_domain_plan_rejection_replays_and_refuses_same_code_tampering(
    world: Any,
    journal: SqliteJournal,
) -> None:
    """A lost attempt fence has one response derived from its immutable plan."""

    run_id = _prepare_failed_run(world, journal, "resume-damaged-rejection")
    key = "resume-damaged-rejection"
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_resume", key)
    control = _fresh_control(
        world,
        journal,
        "control-resume-damaged",
        run_host=cast(RunHost, _SupersedingHost()),
    )
    rejected = await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    assert isinstance(rejected, ControlRejected)
    assert [fault.code for fault in rejected.faults] == [ControlCode.RUN_NOT_RESUMABLE]
    assert _stored_plan_kind(journal, command_id) == "resume"

    replay = await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    assert replay == rejected

    _rewrite_terminal_fault(
        journal._db_path,
        command_id,
        message="forged refusal under the lawful code",
    )
    with pytest.raises(JournalDamaged, match="exact planned refusal"):
        await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    await control.shutdown()


async def test_current_resume_wire_downgrade_requires_migration_era_evidence(
    world: Any,
    journal: SqliteJournal,
) -> None:
    """Mutable post-plan state cannot be invented as old refusal evidence."""

    run_id = _prepare_failed_run(world, journal, "legacy-resume-rejection")
    key = "legacy-resume-rejection"
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_resume", key)
    control = _fresh_control(
        world,
        journal,
        "control-legacy-resume-rejection",
        run_host=cast(RunHost, _SupersedingHost()),
    )
    current = await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    assert isinstance(current, ControlRejected)

    legacy = ControlRejected.one_fault(
        ControlCode.RUN_NOT_RESUMABLE,
        f"resume intent for {run_id!r} was superseded at its attempt fence",
        "submit a new resume command after refreshing run status",
        {"reason": "attempt_superseded"},
    )
    _rewrite_resume_as_legacy_rejection(journal._db_path, command_id, legacy)
    with pytest.raises(
        JournalDamaged,
        match=r"resume_plan_pre_v7.*no positive seal",
    ):
        await control.runs_resume(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    await control.shutdown()
