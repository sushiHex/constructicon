"""Fixed N5 qualifications under one root-installed authorization.

The no-dispatch, READ and WRITE stages share the real control-plane lifecycle.
Each binds its fixed graph and exact assembled authority; the provider remains
unavailable outside that authorization. Credential-free smoke shares WRITE's
contained capture/gate path without an executor. This is not an MCP surface:
the import contracts keep the adapter away from this entry and its helpers.

Recovery has one driver, the control plane's own RunHost: calling ``qualify``
again after a crash replays the same command and recovers the same run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId, ScopePath
from constructicon.core.component import CapabilityRequirement, ComponentDef, PythonRef
from constructicon.core.control import (
    ADMIN_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    PromotionCommandResult,
    RegistrationCommandResult,
    RunSubmission,
    command_id_for,
    run_id_for_command,
)
from constructicon.core.envelope import utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorSuccess, TaskSpec
from constructicon.core.grants import EffectiveGrants, Posture
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import Digest, digest
from constructicon.core.manifest import parse_manifest_json, source_graph_hash_for
from constructicon.core.ports import Port
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext, NodeImpl
from constructicon.runtime.registry import CapabilityDescriptor, source_digest_for
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.codex import CodexOperatorHandle, CodexOperatorProvider
from constructicon.substrate.executors.codex_host import READ_GRANTS, HostSession, operator_provider
from constructicon.substrate.executors.qualification import read_authorization
from constructicon.substrate.journal.sqlite import SqliteJournal

if TYPE_CHECKING:
    from constructicon.api._qualification_write_assembly import (
        ContainedWriteResources,
        WriteAssembly,
    )
    from constructicon.core.qualification_write import (
        SmokeQualificationReport,
        WriteQualificationReport,
    )

GRAPH_NAME = "constructicon-qualification"
NODE_ID = "qualify"
EXECUTOR = "executor"
COMPONENT = "constructicon.qualification/no-dispatch"
REQUEST = Port(name="request", type_id="constructicon.qualification/Request", schema_hash="v1")
REPORT = Port(name="report", type_id="constructicon.qualification/Report", schema_hash="v1")
SCOPE = ScopePath(segments=(GRAPH_NAME, NODE_ID))
"""The one invocation an authorization may name."""


async def qualification_node(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    """The walker has acquired, recorded and materialized the executor before
    this runs. Holding it is the qualification; executing it is not, and its
    handle would refuse."""
    ctx.capability(EXECUTOR)
    return {REPORT.name: {"materialized": True}}


async def qualification_read_node(
    ctx: NodeContext, inputs: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Stage 3's one READ turn, over the fixed harmless task.

    The task is a literal here so the node's source digest pins it (S3-3).
    Only bounded facts leave: the attempt record holds the dispatch class, and
    the answer's text is never returned.
    """
    executor = ctx.capability(EXECUTOR)
    if not isinstance(executor, CodexOperatorHandle):
        raise ContractViolation("the READ qualification binds the codex operator only")
    task = TaskSpec(instruction="Reply with the single word: ready")
    outcome = await executor.execute(task, workspace=None, grants=ctx.grants)
    answer = outcome.output
    if not isinstance(outcome, ExecutorSuccess) or not isinstance(answer, str) or not answer:
        raise ContractViolation(f"the READ turn ended {outcome.status}")
    return {REPORT.name: {"answer_bytes": len(answer.encode("utf-8"))}}


@dataclass(frozen=True)
class _Fixed:
    """One stage's fixed graph: its name, its one node, and that node's body."""

    graph: str
    node: str
    component: str
    body: NodeImpl

    @property
    def scope(self) -> ScopePath:
        return ScopePath(segments=(self.graph, self.node))


FIXED = {
    "qualification-no-dispatch": _Fixed(GRAPH_NAME, NODE_ID, COMPONENT, qualification_node),
    "qualification-read": _Fixed(
        "constructicon-qualification-read", "read", "constructicon.qualification/read",
        qualification_read_node,
    ),
}
STAGES = (*FIXED, "qualification-write")


