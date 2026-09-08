"""Endpoint existence is one compiler law, with coordinates owned by authored bytes."""

from __future__ import annotations

import json

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.admission import FAULT_DETAILS_SEPARATOR, AdmissionCode, AdmissionRejected
from constructicon.core.component import ComponentDef
from constructicon.core.errors import AdmissionError
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.identity import canonical_json
from constructicon.core.introspection import AdmissionLimits
from constructicon.runtime import validator
from tests.conftest import SUMMARY, atomic, summarize_impl
from tests.runtime.test_explicit_membership import INPUTS, membership_graph, raw_admit
from tests.runtime.test_loop_validator import CONTINUE

ROOT = "endpoint/root: \x1f"
INSTANCE = "nested/instance"
WRAPPERS = ("root", "inline", "loop", "retained", "retained-inline", "retained-loop")
PATHS = {
    "root": ("connections", 1),
    "inline": ("nodes", 0, "body", "connections", 1),
    "loop": ("nodes", 0, "body", "body", "connections", 1),
    "retained": ("body", "connections", 1),
    "retained-inline": ("body", "nodes", 0, "body", "connections", 1),
    "retained-loop": ("body", "connections", 1),
}
SCOPES = {
    "root": (ROOT,),
    "inline": (ROOT, INSTANCE),
    "loop": (ROOT, INSTANCE, "body"),
    "retained": (ROOT, INSTANCE),
    "retained-inline": (ROOT, INSTANCE, "inside/graph"),
    "retained-loop": (ROOT, INSTANCE, "body", "$body"),
}


def endpoint_graph(
    system: Constructicon,
    *,
    missing_roles: tuple[str, ...] = ("src", "dst"),
    wrapper: str = "root",
    mapped: bool = True,
) -> Graph:
    inner = membership_graph(system, selectors=("a.brief",))
    inner = inner.model_copy(
        update={
            "name": ROOT,
            "connections": (
                *inner.connections,
                Connection(
                    src="missing/src: loop" if "src" in missing_roles else "a",
                    dst="missing/dst: explicit selector" if "dst" in missing_roles else "gather",
                    map={"briefs": "a.brief"} if mapped else {},
                ),
            ),
        }
    )
    if wrapper == "root":
        return inner
    if wrapper in {"loop", "retained-loop"}:
        definition, impl = atomic("endpoints/continue", (), (CONTINUE,), summarize_impl)
        version = system._register(definition, impl)
        system._promote_initial(component=definition.name, version=version)
        inner = inner.model_copy(
            update={
                "nodes": (
                    *inner.nodes,
                    GraphNode(id="continue", body=Ref(component=definition.name)),
                ),
                "outputs": (*inner.outputs, CONTINUE),
            }
        )
    body = inner
    if wrapper.startswith("retained"):
        if wrapper == "retained-inline":
            inner = Graph(
                name="retained-wrapper",
                nodes=(GraphNode(id="inside/graph", body=inner),),
                inputs=inner.inputs,
                outputs=inner.outputs,
            )
        definition = ComponentDef(
            name="endpoints/composite",
            role="component",
            body=inner,
            inputs=inner.inputs,
            outputs=inner.outputs,
        )
        version = system._register(definition)
        system._promote_initial(component=definition.name, version=version)
        body = Ref(component=definition.name)
    if wrapper in {"loop", "retained-loop"}:
        body = Loop(body=body, feedback={}, continue_from="continue", max_iterations=1)
    return Graph(
        name=ROOT,
        nodes=(GraphNode(id=INSTANCE, body=body),),
        inputs=inner.inputs,
        outputs=(SUMMARY,),
    )


