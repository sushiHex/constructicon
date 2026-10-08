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

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
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
from constructicon.core.grants import EffectiveGrants
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import digest
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.ports import Port
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor, source_digest_for
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.executors.codex import CodexOperatorProvider
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


def qualification_definition() -> ComponentDef:
    return ComponentDef(
        name=COMPONENT,
        role="node",
        capability_requirements=(CapabilityRequirement(alias=EXECUTOR, kind="executor"),),
        body=PythonRef(
            package="constructicon",
            module=qualification_node.__module__,
            qualname=qualification_node.__qualname__,
            contract_hash=digest(
                "component-contract",
                1,
                {
                    "inputs": [REQUEST.model_dump(mode="json")],
                    "outputs": [REPORT.model_dump(mode="json")],
                },
            ),
            source_digest=source_digest_for(qualification_node),
        ),
        inputs=(REQUEST,),
        outputs=(REPORT,),
    )


def qualification_graph(capability_id: str) -> Graph:
    """One node, one executor binding, no loop, an explicit version."""
    definition = qualification_definition()
    return Graph(
        name=GRAPH_NAME,
        inputs=(REQUEST,),
        outputs=(REPORT,),
        nodes=(
            GraphNode(
                id=NODE_ID,
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
    await control.startup()
    try:
        await _bootstrap(control, actor)
        submitted = await control.runs_start(
            actor,
            proposal=qualification_graph(capability),
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


def _require_coherent(authorization: QualificationAuthorization) -> None:
    """An authorization for anything but this entry's own fixed invocation is not ours."""
    graph = source_graph_hash_for(qualification_graph(authorization.capability_id))
    if (
        authorization.scope != SCOPE
        or authorization.binding != EXECUTOR
        or authorization.source_graph_hash != graph
        or not Path(authorization.journal).is_absolute()
    ):
        raise ContractViolation("the authorization does not name this qualification")


async def _bootstrap(control: ControlPlane, actor: AuthenticatedActor) -> None:
    """Register and promote the fixed component, idempotently per version."""
    definition = qualification_definition()
    version = str(definition.content_hash())
    registered = await control.registry_register(
        actor,
        definition=DefinitionBundle(definition, qualification_node),
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
