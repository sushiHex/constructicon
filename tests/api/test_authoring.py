"""M5 typed describe and architect admission surfaces."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from constructicon.api.system import Constructicon
from constructicon.core.admission import AdmissionCode, AdmissionRejected
from constructicon.core.component import CapabilityRequirement
from constructicon.core.graph import Graph, GraphNode
from constructicon.sdk import port_type, task


class Request(BaseModel):
    text: str


class Reply(BaseModel):
    text: str


@task(
    "authoring/respond",
    output="reply",
    capabilities=(CapabilityRequirement(alias="executor", kind="executor"),),
)
async def respond(
    request: Annotated[Request, port_type("authoring/Request")],
) -> Annotated[Reply, port_type("authoring/Reply")]:
    return Reply(text=request.text)


def test_describe_is_bounded_complete_and_secret_free(
    system: Constructicon,
) -> None:
    version = system.register(respond)
    system.promote_initial(component=respond.name, version=version)
    description = system.describe(limit=100)
    assert description.graph_schema.schema_["title"] == "Graph"
    assert description.admission_schema.schema_
    assert description.grants.root_grants.posture.value == "read"
    assert description.authoring.bindings.ambiguity_policy == "reject"
    described = next(item for item in description.components if item.name == respond.name)
    assert described.completeness.capability_bindings is True
    assert described.completeness.port_schemas is True
    assert described.capability_requirements[0].alias == "executor"
    capability = next(
        item for item in description.capabilities if item.capability_id == "fake-executor"
    )
    assert capability.available is True
    rendered = description.model_dump_json()
    assert "FakeExecutor" not in rendered
    assert "_scripts" not in rendered


def test_missing_declared_capability_is_a_typed_repair(
    system: Constructicon,
) -> None:
    version = system.register(respond)
    system.promote_initial(component=respond.name, version=version)
    graph = Graph(
        name="missing-capability",
        nodes=(GraphNode(id="respond", body=respond.ref()),),
        inputs=respond.definition.inputs,
        outputs=respond.definition.outputs,
    )
    result = system.admit_graph(graph, {"request": {"text": "hello"}})
    assert isinstance(result, AdmissionRejected)
    fault = next(
        item
        for item in result.faults
        if item.code is AdmissionCode.GRAPH_CAPABILITY_MISSING_BINDING
    )
    assert fault.details["alias"] == "executor"
    assert "fake-executor" in fault.details["available_capability_ids"]


def test_raw_graph_json_is_fail_closed(system: Constructicon) -> None:
    proposal = {
        "schema_version": 1,
        "name": "strict",
        "nodes": [],
        "connections": [],
        "inputs": [],
        "outputs": [],
        "invented_semantics": {"trust_me": True},
    }
    result = system.admit_graph(proposal, {})
    assert isinstance(result, AdmissionRejected)
    assert result.graph is None
    assert result.faults[0].code is AdmissionCode.GRAPH_SCHEMA_INVALID_VALUE
    assert result.faults[0].path == ("invented_semantics",)
