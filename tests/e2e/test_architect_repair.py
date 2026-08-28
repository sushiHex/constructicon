"""M5 acceptance: schemas + describe + faults are a complete repair loop."""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import BaseModel

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.admission import (
    AdmissionAccepted,
    AdmissionCode,
    AdmissionRejected,
)
from constructicon.core.graph import Connection, Graph, GraphNode
from constructicon.sdk import port_type, task


class Value(BaseModel):
    text: str


class Result(BaseModel):
    selected: str


@task("architect/left", output="left")
async def left() -> Annotated[Value, port_type("architect/Value")]:
    return Value(text="left")


@task("architect/right", output="right")
async def right() -> Annotated[Value, port_type("architect/Value")]:
    return Value(text="right")


@task("architect/select", output="result")
async def select(
    value: Annotated[Value, port_type("architect/Value")],
) -> Annotated[Result, port_type("architect/Result")]:
    return Result(selected=value.text)


class ScriptedArchitect:
    """Receives serialized contracts and edits serialized Graph data only."""

    def __init__(self, authoring_contract_json: str) -> None:
        contract = json.loads(authoring_contract_json)
        names = {item["name"] for item in contract["components"]}
        assert {left.name, right.name, select.name} <= names
        self._proposal: dict[str, Any] = {
            "schema_version": 1,
            "name": "architect-selection",
            "nodes": [
                {"id": "left", "body": {"component": left.name}},
                {"id": "right", "body": {"component": right.name}},
                {"id": "select", "body": {"component": select.name}},
            ],
            "connections": [
                {"src": "left", "dst": "select", "map": {}},
                {"src": "right", "dst": "select", "map": {}},
            ],
            "inputs": [],
            "outputs": [select.definition.outputs[0].model_dump(mode="json")],
            "unsupported_shortcut": True,
        }

    def propose(self) -> str:
        return json.dumps(self._proposal)

    def repair(self, rejection_json: str) -> str:
        rejection = json.loads(rejection_json)
        faults = rejection["faults"]
        if any(fault["code"].startswith("graph.schema.") for fault in faults):
            self._proposal.pop("unsupported_shortcut", None)
            return self.propose()
        ambiguity = next(
            fault
            for fault in faults
            if fault["code"] == AdmissionCode.GRAPH_PORT_AMBIGUOUS.value
        )
        details = ambiguity["details"]
        index = details["connection_index"]
        self._proposal["connections"][index]["map"].update(details["map_example"])
        return self.propose()


async def test_architect_repairs_json_and_executes(
    system: Constructicon,
) -> None:
    for bundle in (left, right, select):
        version = system._register(bundle)
        system._promote_initial(component=bundle.name, version=version)

    architect = ScriptedArchitect(system.describe().model_dump_json())

    schema_rejection = system.admit_graph(architect.propose(), {})
    assert isinstance(schema_rejection, AdmissionRejected)
    assert schema_rejection.faults[0].code is AdmissionCode.GRAPH_SCHEMA_INVALID_VALUE

    ambiguous = system.admit_graph(
        architect.repair(schema_rejection.model_dump_json()),
        {},
    )
    assert isinstance(ambiguous, AdmissionRejected)
    ambiguity = next(
        fault
        for fault in ambiguous.faults
        if fault.code is AdmissionCode.GRAPH_PORT_AMBIGUOUS
    )
    assert ambiguity.details["candidates"] == ["left.left", "right.right"]
    assert ambiguity.details["map_example"] == {"value": "left.left"}

    accepted = system.admit_graph(
        architect.repair(ambiguous.model_dump_json()),
        {},
    )
    assert isinstance(accepted, AdmissionAccepted)

    direct = Graph(
        name="architect-selection",
        nodes=(
            GraphNode(id="left", body=left.ref()),
            GraphNode(id="right", body=right.ref()),
            GraphNode(id="select", body=select.ref()),
        ),
        connections=(
            Connection(src="left", dst="select", map={"value": "left.left"}),
            Connection(src="right", dst="select"),
        ),
        outputs=select.definition.outputs,
    )
    assert accepted.graph.model_dump(mode="json") == direct.model_dump(mode="json")
    direct_manifest = system.validate(direct, {})
    assert accepted.manifest.manifest_hash == direct_manifest.manifest_hash

    result = await system._start_direct(
        accepted.graph,
        {},
        run_id=RunId("architect-repair"),
    )
    assert result.outputs == {"result": {"selected": "left"}}
