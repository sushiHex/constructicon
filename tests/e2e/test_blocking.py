"""Dependency blocking resolved before collection (M2 §5).

A destination whose producer failed is BLOCKED with a typed
``DependencyReport`` naming the COMPLETE recorded producer set — completed
producers included, never only the failing one. Unrelated branches finish;
the run's terminal status is decided at graph closure.
"""

from __future__ import annotations

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.ports import Port
from constructicon.core.run import InvocationStatus, RunStatus
from tests.conftest import (
    BRIEF,
    ISSUE,
    SUMMARY,
    atomic,
    failing_impl,
)

INPUTS = {"issue": {"title": "retry loop is flaky"}}
GATHER = Port(name="briefs", type_id="test/Brief", schema_hash="s1", cardinality="many")
COLLECTED = Port(name="collected", type_id="test/Collected", schema_hash="s1")


def diamond_world(world: Constructicon) -> Constructicon:
    for definition, impl in (
        atomic("test/failer", (ISSUE,), (BRIEF,), failing_impl),
        atomic("test/collect", (GATHER,), (COLLECTED,), collect_impl),
    ):
        version = world.register(definition, impl)
        world.promote_initial(component=definition.name, version=version)
    return world


async def collect_impl(ctx, inputs):  # gathers many briefs
    titles = ", ".join(brief["title"] for brief in inputs["briefs"])
    return {"collected": {"text": f"collected {titles}"}}


def diamond_graph() -> Graph:
    """triage and failer both feed collect; summarize hangs off triage alone —
    the unrelated branch that must finish."""
    return Graph(
        name="diamond",
        nodes=(
            GraphNode(
                id="triage",
                body=Ref(component="test/triage", bind={"executor": "fake-executor"}),
            ),
            GraphNode(id="failer", body=Ref(component="test/failer")),
            GraphNode(id="collect", body=Ref(component="test/collect")),
            GraphNode(id="summarize", body=Ref(component="test/summarize")),
        ),
        connections=(
            Connection(src="triage", dst="collect"),
            Connection(src="failer", dst="collect"),
            Connection(src="triage", dst="summarize"),
        ),
        inputs=(ISSUE,),
        outputs=(SUMMARY, COLLECTED),
    )


async def test_blocked_report_names_the_complete_producer_set(
    world: Constructicon,
) -> None:
    diamond_world(world)
    run_id = RunId("run-diamond")
    result = await world.start(diamond_graph(), INPUTS, run_id=run_id)

    assert result.status is RunStatus.FAILED
    assert list(result.failures) == ["diamond/failer"]
    assert "scripted node failure" in result.failures["diamond/failer"]

    assert len(result.blocked) == 1
    report = result.blocked[0]
    assert report.destination.render() == "diamond/collect"
    by_path = {p.path.render(): p.status for p in report.producers}
    # the COMPLETE producer set: the completed producer is listed too
    assert by_path == {
        "diamond/triage": InvocationStatus.COMPLETED,
        "diamond/failer": InvocationStatus.FAILED,
    }

    kinds = {event.kind for event in world.journal.events(run_id, limit=200)}
    assert {"NodeFailed", "NodeBlocked", "RunFailed"} <= kinds
    # the unrelated branch finished: summarize completed despite the failure
    completed_paths = {
        event.path.render()
        for event in world.journal.events(run_id, limit=200)
        if event.kind == "NodeCompleted" and event.path is not None
    }
    assert "diamond/summarize" in completed_paths


async def test_blocked_event_payload_is_the_typed_report(
    world: Constructicon,
) -> None:
    diamond_world(world)
    run_id = RunId("run-diamond-payload")
    await world.start(diamond_graph(), INPUTS, run_id=run_id)
    blocked_events = [
        event
        for event in world.journal.events(run_id, limit=200)
        if event.kind == "NodeBlocked"
    ]
    assert len(blocked_events) == 1
    payload = blocked_events[0].payload
    assert payload is not None
    statuses = {p["status"] for p in payload["producers"]}
    assert statuses == {"completed", "failed"}
