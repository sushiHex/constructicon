"""N2 WRITE composition: scripted native, real worker/capture/contained gate.

The native byte peer and store syscalls are doubles. The worker, acquisition
guards, Git capture and gate are physical Linux operations. This is neither a
live subscription turn nor a qualification of applied vendor configuration.
"""

import asyncio
from dataclasses import dataclass, field, fields

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.control import (
    PromotionCommandResult,
    RegistrationCommandResult,
    RunSubmission,
)
from constructicon.core.gates import MergeEvaluation
from constructicon.core.grants import Posture
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.run import RunStatus
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.effects.git import MergeVerifiedEffect
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.gates.contained import ContainedGateRunner
from constructicon.substrate.gates.runner import CheckSpec
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import (
    LOCAL_ADMIN,
    RUN_ACTOR,
    _fresh_control,
    _PassiveHost,
)
from tests.captureworld import register_capture
from tests.conftest import atomic
from tests.gateworld import register_gate
from tests.gitworld import EVALUATION, MERGED, merge_impl
from tests.substrate.test_codex_adapter import (
    FINISHED,
    ScriptedLauncher,
    bare_launcher,
    descriptor_of,
)
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_write import WRITE_GRANTS, write_native, write_provider
from tests.substrate.test_contained_capture import write_provider as capture_provider
from tests.substrate.test_contained_gates import ObservedLauncher
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher


@dataclass(frozen=True, kw_only=True)
class PhysicalWorkerLauncher(ScriptedLauncher):
    worker_calls: list = field(default_factory=list)

    async def run(self, command, **kwargs):
        self.worker_calls.append((command, kwargs))
        return await LinuxLauncher.run(self, command, **kwargs)


def write_system(journal, workspace, executor, gate, *, effects=None):
    return Constructicon(
        journal=journal, root_grants=WRITE_GRANTS, effects=effects,
        capabilities={"capture": workspace, "recorded": executor, "gate": gate},
        catalog={
            "capture": CapabilityDescriptor(
                capability_id="capture", kind="workspace.contained", leased=True,
                revision=workspace.revision, requires_posture=Posture.WRITE,
            ),
            "recorded": descriptor_of(executor, "recorded"),
            "gate": CapabilityDescriptor(
                capability_id="gate", kind="gates.contained", leased=True,
                revision=gate.revision,
            ),
        },
    )


async def write_graph(control):
    proposal = await register_capture(control, executor=True)
    check = await register_gate(control)
    return Graph(
        name="native-write-capture-gate", inputs=proposal.inputs, outputs=check.outputs,
        nodes=(*proposal.nodes, *check.nodes),
        connections=(Connection(src="writer", dst="check"),),
    )


async def test_write_capture_graph_is_admitted_without_starting_a_process(
    provider, portable_binding, tmp_path,
):
    scripted = bare_launcher(native=write_native())
    executor = write_provider(
        scripted, binding=portable_binding[1:3], root=tmp_path / "executor",
    )
    workspace = capture_provider(provider, scripted)
    journal = SqliteJournal(tmp_path / "admission.sqlite")
    gate = await ContainedGateRunner.create(
        journal=journal, authority=workspace.authority, root=tmp_path / "gates",
        target_ref=workspace.target_ref, provider_id="n2-write-gate", launcher=ObservedLauncher(),
        checks=(CheckSpec("inert", ("/usr/bin/python3", "-c", "pass"), 20),),
    )
    system = write_system(journal, workspace, executor, gate)
    control = _fresh_control(system, journal, "write-admission", run_host=_PassiveHost())
    await control.startup()
    try:
        graph = await write_graph(control)
        submitted = await control.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"goal": {"message": "write one file"}},
            idempotency_key="admit-write",
        )
        assert isinstance(submitted, RunSubmission), submitted
        assert not scripted.calls and not scripted.commands and not executor.handles
        assert not workspace.root.exists() and not gate.root.exists()
    finally:
        await control.shutdown()


