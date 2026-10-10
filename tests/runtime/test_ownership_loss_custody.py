"""A live loser's custody must not outlive its ownership.

ADR 0018: cancellation/ownership loss quiesces work before returning. The
codex provider's handle keeps an exclusive acquisition guard until close, and
the walker never closes after ownership loss: disposition is the successor's.
While the losing process lives, the successor's reconciliation then waits on
that guard forever. This double retains exclusive custody exactly so, without
Linux: materialization takes a process-local lock that only close or
relinquishment releases, and reconciliation must take it before disposing.
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

Hook = Callable[["RetainingHandle"], Awaitable[None]]


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
        self.before_execute: Hook | None = None
        self.before_close: Hook | None = None
        self.before_relinquish: Hook | None = None
        self.closes: list[str] = []
        self.relinquished: list[str] = []
        self.acquisitions: list[AcquiredCapability] = []

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        acquisition = await super().acquire(context)
        handle = RetainingHandle(self, context, acquisition.acquisition_id)
        self.handles[-1] = handle
        retained = replace(acquisition, resource=handle, materialize=handle.materialize)
        self.acquisitions.append(retained)
        return retained

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition
    ) -> LeaseClosure:
        if self.before_close is not None:
            await self.before_close(acquisition.resource)
        self.closes.append(disposition)
        closure = await super().close(acquisition, disposition)
        acquisition.resource.release()
        return closure

    async def relinquish(self, acquisition: AcquiredCapability) -> None:
        if self.before_relinquish is not None:
            await self.before_relinquish(acquisition.resource)
        self.relinquished.append(acquisition.resource_ref)
        acquisition.resource.release()

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...]
    ) -> LeaseReconciliation:
        for item in stale:
            assert item.lease.resource_ref is not None
            async with self.custody.lock(item.lease.resource_ref):
                pass
        return await super().reconcile(context, stale)


@dataclass
class World:
    """A losing worker with one or two retaining bindings, and a clock to lose by."""

    journal: object
    clock: object
    ledger: AllocationLedger = field(default_factory=AllocationLedger)
    custody: Custody = field(default_factory=Custody)
    providers: dict[str, RetainingProvider] = field(default_factory=dict)

    def provider(self, key: str) -> RetainingProvider:
        return self.providers.setdefault(
            key, RetainingProvider(ledger=self.ledger, custody=self.custody)
        )

    def system(self, owner: str, providers: dict[str, RetainingProvider]) -> Constructicon:
        return Constructicon(
            journal=self.journal,
            owner_id=owner,
            capabilities=providers,
            catalog={key: value.descriptor(key) for key, value in providers.items()},
            lease_ttl_s=LEASE_TTL_S,
        )

    latched: asyncio.Event = field(default_factory=asyncio.Event)

    async def start(self, run_id: RunId, bindings: dict[str, str]):
        providers = {key: self.provider(key) for key in bindings.values()}
        system = self.system("loser", providers)
        system._walker._heartbeat_interval_s = 0.001
        heartbeat = self.journal.heartbeat

        def observe(*args, **kwargs):
            try:
                return heartbeat(*args, **kwargs)
            except OwnershipLost:
                self.latched.set()
                raise

        self.journal.heartbeat = observe
        graph = await register_component(system, self.journal, bindings=bindings)
        return asyncio.create_task(system._start_direct(graph, INPUTS, run_id=run_id))

    def lose(self, run_id: RunId):
        self.clock.advance(LEASE_TTL_S + 1)
        return self.journal.claim_run(run_id, owner_id="successor", ttl_s=LEASE_TTL_S)

    def held(self) -> list[bool]:
        return [
            self.custody.lock(handle.key).locked()
            for provider in self.providers.values()
            for handle in provider.handles
        ]

    def rows(self, run_id: RunId) -> list[tuple[str, str | None]]:
        return [
            (row.state, row.disposition) for row in self.journal.capability_leases(run_id)
        ]

    async def succeed(self, run_id: RunId, winner) -> None:
        """The successor's recovery completes: nothing is left to wait on."""
        self.journal.release_run(winner)
        fresh = {
            key: RetainingProvider(ledger=self.ledger, custody=self.custody)
            for key in self.providers
        }
        result = await asyncio.wait_for(
            self.system("successor", fresh)._resume_direct(run_id), 5
        )
        assert result.status is RunStatus.SUCCEEDED
        assert self.ledger.resources == set()


@pytest.fixture
def world(journal, clock) -> World:
    return World(journal=journal, clock=clock)


async def outcome(running: asyncio.Task) -> OwnershipLost:
    """The run's exception, asserted to be the loss. Collected, not propagated,
    so a mutant that lets a cancellation escape fails here as an assertion."""
    (result,) = await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), 5)
    assert isinstance(result, OwnershipLost), repr(result)
    return result


