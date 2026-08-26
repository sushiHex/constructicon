"""The walker owns every lease transition on every exit path — proven with
the I6 double, no git anywhere (M3 §5)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.run import RunStatus
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


@dataclass
class FakeLeasedCapability:
    """Same contract as the git workspace provider, zero git (I6)."""

    acquired: list[str] = field(default_factory=list)
    closed: list[tuple[str, str]] = field(default_factory=list)  # (acq, disposition)
    reconciled: list[tuple[str, str]] = field(default_factory=list)

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        lease_id = lease_id_for(
            context.run_lease.run_id, context.binding.scope, context.binding.binding
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
    version = system.register(definition, impl)
    system.promote_initial(component="test/leased", version=version)
    return system, capability


async def test_success_releases_the_lease(journal: SqliteJournal) -> None:
    system, capability = leased_system(journal, leased_ok_impl)
    result = await system.start(leased_graph(), INPUTS, run_id=RunId("run-ok"))
    assert result.status is RunStatus.SUCCEEDED
    assert len(capability.acquired) == 1
    assert capability.closed == [(capability.acquired[0], "release")]
    rows = system.journal.capability_leases(RunId("run-ok"))
    assert [(r.state, r.disposition) for r in rows] == [("closed", "released")]


async def test_node_failure_discards_the_lease(journal: SqliteJournal) -> None:
    system, capability = leased_system(journal, leased_failing_impl)
    result = await system.start(leased_graph(), INPUTS, run_id=RunId("run-fail"))
    assert result.status is RunStatus.FAILED
    assert capability.closed == [(capability.acquired[0], "discard")]
    rows = system.journal.capability_leases(RunId("run-fail"))
    assert [(r.state, r.disposition) for r in rows] == [("closed", "discarded")]


async def test_crash_leaves_the_lease_for_reconciliation(
    journal: SqliteJournal, clock: FakeClock
) -> None:
    """Simulated death: the row stays active; the reclaiming epoch discards
    the uncheckpointed acquisition and acquires a fresh one."""
    system, capability = leased_system(journal, leased_dying_impl)
    with pytest.raises(InjectedCrash):
        await system.start(leased_graph(), INPUTS, run_id=RunId("run-dead"))
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
        await healthy.resume(RunId("run-dead"))
    rows = journal.capability_leases(RunId("run-dead"))
    # the first epoch's acquisition was reconciled and discarded before replay
    first_epoch_rows = [r for r in rows if r.acquisition_epoch == 1]
    assert [(r.state, r.disposition) for r in first_epoch_rows] == [
        ("closed", "discarded")
    ]
    assert healthy_capability.reconciled == [(capability.acquired[0], "discard")]
    # and the replaying epoch acquired a DIFFERENT physical acquisition
    assert healthy_capability.acquired != capability.acquired


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
        await system.start(leased_graph(), INPUTS, run_id=RunId("run-late"))
    journal.fault_probe = lambda name: None
    clock.advance(LEASE_TTL_S + 1)

    second, second_capability = leased_system(journal, leased_ok_impl)
    result = await second.resume(RunId("run-late"))
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
    version = system.register(definition, leased_ok_impl)
    system.promote_initial(component="test/leased", version=version)
    result = await system.start(leased_graph(), INPUTS, run_id=RunId("run-bad-cap"))
    assert result.status is RunStatus.FAILED
    assert any("does not implement" in error for error in result.failures.values())
