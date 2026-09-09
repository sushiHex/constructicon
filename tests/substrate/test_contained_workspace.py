"""Existing lease identities own inert workspace views and physical recovery."""

from __future__ import annotations

import asyncio
import copy
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.identity import digest
from constructicon.core.manifest import CapabilityBinding, CapabilityLease
from constructicon.core.run import RunLease
from constructicon.core.workspace import LeaseContext, StaleAcquisition, acquisition_id_for
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.contained import ContainedWorkspaceProvider
from tests.gitworld import seed_authority
from tests.substrate.test_linux_containment import launcher as launcher

LINUX = pytest.mark.skipif(
    sys.platform != "linux", reason="physical acquisition guard requires Linux",
)


def context(*, epoch=1, posture=Posture.READ, binding="workspace", run_id="workspace-run"):
    scope = ScopePath(segments=("root", "worker"))
    return LeaseContext(
        run_lease=RunLease(run_id=RunId(run_id), owner_id=f"owner-{epoch}", epoch=epoch,
                           expires_at=datetime.now(UTC) + timedelta(minutes=5)),
        binding=CapabilityBinding(
            scope=scope, binding=binding, capability_id="owned-workspace", revision="test",
            effective_grants=EffectiveGrants(
                posture=posture, model_selection=ModelSelection(kind="backend_default"),
                effort=None,
                allowed_tools=(), env_allowlist=(), network="none", timeout_s=30,
            ),
        ),
        path=ExecutionPath(scope=scope), manifest_hash=digest("test-manifest", 1, "workspace"),
    )


def stale_row(acquired, ctx):
    return StaleAcquisition(lease=CapabilityLease(
        lease_id=acquired.lease_id, acquisition_epoch=ctx.run_lease.epoch,
        run_id=ctx.run_lease.run_id, binding_id=ctx.binding.binding, path=ctx.path,
        state="active", resource_ref=acquired.resource_ref,
    ), disposition="discard")


@pytest.fixture
def provider(tmp_path):
    authority = GitAuthority(seed_authority(tmp_path), tmp_path / "legacy")
    # READ export/lease tests do not execute a process boundary. The physical
    # staging test below substitutes the real provisioned launcher explicitly.
    return ContainedWorkspaceProvider(
        authority, root=tmp_path / "owned", target_ref="refs/heads/main",
        provider_id="test-workspace", posture=Posture.READ,
        launcher=SimpleNamespace(limits=ProcessLimits()),
    )


async def test_acquire_and_close_before_materialization_are_physically_inert(provider):
    acquired = await provider.acquire(context())
    assert not provider.root.exists()
    assert not provider.closure.is_closed(acquired.resource.paths)
    result = await provider.close(acquired, "discard")
    assert result.disposition == "discarded" and not provider.root.exists()
    assert not provider.closure.is_closed(acquired.resource.paths)
    with pytest.raises(ContractViolation, match="locally closed"):
        await acquired.materialize()
    assert not provider.root.exists()


async def test_incompatible_posture_is_refused_without_allocation(provider):
    with pytest.raises(ContractViolation, match="posture"):
        await provider.acquire(context(posture=Posture.WRITE))
    assert not provider.root.exists()


@LINUX
async def test_recorded_never_started_acquisition_is_fenced_without_current_base(provider):
    old = context()
    acquired = await provider.acquire(old)
    provider.authority._run("update-ref", "-d", "refs/heads/main")
    await provider.reconcile(context(epoch=2), (stale_row(acquired, old),))
    assert provider.closure.is_closed(acquired.resource.paths)
    assert acquired.resource.paths.guard.is_file()
    assert not acquired.resource.paths.payload.exists()
    with pytest.raises(ContractViolation, match="permanently closed"):
        await acquired.materialize()
    assert not acquired.resource.paths.payload.exists()


@LINUX
async def test_waiting_materializer_cannot_recreate_disposed_payload(provider):
    old = context()
    acquired = await provider.acquire(old)
    paths = acquired.resource.paths
    fresh = AcquisitionPaths(provider.root, acquisition_id_for(acquired.lease_id, 2))
    fresh.payload.mkdir(parents=True)
    (fresh.payload / "sentinel").write_text("current")
    async with acquisition_guard(paths):
        producer = asyncio.create_task(acquired.materialize())
        await asyncio.sleep(.02)
        assert acquired.resource.entered and not paths.payload.exists()
        recovery = asyncio.create_task(provider.reconcile(
            context(epoch=2), (stale_row(acquired, old),),
        ))
        async with asyncio.timeout(5):
            while not provider.closure.is_closed(paths):
                await asyncio.sleep(.01)
        assert not recovery.done()
    with pytest.raises(ContractViolation, match="permanently closed"):
        await producer
    await recovery
    assert not paths.payload.exists()
    assert (fresh.payload / "sentinel").read_text() == "current"