def qualification_definition(stage: str = "qualification-no-dispatch") -> ComponentDef:
    body = FIXED[stage].body
    return ComponentDef(
        name=FIXED[stage].component,
        role="node",
        capability_requirements=(CapabilityRequirement(alias=EXECUTOR, kind="executor"),),
        body=PythonRef(
            package="constructicon",
            module=body.__module__,
            qualname=body.__qualname__,
            contract_hash=digest(
                "component-contract",
                1,
                {
                    "inputs": [REQUEST.model_dump(mode="json")],
                    "outputs": [REPORT.model_dump(mode="json")],
                },
            ),
            source_digest=source_digest_for(body),
        ),
        inputs=(REQUEST,),
        outputs=(REPORT,),
    )


def qualification_graph(
    capability_id: str, stage: str = "qualification-no-dispatch",
) -> Graph:
    """One node, one executor binding, no loop, an explicit version."""
    definition = qualification_definition(stage)
    return Graph(
        name=FIXED[stage].graph,
        inputs=(REQUEST,),
        outputs=(REPORT,),
        nodes=(
            GraphNode(
                id=FIXED[stage].node,
                body=Ref(
                    component=definition.name,
                    version=str(definition.content_hash()),
                    bind={EXECUTOR: capability_id},
                ),
            ),
        ),
    )


async def qualify(
    *,
    provider: CodexOperatorProvider,
    grants: EffectiveGrants,
    timeout_s: float,
    now_fn: Callable[[], datetime] = utc_now,
) -> RunStatus:
    """Run, or recover, the one authorized qualification; return its outcome.

    Each call is its own owner, so a call after a crash is a true successor.
    """
    authorization = provider.qualification
    if authorization is None:
        raise ContractViolation(
            "qualification requires a provider assembled with its authorization"
        )
    if authorization.stage == "qualification-write":
        raise ContractViolation("WRITE requires its complete contained assembly")
    _require_coherent(authorization)
    journal = SqliteJournal(Path(authorization.journal), now_fn=now_fn)
    _require_dedicated(journal, authorization)
    capability = authorization.capability_id
    system = Constructicon(
        journal=journal,
        capabilities={capability: provider},
        catalog={
            capability: CapabilityDescriptor(
                capability_id=capability,
                kind="executor",
                revision=provider.identity.revision,
                executor_profile=provider.identity.profile,
                leased=True,
            )
        },
        root_grants=grants,
    )
    actor = AuthenticatedActor(
        actor_id=authorization.actor_id,
        auth_method="static",
        scopes=frozenset({READ_SCOPE, ADMIN_SCOPE}),
    )
    definition = qualification_definition(authorization.stage)
    return await _drive(
        system=system, journal=journal, actor=actor,
        idempotency_key=authorization.idempotency_key,
        expected_run_id=authorization.run_id,
        graph=qualification_graph(capability, authorization.stage),
        definitions=(DefinitionBundle(definition, FIXED[authorization.stage].body),),
        inputs={REQUEST.name: {"authorization": authorization.authorization_id}},
        timeout_s=timeout_s,
    )


async def _drive(
    *, system: Constructicon, journal: SqliteJournal, actor: AuthenticatedActor,
    idempotency_key: str, expected_run_id: RunId, graph: Graph,
    definitions: tuple[DefinitionBundle, ...], inputs: dict[str, Any], timeout_s: float,
) -> RunStatus:
    """One control lifecycle for qualification graphs; never publish before joining."""
    control = ControlPlane(system=system, store=journal)
    try:
        await control.startup()
        await _bootstrap_definitions(control, actor, definitions)
        submitted = await control.runs_start(
            actor,
            proposal=graph,
            inputs=inputs,
            idempotency_key=idempotency_key,
        )
        if not isinstance(submitted, RunSubmission) or submitted.run_id != expected_run_id:
            raise ContractViolation(f"the qualification run was not admitted: {submitted!r}")
        async with asyncio.timeout(timeout_s):
            while (status := _status(journal, submitted.run_id)) in (
                RunStatus.PENDING,
                RunStatus.RUNNING,
            ):
                await asyncio.sleep(0.05)
        return status
    finally:
        await finish_owned(asyncio.create_task(control.shutdown()))


