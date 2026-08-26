"""M5 typed describe and architect admission surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel

from constructicon.api.system import Constructicon
from constructicon.core.admission import AdmissionCode, AdmissionRejected
from constructicon.core.component import CapabilityRequirement
from constructicon.core.graph import Graph, GraphNode
from constructicon.runtime.context import NodeContext
from constructicon.sdk import port_type, task
from tests.conftest import atomic


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


@task("authoring/plain", output="reply")
async def plain(
    request: Annotated[Request, port_type("authoring/Request")],
) -> Annotated[Reply, port_type("authoring/Reply")]:
    return Reply(text=request.text)


async def legacy_impl(
    ctx: NodeContext,
    inputs: Mapping[str, Any],
) -> Mapping[str, Any]:
    return {"reply": inputs["request"]}


def test_describe_is_bounded_complete_and_secret_free(
    system: Constructicon,
) -> None:
    for bundle in (respond, plain):
        version = system.register(bundle)
        system.promote_initial(component=bundle.name, version=version)
    legacy_definition, legacy_implementation = atomic(
        "authoring/legacy",
        respond.definition.inputs,
        respond.definition.outputs,
        legacy_impl,
    )
    legacy_version = system.register(legacy_definition, legacy_implementation)
    system.promote_initial(component=legacy_definition.name, version=legacy_version)

    description = system.describe(limit=100)
    assert description.graph_schema.schema_["title"] == "Graph"
    assert description.admission_schema.schema_
    assert description.grants.root_grants.posture.value == "read"
    assert description.authoring.bindings.ambiguity_policy == "reject"

    described = next(item for item in description.components if item.name == respond.name)
    assert described.completeness.capability_bindings is True
    assert described.completeness.port_schemas is True
    assert described.capability_requirements[0].alias == "executor"
    for port in (*described.inputs, *described.outputs):
        document = next(
            schema for schema in description.schemas if schema.schema_hash == port.schema_hash
        )
        assert document.schema_ and document.schema_hash == port.schema_hash

    plain_description = next(
        item for item in description.components if item.name == plain.name
    )
    assert plain_description.capability_requirements == ()
    assert plain_description.completeness.capability_bindings is True

    legacy_description = next(
        item for item in description.components if item.name == legacy_definition.name
    )
    assert legacy_description.capability_requirements == ()
    assert legacy_description.completeness.capability_bindings is False

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