@pytest.mark.parametrize("wrapper", WRAPPERS)
@pytest.mark.parametrize("missing_roles", [("src",), ("dst",), ("src", "dst")])
@pytest.mark.parametrize("mapped", [False, True])
def test_unknown_endpoints_have_one_exact_fault_per_connection(
    system: Constructicon,
    wrapper: str,
    missing_roles: tuple[str, ...],
    mapped: bool,
) -> None:
    graph = endpoint_graph(system, wrapper=wrapper, missing_roles=missing_roles, mapped=mapped)
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    faults = [f for f in result.faults if f.details.get("defect") == "unknown_connection_node"]
    assert len(faults) == 1
    fault = faults[0]
    assert fault.code == AdmissionCode.GRAPH_CONTRACT_INVALID
    assert fault.scope is not None and fault.scope.segments == SCOPES[wrapper]
    assert fault.details["missing_roles"] == list(missing_roles)
    assert fault.details["connection_index"] == 1
    assert fault.details["source_node"] == ("missing/src: loop" if "src" in missing_roles else "a")
    assert fault.details["destination_node"] == (
        "missing/dst: explicit selector" if "dst" in missing_roles else "gather"
    )
    assert "declared node" in fault.repair
    if wrapper.startswith("retained"):
        assert fault.path == ()
        assert fault.details["component"] == "endpoints/composite"
        assert fault.details["version"] == system._registry.snapshot().stable["endpoints/composite"]
        assert fault.details["definition_path"] == list(PATHS[wrapper])
    else:
        assert fault.path == PATHS[wrapper]
        assert "component" not in fault.details and "definition_path" not in fault.details
    with pytest.raises(AdmissionError) as caught:
        raw_admit(system, graph)
    raw = [
        json.loads(f.message.rpartition(FAULT_DETAILS_SEPARATOR)[2])
        for f in caught.value.faults
        if f.message == fault.message
    ]
    expected = {"scope": list(SCOPES[wrapper]), **fault.details}
    if not wrapper.startswith("retained"):
        expected["path"] = list(PATHS[wrapper])
    assert raw == [expected]


def test_bad_endpoints_stop_before_reachability_and_node_compilation(
    system: Constructicon,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = endpoint_graph(system)

    def must_not_run(*args, **kwargs):
        pytest.fail("an endpoint-invalid graph reached compilation")

    monkeypatch.setattr(validator, "_upstream_closure", must_not_run)
    monkeypatch.setattr(validator, "_compile_node", must_not_run)
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    assert result.faults[0].details["defect"] == "unknown_connection_node"
    with pytest.raises(AdmissionError, match="unknown_connection_node"):
        raw_admit(system, graph)


@pytest.mark.parametrize("limit", [3, 20])
def test_endpoint_fault_order_and_truncation_ignore_map_object_order(
    system: Constructicon,
    limit: int,
) -> None:
    system._admission_limits = AdmissionLimits(max_faults=limit)
    graph = membership_graph(system, selectors=("a.brief",))
    observed = []
    for keys in (("z", "a"), ("a", "z")):
        proposal = graph.model_copy(
            update={
                "connections": tuple(
                    Connection(
                        src=f"absent-{index}", dst="gather", map={key: "a.brief" for key in keys}
                    )
                    for index in range(5)
                )
            }
        )
        result = system.admit_graph(proposal.model_dump_json(), INPUTS)
        assert isinstance(result, AdmissionRejected)
        observed.append(canonical_json(result.model_dump(mode="json")))
        faults = [f for f in result.faults if f.details.get("defect") == "unknown_connection_node"]
        assert [f.details["connection_index"] for f in faults] == list(
            range(2 if limit == 3 else 5)
        )
        if limit == 3:
            assert result.faults[-1].code == AdmissionCode.GRAPH_PROPOSAL_LIMIT_EXCEEDED
            assert result.faults[-1].details["fault_total"] == 5
    assert observed[0] == observed[1]


@pytest.mark.parametrize("node_id", ["", "source.with.dots", "source/with: punctuation"])
def test_endpoint_names_are_exact_ids_not_selector_syntax(
    system: Constructicon,
    node_id: str,
) -> None:
    graph = membership_graph(system, selectors=("a.brief",))
    graph = graph.model_copy(
        update={
            "nodes": (graph.nodes[0].model_copy(update={"id": node_id}), *graph.nodes[1:]),
            "connections": (Connection(src=node_id, dst="gather", map={"briefs": "$input.brief"}),),
        }
    )
    manifest = system.validate(graph, INPUTS)
    assert raw_admit(system, graph) == manifest


@pytest.mark.parametrize("node_id", ["", "$input", "a.port", "a/notreal"])
def test_an_endpoint_must_name_a_declared_node_even_when_its_map_resolves(
    system: Constructicon,
    node_id: str,
) -> None:
    graph = membership_graph(system, selectors=("a.brief",))
    graph = graph.model_copy(
        update={
            "connections": (
                *graph.connections,
                Connection(src=node_id, dst="gather", map={"briefs": "a.brief"}),
            ),
        }
    )
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    assert len(result.faults) == 1
    assert result.faults[0].details["defect"] == "unknown_connection_node"
    assert result.faults[0].details["missing_roles"] == ["src"]
    with pytest.raises(AdmissionError, match="unknown_connection_node"):
        raw_admit(system, graph)
