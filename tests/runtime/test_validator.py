"""Admission compiles magnetic intent into a sealed manifest — deterministically,
with itemized repair-naming faults, never a guess (I11, I13)."""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.component import ComponentDef
from constructicon.core.errors import AdmissionError
from constructicon.core.grants import GrantRequest, Posture
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.manifest import ExecutionManifest
from constructicon.core.ports import NodePortAddress, Port
from tests.conftest import ANNOUNCED, BRIEF, ISSUE, SUMMARY, atomic, pipeline_graph, summarize_impl

INPUTS = {"issue": {"title": "retry loop is flaky"}}


def test_admission_produces_a_sealed_manifest(world: Constructicon) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)
    assert isinstance(manifest, ExecutionManifest)
    resolved = {tuple(r.scope.segments): r.component for r in manifest.resolved_components}
    assert resolved[("issue-to-summary", "triage")] == "test/triage"
    # summarize pulls `brief` from triage two steps upstream — cross-node magnetism
    binding = next(
        b
        for b in manifest.resolved_connections
        if isinstance(b.destination, NodePortAddress)
        and b.destination.node == "summarize"
        and b.destination.port == "brief"
    )
    source = binding.sources[0]
    assert isinstance(source, NodePortAddress) and source.node == "triage"


def test_manifest_hashes_are_stable_and_input_scoped(world: Constructicon) -> None:
    first = world.validate(pipeline_graph(), INPUTS)
    second = world.validate(pipeline_graph(), INPUTS)
    assert first.manifest_hash == second.manifest_hash
    other = world.validate(pipeline_graph(), {"issue": {"title": "different"}})
    assert other.world_hash == first.world_hash
    assert other.input_hash != first.input_hash


def test_ambiguity_is_an_itemized_error_never_a_rebind(world: Constructicon) -> None:
    graph = pipeline_graph()
    # a second producer of test/Brief converts a valid graph into an error
    clone_def, clone_impl = atomic("test/triage-b", (ISSUE,), (BRIEF,), summarize_impl)
    version = world.register(clone_def, clone_impl)
    world.promote_initial(component="test/triage-b", version=version)
    ambiguous = Graph(
        name=graph.name,
        nodes=(
            *graph.nodes,
            GraphNode(id="triage_b", body=Ref(component="test/triage-b")),
        ),
        connections=(*graph.connections, Connection(src="triage_b", dst="summarize")),
        inputs=graph.inputs,
        outputs=graph.outputs,
    )
    with pytest.raises(
        AdmissionError, match=r"exact-name match must be unique|ambiguity is an error"
    ):
        world.validate(ambiguous, INPUTS)


def test_gather_records_the_complete_producer_set(world: Constructicon) -> None:
    gather_port = Port(
        name="briefs", type_id="test/Brief", schema_hash="s1", cardinality="many"
    )
    collect_def, collect_impl = atomic("test/collect", (gather_port,), (SUMMARY,), summarize_impl)
    version = world.register(collect_def, collect_impl)
    world.promote_initial(component="test/collect", version=version)
    clone_def, clone_impl = atomic("test/triage-b", (ISSUE,), (BRIEF,), summarize_impl)
    v2 = world.register(clone_def, clone_impl)
    world.promote_initial(component="test/triage-b", version=v2)
    graph = Graph(
        name="gathering",
        nodes=(
            GraphNode(
                id="a", body=Ref(component="test/triage", bind={"executor": "fake-executor"})
            ),
            GraphNode(id="b", body=Ref(component="test/triage-b")),
            GraphNode(id="collect", body=Ref(component="test/collect")),
        ),
        connections=(
            Connection(src="a", dst="collect"),
            Connection(src="b", dst="collect"),
        ),
        inputs=(ISSUE,),
        outputs=(SUMMARY,),
    )
    manifest = world.validate(graph, INPUTS)
    binding = next(
        b
        for b in manifest.resolved_connections
        if isinstance(b.destination, NodePortAddress) and b.destination.port == "briefs"
    )
    assert len(binding.sources) == 2


def test_missing_type_names_the_available_pool(world: Constructicon) -> None:
    graph = Graph(
        name="broken",
        nodes=(GraphNode(id="announce", body=Ref(component="test/announce")),),
        inputs=(ISSUE,),
        outputs=(ANNOUNCED,),
    )
    with pytest.raises(AdmissionError, match="no upstream output of type 'test/Brief'"):
        world.validate(graph, INPUTS)


def test_grants_only_narrow(world: Constructicon) -> None:
    graph = pipeline_graph()
    widened = Graph(
        name=graph.name,
        nodes=(
            GraphNode(
                id="triage",
                body=Ref(
                    component="test/triage",
                    bind={"executor": "fake-executor"},
                    grants=GrantRequest(posture=Posture.WRITE),
                ),
            ),
            *graph.nodes[1:],
        ),
        connections=graph.connections,
        inputs=graph.inputs,
        outputs=graph.outputs,
    )
    with pytest.raises(AdmissionError, match="only narrow"):
        world.validate(widened, INPUTS)


def test_unknown_capability_is_itemized(world: Constructicon) -> None:
    graph = pipeline_graph()
    broken = Graph(
        name=graph.name,
        nodes=(
            GraphNode(
                id="triage",
                body=Ref(component="test/triage", bind={"executor": "no-such-capability"}),
            ),
            *graph.nodes[1:],
        ),
        connections=graph.connections,
        inputs=graph.inputs,
        outputs=graph.outputs,
    )
    with pytest.raises(AdmissionError, match=r"unknown capability 'no-such-capability'"):
        world.validate(broken, INPUTS)


def test_loop_contract_faults_are_itemized(world: Constructicon) -> None:
    graph = Graph(
        name="looped",
        nodes=(
            GraphNode(
                id="loop",
                body=Loop(
                    body=Ref(component="test/summarize"),
                    feedback={"brief": "summary"},
                    continue_from="summary",
                    max_iterations=3,
                ),
            ),
        ),
        inputs=(BRIEF,),
        outputs=(),
    )
    with pytest.raises(AdmissionError, match="continuation output"):
        world.validate(graph, {"brief": {"title": "x"}})


def test_composite_flattens_with_distinct_nested_scopes(world: Constructicon) -> None:
    inner = pipeline_graph()
    composite = ComponentDef(
        name="test/pipeline",
        role="workflow",
        body=inner,
        inputs=(ISSUE,),
        outputs=inner.outputs,
    )
    version = world.register(composite)
    world.promote_initial(component="test/pipeline", version=version)
    outer = Graph(
        name="outer",
        nodes=(GraphNode(id="pipeline", body=Ref(component="test/pipeline")),),
        inputs=(ISSUE,),
        outputs=inner.outputs,
    )
    manifest = world.validate(outer, INPUTS)
    scopes = {tuple(r.scope.segments) for r in manifest.resolved_components}
    # nested instances carry the full scope chain — duplicates stay distinct
    assert ("outer", "pipeline", "triage") in scopes
