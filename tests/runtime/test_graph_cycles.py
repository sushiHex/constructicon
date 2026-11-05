"""Authored connection cycles are refused, never silently dropped (issue #367)."""

from __future__ import annotations

import json

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.admission import (
    FAULT_DETAILS_SEPARATOR,
    AdmissionAccepted,
    AdmissionCode,
    AdmissionRejected,
)
from constructicon.core.component import ComponentDef
from constructicon.core.errors import AdmissionError
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.introspection import AdmissionLimits
from constructicon.runtime import validator
from constructicon.runtime.validator import admit
from tests.conftest import BRIEF, ISSUE, SUMMARY, atomic, summarize_impl
from tests.runtime.test_loop_validator import (
    CONTINUE,
    STATE,
    basic_loop,
    register_atomic,
    step_impl,
)

ROOT = "cycle-root"
INPUTS = {"issue": {}}


@pytest.mark.parametrize("cap", [1, 2, 5, 25])
def test_cycle_preview_obeys_public_detail_limit(system: Constructicon, cap: int) -> None:
    register(system)
    names = [f"vertex-{i}" for i in range(5)]
    graph = cyclic(
        tuple(node(name, "cycle/triage") for name in names),
        tuple(zip(names, [*names[1:], names[0]], strict=True)),
    )
    bounded = Constructicon(
        journal=system._journal, admission_limits=AdmissionLimits(max_fault_detail_items=cap),
    )
    result = bounded.admit_graph(graph, INPUTS)
    assert isinstance(result, AdmissionRejected)
    (fault,) = result.faults
    expected = [*names, names[0]][:cap]
    assert fault.details["cycle"] == expected
    assert fault.details["cycle_total"] == 6
    assert fault.details["truncated"] is (cap < 6)
    framed = json.loads(fault.message.rpartition(FAULT_DETAILS_SEPARATOR)[2])
    assert framed["cycle"] == expected
    assert framed["cycle_total"] == 6
    assert framed["truncated"] is (cap < 6)
    if cap < 3:
        assert names[2] not in fault.message


def raw_admit(system: Constructicon, graph: Graph):
    return admit(
        graph,
        snapshot=system._registry.snapshot(),
        catalog=system._catalog,
        capabilities=system._capabilities,
        root_grants=system._root_grants,
        inputs=INPUTS,
    )


def register(system: Constructicon) -> None:
    for name, inputs, outputs in (
        ("cycle/back", (BRIEF,), (ISSUE,)),
        ("cycle/triage", (ISSUE,), (BRIEF,)),
        ("cycle/summarize", (BRIEF,), (SUMMARY,)),
    ):
        definition, impl = atomic(name, inputs, outputs, summarize_impl)
        version = system._register(definition, impl)
        system._promote_initial(component=name, version=version)


def node(name: str, component: str) -> GraphNode:
    return GraphNode(id=name, body=Ref(component=component))


def edges(*pairs: tuple[str, str]) -> tuple[Connection, ...]:
    return tuple(Connection(src=src, dst=dst) for src, dst in pairs)


def cyclic(nodes: tuple[GraphNode, ...], pairs: tuple[tuple[str, str], ...]) -> Graph:
    return Graph(
        name=ROOT, nodes=nodes, connections=edges(*pairs),
        inputs=(ISSUE,), outputs=(),
    )


CASES = {
    # The reported shape: back(BRIEF->ISSUE) <-> triage(ISSUE->BRIEF).
    "two-node": (
        (node("back", "cycle/back"), node("triage", "cycle/triage")),
        (("triage", "back"), ("back", "triage")),
        ["back", "triage", "back"], 0,
    ),
    "self-edge": (
        (node("triage", "cycle/triage"),),
        (("triage", "triage"),),
        ["triage", "triage"], 0,
    ),
    # Neither cycle member is fed by, or feeds, the graph boundary or any other node.
    "unanchored-three-node": (
        (node("a", "cycle/triage"), node("b", "cycle/back"), node("c", "cycle/triage"),
         node("lone", "cycle/triage")),
        (("a", "b"), ("b", "c"), ("c", "a")),
        ["a", "b", "c", "a"], 2,
    ),
    # A cycle reached through an acyclic prefix.
    "downstream-of-dag": (
        (node("head", "cycle/triage"), node("back", "cycle/back"),
         node("triage", "cycle/triage")),
        (("head", "triage"), ("triage", "back"), ("back", "triage")),
        ["triage", "back", "triage"], 2,
    ),
}


def wrap(system: Constructicon, inner: Graph, wrapper: str) -> tuple[Graph, tuple[str, ...]]:
    if wrapper == "root":
        return inner, (ROOT,)
    if wrapper == "inline":
        return Graph(
            name="outer", nodes=(GraphNode(id="inner", body=inner),),
            inputs=inner.inputs, outputs=(),
        ), ("outer", "inner")
    if wrapper == "loop":
        return Graph(
            name="outer",
            nodes=(GraphNode(id="inner", body=Loop(
                body=inner, feedback={}, continue_from="continue", max_iterations=1,
            )),),
            inputs=inner.inputs, outputs=(),
        ), ("outer", "inner", "body")
    definition = ComponentDef(
        name="cycle/composite", role="component", body=inner,
        inputs=inner.inputs, outputs=inner.outputs,
    )
    version = system._register(definition)
    system._promote_initial(component=definition.name, version=version)
    return Graph(
        name="outer", nodes=(GraphNode(id="inner", body=Ref(component=definition.name)),),
        inputs=inner.inputs, outputs=(),
    ), ("outer", "inner")


