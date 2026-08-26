"""M4 graph closure: PARKED is a typed root outcome, not a hidden failure."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.manifest import CONTINUE_SCHEMA_HASH, CONTINUE_TYPE
from constructicon.core.ports import Port
from constructicon.core.run import InvocationStatus, RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import atomic

A_STATE = Port(name="a_state", type_id="loop/AState", schema_hash="a-v1")
B_STATE = Port(name="b_state", type_id="loop/BState", schema_hash="b-v1")
CONTINUE = Port(
    name="continue",
    type_id=CONTINUE_TYPE,
    schema_hash=CONTINUE_SCHEMA_HASH,
    json_schema={"type": "boolean"},
)
DONE = Port(name="done", type_id="loop/Done", schema_hash="done-v1")

CANCEL_STARTED: asyncio.Event | None = None
ASYNC_CANCEL_STARTED: asyncio.Event | None = None


async def a_forever(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "a_state": {"value": int(inputs["a_state"]["value"]) + 1},
        "continue": True,
    }


async def b_forever(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "b_state": {"value": int(inputs["b_state"]["value"]) + 1},
        "continue": True,
    }


async def done_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"done": {"ok": True}}


async def dependent_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    return {"done": {"value": inputs["a_state"]["value"]}}


async def fail_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    raise RuntimeError("independent failure")


async def cancellable_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    assert CANCEL_STARTED is not None
    CANCEL_STARTED.set()
    await asyncio.sleep(0.02)
    return {
        "a_state": {"value": int(inputs["a_state"]["value"]) + 1},
        "continue": True,
    }


async def async_cancellable_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    assert ASYNC_CANCEL_STARTED is not None
    ASYNC_CANCEL_STARTED.set()
    await asyncio.sleep(60)
    return {"a_state": inputs["a_state"], "continue": True}


def register(
    system: Constructicon,
    name: str,
    inputs: tuple[Port, ...],
    outputs: tuple[Port, ...],
    impl: Any,
) -> None:
    definition, implementation = atomic(name, inputs, outputs, impl)
    version = system.register(definition, implementation)
    system.promote_initial(component=name, version=version)


def loop_node(node_id: str, component: str, state: Port, maximum: int) -> GraphNode:
    return GraphNode(
        id=node_id,
        body=Loop(
            body=Ref(component=component),
            feedback={state.name: state.name},
            continue_from="continue",
            max_iterations=maximum,
        ),
    )


def system_at(tmp_path: Path) -> Constructicon:
    return Constructicon(
        journal=SqliteJournal(tmp_path / "closure.db"),
        owner_id="closure-worker",
    )


async def test_multiple_parked_roots_are_reported_and_siblings_finish(
    tmp_path: Path,
) -> None:
    system = system_at(tmp_path)
    register(system, "loop/a-forever", (A_STATE,), (A_STATE, CONTINUE), a_forever)
    register(system, "loop/b-forever", (B_STATE,), (B_STATE, CONTINUE), b_forever)
    register(system, "loop/done", (), (DONE,), done_impl)
    register(system, "loop/dependent", (A_STATE,), (DONE,), dependent_impl)
    graph = Graph(
        name="multi-park",
        nodes=(
            loop_node("a_repeat", "loop/a-forever", A_STATE, 2),
            loop_node("b_repeat", "loop/b-forever", B_STATE, 3),
            GraphNode(id="sibling", body=Ref(component="loop/done")),
            GraphNode(id="dependent", body=Ref(component="loop/dependent")),
        ),
        connections=(
            Connection(
                src="a_repeat",
                dst="dependent",
                map={"a_state": "a_repeat.a_state"},
            ),
        ),
        inputs=(A_STATE, B_STATE),
        outputs=(),
    )

    result = await system.start(
        graph,
        {"a_state": {"value": 0}, "b_state": {"value": 0}},
        run_id=RunId("multi-park"),
    )

    assert result.status is RunStatus.PARKED
    observed = [
        (item.path.scope.segments[-1], item.completed_iterations)
        for item in result.parked
    ]
    assert observed == [("a_repeat", 2), ("b_repeat", 3)]
    assert len(result.blocked) == 1
    assert result.blocked[0].destination.scope.segments[-1] == "dependent"
    assert result.blocked[0].producers[0].status is InvocationStatus.PARKED
    kinds = [event.kind for event in system.journal.events(RunId("multi-park"), limit=300)]
    assert "NodeCompleted" in kinds  # independent sibling finished
    assert "RunParked" in kinds

    projected = system.project_run(RunId("multi-park"), tmp_path / "projection")
    assert projected.through_seq > 0
    assert (tmp_path / "projection" / "events.jsonl").exists()


async def test_failure_wins_over_parking_but_parking_detail_survives(
    tmp_path: Path,
) -> None:
    system = system_at(tmp_path)
    register(system, "loop/a-forever", (A_STATE,), (A_STATE, CONTINUE), a_forever)
    register(system, "loop/fail", (), (DONE,), fail_impl)
    graph = Graph(
        name="fail-and-park",
        nodes=(
            loop_node("repeat", "loop/a-forever", A_STATE, 2),
            GraphNode(id="fail", body=Ref(component="loop/fail")),
        ),
        inputs=(A_STATE,),
    )
    result = await system.start(
        graph,
        {"a_state": {"value": 0}},
        run_id=RunId("fail-and-park"),
    )
    assert result.status is RunStatus.FAILED
    assert result.parked and result.parked[0].reason == "policy_exhausted"
    run_failed = next(
        event
        for event in system.journal.events(RunId("fail-and-park"), limit=200)
        if event.kind == "RunFailed"
    )
    assert run_failed.payload and run_failed.payload["parked"]


async def test_durable_cancel_between_iterations_transitions_to_cancelled(
    tmp_path: Path,
) -> None:
    global CANCEL_STARTED
    CANCEL_STARTED = asyncio.Event()
    system = system_at(tmp_path)
    register(
        system,
        "loop/cancellable",
        (A_STATE,),
        (A_STATE, CONTINUE),
        cancellable_impl,
    )
    run_id = RunId("cancel-loop")
    task = asyncio.create_task(
        system.start(
            Graph(
                name="cancel-loop",
                nodes=(loop_node("repeat", "loop/cancellable", A_STATE, 10),),
                inputs=(A_STATE,),
            ),
            {"a_state": {"value": 0}},
            run_id=run_id,
        )
    )
    await asyncio.wait_for(CANCEL_STARTED.wait(), timeout=2)
    system.cancel(run_id)
    result = await asyncio.wait_for(task, timeout=2)
    assert result.status is RunStatus.CANCELLED
    state = system.run_state(run_id)
    assert state is not None
    assert state.status is RunStatus.CANCELLED


async def test_asyncio_task_cancel_uses_the_same_durable_state(
    tmp_path: Path,
) -> None:
    global ASYNC_CANCEL_STARTED
    ASYNC_CANCEL_STARTED = asyncio.Event()
    system = system_at(tmp_path)
    register(
        system,
        "loop/async-cancellable",
        (A_STATE,),
        (A_STATE, CONTINUE),
        async_cancellable_impl,
    )
    run_id = RunId("async-cancel-loop")
    task = asyncio.create_task(
        system.start(
            Graph(
                name="async-cancel-loop",
                nodes=(
                    loop_node("repeat", "loop/async-cancellable", A_STATE, 10),
                ),
                inputs=(A_STATE,),
            ),
            {"a_state": {"value": 0}},
            run_id=run_id,
        )
    )
    await asyncio.wait_for(ASYNC_CANCEL_STARTED.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    state = system.run_state(run_id)
    assert state is not None and state.status is RunStatus.CANCELLED