async def lose_mid_call(world: World, provider: RetainingProvider, run_id: RunId):
    """Hold the executor mid-call until a successor has claimed the run."""
    held, claimed = asyncio.Event(), asyncio.Event()

    async def hold(handle):
        held.set()
        await claimed.wait()
        assert handle.context.check_control is not None
        handle.context.check_control()

    provider.before_execute = hold
    return held, claimed


@pytest.mark.parametrize("observation", ["checked", "cancelled"])
async def test_a_live_loser_releases_custody_so_its_successor_can_reconcile(
    world, observation
):
    """Both ways a loss reaches the walker mid-call: the handle's own control
    check raises it, or a cancellation arrives after the heartbeat latched it."""
    run_id = RunId(f"live-loser-{observation}")
    executor = world.provider("retaining")
    held, claimed = await lose_mid_call(world, executor, run_id)
    if observation == "cancelled":
        async def hold_through_cancellation(handle):
            held.set()
            await asyncio.Event().wait()

        executor.before_execute = hold_through_cancellation
    running = await world.start(run_id, {"executor": "retaining"})

    await asyncio.wait_for(held.wait(), 5)
    assert world.held() == [True]
    winner = world.lose(run_id)
    if observation == "cancelled":
        # The heartbeat latches the loss; then the shutdown arrives.
        await asyncio.wait_for(world.latched.wait(), 5)
        running.cancel()
    else:
        claimed.set()
    await outcome(running)

    # The loser is alive and has returned. It wrote nothing durable and closed
    # nothing: disposition is the successor's. But it holds no custody either.
    assert executor.closes == []
    assert world.rows(run_id) == [("active", None)]
    assert world.held() == [False]
    await world.succeed(run_id, winner)


@pytest.mark.parametrize(
    "failure",
    [OSError("this custody would not release"), asyncio.CancelledError("relinquish cancelled")],
    ids=["error", "cancellation"],
)
async def test_one_failed_relinquishment_strands_no_sibling_and_the_loss_stays_primary(
    world, failure
):
    run_id = RunId(f"live-loser-failed-sibling-{type(failure).__name__}")
    executor = world.provider("retaining")
    sibling = world.provider("sibling")
    held, claimed = await lose_mid_call(world, executor, run_id)

    async def fail(handle):
        raise failure

    executor.before_relinquish = fail
    running = await world.start(run_id, {"executor": "retaining", "z": "sibling"})
    await asyncio.wait_for(held.wait(), 5)
    world.lose(run_id)
    claimed.set()
    loss = await outcome(running)

    assert loss.__cause__ is failure
    assert sibling.relinquished == [sibling.handles[0].key]
    assert world.held() == [True, False]


async def test_a_cancellation_during_relinquishment_leaves_the_loss_primary(world, monkeypatch):
    from constructicon.runtime.walker import Walker

    run_id = RunId("live-loser-cancelled-relinquishment")
    executor = world.provider("retaining")
    held, claimed = await lose_mid_call(world, executor, run_id)
    relinquishing, finish = asyncio.Event(), asyncio.Event()
    stops = []
    stop = Walker._stop_heartbeat

    async def tracked_stop(task):
        stops.append(finish.is_set())
        await stop(task)

    monkeypatch.setattr(Walker, "_stop_heartbeat", staticmethod(tracked_stop))

    async def slow(handle):
        relinquishing.set()
        await finish.wait()

    executor.before_relinquish = slow
    running = await world.start(run_id, {"executor": "retaining"})
    await asyncio.wait_for(held.wait(), 5)
    winner = world.lose(run_id)
    claimed.set()
    await asyncio.wait_for(relinquishing.wait(), 5)
    running.cancel()
    await asyncio.sleep(0)
    finish.set()
    await outcome(running)

    assert stops == [True], "the outer run returned before its owned release batch joined"
    assert world.held() == [False]
    await world.succeed(run_id, winner)


async def test_a_loss_found_while_closing_relinquishes_the_siblings_not_yet_closed(world):
    """Ownership loss first detected by a fenced row transition in ordinary close."""
    run_id = RunId("live-loser-found-in-close")
    executor = world.provider("retaining")
    sibling = world.provider("sibling")
    winners = []

    async def lose_before_the_row_closes(handle):
        if not winners:
            winners.append(world.lose(run_id))

    executor.before_close = lose_before_the_row_closes
    running = await world.start(run_id, {"executor": "retaining", "z": "sibling"})
    await outcome(running)

    assert executor.closes == ["release"] and executor.relinquished == []
    assert sibling.closes == [] and sibling.relinquished == [sibling.handles[0].key]
    assert world.held() == [False, False]
    assert world.rows(run_id) == [("active", None), ("active", None)]
    await world.succeed(run_id, winners[0])
