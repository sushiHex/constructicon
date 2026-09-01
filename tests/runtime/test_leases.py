"""The walker owns every lease transition on every exit path — proven with
the I6 double, no git anywhere (M3 §5)."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.errors import JournalDamaged
from constructicon.core.graph import Graph, GraphNode, Loop, Ref
from constructicon.core.manifest import CONTINUE_SCHEMA_HASH, CONTINUE_TYPE
from constructicon.core.ports import Port
from constructicon.core.run import CheckpointConflict, OwnershipLost, RunStatus
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseClosure,
    LeaseContext,
    LeaseReconciliation,
    StaleAcquisition,
    acquisition_id_for,
    lease_id_for,
)
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.channels.in_process import InProcessChannel
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import (
    ISSUE,
    LEASE_TTL_S,
    SUMMARY,
    FakeClock,
    InjectedCrash,
    atomic,
)

INPUTS = {"issue": {"title": "lease me"}}

LOOP_STATE = Port(name="state", type_id="lease/State", schema_hash="lease-state-v1")
LOOP_AGAIN = Port(
    name="again",
    type_id=CONTINUE_TYPE,
    schema_hash=CONTINUE_SCHEMA_HASH,
    json_schema={"type": "boolean"},
)


@dataclass
class FakeLeasedCapability:
    """Same contract as the git workspace provider, zero git (I6)."""

    acquired: list[str] = field(default_factory=list)
    closed: list[tuple[str, str]] = field(default_factory=list)  # (acq, disposition)
    reconciled: list[tuple[str, str]] = field(default_factory=list)

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        lease_id = lease_id_for(
            context.run_lease.run_id, context.path, context.binding.binding
        )
        acquisition_id = acquisition_id_for(lease_id, context.run_lease.epoch)
        self.acquired.append(acquisition_id)
        return AcquiredCapability(
            resource={"token": acquisition_id},
            lease_id=lease_id,
            acquisition_id=acquisition_id,
            resource_ref=acquisition_id,
        )

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition
    ) -> LeaseClosure:
        self.closed.append((acquisition.acquisition_id, disposition))
        return LeaseClosure(
            disposition="discarded" if disposition == "discard" else "released"
        )

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...]
    ) -> LeaseReconciliation:
        for item in stale:
            self.reconciled.append((item.lease.resource_ref or "", item.disposition))
        return LeaseReconciliation(
            reaped=tuple(item.lease.resource_ref or "" for item in stale)
        )


@dataclass
class ChannelLaunderingCapability(FakeLeasedCapability):
    """A generic provider whose acquired resource violates its sealed kind."""

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        acquired = await super().acquire(context)
        return AcquiredCapability(
            resource=InProcessChannel(channel_id="smuggled"),
            lease_id=acquired.lease_id,
            acquisition_id=acquired.acquisition_id,
            resource_ref=acquired.resource_ref,
        )


class SuspendingCloseCapability(FakeLeasedCapability):
    """Expose the unrecorded-acquisition cancellation window deterministically."""

    def __init__(self, *, fail_close: bool = False) -> None:
        super().__init__()
        self.close_started = asyncio.Event()
        self.finish_close = asyncio.Event()
        self.fail_close = fail_close

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition
    ) -> LeaseClosure:
        self.close_started.set()
        await self.finish_close.wait()
        if self.fail_close:
            raise RuntimeError("unrecorded acquisition cleanup failed")
        return await super().close(acquisition, disposition)


async def leased_ok_impl(ctx: NodeContext, inputs: dict) -> dict:
    token = ctx.capability("cap")
    assert isinstance(token, dict) and "token" in token
    return {"summary": {"text": f"held {token['token'][:12]}"}}


async def leased_failing_impl(ctx: NodeContext, inputs: dict) -> dict:
    ctx.capability("cap")
    raise RuntimeError("node failed while holding a lease")


async def leased_dying_impl(ctx: NodeContext, inputs: dict) -> dict:
    ctx.capability("cap")
    raise InjectedCrash("simulated process death mid-node")


async def leased_loop_impl(ctx: NodeContext, inputs: dict) -> dict:
    token = ctx.capability("cap")
    assert isinstance(token, dict) and "token" in token
    value = int(inputs["state"]["value"]) + 1
    return {"state": {"value": value}, "again": value < 3}


def leased_graph() -> Graph:
    return Graph(
        name="leasing",
        nodes=(
            GraphNode(
                id="worker", body=Ref(component="test/leased", bind={"cap": "fake-leased"})
            ),
        ),
        inputs=(ISSUE,),
        outputs=(SUMMARY,),
    )


def leased_system(
    journal: SqliteJournal, impl: object
) -> tuple[Constructicon, FakeLeasedCapability]:
    capability = FakeLeasedCapability()
    system = Constructicon(
        journal=journal,
        capabilities={"fake-leased": capability},
        catalog={
            "fake-leased": CapabilityDescriptor(
                capability_id="fake-leased", kind="fake", revision="1", leased=True
            )
        },
        owner_id="worker-one",
        lease_ttl_s=LEASE_TTL_S,
    )
    definition, _ = atomic("test/leased", (ISSUE,), (SUMMARY,), impl)
    version = system._register(definition, impl)
    system._promote_initial(component="test/leased", version=version)
    return system, capability


def leased_loop_graph() -> Graph:
    return Graph(
        name="leased-loop",
        nodes=(
            GraphNode(
                id="repeat",
                body=Loop(
                    body=Ref(
                        component="test/leased-loop",
                        bind={"cap": "fake-leased"},
                    ),
                    feedback={"state": "state"},
                    continue_from="again",
                    max_iterations=5,
                ),
            ),
        ),
        inputs=(LOOP_STATE,),
        outputs=(LOOP_STATE,),
    )


def leased_loop_system(
    journal: SqliteJournal,
) -> tuple[Constructicon, FakeLeasedCapability]:
    capability = FakeLeasedCapability()
    system = Constructicon(
        journal=journal,
        capabilities={"fake-leased": capability},
        catalog={
            "fake-leased": CapabilityDescriptor(
                capability_id="fake-leased", kind="fake", revision="1", leased=True
            )
        },
        owner_id="loop-worker",
        lease_ttl_s=LEASE_TTL_S,
    )
    definition, _ = atomic(
        "test/leased-loop",
        (LOOP_STATE,),
        (LOOP_STATE, LOOP_AGAIN),
        leased_loop_impl,
    )
    version = system._register(definition, leased_loop_impl)
    system._promote_initial(component=definition.name, version=version)
    return system, capability


async def test_success_releases_the_lease(journal: SqliteJournal) -> None:
    system, capability = leased_system(journal, leased_ok_impl)
    result = await system._start_direct(leased_graph(), INPUTS, run_id=RunId("run-ok"))
    assert result.status is RunStatus.SUCCEEDED
    assert len(capability.acquired) == 1
    assert capability.closed == [(capability.acquired[0], "release")]
    rows = system._journal.capability_leases(RunId("run-ok"))
    assert [(r.state, r.disposition) for r in rows] == [("closed", "released")]


async def test_node_failure_discards_the_lease(journal: SqliteJournal) -> None:
    system, capability = leased_system(journal, leased_failing_impl)
    result = await system._start_direct(leased_graph(), INPUTS, run_id=RunId("run-fail"))
    assert result.status is RunStatus.FAILED
    assert capability.closed == [(capability.acquired[0], "discard")]
    rows = system._journal.capability_leases(RunId("run-fail"))
    assert [(r.state, r.disposition) for r in rows] == [("closed", "discarded")]


async def test_crash_leaves_the_lease_for_reconciliation(
    journal: SqliteJournal, clock: FakeClock
) -> None:
    """Simulated death: the row stays active; the reclaiming epoch discards
    the uncheckpointed acquisition and acquires a fresh one."""
    system, capability = leased_system(journal, leased_dying_impl)
    with pytest.raises(InjectedCrash):
        await system._start_direct(leased_graph(), INPUTS, run_id=RunId("run-dead"))
    rows = journal.capability_leases(RunId("run-dead"))
    assert [(r.state, r.disposition) for r in rows] == [("active", None)]
    assert capability.closed == []  # death runs no cleanup

    clock.advance(LEASE_TTL_S + 1)
    # heal the implementation in place (same registered identity, new behavior
    # is not allowed — so re-register a healthy component is not the path;
    # the run simply replays and dies again unless we resume with a healthy
    # system sharing the store)
    healthy, healthy_capability = leased_system(journal, leased_dying_impl)
    with pytest.raises(InjectedCrash):
        await healthy._resume_direct(RunId("run-dead"))
    rows = journal.capability_leases(RunId("run-dead"))
    # the first epoch's acquisition was reconciled and discarded before replay
    first_epoch_rows = [r for r in rows if r.acquisition_epoch == 1]
    assert [(r.state, r.disposition) for r in first_epoch_rows] == [
        ("closed", "discarded")
    ]
    assert healthy_capability.reconciled == [(capability.acquired[0], "discard")]
    # and the replaying epoch acquired a DIFFERENT physical acquisition
    assert healthy_capability.acquired != capability.acquired


async def test_forged_lease_closure_cannot_silently_abandon_the_resource(
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    run_id = RunId("run-forged-lease-closure")
    abandoned, abandoned_capability = leased_system(journal, leased_dying_impl)
    with pytest.raises(InjectedCrash):
        await abandoned._start_direct(leased_graph(), INPUTS, run_id=run_id)
    assert abandoned_capability.closed == []

    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE capability_leases"
            " SET state = 'closed', disposition = 'discarded'"
            " WHERE run_id = ?",
            (str(run_id),),
        )

    clock.advance(LEASE_TTL_S + 1)
    recovered, recovered_capability = leased_system(journal, leased_dying_impl)
    with pytest.raises(JournalDamaged, match="lifecycle contradicts its event chain"):
        await recovered._resume_direct(run_id)

    assert recovered_capability.reconciled == []
    assert abandoned_capability.closed == []


async def test_crash_after_completion_releases_on_reconcile(
    journal: SqliteJournal, clock: FakeClock
) -> None:
    """Completion durable, close missed: reconcile reaps with release — the
    checkpoint stands and the node restores instead of replaying."""
    system, capability = leased_system(journal, leased_ok_impl)

    def armed(name: str) -> None:
        if name == "completion.after_commit":
            raise InjectedCrash(name)

    journal.fault_probe = armed
    with pytest.raises(InjectedCrash):
        await system._start_direct(leased_graph(), INPUTS, run_id=RunId("run-late"))
    journal.fault_probe = lambda name: None
    clock.advance(LEASE_TTL_S + 1)

    second, second_capability = leased_system(journal, leased_ok_impl)
    result = await second._resume_direct(RunId("run-late"))
    assert result.status is RunStatus.SUCCEEDED
    assert second_capability.reconciled == [(capability.acquired[0], "release")]
    assert second_capability.acquired == []  # restored, never re-acquired
    kinds = [e.kind for e in journal.events(RunId("run-late"), limit=200)]
    assert "NodeRestored" in kinds


async def test_leased_declaration_requires_the_protocol(
    journal: SqliteJournal,
) -> None:
    system = Constructicon(
        journal=journal,
        capabilities={"fake-leased": object()},  # not a LeasedCapability
        catalog={
            "fake-leased": CapabilityDescriptor(
                capability_id="fake-leased", kind="fake", revision="1", leased=True
            )
        },
        owner_id="worker-one",
        lease_ttl_s=LEASE_TTL_S,
    )
    definition, _ = atomic("test/leased", (ISSUE,), (SUMMARY,), leased_ok_impl)
    version = system._register(definition, leased_ok_impl)
    system._promote_initial(component="test/leased", version=version)
    result = await system._start_direct(leased_graph(), INPUTS, run_id=RunId("run-bad-cap"))
    assert result.status is RunStatus.FAILED
    assert any("does not implement" in error for error in result.failures.values())


async def test_acquired_channel_cannot_escape_through_a_generic_lease(
    journal: SqliteJournal,
) -> None:
    capability = ChannelLaunderingCapability()
    system = Constructicon(
        journal=journal,
        capabilities={"fake-leased": capability},
        catalog={
            "fake-leased": CapabilityDescriptor(
                capability_id="fake-leased", kind="fake", revision="1", leased=True
            )
        },
        owner_id="worker-one",
        lease_ttl_s=LEASE_TTL_S,
    )
    definition, _ = atomic("test/leased", (ISSUE,), (SUMMARY,), leased_ok_impl)
    version = system._register(definition, leased_ok_impl)
    system._promote_initial(component="test/leased", version=version)

    result = await system._start_direct(
        leased_graph(), INPUTS, run_id=RunId("run-laundered-channel")
    )

    assert result.status is RunStatus.FAILED
    assert any("has no sealed channel binding" in error for error in result.failures.values())
    assert capability.closed == [(capability.acquired[0], "discard")]
    rows = journal.capability_leases(RunId("run-laundered-channel"))
    assert [(row.state, row.disposition) for row in rows] == [
        ("closed", "discarded")
    ]


async def test_unrecorded_acquisition_is_closed_without_a_lease_transition(
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system, capability = leased_system(journal, leased_ok_impl)

    def refuse_record(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise CheckpointConflict("lease record refused")

    monkeypatch.setattr(journal, "record_capability_lease", refuse_record)

    with pytest.raises(CheckpointConflict, match="lease record refused"):
        await system._start_direct(
            leased_graph(), INPUTS, run_id=RunId("run-unrecorded-acquisition")
        )

    assert capability.closed == [(capability.acquired[0], "discard")]
    assert journal.capability_leases(RunId("run-unrecorded-acquisition")) == []


@pytest.mark.parametrize("close_fails", [False, True], ids=["closed", "close-failed"])
async def test_cancellation_waits_for_unrecorded_acquisition_cleanup_and_preserves_failure(
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
    close_fails: bool,
) -> None:
    capability = SuspendingCloseCapability(fail_close=close_fails)
    system = Constructicon(
        journal=journal,
        capabilities={"fake-leased": capability},
        catalog={
            "fake-leased": CapabilityDescriptor(
                capability_id="fake-leased", kind="fake", revision="1", leased=True
            )
        },
        owner_id="worker-one",
        lease_ttl_s=LEASE_TTL_S,
    )
    definition, _ = atomic("test/leased", (ISSUE,), (SUMMARY,), leased_ok_impl)
    version = system._register(definition, leased_ok_impl)
    system._promote_initial(component=definition.name, version=version)

    def refuse_record(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise CheckpointConflict("lease record refused")

    monkeypatch.setattr(journal, "record_capability_lease", refuse_record)
    run_id = RunId("run-cancelled-unrecorded-acquisition")
    running = asyncio.create_task(
        system._start_direct(leased_graph(), INPUTS, run_id=run_id)
    )
    await capability.close_started.wait()

    running.cancel()
    await asyncio.sleep(0)
    running.cancel()
    await asyncio.sleep(0)
    assert not running.done()

    capability.finish_close.set()
    if close_fails:
        result = await running
        assert result.status is RunStatus.FAILED
        assert any(
            "unrecorded acquisition cleanup failed" in failure
            for failure in result.failures.values()
        )
        assert capability.closed == []
    else:
        with pytest.raises(asyncio.CancelledError):
            await running
        assert capability.closed == [(capability.acquired[0], "discard")]
    assert journal.capability_leases(run_id) == []


async def test_cancellation_during_a_later_unrecorded_cleanup_discards_recorded_siblings(
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = FakeLeasedCapability()
    second = SuspendingCloseCapability()
    system = Constructicon(
        journal=journal,
        capabilities={"leased-first": first, "leased-second": second},
        catalog={
            capability_id: CapabilityDescriptor(
                capability_id=capability_id,
                kind="fake",
                revision="1",
                leased=True,
            )
            for capability_id in ("leased-first", "leased-second")
        },
        owner_id="worker-one",
        lease_ttl_s=LEASE_TTL_S,
    )
    definition, _ = atomic("test/two-leases", (ISSUE,), (SUMMARY,), leased_ok_impl)
    version = system._register(definition, leased_ok_impl)
    system._promote_initial(component=definition.name, version=version)
    graph = Graph(
        name="two-leases-cancelled-cleanup",
        nodes=(
            GraphNode(
                id="worker",
                body=Ref(
                    component=definition.name,
                    bind={"first": "leased-first", "second": "leased-second"},
                ),
            ),
        ),
        inputs=(ISSUE,),
        outputs=(SUMMARY,),
    )
    original_record = journal.record_capability_lease
    records = 0

    def refuse_second_record(lease: Any, capability_lease: Any) -> None:
        nonlocal records
        records += 1
        if records == 2:
            raise CheckpointConflict("second lease record refused")
        original_record(lease, capability_lease)

    monkeypatch.setattr(journal, "record_capability_lease", refuse_second_record)
    run_id = RunId("run-two-lease-cancelled-cleanup")
    running = asyncio.create_task(system._start_direct(graph, INPUTS, run_id=run_id))
    await second.close_started.wait()

    running.cancel()
    await asyncio.sleep(0)
    assert not running.done()
    second.finish_close.set()

    with pytest.raises(asyncio.CancelledError):
        await running

    assert first.closed == [(first.acquired[0], "discard")]
    assert second.closed == [(second.acquired[0], "discard")]
    rows = journal.capability_leases(run_id)
    assert [(row.state, row.disposition) for row in rows] == [
        ("closed", "discarded")
    ]


async def test_ownership_loss_during_later_cleanup_leaves_recorded_siblings_to_successor(
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = FakeLeasedCapability()
    second = SuspendingCloseCapability()
    system = Constructicon(
        journal=journal,
        capabilities={"leased-first": first, "leased-second": second},
        catalog={
            capability_id: CapabilityDescriptor(
                capability_id=capability_id,
                kind="fake",
                revision="1",
                leased=True,
            )
            for capability_id in ("leased-first", "leased-second")
        },
        owner_id="worker-one",
        lease_ttl_s=LEASE_TTL_S,
    )
    definition, _ = atomic("test/two-leases", (ISSUE,), (SUMMARY,), leased_ok_impl)
    version = system._register(definition, leased_ok_impl)
    system._promote_initial(component=definition.name, version=version)
    graph = Graph(
        name="two-leases-lost-cleanup",
        nodes=(
            GraphNode(
                id="worker",
                body=Ref(
                    component=definition.name,
                    bind={"first": "leased-first", "second": "leased-second"},
                ),
            ),
        ),
        inputs=(ISSUE,),
        outputs=(SUMMARY,),
    )
    original_record = journal.record_capability_lease
    records = 0

    def lose_second_record(lease: Any, capability_lease: Any) -> None:
        nonlocal records
        records += 1
        if records == 2:
            raise OwnershipLost("a successor owns recorded leases")
        original_record(lease, capability_lease)

    monkeypatch.setattr(journal, "record_capability_lease", lose_second_record)
    run_id = RunId("run-two-lease-lost-cleanup")
    running = asyncio.create_task(system._start_direct(graph, INPUTS, run_id=run_id))
    await second.close_started.wait()

    running.cancel()
    await asyncio.sleep(0)
    assert not running.done()
    second.finish_close.set()

    with pytest.raises(OwnershipLost, match="successor owns"):
        await running

    assert first.closed == []
    assert second.closed == [(second.acquired[0], "discard")]
    rows = journal.capability_leases(run_id)
    assert [(row.state, row.disposition) for row in rows] == [("active", None)]


async def test_a_later_lease_record_conflict_discards_earlier_acquisitions(
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = FakeLeasedCapability()
    second = FakeLeasedCapability()
    system = Constructicon(
        journal=journal,
        capabilities={"leased-first": first, "leased-second": second},
        catalog={
            capability_id: CapabilityDescriptor(
                capability_id=capability_id,
                kind="fake",
                revision="1",
                leased=True,
            )
            for capability_id in ("leased-first", "leased-second")
        },
        owner_id="worker-one",
        lease_ttl_s=LEASE_TTL_S,
    )
    definition, _ = atomic("test/two-leases", (ISSUE,), (SUMMARY,), leased_ok_impl)
    version = system._register(definition, leased_ok_impl)
    system._promote_initial(component=definition.name, version=version)
    graph = Graph(
        name="two-leases",
        nodes=(
            GraphNode(
                id="worker",
                body=Ref(
                    component=definition.name,
                    bind={"first": "leased-first", "second": "leased-second"},
                ),
            ),
        ),
        inputs=(ISSUE,),
        outputs=(SUMMARY,),
    )
    original_record = journal.record_capability_lease
    records = 0

    def refuse_second_record(lease: Any, capability_lease: Any) -> None:
        nonlocal records
        records += 1
        if records == 2:
            raise CheckpointConflict("second lease record refused")
        original_record(lease, capability_lease)

    monkeypatch.setattr(journal, "record_capability_lease", refuse_second_record)

    with pytest.raises(CheckpointConflict, match="second lease record refused"):
        await system._start_direct(graph, INPUTS, run_id=RunId("run-two-lease-conflict"))

    assert len(first.acquired) + len(second.acquired) == 2
    closed = first.closed + second.closed
    assert len(closed) == 2
    assert {acquisition for acquisition, _disposition in closed} == set(
        first.acquired + second.acquired
    )
    assert {disposition for _acquisition, disposition in closed} == {"discard"}
    rows = journal.capability_leases(RunId("run-two-lease-conflict"))
    assert [(row.state, row.disposition) for row in rows] == [("closed", "discarded")]


async def test_loop_iterations_have_frame_distinct_lease_identities(
    journal: SqliteJournal,
) -> None:
    system, capability = leased_loop_system(journal)

    result = await system._start_direct(
        leased_loop_graph(),
        {"state": {"value": 0}},
        run_id=RunId("run-leased-loop"),
    )

    assert result.status is RunStatus.SUCCEEDED
    rows = journal.capability_leases(RunId("run-leased-loop"))
    assert len(rows) == 3
    assert len({row.lease_id for row in rows}) == 3
    assert sorted(row.path.iterations[0].index for row in rows) == [0, 1, 2]
    assert all(
        row.state == "closed" and row.disposition == "released" for row in rows
    )
    assert len(capability.acquired) == 3


async def test_stale_loop_lease_reconcile_uses_the_frame_checkpoint(
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    first, first_capability = leased_loop_system(journal)
    fired = False

    def crash_after_first_iteration_member(name: str) -> None:
        nonlocal fired
        if name == "completion.after_commit" and not fired:
            fired = True
            raise InjectedCrash(name)

    journal.fault_probe = crash_after_first_iteration_member
    with pytest.raises(InjectedCrash):
        await first._start_direct(
            leased_loop_graph(),
            {"state": {"value": 0}},
            run_id=RunId("run-loop-stale-lease"),
        )
    journal.fault_probe = lambda name: None
    active = journal.capability_leases(RunId("run-loop-stale-lease"))
    assert len(active) == 1 and active[0].state == "active"
    assert active[0].path.iterations[0].index == 0

    clock.advance(LEASE_TTL_S + 1)
    second, second_capability = leased_loop_system(journal)
    result = await second._resume_direct(RunId("run-loop-stale-lease"))

    assert result.status is RunStatus.SUCCEEDED
    assert second_capability.reconciled == [
        (first_capability.acquired[0], "release")
    ]
    rows = journal.capability_leases(RunId("run-loop-stale-lease"))
    first_row = next(row for row in rows if row.acquisition_epoch == 1)
    assert first_row.state == "closed" and first_row.disposition == "released"
