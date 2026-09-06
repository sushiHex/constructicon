"""The authored map is an ordered scalar binding claim, including at a Loop."""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.admission import AdmissionCode, AdmissionRejected
from constructicon.core.component import ComponentDef
from constructicon.core.errors import AdmissionError
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.identity import canonical_json
from constructicon.core.ports import NodePortAddress
from constructicon.runtime.validator import admit
from tests.conftest import BRIEF, ISSUE, SUMMARY, atomic, summarize_impl
from tests.runtime.test_loop_validator import CONTINUE


def membership_graph(
    system: Constructicon,
    *,
    selectors: tuple[str, ...] = ("a.brief", "b.brief"),
    destination_cardinality: str = "many",
    source_cardinality: str = "one",
    loop: bool = False,
) -> Graph:
    source = BRIEF.model_copy(update={"cardinality": source_cardinality})
    gather = BRIEF.model_copy(update={"name": "briefs", "cardinality": destination_cardinality})
    for name, inputs, outputs in (
        ("maps/source", (ISSUE,), (source,)),
        ("maps/gather", (gather,), (SUMMARY, CONTINUE) if loop else (SUMMARY,)),
    ):
        definition, impl = atomic(name, inputs, outputs, summarize_impl)
        version = system._register(definition, impl)
        system._promote_initial(component=name, version=version)
    ref = Ref(component="maps/gather")
    return Graph(
        name="membership",
        nodes=(
            GraphNode(id="a", body=Ref(component="maps/source")),
            GraphNode(id="b", body=Ref(component="maps/source")),
            GraphNode(
                id="gather",
                body=Loop(body=ref, feedback={}, continue_from="continue", max_iterations=1)
                if loop
                else ref,
            ),
        ),
        connections=tuple(
            Connection(src=selector.split(".")[0], dst="gather", map={"briefs": selector})
            for selector in selectors
        ),
        inputs=(ISSUE, BRIEF),
        outputs=(SUMMARY,),
    )


INPUTS = {"issue": {}, "brief": {"bystander": True}}


def raw_admit(system: Constructicon, graph: Graph):
    return admit(
        graph,
        snapshot=system._registry.snapshot(),
        catalog=system._catalog,
        capabilities=system._capabilities,
        root_grants=system._root_grants,
        inputs=INPUTS,
    )


@pytest.mark.parametrize("loop", [False, True])
@pytest.mark.parametrize(
    "selectors",
    [
        ("a.brief", "b.brief"),
        ("b.brief", "a.brief"),
        ("b.brief", "a.brief", "b.brief"),
    ],
)
def test_ordered_scalar_union_replaces_the_pool(
    system: Constructicon, loop: bool, selectors: tuple[str, ...]
) -> None:
    graph = membership_graph(system, selectors=selectors, loop=loop)
    manifest = system.validate(graph, INPUTS)
    assert raw_admit(system, graph) == manifest
    bindings = (
        manifest.resolved_loops[0].initial_bindings if loop else manifest.resolved_connections
    )
    binding = next(item for item in bindings if item.destination.port == "briefs")
    assert all(isinstance(source, NodePortAddress) for source in binding.sources)
    assert [
        str(source.node) for source in binding.sources if isinstance(source, NodePortAddress)
    ] == [selector.split(".")[0] for selector in dict.fromkeys(selectors)]
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert result.status == "accepted"
    assert canonical_json(result.manifest.model_dump(mode="json")) == canonical_json(
        manifest.model_dump(mode="json")
    )


@pytest.mark.parametrize("loop", [False, True])
@pytest.mark.parametrize("cardinality", ["one", "optional"])
def test_distinct_scalar_maps_still_refuse_a_non_many_destination(
    system: Constructicon, loop: bool, cardinality: str
) -> None:
    graph = membership_graph(system, loop=loop, destination_cardinality=cardinality)
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    fault = next(
        item for item in result.faults if item.details.get("defect") == "duplicate_map_destination"
    )
    assert fault.code == AdmissionCode.GRAPH_CONTRACT_INVALID
    assert fault.path == ("connections", 1, "map", "briefs")
    assert fault.details["destination_cardinality"] == cardinality
    assert fault.details["selector"] == "b.brief"
    assert fault.details["first_connection_index"] == 0
    assert fault.details["first_selector"] == "a.brief"
    assert "one distinct selector" in fault.repair
    with pytest.raises(AdmissionError, match="maps destination port 'briefs' twice"):
        system.validate(graph, INPUTS)
    with pytest.raises(AdmissionError, match="maps destination port 'briefs' twice"):
        raw_admit(system, graph)


