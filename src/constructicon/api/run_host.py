"""Process-local ownership of durable runs; never a graph scheduler (M6.1)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.control import (
    RESUMABLE_RUN_STATUSES,
    CommandRecord,
    ControlStore,
    RunRecord,
)
from constructicon.core.errors import ConstructiconError
from constructicon.core.journal import Journal
from constructicon.core.run import (
    AttemptCause,
    OwnershipLost,
    RunAttemptSuperseded,
    RunStatus,
)
from constructicon.runtime.walker import RunResult

FailureSink = Callable[[RunId, BaseException], None]
ResumeDecoder = Callable[[CommandRecord], tuple[RunId, int, str] | None]
LaunchDisposition = Literal["queued", "coalesced_exact", "superseded"]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], Coroutine[Any, Any, None]]
_RECOVERY_STATUSES = (RunStatus.PENDING, RunStatus.RUNNING)
_RECOVERY_STATUS_SET = frozenset(_RECOVERY_STATUSES)
_WorkerTask = asyncio.Task[RunResult | None]


@dataclass(frozen=True)
class _LaunchIntent:
    expected_event_seq: int | None
    allowed_statuses: frozenset[RunStatus]
    cause: AttemptCause | None = None


class RunHost:
    """Host a bounded set of durable run workers in this process.

    The host decides only which durable RunIds currently have a local coroutine.
    It never inspects a Graph, schedules graph units, or caches durable domain
    state; the walker and journal remain authoritative for all three.
    """

    def __init__(
        self,
        system: Constructicon,
        *,
        journal: Journal,
        max_concurrency: int = 4,
        on_failure: FailureSink | None = None,
        recovery_page_size: int = 100,
        resume_pages_per_tick: int = 4,
        resume_retry_s: float = 0.25,
        claim_retry_s: float = 0.1,
        now_fn: Clock | None = None,
        sleep_fn: Sleeper = asyncio.sleep,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("RunHost max_concurrency must be positive")
        if recovery_page_size <= 0:
            raise ValueError("RunHost recovery_page_size must be positive")
        if claim_retry_s <= 0:
            raise ValueError("RunHost claim_retry_s must be positive")
        if resume_pages_per_tick <= 0:
            raise ValueError("RunHost resume_pages_per_tick must be positive")
        if resume_retry_s <= 0:
            raise ValueError("RunHost resume_retry_s must be positive")
        self._system = system
        self._journal = journal
        self._max_concurrency = max_concurrency
        self._recovery_page_size = recovery_page_size
        self._claim_retry_s = claim_retry_s
        self._resume_pages_per_tick = resume_pages_per_tick
        self._resume_retry_s = resume_retry_s
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._sleep = sleep_fn
        self._tasks: dict[RunId, _WorkerTask] = {}
        # Explicit launches are process-local scheduling intent. Keeping RunIds,
        # rather than creating semaphore-waiting tasks, bounds local coroutines.
        self._requested: dict[RunId, _LaunchIntent] = {}
        self._explicit_tasks: dict[RunId, _LaunchIntent] = {}
        self._claim_retry_at: dict[RunId, datetime] = {}
        # A row that failed unexpectedly must remain durable and observable, but
        # this host must not spin on it. A fresh host or explicit operator action
        # can retry after the cause changes.
        self._deferred: set[RunId] = set()
        self._on_failure = on_failure
        self._closed = False
        self._wake = asyncio.Event()
        self._pump_task: asyncio.Task[None] | None = None
        self._scan_waiters: set[asyncio.Future[None]] = set()
        self._pump_failure: BaseException | None = None
        self._control_store: ControlStore | None = None
        self._resume_decoder: ResumeDecoder | None = None
        self._resume_through: tuple[str, str] | None = None
        self._resume_after: tuple[str, str] | None = None
        self._wait_through: tuple[str, str] | None = None
        self._wait_after: tuple[str, str] | None = None

    def _configure_committed_resumes(
        self,
        store: ControlStore,
        decoder: ResumeDecoder,
    ) -> None:
        if self._pump_task is not None:
            raise RuntimeError("committed resume recovery must be configured before startup")
        self._control_store = store
        self._resume_decoder = decoder

    @property
    def active_run_ids(self) -> tuple[RunId, ...]:
        return tuple(sorted(self._tasks))

    def is_assembled_from(self, system: Constructicon, journal: Journal) -> bool:
        """Whether this host runs the exact world the control plane serves."""

        return self._system is system and self._journal is journal

    @property
    def pump_failure(self) -> BaseException | None:
        """The most recent recovery-loop failure, if one stopped the pump."""

        return self._pump_failure

    async def startup(self) -> None:
        """Start recovery and await one complete, observable recovery scan."""

        if self._closed:
            raise RuntimeError("RunHost is closed")
        scanned = asyncio.get_running_loop().create_future()
        self._scan_waiters.add(scanned)
        self._ensure_pump()
        self._wake.set()
        try:
            await scanned
        finally:
            self._scan_waiters.discard(scanned)

    def recover(self, *, limit: int | None = None) -> None:
        """Fire-and-signal compatibility shim; use :meth:`startup` to observe it.

        Recovery is pump-owned and fully paged. A synchronous method cannot
        truthfully report which workers an asynchronous scan launched, so this
        shim deliberately has no result. ``limit`` remains accepted only for
        source compatibility and never truncates the durable snapshot.
        """

        del limit
        if self._closed:
            raise RuntimeError("RunHost is closed")
        self._ensure_pump()
        self._wake.set()

    def launch(
        self,
        run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> LaunchDisposition:
        """Queue explicit local scheduling intent without creating a waiter task.

        The return value reports whether new intent was accepted, not whether a
        worker happened to fit synchronously. The pump validates durable status
        and ownership before starting it.
        """

        if self._closed:
            raise RuntimeError("RunHost is closed")
        intent = _LaunchIntent(
            expected_event_seq=expected_event_seq,
            allowed_statuses=(
                RESUMABLE_RUN_STATUSES if allowed_statuses is None else allowed_statuses
            ),
            cause=cause,
        )
        current = self._tasks.get(run_id)
        queued = self._requested.get(run_id)
        if queued is not None:
            if queued == intent:
                self._ensure_pump()
                self._wake.set()
                return "coalesced_exact"
            accepted = self._supersedes(intent, queued)
            if accepted:
                self._requested[run_id] = intent
                self._deferred.discard(run_id)
                self._claim_retry_at.pop(run_id, None)
            # A prior scan may have failed after retaining this exact intent.
            # Duplicate delivery must be enough to revive the process-local pump.
            self._ensure_pump()
            self._wake.set()
            return "queued" if accepted else "superseded"
        if current is not None and not current.done():
            inflight = self._explicit_tasks.get(run_id)
            if inflight == intent:
                return "coalesced_exact"
            accepted = inflight is None or self._supersedes(intent, inflight)
            if accepted:
                # Keep the newer attempt behind the still-unwinding worker. Its
                # durable baseline will be checked after the callback frees capacity.
                self._requested[run_id] = intent
                self._deferred.discard(run_id)
                self._claim_retry_at.pop(run_id, None)
            self._ensure_pump()
            self._wake.set()
            return "queued" if accepted else "superseded"
        self._deferred.discard(run_id)
        self._claim_retry_at.pop(run_id, None)
        self._requested[run_id] = intent
        self._ensure_pump()
        self._wake.set()
        return "queued"

    async def shutdown(self) -> None:
        """Abandon local work without recording durable cancellation intent."""

        self._closed = True
        await self._abandon_local_state()

    async def abort_startup(self) -> None:
        """Reset a partial startup without permanently closing this host."""

        if self._closed:
            raise RuntimeError("RunHost is closed")
        await self._abandon_local_state()
        self._pump_failure = None

    async def _abandon_local_state(self) -> None:
        pump = self._pump_task
        if pump is not None and not pump.done():
            pump.cancel()
        tasks = tuple(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(
            *(item for item in (pump, *tasks) if item is not None),
            return_exceptions=True,
        )
        self._tasks.clear()
        self._requested.clear()
        self._explicit_tasks.clear()
        self._claim_retry_at.clear()
        self._deferred.clear()
        self._resume_through = None
        self._resume_after = None
        self._wait_through = None
        self._wait_after = None
        self._wake.clear()
        self._cancel_scan_waiters()
        self._pump_task = None

    def _ensure_pump(self) -> None:
        if self._pump_task is not None and not self._pump_task.done():
            return
        self._pump_failure = None
        pump = asyncio.create_task(self._pump(), name="constructicon:run-host")
        self._pump_task = pump
        pump.add_done_callback(self._pump_finished)

    def _start(
        self,
        run_id: RunId,
        *,
        intent: _LaunchIntent,
        explicit: bool,
    ) -> None:
        task = asyncio.create_task(
            self._run(run_id, intent),
            name=f"constructicon:{run_id}",
        )
        self._tasks[run_id] = task
        self._requested.pop(run_id, None)
        if explicit:
            self._explicit_tasks[run_id] = intent
        task.add_done_callback(lambda completed: self._finished(run_id, completed))

    async def _pump(self) -> None:
        while not self._closed:
            self._wake.clear()
            resume_expiry = self._earlier(
                self._scan_committed_resumes(),
                self._scan_answered_waits(),
            )
            next_expiry = self._earlier(self._fill_capacity(), resume_expiry)
            self._complete_scan_waiters()
            if self._closed:
                return
            await self._wait_for_work(next_expiry)

    def _scan_committed_resumes(self) -> datetime | None:
        store = self._control_store
        decoder = self._resume_decoder
        if store is None or decoder is None:
            return None
        if self._resume_through is None:
            self._resume_through = store.latest_command_key(operation="runs_resume")
            self._resume_after = None
            if self._resume_through is None:
                return self._now() + timedelta(seconds=self._resume_retry_s)
        through = self._resume_through
        assert through is not None
        for _ in range(self._resume_pages_per_tick):
            records = store.command_records(
                operation="runs_resume",
                after=self._resume_after,
                through=through,
                limit=self._recovery_page_size,
            )
            if not records:
                self._resume_through = None
                self._resume_after = None
                break
            for record in records:
                self._resume_after = (
                    record.created_at.isoformat(),
                    record.command_id,
                )
                if record.state == "prepared":
                    continue
                decoded = decoder(record)
                if decoded is None:
                    continue
                run_id, baseline, command_id = decoded
                self.launch(
                    run_id,
                    expected_event_seq=baseline,
                    allowed_statuses=RESUMABLE_RUN_STATUSES,
                    cause=AttemptCause(kind="resume_command", id=command_id),
                )
            if len(records) < self._recovery_page_size or (
                self._resume_after is not None and self._resume_after >= through
            ):
                self._resume_through = None
                self._resume_after = None
                break
        return self._now() + timedelta(seconds=self._resume_retry_s)

    def _scan_answered_waits(self) -> datetime | None:
        """Wake a PARKED run whose request already carries a stored reply.

        Recovery derives eligibility from durable domain facts, never command
        completion, so a death after a reply's domain transaction but before
        its command completes still produces the wake. Immutable writer command
        plans are consulted only to prove the reply's provenance; they do not
        reconstruct it or gate the wake on a terminal command state.

        PARKED deliberately never joins the ordinary recovery statuses: a
        parked run is waiting on a human, not on a lost worker, so only an
        observed reply may wake it. Scanning parking facts rather than
        watermarking replies also closes the race where a fast reply lands
        after a component's absence check but just before the park is recorded.

        The cut persists across ticks. Restarting it every tick would cap the
        scan at one bounded prefix, so a wait beyond `recovery_page_size *
        resume_pages_per_tick` unanswered rows would never be examined and its
        run would stay PARKED forever.
        """

        if self._wait_through is None:
            self._wait_through = self._journal.latest_run_key(statuses=(RunStatus.PARKED,))
            self._wait_after = None
            if self._wait_through is None:
                return self._now() + timedelta(seconds=self._resume_retry_s)
        through = self._wait_through
        for _ in range(self._resume_pages_per_tick):
            waits = self._journal.parked_waits(
                after=self._wait_after,
                through=through,
                limit=self._recovery_page_size,
            )
            if not waits:
                self._wait_through = None
                self._wait_after = None
                break
            answered = self._journal.answered_requests(
                [request for wait in waits for request in wait.requests]
            )
            for wait in waits:
                # Advance the cut BEFORE acting, so the next tick resumes past
                # this row rather than re-reading the same bounded prefix.
                self._wait_after = wait.key
                reply = next(
                    (answered[request] for request in wait.requests if request in answered),
                    None,
                )
                if reply is None:
                    continue
                self.launch(
                    wait.run_id,
                    expected_event_seq=wait.event_seq,
                    allowed_statuses=frozenset({RunStatus.PARKED}),
                    cause=AttemptCause(kind="channel_reply", id=str(reply)),
                )
            if len(waits) < self._recovery_page_size or (
                self._wait_after is not None and self._wait_after >= through
            ):
                self._wait_through = None
                self._wait_after = None
                break
        return self._now() + timedelta(seconds=self._resume_retry_s)

    def _fill_capacity(self) -> datetime | None:
        capacity = self._max_concurrency - len(self._tasks)
        if capacity <= 0:
            return None

        next_expiry: datetime | None = None
        now = self._now()
        for run_id, intent in sorted(self._requested.items()):
            record = self._journal.run_record(run_id)
            if record is None or record.status not in intent.allowed_statuses:
                self._requested.pop(run_id, None)
                self._claim_retry_at.pop(run_id, None)
                continue
            if (
                intent.expected_event_seq is not None
                and self._journal.max_event_seq(run_id) != intent.expected_event_seq
            ):
                self._requested.pop(run_id, None)
                self._claim_retry_at.pop(run_id, None)
                continue
            ready_at = self._ready_at(record, now)
            if ready_at is not None:
                next_expiry = self._earlier(next_expiry, ready_at)
                continue
            self._claim_retry_at.pop(run_id, None)
            self._start(run_id, intent=intent, explicit=True)
            capacity -= 1
            if capacity == 0:
                return next_expiry

        recovered, recovery_expiry = self._recoverable_batch(capacity, now=now)
        next_expiry = self._earlier(next_expiry, recovery_expiry)
        for run_id, intent in recovered:
            self._start(run_id, intent=intent, explicit=False)
        return next_expiry

    def _recoverable_batch(
        self,
        limit: int,
        *,
        now: datetime,
    ) -> tuple[tuple[tuple[RunId, _LaunchIntent], ...], datetime | None]:
        """Page until capacity is filled or the complete snapshot is exhausted."""

        if limit <= 0:
            return (), None
        through = self._journal.latest_run_key(statuses=_RECOVERY_STATUSES)
        if through is None:
            return (), None
        after: tuple[str, str] | None = None
        selected: list[tuple[RunId, _LaunchIntent]] = []
        next_expiry: datetime | None = None
        while len(selected) < limit:
            records = self._journal.run_records(
                statuses=_RECOVERY_STATUSES,
                after=after,
                through=through,
                limit=self._recovery_page_size,
            )
            if not records:
                break
            for record in records:
                after = (record.created_at.isoformat(), str(record.run_id))
                if (
                    record.run_id in self._tasks
                    or record.run_id in self._requested
                    or record.run_id in self._deferred
                ):
                    continue
                ready_at = self._ready_at(record, now)
                if ready_at is not None:
                    next_expiry = self._earlier(next_expiry, ready_at)
                    continue
                self._claim_retry_at.pop(record.run_id, None)
                selected.append(
                    (
                        record.run_id,
                        _LaunchIntent(
                            expected_event_seq=self._journal.max_event_seq(record.run_id),
                            allowed_statuses=_RECOVERY_STATUS_SET,
                        ),
                    )
                )
                if len(selected) == limit:
                    break
            if len(records) < self._recovery_page_size:
                break
        return tuple(selected), next_expiry

    async def _wait_for_work(self, next_expiry: datetime | None) -> None:
        if self._wake.is_set():
            return
        if next_expiry is None:
            await self._wake.wait()
            return
        delay = max(0.0, (next_expiry - self._now()).total_seconds())
        if delay == 0:
            await asyncio.sleep(0)
            return

        wake = asyncio.create_task(self._wake.wait(), name="constructicon:run-host-wake")
        timer: asyncio.Task[None] = asyncio.create_task(
            self._sleep(delay),
            name="constructicon:run-host-lease-expiry",
        )
        pending: set[asyncio.Task[object]] = {wake, timer}
        try:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for completed in done:
                completed.result()
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run(
        self,
        run_id: RunId,
        intent: _LaunchIntent,
    ) -> RunResult | None:
        try:
            return await self._system._run_prepared(
                run_id,
                cancellation="abandon",
                expected_event_seq=intent.expected_event_seq,
                expected_statuses=intent.allowed_statuses,
                cause=intent.cause,
            )
        except asyncio.CancelledError:
            raise
        except RunAttemptSuperseded:
            # The exact selected attempt no longer exists. This is neither a
            # worker failure nor ownership loss, and must never revive old intent.
            return None
        except OwnershipLost:
            self._claim_retry_at[run_id] = self._now() + timedelta(seconds=self._claim_retry_s)
            # Preserve explicit FAILED/PARKED resume intent across a claim race.
            # Ordinary PENDING/RUNNING recovery remains discoverable in the journal.
            if run_id in self._explicit_tasks and not self._closed:
                explicit_intent = self._explicit_tasks.get(run_id)
                queued = self._requested.get(run_id)
                if explicit_intent is not None and (
                    queued is None or self._supersedes(explicit_intent, queued)
                ):
                    self._requested[run_id] = explicit_intent
            return None
        except ConstructiconError as exc:
            self._report_failure(run_id, exc)
            return None
        except Exception as exc:
            self._report_failure(run_id, exc)
            return None
        # Deliberately do not catch BaseException. Hard-death signals remain task
        # failures and the durable run stays reclaimable after lease expiry.

    def _finished(self, run_id: RunId, task: _WorkerTask) -> None:
        # Only the worker still recorded here retires this RunId. A superseding
        # attempt owns the explicit resume fence from the moment ``_start`` records
        # it, so an older worker's completion must never erase it — ``OwnershipLost``
        # would then find no intent to requeue and drop the resume command.
        if self._tasks.get(run_id) is task:
            del self._tasks[run_id]
            self._explicit_tasks.pop(run_id, None)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None and not isinstance(exc, Exception):
                self._report_failure(run_id, exc)
        self._wake.set()

    def _pump_finished(self, task: asyncio.Task[None]) -> None:
        if self._pump_task is not task or task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            if self._closed:
                return
            exc = RuntimeError("Constructicon run-host recovery pump stopped unexpectedly")
        self._pump_failure = exc
        self._fail_scan_waiters(exc)
        task.get_loop().call_exception_handler(
            {
                "message": "Constructicon run-host recovery pump failed",
                "exception": exc,
            }
        )

    def _complete_scan_waiters(self) -> None:
        waiters = tuple(self._scan_waiters)
        self._scan_waiters.clear()
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)

    def _fail_scan_waiters(self, exc: BaseException) -> None:
        waiters = tuple(self._scan_waiters)
        self._scan_waiters.clear()
        for waiter in waiters:
            if not waiter.done():
                waiter.set_exception(exc)

    def _cancel_scan_waiters(self) -> None:
        waiters = tuple(self._scan_waiters)
        self._scan_waiters.clear()
        for waiter in waiters:
            if not waiter.done():
                waiter.cancel()

    def _ready_at(self, record: RunRecord, now: datetime) -> datetime | None:
        deadlines = [
            deadline
            for deadline in (
                self._claim_retry_at.get(record.run_id),
                (
                    record.lease_expires_at
                    if record.owner_id is not None and record.lease_expires_at is not None
                    else None
                ),
            )
            if deadline is not None and deadline > now
        ]
        return max(deadlines) if deadlines else None

    @staticmethod
    def _earlier(left: datetime | None, right: datetime | None) -> datetime | None:
        if right is None:
            return left
        if left is None or right < left:
            return right
        return left

    @staticmethod
    def _supersedes(incoming: _LaunchIntent, existing: _LaunchIntent) -> bool:
        """Order attempt-bound intent without letting an unbound retry weaken it."""

        if incoming == existing:
            return False
        incoming_seq = incoming.expected_event_seq
        existing_seq = existing.expected_event_seq
        if incoming_seq is None:
            return existing_seq is None and incoming.allowed_statuses > existing.allowed_statuses
        if existing_seq is None:
            return True
        if incoming_seq != existing_seq:
            return incoming_seq > existing_seq
        if incoming.cause != existing.cause:
            # At one fence an observed durable cause may replace ordinary
            # recovery, but the first distinct caused intent wins.
            return incoming.cause is not None and existing.cause is None
        # At one exact baseline, broaden the admissible durable observation only.
        # A stale restrictive delivery must never replace a legitimate resume.
        return incoming.allowed_statuses > existing.allowed_statuses

    def _report_failure(self, run_id: RunId, exc: BaseException) -> None:
        self._deferred.add(run_id)
        if self._on_failure is not None:
            self._on_failure(run_id, exc)
            return
        asyncio.get_running_loop().call_exception_handler(
            {
                "message": f"Constructicon run host failed for {run_id}",
                "exception": exc,
                "run_id": run_id,
            }
        )
