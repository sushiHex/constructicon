"""Existing lease identities own inert workspace views and physical recovery."""

from __future__ import annotations

import asyncio
import copy
import random
import sys
import threading
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
from tests.gitworld import push_to_main, seed_authority
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


async def test_crash_helper_graph_is_admissible_without_a_linux_host(provider, tmp_path):
    from constructicon.api.system import Constructicon
    from constructicon.core.control import RunSubmission
    from constructicon.runtime.registry import CapabilityDescriptor
    from constructicon.substrate.journal.sqlite import SqliteJournal
    from tests.api.test_control_response_loss import RUN_ACTOR, _fresh_control, _PassiveHost
    from tests.substrate._lease_owner import register_read

    journal = SqliteJournal(tmp_path / "portable.sqlite")
    system = Constructicon(journal=journal, capabilities={"snapshot": provider}, catalog={
        "snapshot": CapabilityDescriptor(
            capability_id="snapshot", kind="workspace.snapshot", leased=True,
            revision="test-snapshot", requires_posture=Posture.READ,
        ),
    })
    control = _fresh_control(system, journal, "portable", run_host=_PassiveHost())
    await control.startup()
    try:
        graph = await register_read(control)
        submitted = await control.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"issue": {"title": "physical lease"}},
            idempotency_key="portable-admission",
        )
        assert isinstance(submitted, RunSubmission), submitted
        assert not provider.root.exists()  # Admission is not materialization.
    finally:
        await control.shutdown()


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


@pytest.fixture
def large_repository(provider):
    # Incompressible enough that both the tar and Git pack exceed TaskSpec's
    # 1 MiB, while fitting the separately declared artifact bound.
    content = random.Random(8).randbytes(2 * 1024 * 1024).hex()
    push_to_main(Path(provider.authority.repository_id), {"large.txt": content}, "large fixture")
    return content


async def test_export_has_an_artifact_bound_not_the_task_input_bound(provider, large_repository):
    base = provider.authority.resolve_ref("refs/heads/main")
    for args, stdin in (
        (("archive", "--format=tar", base), b""),
        (("pack-objects", "--stdout", "--revs"), f"{base}\n".encode()),
    ):
        try:
            content = await provider._export(*args, stdin=stdin)
        except ContractViolation as exc:
            if "materialization bound" not in str(exc):
                raise
            pytest.fail("a valid artifact was refused at the task-input boundary")
        assert provider.launcher.limits.input_bytes < len(content)
        assert len(content) <= provider.launcher.limits.artifact_bytes
    provider.launcher.limits = ProcessLimits(artifact_bytes=8192)
    with pytest.raises(ContractViolation, match="materialization bound"):
        async with asyncio.timeout(5):
            await provider._export("archive", "--format=tar", base)


@pytest.mark.parametrize("posture", [Posture.READ, Posture.WRITE])
async def test_large_materialization_keeps_artifact_and_task_limits_separate(
    provider, launcher, large_repository, posture,
):
    provider.launcher = launcher
    provider.posture = posture
    acquired = await provider.acquire(context(posture=posture))
    try:
        await acquired.materialize()
        assert Path(acquired.resource.path, "large.txt").read_text() == large_repository
        async with acquired.resource.use() as guard:
            with pytest.raises(ContractViolation, match="input/deadline"):
                await launcher.run(
                    ("/usr/bin/python3", "-c", "print('should not start')"),
                    workspace=Path(acquired.resource.path), posture=posture,
                    guard_fds=(guard,), stdin=b"x" * (launcher.limits.input_bytes + 1), timeout_s=5,
                )
    finally:
        await provider.close(acquired, "discard")


@LINUX
async def test_deletion_yields_but_keeps_its_guard_through_repeated_cancellation(
    provider, monkeypatch,
):
    from constructicon.substrate.git import acquisition

    acquired = await provider.acquire(context())
    await acquired.materialize()
    started, finish = threading.Event(), threading.Event()
    remove = acquisition.shutil.rmtree

    def blocked_remove(path):
        started.set()
        finish.wait(5)  # A watchdog, not the event-loop synchronization mechanism.
        remove(path)

    blocked_remove.avoids_symlink_attacks = remove.avoids_symlink_attacks
    monkeypatch.setattr(acquisition.shutil, "rmtree", blocked_remove)
    closing = asyncio.create_task(provider.close(acquired, "discard"))
    waiting = None

    async def next_guard():
        async with acquisition_guard(acquired.resource.paths):
            return "quiescent"

    try:
        try:
            async with asyncio.timeout(2):
                while not started.is_set():
                    await asyncio.sleep(.001)
        except TimeoutError:
            # The worker's watchdog has returned, but the loop was unable to
            # observe entry while deletion owned it. This is the latency law,
            # not a harness timeout or an incidental process failure.
            pytest.fail("the event loop could not observe deletion entry within its deadline")
        assert not closing.done(), "deletion monopolized the event loop until completion"
        waiting = asyncio.create_task(next_guard())
        for _ in range(2):
            closing.cancel()
            await asyncio.sleep(.02)
            assert not closing.done() and not waiting.done(), "deletion abandoned its guard"
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert await waiting == "quiescent"
        assert not acquired.resource.paths.payload.exists()
        assert provider.closure.is_closed(acquired.resource.paths)
    finally:
        finish.set()
        await asyncio.gather(closing, *(t for t in (waiting,) if t), return_exceptions=True)
