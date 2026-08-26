"""Shared fixtures: a small component world exercising the M1 vertical slice."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.component import ComponentDef, PythonRef
from constructicon.core.executor import Executor, TaskSpec
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.identity import digest
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import source_digest_for
from constructicon.runtime.validator import CapabilityDescriptor
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor

ISSUE = Port(name="issue", type_id="test/Issue", schema_hash="s1")
BRIEF = Port(name="brief", type_id="test/Brief", schema_hash="s1")
ANNOUNCED = Port(name="announced", type_id="test/Announced", schema_hash="s1")
SUMMARY = Port(name="summary", type_id="test/Summary", schema_hash="s1")


def atomic(
    name: str,
    inputs: tuple[Port, ...],
    outputs: tuple[Port, ...],
    impl: Any,
) -> tuple[ComponentDef, Any]:
    definition = ComponentDef(
        name=name,
        role="node",
        body=PythonRef(
            package="tests",
            module=impl.__module__,
            qualname=impl.__qualname__,
            contract_hash=digest(
                "component-contract",
                1,
                {
                    "inputs": [p.model_dump(mode="json") for p in inputs],
                    "outputs": [p.model_dump(mode="json") for p in outputs],
                },
            ),
            source_digest=source_digest_for(impl),
        ),
        inputs=inputs,
        outputs=outputs,
    )
    return definition, impl


async def triage_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    executor = ctx.capability("executor")
    assert isinstance(executor, FakeExecutor)
    typed: Executor = executor
    outcome = await typed.execute(
        TaskSpec(instruction="triage"), workspace=None, grants=ctx.grants
    )
    assert outcome.status == "success", outcome
    return {"brief": outcome.output}


async def announce_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    receipt = await ctx.effect("announce", {"title": inputs["brief"]["title"]})
    return {"announced": {"reference": receipt.external_reference}}


async def summarize_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"summary": {"text": f"summary of {inputs['brief']['title']}"}}


@pytest.fixture
def announce_effect() -> FakeAnnounceEffect:
    return FakeAnnounceEffect()


@pytest.fixture
def fake_executor() -> FakeExecutor:
    return FakeExecutor({"triage": {"title": "fix the flaky retry loop", "risk": "low"}})


@pytest.fixture
def system(
    tmp_path: Path, fake_executor: FakeExecutor, announce_effect: FakeAnnounceEffect
) -> Constructicon:
    from constructicon.substrate.journal.sqlite import SqliteJournal

    return Constructicon(
        journal=SqliteJournal(tmp_path / "journal.db"),
        capabilities={"fake-executor": fake_executor},
        catalog={
            "fake-executor": CapabilityDescriptor(
                capability_id="fake-executor",
                kind="executor",
                revision="1",
                executor_profile=fake_executor.profile,
            )
        },
        effects={"announce": announce_effect},
    )


@pytest.fixture
def world(system: Constructicon) -> Constructicon:
    """Register + promote the three test components (registration != promotion)."""
    for definition, impl in (
        atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl),
        atomic("test/announce", (BRIEF,), (ANNOUNCED,), announce_impl),
        atomic("test/summarize", (BRIEF,), (SUMMARY,), summarize_impl),
    ):
        version = system.register(definition, impl)
        system.promote_initial(component=definition.name, version=version)
    return system


def pipeline_graph() -> Graph:
    """triage -> announce -> summarize; summarize pulls `brief` from triage two
    steps upstream via the dataflow scope — the single-connector chain."""
    return Graph(
        name="issue-to-summary",
        nodes=(
            GraphNode(
                id="triage",
                body=Ref(component="test/triage", bind={"executor": "fake-executor"}),
            ),
            GraphNode(id="announce", body=Ref(component="test/announce")),
            GraphNode(id="summarize", body=Ref(component="test/summarize")),
        ),
        connections=(
            Connection(src="triage", dst="announce"),
            Connection(src="announce", dst="summarize"),
        ),
        inputs=(ISSUE,),
        outputs=(SUMMARY, ANNOUNCED),
    )
