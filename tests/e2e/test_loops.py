"""M4: sealed generic bounded loops, frame-aware recovery, and PARKED closure."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, IterationFrame, RunId, ScopePath
from constructicon.core.errors import AdmissionError
from constructicon.core.graph import Graph, GraphNode, Loop, Ref
from constructicon.core.manifest import CONTINUE_SCHEMA_HASH, CONTINUE_TYPE
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock, InjectedCrash, atomic

STATE = Port(name="state", type_id="loop/State", schema_hash="state-v1")
AGAIN = Port(
    name="again",
    type_id=CONTINUE_TYPE,
    schema_hash=CONTINUE_SCHEMA_HASH,
    json_schema={"type": "boolean"},
)
OPTIONAL_NOTE = Port(
    name="note",
    type_id="loop/Note",
    schema_hash="note-v1",
    cardinality="optional",
)
RESULT = Port(name="result", type_id="loop/Result", schema_hash="result-v1")

CALLS: list[int] = []


async def step_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    value = int(inputs["state"]["value"]) + 1
    CALLS.append(value)
    return {"state": {"value": value}, "again": value < 3}


async def one_step_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    value = int(inputs["state"]["value"]) + 1
    return {"state": {"value": value}, "again": False}


async def always_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    value = int(inputs["state"]["value"]) + 1
    return {"state": {"value": value}, "again": True}


async def final_iteration_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    value = int(inputs["state"]["value"]) + 1
    return {"state": {"value": value}, "again": value < 3}


async def optional_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    value = int(inputs["state"]["value"]) + 1
    note = inputs["note"]
    return {
        "state": {"value": value, "note_was_none": note is None},
        "again": False,
    }


async def effect_step_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    value = int(inputs["state"]["value"]) + 1
    await ctx.effect("announce", {"iteration": value})
    return {"state": {"value": value}, "again": value < 3}


async def fail_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    raise RuntimeError("independent failure")


def loop_graph(component: str, *, max_iterations: int = 5) -> Graph:
    return Graph(
        name="bounded-loop",
        nodes=(
            GraphNode(
                id="repeat",
                body=Loop(
                    body=Ref(component=component),
                    feedback={"state": "state"},
                    continue_from="again",
                    max_iterations=max_iterations,
                ),
            ),
        ),
        inputs=(STATE,),
        outputs=(STATE,),
    )


def register(
    system: Constructicon,
    name: str,
    impl: Any,
    *,
    inputs: tuple[Port, ...] = (STATE,),
) -> None:
    definition, implementation = atomic(name, inputs, (STATE, AGAIN), impl)
    version = system.register(definition, implementation)
    system.promote_initial(component=name, version=version)


def make_system(
    tmp_path: Path,
    *,
    clock: FakeClock | None = None,
    effect: FakeAnnounceEffect | None = None,
) -> tuple[Constructicon, SqliteJournal]:
    journal = (
        SqliteJournal(tmp_path / "loop.db", now_fn=clock.now)
        if clock is not None
        else SqliteJournal(tmp_path / "loop.db")
    )
    system = Constructicon(
        journal=journal,
        effects={"announce": effect} if effect else {},
        owner_id="loop-worker",
        lease_ttl_s=30.0,
    )
    return system, journal


async def test_admission_seals_the_complete_loop_program(tmp_path: Path) -> None:
    system, _ = make_system(tmp_path)
    register(system, "loop/step", step_impl)
    graph = loop_graph("loop/step")

    manifest = system.validate(graph, {"state": {"value": 0}})

    assert manifest.schema_version == 2
    assert len(manifest.resolved_loops) == 1
    loop = manifest.resolved_loops[0]
    assert loop.scope.render() == "bounded-loop/repeat"
    assert loop.body_scope.render() == "bounded-loop/repeat/body"
    assert [path.render() for path in loop.member_order] == [
        "bounded-loop/repeat/body/$body"
    ]
    assert [binding.destination.port for binding in loop.initial_bindings] == ["state"]
    assert [binding.destination.port for binding in loop.feedback_bindings] == ["state"]
    assert [export.port.name for export in loop.exports] == ["state"]
    assert all(export.port.name != "again" for export in loop.exports)


async def test_loop_executes_until_false_and_exports_final_values(tmp_path: Path) -> None:
    CALLS.clear()
    system, journal = make_system(tmp_path)
    register(system, "loop/step", step_impl)

    result = await system.start(
        loop_graph("loop/step"),
        {"state": {"value": 0}},
        run_id=RunId("run-loop"),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs == {"state": {"value": 3}}
    assert CALLS == [1, 2, 3]
    loop_scope = ScopePath(segments=("bounded-loop", "repeat"))
    member_scope = loop_scope.child("body").child("$body")
    for index in range(3):
        frame = IterationFrame(loop=loop_scope, index=index)
        assert journal.checkpoint(
            RunId("run-loop"), ExecutionPath(scope=member_scope, iterations=(frame,))
        ) is not None


async def test_false_on_first_iteration_still_executes_once(tmp_path: Path) -> None:
    system, _ = make_system(tmp_path)
    register(system, "loop/once", one_step_impl)
    result = await system.start(
        loop_graph("loop/once"),
        {"state": {"value": 0}},
        run_id=RunId("run-once"),
    )
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["state"] == {"value": 1}


async def test_exhaustion_parks_without_exporting_partial_state(tmp_path: Path) -> None:
    system, _ = make_system(tmp_path)
    register(system, "loop/always", always_impl)
    result = await system.start(
        loop_graph("loop/always", max_iterations=2),
        {"state": {"value": 0}},
        run_id=RunId("run-parked"),
    )
    assert result.status is RunStatus.PARKED
    assert result.outputs == {}
    assert len(result.parked) == 1
    assert result.parked[0].reason == "policy_exhausted"
    assert result.parked[0].completed_iterations == 2


async def test_false_on_final_allowed_iteration_succeeds(tmp_path: Path) -> None:
    system, _ = make_system(tmp_path)
    register(system, "loop/final", final_iteration_impl)
    result = await system.start(
        loop_graph("loop/final", max_iterations=3),
        {"state": {"value": 0}},
        run_id=RunId("run-final"),
    )
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["state"] == {"value": 3}


async def test_resume_restores_completed_iteration_and_replays_only_missing_work(
    tmp_path: Path,
) -> None:
    CALLS.clear()
    clock = FakeClock()
    system, journal = make_system(tmp_path, clock=clock)
    register(system, "loop/step", step_impl)
    fired = False

    def probe(name: str) -> None:
        nonlocal fired
        if name == "completion.after_commit" and not fired:
            fired = True
            raise InjectedCrash(name)

    journal.fault_probe = probe
    with pytest.raises(InjectedCrash):
        await system.start(
            loop_graph("loop/step"),
            {"state": {"value": 0}},
            run_id=RunId("run-resume-loop"),
        )
    journal.fault_probe = lambda name: None
    clock.advance(31.0)

    second, _ = make_system(tmp_path, clock=clock)
    register(second, "loop/step", step_impl)
    result = await second.resume(RunId("run-resume-loop"))

    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["state"] == {"value": 3}
    assert CALLS == [1, 2, 3]  # iteration zero restored, never invoked twice
    kinds = [event.kind for event in journal.events(RunId("run-resume-loop"), limit=200)]
    assert "NodeRestored" in kinds


async def test_effect_keys_are_frame_distinct(tmp_path: Path) -> None:
    effect = FakeAnnounceEffect()
    system, _ = make_system(tmp_path, effect=effect)
    register(system, "loop/effect-step", effect_step_impl)
    result = await system.start(
        loop_graph("loop/effect-step"),
        {"state": {"value": 0}},
        run_id=RunId("run-loop-effects"),
    )
    assert result.status is RunStatus.SUCCEEDED
    assert len(effect.executions) == 3


async def test_effect_replay_deduplicates_within_the_same_iteration_frame(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    effect = FakeAnnounceEffect()
    system, journal = make_system(tmp_path, clock=clock, effect=effect)
    register(system, "loop/effect-replay", effect_step_impl)
    fired = False

    def crash_before_first_checkpoint_commit(name: str) -> None:
        nonlocal fired
        if name == "completion.after_checkpoint_insert" and not fired:
            fired = True
            raise InjectedCrash(name)

    journal.fault_probe = crash_before_first_checkpoint_commit
    with pytest.raises(InjectedCrash):
        await system.start(
            loop_graph("loop/effect-replay"),
            {"state": {"value": 0}},
            run_id=RunId("run-loop-effect-replay"),
        )
    journal.fault_probe = lambda name: None
    clock.advance(31.0)

    result = await system.resume(RunId("run-loop-effect-replay"))

    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs == {"state": {"value": 3}}
    assert len(effect.executions) == 3
    kinds = [
        event.kind
        for event in journal.events(RunId("run-loop-effect-replay"), limit=300)
    ]
    assert "EffectDeduplicated" in kinds


async def test_optional_invariant_input_without_source_is_none(tmp_path: Path) -> None:
    system, _ = make_system(tmp_path)
    register(
        system,
        "loop/optional",
        optional_impl,
        inputs=(STATE, OPTIONAL_NOTE),
    )
    result = await system.start(
        loop_graph("loop/optional"),
        {"state": {"value": 0}},
        run_id=RunId("run-optional"),
    )
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["state"]["note_was_none"] is True


async def test_wrong_continuation_schema_is_rejected(tmp_path: Path) -> None:
    system, _ = make_system(tmp_path)
    wrong = Port(
        name="again",
        type_id=CONTINUE_TYPE,
        schema_hash="not-the-boolean-schema",
    )
    definition, implementation = atomic(
        "loop/wrong-control", (STATE,), (STATE, wrong), step_impl
    )
    version = system.register(definition, implementation)
    system.promote_initial(component=definition.name, version=version)
    with pytest.raises(AdmissionError, match="continuation output"):
        system.validate(loop_graph("loop/wrong-control"), {"state": {"value": 0}})

A_STATE = Port(name="state_a", type_id="loop/AState", schema_hash="a-v1")
B_STATE = Port(name="state_b", type_id="loop/BState", schema_hash="b-v1")
TRIGGER = Port(name="trigger", type_id="loop/Trigger", schema_hash="trigger-v1")
SINK = Port(name="sink", type_id="loop/Sink", schema_hash="sink-v1")


async def always_a_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "state_a": {"value": int(inputs["state_a"]["value"]) + 1},
        "again": True,
    }


async def always_b_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "state_b": {"value": int(inputs["state_b"]["value"]) + 1},
        "again": True,
    }


async def sink_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    raise AssertionError("a dependent of a parked loop must never execute")


async def independent_fail_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    raise RuntimeError("independent branch failed")


async def wait_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    started = WAIT_EVENTS["started"]
    release = WAIT_EVENTS["release"]
    started.set()
    await release.wait()
    return {"state": inputs["state"], "again": True}


WAIT_EVENTS: dict[str, Any] = {}


def _register_exact(
    system: Constructicon,
    name: str,
    inputs: tuple[Port, ...],
    outputs: tuple[Port, ...],
    impl: Any,
) -> None:
    definition, implementation = atomic(name, inputs, outputs, impl)
    version = system.register(definition, implementation)
    system.promote_initial(component=name, version=version)


def _parked_loop(
    node_id: str,
    component: str,
    state_name: str,
    *,
    max_iterations: int = 1,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        body=Loop(
            body=Ref(component=component),
            feedback={state_name: state_name},
            continue_from="again",
            max_iterations=max_iterations,
        ),
    )


async def test_multiple_independent_loops_report_every_parked_root(tmp_path: Path) -> None:
    system, _ = make_system(tmp_path)
    _register_exact(system, "loop/always-a", (A_STATE,), (A_STATE, AGAIN), always_a_impl)
    _register_exact(system, "loop/always-b", (B_STATE,), (B_STATE, AGAIN), always_b_impl)
    graph = Graph(
        name="two-parks",
        nodes=(
            _parked_loop("a", "loop/always-a", "state_a"),
            _parked_loop("b", "loop/always-b", "state_b"),
        ),
        inputs=(A_STATE, B_STATE),
    )

    result = await system.start(
        graph,
        {"state_a": {"value": 0}, "state_b": {"value": 0}},
        run_id=RunId("run-two-parks"),
    )

    assert result.status is RunStatus.PARKED
    assert [item.path.scope.segments[-1] for item in result.parked] == ["a", "b"]
    assert all(item.reason == "policy_exhausted" for item in result.parked)


async def test_dependent_is_blocked_on_parked_producer_without_failing_run(
    tmp_path: Path,
) -> None:
    from constructicon.core.graph import Connection

    system, _ = make_system(tmp_path)
    _register_exact(system, "loop/always-a", (A_STATE,), (A_STATE, AGAIN), always_a_impl)
    _register_exact(system, "loop/park-sink", (A_STATE,), (SINK,), sink_impl)
    graph = Graph(
        name="park-blocks",
        nodes=(
            _parked_loop("loop", "loop/always-a", "state_a"),
            GraphNode(id="sink", body=Ref(component="loop/park-sink")),
        ),
        connections=(
            Connection(
                src="loop",
                dst="sink",
                map={"state_a": "loop.state_a"},
            ),
        ),
        inputs=(A_STATE,),
        outputs=(SINK,),
    )

    result = await system.start(
        graph,
        {"state_a": {"value": 0}},
        run_id=RunId("run-park-blocks"),
    )

    assert result.status is RunStatus.PARKED
    assert len(result.blocked) == 1
    assert result.blocked[0].destination.scope.segments[-1] == "sink"
    assert result.blocked[0].producers[0].status.value == "parked"


async def test_failure_precedes_park_at_graph_closure_but_retains_park_detail(
    tmp_path: Path,
) -> None:
    system, journal = make_system(tmp_path)
    _register_exact(system, "loop/always-a", (A_STATE,), (A_STATE, AGAIN), always_a_impl)
    _register_exact(
        system,
        "loop/independent-fail",
        (TRIGGER,),
        (SINK,),
        independent_fail_impl,
    )
    graph = Graph(
        name="failure-precedes-park",
        nodes=(
            _parked_loop("a-loop", "loop/always-a", "state_a"),
            GraphNode(id="z-fail", body=Ref(component="loop/independent-fail")),
        ),
        inputs=(A_STATE, TRIGGER),
    )

    result = await system.start(
        graph,
        {"state_a": {"value": 0}, "trigger": {}},
        run_id=RunId("run-fail-and-park"),
    )

    assert result.status is RunStatus.FAILED
    assert len(result.parked) == 1
    failed_event = next(
        event
        for event in journal.events(RunId("run-fail-and-park"), limit=200)
        if event.kind == "RunFailed"
    )
    assert failed_event.payload is not None
    assert len(failed_event.payload["parked"]) == 1


async def test_asyncio_cancellation_inside_loop_becomes_durable_cancelled(
    tmp_path: Path,
) -> None:
    import asyncio

    system, _ = make_system(tmp_path)
    _register_exact(system, "loop/wait", (STATE,), (STATE, AGAIN), wait_impl)
    WAIT_EVENTS["started"] = asyncio.Event()
    WAIT_EVENTS["release"] = asyncio.Event()

    task = asyncio.create_task(
        system.start(
            loop_graph("loop/wait", max_iterations=3),
            {"state": {"value": 0}},
            run_id=RunId("run-loop-cancel"),
        )
    )
    await WAIT_EVENTS["started"].wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    state = system.run_state(RunId("run-loop-cancel"))
    assert state is not None and state.status is RunStatus.CANCELLED
