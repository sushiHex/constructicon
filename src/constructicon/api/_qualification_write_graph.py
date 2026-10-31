"""The fixed two-node WRITE graph, and its vendor-free contained smoke twin."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from constructicon.core.address import ScopePath
from constructicon.core.component import CapabilityRequirement, ComponentDef, PythonRef
from constructicon.core.envelope import GitRef
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorSuccess, TaskSpec
from constructicon.core.gates import MergeEvaluation
from constructicon.core.grants import EffectiveGrants, GrantRequest, Posture
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.identity import digest
from constructicon.core.ports import Port
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.qualification_write import WriteQualificationPins, WriteQualificationRequest
from constructicon.runtime.context import NodeContext, NodeImpl
from constructicon.runtime.registry import source_digest_for
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.codex import WORKER_ARGUMENTS, CodexOperatorHandle
from constructicon.substrate.executors.codex_host import WRITE_GRANTS
from constructicon.substrate.gates.contained import BoundContainedGate
from constructicon.substrate.git.capture import ContainedWriteWorkspace

GRAPH_NAME = "constructicon-qualification-write"
WRITER_ID, CHECKER_ID = "writer", "checker"
EXECUTOR, WORKSPACE, GATE = "executor", "workspace", "gate"
WRITER_SCOPE = ScopePath(segments=(GRAPH_NAME, WRITER_ID))
CHECKER_SCOPE = ScopePath(segments=(GRAPH_NAME, CHECKER_ID))
SMOKE_WRITER_SCOPE = ScopePath(segments=(GRAPH_NAME + "-smoke", WRITER_ID))
SMOKE_CHECKER_SCOPE = ScopePath(segments=(GRAPH_NAME + "-smoke", CHECKER_ID))
WRITE_OBSERVATION_SECONDS = 1200
OBSERVATION_TIMEOUT_S = WRITE_OBSERVATION_SECONDS
CHECKER_GRANTS = EffectiveGrants(
    posture=Posture.READ, model_selection=WRITE_GRANTS.model_selection, effort=WRITE_GRANTS.effort,
    allowed_tools=(), env_allowlist=(), network="none", timeout_s=30,
)


def _port(name: str, model: type[BaseModel]) -> Port:
    schema = model.model_json_schema()
    return Port(name=name, type_id=f"constructicon.qualification/{model.__name__}",
                schema_hash=str(digest("json-schema", 1, schema)), json_schema=schema)


REQUEST = _port("request", WriteQualificationRequest)
CANDIDATE = _port("candidate", GitRef)
EVALUATION = _port("evaluation", MergeEvaluation)


def _request(inputs: Mapping[str, Any]) -> WriteQualificationRequest:
    return WriteQualificationRequest.model_validate(inputs[REQUEST.name])


async def _writer_workspace(
    ctx: NodeContext, request: WriteQualificationRequest,
) -> ContainedWriteWorkspace:
    from constructicon.api._qualification_write_assembly import inspect_fixture

    workspace = ctx.capability(WORKSPACE)
    if not isinstance(workspace, ContainedWriteWorkspace):
        raise ContractViolation("the WRITE writer requires the contained acquired workspace")
    if workspace.base != request.base_commit:
        raise ContractViolation("the acquired WRITE workspace base drifted")
    actual = await finish_owned(asyncio.create_task(asyncio.to_thread(
        workspace.provider.authority.resolve_ref, workspace.provider.target_ref,
    )))
    if actual != request.base_commit or workspace.base != request.base_commit:
        raise ContractViolation("the WRITE target changed before dispatch")
    fixture = inspect_fixture(Path(workspace.provider.authority.repository_id).parent)
    if fixture.identity != request.fixture_identity or fixture.base_commit != request.base_commit:
        raise ContractViolation("the WRITE request names another actual fixture")
    return workspace


async def write_writer(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    executor = ctx.capability(EXECUTOR)
    if not isinstance(executor, CodexOperatorHandle):
        raise ContractViolation("the WRITE qualification binds the codex operator only")
    request = _request(inputs)
    workspace = await _writer_workspace(ctx, request)
    task = TaskSpec(instruction=(
        "Use contained_python to create n5-write.txt containing exactly ready "
        "followed by a newline. Change no other files."
    ))
    outcome = await executor.execute(task, workspace=workspace, grants=ctx.grants)
    if not isinstance(outcome, ExecutorSuccess):
        raise ContractViolation(f"the WRITE turn ended {outcome.status}")
    return await capture_changed_candidate(workspace, request)


async def capture_changed_candidate(
    workspace: ContainedWriteWorkspace, request: WriteQualificationRequest,
) -> Mapping[str, Any]:
    """Both subscription writers checkpoint only an actual changed capture."""
    await workspace.commit_all("constructicon N5 WRITE candidate")
    candidate = workspace.git_ref()
    if candidate.commit == request.base_commit:
        raise ContractViolation("the WRITE qualification captured no change")
    return {CANDIDATE.name: candidate.model_dump(mode="json")}


async def smoke_writer(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    workspace = await _writer_workspace(ctx, _request(inputs))
    async with workspace.use() as guard:
        result = await workspace.provider.launcher.run(
            WORKER_ARGUMENTS, workspace=Path(workspace.path), posture=Posture.WRITE,
            guard_fds=(guard,), timeout_s=300,
            stdin=b"from pathlib import Path\nPath('n5-write.txt').write_bytes(b'ready\\n')\n",
        )
    if (
        result.returncode != 0 or result.payload_returncode != 0
        or result.timed_out or result.bound_exceeded
    ):
        raise ContractViolation("the contained smoke writer did not positively complete")
    await workspace.commit_all("constructicon N5 WRITE candidate")
    return {CANDIDATE.name: workspace.git_ref().model_dump(mode="json")}


async def write_checker(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    request = _request(inputs)
    candidate = GitRef.model_validate(inputs[CANDIDATE.name])
    gate = ctx.capability(GATE)
    if not isinstance(gate, BoundContainedGate) or (
        candidate.repository != gate.provider.authority.repository_id
        or candidate.diff_against != request.base_commit
    ):
        raise ContractViolation("the WRITE checker requires the captured fixed-fixture candidate")
    evaluation = await gate.verify(candidate.commit)
    subject = evaluation.subject
    if not evaluation.ok or subject is None or (
        subject.candidate != candidate.commit or subject.expected_base != request.base_commit
        or subject.repository != candidate.repository or subject.target_ref != gate.target_ref
    ):
        raise ContractViolation("the WRITE candidate failed its exact contained gate")
    tree = await finish_owned(asyncio.create_task(asyncio.to_thread(
        gate.provider.authority._run, "rev-parse", f"{candidate.commit}^{{tree}}",
    )))
    if subject.tested_tree != tree.stdout.strip():
        raise ContractViolation("the WRITE gate tested another candidate tree")
    actual_base = await finish_owned(asyncio.create_task(asyncio.to_thread(
        gate.provider.authority.resolve_ref, gate.target_ref,
    )))
    if actual_base != request.base_commit:
        raise ContractViolation("the WRITE target drifted while checking")
    return {EVALUATION.name: evaluation.model_dump(mode="json")}


def _definition(
    name: str, body: NodeImpl, *, writer: bool, smoke: bool = False,
) -> DefinitionBundle:
    inputs = (REQUEST,) if writer else (REQUEST, CANDIDATE)
    outputs = (CANDIDATE,) if writer else (EVALUATION,)
    requirements = ((CapabilityRequirement(alias=WORKSPACE, kind="workspace.contained"),)
                    if writer and smoke else
                    (CapabilityRequirement(alias=EXECUTOR, kind="executor"),
                     CapabilityRequirement(alias=WORKSPACE, kind="workspace.contained"))
                    if writer else (CapabilityRequirement(alias=GATE, kind="gates.contained"),))
    definition = ComponentDef(
        name=name, role="node", inputs=inputs, outputs=outputs,
        capability_requirements=requirements,
        body=PythonRef(package="constructicon", module=body.__module__, qualname=body.__qualname__,
            contract_hash=digest("component-contract", 1, {
                "inputs": [p.model_dump(mode="json") for p in inputs],
                "outputs": [p.model_dump(mode="json") for p in outputs],
            }), source_digest=source_digest_for(body)),
    )
    return DefinitionBundle(definition, body)


def write_definitions() -> tuple[DefinitionBundle, DefinitionBundle]:
    return (_definition("constructicon.qualification/write-writer", write_writer, writer=True),
            _definition("constructicon.qualification/write-checker", write_checker, writer=False))


def smoke_definitions() -> tuple[DefinitionBundle, DefinitionBundle]:
    return (
        _definition(
            "constructicon.qualification/write-smoke", smoke_writer, writer=True, smoke=True,
        ),
        write_definitions()[1],
    )


def _graph(capability: str | None, pins: WriteQualificationPins) -> Graph:
    definitions = write_definitions() if capability is not None else smoke_definitions()
    grants = GrantRequest(
        posture=Posture.WRITE, model=WRITE_GRANTS.model_selection.model, effort=WRITE_GRANTS.effort,
        allowed_tools=WRITE_GRANTS.allowed_tools, env_allowlist=(), network="allow", timeout_s=300,
    )
    bind = {WORKSPACE: pins.workspace.capability_id}
    if capability is not None:
        bind[EXECUTOR] = capability
    return Graph(
        name=GRAPH_NAME if capability is not None else GRAPH_NAME + "-smoke",
        inputs=(REQUEST,), outputs=(CANDIDATE, EVALUATION),
        nodes=(
            GraphNode(id=WRITER_ID, body=Ref(component=definitions[0].definition.name,
                version=str(definitions[0].definition.content_hash()), bind=bind, grants=grants)),
            GraphNode(id=CHECKER_ID, body=Ref(component=definitions[1].definition.name,
                version=str(definitions[1].definition.content_hash()),
                bind={GATE: pins.gate.capability_id},
                grants=GrantRequest(posture=Posture.READ,
                                    model=CHECKER_GRANTS.model_selection.model,
                                    effort=CHECKER_GRANTS.effort,
                                    allowed_tools=(), env_allowlist=(),
                                    network="none", timeout_s=30))),
        ),
        connections=(Connection(src=WRITER_ID, dst=CHECKER_ID,
            map={"candidate": "writer.candidate", "request": "$input.request"}),),
    )


def write_graph(executor_capability_id: str, pins: WriteQualificationPins) -> Graph:
    return _graph(executor_capability_id, pins)


def smoke_graph(pins: WriteQualificationPins) -> Graph:
    return _graph(None, pins)


def write_inputs(auth: QualificationAuthorization) -> dict[str, Any]:
    if auth.write is None:
        raise ContractViolation("WRITE inputs require the fixture pin")
    return {REQUEST.name: WriteQualificationRequest(
        authorization_id=auth.authorization_id, fixture_identity=auth.write.fixture.identity,
        base_commit=auth.write.fixture.base_commit,
    ).model_dump(mode="json")}


# Helper and fixed check changes must invalidate retained component versions too.
for _body in (write_writer, smoke_writer, write_checker):
    _body.__constructicon_adapter_revision__ = (  # type: ignore[attr-defined]
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    )
