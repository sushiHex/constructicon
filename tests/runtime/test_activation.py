"""One activation path for start, resume, and reproduce: refuse — never
substitute — when the manifest's world cannot be reproduced exactly (M2 §3).

A crash followed by a code update must not execute an old run's suffix on new
code; a fresh host without the implementation must say so, not improvise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.errors import AdmissionError
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext, NodeImpl
from constructicon.runtime.registry import (
    CapabilityDescriptor,
    ComponentRegistry,
    InMemoryRegistryStore,
)
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import (
    LEASE_TTL_S,
    FakeClock,
    InjectedCrash,
    build_system,
    pipeline_graph,
)

INPUTS = {"issue": {"title": "retry loop is flaky"}}


async def drifted_summarize(ctx: NodeContext, inputs: dict) -> dict:
    return {"summary": {"text": "the updated code answers differently"}}


def test_activation_binds_a_complete_world(world: Constructicon) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)
    bound = world.registry.activate(manifest, catalog=world._catalog)
    atomics = [r for r in manifest.resolved_components]
    assert all(
        bound.bound(r.component, r.resolved_version).impl is not None for r in atomics
    )


def test_activation_refuses_a_missing_version(world: Constructicon) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)
    empty = ComponentRegistry(store=InMemoryRegistryStore())
    with pytest.raises(AdmissionError, match="not in the registry"):
        empty.activate(manifest, catalog=world._catalog)


def test_activation_refuses_a_missing_capability_or_revision(
    world: Constructicon,
) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)
    with pytest.raises(AdmissionError, match="not assembled"):
        world.registry.activate(manifest, catalog={})
    bumped = {
        "fake-executor": CapabilityDescriptor(
            capability_id="fake-executor", kind="executor", revision="2"
        )
    }
    with pytest.raises(AdmissionError, match="revision '2' differs"):
        world.registry.activate(manifest, catalog=bumped)


def test_activation_refuses_implementation_drift(world: Constructicon) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)
    version = next(
        r.resolved_version
        for r in manifest.resolved_components
        if r.component == "test/summarize"
    )
    # the host's installed implementation changed after admission
    drifted: NodeImpl = drifted_summarize
    world.registry._impls[("test/summarize", str(version))] = drifted
    with pytest.raises(AdmissionError, match=r"drift|differs from the manifest"):
        world.registry.activate(manifest, catalog=world._catalog)


async def test_resume_refuses_drift_after_a_crash(
    world: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """Crash mid-run, update the code, resume: the suffix must NOT execute on
    new code — activation refuses before a single node runs."""
    run_id = RunId("run-drift")

    def probe(name: str) -> None:
        if name == "completion.after_commit":  # die after the first checkpoint
            raise InjectedCrash(name)

    journal.fault_probe = probe
    with pytest.raises(InjectedCrash):
        await world.start(pipeline_graph(), INPUTS, run_id=run_id)
    journal.fault_probe = lambda name: None
    clock.advance(LEASE_TTL_S + 1)

    version = world.registry.stable_version("test/summarize")
    assert version is not None
    drifted: NodeImpl = drifted_summarize
    world.registry._impls[("test/summarize", str(version))] = drifted
    with pytest.raises(AdmissionError, match=r"drift|differs from the manifest"):
        await world.resume(run_id)
    state = world.journal.run_state(run_id)
    assert state is not None and state.status is RunStatus.RUNNING  # untouched


async def test_reproduce_refuses_drift_too(
    world: Constructicon, clock: FakeClock, tmp_path: Path
) -> None:
    source = RunId("run-repro-src")
    await world.start(pipeline_graph(), INPUTS, run_id=source)

    # a second worker over the same files, with a drifted in-process impl
    second_journal = SqliteJournal(tmp_path / "journal.db", now_fn=clock.now)
    second = build_system(
        second_journal, FakeExecutor({}), FakeAnnounceEffect(), owner_id="worker-two"
    )
    version = second.registry.stable_version("test/summarize")
    assert version is not None
    drifted: NodeImpl = drifted_summarize
    second.registry._impls[("test/summarize", str(version))] = drifted
    with pytest.raises(AdmissionError, match=r"drift|differs from the manifest"):
        await second.reproduce(source, new_run_id=RunId("run-repro-new"))


async def test_a_second_worker_resumes_from_durable_state_alone(
    world: Constructicon,
    journal: SqliteJournal,
    announce_effect: FakeAnnounceEffect,
    clock: FakeClock,
    tmp_path: Path,
) -> None:
    """The manifest's implementations load by module/qualname on a fresh host
    (no in-process registration) and digests verify against the manifest."""
    run_id = RunId("run-second-worker")

    def probe(name: str) -> None:
        if name == "completion.after_commit":
            raise InjectedCrash(name)

    journal.fault_probe = probe
    with pytest.raises(InjectedCrash):
        await world.start(pipeline_graph(), INPUTS, run_id=run_id)
    journal.fault_probe = lambda name: None
    clock.advance(LEASE_TTL_S + 1)

    from tests.conftest import TRIAGE_SCRIPT

    second_journal = SqliteJournal(tmp_path / "journal.db", now_fn=clock.now)
    second = build_system(
        second_journal,
        FakeExecutor(dict(TRIAGE_SCRIPT)),
        announce_effect,  # the same external world
        owner_id="worker-two",
    )
    result = await second.resume(run_id)
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["summary"] == {"text": "summary of fix the flaky retry loop"}
    assert len(announce_effect.executions) == 1


def test_loadability_reports_are_typed_and_host_local(world: Constructicon) -> None:
    snapshot = world.registry.snapshot()
    fresh = ComponentRegistry(store=world.registry.store)  # empty impl cache
    stored = snapshot.versions["test/summarize"]
    bound = fresh.bind(next(iter(stored.values())))
    assert bound.loadability.status == "loadable"  # importable module qualname
    assert bound.loadability.observed_digest == bound.loadability.expected_digest
