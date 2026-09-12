"""Exact public coordinates for validator faults with legal identifiers (#69)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import ScopePath
from constructicon.core.admission import (
    AdmissionAccepted,
    AdmissionCode,
    AdmissionFault,
    AdmissionRejected,
)
from constructicon.core.component import ComponentDef
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.introspection import AdmissionLimits
from constructicon.core.manifest import CONTINUE_SCHEMA_HASH, CONTINUE_TYPE
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeContext
from tests.conftest import BRIEF, ISSUE, atomic

STATE = Port(name="state", type_id="faults/State", schema_hash="state-v1")
CONTINUE = Port(
    name="continue",
    type_id=CONTINUE_TYPE,
    schema_hash=CONTINUE_SCHEMA_HASH,
    json_schema={"type": "boolean"},
)
SELECTED = BRIEF.model_copy(update={"name": "selected"})
MAYBE_BRIEF = BRIEF.model_copy(update={"name": "maybe", "cardinality": "optional"})


async def _unused_impl(
    ctx: NodeContext, inputs: Mapping[str, Any],
) -> Mapping[str, Any]:
    del ctx, inputs
    return {}


def _register_atomic(
    system: Constructicon,
    name: str,
    inputs: tuple[Port, ...],
    outputs: tuple[Port, ...],
) -> None:
    definition, implementation = atomic(name, inputs, outputs, _unused_impl)
    version = system._register(definition, implementation)
    system._promote_initial(component=name, version=version)


def _fault(
    system: Constructicon,
    graph: Graph,
    code: AdmissionCode,
    *,
    marker: str | None = None,
    inputs: dict[str, Any] | None = None,
) -> AdmissionFault:
    result = system.admit_graph(graph.model_dump(mode="json"), inputs or {})
    assert isinstance(result, AdmissionRejected)
    matches = [
        fault
        for fault in result.faults
        if fault.code is code and (marker is None or marker in fault.message)
    ]
    assert len(matches) == 1, result.faults
    return matches[0]


@pytest.mark.parametrize(
    ("root", "seat"),
    [("root", "seat"), ("root/with:colon", "seat/with:colon")],
)
def test_missing_node_source_keeps_its_exact_destination(
    world: Constructicon, root: str, seat: str,
) -> None:
    graph = Graph(
        name=root,
        nodes=(GraphNode(id=seat, body=Ref(component="test/summarize")),),
    )

    fault = _fault(world, graph, AdmissionCode.GRAPH_PORT_MISSING_SOURCE)

    assert fault.scope == ScopePath(segments=(root, seat))
    assert fault.path == ("nodes", 0, "body")
    assert fault.details["defect"] == "missing_port_source"
    assert fault.details["destination_node"] == seat
    assert fault.details["destination_port"] == "brief"
    assert fault.repair == "connect a matching upstream output or graph input"


@pytest.mark.parametrize(
    ("root", "seat"),
    [("root", "repeat"), ("root:colon", "repeat/seat")],
)
def test_feedback_seed_keeps_its_exact_loop_destination(
    system: Constructicon, root: str, seat: str,
) -> None:
    _register_atomic(system, "faults/step", (STATE,), (STATE, CONTINUE))
    graph = Graph(
        name=root,
        nodes=(
            GraphNode(
                id=seat,
                body=Loop(
                    body=Ref(component="faults/step"),
                    feedback={"state": "state"},
                    continue_from="continue",
                    max_iterations=1,
                ),
            ),
        ),
    )

    fault = _fault(
        system,
        graph,
        AdmissionCode.GRAPH_PORT_MISSING_SOURCE,
        marker="feedback port 'state' needs an initial value",
    )

    assert fault.scope == ScopePath(segments=(root, seat))
    assert fault.path == ("nodes", 0, "body")
    assert fault.details["defect"] == "missing_feedback_seed"
    assert fault.details["destination_node"] == seat
    assert fault.details["destination_port"] == "state"
    assert fault.repair == "connect a matching outer seed or add a per-port map override"


@pytest.mark.parametrize("destination", ["target", "target/with:colon"])
def test_ambiguous_node_input_keeps_the_exact_map_repair(
    world: Constructicon, destination: str,
) -> None:
    graph = Graph(
        name="root",
        inputs=(ISSUE,),
        nodes=(
            GraphNode(
                id="left",
                body=Ref(
                    component="test/triage", bind={"executor": "fake-executor"},
                ),
            ),
            GraphNode(
                id="right",
                body=Ref(
                    component="test/triage", bind={"executor": "fake-executor"},
                ),
            ),
            GraphNode(id=destination, body=Ref(component="test/summarize")),
        ),
        connections=(
            Connection(src="left", dst=destination),
            Connection(src="right", dst=destination),
        ),
    )

    fault = _fault(
        world,
        graph,
        AdmissionCode.GRAPH_PORT_AMBIGUOUS,
        inputs={"issue": {"title": "x"}},
    )

    assert fault.scope == ScopePath(segments=("root", destination))
    assert fault.path == ("connections", 0, "map", "brief")
    assert fault.details["connection_index"] == 0
    assert fault.details["destination_node"] == destination
    assert fault.details["destination_port"] == "brief"
    assert fault.details["map_path"] == ["connections", 0, "map", "brief"]
    assert fault.details["candidates"] == ["left.brief", "right.brief"]
    assert fault.details["map_example"] == {"brief": "left.brief"}
    assert fault.repair == "add a Connection.map override selecting one candidate"


def test_ambiguity_advertises_only_applicable_level_local_selectors(
    world: Constructicon,
) -> None:
    inner = Graph(
        name="inner/name:is-not-an-authoring-selector",
        inputs=(ISSUE,),
        outputs=(BRIEF,),
        nodes=(
            GraphNode(
                id="flattened/inner:seat",
                body=Ref(
                    component="test/triage", bind={"executor": "fake-executor"},
                ),
            ),
        ),
    )
    composite = ComponentDef(
        name="faults/composite-source",
        role="component",
        body=inner,
        inputs=inner.inputs,
        outputs=inner.outputs,
    )
    version = world._register(composite)
    world._promote_initial(component=composite.name, version=version)
    _register_atomic(world, "faults/optional-source", (), (MAYBE_BRIEF,))
    _register_atomic(world, "faults/select", (SELECTED,), ())
    source = "outer/source:alias"
    target = "target/with:colon"
    graph = Graph(
        name="root/with:colon",
        inputs=(ISSUE, BRIEF.model_copy(update={"name": "seed"})),
        nodes=(
            GraphNode(id=source, body=Ref(component=composite.name)),
            GraphNode(id="optional", body=Ref(component="faults/optional-source")),
            GraphNode(id=target, body=Ref(component="faults/select")),
        ),
        connections=(
            Connection(src=source, dst=target),
            Connection(src="optional", dst=target),
        ),
    )
    inputs = {"issue": {"title": "x"}, "seed": {"title": "seed"}}

    fault = _fault(
        world,
        graph,
        AdmissionCode.GRAPH_PORT_AMBIGUOUS,
        inputs=inputs,
    )

    assert fault.details["candidates"] == ["$input.seed", f"{source}.brief"]
    assert fault.details["candidate_total"] == 2
    assert fault.details["map_example"] == {"selected": "$input.seed"}
    assert "optional.maybe" not in fault.details["candidates"]
    assert "flattened/inner:seat.brief" not in fault.details["candidates"]

    for selector in fault.details["candidates"]:
        repaired = graph.model_copy(
            update={
                "connections": (
                    graph.connections[0].model_copy(
                        update={"map": {"selected": selector}},
                    ),
                    graph.connections[1],
                ),
            },
        )
        result = world.admit_graph(repaired.model_dump(mode="json"), inputs)
        assert isinstance(result, AdmissionAccepted), result

    world._admission_limits = AdmissionLimits(max_fault_detail_items=1)
    bounded = _fault(
        world,
        graph,
        AdmissionCode.GRAPH_PORT_AMBIGUOUS,
        inputs=inputs,
    )
    assert bounded.details["candidates"] == ["$input.seed"]
    assert bounded.details["candidate_total"] == 2
    assert bounded.details["truncated"] is True
    assert bounded.details["map_example"] == {"selected": "$input.seed"}


def test_ambiguity_does_not_offer_a_map_without_a_connection_to_own_it(
    system: Constructicon,
) -> None:
    _register_atomic(system, "faults/select", (SELECTED,), ())
    graph = Graph(
        name="root/with:colon",
        inputs=(
            BRIEF.model_copy(update={"name": "left"}),
            BRIEF.model_copy(update={"name": "right"}),
        ),
        nodes=(
            GraphNode(
                id="target/with:colon",
                body=Ref(component="faults/select"),
            ),
        ),
    )

    fault = _fault(
        system,
        graph,
        AdmissionCode.GRAPH_PORT_AMBIGUOUS,
        inputs={"left": {}, "right": {}},
    )

    assert fault.path == ("nodes", 0, "body")
    assert fault.details["candidates"] == ["$input.left", "$input.right"]
    assert "connection_index" not in fault.details
    assert "map_path" not in fault.details
    assert "map_example" not in fault.details
    assert fault.repair == (
        "add an incoming connection with a per-port map or compose a scalar adapter"
    )


def test_retained_missing_source_keeps_definition_owned_coordinates(
    world: Constructicon,
) -> None:
    body = Graph(
        name="ignored/retained:name",
        nodes=(
            GraphNode(
                id="inner/seat:colon",
                body=Ref(component="test/summarize"),
            ),
        ),
    )
    composite = ComponentDef(
        name="faults/retained-missing-source",
        role="component",
        body=body,
        inputs=(),
        outputs=(),
    )
    version = world._register(composite)
    world._promote_initial(component=composite.name, version=version)
    graph = Graph(
        name="root/with:colon",
        nodes=(
            GraphNode(
                id="outer/seat:colon",
                body=Ref(component=composite.name),
            ),
        ),
    )

    fault = _fault(world, graph, AdmissionCode.GRAPH_PORT_MISSING_SOURCE)

    assert fault.path == ()
    assert fault.scope == ScopePath(
        segments=("root/with:colon", "outer/seat:colon", "inner/seat:colon"),
    )
    assert fault.details["component"] == composite.name
    assert fault.details["version"] == str(version)
    assert fault.details["definition_path"] == ["body", "nodes", 0, "body"]
    assert fault.details["destination_node"] == "inner/seat:colon"
    assert fault.details["destination_port"] == "brief"