@pytest.mark.parametrize("wrapper", ["root", "inline", "retained"])
@pytest.mark.parametrize("case", sorted(CASES))
def test_connection_cycles_are_refused_with_the_cycle_named(
    system: Constructicon, case: str, wrapper: str
) -> None:
    register(system)
    nodes, pairs, cycle, index = CASES[case]
    graph, scope = wrap(system, cyclic(nodes, pairs), wrapper)
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    assert len(result.faults) == 1
    fault = result.faults[0]
    assert fault.code == AdmissionCode.GRAPH_CYCLE
    assert fault.details["defect"] == "graph_cycle"
    assert fault.details["cycle"] == cycle
    assert fault.details["connection_index"] == index
    assert fault.details["source_node"] == cycle[-2]
    assert fault.details["destination_node"] == cycle[-1]
    assert fault.scope is not None and fault.scope.segments == scope
    assert "cycle outside Loop" in fault.message
    with pytest.raises(AdmissionError) as caught:
        raw_admit(system, graph)
    assert len(caught.value.faults) == 1
    carried = json.loads(caught.value.faults[0].message.rpartition(FAULT_DETAILS_SEPARATOR)[2])
    assert carried["cycle"] == cycle


def test_cycle_inside_a_loop_body_is_refused(system: Constructicon) -> None:
    register(system)
    nodes, pairs, cycle, _ = CASES["two-node"]
    graph, scope = wrap(system, cyclic(nodes, pairs), "loop")
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    # The synthetic body may add unrelated Loop-contract faults; the cycle is one of them.
    faults = [f for f in result.faults if f.code == AdmissionCode.GRAPH_CYCLE]
    assert len(faults) == 1
    assert faults[0].details["cycle"] == cycle
    assert faults[0].scope is not None and faults[0].scope.segments == scope


def test_each_independent_cycle_gets_one_fault(system: Constructicon) -> None:
    register(system)
    graph = cyclic(
        (node("a", "cycle/triage"), node("b", "cycle/back"),
         node("c", "cycle/triage"), node("d", "cycle/back")),
        (("a", "b"), ("b", "a"), ("c", "d"), ("d", "c")),
    )
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    assert [f.details["cycle"] for f in result.faults] == [["a", "b", "a"], ["c", "d", "c"]]


def test_endpoint_fault_precedence_is_unchanged(
    system: Constructicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(system)
    graph = cyclic(
        (node("a", "cycle/triage"), node("b", "cycle/back")),
        (("a", "b"), ("b", "a"), ("a", "ghost")),
    )

    def must_not_run(*args, **kwargs):
        pytest.fail("cycle detection ran on an endpoint-invalid graph")

    monkeypatch.setattr(validator, "_reject_cycles", must_not_run)
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    assert [f.details["defect"] for f in result.faults] == ["unknown_connection_node"]


def test_cycle_refusal_precedes_closure_and_node_compilation(
    system: Constructicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(system)
    nodes, pairs, _, _ = CASES["two-node"]

    def must_not_run(*args, **kwargs):
        pytest.fail("a cyclic graph reached closure or compilation")

    monkeypatch.setattr(validator, "_upstream_closure", must_not_run)
    monkeypatch.setattr(validator, "_compile_node", must_not_run)
    result = system.admit_graph(cyclic(nodes, pairs).model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    assert result.faults[0].code == AdmissionCode.GRAPH_CYCLE


def test_empty_node_id_self_edge_is_a_cycle(
    system: Constructicon,
) -> None:
    register(system)
    looped = cyclic((node("", "cycle/triage"),), (("", ""),))
    result = system.admit_graph(looped.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    assert result.faults[0].details["cycle"] == ["", ""]


def test_shared_ancestors_and_diamonds_are_accepted(system: Constructicon) -> None:
    register(system)
    # head fans out to left/right, which both feed join: a diamond with a shared ancestor.
    graph = Graph(
        name="diamond",
        nodes=(
            node("head", "cycle/triage"),
            node("left", "cycle/summarize"),
            node("right", "cycle/summarize"),
        ),
        connections=edges(("head", "left"), ("head", "right")),
        inputs=(ISSUE,),
        outputs=(),
    )
    assert isinstance(system.admit_graph(graph.model_dump_json(), INPUTS), AdmissionAccepted)
    chain = Graph(
        name="shared",
        nodes=(
            node("head", "cycle/triage"),
            node("mid", "cycle/back"),
            node("tail", "cycle/summarize"),
        ),
        connections=edges(("head", "mid"), ("mid", "tail"), ("head", "tail")),
        inputs=(ISSUE,),
        outputs=(),
    )
    assert isinstance(system.admit_graph(chain.model_dump_json(), INPUTS), AdmissionAccepted)


def test_explicit_loop_feedback_is_still_admitted(system: Constructicon) -> None:
    register_atomic(system, "cycle/step", (STATE,), (STATE, CONTINUE), step_impl)
    graph = basic_loop("cycle/step")
    result = system.admit_graph(graph.model_dump_json(), {"state": {"value": 0}})
    assert isinstance(result, AdmissionAccepted)
    assert len(result.manifest.resolved_loops) == 1
