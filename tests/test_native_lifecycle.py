"""Portable instrument checks; never credited as physical native proof."""

import asyncio
from contextlib import nullcontext
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.errors import ContractViolation
from constructicon.core.workspace import StaleAcquisition, acquisition_id_for
from constructicon.substrate.executors.linux import ProcessExchangeError, ProcessResult
from tests import native_lifecycle
from tests.native_lifecycle import NativeFixtureProvider
from tests.native_startup import MODELS
from tests.substrate.test_contained_workspace import context, stale_row


@pytest.fixture
def provider(tmp_path):
    return NativeFixtureProvider(
        tmp_path / "native", SimpleNamespace(closure=SimpleNamespace(require_open=Mock()),
                                             launcher=object()),
        SimpleNamespace(expected_runtime="test-only-runtime"), MODELS[0],
    )


async def test_native_acquire_and_unentered_close_write_nothing(provider, monkeypatch):
    dispose = AsyncMock(side_effect=AssertionError("unrecorded resource disposal"))
    monkeypatch.setattr(native_lifecycle, "dispose_acquisition", dispose)
    acquired = await provider.acquire(context())
    assert not provider.root.exists() and not acquired.resource.entered
    closed = await provider.close(acquired, "discard")
    assert closed.disposition == "discarded" and not provider.root.exists()
    dispose.assert_not_awaited()
    with pytest.raises(ContractViolation, match="closed"):
        await acquired.materialize()
    assert not provider.root.exists()


@pytest.mark.parametrize("field", ["root", "acquisition", "epoch", "binding", "path", "run"])
async def test_native_recovery_rejects_foreign_rows(provider, monkeypatch, field):
    dispose = AsyncMock()
    monkeypatch.setattr(native_lifecycle, "dispose_acquisition", dispose)
    ctx = context()
    acquired = await provider.acquire(ctx)
    stale = stale_row(acquired, ctx)
    changes = {
        "root": {"resource_ref": acquired.resource_ref.replace('"root":', '"foreign":')},
        "acquisition": {"resource_ref": acquired.resource_ref.replace("acq-", "other-")},
        "epoch": {"acquisition_epoch": 2, "resource_ref": provider.reference(
            acquisition_id_for(acquired.lease_id, 2),
        )},
        "binding": {"binding_id": "other"},
        "path": {"path": ExecutionPath(scope=ScopePath(segments=("root", "other")))},
        "run": {"run_id": "other-run"},
    }[field]
    stale = StaleAcquisition(stale.lease.model_copy(update=changes), "discard")
    with pytest.raises(ContractViolation, match="durable row"):
        await provider.reconcile(context(epoch=2), (stale,))
    dispose.assert_not_awaited()


async def test_native_recovery_disposes_durable_row_even_if_absent(provider, monkeypatch):
    dispose = AsyncMock()
    monkeypatch.setattr(native_lifecycle, "dispose_acquisition", dispose)
    ctx = context()
    acquired = await provider.acquire(ctx)
    assert not provider.root.exists()
    result = await provider.reconcile(context(epoch=2), (stale_row(acquired, ctx),))
    dispose.assert_awaited_once_with(provider.closure, acquired.resource.paths)
    assert result.reaped == (acquired.resource_ref,)


async def test_native_cleanup_failure_cannot_report_closed(provider, monkeypatch):
    monkeypatch.setattr(native_lifecycle, "dispose_acquisition",
                        AsyncMock(side_effect=RuntimeError("cleanup failed")))
    acquired = await provider.acquire(context())
    acquired.resource.entered = True
    with pytest.raises(RuntimeError, match="cleanup failed"):
        await provider.close(acquired, "release")
    with pytest.raises(RuntimeError, match="cleanup failed"):
        await provider.reconcile(context(epoch=2), (stale_row(acquired, context()),))


async def test_native_work_observes_control_and_closure(provider):
    control = Mock()
    acquired = await provider.acquire(replace(context(), check_control=control))
    handle = acquired.resource
    with pytest.raises(ContractViolation, match="not open"):
        await handle.require_open()
    handle.ready = True
    await handle.require_open()
    assert control.call_count == 2
    provider.closure.require_open.assert_called_once_with(handle.paths)
    provider.closure.require_open.side_effect = ContractViolation("permanent closure")
    with pytest.raises(ContractViolation, match="permanent closure"):
        await handle.require_open()
    provider.closure.require_open.side_effect = None
    control.side_effect = ContractViolation("revoked")
    with pytest.raises(ContractViolation, match="revoked"):
        await handle.require_open()


