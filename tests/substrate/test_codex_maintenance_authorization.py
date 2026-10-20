"""Credential-free accepting and refusing proofs for the separate maintenance attempt."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from constructicon.core.address import ExecutionPath
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.core.maintenance import MaintenanceAttemptAuthorization
from constructicon.core.manifest import CapabilityBinding, CapabilityLease
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunLease
from constructicon.core.workspace import LeaseContext, StaleAcquisition
from constructicon.substrate.executors import codex
from constructicon.substrate.executors import maintenance as reader
from constructicon.substrate.executors.attempt_record import AttemptRecord
from constructicon.substrate.executors.codex import (
    UNQUALIFIED_PREREQUISITES,
    CodexOperatorProvider,
    launch_identity,
)
from constructicon.substrate.executors.codex_protocol import CONTAINED_PYTHON_CATALOG
from constructicon.substrate.executors.linux import ProcessResult
from constructicon.substrate.git import acquisition, contained
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from tests.core.test_maintenance_authorization import GRANTS, SCOPE, authorization
from tests.gitworld import seed_authority
from tests.native_operator_world import native_egress
from tests.substrate.test_codex_adapter import BINARY, CONFIGURATION, EXPECTED, FINISHED
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_write import (
    ControlledWorkerLauncher,
    portable_guard,
    write_native,
    write_profile,
)


def launcher(native=None):
    return ControlledWorkerLauncher(
        runtime_root=Path("/opt/codex-runtime"),
        expected_runtime=digest("test-maintenance-runtime", 1, "runtime"),
        bubblewrap=Path("/usr/bin/bwrap"), policy=Path("/etc/apparmor.d/constructicon-m8-launch"),
        expected_policy_sha256="0" * 64,
        native=native if native is not None else write_native(program="print('one call')"),
        result=FINISHED,
        worker_result=ProcessResult(0, b"worker-output", b"", 0.1, payload_returncode=0),
    )


def provider(tmp_path, binding, *, maintenance=None, qualification=None, native_launcher=None):
    launch = native_launcher if native_launcher is not None else launcher()
    profile = write_profile()
    identity = launch_identity(
        launcher=launch, profile=profile, egress=native_egress(), store=binding[1].sealed,
        executable_digest=digest("test-maintenance-binary", 1, BINARY),
        configuration=CONFIGURATION, catalog=CONTAINED_PYTHON_CATALOG,
        authenticated_startup_conformance_revision=digest("test-maintenance-startup", 1, "fixture"),
        subscription_mode_conformance_revision=digest("test-maintenance-mode", 1, "fixture"),
    )
    return CodexOperatorProvider(
        launcher=launch, profile=profile, identity=identity, expected_account=EXPECTED,
        binary=BINARY, configuration=CONFIGURATION, catalog=CONTAINED_PYTHON_CATALOG,
        acquisition_root=tmp_path / "executor", binding_store=binding[1], closure=binding[2],
        maintenance=maintenance, qualification=qualification,
    )


def authorized(tmp_path, binding, **changes):
    plain = provider(tmp_path, binding)
    granted = authorization(
        revision=plain.identity.revision,
        operator_binding_digest=plain.identity.store.operator_binding_digest,
        not_after=datetime.now(UTC) + timedelta(hours=1),
        attempt_record=str(tmp_path / "maintenance.attempt"), **changes,
    )
    return provider(tmp_path, binding, maintenance=granted), granted


def context(granted, **changes):
    fields = {
        "run_lease": RunLease(run_id=granted.run_id, owner_id="owner-1", epoch=1,
                              expires_at=datetime.now(UTC) + timedelta(minutes=5)),
        "binding": CapabilityBinding(scope=SCOPE, binding=granted.binding,
                                     capability_id=granted.capability_id,
                                     revision=granted.revision, effective_grants=GRANTS),
        "path": ExecutionPath(scope=SCOPE), "source_graph_hash": granted.source_graph_hash,
        "manifest_hash": digest("test-maintenance-manifest", 1, "manifest"),
        "check_control": lambda: None, **changes,
    }
    return LeaseContext(**fields)


@pytest.fixture
def portable_guards(monkeypatch, portable_acquisition_namespace):
    # Only the POSIX lock primitive is replaced. Concrete custody/closure code runs.
    monkeypatch.setattr(codex, "acquisition_guard", portable_guard)
    monkeypatch.setattr(contained, "acquisition_guard", portable_guard)
    monkeypatch.setattr(acquisition, "acquisition_guard", portable_guard)


async def workspace_for(tmp_path, executor, invocation):
    workspace_provider = ContainedWriteWorkspaceProvider(
        GitAuthority(seed_authority(tmp_path / "workspace-authority"), tmp_path / "legacy"),
        root=tmp_path / "workspaces", target_ref="refs/heads/main",
        provider_id="maintenance-workspace", posture=Posture.WRITE, launcher=executor.launcher,
    )
    work_context = replace(invocation, binding=invocation.binding.model_copy(update={
        "binding": "workspace", "capability_id": "workspace",
        "revision": workspace_provider.revision,
    }))
    work = await workspace_provider.acquire(work_context)
    Path(work.resource.path).mkdir(parents=True)
    work.resource._phase.ready = True
    return workspace_provider, work


async def test_one_maintenance_turn_records_purpose_and_completed_dispatch(
    tmp_path, portable_binding, portable_guards, monkeypatch,
):
    executor, granted = authorized(tmp_path, portable_binding)
    native = executor.launcher.native
    respond = native._respond

    def check_intent(raw):
        if json.loads(raw).get("method") == "turn/start":
            assert json.loads(Path(granted.attempt_record).read_text())["phase"] == "intent"
        respond(raw)

    monkeypatch.setattr(native, "_respond", check_intent)
    invocation = context(granted)
    acquired = await executor.acquire(invocation)
    record = json.loads(Path(granted.attempt_record).read_text())
    assert record.get("purpose") == granted.purpose and record["phase"] == "acquired"
    assert "dispatch" not in record and "turn/start" not in native.methods
    await acquired.materialize()
    work_provider, work = await workspace_for(tmp_path, executor, invocation)
    try:
        outcome = await acquired.resource.execute(
            TaskSpec(instruction="fixed worker"), workspace=work.resource, grants=GRANTS,
        )
        assert outcome.status == "success" and outcome.output == "done"
        assert native.methods.count("turn/start") == 1
        assert len(executor.launcher.worker_calls) == 1
        assert 0 < executor.launcher.calls[0]["timeout_s"] <= 300
        record = json.loads(Path(granted.attempt_record).read_text())
        assert (record.get("purpose"), record["phase"], record["dispatch"]) == (
            "plan-manifest-maintenance", "outcome", "completed",
        )
        assert "stage" not in record and "done" not in Path(granted.attempt_record).read_text()
        with pytest.raises(ContractViolation, match="executes one task only"):
            await acquired.resource.execute(TaskSpec(instruction="again"),
                                            workspace=work.resource, grants=GRANTS)
    finally:
        await executor.close(acquired, "discard")
        await work_provider.close(work, "discard")


async def test_reservation_spends_one_attempt_with_a_fresh_provider_at_epoch_one(
    tmp_path, portable_binding,
):
    executor, granted = authorized(tmp_path, portable_binding)
    acquired = await executor.acquire(context(granted))
    assert not acquired.resource.entered and acquired.resource.dispatch
    assert executor.unavailable_reasons == UNQUALIFIED_PREREQUISITES
    assert executor.unavailable_reasons == provider(tmp_path, portable_binding).unavailable_reasons
    previous = Path(granted.attempt_record).read_bytes()
    successor = provider(tmp_path, portable_binding, maintenance=granted)
    with pytest.raises(ContractViolation, match="one attempt is spent"):
        await successor.acquire(context(granted))
    assert successor.handles == [] and Path(granted.attempt_record).read_bytes() == previous
    assert "turn/start" not in successor.launcher.native.methods


async def test_a_preexisting_attempt_refuses_before_a_handle_exists(tmp_path, portable_binding):
    executor, granted = authorized(tmp_path, portable_binding)
    AttemptRecord.reserve(Path(granted.attempt_record), {"purpose": granted.purpose})
    original = Path(granted.attempt_record).read_bytes()
    with pytest.raises(ContractViolation, match="one attempt is spent"):
        await executor.acquire(context(granted))
    assert executor.handles == [] and Path(granted.attempt_record).read_bytes() == original


async def test_qualification_record_keeps_its_old_shape_and_cannot_be_reused_by_maintenance(
    tmp_path, portable_binding,
):
    _, granted = authorized(tmp_path, portable_binding)
    qualification = QualificationAuthorization(
        authorization_id="old-write", stage="qualification-write", actor_id=granted.actor_id,
        idempotency_key=granted.idempotency_key, scope=SCOPE, binding=granted.binding,
        source_graph_hash=granted.source_graph_hash, capability_id=granted.capability_id,
        revision=granted.revision, operator_binding_digest=granted.operator_binding_digest,
        journal=granted.journal, max_epoch=1, not_after=granted.not_after,
        grants=GRANTS, attempt_record=granted.attempt_record,
        write={"workspace": granted.workspace.model_dump(mode="json"),
               "gate": granted.gate.model_dump(mode="json"),
               "fixture": {"identity": granted.source_graph_hash,
                           "base_commit": granted.request.base_commit,
                           "target_ref": granted.request.target_ref},
               "report_definition": granted.application_revision},
    )
    old_provider = provider(tmp_path, portable_binding, qualification=qualification)
    await old_provider.acquire(context(granted))
    old = Path(granted.attempt_record).read_bytes()
    assert set(json.loads(old)) == {
        "authorization_id", "run_id", "epoch", "acquisition_id", "phase", "at",
    }
    new_provider = provider(tmp_path, portable_binding, maintenance=granted)
    with pytest.raises(ContractViolation, match="one attempt is spent"):
        await new_provider.acquire(context(granted))
    assert new_provider.handles == [] and Path(granted.attempt_record).read_bytes() == old


@pytest.mark.parametrize("change,fault", [
    ({"source_graph_hash": None}, "different source graph"),
    ({"path": ExecutionPath(scope=SCOPE.child("other"))}, "different invocation"),
    ({"check_control": None}, "invocation control"),
])
async def test_foreign_invocations_mint_no_handle_or_record(
    tmp_path, portable_binding, change, fault,
):
    executor, granted = authorized(tmp_path, portable_binding)
    with pytest.raises(ContractViolation, match=fault):
        await executor.acquire(context(granted, **change))
    assert executor.handles == [] and not Path(granted.attempt_record).exists()


async def test_epoch_two_and_expired_acquisitions_do_not_spend_attempt(tmp_path, portable_binding):
    executor, granted = authorized(tmp_path, portable_binding)
    invocation = context(granted)
    for changed, fault in (
        (replace(invocation, run_lease=invocation.run_lease.model_copy(update={"epoch": 2})),
         "epoch"),
        (invocation, "expired"),
    ):
        if fault == "expired":
            executor.maintenance = granted.model_copy(update={"not_after": datetime.now(UTC)})
        with pytest.raises(ContractViolation, match=fault):
            await executor.acquire(changed)
        assert not Path(granted.attempt_record).exists() and executor.handles == []


def test_maintenance_and_qualification_are_exclusive_and_not_interchangeable(
    tmp_path, portable_binding,
):
    executor, granted = authorized(tmp_path, portable_binding)
    qualification = QualificationAuthorization(
        authorization_id="old", stage="qualification-no-dispatch", actor_id=granted.actor_id,
        idempotency_key=granted.idempotency_key, scope=SCOPE, binding="executor",
        source_graph_hash=granted.source_graph_hash, capability_id=granted.capability_id,
        revision=granted.revision, operator_binding_digest=granted.operator_binding_digest,
        journal=granted.journal, max_epoch=1, not_after=granted.not_after,
    )
    old_bytes = qualification.model_dump_json()
    with pytest.raises(ContractViolation, match="exclusive"):
        provider(tmp_path, portable_binding, maintenance=granted, qualification=qualification)
    with pytest.raises(ContractViolation, match="separate authorization"):
        provider(tmp_path, portable_binding, maintenance=qualification)
    with pytest.raises(ContractViolation, match="separate authorization"):
        provider(tmp_path, portable_binding, qualification=granted)
    with pytest.raises(ValidationError):
        MaintenanceAttemptAuthorization.model_validate_json(old_bytes)
    assert qualification.model_dump_json() == old_bytes
    assert executor.authorizes_admission(source_graph_hash=granted.source_graph_hash,
                                         capability_id=granted.capability_id)
    assert not executor.authorizes_admission(source_graph_hash=digest("other", 1, "graph"),
                                             capability_id=granted.capability_id)
    assert not executor.authorizes_admission(source_graph_hash=granted.source_graph_hash,
                                             capability_id="other")


@pytest.mark.parametrize("change", [
    {"revision": str(digest("other", 1, "revision"))},
    {"operator_binding_digest": digest("other", 1, "binding")},
    {"max_epoch": 2}, {"purpose": "qualification-write"},
    {"grants": GRANTS.model_copy(update={"timeout_s": 600})},
    {"grants": GRANTS.model_copy(update={"effort": "medium"})},
])
def test_assembly_revalidates_unchecked_copies_and_provider_pins(
    tmp_path, portable_binding, change,
):
    _, granted = authorized(tmp_path, portable_binding)
    with pytest.raises(ContractViolation, match="maintenance authorization"):
        provider(tmp_path, portable_binding, maintenance=granted.model_copy(update=change))


@pytest.mark.parametrize("during_intent", [False, True])
async def test_expiry_on_either_side_of_intent_dispatches_nothing_but_cleanup_still_works(
    tmp_path, portable_binding, portable_guards, monkeypatch, during_intent,
):
    executor, granted = authorized(tmp_path, portable_binding)
    invocation = context(granted)
    acquired = await executor.acquire(invocation)
    await acquired.materialize()
    work_provider, work = await workspace_for(tmp_path, executor, invocation)

    def expire():
        executor.maintenance = granted.model_copy(update={"not_after": datetime.now(UTC)})

    if during_intent:
        intend = AttemptRecord.intend

        def expires_during(record):
            result = intend(record)
            expire()
            return result

        monkeypatch.setattr(AttemptRecord, "intend", expires_during)
    else:
        expire()
    try:
        outcome = await acquired.resource.execute(
            TaskSpec(instruction="fixed"), workspace=work.resource, grants=GRANTS,
        )
        assert outcome.status == "failure" and "expired" in outcome.error.detail
        assert "turn/start" not in executor.launcher.native.methods
        record = json.loads(Path(granted.attempt_record).read_text())
        assert record["dispatch"] == "not dispatched"
    finally:
        await executor.close(acquired, "discard")
        await work_provider.close(work, "discard")
    successor = provider(tmp_path, portable_binding, maintenance=executor.maintenance)
    row = CapabilityLease(
        lease_id=acquired.lease_id, acquisition_epoch=1, run_id=granted.run_id,
        binding_id=granted.binding, path=invocation.path, state="active",
        resource_ref=acquired.resource_ref,
    )
    result = await successor.reconcile(
        replace(invocation, run_lease=invocation.run_lease.model_copy(update={"epoch": 2})),
        (StaleAcquisition(lease=row, disposition="discard"),),
    )
    assert result.reaped == (acquired.resource_ref,)


def test_new_reader_accepts_the_separate_type_and_rejects_ambiguous_bytes(monkeypatch):
    granted = authorization()
    raw = granted.model_dump_json().encode()
    monkeypatch.setattr(reader, "_read_authorization_bytes", lambda path: raw)
    assert reader.read_maintenance_authorization(Path("/owner/auth.json")) == granted
    for malformed in (
        raw[:-1] + b',"purpose":"plan-manifest-maintenance"}',
        raw[:-1] + b',"not_after":NaN}', b"\xff", b"{}", b"[" * 1200 + b"0" + b"]" * 1200,
    ):
        monkeypatch.setattr(reader, "_read_authorization_bytes", lambda path, raw=malformed: raw)
        with pytest.raises(ContractViolation, match="maintenance authorization is unavailable"):
            reader.read_maintenance_authorization(Path("/owner/auth.json"))


async def test_plain_unavailable_provider_never_inherits_the_exception(tmp_path, portable_binding):
    _, granted = authorized(tmp_path, portable_binding)
    plain = provider(tmp_path, portable_binding)
    assert not plain.authorizes_admission(source_graph_hash=granted.source_graph_hash,
                                          capability_id=granted.capability_id)
    with pytest.raises(ContractViolation, match="unavailable operator provider"):
        await plain.acquire(context(granted))
    assert plain.handles == [] and not Path(granted.attempt_record).exists()