@pytest.mark.parametrize("loop", [False, True])
@pytest.mark.parametrize("cardinality", ["many", "optional"])
def test_a_selector_is_not_a_collection_or_an_optional_seat(
    system: Constructicon, loop: bool, cardinality: str
) -> None:
    graph = membership_graph(
        system, selectors=("a.brief",), loop=loop, source_cardinality=cardinality
    )
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    fault = next(item for item in result.faults if item.details.get("selector") == "a.brief")
    assert fault.code == AdmissionCode.GRAPH_PORT_CONTRACT_MISMATCH
    assert fault.details["source_cardinality"] == cardinality
    assert "scalar adapter" in fault.repair
    with pytest.raises(AdmissionError, match="source cardinality"):
        raw_admit(system, graph)


@pytest.mark.parametrize("loop", [False, True])
def test_an_unused_map_destination_is_never_discarded(system: Constructicon, loop: bool) -> None:
    graph = membership_graph(system, selectors=("a.brief",), loop=loop)
    graph = graph.model_copy(
        update={"connections": (Connection(src="a", dst="gather", map={"renamed": "a.brief"}),)}
    )
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    fault = next(
        item for item in result.faults if item.details.get("defect") == "unused_map_destination"
    )
    assert fault.code == AdmissionCode.GRAPH_CONTRACT_INVALID
    assert fault.path == ("connections", 0, "map", "renamed")
    assert fault.details["destination_node"] == "gather"
    assert fault.details["destination_port"] == "renamed"
    with pytest.raises(AdmissionError, match="unused_map_destination"):
        raw_admit(system, graph)


def test_map_object_order_is_not_fault_order(system: Constructicon) -> None:
    graph = membership_graph(system, selectors=("a.brief",))
    results = []
    raw_faults = []
    for pairs in (("z", "a"), ("a", "z")):
        proposal = graph.model_copy(
            update={
                "connections": (
                    Connection(src="a", dst="gather", map={name: "a.brief" for name in pairs}),
                )
            }
        )
        result = system.admit_graph(proposal.model_dump_json(), INPUTS)
        assert isinstance(result, AdmissionRejected)
        results.append(canonical_json(result.model_dump(mode="json")))
        with pytest.raises(AdmissionError) as raw:
            raw_admit(system, proposal)
        raw_faults.append(canonical_json(raw.value.faults))
    assert results[0] == results[1]
    assert raw_faults[0] == raw_faults[1]


@pytest.mark.parametrize("wrapper", ["inline", "loop", "retained", "retained-inline"])
@pytest.mark.parametrize(
    ("defect", "cardinality"),
    [
        ("unused_map_destination", "many"),
        ("duplicate_map_destination", "one"),
        ("duplicate_map_destination", "optional"),
        ("malformed_selector", "many"),
    ],
)
def test_map_coordinates_follow_the_bytes_that_own_them(
    system: Constructicon,
    wrapper: str,
    defect: str,
    cardinality: str,
) -> None:
    duplicate = defect == "duplicate_map_destination"
    inner = membership_graph(
        system,
        selectors=("a.brief", "a.brief", "b.brief") if duplicate else ("a.brief",),
        destination_cardinality=cardinality,
    )
    destination = "lost" if defect == "unused_map_destination" else "briefs"
    if not duplicate:
        selector = "foo" if defect == "malformed_selector" else "a.brief"
        inner = inner.model_copy(
            update={
                "connections": (Connection(src="a", dst="gather", map={destination: selector}),)
            }
        )
    # A repeated first selector coalesces; the third entry introduces the conflict.
    coordinate = ("connections", 2 if duplicate else 0, "map", destination)
    expected = ("nodes", 0, "body", *coordinate)
    definition_version = None
    if wrapper == "loop":
        definition, impl = atomic("maps/continue", (), (CONTINUE,), summarize_impl)
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
        body = Loop(body=inner, feedback={}, continue_from="continue", max_iterations=1)
        expected = ("nodes", 0, "body", "body", *coordinate)
    elif wrapper.startswith("retained"):
        if wrapper == "retained-inline":
            inner = Graph(
                name="nested",
                nodes=(GraphNode(id="inner", body=inner),),
                inputs=inner.inputs,
                outputs=inner.outputs,
            )
        definition = ComponentDef(
            name="maps/composite",
            role="component",
            body=inner,
            inputs=inner.inputs,
            outputs=inner.outputs,
        )
        definition_version = system._register(definition)
        system._promote_initial(component=definition.name, version=definition_version)
        body = Ref(component=definition.name)
        expected = (
            "body",
            *(("nodes", 0, "body") if wrapper == "retained-inline" else ()),
            *coordinate,
        )
    else:
        body = inner
    graph = Graph(
        name="root/with: punctuation",
        nodes=(GraphNode(id="nested/instance", body=body),),
        inputs=inner.inputs,
        outputs=(SUMMARY,),
    )
    rejected = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(rejected, AdmissionRejected)
    fault = next(item for item in rejected.faults if item.details.get("defect") == defect)
    assert fault.scope is not None
    assert fault.scope.segments[:2] == ("root/with: punctuation", "nested/instance")
    if definition_version is None:
        assert fault.path == expected
        assert "component" not in fault.details
    else:
        assert fault.path == ()
        assert fault.details["component"] == "maps/composite"
        assert fault.details["version"] == str(definition_version)
        assert fault.details["definition_path"] == list(expected)
    with pytest.raises(AdmissionError, match=defect):
        raw_admit(system, graph)


