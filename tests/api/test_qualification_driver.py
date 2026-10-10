"""The shared qualification driver joins shutdown before publishing an outcome."""

import asyncio
from types import SimpleNamespace

import pytest

from constructicon.api import qualification
from constructicon.core.control import RunSubmission
from constructicon.core.run import RunStatus


@pytest.mark.parametrize("outcome", ["terminal", "timeout", "error"])
async def test_the_driver_joins_shutdown_on_every_observation(monkeypatch, outcome):
    assert callable(getattr(qualification, "_drive", None))
    entered = asyncio.Event()
    release = asyncio.Event()
    order = []

    class Control:
        def __init__(self, **kwargs):
            pass

        async def startup(self):
            order.append("startup")

        async def runs_start(self, actor, **kwargs):
            order.append("submit")
            assert kwargs["inputs"] == {"request": "fixed"}
            if outcome == "error":
                raise ValueError("submission failed")
            return RunSubmission.model_construct(run_id="run-test")

        async def shutdown(self):
            entered.set()
            await release.wait()
            order.append("shutdown")

    async def bootstrap(control, actor, definitions):
        assert definitions == ("writer", "checker")
        order.append("bootstrap")

    monkeypatch.setattr(qualification, "ControlPlane", Control)
    monkeypatch.setattr(qualification, "_bootstrap_definitions", bootstrap)
    state = RunStatus.RUNNING if outcome == "timeout" else RunStatus.SUCCEEDED
    journal = SimpleNamespace(run_record=lambda _: SimpleNamespace(status=state))
    task = asyncio.create_task(qualification._drive(
        system=object(), journal=journal, actor=object(), idempotency_key="fixed",
        expected_run_id="run-test", graph=object(), definitions=("writer", "checker"),
        inputs={"request": "fixed"}, timeout_s=0,
    ))
    await entered.wait()
    assert not task.done(), "an outcome cannot escape while shutdown is still pending"
    release.set()
    if outcome == "terminal":
        assert await task is RunStatus.SUCCEEDED
    else:
        with pytest.raises(TimeoutError if outcome == "timeout" else ValueError):
            await task
    assert order == ["startup", "bootstrap", "submit", "shutdown"]


async def test_repeated_cancellation_cannot_abandon_driver_shutdown(monkeypatch):
    assert callable(getattr(qualification, "_drive", None))
    entered = asyncio.Event()
    release = asyncio.Event()
    joined = []

    class Control:
        def __init__(self, **kwargs):
            pass

        async def startup(self):
            raise ValueError("startup failed")

        async def shutdown(self):
            entered.set()
            await release.wait()
            joined.append(True)

    monkeypatch.setattr(qualification, "ControlPlane", Control)
    task = asyncio.create_task(qualification._drive(
        system=object(), journal=object(), actor=object(), idempotency_key="fixed",
        expected_run_id="run-test", graph=object(), definitions=(), inputs={}, timeout_s=0,
    ))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and not joined
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert joined == [True]
