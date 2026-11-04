"""An unchanged, declared workspace READ component across compatible profiles."""

from constructicon.api import claude_qualification as claude
from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import ScopePath
from constructicon.core.admission import AdmissionCode, AdmissionRejected
from constructicon.core.component import CapabilityRequirement
from constructicon.core.control import RegistrationCommandResult, RunSubmission
from constructicon.core.executor import ExecutorSuccess, TaskSpec
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.manifest import parse_manifest_json, source_graph_hash_for
from constructicon.core.native_operator import NativeOperatorExecutorProfileV3
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.executors.claude_provider import ClaudeOperatorProvider
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_claude_qualification import assembled as assembled
from tests.api.test_claude_qualification import qualified as qualified
from tests.api.test_control_response_loss import LOCAL_ADMIN, RUN_ACTOR
from tests.conftest import ISSUE, SUMMARY, atomic, await_attempt_terminal
from tests.substrate.test_claude_provider import provider as provider
from tests.substrate.test_codex_adapter import (
    CAPABILITY,
    GRANTS,
    bare_launcher,
    clean_native,
    descriptor_of,
)
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_read_stage import provider as codex_provider
from tests.substrate.test_codex_read_stage import read_authorization
from tests.substrate.test_pi_provider import world as world
from tests.substrate.test_pi_read import grants as pi_grants

NAME = "common-workspace-read"
SCOPE = ScopePath(segments=(NAME, "worker"))


async def read_fixture(ctx, inputs):
    result = await ctx.capability("executor").execute(
        TaskSpec(instruction=f"Read {inputs['issue']['title']} once and report its contents."),
        workspace=ctx.capability("workspace"),
        grants=ctx.grants,
    )
    assert isinstance(result, ExecutorSuccess), result
    assert isinstance(result.raw_reply, str)
    return {"summary": result.raw_reply}


def definition():
    component, _ = atomic("test/common-workspace-read", (ISSUE,), (SUMMARY,), read_fixture)
    return component.model_copy(update={"capability_requirements": (
        CapabilityRequirement(alias="executor", kind="executor"),
        CapabilityRequirement(alias="workspace", kind="workspace.contained"),
    )})


def graph(executor_id, workspace_id=None):
    bind = {"executor": executor_id}
    if workspace_id is not None:
        bind["workspace"] = workspace_id
    component = definition()
    return Graph(name=NAME, inputs=(ISSUE,), outputs=(SUMMARY,), nodes=(
        GraphNode(id="worker", body=Ref(
            component=component.name, version=str(component.content_hash()), bind=bind,
        )),
    ))


def descriptors(executor_id, executor, workspace_id, revision):
    return {
        executor_id: descriptor_of(executor, executor_id),
        workspace_id: CapabilityDescriptor(
            capability_id=workspace_id, kind="workspace.contained", revision=revision, leased=True,
        ),
    }


async def register(control):
    result = await control.registry_register(
        LOCAL_ADMIN, definition=definition(), idempotency_key="common-read-register",
    )
    assert isinstance(result, RegistrationCommandResult), result
    assert result.version == definition().content_hash()


async def run_read(journal, executor_id, executor, workspace, grants, actor, key, filename, answer):
    workspace_id = executor.workspace_capability_id
    system = Constructicon(
        journal=journal, root_grants=grants,
        capabilities={executor_id: executor, workspace_id: workspace},
        catalog=descriptors(executor_id, executor, workspace_id, executor.workspace_revision),
    )
    control = ControlPlane(system=system, store=journal)
    before = workspace.authority.read_ref(workspace.target_ref)
    assert before is not None
    await control.startup()
    try:
        await register(control)
        submitted = await control.runs_start(
            actor, proposal=graph(executor_id, workspace_id),
            inputs={"issue": {"title": filename}}, idempotency_key=key,
        )
        assert isinstance(submitted, RunSubmission), submitted
        terminal = await await_attempt_terminal(
            journal, submitted.run_id, baseline_event_seq=0, timeout_s=60,
        )
        assert terminal.kind == "RunSucceeded", journal.events(submitted.run_id)
    finally:
        await control.shutdown()
    rows = journal.capability_leases(submitted.run_id)
    assert len(rows) == 2 and {row.binding_id for row in rows} == {"executor", "workspace"}
    assert all(row.state == "closed" and row.disposition == "released" for row in rows)
    manifest_hash = journal.run_manifest_hash(submitted.run_id)
    assert manifest_hash is not None
    manifest_json = journal.load_manifest_json(manifest_hash)
    assert manifest_json is not None
    manifest = parse_manifest_json(manifest_json)
    (resolved,) = manifest.resolved_components
    assert resolved.scope == SCOPE
    assert resolved.resolved_version == definition().content_hash()
    assert resolved.implementation_digest == definition().body.source_digest
    bindings = {binding.binding: binding for binding in manifest.capability_bindings}
    assert bindings["executor"].capability_id == executor_id
    assert bindings["executor"].revision == executor.identity.revision
    assert bindings["workspace"].capability_id == workspace_id
    assert bindings["workspace"].revision == executor.workspace_revision
    assert all(bindings[alias].effective_grants == grants for alias in ("executor", "workspace"))
    checkpoint = journal.checkpoint(submitted.run_id, rows[0].path)
    assert checkpoint is not None
    assert checkpoint.outputs["summary"].payload == answer
    assert workspace.authority.read_ref(workspace.target_ref) == before
    assert not list(workspace.root.glob("payloads/*"))


