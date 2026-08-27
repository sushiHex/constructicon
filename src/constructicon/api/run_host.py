"""Process-local ownership of durable runs; never a graph scheduler (M6)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.errors import ConstructiconError
from constructicon.core.run import OwnershipLost
from constructicon.runtime.walker import RunResult


class RunHost:
    """Launch and recover prepared runs under one bounded process-local pool.

    The host chooses only which durable run has a worker coroutine. The walker
    remains the sole scheduler of graph units and invocations.
    """

    def __init__(
        self,
        system: Constructicon,
        *,
        max_concurrency: int = 4,
        on_failure: Callable[[RunId, BaseException], None] | None = None,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("RunHost max_concurrency must be positive")
        self._system = system
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._tasks: dict[RunId, asyncio.Task[RunResult | None]] = {}
        self._on_failure = on_failure
        self._closed = False

    @property
    def active_run_ids(self) -> tuple[RunId, ...]:
        return tuple(sorted(self._tasks))

    def launch(self, run_id: RunId) -> bool:
        """Ensure one local coroutine exists for ``run_id``; return if created."""

        if self._closed:
            raise RuntimeError("RunHost is closed")
        current = self._tasks.get(run_id)
        if current is not None and not current.done():
            return False
        task = asyncio.create_task(self._run(run_id), name=f"constructicon:{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda completed, rid=run_id: self._finished(rid, completed))
        return True

    def recover(self, *, limit: int = 100) -> tuple[RunId, ...]:
        launched: list[RunId] = []
        for run_id in self._system.journal.recoverable_runs(limit=limit):
            if self.launch(run_id):
                launched.append(run_id)
        return tuple(launched)

    async def wait(self, run_id: RunId) -> RunResult | None:
        task = self._tasks.get(run_id)
        if task is None:
            return None
        return await asyncio.shield(task)

    async def shutdown(self) -> None:
        """Abandon local work without writing durable cancellation intent."""

        self._closed = True
        tasks = tuple(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run(self, run_id: RunId) -> RunResult | None:
        async with self._semaphore:
            try:
                return await self._system.run_prepared(
                    run_id,
                    cancellation="abandon",
                )
            except asyncio.CancelledError:
                raise
            except OwnershipLost:
                # Another host owns the same durable run; the fence is the result.
                return None
            except ConstructiconError as exc:
                if self._on_failure is not None:
                    self._on_failure(run_id, exc)
                return None
            except BaseException as exc:
                if self._on_failure is not None:
                    self._on_failure(run_id, exc)
                return None

    def _finished(
        self,
        run_id: RunId,
        task: asyncio.Task[RunResult | None],
    ) -> None:
        current = self._tasks.get(run_id)
        if current is task:
            self._tasks.pop(run_id, None)
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.exception()