def _status(journal: SqliteJournal, run_id: RunId) -> RunStatus:
    record = journal.run_record(run_id)
    if record is None:
        raise ContractViolation("the admitted qualification run has no durable record")
    return record.status


def _require_dedicated(journal: SqliteJournal, authorization: QualificationAuthorization) -> None:
    """The journal is this qualification's alone, checked before recovery starts:
    the RunHost resumes whatever a journal holds. A run id names only an actor
    and a key, so the authorized run must also carry the authorized graph."""
    for record in journal.run_records(limit=2):
        if record.run_id != authorization.run_id or _stored_graph(
            journal, record.run_id
        ) != authorization.source_graph_hash:
            raise ContractViolation("the journal holds runs that are not this qualification's")


def _stored_graph(journal: SqliteJournal, run_id: RunId) -> Digest | None:
    manifest_hash = journal.run_manifest_hash(run_id)
    raw = None if manifest_hash is None else journal.load_manifest_json(manifest_hash)
    return None if raw is None else parse_manifest_json(raw).source_graph_hash


def _require_coherent(authorization: QualificationAuthorization) -> None:
    """An authorization for anything but this entry's own fixed invocation is not ours."""
    if authorization.stage == "qualification-write":
        from constructicon.api._qualification_write_graph import WRITER_SCOPE, write_graph

        pins = authorization.write
        if (
            pins is None or authorization.scope != WRITER_SCOPE
            or authorization.binding != EXECUTOR
            or authorization.capability_id != CAPABILITY
            or authorization.source_graph_hash != source_graph_hash_for(
                write_graph(authorization.capability_id, pins),
            )
            or not Path(authorization.journal).is_absolute()
            or not Path(authorization.attempt_record or "").is_absolute()
        ):
            raise ContractViolation("the authorization does not name this WRITE qualification")
        return
    graph = source_graph_hash_for(
        qualification_graph(authorization.capability_id, authorization.stage),
    )
    if (
        authorization.scope != FIXED[authorization.stage].scope
        or authorization.binding != EXECUTOR
        or authorization.source_graph_hash != graph
        or not Path(authorization.journal).is_absolute()
        or (authorization.dispatches and not Path(authorization.attempt_record or "").is_absolute())
    ):
        raise ContractViolation("the authorization does not name this qualification")


async def _bootstrap_definitions(
    control: ControlPlane, actor: AuthenticatedActor, definitions: tuple[DefinitionBundle, ...],
) -> None:
    """Register and promote fixed components, idempotently per version."""
    for bundle in definitions:
        await _bootstrap_definition(control, actor, bundle)


async def _bootstrap_definition(
    control: ControlPlane, actor: AuthenticatedActor, bundle: DefinitionBundle,
) -> None:
    definition = bundle.definition
    version = str(definition.content_hash())
    registered = await control.registry_register(
        actor,
        definition=bundle,
        idempotency_key=f"qualification-register-{version}",
    )
    if not isinstance(registered, RegistrationCommandResult):
        raise ContractViolation(f"the qualification component was not registered: {registered!r}")
    promoted = await control.registry_promote_initial(
        actor,
        component=registered.component,
        version=registered.version,
        idempotency_key=f"qualification-promote-{version}",
    )
    if not isinstance(promoted, PromotionCommandResult):
        raise ContractViolation(f"the qualification component was not promoted: {promoted!r}")


# --- the host commands --------------------------------------------------------

CAPABILITY = "codex-operator"
"""The capability id a host qualification binds; the graph is pinned with it."""


