"""Deterministic RunHost recovery, capacity, and failure regressions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.control import RunRecord
from constructicon.core.identity import Digest, digest
from constructicon.core.run import (
    AttemptCause,
    OwnershipLost,
    ParkedWait,
    RunAttemptSuperseded,
    RunStatus,
)
from constructicon.runtime.walker import RunResult


class FatalWorkerCrash(BaseException):
    """A process-death-shaped worker failure that Exception handlers cannot hide."""


class AsyncClock:
    """Fake wall clock whose injected async sleeps advance without real time."""

    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)
        self._sleepers: dict[asyncio.Future[None], datetime] = {}

    def now(self) -> datetime:
        return self._now

    @property
    def sleeper_count(self) -> int:
        return len(self._sleepers)

    async def sleep(self, seconds: float) -> None:
        deadline = self._now + timedelta(seconds=seconds)
        if deadline <= self._now:
            return
        sleeper = asyncio.get_running_loop().create_future()
        self._sleepers[sleeper] = deadline
        try:
            await sleeper
        finally:
            self._sleepers.pop(sleeper, None)

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        for sleeper, deadline in tuple(self._sleepers.items()):
            if deadline <= self._now and not sleeper.done():
                sleeper.set_result(None)


class FakeJournal:
    """The bounded read surface RunHost is allowed to use."""

    def __init__(self, records: list[RunRecord]) -> None:
        self.records = {record.run_id: record for record in records}
        self.event_seqs = {record.run_id: 0 for record in records}
        # The wake surface: what each PARKED run waits on, and which of those
        # requests already carry a reply.
        self.parked: dict[RunId, tuple[Digest, ...]] = {}
        self.replies: dict[Digest, Digest] = {}
        self.latest_calls = 0
        self.page_calls = 0
        self.record_calls = 0
        self.max_event_calls = 0
        self.fail_latest: BaseException | None = None
        self.run_record_failures: list[BaseException] = []
        self.after_max_event_seq: Callable[[RunId], None] | None = None

    def run_record(self, run_id: RunId) -> RunRecord | None:
        self.record_calls += 1
        if self.run_record_failures:
            raise self.run_record_failures.pop(0)
        return self.records.get(run_id)

    def max_event_seq(self, run_id: RunId) -> int:
        self.max_event_calls += 1
        current = self.event_seqs.get(run_id, 0)
        if self.after_max_event_seq is not None:
            self.after_max_event_seq(run_id)
        return current

    def parked_waits(
        self,
        *,
        after: tuple[str, str] | None = None,
        through: tuple[str, str] | None = None,
        limit: int = 100,
    ) -> list[ParkedWait]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        records = self._filtered(statuses=(RunStatus.PARKED,))
        if after is not None:
            records = [record for record in records if self._key(record) > after]
        if through is not None:
            records = [record for record in records if self._key(record) <= through]
        return [
            ParkedWait(
                run_id=record.run_id,
                created_at=record.created_at,
                event_seq=self.event_seqs[record.run_id],
                requests=self.parked.get(record.run_id, ()),
            )
            for record in records[:limit]
        ]

    def answered_requests(self, requests: Sequence[Digest]) -> dict[Digest, Digest]:
        return {
            request: self.replies[request] for request in requests if request in self.replies
        }

    def latest_run_key(
        self,
        *,
        statuses: tuple[RunStatus, ...] | None = None,
    ) -> tuple[str, str] | None:
        self.latest_calls += 1
        if self.fail_latest is not None:
            raise self.fail_latest
        records = self._filtered(statuses=statuses)
        if not records:
            return None
        record = records[-1]
        return (record.created_at.isoformat(), str(record.run_id))

    def run_records(
        self,
        *,
        statuses: tuple[RunStatus, ...] | None = None,
        after: tuple[str, str] | None = None,
        through: tuple[str, str] | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        self.page_calls += 1
        records = self._filtered(statuses=statuses)
        if after is not None:
            records = [record for record in records if self._key(record) > after]
        if through is not None:
            records = [record for record in records if self._key(record) <= through]
        return records[:limit]

    def update(self, run_id: RunId, **changes: Any) -> None:
        record = self.records[run_id]
        status = changes.get("status", record.status)
        owner_id = changes.get("owner_id", record.owner_id)
        lease_expires_at = changes.get("lease_expires_at", record.lease_expires_at)
        if status is RunStatus.RUNNING:
            liveness = "live" if owner_id is not None and lease_expires_at else "lost"
        else:
            liveness = "not_applicable"
        self.records[run_id] = record.model_copy(
            update={
                **changes,
                "liveness": liveness,
            }
        )

    def _filtered(
        self,
        *,
        statuses: tuple[RunStatus, ...] | None,
    ) -> list[RunRecord]:
        records = self.records.values()
        if statuses is not None:
            records = (record for record in records if record.status in statuses)
        return sorted(records, key=self._key)

    @staticmethod
    def _key(record: RunRecord) -> tuple[str, str]:
        return (record.created_at.isoformat(), str(record.run_id))


class FakeSystem:
    """A worker surface with controllable claims, completions, and hard death."""

    def __init__(self, journal: FakeJournal, clock: AsyncClock) -> None:
        self.journal = journal
        self.clock = clock
        self.attempted: list[RunId] = []
        self.started: list[RunId] = []
        self.causes: dict[RunId, AttemptCause | None] = {}
        self.blockers: dict[RunId, asyncio.Event] = {}
        self.lose_once: set[RunId] = set()
        self.lose_unowned_once: set[RunId] = set()
        self.ownership_loss_ready: dict[RunId, asyncio.Event] = {}
        self.ownership_loss_release: dict[RunId, asyncio.Event] = {}
        self.crash_once: set[RunId] = set()
        self.terminal_once: dict[RunId, RunStatus] = {}
        self.terminal_persisted: dict[RunId, asyncio.Event] = {}
        self.terminal_release: dict[RunId, asyncio.Event] = {}
        self.abandoned: set[RunId] = set()
        self.running = 0
        self.max_running = 0

    async def _run_prepared(
        self,
        run_id: RunId,
        *,
        cancellation: str,
        expected_event_seq: int | None = None,
        expected_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> RunResult:
        assert cancellation == "abandon"
        self.causes[run_id] = cause
        self.attempted.append(run_id)
        durable = self.journal.records[run_id]
        if (
            expected_event_seq is not None and self.journal.event_seqs[run_id] != expected_event_seq
        ) or (expected_statuses is not None and durable.status not in expected_statuses):
            raise RunAttemptSuperseded("scripted atomic attempt fence")
        self.started.append(run_id)
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            if run_id in self.lose_once:
                self.lose_once.remove(run_id)
                self.journal.update(
                    run_id,
                    owner_id="other-host",
                    lease_expires_at=self.clock.now() + timedelta(seconds=30),
                )
                raise OwnershipLost("scripted claim race")
            if run_id in self.lose_unowned_once:
                self.lose_unowned_once.remove(run_id)
                raise OwnershipLost("scripted claim race without owner projection")
            if run_id in self.ownership_loss_ready:
                self.ownership_loss_ready[run_id].set()
                await self.ownership_loss_release[run_id].wait()
                self.ownership_loss_ready.pop(run_id, None)
                self.ownership_loss_release.pop(run_id, None)
                raise OwnershipLost("scripted delayed ownership loss")
            self.journal.update(
                run_id,
                status=RunStatus.RUNNING,
                owner_id="this-host",
                lease_expires_at=self.clock.now() + timedelta(seconds=30),
            )
            if run_id in self.crash_once:
                self.crash_once.remove(run_id)
                raise FatalWorkerCrash("scripted hard death")
            terminal_status = self.terminal_once.pop(run_id, None)
            if terminal_status is not None:
                self.journal.event_seqs[run_id] += 1
                self.journal.update(run_id, status=terminal_status)
                self.terminal_persisted[run_id].set()
                await self.terminal_release[run_id].wait()
                self.journal.update(
                    run_id,
                    owner_id=None,
                    lease_expires_at=None,
                )
                return RunResult(run_id=run_id, status=terminal_status, outputs={})
            blocker = self.blockers.get(run_id)
            if blocker is not None:
                await blocker.wait()
            self.journal.update(
                run_id,
                status=RunStatus.SUCCEEDED,
                owner_id=None,
                lease_expires_at=None,
            )
            return RunResult(run_id=run_id, status=RunStatus.SUCCEEDED, outputs={})
        except asyncio.CancelledError:
            self.abandoned.add(run_id)
            raise
        finally:
            self.running -= 1


def record(
    name: str,
    clock: AsyncClock,
    *,
    created_offset: int,
    status: RunStatus = RunStatus.PENDING,
    owner_id: str | None = None,
    lease_seconds: float | None = None,
) -> RunRecord:
    run_id = RunId(name)
    lease_expires_at = (
        clock.now() + timedelta(seconds=lease_seconds) if lease_seconds is not None else None
    )
    if status is RunStatus.RUNNING:
        liveness = "live" if owner_id is not None and lease_seconds else "lost"
    else:
        liveness = "not_applicable"
    return RunRecord(
        run_id=run_id,
        manifest_hash=digest("test-manifest", 1, {"run": name}),
        input_hash=digest("test-input", 1, {"run": name}),
        status=status,
        liveness=liveness,
        created_at=clock.now() + timedelta(seconds=created_offset),
        owner_id=owner_id,
        lease_expires_at=lease_expires_at,
    )


def host_for(
    system: FakeSystem,
    *,
    max_concurrency: int = 1,
    recovery_page_size: int = 2,
    on_failure: Callable[[RunId, BaseException], None] | None = None,
) -> RunHost:
    return RunHost(
        cast(Constructicon, system),
        journal=cast(Any, system.journal),
        max_concurrency=max_concurrency,
        recovery_page_size=recovery_page_size,
        on_failure=on_failure,
        now_fn=system.clock.now,
        sleep_fn=system.clock.sleep,
    )


async def eventually(predicate: Callable[[], bool], message: str) -> None:
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError(message)


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.PARKED])
async def test_capacity_full_explicit_resume_is_retained_without_waiter_tasks(
    status: RunStatus,
) -> None:
    clock = AsyncClock()
    first = RunId("run-a-active")
    resumed = RunId(f"run-b-{status.value}")
    journal = FakeJournal(
        [
            record(str(first), clock, created_offset=0),
            record(str(resumed), clock, created_offset=1, status=status),
        ]
    )
    system = FakeSystem(journal, clock)
    system.blockers[first] = asyncio.Event()
    system.blockers[resumed] = asyncio.Event()
    host = host_for(system)

    assert host.launch(first) == "queued"
    assert host.launch(resumed) == "queued"
    assert host.launch(resumed) == "coalesced_exact"
    await eventually(lambda: system.started == [first], "first worker did not start")
    assert host.active_run_ids == (first,)
    assert system.max_running == 1

    system.blockers[first].set()
    await eventually(lambda: resumed in system.started, "queued resume was lost at capacity")
    assert host.active_run_ids == (resumed,)
    assert system.max_running == 1
    system.blockers[resumed].set()
    await eventually(lambda: not host.active_run_ids, "resumed worker did not finish")
    await host.shutdown()


@pytest.mark.parametrize("status", [RunStatus.PENDING, RunStatus.RUNNING])
async def test_recovery_skips_every_live_owner_and_wakes_at_exact_lease_expiry(
    status: RunStatus,
) -> None:
    clock = AsyncClock()
    run_id = RunId(f"run-live-{status.value}")
    journal = FakeJournal(
        [
            record(
                str(run_id),
                clock,
                created_offset=0,
                status=status,
                owner_id="other-host",
                lease_seconds=30,
            )
        ]
    )
    system = FakeSystem(journal, clock)
    system.blockers[run_id] = asyncio.Event()
    host = host_for(system)

    await host.startup()
    await eventually(lambda: clock.sleeper_count == 1, "lease timer was not armed")
    scans_before_expiry = journal.latest_calls
    for _ in range(20):
        await asyncio.sleep(0)
    assert system.started == []
    assert journal.latest_calls == scans_before_expiry

    clock.advance(29)
    for _ in range(5):
        await asyncio.sleep(0)
    assert system.started == []
    clock.advance(1)
    await eventually(lambda: system.started == [run_id], "lease expiry did not wake recovery")
    system.blockers[run_id].set()
    await host.shutdown()


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.PARKED])
async def test_explicit_resume_retries_an_ownership_race_after_lease_expiry(
    status: RunStatus,
) -> None:
    clock = AsyncClock()
    run_id = RunId(f"run-raced-{status.value}")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0, status=status)])
    system = FakeSystem(journal, clock)
    system.lose_once.add(run_id)
    system.blockers[run_id] = asyncio.Event()
    host = host_for(system)

    host.launch(
        run_id,
        expected_event_seq=0,
        allowed_statuses=frozenset({status}),
    )
    await eventually(lambda: system.started == [run_id], "first resume did not attempt")
    await eventually(lambda: clock.sleeper_count == 1, "lost claim did not arm retry")
    clock.advance(30)
    await eventually(
        lambda: system.started == [run_id, run_id],
        "explicit resume disappeared after OwnershipLost",
    )
    system.blockers[run_id].set()
    await eventually(
        lambda: journal.records[run_id].status is RunStatus.SUCCEEDED,
        "retried resume did not finish",
    )
    await host.shutdown()


async def test_ownership_loss_without_owner_projection_uses_bounded_backoff() -> None:
    clock = AsyncClock()
    run_id = RunId("run-raced-without-owner")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0, status=RunStatus.FAILED)])
    system = FakeSystem(journal, clock)
    system.lose_unowned_once.add(run_id)
    system.blockers[run_id] = asyncio.Event()
    host = host_for(system)

    host.launch(run_id)
    await eventually(lambda: system.started == [run_id], "first resume did not attempt")
    await eventually(lambda: clock.sleeper_count == 1, "claim backoff was not armed")
    for _ in range(20):
        await asyncio.sleep(0)
    assert system.started == [run_id]
    clock.advance(0.09)
    for _ in range(5):
        await asyncio.sleep(0)
    assert system.started == [run_id]
    clock.advance(0.01)
    await eventually(
        lambda: system.started == [run_id, run_id],
        "claim retry did not run after bounded backoff",
    )
    system.blockers[run_id].set()
    await host.shutdown()


async def test_attempt_baseline_mismatch_discards_intent_without_launching() -> None:
    clock = AsyncClock()
    run_id = RunId("run-stale-attempt")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0, status=RunStatus.FAILED)])
    journal.event_seqs[run_id] = 4
    system = FakeSystem(journal, clock)
    host = host_for(system)

    assert (
        host.launch(
            run_id,
            expected_event_seq=3,
            allowed_statuses=frozenset({RunStatus.FAILED}),
        )
        == "queued"
    )
    await eventually(lambda: journal.max_event_calls == 1, "stale intent was not checked")
    assert system.started == []
    assert journal.max_event_calls == 1

    assert (
        host.launch(
            run_id,
            expected_event_seq=4,
            allowed_statuses=frozenset({RunStatus.FAILED}),
        )
        == "queued"
    )
    await eventually(
        lambda: journal.records[run_id].status is RunStatus.SUCCEEDED,
        "current intent did not finish",
    )
    await host.shutdown()


async def test_atomic_explicit_fence_closes_preflight_to_claim_race() -> None:
    clock = AsyncClock()
    run_id = RunId("run-explicit-atomic-fence")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0, status=RunStatus.FAILED)])
    journal.event_seqs[run_id] = 7

    def advance_attempt(selected_run_id: RunId) -> None:
        assert selected_run_id == run_id
        journal.after_max_event_seq = None
        journal.event_seqs[run_id] = 8
        journal.update(run_id, status=RunStatus.PARKED)

    journal.after_max_event_seq = advance_attempt
    system = FakeSystem(journal, clock)
    failures: list[tuple[RunId, BaseException]] = []
    host = host_for(system, on_failure=lambda failed, exc: failures.append((failed, exc)))

    host.launch(
        run_id,
        expected_event_seq=7,
        allowed_statuses=frozenset({RunStatus.FAILED}),
    )
    await eventually(lambda: system.attempted == [run_id], "superseded worker was not attempted")
    assert system.attempted == [run_id]
    assert system.started == []
    assert failures == []
    assert journal.records[run_id].status is RunStatus.PARKED
    await host.shutdown()


async def test_atomic_recovery_fence_cannot_resume_newly_failed_attempt() -> None:
    clock = AsyncClock()
    run_id = RunId("run-recovery-atomic-fence")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0)])

    def fail_after_selection(selected_run_id: RunId) -> None:
        assert selected_run_id == run_id
        journal.after_max_event_seq = None
        journal.event_seqs[run_id] = 1
        journal.update(run_id, status=RunStatus.FAILED)

    journal.after_max_event_seq = fail_after_selection
    system = FakeSystem(journal, clock)
    failures: list[tuple[RunId, BaseException]] = []
    host = host_for(system, on_failure=lambda failed, exc: failures.append((failed, exc)))

    await host.startup()
    await eventually(lambda: system.attempted == [run_id], "recovery claim was not attempted")
    await eventually(lambda: not host.active_run_ids, "superseded recovery did not drain")
    assert system.started == []
    assert failures == []
    assert journal.records[run_id].status is RunStatus.FAILED
    await host.shutdown()


async def test_duplicate_launch_restarts_failed_pump_and_retains_exact_intent() -> None:
    clock = AsyncClock()
    run_id = RunId("run-retry-dead-pump")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0, status=RunStatus.PARKED)])
    failure = RuntimeError("transient run-record read failure")
    journal.run_record_failures.append(failure)
    system = FakeSystem(journal, clock)
    host = host_for(system)
    contexts: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: contexts.append(context))
    try:
        assert (
            host.launch(
                run_id,
                expected_event_seq=0,
                allowed_statuses=frozenset({RunStatus.PARKED}),
            )
            == "queued"
        )
        await eventually(lambda: host.pump_failure is failure, "pump did not fail")

        assert (
            host.launch(
                run_id,
                expected_event_seq=0,
                allowed_statuses=frozenset({RunStatus.PARKED}),
            )
            == "coalesced_exact"
        )
        await eventually(
            lambda: journal.records[run_id].status is RunStatus.SUCCEEDED,
            "duplicate delivery did not revive the pump",
        )
        assert system.started == [run_id]
        assert contexts and contexts[-1]["exception"] is failure
    finally:
        loop.set_exception_handler(previous_handler)
        await host.shutdown()


async def test_duplicate_delivery_restarts_failed_pump_for_retained_intent() -> None:
    clock = AsyncClock()
    run_id = RunId("run-wait-restarts-pump")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0, status=RunStatus.FAILED)])
    failure = RuntimeError("transient queued-intent read failure")
    journal.run_record_failures.append(failure)
    system = FakeSystem(journal, clock)
    host = host_for(system)
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, _context: None)
    try:
        host.launch(
            run_id,
            expected_event_seq=0,
            allowed_statuses=frozenset({RunStatus.FAILED}),
        )
        await eventually(lambda: host.pump_failure is failure, "pump did not fail")
        assert (
            host.launch(
                run_id,
                expected_event_seq=0,
                allowed_statuses=frozenset({RunStatus.FAILED}),
            )
            == "coalesced_exact"
        )
        await eventually(
            lambda: journal.records[run_id].status is RunStatus.SUCCEEDED,
            "duplicate delivery did not revive the pump",
        )
        assert system.started == [run_id]
    finally:
        loop.set_exception_handler(previous_handler)
        await host.shutdown()


@pytest.mark.parametrize("terminal_status", [RunStatus.FAILED, RunStatus.PARKED])
async def test_new_resume_intent_survives_terminal_persist_before_worker_callback(
    terminal_status: RunStatus,
) -> None:
    clock = AsyncClock()
    run_id = RunId(f"run-terminal-before-callback-{terminal_status.value}")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0)])
    system = FakeSystem(journal, clock)
    system.terminal_once[run_id] = terminal_status
    system.terminal_persisted[run_id] = asyncio.Event()
    system.terminal_release[run_id] = asyncio.Event()
    system.blockers[run_id] = asyncio.Event()
    host = host_for(system)

    assert (
        host.launch(
            run_id,
            expected_event_seq=0,
            allowed_statuses=frozenset({RunStatus.PENDING}),
        )
        == "queued"
    )
    await system.terminal_persisted[run_id].wait()
    terminal_seq = journal.event_seqs[run_id]
    assert journal.records[run_id].status is terminal_status

    assert (
        host.launch(
            run_id,
            expected_event_seq=terminal_seq,
            allowed_statuses=frozenset({terminal_status}),
        )
        == "queued"
    )
    system.terminal_release[run_id].set()
    await eventually(
        lambda: system.started == [run_id, run_id],
        "post-terminal resume intent was dropped behind the unwinding worker",
    )
    system.blockers[run_id].set()
    await eventually(
        lambda: journal.records[run_id].status is RunStatus.SUCCEEDED,
        "post-terminal resume did not finish",
    )
    await host.shutdown()


async def test_newer_queued_intent_supersedes_stale_status_restriction() -> None:
    clock = AsyncClock()
    active = RunId("run-active-capacity-holder")
    target = RunId("run-queued-intent-superseded")
    journal = FakeJournal(
        [
            record(str(active), clock, created_offset=0),
            record(str(target), clock, created_offset=1),
        ]
    )
    system = FakeSystem(journal, clock)
    system.blockers[active] = asyncio.Event()
    system.blockers[target] = asyncio.Event()
    host = host_for(system)

    host.launch(active)
    await eventually(lambda: system.started == [active], "capacity holder did not start")
    assert (
        host.launch(
            target,
            expected_event_seq=0,
            allowed_statuses=frozenset({RunStatus.PENDING}),
        )
        == "queued"
    )

    journal.event_seqs[target] = 2
    journal.update(target, status=RunStatus.FAILED)
    assert (
        host.launch(
            target,
            expected_event_seq=2,
            allowed_statuses=frozenset({RunStatus.FAILED}),
        )
        == "queued"
    )
    assert (
        host.launch(
            target,
            expected_event_seq=2,
            allowed_statuses=frozenset({RunStatus.PENDING}),
        )
        == "superseded"
    )
    system.blockers[active].set()
    await eventually(
        lambda: system.started == [active, target],
        "newer queued intent did not supersede stale PENDING-only intent",
    )
    system.blockers[target].set()
    await eventually(lambda: not host.active_run_ids, "superseding attempt did not finish")
    await host.shutdown()


async def test_unguarded_same_baseline_intent_can_expand_but_not_replace_statuses() -> None:
    clock = AsyncClock()
    active = RunId("run-unguarded-capacity-holder")
    target = RunId("run-unguarded-no-weakening")
    journal = FakeJournal(
        [
            record(str(active), clock, created_offset=0),
            record(str(target), clock, created_offset=1, status=RunStatus.FAILED),
        ]
    )
    system = FakeSystem(journal, clock)
    system.blockers[active] = asyncio.Event()
    system.blockers[target] = asyncio.Event()
    host = host_for(system)

    host.launch(active)
    await eventually(lambda: system.started == [active], "capacity holder did not start")
    assert host.launch(target, allowed_statuses=frozenset({RunStatus.FAILED})) == "queued"
    assert (
        host.launch(
            target,
            allowed_statuses=frozenset({RunStatus.FAILED, RunStatus.PARKED}),
        )
        == "queued"
    )
    assert (
        host.launch(
            target,
            allowed_statuses=frozenset({RunStatus.PENDING}),
        )
        == "superseded"
    )

    system.blockers[active].set()
    await eventually(
        lambda: system.started == [active, target],
        "restrictive same-baseline intent replaced the legitimate queued resume",
    )
    system.blockers[target].set()
    await host.shutdown()


async def test_ownership_loss_cannot_overwrite_newer_queued_attempt_intent() -> None:
    clock = AsyncClock()
    run_id = RunId("run-newer-intent-survives-old-ownership-loss")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0, status=RunStatus.FAILED)])
    system = FakeSystem(journal, clock)
    system.ownership_loss_ready[run_id] = asyncio.Event()
    system.ownership_loss_release[run_id] = asyncio.Event()
    system.blockers[run_id] = asyncio.Event()
    host = host_for(system)

    assert (
        host.launch(
            run_id,
            expected_event_seq=0,
            allowed_statuses=frozenset({RunStatus.FAILED}),
        )
        == "queued"
    )
    await system.ownership_loss_ready[run_id].wait()

    journal.event_seqs[run_id] = 1
    journal.update(run_id, status=RunStatus.PARKED)
    assert (
        host.launch(
            run_id,
            expected_event_seq=1,
            allowed_statuses=frozenset({RunStatus.PARKED}),
        )
        == "queued"
    )
    system.ownership_loss_release[run_id].set()
    await eventually(lambda: clock.sleeper_count == 1, "claim backoff was not armed")
    clock.advance(0.1)
    await eventually(
        lambda: system.started == [run_id, run_id],
        "old OwnershipLost overwrote the newer queued intent",
    )
    system.blockers[run_id].set()
    await eventually(
        lambda: journal.records[run_id].status is RunStatus.SUCCEEDED,
        "newer queued attempt did not finish",
    )
    await host.shutdown()


async def test_recovery_pages_past_live_rows_and_refills_to_exhaust_snapshot() -> None:
    clock = AsyncClock()
    live = [RunId(f"run-0-live-{index}") for index in range(2)]
    recoverable = [RunId(f"run-1-recoverable-{index}") for index in range(5)]
    records = [
        record(
            str(run_id),
            clock,
            created_offset=index,
            owner_id="other-host",
            lease_seconds=100,
        )
        for index, run_id in enumerate(live)
    ]
    records.extend(
        record(str(run_id), clock, created_offset=index + 2)
        for index, run_id in enumerate(recoverable)
    )
    journal = FakeJournal(records)
    system = FakeSystem(journal, clock)
    for run_id in recoverable:
        system.blockers[run_id] = asyncio.Event()
    host = host_for(system, max_concurrency=2, recovery_page_size=2)

    await host.startup()
    await eventually(lambda: len(system.started) == 2, "recovery did not page past live rows")
    assert journal.page_calls >= 2
    assert set(system.started).isdisjoint(live)

    while len(system.started) < len(recoverable):
        for run_id in tuple(host.active_run_ids):
            system.blockers[run_id].set()
        previous = len(system.started)
        await eventually(
            lambda previous=previous: len(system.started) > previous,
            "capacity refill did not continue the durable snapshot",
        )
    for run_id in recoverable:
        system.blockers[run_id].set()
    await eventually(lambda: not host.active_run_ids, "recovered workers did not drain")
    assert set(system.started) == set(recoverable)
    assert system.max_running <= 2
    await host.shutdown()


async def test_startup_propagates_and_reports_initial_journal_failure() -> None:
    clock = AsyncClock()
    journal = FakeJournal([])
    failure = RuntimeError("journal unavailable")
    journal.fail_latest = failure
    system = FakeSystem(journal, clock)
    host = host_for(system)
    contexts: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: contexts.append(context))
    try:
        with pytest.raises(RuntimeError, match="journal unavailable"):
            await host.startup()
        assert host.pump_failure is failure
        assert contexts and contexts[-1]["exception"] is failure
    finally:
        loop.set_exception_handler(previous_handler)
        await host.shutdown()


async def test_later_pump_failure_is_observable_and_recover_is_truthfully_none() -> None:
    clock = AsyncClock()
    journal = FakeJournal([])
    system = FakeSystem(journal, clock)
    host = host_for(system)
    contexts: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: contexts.append(context))
    try:
        await host.startup()
        failure = RuntimeError("later scan failed")
        journal.fail_latest = failure
        assert host.recover(limit=1) is None
        await eventually(lambda: host.pump_failure is failure, "pump failure stayed silent")
        assert contexts and contexts[-1]["exception"] is failure
    finally:
        loop.set_exception_handler(previous_handler)
        await host.shutdown()


async def test_shutdown_abandons_worker_without_durable_cancel_intent() -> None:
    clock = AsyncClock()
    run_id = RunId("run-shutdown-abandon")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0)])
    system = FakeSystem(journal, clock)
    system.blockers[run_id] = asyncio.Event()
    host = host_for(system)

    host.launch(run_id)
    await eventually(lambda: system.started == [run_id], "worker did not start")
    await host.shutdown()
    durable = journal.records[run_id]
    assert system.abandoned == {run_id}
    assert durable.status is RunStatus.RUNNING
    assert durable.cancel_requested is False


async def test_hard_death_remains_visible_and_fresh_host_reclaims_after_expiry() -> None:
    clock = AsyncClock()
    run_id = RunId("run-hard-death")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0)])
    system = FakeSystem(journal, clock)
    system.crash_once.add(run_id)
    failures: list[tuple[RunId, BaseException]] = []
    first = host_for(system, on_failure=lambda failed_run, exc: failures.append((failed_run, exc)))

    first.launch(run_id)
    await eventually(lambda: len(failures) == 1, "hard death was hidden")
    assert failures[0][0] == run_id
    assert isinstance(failures[0][1], FatalWorkerCrash)
    assert system.started == [run_id]

    clock.advance(31)
    system.blockers[run_id] = asyncio.Event()
    second = host_for(system)
    await second.startup()
    await eventually(
        lambda: system.started == [run_id, run_id],
        "fresh host did not reclaim the hard-dead worker",
    )
    system.blockers[run_id].set()
    await first.shutdown()
    await second.shutdown()


async def test_older_worker_completion_cannot_retire_a_superseding_explicit_intent() -> None:
    """A stale done-callback must not retire the live attempt's resume fence.

    With spare capacity a superseding worker starts while the previous one is
    still unwinding, so the older callback fires last. If it retired the
    RunId's explicit intent, the live worker's `OwnershipLost` would find
    nothing to requeue and the resume command would silently never take effect
    — `FAILED` is not a recoverable status, so nothing else would revive it.
    """

    clock = AsyncClock()
    run_id = RunId("run-stale-callback-keeps-explicit-intent")
    journal = FakeJournal([record(str(run_id), clock, created_offset=0, status=RunStatus.FAILED)])
    system = FakeSystem(journal, clock)
    system.terminal_once[run_id] = RunStatus.FAILED
    system.terminal_persisted[run_id] = asyncio.Event()
    system.terminal_release[run_id] = asyncio.Event()
    host = host_for(system, max_concurrency=2)

    assert (
        host.launch(
            run_id,
            expected_event_seq=0,
            allowed_statuses=frozenset({RunStatus.FAILED}),
        )
        == "queued"
    )
    await system.terminal_persisted[run_id].wait()
    # The unwinding worker still holds its lease; let it expire so capacity,
    # not ownership, is what gates the superseding attempt.
    clock.advance(31)

    # The superseding attempt starts on spare capacity while the first unwinds.
    system.ownership_loss_ready[run_id] = asyncio.Event()
    system.ownership_loss_release[run_id] = asyncio.Event()
    assert (
        host.launch(
            run_id,
            expected_event_seq=1,
            allowed_statuses=frozenset({RunStatus.FAILED}),
        )
        == "queued"
    )
    await system.ownership_loss_ready[run_id].wait()

    # Only now does the older worker finish, and its done-callback must have
    # actually run before the live worker loses its claim.
    system.terminal_release[run_id].set()
    await eventually(
        lambda: journal.records[run_id].owner_id is None,
        "the older worker never released its lease",
    )
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(system.started) == 2 and host.active_run_ids == (run_id,)

    system.ownership_loss_release[run_id].set()
    await eventually(
        lambda: clock.sleeper_count == 1,
        "a stale completion erased the superseding explicit resume intent",
    )
    clock.advance(0.1)
    await eventually(
        lambda: len(system.started) == 3,
        "the retained explicit resume intent was never retried",
    )
    await host.shutdown()
