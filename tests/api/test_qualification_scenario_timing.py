"""Controlled observer ordering, not a reconstruction of the lost gate trace."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from constructicon.api import qualification
from constructicon.core.run import RunStatus
from tests.api import test_qualification_entry as entry
from tests.api import test_qualification_write_lifecycle as write

portable_binding = entry.portable_binding
substituted_guard = entry.substituted_guard
portable_write_boundary = write.portable_write_boundary


async def test_recovery_scenario_does_not_guess_crash_from_observer_timeout(
    tmp_path, portable_binding, substituted_guard, clock, monkeypatch,
):
    entered, release = asyncio.Event(), asyncio.Event()
    dying, drive = entry.dying_after_materialization, qualification._drive
    observer_budgets, premature_aborts, owned = [], [], []

    def held_materialization(provider, *args, **kwargs):
        dying(provider, *args, **kwargs)
        acquire = provider.acquire

        async def held_acquire(context):
            acquired = await acquire(context)
            materialize = acquired.materialize

            async def held():
                entered.set()
                await release.wait()
                await materialize()

            return replace(acquired, materialize=held)

        provider.acquire = held_acquire

    async def controlled_observer(**kwargs):
        observer_budgets.append(kwargs["timeout_s"])
        if len(observer_budgets) != 1:
            return await drive(**kwargs)
        # Hold real materialization before its crash, then choose which event
        # wins without sleeping out a wall-clock margin.
        running = asyncio.create_task(drive(**{**kwargs, "timeout_s": float("inf")}))
        waiting = asyncio.create_task(entered.wait())
        owned.extend((running, waiting))
        try:
            await asyncio.wait((running, waiting), return_when=asyncio.FIRST_COMPLETED)
            assert waiting.done() and not running.done(), "driver ended before materialization"
            if kwargs["timeout_s"] == 2:
                premature_aborts.append(not release.is_set())
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
                raise TimeoutError("controlled pre-crash observer timeout")
            release.set()
            return await running
        finally:
            for task in (running, waiting):
                if not task.done():
                    task.cancel()
            await asyncio.gather(running, waiting, return_exceptions=True)

    monkeypatch.setattr(entry, "dying_after_materialization", held_materialization)
    monkeypatch.setattr(qualification, "_drive", controlled_observer)
    try:
        await entry.test_a_successor_reconciles_and_acquires_only_within_the_budget(
            tmp_path, portable_binding, substituted_guard, clock,
            1, RunStatus.FAILED, [(1, "closed", "discarded")],
        )
    except AssertionError:
        assert premature_aborts == [True], "failure was not the controlled false crash scenario"
        raise
    assert observer_budgets == [float("inf"), 30]
    assert premature_aborts == [] and all(task.done() for task in owned)


@pytest.mark.parametrize("outcome", ["failed", "timeout", "cancelled"])
async def test_recovery_scenario_rejects_and_joins_an_early_observer(
    tmp_path, portable_binding, substituted_guard, clock, monkeypatch, outcome,
):
    pending_before, calls = asyncio.all_tasks(), []

    async def ended(**kwargs):
        calls.append(kwargs)
        assert kwargs["timeout_s"] == float("inf")
        assert kwargs["grants"] is entry.GRANTS
        assert "Infinity" not in kwargs["provider"].qualification.model_dump_json()
        if outcome == "timeout":
            raise TimeoutError("controlled observer end")
        if outcome == "cancelled":
            raise asyncio.CancelledError
        return RunStatus.FAILED

    monkeypatch.setattr(entry, "qualify", ended)
    with pytest.raises(AssertionError, match="observer ended before recorded crash"):
        await entry.test_a_successor_reconciles_and_acquires_only_within_the_budget(
            tmp_path, portable_binding, substituted_guard, clock,
            1, RunStatus.FAILED, [(1, "closed", "discarded")],
        )
    assert len(calls) == 1  # No purported crash or successor reconciliation.
    assert calls[0]["provider"].handles == []
    assert not (asyncio.all_tasks() - pending_before)


async def test_recovery_failure_watchdog_refuses_a_stalled_crash_witness(
    tmp_path, portable_binding, substituted_guard, clock, monkeypatch,
):
    pending_before = asyncio.all_tasks()
    entered, stopped = asyncio.Event(), asyncio.Event()
    calls, waiting, crashes = [], [], []
    dying = entry.dying_after_materialization

    def capture_crash(provider, crashed):
        crashes.append(crashed)
        dying(provider, crashed)

    async def stalled(**kwargs):
        calls.append(kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    class WatchdogAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        async def wait(self, tasks, *, return_when, timeout=None):
            await entered.wait()
            waiting.extend(tasks)
            assert len(tasks) == 2 and all(not task.done() for task in tasks)
            assert return_when is asyncio.FIRST_COMPLETED
            assert timeout == 30, "pending crash scenario has no finite failure watchdog"
            # Substitute only the wait primitive: expiration is an empty done
            # set, not a crash fact. No seconds-long stall supplies the proof.
            return set(), set(tasks)

    monkeypatch.setattr(entry, "asyncio", WatchdogAsyncio())
    monkeypatch.setattr(entry, "qualify", stalled)
    monkeypatch.setattr(entry, "dying_after_materialization", capture_crash)
    with pytest.raises(AssertionError, match="crash witness stalled before failure watchdog"):
        await entry.test_a_successor_reconciles_and_acquires_only_within_the_budget(
            tmp_path, portable_binding, substituted_guard, clock,
            1, RunStatus.FAILED, [(1, "closed", "discarded")],
        )
    assert len(calls) == 1 and calls[0]["provider"].handles == []
    assert len(crashes) == 1 and not crashes[0].is_set()
    assert stopped.is_set() and all(task.done() for task in waiting)
    assert not (asyncio.all_tasks() - pending_before)


async def test_write_scenario_waits_for_report_not_an_outer_scenario_timer(
    tmp_path, portable_binding, portable_write_boundary, monkeypatch,
):
    entered, release = asyncio.Event(), asyncio.Event()
    qualify_write = qualification.qualify_write
    timers, owned, completed = [], [], []

    class ScenarioAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @asynccontextmanager
        async def timeout(self, seconds):
            timers.append(seconds)
            caller = asyncio.current_task()

            async def expire_before_report():
                await entered.wait()
                assert not release.is_set()
                caller.cancel()

            expired = asyncio.create_task(expire_before_report())
            owned.append(expired)
            try:
                yield
            except asyncio.CancelledError:
                raise TimeoutError("controlled outer scenario timeout") from None
            finally:
                if not expired.done():
                    expired.cancel()
                await asyncio.gather(expired, return_exceptions=True)

    async def held_entry(**kwargs):
        entered.set()
        if not timers:
            release.set()
        await release.wait()
        report = await qualify_write(**kwargs)
        completed.append(report.observation)
        return report

    monkeypatch.setattr(write, "asyncio", ScenarioAsyncio())
    monkeypatch.setattr(qualification, "qualify_write", held_entry)
    try:
        await write.test_qualified_write_actual_entry_joins_and_reports_exact_candidate(
            tmp_path, portable_binding, portable_write_boundary, b"ready\n", True,
        )
    except TimeoutError:
        assert timers == [30] and entered.is_set() and not release.is_set()
        assert completed == [] and all(task.done() for task in owned)
        raise AssertionError("outer scenario timer aborted before the report") from None
    assert timers == [] and completed == ["terminal"]