@pytest.mark.parametrize("gate_passes", [True, False])
async def test_callback_change_is_captured_and_the_exact_candidate_is_gated(
    launcher, provider, portable_binding, tmp_path, gate_passes,
):
    program = (
        "from pathlib import Path\n"
        "assert not Path('/vendor-store').exists()\n"
        "assert not Path('/tmp/home/.codex').exists()\n"
        "assert Path('/proc/net/route').read_text().splitlines()[1:] == []\n"
        "Path('callback.txt').write_text('one callback')\n"
    )
    native = write_native(program=program)
    physical = PhysicalWorkerLauncher(
        **{item.name: getattr(launcher, item.name) for item in fields(LinuxLauncher)},
        native=native, result=FINISHED,
    )
    executor = write_provider(
        physical, binding=portable_binding[1:3], root=tmp_path / "executor",
    )
    workspace = capture_provider(provider, launcher)
    journal = SqliteJournal(tmp_path / "write.sqlite")
    gate_program = (
        "from pathlib import Path; "
        "assert Path('callback.txt').read_text() == 'one callback'; "
        f"assert {gate_passes!r}"
    )
    gate = await ContainedGateRunner.create(
        journal=journal, authority=workspace.authority, root=tmp_path / "gates",
        target_ref=workspace.target_ref, provider_id="n2-write-gate", launcher=launcher,
        checks=(CheckSpec("callback-content", ("/usr/bin/python3", "-c", gate_program), 20),),
    )
    system = write_system(journal, workspace, executor, gate)
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        graph = await write_graph(control)
        submitted = await control.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"goal": {"message": "write one file"}},
            idempotency_key="n2-write",
        )
        assert isinstance(submitted, RunSubmission), submitted
        async with asyncio.timeout(60):
            while journal.run_state(submitted.run_id).status not in (
                RunStatus.SUCCEEDED, RunStatus.FAILED,
            ):
                await asyncio.sleep(0.01)
        assert journal.run_state(submitted.run_id).status is RunStatus.SUCCEEDED, (
            journal.events(submitted.run_id)
        )
        leases = journal.capability_leases(submitted.run_id)
        assert len(leases) == 3 and all(lease.state == "closed" for lease in leases)
        capture_lease = next(lease for lease in leases if lease.binding_id == "workspace")
        gate_lease = next(lease for lease in leases if lease.binding_id == "gates")
        candidate = journal.checkpoint(submitted.run_id, capture_lease.path).outputs[
            "candidate"
        ].payload["commit"]
        evaluation = MergeEvaluation.model_validate(
            journal.checkpoint(submitted.run_id, gate_lease.path).outputs["evaluation"].payload,
        )
        assert evaluation.subject is not None and evaluation.subject.candidate == candidate
        assert evaluation.ok is gate_passes
        # A failed check is still durable evidence, not merge authority.
        assert evaluation.attestation_id is not None
        attestation = journal.load_attestation(evaluation.attestation_id)
        assert attestation is not None and attestation.subject == evaluation.subject
        assert attestation.checks == evaluation.checks
        assert workspace.authority._run("show", f"{candidate}:callback.txt").stdout == (
            "one callback"
        )
        assert workspace.authority.resolve_ref(workspace.target_ref) != candidate
        assert len(physical.worker_calls) == len(physical.commands) == 1
        command, worker = physical.worker_calls[0]
        assert command[0] == "/usr/bin/python3"
        assert worker["posture"] is Posture.WRITE and worker["workspace"] is not None
        assert len(worker["guard_fds"]) == 1 and "native_store" not in worker
        assert all(handle.closed for handle in executor.handles)
        assert not list(workspace.root.glob("payloads/*"))
    finally:
        await control.shutdown()