@LINUX
async def test_recovery_waits_for_started_materialization_then_removes_it(provider):
    old = context()
    acquired = await provider.acquire(old)
    entered, finish = asyncio.Event(), asyncio.Event()
    populate = provider.populate

    async def pause(workspace, guard):
        entered.set()
        await finish.wait()
        await populate(workspace, guard)

    provider.populate = pause
    producer = asyncio.create_task(acquired.materialize())
    await entered.wait()
    recovery = asyncio.create_task(provider.reconcile(
        context(epoch=2), (stale_row(acquired, old),),
    ))
    async with asyncio.timeout(5):
        while not provider.closure.is_closed(acquired.resource.paths):
            await asyncio.sleep(.01)
    assert not recovery.done()
    finish.set()
    await producer
    await recovery
    assert not acquired.resource.paths.payload.exists()
    with pytest.raises(ContractViolation, match="permanently closed"):
        async with acquired.resource.use():
            pytest.fail("a stale view reacquired authority after disposal")


@LINUX
@pytest.mark.parametrize("mismatch", [
    "none", "path", "forged", "relocated", "provider", "epoch", "run", "posture", "closed",
])
async def test_mount_authority_comes_from_the_provider_and_exact_invocation(provider, mismatch):
    ctx = context()
    acquired = await provider.acquire(ctx)
    await acquired.materialize()
    view = acquired.resource
    call = context(binding="executor")
    assert provider.owned_view(view, call) is view
    if mismatch == "none":
        view = None
    elif mismatch == "path":
        view = SimpleNamespace(path=acquired.resource.path, git_ref=acquired.resource.git_ref)
    elif mismatch == "forged":
        view = copy.copy(view)
    elif mismatch == "relocated":
        view = replace(view, paths=AcquisitionPaths(
            provider.root / "other", view.paths.acquisition_id,
        ))
    elif mismatch == "provider":
        view = replace(view, provider=object())
    elif mismatch == "epoch":
        call = context(epoch=2, binding="executor")
    elif mismatch == "run":
        call = context(run_id="another-run", binding="executor")
    elif mismatch == "posture":
        call = context(posture=Posture.WRITE, binding="executor")
    else:
        await provider.close(acquired, "release")
    with pytest.raises(ContractViolation, match=r"provider|invocation"):
        provider.owned_view(view, call)


@LINUX
async def test_recovery_cannot_close_the_current_or_an_unrelated_epoch(provider):
    acquired = await provider.acquire(context())
    row = stale_row(acquired, context())
    for current in (context(), context(run_id="another"), context(binding="other")):
        with pytest.raises(ContractViolation, match="stale invocation"):
            await provider.reconcile(current, (row,))
    bad = replace(row, lease=row.lease.model_copy(update={"resource_ref": "{}"}))
    with pytest.raises(ValueError):
        await provider.reconcile(context(epoch=2), (bad,))
    assert not provider.closure.is_closed(acquired.resource.paths)


async def test_staging_is_initialized_through_the_actual_contained_launcher(provider, launcher):
    provider.posture = Posture.WRITE
    provider.launcher = launcher
    ctx = context(posture=Posture.WRITE)
    acquired = await provider.acquire(ctx)
    assert not provider.root.exists()
    await acquired.materialize()
    view = acquired.resource
    assert Path(view.path, ".git").is_dir()
    assert Path(view.path, "calc.py").read_text().startswith("def add")
    # This view cannot accidentally call the historical, host-executing API.
    assert not hasattr(view, "commit_all") and not hasattr(view, "reset_to")
    before = provider.authority.resolve_ref("refs/heads/main")
    async with view.use() as guard:
        result = await launcher.run(
            ("/usr/bin/git", "rev-parse", "HEAD"), workspace=Path(view.path),
            posture=Posture.WRITE, guard_fds=(guard,), timeout_s=5,
        )
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode().strip() == before
    await provider.close(acquired, "discard")
    assert not view.paths.payload.exists() and provider.closure.is_closed(view.paths)
    assert provider.authority.resolve_ref("refs/heads/main") == before
