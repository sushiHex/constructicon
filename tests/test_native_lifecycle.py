"""Portable instrument checks; never credited as physical native proof."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.errors import ContractViolation
from constructicon.core.workspace import StaleAcquisition
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
        "epoch": {"acquisition_epoch": 2},
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
        handle.require_open()
    handle.ready = True
    handle.require_open()
    control.assert_called_once()
    provider.closure.require_open.assert_called_once_with(handle.paths)
    provider.closure.require_open.side_effect = ContractViolation("permanent closure")
    with pytest.raises(ContractViolation, match="permanent closure"):
        handle.require_open()
    provider.closure.require_open.side_effect = None
    control.side_effect = ContractViolation("revoked")
    with pytest.raises(ContractViolation, match="revoked"):
        handle.require_open()


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
