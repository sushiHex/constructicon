"""A live loser's custody must not outlive its ownership.

ADR 0018: cancellation/ownership loss quiesces work before returning. The
codex provider's handle keeps an exclusive acquisition guard until close, and
the walker never closes after ownership loss: disposition is the successor's.
While the losing process lives, the successor's reconciliation then waits on
that guard forever. This double retains exclusive custody exactly so, without
Linux: materialization takes a process-local lock that only close releases,
and reconciliation must take it before disposing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.run import OwnershipLost, RunStatus
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseClosure,
    LeaseContext,
    LeaseReconciliation,
    StaleAcquisition,
)
from tests.api.test_executor_admission import INPUTS
from tests.conftest import LEASE_TTL_S
from tests.executorworld import (
    AllocationLedger,
    FakeExecutorHandle,
    FakeExecutorProvider,
    register_component,
)


@dataclass
class Custody:
    """One exclusive claim per acquisition, shared like the physical guard file."""

    locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def lock(self, key: str) -> asyncio.Lock:
        return self.locks.setdefault(key, asyncio.Lock())


class RetainingHandle(FakeExecutorHandle):
    provider: RetainingProvider
    held = False

    async def materialize(self) -> None:
        # Like the codex handle: custody is retained only by a materialization
        # that succeeds; a failed one releases its own.
        lock = self.provider.custody.lock(self.key)
        await lock.acquire()
        try:
            await super().materialize()
        except BaseException:
            lock.release()
            raise
        self.held = True

    async def execute(self, task, *, workspace, grants):
        if self.provider.before_execute is not None:
            await self.provider.before_execute(self)
        return await super().execute(task, workspace=workspace, grants=grants)

    def release(self) -> None:
        if self.held:
            self.held = False
            self.provider.custody.lock(self.key).release()


class RetainingProvider(FakeExecutorProvider):
    def __init__(self, *, ledger: AllocationLedger, custody: Custody) -> None:
        super().__init__(ledger=ledger)
        self.custody = custody
        self.before_execute: Callable[[RetainingHandle], Awaitable[None]] | None = None

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        acquisition = await super().acquire(context)
        handle = RetainingHandle(self, context, acquisition.acquisition_id)
        self.handles[-1] = handle
        return replace(acquisition, resource=handle, materialize=handle.materialize)

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition
    ) -> LeaseClosure:
        closure = await super().close(acquisition, disposition)
        acquisition.resource.release()
        return closure

    async def relinquish(self, acquisition: AcquiredCapability) -> None:
        acquisition.resource.release()

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...]
    ) -> LeaseReconciliation:
        for item in stale:
            assert item.lease.resource_ref is not None
            async with self.custody.lock(item.lease.resource_ref):
                pass
        return await super().reconcile(context, stale)


def _system(journal, owner: str, provider: FakeExecutorProvider) -> Constructicon:
    return Constructicon(
        journal=journal,
        owner_id=owner,
        capabilities={"retaining": provider},
        catalog={"retaining": provider.descriptor("retaining")},
        lease_ttl_s=LEASE_TTL_S,
    )


@pytest.mark.parametrize("observation", ["checked", "cancelled"])
async def test_a_live_loser_releases_custody_so_its_successor_can_reconcile(
    journal, clock, monkeypatch, observation
):
    """Both ways a loss reaches the walker: the handle's own control check
    raises it, or the heartbeat latches it and cancels the invocation."""
    ledger, custody = AllocationLedger(), Custody()
    loser = RetainingProvider(ledger=ledger, custody=custody)
    system = _system(journal, "loser", loser)
    system._walker._heartbeat_interval_s = 0.001
    graph = await register_component(system, journal, bindings={"executor": "retaining"})

    held = asyncio.Event()
    lost = asyncio.Event()
    observed: list[OwnershipLost] = []
    closes: list[str] = []
    heartbeat = journal.heartbeat
    close = loser.close

    def observe_heartbeat(*args, **kwargs):
        try:
            return heartbeat(*args, **kwargs)
        except OwnershipLost as exc:
            observed.append(exc)
            lost.set()
            raise

    async def observe_close(acquisition, disposition):
        closes.append(disposition)
        return await close(acquisition, disposition)

    async def hold_until_lost(handle):
        # Materialized: the handle holds custody, and loses ownership mid-call.
        held.set()
        if observation == "cancelled":
            await asyncio.Event().wait()
        await lost.wait()
        assert handle.context.check_control is not None
        handle.context.check_control()

    monkeypatch.setattr(journal, "heartbeat", observe_heartbeat)
    monkeypatch.setattr(loser, "close", observe_close)
    loser.before_execute = hold_until_lost
    run_id = RunId("live-loser-custody")
    running = asyncio.create_task(system._start_direct(graph, INPUTS, run_id=run_id))

    await asyncio.wait_for(held.wait(), 5)
    (handle,) = loser.handles
    lock = custody.lock(handle.key)
    assert lock.locked()
    clock.advance(LEASE_TTL_S + 1)
    winner = journal.claim_run(run_id, owner_id="successor", ttl_s=LEASE_TTL_S)
    with pytest.raises(OwnershipLost) as caught:
        await asyncio.wait_for(running, 5)
    assert caught.value is observed[0]

    # The loser is alive and has returned. It wrote nothing durable and closed
    # nothing: disposition is the successor's. But it holds no custody either.
    assert closes == []
    assert [(row.state, row.disposition) for row in journal.capability_leases(run_id)] == [
        ("active", None),
    ]
    assert not lock.locked()

    journal.release_run(winner)
    successor = RetainingProvider(ledger=ledger, custody=custody)
    recovered = _system(journal, "successor", successor)
    result = await asyncio.wait_for(recovered._resume_direct(run_id), 5)
    assert result.status is RunStatus.SUCCEEDED
    assert successor.reconciled == [handle.key]
    assert ledger.resources == set()
