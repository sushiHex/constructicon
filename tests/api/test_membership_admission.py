"""M7.1's new admission claims and its deliberately stronger override law."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import ValidationError

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId, ScopePath
from constructicon.core.admission import AdmissionCode, AdmissionRejected
from constructicon.core.component import CapabilityRequirement
from constructicon.core.control import (
    ControlCode,
    ControlRejected,
    ResolutionLock,
    ResolutionPin,
    RunSubmission,
)
from constructicon.core.errors import AdmissionError
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import canonical_json, digest
from constructicon.core.introspection import (
    DESCRIPTION_SCHEMA_VERSION,
    AdmissionLimits,
    SystemDescription,
)
from constructicon.core.manifest import manifest_hash_for, source_graph_hash_for
from constructicon.core.ports import Port
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import (
    SEAMS,
    _crash_at,
    _fresh_control,
    _PassiveHost,
    _terminal_response_bytes,
)
from tests.api.test_counterfactual import ACTOR, _PassiveRunHost
from tests.conftest import BRIEF, ISSUE, FakeClock, InjectedCrash, atomic, summarize_impl
from tests.runtime.test_explicit_membership import membership_graph


class _V1Description(SystemDescription):
    # The published version field alone must make even this permissive
    # approximation of a strict old reader reject the new document.
    schema_version: Literal[1] = 1  # type: ignore[assignment]


def test_description_preserves_both_membership_laws(system: Constructicon) -> None:
    description = system.describe()
    payload = description.model_dump(mode="json")
    assert description.schema_version == DESCRIPTION_SCHEMA_VERSION == 3
    assert description.graph_schema.version == description.admission_schema.version == 1
    assert payload["authoring"]["bindings"]["explicit_map_source_cardinality"] == "one"
    assert payload["authoring"]["bindings"]["mapped_many_policy"] == (
        "ordered_scalar_selector_union_replaces_pool"
    )
    assert SystemDescription.model_validate_json(description.model_dump_json()) == description
    with pytest.raises(ValidationError):
        _V1Description.model_validate(payload)
    body = {key: value for key, value in payload.items() if key != "description_digest"}
    assert description.description_digest == digest("system-description", 3, body)
    assert description.description_digest != digest("system-description", 1, body)
    for field in ("explicit_map_source_cardinality", "mapped_many_policy"):
        changed = description.model_dump(mode="json", exclude={"description_digest"})
        del changed["authoring"]["bindings"][field]
        assert digest("system-description", 3, changed) != description.description_digest


@pytest.mark.parametrize("nested", [False, True])
def test_preflight_inspects_the_exact_pin_not_current_stable(
    system: Constructicon,
    nested: bool,
) -> None:
    compatible, impl = atomic("pins/member", (ISSUE,), (BRIEF,), summarize_impl)
    version_a = system._register(
        compatible.model_copy(update={"capability_requirements": ()}), impl
    )
    incompatible = compatible.model_copy(
        update={
            "capability_requirements": (
                CapabilityRequirement(alias="unavailable", kind="executor"),
            )
        }
    )
    version_b = system._register(incompatible, impl)
    system._promote_initial(component=compatible.name, version=version_b)
    inner = Graph(
        name="inner",
        nodes=(GraphNode(id="member", body=Ref(component=compatible.name)),),
        inputs=(ISSUE,),
        outputs=(BRIEF,),
    )
    graph = (
        Graph(
            name="outer",
            nodes=(GraphNode(id="nested", body=inner),),
            inputs=inner.inputs,
            outputs=inner.outputs,
        )
        if nested
        else inner
    )
    scope = ScopePath(segments=("outer", "nested", "member") if nested else ("inner", "member"))
    lock = ResolutionLock(
        source_manifest_hash=digest("fixture", 1, {}),
        pins=(ResolutionPin(scope=scope, component=compatible.name, version=version_a),),
    )
    with pytest.raises(AdmissionError) as caught:
        system.validate(graph, {"issue": {}})
    assert caught.value.faults[0].code == AdmissionCode.GRAPH_CAPABILITY_MISSING_BINDING
    try:
        manifest = system.validate(graph, {"issue": {}}, resolution_lock=lock)
    except AdmissionError as exc:
        pytest.fail(f"the compatible pinned version must admit independently of stable: {exc}")
    assert manifest.resolved_components[0].resolved_version == version_a
    # No missing or mismatched lock may acquire authority from B's preflight.
    for pins in ((), (lock.pins[0].model_copy(update={"component": "other"}),)):
        with pytest.raises(AdmissionError) as missing:
            system.validate(
                graph, {"issue": {}}, resolution_lock=lock.model_copy(update={"pins": pins})
            )
        assert all(
            item.code != AdmissionCode.GRAPH_CAPABILITY_MISSING_BINDING
            for item in missing.value.faults
        )


@pytest.mark.parametrize("extra", ["output", "optional_input"])
@pytest.mark.parametrize("detail_limit", [1, 25])
async def test_counterfactual_preserves_the_whole_boundary_at_every_affected_scope(
    system: Constructicon,
    journal: SqliteJournal,
    extra: str,
    detail_limit: int,
) -> None:
    system._admission_limits = AdmissionLimits(max_fault_detail_items=detail_limit)
    graph = membership_graph(system)
    inputs = {"issue": {}, "brief": {}}
    source = system.validate(graph, inputs)
    source_id = RunId(f"boundary-{extra}")
    system._prepare_run(source, run_id=source_id, inputs=inputs)
    retained = journal.snapshot().get("maps/source", source.resolved_components[0].resolved_version)
    assert retained is not None
    spare = Port(name="spare", type_id="test/Spare", schema_hash="s1", cardinality="optional")
    changed, impl = atomic(
        "maps/source",
        (*retained.definition.inputs, spare)
        if extra == "optional_input"
        else retained.definition.inputs,
        (*retained.definition.outputs, spare) if extra == "output" else retained.definition.outputs,
        summarize_impl,
    )
    version = system._register(changed, impl)
    # Every consumed input/output still binds; admission alone cannot prove
    # the M6 promise. Use an exact ref to test that fact without moving stable.
    modified = graph.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(update={"body": Ref(component="maps/source", version=str(version))})
                if str(node.id) in {"a", "b"}
                else node
                for node in graph.nodes
            ),
            "outputs": (),
        }
    )
    system.validate(modified, inputs)
    host = _PassiveRunHost(system, journal=journal)
    control = ControlPlane(system=system, store=journal, run_host=host)
    before = canonical_json(source.model_dump(mode="json"))
    responses = []
    for _ in range(2):
        result = await control.runs_counterfactual(
            ACTOR,
            source_run_id=source_id,
            overrides={"maps/source": version},
            idempotency_key="change",
        )
        assert isinstance(result, ControlRejected)
        fault = result.faults[0]
        assert fault.code == ControlCode.COUNTERFACTUAL_LOCK_MISMATCH
        assert fault.details["affected_total"] == 2
        assert [item["scope"] for item in fault.details["affected_scopes"]] == [
            ["membership", "a"],
            ["membership", "b"],
        ][:detail_limit]
        assert fault.details["truncated"] == (detail_limit < 2)
        responses.append(_terminal_response_bytes(journal, "runs_counterfactual"))
    assert responses[0] == responses[1]
    assert len(journal.run_records(limit=100)) == 1
    assert canonical_json(system.manifest_for_run(source_id).model_dump(mode="json")) == before
    await control.shutdown()


async def test_rejected_start_replays_and_repair_requires_a_fresh_key(
    system: Constructicon,
    journal: SqliteJournal,
) -> None:
    graph = membership_graph(system, selectors=("a.brief",), source_cardinality="many")
    inputs = {"issue": {}, "brief": {}}
    control = _fresh_control(system, journal, "map-rejection", run_host=_PassiveHost())
    for _ in range(2):
        result = await control.runs_start(
            ACTOR, proposal=graph, inputs=inputs, idempotency_key="bad"
        )
        assert isinstance(result, AdmissionRejected)
        assert result.faults[0].code == AdmissionCode.GRAPH_PORT_CONTRACT_MISMATCH
    assert journal.run_records(limit=100) == []
    repaired = graph.model_copy(
        update={
            "connections": tuple(
                connection.model_copy(update={"map": {}}) for connection in graph.connections
            )
        }
    )
    conflict = await control.runs_start(
        ACTOR, proposal=repaired, inputs=inputs, idempotency_key="bad"
    )
    assert isinstance(conflict, ControlRejected)
    assert conflict.faults[0].code == ControlCode.IDEMPOTENCY_CONFLICT
    accepted = await control.runs_start(
        ACTOR, proposal=repaired, inputs=inputs, idempotency_key="repaired"
    )
    assert isinstance(accepted, RunSubmission)
    assert len(journal.run_records(limit=100)) == 1
    await control.shutdown()


@pytest.mark.parametrize("seam", SEAMS)
async def test_compatible_override_recovers_every_command_seam(
    system: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
    seam: str,
) -> None:
    graph = membership_graph(system)
    inputs = {"issue": {}, "brief": {}}
    source = system.validate(graph, inputs)
    source_id = RunId("mapped-counterfactual-source")
    system._prepare_run(source, run_id=source_id, inputs=inputs)
    retained = journal.snapshot().get("maps/source", source.resolved_components[0].resolved_version)
    assert retained is not None
    # An authority declaration can change without changing a data contract.
    compatible = retained.definition.model_copy(update={"capability_requirements": ()})
    version = system._register(compatible, summarize_impl)
    first = _fresh_control(
        system,
        journal,
        "seam-a",
        run_host=_PassiveHost(),
        fault_probe=_crash_at("runs_counterfactual", seam),
    )
    with pytest.raises(InjectedCrash):
        await first.runs_counterfactual(
            ACTOR,
            source_run_id=source_id,
            overrides={"maps/source": version},
            idempotency_key="override",
        )
    clock.advance(31)
    second = _fresh_control(system, journal, "seam-b", run_host=_PassiveHost())
    recovered = await second.runs_counterfactual(
        ACTOR,
        source_run_id=source_id,
        overrides={"maps/source": version},
        idempotency_key="override",
    )
    assert isinstance(recovered, RunSubmission)
    final = system.manifest_for_run(recovered.run_id)
    for resolution in final.resolved_components:
        if resolution.component == "maps/source":
            assert resolution.resolved_version == version
    assert len(journal.run_records(limit=100)) == 2
    recorded = _terminal_response_bytes(journal, "runs_counterfactual")
    replay = await second.runs_counterfactual(
        ACTOR,
        source_run_id=source_id,
        overrides={"maps/source": version},
        idempotency_key="override",
    )
    assert isinstance(replay, RunSubmission) and replay.command.replayed
    assert _terminal_response_bytes(journal, "runs_counterfactual") == recorded
    await first.shutdown()
    await second.shutdown()


async def test_unmapped_history_does_not_acquire_an_invented_membership_claim(
    system: Constructicon,
    journal: SqliteJournal,
) -> None:
    graph = membership_graph(system)
    unrelated = Port(name="unrelated", type_id="legacy/Unrelated", schema_hash="s1")
    drifted, impl = atomic("legacy/drifted", (ISSUE,), (unrelated,), summarize_impl)
    version = system._register(drifted, impl)
    system._promote_initial(component=drifted.name, version=version)
    graph = graph.model_copy(
        update={
            "nodes": (GraphNode(id="a", body=Ref(component=drifted.name)), *graph.nodes[1:]),
            "connections": tuple(
                connection.model_copy(update={"map": {}}) for connection in graph.connections
            ),
            "inputs": (ISSUE,),
        }
    )
    inputs = {"issue": {}}
    source = system.validate(graph, inputs)
    gather = next(
        binding for binding in source.resolved_connections if binding.destination.port == "briefs"
    )
    assert [source.node for source in gather.sources] == ["b"]
    source_id = RunId("legacy-unmapped")
    system._prepare_run(source, run_id=source_id, inputs=inputs)
    control = _fresh_control(system, journal, "legacy", run_host=_PassiveHost())
    for operation in ("runs_reproduce", "runs_counterfactual"):
        kwargs = {"overrides": {}} if operation == "runs_counterfactual" else {}
        result = await getattr(control, operation)(
            ACTOR, source_run_id=source_id, idempotency_key=operation, **kwargs
        )
        assert isinstance(result, RunSubmission)
        final = system.manifest_for_run(result.run_id)
        assert final.source_graph == graph
        assert final.resolved_connections == source.resolved_connections
    await control.shutdown()


@pytest.mark.parametrize("overridden", [False, True])
async def test_retained_non_scalar_map_is_baseline_invalid_not_an_override_mismatch(
    system: Constructicon,
    journal: SqliteJournal,
    overridden: bool,
) -> None:
    graph = membership_graph(system, selectors=("a.brief",), source_cardinality="many")
    graph = graph.model_copy(update={"inputs": (ISSUE,)})
    inputs = {"issue": {}}
    unmapped = graph.model_copy(
        update={
            "connections": tuple(
                connection.model_copy(update={"map": {}}) for connection in graph.connections
            )
        }
    )
    # The pre-M7.1 validator admitted this accidental shape. Its single
    # producer binding equals the unmapped fixture; preserve that retained
    # manifest and Graph rather than weakening current admission for a test.
    retained = system.validate(unmapped, inputs).model_copy(
        update={
            "source_graph": graph,
            "source_graph_hash": source_graph_hash_for(graph),
        }
    )
    retained = retained.model_copy(update={"manifest_hash": manifest_hash_for(retained)})
    source_id = RunId("old-non-scalar-map")
    system._prepare_run(retained, run_id=source_id, inputs=inputs)
    host = _PassiveRunHost(system, journal=journal)
    control = ControlPlane(system=system, store=journal, run_host=host)
    overrides = (
        {"maps/source": retained.resolved_components[0].resolved_version} if overridden else {}
    )
    responses = []
    for _ in range(2):
        result = await control.runs_counterfactual(
            ACTOR,
            source_run_id=source_id,
            overrides=overrides,
            idempotency_key="historical",
        )
        assert isinstance(result, ControlRejected)
        fault = result.faults[0]
        assert fault.code == ControlCode.REQUEST_INVALID
        assert "runs_reproduce" in fault.repair and "re-author" in fault.repair
        assert (
            fault.details["admission_faults"][0]["code"]
            == AdmissionCode.GRAPH_PORT_CONTRACT_MISMATCH
        )
        responses.append(_terminal_response_bytes(journal, "runs_counterfactual"))
    assert responses[0] == responses[1]
    assert len(journal.run_records(limit=100)) == 1
    assert system.manifest_for_run(source_id) == retained
    await control.shutdown()
