"""Process-local ownership of durable runs; never a graph scheduler (M6.1)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.errors import ConstructiconError
from constructicon.core.run import OwnershipLost, RunStatus

FailureSink = Callable[[RunId, BaseException], None]
_RECOVERY_STATUSES = (RunStatus.PENDING, RunStatus.RUNNING)


class RunHost:
    """Host a bounded set of durable run workers in this process.

    The host decides only which durable RunIds currently have a local coroutine.
    It never inspects a Graph, schedules graph units, or caches run results; the
    walker and journal remain authoritative for all three.
    """

    def __init__(
        self,
        system: Constructicon,
        *,
        max_concurrency: int = 4,
        on_failure: FailureSink | None = None,
        recovery_page_size: int = 100,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("RunHost max_concurrency must be positive")
        if recovery_page_size <= 0:
            raise ValueError("RunHost recovery_page_size must be positive")
        self._system = system
        self._max_concurrency = max_concurrency
        self._recovery_page_size = recovery_page_size
        self._tasks: dict[RunId, asyncio.Task[None]] = {}
        # A row that failed unexpectedly must remain durable and observable, but
        # this host must not spin on it. A fresh host or explicit operator action
        # can retry after the cause changes.
        self._deferred: set[RunId] = set()
        self._on_failure = on_failure
        self._closed = False
        self._wake = asyncio.Event()
        self._pump_task: asyncio.Task[None] | None = None

    @property
    def active_run_ids(self) -> tuple[RunId, ...]:
        return tuple(sorted(self._tasks))

    async def startup(self) -> None:
        """Begin bounded recovery of every PENDING or lost RUNNING row."""

        if self._closed:
            raise RuntimeError("RunHost is closed")
        self._ensure_pump()
        self._wake.set()
        # One turn makes startup observable without waiting for long-lived work.
        await asyncio.sleep(0)

    def launch(self, run_id: RunId) -> bool:
        """Ensure the durable run is considered without creating a waiting task."""

        if self._closed:
            raise RuntimeError("RunHost is closed")
        current = self._tasks.get(run_id)
        if current is not None and not current.done():
            return False
        self._deferred.discard(run_id)
        created = False
        if len(self._tasks) < self._max_concurrency:
            self._start(run_id)
            created = True
        # If capacity is full, the run remains PENDING in the journal. The pump
        # will discover it after a worker exits; no semaphore-waiting task piles up.
        self._ensure_pump()
        self._wake.set()
        return created

    async def shutdown(self) -> None:
        """Abandon local work without recording durable cancellation intent."""

        self._closed = True
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
        self._pump_task = None

    def _ensure_pump(self) -> None:
        if self._pump_task is None or self._pump_task.done():
            self._pump_task = asyncio.create_task(
                self._pump(),
                name="constructicon:run-host",
            )

    def _start(self, run_id: RunId) -> None:
        task = asyncio.create_task(self._run(run_id), name=f"constructicon:{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda completed: self._finished(run_id, completed))

    async def _pump(self) -> None:
        try:
            while not self._closed:
                self._wake.clear()
                capacity = self._max_concurrency - len(self._tasks)
                if capacity > 0:
                    for run_id in self._recoverable_batch(capacity):
                        self._start(run_id)
                if self._closed:
                    return
                if len(self._tasks) < self._max_concurrency:
                    # A just-started worker may complete before the callback wakes
                    # us. Yield once, then rescan the durable snapshot.
                    await asyncio.sleep(0)
                    if self._recoverable_batch(1):
                        self._wake.set()
                        continue
                await self._wake.wait()
        except asyncio.CancelledError:
            raise

    def _recoverable_batch(self, limit: int) -> tuple[RunId, ...]:
        """Page the full recovery snapshot, skipping this host's deferred rows."""

        if limit <= 0:
            return ()
        through = self._system.journal.latest_run_key(statuses=_RECOVERY_STATUSES)
        if through is None:
            return ()
        after: tuple[str, str] | None = None
        selected: list[RunId] = []
        while len(selected) < limit:
            records = self._system.journal.run_records(
                statuses=_RECOVERY_STATUSES,
                after=after,
                through=through,
                limit=self._recovery_page_size,
            )
            if not records:
                break
            for record in records:
                after = (record.created_at.isoformat(), str(record.run_id))
                if record.run_id in self._tasks or record.run_id in self._deferred:
                    continue
                if record.status is RunStatus.PENDING or (
                    record.status is RunStatus.RUNNING and record.liveness == "lost"
                ):
                    selected.append(record.run_id)
                    if len(selected) == limit:
                        break
            if len(records) < self._recovery_page_size:
                break
        return tuple(selected)

    async def _run(self, run_id: RunId) -> None:
        try:
            await self._system._run_prepared(run_id, cancellation="abandon")
        except asyncio.CancelledError:
            raise
        except OwnershipLost:
            # Another host owns the same durable run; the fence is the result.
            return
        except ConstructiconError as exc:
            self._report_failure(run_id, exc)
        except Exception as exc:
            self._report_failure(run_id, exc)
        # Deliberately do not catch BaseException. Hard-death signals remain task
        # failures and the durable run stays reclaimable after lease expiry.

    def _finished(self, run_id: RunId, task: asyncio.Task[None]) -> None:
        current = self._tasks.get(run_id)
        if current is task:
            self._tasks.pop(run_id, None)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None and not isinstance(exc, Exception):
                self._report_failure(run_id, exc)
        self._wake.set()

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
