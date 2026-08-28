"""Shared frame-aware fake loop fixtures for hard-crash acceptance tests."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from constructicon.api.system import Constructicon
from constructicon.core.executor import Executor, TaskSpec
from constructicon.core.graph import Graph, GraphNode, Loop, Ref
from constructicon.core.manifest import CONTINUE_SCHEMA_HASH, CONTINUE_TYPE
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.external.fake import FakeExternalLedger
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import atomic

STATE = Port(name="state", type_id="loop-crash/State", schema_hash="state-v1")
AGAIN = Port(
    name="again",
    type_id=CONTINUE_TYPE,
    schema_hash=CONTINUE_SCHEMA_HASH,
    json_schema={"type": "boolean"},
)
SCRIPT = {
    "step-0": {"value": 1},
    "step-1": {"value": 2},
    "step-2": {"value": 3},
}
INPUTS = {"state": {"value": 0}}


async def hard_step_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    executor = ctx.capability("executor")
    assert isinstance(executor, FakeExecutor)
    typed: Executor = executor
    current = int(inputs["state"]["value"])
    outcome = await typed.execute(
        TaskSpec(instruction=f"step-{current}"),
        workspace=None,
        grants=ctx.grants,
    )
    assert outcome.status == "success"
    state = outcome.output
    assert isinstance(state, dict)
    return {"state": state, "again": int(state["value"]) < 3}


def loop_graph() -> Graph:
    return Graph(
        name="hard-crash-loop",
        nodes=(
            GraphNode(
                id="repeat",
                body=Loop(
                    body=Ref(
                        component="loop-crash/step",
                        bind={"executor": "fake-executor"},
                    ),
                    feedback={"state": "state"},
                    continue_from="again",
                    max_iterations=5,
                ),
            ),
        ),
        inputs=(STATE,),
        outputs=(STATE,),
    )


def build_loop_worker_system(
    journal_db: Path,
    external_db: Path,
    *,
    owner_id: str,
) -> tuple[Constructicon, SqliteJournal]:
    ledger = FakeExternalLedger(external_db)
    journal = SqliteJournal(journal_db)
    executor = FakeExecutor(dict(SCRIPT), ledger=ledger)
    system = Constructicon(
        journal=journal,
        capabilities={"fake-executor": executor},
        catalog={
            "fake-executor": CapabilityDescriptor(
                capability_id="fake-executor",
                kind="executor",
                revision="1",
                executor_profile=executor.profile,
            )
        },
        owner_id=owner_id,
    )
    definition, impl = atomic(
        "loop-crash/step",
        (STATE,),
        (STATE, AGAIN),
        hard_step_impl,
    )
    version = system._register(definition, impl)
    system._promote_initial(component=definition.name, version=version)
    return system, journal
