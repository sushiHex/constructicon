"""M4: sealed generic bounded loops, frame-aware resume, and PARKED closure."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, IterationFrame, RunId, ScopePath
from constructicon.core.errors import AdmissionError, JournalDamaged
from constructicon.core.graph import Graph, GraphNode, Loop, Ref
from constructicon.core.identity import digest
from constructicon.core.manifest import CONTINUE_SCHEMA_HASH, CONTINUE_TYPE
from constructicon.core.ports import GraphInputAddress, NodePortAddress, Port
from constructicon.core.run import CheckpointConflict, RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock, InjectedCrash, atomic

SEED = Port(name="seed", type_id="loop/State", schema_hash="state-v1")
STATE = Port(name="state", type_id="loop/State", schema_hash="state-v1")
LIMIT = Port(name="limit", type_id="loop/Limit", schema_hash="limit-v1")
CONTINUE = Port(
    name="continue",
    type_id=CONTINUE_TYPE,
    schema_hash=CONTINUE_SCHEMA_HASH,
    json_schema={"type": "boolean"},
)

ADVANCE_CALLS: list[int] = []


async def advance_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    next_count = int(inputs["state"]["count"]) + 1
    ADVANCE_CALLS.append(next_count)
    return {
        "state": {"count": next_count},
        "continue": next_count < int(inputs["limit"]),
    }


async def non_bool_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    return {"state": inputs["state"], "continue": 1}


async def control_sink_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    return {"state": {"count": 0}}


def register_loop_component(system: Constructicon, *, bad: bool = False) -> str:
    impl = non_bool_impl if bad else advance_impl
    name = "loop/non-bool" if bad else "loop/advance"
    definition, _ = atomic(name, (STATE, LIMIT), (STATE, CONTINUE), impl)
    version = system._register(definition, impl)
    system._promote_initial(component=name, version=version)
    return name


def loop_graph(component: str, *, max_iterations: int) -> Graph:
    return Graph(
        name="bounded-counter",
        nodes=(
            GraphNode(
                id="counter",
                body=Loop(
                    body=Ref(component=component),
                    feedback={"state": "state"},
                    continue_from="continue",
                    max_iterations=max_iterations,
                ),
            ),
        ),
        inputs=(SEED, LIMIT),
        outputs=(STATE,),
    )


def test_admission_seals_the_complete_loop_program(system: Constructicon) -> None:
    component = register_loop_component(system)
    manifest = system.validate(
        loop_graph(component, max_iterations=4),
        {"seed": {"count": 0}, "limit": 3},
    )

    assert manifest.schema_version == 2
    assert len(manifest.resolved_loops) == 1
    loop = manifest.resolved_loops[0]
    assert loop.scope.render() == "bounded-counter/counter"
    assert loop.body_scope.render() == "bounded-counter/counter/body"
    assert [scope.render() for scope in loop.member_order] == [
        "bounded-counter/counter/body/$body"
    ]
    assert {binding.destination.port for binding in loop.initial_bindings} == {
        "state",
        "limit",
    }
    assert len(loop.feedback_bindings) == 1
    assert isinstance(loop.feedback_bindings[0].destination, GraphInputAddress)
    assert loop.feedback_bindings[0].destination.port == "state"
    assert [export.port.name for export in loop.exports] == ["state"]
    assert isinstance(loop.exports[0].destination, NodePortAddress)
    assert loop.exports[0].destination.node == "counter"
    # The control value is private to the loop and never becomes an outer output.
    assert all(export.port.name != "continue" for export in loop.exports)


async def test_loop_stops_on_false_and_exports_the_final_iteration(
    system: Constructicon,
) -> None:
    ADVANCE_CALLS.clear()
    component = register_loop_component(system)
    result = await system._start_direct(
        loop_graph(component, max_iterations=5),
        {"seed": {"count": 0}, "limit": 3},
        run_id=RunId("loop-green"),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs == {"state": {"count": 3}}
    assert ADVANCE_CALLS == [1, 2, 3]
    completed = [
        event
        for event in system._journal.events(RunId("loop-green"), limit=200)
        if event.kind == "NodeCompleted"
    ]
    assert [event.path.iterations[0].index for event in completed if event.path] == [0, 1, 2]


async def test_false_on_the_last_allowed_iteration_is_success(
    system: Constructicon,
) -> None:
    ADVANCE_CALLS.clear()
    component = register_loop_component(system)
    result = await system._start_direct(
        loop_graph(component, max_iterations=2),
        {"seed": {"count": 0}, "limit": 2},
        run_id=RunId("loop-last-false"),
    )
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["state"]["count"] == 2
    assert result.parked == ()


async def test_policy_exhaustion_parks_and_resume_restores_every_iteration(
    system: Constructicon,
) -> None:
    ADVANCE_CALLS.clear()
    component = register_loop_component(system)
    graph = loop_graph(component, max_iterations=2)
    inputs = {"seed": {"count": 0}, "limit": 10}

    first = await system._start_direct(graph, inputs, run_id=RunId("loop-parked"))
    assert first.status is RunStatus.PARKED
    assert first.outputs == {}
    assert len(first.parked) == 1
    assert first.parked[0].reason == "policy_exhausted"
    assert first.parked[0].completed_iterations == 2
    assert ADVANCE_CALLS == [1, 2]

    second = await system._resume_direct(RunId("loop-parked"))
    assert second.status is RunStatus.PARKED
    assert ADVANCE_CALLS == [1, 2]  # both frame-specific checkpoints restored
    kinds = [
        event.kind for event in system._journal.events(RunId("loop-parked"), limit=300)
    ]
    assert kinds.count("RunParked") == 2
    assert kinds.count("NodeRestored") == 2


async def test_crash_after_iteration_checkpoint_resumes_without_reexecution(
    system: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    ADVANCE_CALLS.clear()
    component = register_loop_component(system)
    fired = False

    def crash_after_first_completion(name: str) -> None:
        nonlocal fired
        if name == "completion.after_commit" and not fired:
            fired = True
            raise InjectedCrash(name)

    journal.fault_probe = crash_after_first_completion
    with pytest.raises(InjectedCrash):
        await system._start_direct(
            loop_graph(component, max_iterations=5),
            {"seed": {"count": 0}, "limit": 3},
            run_id=RunId("loop-crash"),
        )
    journal.fault_probe = lambda name: None
    clock.advance(31)

    result = await system._resume_direct(RunId("loop-crash"))
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["state"]["count"] == 3
    assert ADVANCE_CALLS == [1, 2, 3]
    assert any(
        event.kind == "NodeRestored"
        for event in journal.events(RunId("loop-crash"), limit=300)
    )


async def test_runtime_continuation_is_exactly_bool(system: Constructicon) -> None:
    component = register_loop_component(system, bad=True)
    result = await system._start_direct(
        loop_graph(component, max_iterations=2),
        {"seed": {"count": 0}, "limit": 2},
        run_id=RunId("loop-bad-control"),
    )
    assert result.status is RunStatus.FAILED
    assert any("exactly bool" in error for error in result.failures.values())


def test_continuation_contract_requires_the_canonical_boolean_schema(
    system: Constructicon,
) -> None:
    wrong_continue = Port(
        name="continue",
        type_id=CONTINUE_TYPE,
        schema_hash="not-the-boolean-schema",
    )
    definition, impl = atomic(
        "loop/wrong-control",
        (STATE, LIMIT),
        (STATE, wrong_continue),
        advance_impl,
    )
    version = system._register(definition, impl)
    system._promote_initial(component=definition.name, version=version)
    with pytest.raises(AdmissionError, match="must be exactly"):
        system.validate(
            loop_graph(definition.name, max_iterations=2),
            {"seed": {"count": 0}, "limit": 2},
        )


def test_feedback_requires_the_exact_schema_and_single_cardinality(
    system: Constructicon,
) -> None:
    wrong_state = Port(name="state", type_id=STATE.type_id, schema_hash="state-v2")
    definition, impl = atomic(
        "loop/wrong-feedback-schema",
        (STATE, LIMIT),
        (wrong_state, CONTINUE),
        advance_impl,
    )
    version = system._register(definition, impl)
    system._promote_initial(component=definition.name, version=version)
    with pytest.raises(AdmissionError, match="exact nominal contract"):
        system.validate(
            loop_graph(definition.name, max_iterations=2),
            {"seed": {"count": 0}, "limit": 2},
        )

    many_state = Port(
        name="state",
        type_id=STATE.type_id,
        schema_hash=STATE.schema_hash,
        cardinality="many",
    )
    definition_many, impl_many = atomic(
        "loop/wrong-feedback-many",
        (STATE, LIMIT),
        (many_state, CONTINUE),
        advance_impl,
    )
    many_version = system._register(definition_many, impl_many)
    system._promote_initial(component=definition_many.name, version=many_version)
    with pytest.raises(AdmissionError, match="cardinality 'one' on both"):
        system.validate(
            loop_graph(definition_many.name, max_iterations=2),
            {"seed": {"count": 0}, "limit": 2},
        )


async def test_direct_composite_body_uses_the_same_loop_boundary(
    system: Constructicon,
) -> None:
    component = register_loop_component(system)
    composite_graph = Graph(
        name="advance-body",
        nodes=(GraphNode(id="advance", body=Ref(component=component)),),
        inputs=(STATE, LIMIT),
        outputs=(STATE, CONTINUE),
    )
    from constructicon.core.component import ComponentDef

    composite = ComponentDef(
        name="loop/composite-body",
        role="component",
        body=composite_graph,
        inputs=(STATE, LIMIT),
        outputs=(STATE, CONTINUE),
    )
    version = system._register(composite)
    system._promote_initial(component=composite.name, version=version)

    manifest = system.validate(
        loop_graph(composite.name, max_iterations=4),
        {"seed": {"count": 0}, "limit": 2},
    )
    assert [scope.render() for scope in manifest.resolved_loops[0].member_order] == [
        "bounded-counter/counter/body/$body/advance"
    ]

    result = await system._start_direct(
        loop_graph(composite.name, max_iterations=4),
        {"seed": {"count": 0}, "limit": 2},
        run_id=RunId("loop-composite"),
    )
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["state"] == {"count": 2}


def test_nested_loop_hidden_behind_composite_ref_is_rejected(
    system: Constructicon,
) -> None:
    component = register_loop_component(system)
    inner_graph = Graph(
        name="inner-loop-body",
        nodes=(
            GraphNode(
                id="inner",
                body=Loop(
                    body=Ref(component=component),
                    feedback={"state": "state"},
                    continue_from="continue",
                    max_iterations=2,
                ),
            ),
        ),
        inputs=(STATE, LIMIT),
        outputs=(STATE, CONTINUE),
    )
    from constructicon.core.component import ComponentDef

    composite = ComponentDef(
        name="loop/contains-loop",
        role="component",
        body=inner_graph,
        inputs=(STATE, LIMIT),
        outputs=(STATE, CONTINUE),
    )
    version = system._register(composite)
    system._promote_initial(component=composite.name, version=version)

    with pytest.raises(AdmissionError, match="nested Loop"):
        system.validate(
            loop_graph(composite.name, max_iterations=2),
            {"seed": {"count": 0}, "limit": 2},
        )


def test_loop_control_value_is_private_and_cannot_bind_downstream(
    system: Constructicon,
) -> None:
    from constructicon.core.graph import Connection

    component = register_loop_component(system)

    sink_def, sink_impl = atomic(
        "loop/control-sink",
        (CONTINUE,),
        (STATE,),
        control_sink_impl,
    )
    sink_version = system._register(sink_def, sink_impl)
    system._promote_initial(component=sink_def.name, version=sink_version)
    graph = Graph(
        name="control-is-private",
        nodes=(
            GraphNode(
                id="counter",
                body=Loop(
                    body=Ref(component=component),
                    feedback={"state": "state"},
                    continue_from="continue",
                    max_iterations=2,
                ),
            ),
            GraphNode(id="sink", body=Ref(component=sink_def.name)),
        ),
        connections=(Connection(src="counter", dst="sink"),),
        inputs=(SEED, LIMIT),
    )

    with pytest.raises(
        AdmissionError,
        match="no upstream output of type 'constructicon/continue'",
    ):
        system.validate(graph, {"seed": {"count": 0}, "limit": 2})


async def test_contradictory_iteration_checkpoint_refuses_before_reexecution(
    system: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    ADVANCE_CALLS.clear()
    component = register_loop_component(system)
    run_id = RunId("loop-contradictory-checkpoint")
    fired = False

    def crash_after_first_completion(name: str) -> None:
        nonlocal fired
        if name == "completion.after_commit" and not fired:
            fired = True
            raise InjectedCrash(name)

    journal.fault_probe = crash_after_first_completion
    with pytest.raises(InjectedCrash):
        await system._start_direct(
            loop_graph(component, max_iterations=3),
            {"seed": {"count": 0}, "limit": 2},
            run_id=run_id,
        )
    journal.fault_probe = lambda name: None

    loop_scope = ScopePath(segments=("bounded-counter", "counter"))
    frame = IterationFrame(loop=loop_scope, index=0)
    member_path = ExecutionPath(
        scope=loop_scope.child("body").child("$body"),
        iterations=(frame,),
    )
    first = journal.checkpoint(run_id, member_path)
    assert first is not None
    later_path = ExecutionPath(
        scope=member_path.scope,
        iterations=(IterationFrame(loop=loop_scope, index=1),),
    )
    contradictory = first.model_copy(
        update={
            "path": later_path,
            "input_hash": digest("inputs", 1, {"damaged": True}),
            "outputs": {
                name: envelope.model_copy(update={"path": later_path})
                for name, envelope in first.outputs.items()
            },
        }
    )
    clock.advance(31)
    injector = journal.claim_run(
        run_id,
        owner_id="contradictory-checkpoint-fixture",
        ttl_s=30,
    )
    journal.record_completion(injector, contradictory)
    journal.release_run(injector)

    with pytest.raises(CheckpointConflict, match="contradicts"):
        await system._resume_direct(run_id)
    assert ADVANCE_CALLS == [1]


async def test_checkpoint_after_terminal_false_is_journal_damage(
    system: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    ADVANCE_CALLS.clear()
    component = register_loop_component(system)
    run_id = RunId("loop-checkpoint-after-false")
    fired = False

    def crash_after_first_completion(name: str) -> None:
        nonlocal fired
        if name == "completion.after_commit" and not fired:
            fired = True
            raise InjectedCrash(name)

    journal.fault_probe = crash_after_first_completion
    with pytest.raises(InjectedCrash):
        await system._start_direct(
            loop_graph(component, max_iterations=2),
            {"seed": {"count": 0}, "limit": 1},
            run_id=run_id,
        )
    journal.fault_probe = lambda name: None

    loop_scope = ScopePath(segments=("bounded-counter", "counter"))
    member_scope = loop_scope.child("body").child("$body")
    first_path = ExecutionPath(
        scope=member_scope,
        iterations=(IterationFrame(loop=loop_scope, index=0),),
    )
    later_path = ExecutionPath(
        scope=member_scope,
        iterations=(IterationFrame(loop=loop_scope, index=1),),
    )
    first = journal.checkpoint(run_id, first_path)
    assert first is not None
    later = first.model_copy(
        update={
            "path": later_path,
            "outputs": {
                name: envelope.model_copy(update={"path": later_path})
                for name, envelope in first.outputs.items()
            },
        }
    )
    clock.advance(31)
    injector = journal.claim_run(
        run_id,
        owner_id="post-terminal-checkpoint-fixture",
        ttl_s=30,
    )
    journal.record_completion(injector, later)
    journal.release_run(injector)

    with pytest.raises(JournalDamaged, match="after terminal false"):
        await system._resume_direct(run_id)