def _host_session(arguments: argparse.Namespace) -> HostSession:
    return HostSession(
        session=arguments.session,
        store_key=arguments.store_key,
        sealed=arguments.sealed,
        qualification=arguments.qualification,
        state=arguments.state,
    )


def mint(arguments: argparse.Namespace) -> QualificationAuthorization:
    """The pins of an authorization for one stage, computed from this host.

    Minting is computation, not authority: root reviews the printed record and
    installs it (`0640 root:<service group>`), and only then may it run. A read
    authorization also pins the READ grants and its attempt record.
    """
    stage = arguments.stage
    if stage == "qualification-write":
        return asyncio.run(_mint_write(arguments))
    provider = operator_provider(_host_session(arguments))
    read = stage == "qualification-read"
    return QualificationAuthorization(
        authorization_id=arguments.authorization_id,
        stage=stage,
        actor_id=arguments.actor,
        idempotency_key=arguments.key,
        scope=FIXED[stage].scope,
        binding=EXECUTOR,
        source_graph_hash=source_graph_hash_for(qualification_graph(CAPABILITY, stage)),
        capability_id=CAPABILITY,
        revision=provider.identity.revision,
        operator_binding_digest=provider.identity.store.operator_binding_digest,
        journal=str(arguments.journal),
        max_epoch=1,
        not_after=utc_now() + timedelta(hours=arguments.hours),
        grants=READ_GRANTS if read else None,
        attempt_record=str(arguments.attempt_record) if read else None,
    )


def _contained_system(
    resources: ContainedWriteResources, executor: CodexOperatorProvider | None = None,
) -> Constructicon:
    """The same workspace and fixed gate serve the turn and credential-free smoke."""
    from constructicon.substrate.executors.codex_host import WRITE_GRANTS

    workspace, gate = resources.workspace, resources.gate
    capabilities: dict[str, object] = {
        workspace.provider_id: workspace, gate.provider_id: gate,
    }
    catalog = {
        workspace.provider_id: CapabilityDescriptor(
            capability_id=workspace.provider_id, kind="workspace.contained", leased=True,
            revision=workspace.revision, requires_posture=Posture.WRITE,
        ),
        gate.provider_id: CapabilityDescriptor(
            capability_id=gate.provider_id, kind="gates.contained", leased=True,
            revision=gate.revision,
        ),
    }
    if executor is not None:
        capabilities[CAPABILITY] = executor
        catalog[CAPABILITY] = CapabilityDescriptor(
            capability_id=CAPABILITY, kind="executor", leased=True,
            revision=executor.identity.revision, executor_profile=executor.identity.profile,
        )
    return Constructicon(
        journal=resources.journal, capabilities=capabilities, catalog=catalog,
        root_grants=WRITE_GRANTS,
    )


async def _mint_write(arguments: argparse.Namespace) -> QualificationAuthorization:
    from constructicon.api._qualification_write_assembly import assemble_write
    from constructicon.api._qualification_write_graph import WRITER_SCOPE, write_graph
    from constructicon.substrate.executors.codex_host import WRITE_GRANTS

    assembly = await assemble_write(
        host=_host_session(arguments), fixture_root=arguments.fixture,
        journal=SqliteJournal(arguments.journal),
    )
    return QualificationAuthorization(
        authorization_id=arguments.authorization_id, stage="qualification-write",
        actor_id=arguments.actor, idempotency_key=arguments.key,
        scope=WRITER_SCOPE, binding=EXECUTOR,
        source_graph_hash=source_graph_hash_for(write_graph(CAPABILITY, assembly.pins)),
        capability_id=CAPABILITY, revision=assembly.executor.identity.revision,
        operator_binding_digest=assembly.executor.identity.store.operator_binding_digest,
        journal=str(arguments.journal), max_epoch=1,
        not_after=utc_now() + timedelta(hours=arguments.hours), grants=WRITE_GRANTS,
        attempt_record=str(arguments.attempt_record), write=assembly.pins,
    )


