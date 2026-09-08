"""New starts refuse bad endpoints; historical runs retain their sealed behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.admission import AdmissionRejected
from constructicon.core.control import ControlCode, ControlRejected, RunSubmission
from constructicon.core.identity import canonical_json
from constructicon.core.manifest import ExecutionManifest, manifest_hash_for
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import (
    _crash_at,
    _fresh_control,
    _PassiveHost,
    _terminal_response_bytes,
)
from tests.api.test_counterfactual import ACTOR
from tests.conftest import FakeClock, InjectedCrash
from tests.runtime.test_connection_endpoints import INPUTS, PATHS, SCOPES, WRAPPERS, endpoint_graph


@pytest.mark.parametrize("wrapper", WRAPPERS)
@pytest.mark.parametrize("overridden", [False, True])
async def test_historical_endpoint_fault_is_baseline_invalid_and_reproduce_stays_exact(
    system: Constructicon,
    journal: SqliteJournal,
    wrapper: str,
    overridden: bool,
) -> None:
    graph = endpoint_graph(system, wrapper=wrapper)
    # Real output of the committed PR A validator, captured before PR B's
    # endpoint checks existed. CI never weakens admission to mint its evidence.
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures/m71/ghost-endpoint-manifests.json").read_text()
    )
    assert fixture["writer_commit"] == "b5ff31f362ded8d486e8473a9cb23c2cffba661b"
    retained = ExecutionManifest.model_validate(fixture["manifests"][wrapper])
    assert retained.manifest_hash == manifest_hash_for(retained)
    assert canonical_json(retained.source_graph.model_dump(mode="json")) == canonical_json(
        graph.model_dump(mode="json")
    )
    source_id = RunId("historical-endpoints")
    system._prepare_run(retained, run_id=source_id, inputs=INPUTS)
    before = canonical_json(retained.model_dump(mode="json"))
    host = _PassiveHost()
    control = _fresh_control(system, journal, "endpoint-history", run_host=host)
    overrides = (
        {"maps/source": system._registry.snapshot().stable_version("maps/source")}
        if overridden
        else {}
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
        endpoints = fault.details["admission_faults"]
        assert len(endpoints) == 1
        endpoint = endpoints[0]
        assert endpoint["details"]["defect"] == "unknown_connection_node"
        assert endpoint["scope"]["segments"] == list(SCOPES[wrapper])
        assert endpoint["details"]["missing_roles"] == ["src", "dst"]
        if wrapper.startswith("retained"):
            assert endpoint["path"] == []
            assert endpoint["details"]["component"] == "endpoints/composite"
            assert (
                endpoint["details"]["version"]
                == system._registry.snapshot().stable["endpoints/composite"]
            )
            assert endpoint["details"]["definition_path"] == list(PATHS[wrapper])
        else:
            assert endpoint["path"] == list(PATHS[wrapper])
        responses.append(_terminal_response_bytes(journal, "runs_counterfactual"))
    assert responses[0] == responses[1]
    assert len(journal.run_records(limit=100)) == 1
    assert host.launches == []
    assert canonical_json(system.manifest_for_run(source_id).model_dump(mode="json")) == before
    reproduced = await control.runs_reproduce(
        ACTOR,
        source_run_id=source_id,
        idempotency_key="reproduce",
    )
    assert isinstance(reproduced, RunSubmission)
    assert (
        canonical_json(system.manifest_for_run(reproduced.run_id).model_dump(mode="json")) == before
    )
    assert len(journal.run_records(limit=100)) == 2
    await control.shutdown()


@pytest.mark.parametrize("seam", ["after_plan", "after_command_completion"])
async def test_endpoint_start_refusal_recovers_and_a_repair_requires_a_new_key(
    system: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
    seam: str,
) -> None:
    graph = endpoint_graph(system)
    first = _fresh_control(
        system,
        journal,
        "endpoint-first",
        run_host=_PassiveHost(),
        fault_probe=_crash_at("runs_start", seam),
    )
    with pytest.raises(InjectedCrash):
        await first.runs_start(ACTOR, proposal=graph, inputs=INPUTS, idempotency_key="start")
    clock.advance(31)
    host = _PassiveHost()
    second = _fresh_control(system, journal, "endpoint-second", run_host=host)
    responses = []
    for _ in range(2):
        result = await second.runs_start(
            ACTOR, proposal=graph, inputs=INPUTS, idempotency_key="start"
        )
        assert isinstance(result, AdmissionRejected)
        assert result.faults[0].details["defect"] == "unknown_connection_node"
        responses.append(_terminal_response_bytes(journal, "runs_start"))
    assert responses[0] == responses[1]
    assert journal.run_records(limit=100) == []
    assert host.launches == []
    repaired = graph.model_copy(update={"connections": graph.connections[:1]})
    conflict = await second.runs_start(
        ACTOR, proposal=repaired, inputs=INPUTS, idempotency_key="start"
    )
    assert isinstance(conflict, ControlRejected)
    assert conflict.faults[0].code == ControlCode.IDEMPOTENCY_CONFLICT
    accepted = await second.runs_start(
        ACTOR, proposal=repaired, inputs=INPUTS, idempotency_key="repaired"
    )
    assert isinstance(accepted, RunSubmission)
    assert len(journal.run_records(limit=100)) == len(host.launches) == 1
    await first.shutdown()
    await second.shutdown()


async def test_endpoint_refusal_has_no_domain_mutation_seam(
    system: Constructicon,
    journal: SqliteJournal,
) -> None:
    host = _PassiveHost()
    control = _fresh_control(
        system,
        journal,
        "endpoint-no-domain",
        run_host=host,
        fault_probe=_crash_at("runs_start", "after_domain_mutation"),
    )
    result = await control.runs_start(
        ACTOR,
        proposal=endpoint_graph(system),
        inputs=INPUTS,
        idempotency_key="refused",
    )
    assert isinstance(result, AdmissionRejected)
    assert host.launches == []
    with journal._connect() as connection:
        for table in ("manifests", "runs", "effects"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    await control.shutdown()
