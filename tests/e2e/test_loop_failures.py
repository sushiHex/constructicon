"""M4 loop failure containment keeps durable iteration history contiguous."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, IterationFrame, RunId, ScopePath
from constructicon.core.component import ComponentDef
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.manifest import CONTINUE_SCHEMA_HASH, CONTINUE_TYPE
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import atomic

STATE = Port(name="state", type_id="loop/FailureState", schema_hash="state-v1")
SIDE = Port(name="side", type_id="loop/Side", schema_hash="side-v1")
CONTINUE = Port(
    name="continue",
    type_id=CONTINUE_TYPE,
    schema_hash=CONTINUE_SCHEMA_HASH,
    json_schema={"type": "boolean"},
)

FAIL_CALLS = 0
SIDE_CALLS = 0
DECIDE_CALLS = 0


async def explode_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    global FAIL_CALLS
    FAIL_CALLS += 1
    raise RuntimeError("iteration exploded")


async def side_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    global SIDE_CALLS
    SIDE_CALLS += 1
    return {"side": {"ok": True}}


async def decide_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    global DECIDE_CALLS
    DECIDE_CALLS += 1
    return {"continue": False}


def register(
    system: Constructicon,
    name: str,
    inputs: tuple[Port, ...],
    outputs: tuple[Port, ...],
    impl: Any,
) -> None:
    definition, implementation = atomic(name, inputs, outputs, impl)
    version = system._register(definition, implementation)
    system._promote_initial(component=name, version=version)


def failure_graph(system: Constructicon) -> Graph:
    register(system, "loop/explode", (STATE,), (STATE,), explode_impl)
    register(system, "loop/side", (), (SIDE,), side_impl)
    register(system, "loop/decide", (STATE,), (CONTINUE,), decide_impl)
    body = Graph(
        name="failing-body",
        nodes=(
            GraphNode(id="explode", body=Ref(component="loop/explode")),
            GraphNode(id="side", body=Ref(component="loop/side")),
            GraphNode(id="decide", body=Ref(component="loop/decide")),
        ),
        connections=(
            Connection(
                src="explode",
                dst="decide",
                map={"state": "explode.state"},
            ),
        ),
        inputs=(STATE,),
        outputs=(STATE, CONTINUE),
    )
    component = ComponentDef(
        name="loop/failing-body",
        role="component",
        body=body,
        inputs=body.inputs,
        outputs=body.outputs,
    )
    version = system._register(component)
    system._promote_initial(component=component.name, version=version)
    return Graph(
        name="failed-loop",
        nodes=(
            GraphNode(
                id="repeat",
                body=Loop(
                    body=Ref(component=component.name),
                    feedback={"state": "state"},
                    continue_from="continue",
                    max_iterations=2,
                ),
            ),
        ),
        inputs=(STATE,),
    )


async def test_failed_member_blocks_downstream_and_skips_independent_tail(
    tmp_path: Path,
) -> None:
    global FAIL_CALLS, SIDE_CALLS, DECIDE_CALLS
    FAIL_CALLS = SIDE_CALLS = DECIDE_CALLS = 0
    system = Constructicon(
        journal=SqliteJournal(tmp_path / "failure.db"),
        owner_id="failure-worker",
    )
    graph = failure_graph(system)
    run_id = RunId("failed-loop")

    first = await system._start_direct(graph, {"state": {"value": 0}}, run_id=run_id)
    assert first.status is RunStatus.FAILED
    assert FAIL_CALLS == 1
    assert SIDE_CALLS == 0
    assert DECIDE_CALLS == 0
    events = system._journal.events(run_id, limit=200)
    assert any(event.kind == "NodeSkipped" for event in events)
    assert any(event.kind == "NodeBlocked" for event in events)

    loop_scope = ScopePath(segments=("failed-loop", "repeat"))
    frame = IterationFrame(loop=loop_scope, index=0)
    body_root = loop_scope.child("body").child("$body")
    for member in ("explode", "side", "decide"):
        assert system._journal.checkpoint(
            run_id,
            ExecutionPath(scope=body_root.child(member), iterations=(frame,)),
        ) is None

    # A failed run may be resumed. The missing first invocation replays, but no
    # sparse later checkpoint is ever mistaken for a valid iteration prefix.
    second = await system._resume_direct(run_id)
    assert second.status is RunStatus.FAILED
    assert FAIL_CALLS == 2
    assert SIDE_CALLS == 0
    assert DECIDE_CALLS == 0
