"""Waiting is not failing: a parked invocation checkpoints nothing (M7)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import Digest, digest
from constructicon.core.run import InvocationParked, ParkedUnit, RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import BRIEF, ISSUE, atomic

REQUEST = digest("channel-message", 1, {"request": "advice"})
INPUTS = {"issue": {"title": "does this ship?"}}


async def waiting_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    """A component that has sent its request and found no reply yet."""

    raise InvocationParked(REQUEST, reason="awaiting_advisor")


def _register_waiting(system: Constructicon) -> Graph:
    definition, implementation = atomic("test/waits", (ISSUE,), (BRIEF,), waiting_impl)
    version = system._register(definition, implementation)
    system._promote_initial(component=definition.name, version=version)
    return Graph(
        name="one-wait",
        nodes=(GraphNode(id="advisor", body=Ref(component="test/waits")),),
        connections=(),
        inputs=(ISSUE,),
        outputs=(BRIEF,),
    )


async def _park_one_run(system: Constructicon, journal: SqliteJournal) -> RunId:
    graph = _register_waiting(system)
    manifest = system.validate(graph, INPUTS)
    run_id = RunId("run-invocation-parked")
    system._prepare_run(manifest, run_id=run_id, inputs=INPUTS)
    result = await system._run_prepared(run_id, cancellation="abandon")
    assert result.status is RunStatus.PARKED
    return run_id


async def test_a_waiting_invocation_parks_its_run_naming_the_exact_request(
    system: Constructicon,
    journal: SqliteJournal,
) -> None:
    run_id = await _park_one_run(system, journal)

    record = journal.run_record(run_id)
    assert record is not None and record.status is RunStatus.PARKED
    waits = journal.parked_waits()
    assert [wait.run_id for wait in waits] == [run_id]
    assert waits[0].requests == (REQUEST,)  # recovery can find this reply later


async def test_a_parked_invocation_checkpoints_no_output_that_does_not_exist(
    system: Constructicon,
    journal: SqliteJournal,
) -> None:
    """The advisor produced nothing; a checkpoint would invent a completion."""

    run_id = await _park_one_run(system, journal)
    path = ExecutionPath(scope=ScopePath(segments=("advisor",)))
    assert journal.checkpoint(run_id, path) is None


async def test_parking_records_a_node_event_carrying_its_wait(
    system: Constructicon,
    journal: SqliteJournal,
) -> None:
    run_id = await _park_one_run(system, journal)
    parked_events = [
        event for event in journal.events(run_id, limit=100) if event.kind == "NodeParked"
    ]
    assert len(parked_events) == 1
    unit = ParkedUnit.model_validate(parked_events[0].payload)
    assert unit.reason == "awaiting_advisor"
    assert unit.waiting_on == REQUEST
    assert unit.completed_iterations is None  # this is a wait, not an exhausted policy

    failed = [event for event in journal.events(run_id, limit=100) if event.kind == "NodeFailed"]
    assert failed == []  # waiting is never reported as failure


async def test_a_parked_run_reports_its_wait_on_the_run_result(
    system: Constructicon,
    journal: SqliteJournal,
) -> None:
    graph = _register_waiting(system)
    manifest = system.validate(graph, INPUTS)
    run_id = RunId("run-parked-result")
    system._prepare_run(manifest, run_id=run_id, inputs=INPUTS)
    result = await system._run_prepared(run_id, cancellation="abandon")

    assert result.status is RunStatus.PARKED
    assert result.failures == {}
    assert [unit.waiting_on for unit in result.parked] == [REQUEST]
    assert isinstance(result.parked[0].waiting_on, Digest)