@pytest.mark.parametrize("loop", [False, True])
@pytest.mark.parametrize("selector", ["foo", "a.", "$input", "$input.", ""])
def test_malformed_selector_gets_a_grammar_repair(
    system: Constructicon, loop: bool, selector: str
) -> None:
    graph = membership_graph(system, selectors=("a.brief",), loop=loop)
    graph = graph.model_copy(
        update={"connections": (Connection(src="a", dst="gather", map={"briefs": selector}),)}
    )
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    fault = next(item for item in result.faults if item.details.get("selector") == selector)
    assert fault.code == AdmissionCode.GRAPH_CONTRACT_INVALID
    assert fault.details["defect"] == "malformed_selector"
    assert fault.path == ("connections", 0, "map", "briefs")
    assert "must be 'node.port' or '$input.port'" in fault.message
    assert "non-empty port segment" in fault.repair
    assert "node.port" in fault.repair and "$input.port" in fault.repair
    assert "scalar adapter" not in fault.repair
    assert "resolved_count" not in fault.details
    with pytest.raises(AdmissionError, match=r"must be 'node\.port'"):
        raw_admit(system, graph)


@pytest.mark.parametrize("selector", ["a.missing", "$input.missing", "a.issue"])
def test_zero_resolved_sources_is_a_selector_contract_fault(
    system: Constructicon, selector: str
) -> None:
    graph = membership_graph(system, selectors=("a.brief",))
    graph = graph.model_copy(
        update={"connections": (Connection(src="a", dst="gather", map={"briefs": selector}),)}
    )
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    fault = next(item for item in result.faults if item.details.get("selector") == selector)
    assert fault.code == AdmissionCode.GRAPH_PORT_CONTRACT_MISMATCH
    assert fault.details["resolved_count"] == 0
    with pytest.raises(AdmissionError, match="resolves to 0 sources"):
        raw_admit(system, graph)


def test_a_composite_selector_cannot_flatten_multiple_producers(system: Constructicon) -> None:
    graph = membership_graph(system, selectors=("a.brief",))
    inner = Graph(
        name="two",
        nodes=(
            GraphNode(id="left", body=Ref(component="maps/source")),
            GraphNode(id="right", body=Ref(component="maps/source")),
        ),
        inputs=(ISSUE,),
        outputs=(BRIEF.model_copy(update={"cardinality": "many"}),),
    )
    graph = graph.model_copy(update={"nodes": (GraphNode(id="a", body=inner), *graph.nodes[1:])})
    result = system.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    fault = next(item for item in result.faults if item.details.get("selector") == "a.brief")
    assert fault.code == AdmissionCode.GRAPH_PORT_CONTRACT_MISMATCH
    assert fault.details["resolved_count"] == 2
    with pytest.raises(AdmissionError, match="resolves to 2 sources"):
        raw_admit(system, graph)
