"""The qualification acquisition (M8 N5 Stage 1): one authorized run, no dispatch.

A narrow L4 entry that drives the real acquire, record, materialize, close and
reconcile of an executor that stays unavailable. It is not an MCP surface: the
MCP adapter may not import it (pyproject import contracts). It runs exactly the
fixed graph below, under the one authorization its provider was assembled
with; the provider admits nothing else and its handles never dispatch.

Recovery has one driver, the control plane's own RunHost: calling ``qualify``
again after a crash replays the same command and recovers the same run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

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
)
from constructicon.core.envelope import utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorSuccess, TaskSpec
from constructicon.core.grants import EffectiveGrants
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import Digest, digest
from constructicon.core.manifest import parse_manifest_json, source_graph_hash_for
from constructicon.core.ports import Port
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext, NodeImpl
from constructicon.runtime.registry import CapabilityDescriptor, source_digest_for
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.executors.codex import CodexOperatorHandle, CodexOperatorProvider
from constructicon.substrate.executors.codex_host import READ_GRANTS, HostSession, operator_provider
from constructicon.substrate.executors.qualification import read_authorization
from constructicon.substrate.journal.sqlite import SqliteJournal

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
    if not isinstance(outcome, ExecutorSuccess) or not outcome.raw_reply:
        raise ContractViolation(f"the READ turn ended {outcome.status}")
    return {REPORT.name: {"answer_bytes": len(outcome.raw_reply.encode("utf-8"))}}


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
    control = ControlPlane(system=system, store=journal)
    try:
        await control.startup()
        await _bootstrap(control, actor, authorization.stage)
        submitted = await control.runs_start(
            actor,
            proposal=qualification_graph(capability, authorization.stage),
            inputs={REQUEST.name: {"authorization": authorization.authorization_id}},
            idempotency_key=authorization.idempotency_key,
        )
        if not isinstance(submitted, RunSubmission) or submitted.run_id != authorization.run_id:
            raise ContractViolation(f"the qualification run was not admitted: {submitted!r}")
        async with asyncio.timeout(timeout_s):
            while (status := _status(journal, submitted.run_id)) in (
                RunStatus.PENDING,
                RunStatus.RUNNING,
            ):
                await asyncio.sleep(0.05)
        return status
    finally:
        await control.shutdown()


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


async def _bootstrap(control: ControlPlane, actor: AuthenticatedActor, stage: str) -> None:
    """Register and promote the fixed component, idempotently per version."""
    definition = qualification_definition(stage)
    version = str(definition.content_hash())
    registered = await control.registry_register(
        actor,
        definition=DefinitionBundle(definition, FIXED[stage].body),
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


async def run(arguments: argparse.Namespace) -> RunStatus:
    """The installed authorization, the production provider, and the entry."""
    provider = operator_provider(
        _host_session(arguments), read_authorization(arguments.authorization),
    )
    return await qualify(provider=provider, grants=READ_GRANTS, timeout_s=arguments.timeout)


def main(argv: list[str] | None = None) -> int:
    """``mint`` prints an authorization's pins; ``run`` runs an installed one."""
    parser = argparse.ArgumentParser(prog="constructicon.api.qualification")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("mint", "run"):
        command = commands.add_parser(name)
        command.add_argument("--session", type=Path, required=True)
        command.add_argument("--store-key", required=True)
        command.add_argument("--sealed", type=Path, required=True)
        command.add_argument("--qualification", type=Path, required=True)
        command.add_argument("--state", type=Path, required=True)
        if name == "mint":
            command.add_argument("--authorization-id", required=True)
            command.add_argument("--stage", choices=sorted(FIXED), required=True)
            command.add_argument("--attempt-record", type=Path)
            command.add_argument("--actor", required=True)
            command.add_argument("--key", required=True)
            command.add_argument("--journal", type=Path, required=True)
            command.add_argument("--hours", type=float, choices=(1.0, 2.0, 4.0, 8.0), default=4.0)
        else:
            command.add_argument("--authorization", type=Path, required=True)
            command.add_argument("--timeout", type=float, default=600.0)
    arguments = parser.parse_args(argv)
    if arguments.command == "mint":
        if (arguments.stage == "qualification-read") != (arguments.attempt_record is not None):
            parser.error("--attempt-record is required by, and only by, the read stage")
        print(mint(arguments).model_dump_json())
        return 0
    status = asyncio.run(run(arguments))
    print(json.dumps({"status": status.value}))
    return 0 if status is RunStatus.SUCCEEDED else 1


if __name__ == "__main__":
    # Run as the importable module, never as ``__main__``: the graph names each
    # node by its module, which must be the one the registry imports cold.
    from constructicon.api import qualification

    raise SystemExit(qualification.main())
