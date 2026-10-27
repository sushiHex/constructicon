"""One owner-authorized Claude READ through the ordinary admitted graph lifecycle.

No API-key fallback, login, activation, recovery loop or general provider switch
lives here. Minting computes pins; only an installed authorization permits run.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from constructicon.api import _claude_read_fixture as fixture
from constructicon.api.qualification import _drive, _require_dedicated
from constructicon.api.system import Constructicon
from constructicon.core.address import ScopePath
from constructicon.core.component import CapabilityRequirement, ComponentDef, PythonRef
from constructicon.core.control import ADMIN_SCOPE, READ_SCOPE, AuthenticatedActor
from constructicon.core.envelope import utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorFailure, ExecutorSuccess, TaskSpec
from constructicon.core.grants import EffectiveGrants, GrantRequest, ModelSelection, Posture
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import canonical_json, digest
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.ports import Port
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor, source_digest_for
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.executors.claude_host import (
    READ_SECONDS,
    ClaudeHostSession,
    operator_provider,
)
from constructicon.substrate.executors.claude_lane import read_configuration
from constructicon.substrate.executors.claude_provider import (
    READ_CATALOG,
    ClaudeOperatorHandle,
    ClaudeOperatorProvider,
)
from constructicon.substrate.executors.claude_read import known_refusal_detail
from constructicon.substrate.executors.claude_read_worker import READ_WORKER_LIMITS
from constructicon.substrate.executors.linux import LinuxLauncher, LinuxLaunchProfile
from constructicon.substrate.executors.qualification import read_authorization
from constructicon.substrate.git.contained import ContainedWorkspace
from constructicon.substrate.journal.sqlite import SqliteJournal

CAPABILITY = "claude-operator"
WORKSPACE_CAPABILITY = "claude-read-workspace"
EXECUTOR, WORKSPACE = "executor", "workspace"
GRAPH, NODE = "constructicon-claude-qualification-read", "read"
SCOPE = ScopePath(segments=(GRAPH, NODE))
REQUEST = Port(name="request", type_id="constructicon.qualification/Request", schema_hash="v1")
REPORT = Port(name="report", type_id="constructicon.qualification/Report", schema_hash="v1")


async def read_node(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    executor, workspace = ctx.capability(EXECUTOR), ctx.capability(WORKSPACE)
    if (not isinstance(executor, ClaudeOperatorHandle)
            or not isinstance(workspace, ContainedWorkspace) or workspace.base != fixture.BASE):
        raise ContractViolation("Claude qualification requires its exact executor and READ fixture")
    task = TaskSpec(instruction=(
        "Use the read_file tool exactly once to read ready.txt. "
        "Reply with the single word found in that file, and nothing else."
    ))
    result = await executor.execute(task, workspace=workspace, grants=ctx.grants)
    if (not isinstance(result, ExecutorSuccess) or type(result.raw_reply) is not str
            or result.raw_reply.strip() != "ready"):
        detail = (known_refusal_detail(result.error.detail)
                  if isinstance(result, ExecutorFailure) and result.error.kind == "exit"
                  else None)
        if detail is not None:
            raise ContractViolation(detail)
        raise ContractViolation("Claude qualification did not complete its fixed READ")
    # The provider requires one completed callback and its joined process before
    # success. The fixed fixture contains no private repository data.
    return {REPORT.name: {"read_completed": True, "answer_bytes": len(result.raw_reply.encode())}}


def definition() -> ComponentDef:
    return ComponentDef(
        name="constructicon.qualification/claude-read", role="node",
        inputs=(REQUEST,), outputs=(REPORT,),
        capability_requirements=(
            CapabilityRequirement(alias=EXECUTOR, kind="executor"),
            CapabilityRequirement(alias=WORKSPACE, kind="workspace.contained"),
        ),
        body=PythonRef(
            package="constructicon", module=__name__, qualname="read_node",
            contract_hash=digest("component-contract", 1, {
                "inputs": [REQUEST.model_dump(mode="json")],
                "outputs": [REPORT.model_dump(mode="json")],
            }), source_digest=source_digest_for(read_node),
        ),
    )


def fixed_grants(provider: ClaudeOperatorProvider) -> EffectiveGrants:
    vendor = provider.launcher.claude
    if vendor is None:
        raise ContractViolation("Claude qualification requires its native recipe")
    return EffectiveGrants(
        posture=Posture.READ, model_selection=ModelSelection(kind="explicit", model=vendor.model),
        effort=vendor.effort, allowed_tools=READ_CATALOG, env_allowlist=(),
        network="allow", timeout_s=READ_SECONDS,
    )


def graph(grants: EffectiveGrants) -> Graph:
    component = definition()
    return Graph(
        name=GRAPH, inputs=(REQUEST,), outputs=(REPORT,),
        nodes=(GraphNode(id=NODE, body=Ref(
            component=component.name, version=str(component.content_hash()),
            bind={EXECUTOR: CAPABILITY, WORKSPACE: WORKSPACE_CAPABILITY},
            grants=GrantRequest(
                posture=Posture.READ, model=grants.model_selection.model, effort=grants.effort,
                allowed_tools=READ_CATALOG, env_allowlist=(), network="allow",
                timeout_s=READ_SECONDS,
            ),
        )),),
    )


def require_coherent(provider: ClaudeOperatorProvider) -> QualificationAuthorization:
    authorization = provider.qualification
    grants = fixed_grants(provider)
    if (authorization is None or authorization.stage != "qualification-read"
            or authorization.scope != SCOPE or authorization.binding != EXECUTOR
            or authorization.capability_id != CAPABILITY
            or authorization.revision != provider.identity.revision
            or authorization.operator_binding_digest
            != provider.identity.store.operator_binding_digest
            or authorization.source_graph_hash != source_graph_hash_for(graph(grants))
            or canonical_json(authorization.grants) != canonical_json(grants)
            or provider.workspace_capability_id != WORKSPACE_CAPABILITY
            or provider.expected_base != fixture.BASE
            or provider.workspace_revision != str(fixture.REVISION)
            or provider.workspace_provider.target_ref != fixture.TARGET
            or not Path(authorization.journal).is_absolute()
            or not Path(authorization.attempt_record or "").is_absolute()):
        raise ContractViolation("authorization does not name this exact Claude READ qualification")
    return authorization


async def qualify(provider: ClaudeOperatorProvider) -> RunStatus:
    authorization = require_coherent(provider)
    grants = fixed_grants(provider)
    journal = SqliteJournal(Path(authorization.journal))
    _require_dedicated(journal, authorization)
    system = Constructicon(
        journal=journal, root_grants=grants,
        capabilities={CAPABILITY: provider, WORKSPACE_CAPABILITY: provider.workspace_provider},
        catalog={
            CAPABILITY: CapabilityDescriptor(
                capability_id=CAPABILITY, kind="executor", revision=provider.identity.revision,
                executor_profile=provider.profile, leased=True,
            ),
            WORKSPACE_CAPABILITY: CapabilityDescriptor(
                capability_id=WORKSPACE_CAPABILITY, kind="workspace.contained",
                revision=provider.workspace_revision, leased=True, requires_posture=Posture.READ,
            ),
        },
    )
    actor = AuthenticatedActor(
        actor_id=authorization.actor_id, auth_method="static",
        scopes=frozenset({READ_SCOPE, ADMIN_SCOPE}),
    )
    return await _drive(
        system=system, journal=journal, actor=actor,
        idempotency_key=authorization.idempotency_key, expected_run_id=authorization.run_id,
        graph=graph(grants), definitions=(DefinitionBundle(definition(), read_node),),
        inputs={REQUEST.name: {"authorization": authorization.authorization_id}},
        timeout_s=READ_SECONDS + 60,
    )


def assemble(options: argparse.Namespace,
             authorization: QualificationAuthorization | None = None) -> ClaudeOperatorProvider:
    configuration = read_configuration(
        options.launch_config, expected_sha256=options.launch_config_sha256,
    )
    worker = LinuxLauncher(
        runtime_root=configuration.launch_root / "runtime",
        expected_runtime=configuration.runtime_digest,
        bubblewrap=configuration.launch_root / "bwrap", policy=configuration.launch_policy,
        expected_policy_sha256=configuration.launch_policy_sha256, limits=READ_WORKER_LIMITS,
        launch_profile=LinuxLaunchProfile.CLAUDE_BOOTSTRAP,
    )
    workspace = fixture.workspace_provider(options.fixture, worker)
    host = ClaudeHostSession(
        configuration=options.launch_config, configuration_sha256=options.launch_config_sha256,
        store_root=options.store_root, store_key=options.store_key, sealed=options.sealed,
        qualification=options.qualification, acquisition_root=options.acquisition_root,
    )
    return operator_provider(
        host, workspace=workspace, workspace_capability_id=WORKSPACE_CAPABILITY,
        workspace_revision=str(fixture.REVISION), expected_base=fixture.BASE,
        worker_launcher=worker,
        authorization=authorization,
    )


def mint(options: argparse.Namespace) -> QualificationAuthorization:
    provider = assemble(options)
    grants = fixed_grants(provider)
    return QualificationAuthorization(
        authorization_id=options.authorization_id, stage="qualification-read",
        actor_id=options.actor, idempotency_key=options.key, scope=SCOPE, binding=EXECUTOR,
        source_graph_hash=source_graph_hash_for(graph(grants)), capability_id=CAPABILITY,
        revision=provider.identity.revision,
        operator_binding_digest=provider.identity.store.operator_binding_digest,
        journal=str(options.journal), max_epoch=1,
        not_after=utc_now() + timedelta(hours=options.hours), grants=grants,
        attempt_record=str(options.attempt_record),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="constructicon.api.claude_qualification", allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--fixture", type=Path, required=True)
    for name in ("mint", "run"):
        command = commands.add_parser(name)
        for path in ("fixture", "launch-config", "store-root", "sealed", "qualification",
                     "acquisition-root"):
            command.add_argument("--" + path, type=Path, required=True)
        command.add_argument("--launch-config-sha256", required=True)
        command.add_argument("--store-key", required=True)
        if name == "mint":
            for text in ("authorization-id", "actor", "key"):
                command.add_argument("--" + text, required=True)
            for path in ("journal", "attempt-record"):
                command.add_argument("--" + path, type=Path, required=True)
            command.add_argument("--hours", type=float, choices=(1.0, 2.0, 4.0), default=1.0)
        else:
            command.add_argument("--authorization", type=Path, required=True)
    options = parser.parse_args(argv)
    if options.command == "prepare":
        print(json.dumps({"fixture_revision": str(fixture.prepare_fixture(options.fixture))}))
        return 0
    if options.command == "mint":
        print(mint(options).model_dump_json())
        return 0
    authorization = read_authorization(options.authorization)
    status = asyncio.run(qualify(assemble(options, authorization)))
    print(json.dumps({"status": status.value}))
    return 0 if status is RunStatus.SUCCEEDED else 1


# The fixed task, assembly law and fixture are part of the retained component.
read_node.__constructicon_adapter_revision__ = digest(  # type: ignore[attr-defined]
    "claude-read-qualification", 1,
    {"entry": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "fixture": fixture.REVISION},
)


if __name__ == "__main__":
    from constructicon.api import claude_qualification

    raise SystemExit(claude_qualification.main())