async def test_common_workspace_read_with_scripted_pi(world):
    _system, journal, executor, workspace, launcher, _facts = world
    await run_read(
        journal, "pi-read-fixture", executor, workspace, pi_grants(),
        RUN_ACTOR, "common-pi-read", "fixture.txt", "Read: leased workspace bytes",
    )
    assert launcher.calls == 1 and launcher.joined and launcher.eof


async def test_common_workspace_read_with_scripted_claude(qualified):
    a = qualified
    previous = a.executor.qualification
    proposal = graph(claude.CAPABILITY, claude.WORKSPACE_CAPABILITY)
    authorization = previous.model_copy(update={
        "scope": SCOPE, "actor_id": RUN_ACTOR.actor_id,
        "source_graph_hash": source_graph_hash_for(proposal),
    })
    executor = ClaudeOperatorProvider(**{**a.kwargs, "qualification": authorization})
    await run_read(
        SqliteJournal(authorization.journal), claude.CAPABILITY, executor,
        executor.workspace_provider, authorization.grants, RUN_ACTOR,
        authorization.idempotency_key, "ready.txt", "ready",
    )
    assert len(a.state.workers) == len(a.state.exchanges) == 1
    assert a.state.guards == a.state.locks == 0


async def test_codex_native_read_shape_cannot_supply_the_required_workspace(
    tmp_path, portable_binding, monkeypatch,
):
    native = clean_native()
    launcher = bare_launcher(native)
    plain = codex_provider(tmp_path, portable_binding, launcher)
    proposal = graph(CAPABILITY)
    journal = SqliteJournal(tmp_path / "control.sqlite")
    record = tmp_path / "codex-attempt.json"
    authorization = read_authorization(
        plain, record, actor_id=RUN_ACTOR.actor_id, scope=SCOPE,
        source_graph_hash=source_graph_hash_for(proposal), journal=str(tmp_path / "control.sqlite"),
    )
    executor = codex_provider(tmp_path, portable_binding, launcher, authorization)
    assert isinstance(executor.profile, NativeOperatorExecutorProfileV3)
    assert not executor.profile.grant_policy.workspace_required
    assert executor.profile.grant_faults(GRANTS) == ()
    assert executor.authorizes_admission(
        source_graph_hash=source_graph_hash_for(proposal), capability_id=CAPABILITY,
    )
    system = Constructicon(
        journal=journal, root_grants=GRANTS,
        capabilities={CAPABILITY: executor}, catalog={CAPABILITY: descriptor_of(executor)},
    )
    host = RunHost(system, journal=journal)

    def no_worker(*args, **kwargs):
        raise AssertionError("an incompatible proposal must not reach RunHost.launch")

    monkeypatch.setattr(host, "launch", no_worker)
    control = ControlPlane(system=system, store=journal, run_host=host)
    await control.startup()
    try:
        await register(control)
        result = await control.runs_start(
            RUN_ACTOR, proposal=proposal, inputs={"issue": {"title": "fixture.txt"}},
            idempotency_key=authorization.idempotency_key,
        )
        assert isinstance(result, AdmissionRejected), result
        assert [fault.code for fault in result.faults] == [
            AdmissionCode.GRAPH_CAPABILITY_MISSING_BINDING,
        ]
        assert result.faults[0].details["alias"] == "workspace"
    finally:
        await control.shutdown()
    assert not journal.run_records(limit=2)
    assert not journal.capability_leases(authorization.run_id)
    assert not record.exists()
    assert not launcher.calls