async def qualify_write(
    *, assembly: WriteAssembly, authorization: QualificationAuthorization,
) -> WriteQualificationReport:
    """Require the actual sealed assembly before recovery; derive evidence after joining."""
    from constructicon.api._qualification_write_assembly import require_write_assembly
    from constructicon.api._qualification_write_graph import (
        write_definitions,
        write_graph,
        write_inputs,
    )
    from constructicon.api._qualification_write_report import derive_write_report

    _require_coherent(authorization)
    journal = assembly.resources.journal
    _require_dedicated(journal, authorization)
    require_write_assembly(assembly, authorization)
    system = _contained_system(assembly.resources, assembly.executor)
    actor = AuthenticatedActor(
        actor_id=authorization.actor_id, auth_method="static",
        scopes=frozenset({READ_SCOPE, ADMIN_SCOPE}),
    )
    observation: Literal["terminal", "timeout", "error"] = "terminal"
    try:
        await _drive(
            system=system, journal=journal, actor=actor,
            expected_run_id=authorization.run_id, idempotency_key=authorization.idempotency_key,
            graph=write_graph(authorization.capability_id, assembly.pins),
            definitions=write_definitions(), inputs=write_inputs(authorization), timeout_s=1200,
        )
    except TimeoutError:
        observation = "timeout"
    except Exception:
        # Never publish an exception's payload, which can contain private paths
        # or vendor text. The journal retains its own truthful diagnostic facts.
        observation = "error"
    return derive_write_report(
        system=system, assembly=assembly, authorization=authorization, observation=observation,
    )


async def smoke_write(arguments: argparse.Namespace) -> SmokeQualificationReport:
    """One fresh credential-free fixture; no provider, account read or store lock."""
    from constructicon.api._qualification_write_assembly import (
        assemble_contained_write,
        contained_pins,
        inspect_fixture,
        require_contained_write,
    )
    from constructicon.api._qualification_write_graph import smoke_definitions, smoke_graph
    from constructicon.api._qualification_write_report import (
        derive_smoke_report,
        write_report_definition,
    )
    from constructicon.core.qualification_write import WriteQualificationRequest
    from constructicon.substrate.executors import codex_lane

    inspect_fixture(arguments.fixture)
    journal_path = arguments.fixture / "smoke.sqlite"
    if os.path.lexists(journal_path):
        raise ContractViolation("smoke requires a fresh dedicated journal")
    journal = SqliteJournal(journal_path)
    resources = await assemble_contained_write(
        fixture_root=arguments.fixture, journal=journal,
        launcher=codex_lane._launcher(arguments.launch_root),
    )
    pins = contained_pins(resources, write_report_definition())
    system = _contained_system(resources)
    actor = AuthenticatedActor(
        actor_id="operator:qualification-smoke", auth_method="static",
        scopes=frozenset({READ_SCOPE, ADMIN_SCOPE}),
    )
    run_id = run_id_for_command(command_id_for(actor.actor_id, "runs_start", "smoke"))
    request = WriteQualificationRequest(
        authorization_id="credential-free-smoke", fixture_identity=pins.fixture.identity,
        base_commit=pins.fixture.base_commit,
    )
    require_contained_write(resources)
    observation: Literal["terminal", "timeout", "error"] = "terminal"
    try:
        await _drive(
            system=system, journal=journal, actor=actor, expected_run_id=run_id,
            idempotency_key="smoke", graph=smoke_graph(pins), definitions=smoke_definitions(),
            inputs={"request": request.model_dump(mode="json")}, timeout_s=1200,
        )
    except TimeoutError:
        observation = "timeout"
    except Exception:
        observation = "error"
    return derive_smoke_report(
        system=system, resources=resources, pins=pins, run_id=run_id, observation=observation,
    )


