"""Shared fixtures: a small component world exercising the vertical slice.

M2 additions: a controllable clock (lease expiry without sleeping), the
``InjectedCrash`` unit-lane crash (a BaseException, so the walker's
node-failure containment cannot launder simulated process death into FAILED),
and a deliberately failing component for dependency-blocking tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.component import ComponentDef, PythonRef
from constructicon.core.executor import Executor, TaskSpec
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.identity import digest
from constructicon.core.journal import Journal, JournalEvent
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor, source_digest_for
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal

_ATTEMPT_EVENTS = frozenset({"RunStarted", "RunResumed", "RunReclaimed"})
_TERMINAL_EVENTS = frozenset({"RunSucceeded", "RunFailed", "RunParked", "RunCancelled"})

ISSUE = Port(name="issue", type_id="test/Issue", schema_hash="s1")
BRIEF = Port(name="brief", type_id="test/Brief", schema_hash="s1")
REVIEW = Port(name="review", type_id="test/Review", schema_hash="s1")
ANNOUNCED = Port(name="announced", type_id="test/Announced", schema_hash="s1")
SUMMARY = Port(name="summary", type_id="test/Summary", schema_hash="s1")

LEASE_TTL_S = 30.0
TRIAGE_SCRIPT = {"triage": {"title": "fix the flaky retry loop", "risk": "low"}}


class InjectedCrash(BaseException):
    """Simulated process death at a named fault probe (the unit lane)."""


class FakeClock:
    """Deterministic time source; tests advance it past lease expiry."""

    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


async def await_attempt_terminal(
    journal: Journal,
    run_id: RunId,
    *,
    baseline_event_seq: int,
    expected_resume_command_id: str | None = None,
    timeout_s: float = 5.0,
) -> JournalEvent:
    """Test-only latch for one exact durable attempt and its terminal event."""

    transition: JournalEvent | None = None
    after = baseline_event_seq
    async with asyncio.timeout(timeout_s):
        while True:
            events = journal.events(run_id, after_seq=after, limit=100)
            for event in events:
                after = event.seq
                if transition is None:
                    if event.kind not in _ATTEMPT_EVENTS:
                        continue
                    actual_command_id = (event.payload or {}).get("resume_command_id")
                    if actual_command_id != expected_resume_command_id:
                        raise AssertionError(
                            "attempt transition carried the wrong resume command: "
                            f"expected {expected_resume_command_id!r}, got {actual_command_id!r}"
                        )
                    transition = event
                    continue
                if event.kind in _TERMINAL_EVENTS:
                    return event
            await asyncio.sleep(0)


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
    outcome = await typed.execute(TaskSpec(instruction="triage"), workspace=None, grants=ctx.grants)
    assert outcome.status == "success", outcome
    return {"brief": outcome.output}


async def announce_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    receipt = await ctx.effect("announce", {"title": inputs["brief"]["title"]})
    return {"announced": {"reference": receipt.external_reference}}


async def summarize_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"summary": {"text": f"summary of {inputs['brief']['title']}"}}


async def review_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"review": {"title": inputs["issue"]["title"]}}


async def failing_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    raise RuntimeError("scripted node failure")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def announce_effect() -> FakeAnnounceEffect:
    return FakeAnnounceEffect()


@pytest.fixture
def fake_executor() -> FakeExecutor:
    return FakeExecutor(dict(TRIAGE_SCRIPT))


@pytest.fixture
def journal(tmp_path: Path, clock: FakeClock) -> SqliteJournal:
    return SqliteJournal(tmp_path / "journal.db", now_fn=clock.now)


def build_system(
    journal: SqliteJournal,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
    *,
    owner_id: str,
) -> Constructicon:
    return Constructicon(
        journal=journal,
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
        owner_id=owner_id,
        lease_ttl_s=LEASE_TTL_S,
    )


@pytest.fixture
def system(
    journal: SqliteJournal,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> Constructicon:
    return build_system(journal, fake_executor, announce_effect, owner_id="worker-one")


@pytest.fixture
def world(system: Constructicon) -> Constructicon:
    """Register + promote the three test components (registration != promotion)."""
    for definition, impl in (
        atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl),
        atomic("test/announce", (BRIEF,), (ANNOUNCED,), announce_impl),
        atomic("test/summarize", (BRIEF,), (SUMMARY,), summarize_impl),
    ):
        version = system._register(definition, impl)
        system._promote_initial(component=definition.name, version=version)
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
