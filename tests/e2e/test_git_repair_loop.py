"""M4 acceptance: a real Git repair loop turns red to green and merges once."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import GitSha, RunId
from constructicon.core.envelope import GitRef
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.manifest import CONTINUE_SCHEMA_HASH, CONTINUE_TYPE
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.substrate.gates.runner import BoundGateRunner, MergeEvaluation
from constructicon.substrate.git.authority import StagedWriteWorkspace
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import LEASE_TTL_S, FakeClock, InjectedCrash, atomic
from tests.gitworld import (
    BROKEN_FIX,
    CANDIDATE,
    EVALUATION,
    GOAL,
    GOOD_FIX,
    MERGED,
    build_git_system,
)

AGAIN = Port(
    name="again",
    type_id=CONTINUE_TYPE,
    schema_hash=CONTINUE_SCHEMA_HASH,
    json_schema={"type": "boolean"},
)

INITIAL_COMMITS: list[GitSha] = []
REPAIR_COMMITS: list[GitSha] = []
REPAIR_CALLS: list[str] = []
NEVER_HEAL_COMMITS: list[GitSha] = []


async def initial_broken_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    workspace = ctx.capability("workspace")
    assert isinstance(workspace, StagedWriteWorkspace)
    Path(workspace.path, "calc.py").write_text(BROKEN_FIX)
    sha = workspace.commit_all("propose: intentionally red")
    INITIAL_COMMITS.append(sha)
    return {"candidate": workspace.git_ref().model_dump(mode="json")}


def _evaluation_payload(evaluation: MergeEvaluation) -> dict[str, Any]:
    return {
        "ok": evaluation.ok,
        "attestation_id": evaluation.attestation_id,
        "subject": (
            evaluation.subject.model_dump(mode="json")
            if evaluation.subject is not None
            else None
        ),
        "checks": [check.model_dump(mode="json") for check in evaluation.checks],
    }


async def repair_and_gate_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    workspace = ctx.capability("workspace")
    gates = ctx.capability("gates")
    assert isinstance(workspace, StagedWriteWorkspace)
    assert isinstance(gates, BoundGateRunner)

    previous = GitRef.model_validate(inputs["candidate"])
    workspace.reset_to(previous)
    calc = Path(workspace.path, "calc.py")
    current = calc.read_text()
    if "return a - b" in current:
        replacement = "def add(a: int, b: int) -> int:\n    return a * b\n"
        label = "still-red"
    elif "return a * b" in current:
        replacement = GOOD_FIX
        label = "green"
    else:
        raise RuntimeError(f"unexpected repair state: {current!r}")
    REPAIR_CALLS.append(label)
    calc.write_text(replacement)
    sha = workspace.commit_all(f"repair: {label}")
    REPAIR_COMMITS.append(sha)

    evaluation = gates.verify(sha)
    return {
        "candidate": workspace.git_ref().model_dump(mode="json"),
        "evaluation": _evaluation_payload(evaluation),
        "again": not evaluation.ok,
    }


async def never_heal_impl(
    ctx: NodeContext,
    inputs: Mapping[str, Any],
) -> Mapping[str, Any]:
    workspace = ctx.capability("workspace")
    gates = ctx.capability("gates")
    assert isinstance(workspace, StagedWriteWorkspace)
    assert isinstance(gates, BoundGateRunner)

    previous = GitRef.model_validate(inputs["candidate"])
    workspace.reset_to(previous)
    index = ctx.path.iterations[0].index
    Path(workspace.path, "calc.py").write_text(
        BROKEN_FIX + f"\n# still broken after attempt {index}\n"
    )
    commit = workspace.commit_all(f"repair: still red {index}")
    NEVER_HEAL_COMMITS.append(commit)
    evaluation = gates.verify(commit)
    return {
        "candidate": workspace.git_ref().model_dump(mode="json"),
        "evaluation": _evaluation_payload(evaluation),
        "again": True,
    }


def repair_graph(
    repair_component: str = "git/repair-and-gate",
    *,
    max_iterations: int = 3,
) -> Graph:
    return Graph(
        name="repair-until-green",
        nodes=(
            GraphNode(
                id="propose",
                body=Ref(
                    component="git/initial-broken",
                    bind={"workspace": "git-workspace"},
                ),
            ),
            GraphNode(
                id="repair",
                body=Loop(
                    body=Ref(
                        component=repair_component,
                        bind={
                            "workspace": "git-workspace",
                            "gates": "git-gates",
                        },
                    ),
                    feedback={"candidate": "candidate"},
                    continue_from="again",
                    max_iterations=max_iterations,
                ),
            ),
            GraphNode(id="merge", body=Ref(component="git/merge")),
        ),
        connections=(
            Connection(src="propose", dst="repair"),
            Connection(src="repair", dst="merge"),
        ),
        inputs=(GOAL,),
        outputs=(MERGED,),
    )


def register_repair_components(system: Constructicon) -> None:
    for definition, impl in (
        atomic("git/initial-broken", (GOAL,), (CANDIDATE,), initial_broken_impl),
        atomic(
            "git/repair-and-gate",
            (CANDIDATE,),
            (CANDIDATE, EVALUATION, AGAIN),
            repair_and_gate_impl,
        ),
    ):
        version = system._register(definition, impl)
        system._promote_initial(component=definition.name, version=version)


async def test_git_repair_loop_turns_red_green_and_installs_once(
    tmp_path: Path,
    journal: SqliteJournal,
) -> None:
    INITIAL_COMMITS.clear()
    REPAIR_COMMITS.clear()
    REPAIR_CALLS.clear()
    system, world = build_git_system(tmp_path, journal)
    register_repair_components(system)
    base = world.authority.resolve_ref("refs/heads/main")

    result = await system._start_direct(
        repair_graph(),
        {"goal": {"title": "repair", "content": BROKEN_FIX}},
        run_id=RunId("run-git-repair-loop"),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["merged"]["status"] == "committed"
    assert REPAIR_CALLS == ["still-red", "green"]
    assert len(INITIAL_COMMITS) == 1 and len(REPAIR_COMMITS) == 2
    assert world.authority.parents_of(REPAIR_COMMITS[0]) == (INITIAL_COMMITS[0],)
    assert world.authority.parents_of(REPAIR_COMMITS[1]) == (REPAIR_COMMITS[0],)

    installed = world.authority.resolve_ref("refs/heads/main")
    assert world.authority.parents_of(installed) == (base, REPAIR_COMMITS[1])
    kinds = [
        event.kind
        for event in journal.events(RunId("run-git-repair-loop"), limit=400)
    ]
    assert kinds.count("EffectCommitted") == 1
    assert kinds.count("LoopIterationCompleted") == 2

    workspace_rows = [
        row
        for row in journal.capability_leases(RunId("run-git-repair-loop"))
        if row.binding_id == "workspace" and row.path.iterations
    ]
    assert sorted(row.path.iterations[0].index for row in workspace_rows) == [0, 1]
    assert len({row.lease_id for row in workspace_rows}) == 2
    assert all(row.disposition == "released" for row in workspace_rows)


async def test_git_repair_loop_resume_restores_completed_iteration(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    INITIAL_COMMITS.clear()
    REPAIR_COMMITS.clear()
    REPAIR_CALLS.clear()
    db = tmp_path / "repair-resume.db"
    journal = SqliteJournal(db, now_fn=clock.now)
    first, _ = build_git_system(tmp_path, journal)
    register_repair_components(first)
    completions = 0

    def crash_after_first_repair(name: str) -> None:
        nonlocal completions
        if name == "completion.after_commit":
            completions += 1
            if completions == 2:  # initial proposal, then repair iteration zero
                raise InjectedCrash(name)

    journal.fault_probe = crash_after_first_repair
    with pytest.raises(InjectedCrash):
        await first._start_direct(
            repair_graph(),
            {"goal": {"title": "repair", "content": BROKEN_FIX}},
            run_id=RunId("run-git-repair-resume"),
        )
    journal.fault_probe = lambda name: None
    assert REPAIR_CALLS == ["still-red"]

    clock.advance(LEASE_TTL_S + 1)
    second, world = build_git_system(tmp_path, journal, owner_id="second-worker")
    register_repair_components(second)
    result = await second._resume_direct(RunId("run-git-repair-resume"))

    assert result.status is RunStatus.SUCCEEDED
    assert REPAIR_CALLS == ["still-red", "green"]
    assert len(REPAIR_COMMITS) == 2
    assert world.authority.parents_of(REPAIR_COMMITS[1]) == (REPAIR_COMMITS[0],)
    kinds = [
        event.kind
        for event in journal.events(RunId("run-git-repair-resume"), limit=500)
    ]
    assert "NodeRestored" in kinds
    assert kinds.count("EffectCommitted") == 1


async def test_never_healing_git_loop_parks_without_installing(
    tmp_path: Path,
    journal: SqliteJournal,
) -> None:
    INITIAL_COMMITS.clear()
    NEVER_HEAL_COMMITS.clear()
    system, world = build_git_system(tmp_path, journal)
    register_repair_components(system)
    definition, implementation = atomic(
        "git/never-heal",
        (CANDIDATE,),
        (CANDIDATE, EVALUATION, AGAIN),
        never_heal_impl,
    )
    version = system._register(definition, implementation)
    system._promote_initial(component=definition.name, version=version)
    before = world.authority.resolve_ref("refs/heads/main")

    result = await system._start_direct(
        repair_graph("git/never-heal", max_iterations=2),
        {"goal": {"title": "remain red", "content": BROKEN_FIX}},
        run_id=RunId("run-git-repair-parked"),
    )

    assert result.status is RunStatus.PARKED
    assert result.outputs == {}
    assert result.parked[0].reason == "policy_exhausted"
    assert world.authority.resolve_ref("refs/heads/main") == before
    assert len(INITIAL_COMMITS) == 1
    assert len(NEVER_HEAL_COMMITS) == 2
    assert world.authority.parents_of(NEVER_HEAL_COMMITS[0]) == (INITIAL_COMMITS[0],)
    assert world.authority.parents_of(NEVER_HEAL_COMMITS[1]) == (NEVER_HEAL_COMMITS[0],)
    kinds = [
        event.kind
        for event in journal.events(RunId("run-git-repair-parked"), limit=500)
    ]
    assert "RunParked" in kinds
    assert "EffectCommitted" not in kinds
    assert "EffectRejected" not in kinds