@pytest.mark.parametrize("gate_passes", [True, False])
async def test_write_candidate_installs_only_after_the_contained_gate(
    launcher, provider, portable_binding, tmp_path, gate_passes,
):
    native = write_native(
        program="from pathlib import Path; Path('callback.txt').write_text('installed')",
    )
    physical = PhysicalWorkerLauncher(
        **{item.name: getattr(launcher, item.name) for item in fields(LinuxLauncher)},
        native=native, result=FINISHED,
    )
    executor = write_provider(physical, binding=portable_binding[1:3], root=tmp_path / "executor")
    workspace = capture_provider(provider, launcher)
    journal = SqliteJournal(tmp_path / "install.sqlite")
    gate_program = (
        "from pathlib import Path; "
        "assert Path('callback.txt').read_text() == 'installed'; "
        f"assert {gate_passes!r}"
    )
    gate = await ContainedGateRunner.create(
        journal=journal, authority=workspace.authority, root=tmp_path / "gates",
        target_ref=workspace.target_ref, provider_id="n2-install-gate", launcher=launcher,
        checks=(CheckSpec("callback-content", ("/usr/bin/python3", "-c", gate_program), 20),),
    )
    effect = MergeVerifiedEffect(journal=journal, authority=workspace.authority)
    system = write_system(journal, workspace, executor, gate, effects={"merge_verified": effect})
    control = ControlPlane(system=system, store=journal)
    before = workspace.authority.resolve_ref(workspace.target_ref)
    await control.startup()
    try:
        graph = await write_graph(control)
        definition, _ = atomic("test/write-merge", (EVALUATION,), (MERGED,), merge_impl)
        registered = await control.registry_register(
            LOCAL_ADMIN, definition=definition, idempotency_key="register-write-merge",
        )
        assert isinstance(registered, RegistrationCommandResult), registered
        promoted = await control.registry_promote_initial(
            LOCAL_ADMIN, component=definition.name, version=registered.version,
            idempotency_key="promote-write-merge",
        )
        assert isinstance(promoted, PromotionCommandResult), promoted
        graph = graph.model_copy(update={
            "outputs": (MERGED,),
            "nodes": (*graph.nodes, GraphNode(id="merge", body=Ref(component=definition.name))),
            "connections": (*graph.connections, Connection(src="check", dst="merge")),
        })
        inputs = {"goal": {"message": "write and install"}}
        submitted = await control.runs_start(
            RUN_ACTOR, proposal=graph, inputs=inputs, idempotency_key="write-install",
        )
        assert isinstance(submitted, RunSubmission), submitted
        async with asyncio.timeout(60):
            while journal.run_state(submitted.run_id).status not in (
                RunStatus.SUCCEEDED, RunStatus.FAILED,
            ):
                await asyncio.sleep(0.01)
        events = journal.events(submitted.run_id)
        assert journal.run_state(submitted.run_id).status is (
            RunStatus.SUCCEEDED if gate_passes else RunStatus.FAILED
        ), events
        leases = journal.capability_leases(submitted.run_id)
        assert len(leases) == 3 and all(lease.state == "closed" for lease in leases)
        writer = next(lease for lease in leases if lease.binding_id == "workspace")
        checker = next(lease for lease in leases if lease.binding_id == "gates")
        candidate = journal.checkpoint(submitted.run_id, writer.path).outputs[
            "candidate"
        ].payload["commit"]
        evaluation = MergeEvaluation.model_validate(
            journal.checkpoint(submitted.run_id, checker.path).outputs["evaluation"].payload,
        )
        assert evaluation.subject is not None and evaluation.subject.candidate == candidate
        assert evaluation.ok is gate_passes and evaluation.attestation_id is not None
        attestation = journal.load_attestation(evaluation.attestation_id)
        assert attestation is not None and attestation.subject == evaluation.subject
        assert attestation.ok is gate_passes
        installed = workspace.authority.resolve_ref(workspace.target_ref)
        assert sum(event.kind == "EffectCommitted" for event in events) == int(gate_passes)
        if gate_passes:
            assert installed == evaluation.subject.merge_commit
            assert workspace.authority.parents_of(installed) == (before, candidate)
            assert workspace.authority._run("show", f"{installed}:callback.txt").stdout == (
                "installed"
            )
        else:
            assert installed == before
        replay = await control.runs_start(
            RUN_ACTOR, proposal=graph, inputs=inputs, idempotency_key="write-install",
        )
        assert isinstance(replay, RunSubmission)
        assert replay.run_id == submitted.run_id and replay.command.replayed is True
        assert workspace.authority.resolve_ref(workspace.target_ref) == installed
        assert len(physical.worker_calls) == len(physical.commands) == 1
        assert all(handle.closed for handle in executor.handles)
        assert not list(workspace.root.glob("payloads/*"))
    finally:
        await control.shutdown()
