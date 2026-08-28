"""M4 admission: loops compile completely or fail with repairable faults."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.component import ComponentDef
from constructicon.core.errors import AdmissionError
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.manifest import CONTINUE_SCHEMA_HASH, CONTINUE_TYPE
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeContext
from tests.conftest import atomic

STATE = Port(name="state", type_id="loop/State", schema_hash="state-v1")
OTHER_STATE = Port(name="state", type_id="loop/State", schema_hash="state-v2")
LIMIT = Port(name="limit", type_id="loop/Limit", schema_hash="limit-v1")
CONTINUE = Port(
    name="continue",
    type_id=CONTINUE_TYPE,
    schema_hash=CONTINUE_SCHEMA_HASH,
    json_schema={"type": "boolean"},
)


async def step_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"state": inputs["state"], "continue": False}


async def seed_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"state": inputs["state"]}


async def decide_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"continue": False}


def register_atomic(
    system: Constructicon,
    name: str,
    inputs: tuple[Port, ...],
    outputs: tuple[Port, ...],
    impl: Any = step_impl,
) -> None:
    definition, implementation = atomic(name, inputs, outputs, impl)
    version = system._register(definition, implementation)
    system._promote_initial(component=name, version=version)


def basic_loop(component: str, *, feedback: dict[str, str] | None = None) -> Graph:
    return Graph(
        name="validator-loop",
        nodes=(
            GraphNode(
                id="repeat",
                body=Loop(
                    body=Ref(component=component),
                    feedback=feedback if feedback is not None else {"state": "state"},
                    continue_from="continue",
                    max_iterations=2,
                ),
            ),
        ),
        inputs=(STATE,),
        outputs=(STATE,),
    )


def test_missing_feedback_seed_names_the_repair(system: Constructicon) -> None:
    register_atomic(system, "loop/step", (STATE,), (STATE, CONTINUE))
    graph = basic_loop("loop/step")
    with pytest.raises(AdmissionError, match="feedback port 'state' needs an initial value"):
        system.validate(graph, {})


def test_feedback_requires_known_ports(system: Constructicon) -> None:
    register_atomic(system, "loop/step", (STATE,), (STATE, CONTINUE))
    graph = basic_loop("loop/step", feedback={"missing-input": "missing-output"})
    with pytest.raises(AdmissionError) as caught:
        system.validate(graph, {"state": {"value": 0}})
    message = str(caught.value)
    assert "feedback destination 'missing-input'" in message
    assert "feedback source 'missing-output'" in message


def test_feedback_requires_exact_schema_revision(system: Constructicon) -> None:
    register_atomic(system, "loop/schema-mismatch", (OTHER_STATE,), (STATE, CONTINUE))
    graph = basic_loop("loop/schema-mismatch")
    with pytest.raises(AdmissionError, match="exact nominal contract"):
        system.validate(graph, {"state": {"value": 0}})


@pytest.mark.parametrize("side", ["input", "output"])
def test_feedback_rejects_non_scalar_cardinality(
    system: Constructicon, side: str
) -> None:
    many_input = STATE.model_copy(update={"cardinality": "many"})
    many_output = STATE.model_copy(update={"cardinality": "many"})
    inputs = (many_input if side == "input" else STATE,)
    outputs = (many_output if side == "output" else STATE, CONTINUE)
    register_atomic(system, f"loop/many-{side}", inputs, outputs)
    graph_input = many_input if side == "input" else STATE
    graph = Graph(
        name=f"many-{side}",
        nodes=(
            GraphNode(
                id="repeat",
                body=Loop(
                    body=Ref(component=f"loop/many-{side}"),
                    feedback={"state": "state"},
                    continue_from="continue",
                    max_iterations=2,
                ),
            ),
        ),
        inputs=(graph_input,),
        outputs=(),
    )
    with pytest.raises(AdmissionError, match="cardinality 'one' on both ports"):
        system.validate(graph, {"state": [{"value": 0}]})


def test_continue_from_must_name_the_canonical_scalar_bool(system: Constructicon) -> None:
    optional_continue = CONTINUE.model_copy(update={"cardinality": "optional"})
    register_atomic(
        system,
        "loop/optional-control",
        (STATE,),
        (STATE, optional_continue),
    )
    with pytest.raises(AdmissionError, match="continuation output"):
        system.validate(
            basic_loop("loop/optional-control"),
            {"state": {"value": 0}},
        )


def test_unknown_continue_port_is_itemized(system: Constructicon) -> None:
    register_atomic(system, "loop/step", (STATE,), (STATE, CONTINUE))
    graph = basic_loop("loop/step")
    loop = graph.nodes[0].body
    assert isinstance(loop, Loop)
    broken = graph.model_copy(
        update={
            "nodes": (
                GraphNode(
                    id="repeat",
                    body=loop.model_copy(update={"continue_from": "missing"}),
                ),
            )
        }
    )
    with pytest.raises(AdmissionError, match="continue_from 'missing'"):
        system.validate(broken, {"state": {"value": 0}})


def test_explicit_map_disambiguates_the_loop_boundary(system: Constructicon) -> None:
    register_atomic(system, "loop/seed", (STATE,), (STATE,), seed_impl)
    register_atomic(system, "loop/step", (STATE,), (STATE, CONTINUE))
    graph = Graph(
        name="mapped-loop",
        nodes=(
            GraphNode(id="left", body=Ref(component="loop/seed")),
            GraphNode(id="right", body=Ref(component="loop/seed")),
            GraphNode(
                id="repeat",
                body=Loop(
                    body=Ref(component="loop/step"),
                    feedback={"state": "state"},
                    continue_from="continue",
                    max_iterations=2,
                ),
            ),
        ),
        connections=(
            Connection(src="left", dst="repeat", map={"state": "left.state"}),
            Connection(src="right", dst="repeat"),
        ),
        inputs=(STATE,),
        outputs=(),
    )
    manifest = system.validate(graph, {"state": {"value": 0}})
    loop = manifest.resolved_loops[0]
    assert len(loop.initial_bindings) == 1
    source = loop.initial_bindings[0].sources[0]
    assert getattr(source, "node", None) == "left"


def test_nested_loop_hidden_inside_a_composite_is_refused(system: Constructicon) -> None:
    register_atomic(system, "loop/step", (STATE,), (STATE, CONTINUE))
    inner = basic_loop("loop/step")
    composite = ComponentDef(
        name="loop/inner-composite",
        role="component",
        body=inner,
        inputs=(STATE,),
        outputs=(STATE,),
    )
    version = system._register(composite)
    system._promote_initial(component=composite.name, version=version)
    outer = basic_loop("loop/inner-composite")
    with pytest.raises(AdmissionError, match="nested Loop arrives with a later milestone"):
        system.validate(outer, {"state": {"value": 0}})


def test_direct_composite_body_has_ordered_atomic_members(system: Constructicon) -> None:
    register_atomic(system, "loop/step", (STATE,), (STATE, CONTINUE))
    body = Graph(
        name="body",
        nodes=(GraphNode(id="advance", body=Ref(component="loop/step")),),
        inputs=(STATE,),
        outputs=(STATE, CONTINUE),
    )
    composite = ComponentDef(
        name="loop/composite",
        role="component",
        body=body,
        inputs=body.inputs,
        outputs=body.outputs,
    )
    version = system._register(composite)
    system._promote_initial(component=composite.name, version=version)
    manifest = system.validate(
        basic_loop("loop/composite"),
        {"state": {"value": 0}},
    )
    assert [scope.render() for scope in manifest.resolved_loops[0].member_order] == [
        "validator-loop/repeat/body/$body/advance"
    ]


def test_control_only_body_is_a_legal_zero_export_sink(system: Constructicon) -> None:
    register_atomic(system, "loop/decide", (), (CONTINUE,), decide_impl)
    graph = Graph(
        name="control-sink",
        nodes=(
            GraphNode(
                id="repeat",
                body=Loop(
                    body=Ref(component="loop/decide"),
                    feedback={},
                    continue_from="continue",
                    max_iterations=1,
                ),
            ),
        ),
    )
    manifest = system.validate(graph, {})
    assert manifest.resolved_loops[0].exports == ()
