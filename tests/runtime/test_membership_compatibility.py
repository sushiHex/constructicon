"""Complete canonical-manifest fingerprints captured on the pre-M7.1 code.

Base: 8262d4fd614028ebb0b41b77ef124ff47afcc5dc. Reuse the actual existing
acceptance fixtures, rather than copies that could cease to exercise them.
"""

from __future__ import annotations

import hashlib

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.admission import AdmissionAccepted, AdmissionRejected
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.identity import canonical_json
from tests.conftest import ISSUE, SUMMARY
from tests.e2e.test_architect_repair import test_architect_repairs_json_and_executes as _architect
from tests.e2e.test_blocking import diamond_graph, diamond_world
from tests.runtime.test_loop_validator import (
    test_explicit_map_disambiguates_the_loop_boundary as _loop,
)
from tests.runtime.test_validator import (
    INPUTS,
)
from tests.runtime.test_validator import (
    test_admission_produces_a_sealed_manifest as _pipeline,
)
from tests.runtime.test_validator import (
    test_gather_records_the_complete_producer_set as _gather,
)

GOLDENS = {
    "issue-to-summary": "1508916163e3fdd30398315e9e6a4688fdd241137948d1b165d1e07e1c10b8bc",
    "gathering": "1d4b082e496ff3c999998fec4ddb34ddedd97e9ed841fff3e72247a17989dd10",
    "mapped-loop": "28481e993522e4598f3e16facd10da801ae1f5853869280bd7e60de8d7eda5bf",
    "architect-selection": "723247d86f139df990dba161133bd0d1f947995be686feec817522e75bf23d3c",
    "diamond": "3f2f6b3b13ddb79a5248e587c14f82625acd08c2e6262711374edd0844b0b36d",
}


def empty_node_graph() -> Graph:
    return Graph(
        name="empty-node-selector",
        nodes=(
            GraphNode(id="", body=Ref(component="test/triage", bind={"executor": "fake-executor"})),
            GraphNode(id="summarize", body=Ref(component="test/summarize")),
        ),
        connections=(Connection(src="", dst="summarize", map={"brief": ".brief"}),),
        inputs=(ISSUE,),
        outputs=(SUMMARY,),
    )


def test_empty_node_selector_preserves_the_base_manifest(world: Constructicon) -> None:
    graph = empty_node_graph()
    result = world.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionAccepted)
    binding = next(
        item for item in result.manifest.resolved_connections if item.destination.port == "brief"
    )
    assert len(binding.sources) == 1
    assert binding.sources[0].model_dump(mode="json") == {
        "kind": "node_port",
        "scope": {"segments": [graph.name]},
        "node": "",
        "port": "brief",
    }
    # Captured from the pre-M7.1 validator at 8262d4f, not from current admission.
    assert hashlib.sha256(
        canonical_json(result.manifest.model_dump(mode="json")).encode()
    ).hexdigest() == ("1047e60c004044d6efe04fb866d01cd187c8fc366cab45107ff2d7cd3edc170e")


def test_empty_node_selector_without_its_node_is_a_missing_source(world: Constructicon) -> None:
    graph = empty_node_graph()
    graph = graph.model_copy(
        update={
            "nodes": (graph.nodes[0].model_copy(update={"id": "triage"}), graph.nodes[1]),
            "connections": (Connection(src="triage", dst="summarize", map={"brief": ".brief"}),),
        }
    )
    result = world.admit_graph(graph.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    fault = next(item for item in result.faults if item.details.get("selector") == ".brief")
    assert fault.details["defect"] == "explicit_source_contract"
    assert fault.details["resolved_count"] == 0


@pytest.mark.parametrize("name", GOLDENS)
async def test_existing_manifest_bytes_are_unchanged(
    world: Constructicon,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    original = world.validate
    observed = []

    def fingerprint(graph, inputs, **kwargs):
        manifest = original(graph, inputs, **kwargs)
        if graph.name == name:
            observed.append(
                hashlib.sha256(
                    canonical_json(manifest.model_dump(mode="json")).encode()
                ).hexdigest()
            )
        return manifest

    monkeypatch.setattr(world, "validate", fingerprint)
    if name == "issue-to-summary":
        _pipeline(world)
    elif name == "gathering":
        _gather(world)
    elif name == "mapped-loop":
        _loop(world)
    elif name == "architect-selection":
        await _architect(world)
    else:
        diamond_world(world).validate(diamond_graph(), INPUTS)
    assert observed and set(observed) == {GOLDENS[name]}