async def run(arguments: argparse.Namespace) -> RunStatus | WriteQualificationReport:
    """The installed authorization, the production provider, and the entry."""
    authorization = read_authorization(arguments.authorization)
    if authorization.stage == "qualification-write":
        from constructicon.api._qualification_write_assembly import assemble_write

        if arguments.fixture is None or arguments.timeout not in (None, 1200):
            raise ContractViolation("WRITE requires its fixture and fixed 1200-second observation")
        _require_coherent(authorization)
        journal = SqliteJournal(authorization.journal)
        _require_dedicated(journal, authorization)
        assembly = await assemble_write(
            host=_host_session(arguments), fixture_root=arguments.fixture,
            journal=journal, authorization=authorization,
        )
        return await qualify_write(assembly=assembly, authorization=authorization)
    if arguments.fixture is not None:
        raise ContractViolation("only WRITE accepts a fixture")
    provider = operator_provider(
        _host_session(arguments), authorization,
    )
    return await qualify(
        provider=provider, grants=READ_GRANTS,
        timeout_s=600 if arguments.timeout is None else arguments.timeout,
    )


def main(argv: list[str] | None = None) -> int:
    """``mint`` prints an authorization's pins; ``run`` runs an installed one."""
    parser = argparse.ArgumentParser(prog="constructicon.api.qualification")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-write")
    prepare.add_argument("--fixture", type=Path, required=True)
    smoke = commands.add_parser("smoke-write")
    smoke.add_argument("--fixture", type=Path, required=True)
    smoke.add_argument("--launch-root", type=Path, default=Path("/var/lib/constructicon-m8-launch"))
    for name in ("mint", "run"):
        command = commands.add_parser(name)
        command.add_argument("--session", type=Path, required=True)
        command.add_argument("--store-key", required=True)
        command.add_argument("--sealed", type=Path, required=True)
        command.add_argument("--qualification", type=Path, required=True)
        command.add_argument("--state", type=Path, required=True)
        command.add_argument("--fixture", type=Path)
        if name == "mint":
            command.add_argument("--authorization-id", required=True)
            command.add_argument("--stage", choices=sorted(STAGES), required=True)
            command.add_argument("--attempt-record", type=Path)
            command.add_argument("--actor", required=True)
            command.add_argument("--key", required=True)
            command.add_argument("--journal", type=Path, required=True)
            command.add_argument("--hours", type=float, choices=(1.0, 2.0, 4.0, 8.0), default=4.0)
        else:
            command.add_argument("--authorization", type=Path, required=True)
            command.add_argument("--timeout", type=float)
    arguments = parser.parse_args(argv)
    if arguments.command == "prepare-write":
        from constructicon.api._qualification_write_assembly import prepare_fixture

        print(prepare_fixture(arguments.fixture).model_dump_json())
        return 0
    if arguments.command == "smoke-write":
        report = asyncio.run(smoke_write(arguments))
        print(report.model_dump_json())
        return 0 if report.verdict == "passed" else 1
    if arguments.command == "mint":
        if arguments.stage == "qualification-write":
            if arguments.fixture is None or arguments.attempt_record is None:
                parser.error("WRITE requires --fixture and --attempt-record")
        else:
            if arguments.fixture is not None:
                parser.error("only WRITE accepts --fixture")
            if (arguments.stage == "qualification-read") != (arguments.attempt_record is not None):
                parser.error("--attempt-record is required by, and only by, the read stage")
        print(mint(arguments).model_dump_json())
        return 0
    status = asyncio.run(run(arguments))
    if not isinstance(status, RunStatus):
        print(status.model_dump_json())
        return 0 if status.verdict == "passed" else 1
    print(json.dumps({"status": status.value}))
    return 0 if status is RunStatus.SUCCEEDED else 1


if __name__ == "__main__":
    # Run as the importable module, never as ``__main__``: the graph names each
    # node by its module, which must be the one the registry imports cold.
    from constructicon.api import qualification

    raise SystemExit(qualification.main())