async def test_duplex_fixture_borrows_recorded_guard_without_relocking(monkeypatch, tmp_path):
    from tests.substrate import test_linux_duplex as duplex

    guard = Mock(side_effect=AssertionError("second guard would deadlock"))
    monkeypatch.setattr(duplex, "acquisition_guard", guard)
    launcher = SimpleNamespace(exchange=AsyncMock(return_value="observed"))
    callback = AsyncMock()
    assert await duplex.exchange(launcher, tmp_path, callback, guard_fd=41) == "observed"
    guard.assert_not_called()
    assert launcher.exchange.call_args.kwargs["guard_fds"] == (41,)
    assert launcher.exchange.call_args.kwargs["conversation"] is callback


async def test_native_checks_closure_after_guard_before_endpoint(provider, monkeypatch):
    from contextlib import asynccontextmanager

    held = False

    @asynccontextmanager
    async def guard(paths):
        nonlocal held
        held = True
        yield 41
        held = False

    monkeypatch.setattr(native_lifecycle, "acquisition_guard", guard)
    acquired = await provider.acquire(replace(context(), check_control=lambda: None))
    handle = acquired.resource
    handle.ready = True

    def require_open(paths):
        assert held and paths == handle.paths

    async def endpoint(workspace, fd):
        assert held and fd == 41
        provider.closure.require_open.assert_called_once_with(handle.paths)
        return "checked"

    provider.closure.require_open.side_effect = require_open
    monkeypatch.setattr(handle, "exchange_owned", endpoint)
    assert await handle.exchange(None) == "checked"
    assert not held


async def test_fixture_graph_admits_without_a_production_executor_profile(tmp_path):
    from constructicon.api.control import ControlPlane
    from constructicon.core.admission import AdmissionAccepted
    from tests.gitworld import seed_authority

    seed_authority(tmp_path)
    image = SimpleNamespace(expected_runtime="portable-fixture-only")
    system, journal, _ = native_lifecycle.assemble(tmp_path, launcher=object(), image=image)
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        graph = await native_lifecycle.register_native(control)
        admitted = system.admit_graph(graph, {"goal": {"message": "native fixture"}})
        assert isinstance(admitted, AdmissionAccepted), admitted
        assert system.describe_component("test/native-fixture").name == "test/native-fixture"
        assert system.rdeps("test/native-fixture") == []
        assert not any(item.executor_profile for item in system.describe().capabilities)
        assert system.describe().grants.root_grants.network == "allow"
        assert all(binding.effective_grants.network == "allow"
                   for binding in admitted.manifest.capability_bindings)
    finally:
        await control.shutdown()


@pytest.mark.parametrize("exchange_error", [False, True])
async def test_native_worker_retains_complete_failure_before_asserting(provider, exchange_error):
    result = ProcessResult(returncode=23, stdout=b"worker-ready\n", stderr=b"failed",
                           elapsed_s=1.25, timed_out=True, bound_exceeded="stdout",
                           payload_returncode=23)
    provider.launcher = SimpleNamespace(exchange=AsyncMock(
        side_effect=ProcessExchangeError(result) if exchange_error else None, return_value=result,
    ))
    acquired = await provider.acquire(replace(context(), check_control=lambda: None))
    handle = acquired.resource
    handle.ready = True
    record = {}
    view = SimpleNamespace(path="unused", use=lambda: nullcontext(42))
    with pytest.raises(ProcessExchangeError if exchange_error else AssertionError):
        await handle.worker(view, 41, asyncio.get_running_loop().time() + 20, record)
    assert record["worker"]["process"] == {
        **asdict(result), "stdout": result.stdout.hex(), "stderr": result.stderr.hex(),
    }
    assert isinstance(record["worker"]["decoded"], dict)
    assert record["worker"]["decoded"]["status"] == "failure"
    assert record["worker"]["decoded"]["error"]["kind"] == "timeout"


async def test_native_worker_interruption_does_not_invent_result(provider):
    provider.launcher = SimpleNamespace(exchange=AsyncMock(side_effect=asyncio.CancelledError))
    acquired = await provider.acquire(replace(context(), check_control=lambda: None))
    handle = acquired.resource
    handle.ready = True
    record = {}
    view = SimpleNamespace(path="unused", use=lambda: nullcontext(42))
    with pytest.raises(asyncio.CancelledError):
        await handle.worker(view, 41, asyncio.get_running_loop().time() + 20, record)
    assert record["worker"] == {"process": None, "decoded": None, "ready": False}


async def test_native_closure_check_is_off_loop_and_joined_on_cancel(provider):
    import threading

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    loop_thread = threading.get_ident()

    def check(paths):
        assert threading.get_ident() != loop_thread
        entered.set()
        assert release.wait(5)
        finished.set()

    provider.closure.require_open.side_effect = check
    handle = (await provider.acquire(replace(context(), check_control=lambda: None))).resource
    handle.ready = True
    task = asyncio.create_task(handle.require_open())
    try:
        async with asyncio.timeout(5):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not finished.is_set()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert finished.is_set()
