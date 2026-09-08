"""Panel maps prove the authored result seats, not an unstated whole boundary."""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.admission import AdmissionCode, AdmissionRejected
from constructicon.core.graph import Graph
from constructicon.core.identity import canonical_json
from constructicon.sdk import panel
from constructicon.sdk.types import DefinitionBundle
from tests.conftest import atomic, summarize_impl
from tests.sdk.test_combinators import _promote_all, panel_no, panel_tally, panel_yes

INPUTS = {"request": {"question": "ship?"}, "quorum": {"required": 1}}


def test_panel_selectors_are_representable_before_constructing_a_graph() -> None:
    with pytest.raises(ValueError, match="dot-free"):
        panel(
            "selectors", panel_yes, panel_yes, aggregator=panel_tally, ids=("first.dot", "second")
        )
    empty = DefinitionBundle(
        panel_yes.definition.model_copy(
            update={
                "outputs": (panel_yes.definition.outputs[0].model_copy(update={"name": ""}),),
            }
        ),
        panel_yes.implementation,
    )
    with pytest.raises(ValueError, match="non-empty member result-port name"):
        panel("selectors", empty, empty, aggregator=panel_tally)
    generated = panel("selectors", panel_yes, panel_yes, aggregator=panel_tally)
    assert isinstance(generated.definition.body, Graph)
    assert all("." not in connection.src for connection in generated.definition.body.connections)


@pytest.mark.parametrize(
    "drift",
    [
        "member_type",
        "member_name",
        "member_policy",
        "member_many",
        "member_optional",
        "gather_name",
        "gather_type",
        "gather_one",
        "gather_optional",
    ],
)
def test_stable_result_drift_cannot_silently_lose_a_panel_seat(
    system: Constructicon,
    drift: str,
) -> None:
    authored = panel("seats", panel_yes, panel_no, aggregator=panel_tally)
    member_drift = drift.startswith("member")
    target = panel_yes if member_drift else panel_tally
    _promote_all(system, panel_no, panel_tally if member_drift else panel_yes)
    ports = list(target.definition.outputs if member_drift else target.definition.inputs)
    if drift.endswith("policy"):
        ports[0] = panel_tally.definition.inputs[1].model_copy(update={"name": ports[0].name})
    elif drift.endswith("type"):
        ports[0] = ports[0].model_copy(update={"type_id": "other/Nominal"})
    elif drift.endswith("name"):
        ports[0] = ports[0].model_copy(update={"name": "ballots"})
    else:
        ports[0] = ports[0].model_copy(update={"cardinality": drift.split("_")[1]})
    changed, impl = atomic(
        target.name,
        target.definition.inputs if member_drift else tuple(ports),
        tuple(ports) if member_drift else target.definition.outputs,
        summarize_impl,
    )
    version = system._register(changed, impl)
    system._promote_initial(component=target.name, version=version)
    result = system.admit_graph(authored.definition.body.model_dump_json(), INPUTS)
    assert isinstance(result, AdmissionRejected)
    if drift == "gather_name":
        assert any(
            fault.details.get("defect") == "unused_map_destination" for fault in result.faults
        )
    elif drift in {"gather_one", "gather_optional"}:
        assert any(
            "maps destination port 'votes' twice" in fault.message for fault in result.faults
        )
    else:
        fault = next(
            item for item in result.faults if item.details.get("destination_port") == "votes"
        )
        assert fault.code == AdmissionCode.GRAPH_PORT_CONTRACT_MISMATCH


@pytest.mark.parametrize(
    "drift", ["input_contract", "input_optional", "input_many", "extra_output"]
)
def test_result_maps_do_not_claim_an_unstated_boundary(system: Constructicon, drift: str) -> None:
    authored = panel("limited", panel_yes, panel_no, aggregator=panel_tally)
    _promote_all(system, panel_no, panel_tally)
    inputs, outputs = panel_yes.definition.inputs, panel_yes.definition.outputs
    if drift == "input_contract":
        inputs = (panel_tally.definition.inputs[1],)
    elif drift.startswith("input"):
        inputs = (inputs[0].model_copy(update={"cardinality": drift.split("_")[1]}),)
    else:
        outputs = (*outputs, inputs[0].model_copy(update={"name": "unused"}))
    changed, impl = atomic(panel_yes.name, inputs, outputs, summarize_impl)
    version = system._register(changed, impl)
    system._promote_initial(component=panel_yes.name, version=version)
    result = system.admit_graph(authored.definition.body.model_dump_json(), INPUTS)
    assert result.status == "accepted"


def test_undrifted_maps_preserve_every_binding_byte_and_source_order(system: Constructicon) -> None:
    _promote_all(system, panel_yes, panel_no, panel_tally)
    graph = panel("unchanged", panel_yes, panel_no, aggregator=panel_tally).definition.body
    assert isinstance(graph, Graph)
    unmapped = graph.model_copy(
        update={
            "connections": tuple(
                connection.model_copy(update={"map": {}}) for connection in graph.connections
            )
        }
    )
    prior = system.validate(unmapped, INPUTS)
    mapped = system.validate(graph, INPUTS)
    assert canonical_json(prior.resolved_connections) == canonical_json(mapped.resolved_connections)
    assert mapped.source_graph_hash != prior.source_graph_hash
