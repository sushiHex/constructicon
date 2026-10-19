"""Portable lease and ownership proofs; only platform primitives are substituted."""

import asyncio
import shutil
import sys
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.identity import digest
from constructicon.substrate.executors import pi_provider
from constructicon.substrate.executors.pi_read import PI_LIMITS
from tests.gitworld import seed_authority
from tests.pi_leaseworld import assemble
from tests.piworld import SubprocessLauncher
from tests.substrate.test_contained_workspace import context, stale_row
from tests.substrate.test_pi_read import grants


async def wait(event):
    async with asyncio.timeout(10):
        await event.wait()


class PortableLauncher(SubprocessLauncher):
    """Same harmless native process; fake containment identity is explicitly portable."""

    def __init__(self, root):
        super().__init__()
        self.root = root
        executable = root / "usr/bin/python3"
        executable.parent.mkdir(parents=True)
        shutil.copyfile(sys.executable, executable)
        self.expected_runtime = digest("portable-pi-runtime", 1, executable.read_bytes().hex())
        self.revision = digest("portable-pi-launch", 1, str(self.expected_runtime))
        self.probes = self.calls = 0
        self.held_guards = {}
        self.launched_guards = []
        self.timeouts = []

    def check_artifacts(self):
        pass  # The physical artifact check is explicitly substituted in this portable double.

    async def probe(self):
        self.probes += 1
        await asyncio.sleep(0)

    async def exchange(self, command, **kwargs):
        self.calls += 1
        held = tuple(self.held_guards.values())
        assert len(held) == 2 and kwargs["guard_fds"] == held
        self.launched_guards.append(held)
        self.timeouts.append(kwargs["timeout_s"])
        try:
            return await super().exchange(command, **kwargs)
        finally:
            assert tuple(self.held_guards.values()) == held


@pytest.fixture
async def world(tmp_path, monkeypatch):
    from constructicon.substrate.git import acquisition, contained

    locks = {}
    facts = []

    @asynccontextmanager
    async def guard(paths):
        lock = locks.setdefault(paths.guard, asyncio.Lock())
        async with lock:
            facts.append(("enter", paths.acquisition_id))
            descriptor = 17 + len(facts)
            launcher.held_guards[paths.guard] = descriptor
            try:
                yield descriptor
            finally:
                del launcher.held_guards[paths.guard]
                facts.append(("exit", paths.acquisition_id))

    for module in (pi_provider, acquisition, contained):
        monkeypatch.setattr(module, "acquisition_guard", guard)
    original_remove = shutil.rmtree

    def portable_remove(path):
        # This fixture owns all disposable bytes; this substitutes the unavailable
        # Windows fd-relative deletion primitive, not a physical safety witness.
        original_remove(path)

    portable_remove.avoids_symlink_attacks = True
    monkeypatch.setattr(acquisition, "shutil", SimpleNamespace(rmtree=portable_remove))
    seed_authority(tmp_path, {"fixture.txt": "leased workspace bytes"})
    launcher = PortableLauncher(tmp_path / "runtime")
    system, journal, executor, workspace = await assemble(tmp_path, launcher)
    return system, journal, executor, workspace, launcher, facts


def executor_context(provider, *, epoch=1):
    ctx = context(epoch=epoch, binding="executor", run_id="pi-lease-run")
    return replace(ctx, binding=ctx.binding.model_copy(update={
        "capability_id": "pi-read-fixture", "revision": provider.identity.revision,
        "effective_grants": grants(),
    }), check_control=lambda: None)


async def acquired_pair(world):
    _system, _journal, provider, workspace, _launcher, _facts = world
    ctx = executor_context(provider)
    workspace_ctx = replace(ctx, binding=ctx.binding.model_copy(update={
        "binding": "workspace", "capability_id": provider.workspace_capability_id,
        "revision": provider.workspace_revision,
    }))
    view = await workspace.acquire(workspace_ctx)
    await view.materialize()
    handle = await provider.acquire(ctx)
    await handle.materialize()
    return ctx, handle, view


async def test_inert_acquire_close_prevents_materialization_without_closure_writes(world):
    provider = world[2]
    acquired = await provider.acquire(executor_context(provider))
    assert not provider.acquisition_root.exists()
    assert not acquired.resource.entered and not acquired.resource.ready
    assert (await provider.close(acquired, "discard")).disposition == "discarded"
    assert not provider.acquisition_root.exists()
    assert not provider.closure.is_closed(acquired.resource.paths)
    with pytest.raises(ContractViolation):
        await acquired.materialize()


async def test_materialized_task_reads_exact_workspace_and_closes_both_leases(world):
    ctx, handle, view = await acquired_pair(world)
    provider, workspace, launcher = world[2:5]
    before = Path(view.resource.path, "fixture.txt").read_bytes(), view.resource.git_ref()
    outcome = await handle.resource.execute(
        TaskSpec(instruction="Analyze fixture.txt"), workspace=view.resource,
        grants=ctx.binding.effective_grants,
    )
    assert outcome.status == "success" and outcome.output == "Read: leased workspace bytes"
    assert before == (Path(view.resource.path, "fixture.txt").read_bytes(), view.resource.git_ref())
    assert launcher.calls == 1 and launcher.joined and launcher.eof
    assert launcher.probes == 1  # Assembly only; no redundant materialization probe.
    assert (await provider.close(handle, "release")).disposition == "released"
    await workspace.close(view, "release")
    assert handle.resource.closed and provider.closure.is_closed(handle.resource.paths)
    assert [kind for kind, _ in world[5]].count("enter") == [
        kind for kind, _ in world[5]
    ].count("exit")


@pytest.mark.parametrize("field,value", [("owner_id", "wrong-owner"), ("epoch", 2)])
async def test_workspace_owner_and_epoch_must_match_before_entry(world, field, value):
    ctx, handle, view = await acquired_pair(world)
    object.__setattr__(view.resource, "context", replace(view.resource.context,
        run_lease=view.resource.context.run_lease.model_copy(update={field: value})))
    with pytest.raises(ContractViolation):
        await handle.resource.execute(TaskSpec(instruction="Analyze fixture.txt"),
                                      workspace=view.resource, grants=ctx.binding.effective_grants)
    assert world[4].calls == 0
    await world[2].close(handle, "discard")
    await world[3].close(view, "discard")


async def test_recorded_never_materialized_handle_is_fenced_from_canonical_reference(world):
    provider = world[2]
    ctx = executor_context(provider)
    acquired = await provider.acquire(ctx)
    result = await provider.reconcile(executor_context(provider, epoch=2),
                                       (stale_row(acquired, ctx),))
    assert result.reaped == (acquired.resource_ref,)
    assert provider.closure.is_closed(acquired.resource.paths)
    with pytest.raises(ContractViolation):
        await acquired.materialize()


async def test_recovery_validates_entire_batch_before_any_fence(world):
    provider = world[2]
    ctx = executor_context(provider)
    acquired = await provider.acquire(ctx)
    first = stale_row(acquired, ctx)
    bad = replace(first, lease=first.lease.model_copy(update={"resource_ref": "{}"}))
    with pytest.raises(ContractViolation):
        await provider.reconcile(executor_context(provider, epoch=2), (first, bad))
    assert not provider.closure.is_closed(acquired.resource.paths)


async def test_relinquishment_joins_but_never_commits_durable_closure(world):
    provider = world[2]
    acquired = await provider.acquire(executor_context(provider))
    await acquired.materialize()
    await provider.relinquish(acquired)
    await provider.relinquish(acquired)
    assert acquired.resource.closed
    assert not provider.closure.is_closed(acquired.resource.paths)
    assert [kind for kind, _ in world[5]] == ["enter", "exit"]


@pytest.mark.parametrize("field", ["command", "workspace_revision"])
async def test_sealed_assembly_inputs_cannot_drift_before_use(world, field):
    provider = world[2]
    acquired = await provider.acquire(executor_context(provider))
    changed = ("/usr/bin/python3", "-c", "changed") if field == "command" else "changed"
    setattr(provider, field, changed)
    with pytest.raises(ContractViolation):
        await acquired.materialize()
    await provider.close(acquired, "discard")
    assert world[4].calls == 0


def test_provider_uses_exact_fixed_limits(world):
    assert world[4].limits == PI_LIMITS


def fresh_provider(world):
    old = world[2]
    return pi_provider.PiReadProvider(
        old.launcher, old.command, workspace_provider=old.workspace_provider,
        workspace_capability_id=old.workspace_capability_id,
        workspace_revision=old.workspace_revision, acquisition_root=old.acquisition_root,
    )


async def test_qualification_publishes_only_a_completed_benign_probe(world):
    provider = fresh_provider(world)
    assert provider.unavailable_reasons
    with pytest.raises(ContractViolation):
        await provider.acquire(executor_context(provider))
    await provider.qualify()
    assert provider.unavailable_reasons == () and world[4].probes == 2
    acquired = await provider.acquire(executor_context(provider))
    assert acquired.resource_ref and provider.unavailable_reasons
    await provider.close(acquired, "release")
    with pytest.raises(ContractViolation, match="spent"):
        await provider.acquire(executor_context(provider))


async def test_rejected_context_does_not_spend_acquisition(world):
    provider = world[2]
    ctx = executor_context(provider)
    bad = replace(ctx, binding=ctx.binding.model_copy(update={"revision": "wrong"}))
    with pytest.raises(ContractViolation):
        await provider.acquire(bad)
    assert provider.unavailable_reasons == ()
    acquired = await provider.acquire(ctx)
    await provider.close(acquired, "release")


@pytest.mark.parametrize("fault", ["refusal", "drift", "loss", "reentry"])
async def test_assembly_probe_faults_cannot_publish_availability(world, monkeypatch, fault):
    provider = fresh_provider(world)
    entered, release = asyncio.Event(), asyncio.Event()
    lost = False

    async def probe():
        entered.set()
        await wait(release)
        if fault == "refusal":
            raise ContractViolation("fixture namespace refused")

    def control():
        if lost:
            raise ContractViolation("assembly ownership lost")

    monkeypatch.setattr(world[4], "probe", probe)
    pending = asyncio.create_task(provider.qualify(check_control=control))
    await wait(entered)
    assert provider.unavailable_reasons
    if fault == "drift":
        provider.command = ("/usr/bin/python3", "-c", "changed")
    elif fault == "loss":
        lost = True
    elif fault == "reentry":
        with pytest.raises(ContractViolation):
            await provider.qualify()
    release.set()
    with pytest.raises(ContractViolation):
        await pending
    assert provider.unavailable_reasons


@pytest.mark.parametrize("field", ["owner", "epoch", "revision", "capability", "grants", "control"])
async def test_workspace_is_revalidated_after_actual_guard_wait(world, monkeypatch, field):
    from constructicon.substrate.git import contained

    ctx, acquired, view = await acquired_pair(world)
    original_context = view.resource.context
    entered, release = asyncio.Event(), asyncio.Event()
    original_guard = contained.acquisition_guard

    @asynccontextmanager
    async def paused(paths):
        async with original_guard(paths) as guard:
            entered.set()
            await wait(release)
            yield guard

    monkeypatch.setattr(contained, "acquisition_guard", paused)
    pending = asyncio.create_task(acquired.resource.execute(
        TaskSpec(instruction="Analyze fixture.txt"), workspace=view.resource,
        grants=ctx.binding.effective_grants,
    ))
    await wait(entered)
    actual = original_context
    if field in ("owner", "epoch"):
        key, value = ("owner_id", "other") if field == "owner" else ("epoch", 2)
        actual = replace(actual, run_lease=actual.run_lease.model_copy(update={key: value}))
    elif field == "control":
        def lost():
            raise ContractViolation("workspace ownership lost")

        actual = replace(actual, check_control=lost)
    else:
        key, value = {
            "revision": ("revision", "wrong"), "capability": ("capability_id", "wrong"),
            "grants": ("effective_grants", grants().model_copy(update={"timeout_s": 30})),
        }[field]
        actual = replace(actual, binding=actual.binding.model_copy(update={key: value}))
    object.__setattr__(view.resource, "context", actual)
    release.set()
    with pytest.raises(ContractViolation):
        await pending
    assert world[4].calls == 0
    object.__setattr__(view.resource, "context", original_context)
    await world[2].close(acquired, "discard")
    await world[3].close(view, "discard")


async def test_deadline_spends_real_guard_wait_and_passes_remaining(world, monkeypatch):
    provider, launcher = world[2], world[4]
    ctx = executor_context(provider)
    view_ctx = replace(ctx, binding=ctx.binding.model_copy(update={
        "binding": "workspace", "capability_id": provider.workspace_capability_id,
        "revision": provider.workspace_revision,
    }))
    view = await world[3].acquire(view_ctx)
    await view.materialize()
    acquired = await provider.acquire(ctx)
    entered, release = asyncio.Event(), asyncio.Event()
    original = pi_provider.acquisition_guard

    @asynccontextmanager
    async def paused(paths):
        entered.set()
        await wait(release)
        async with original(paths) as guard:
            yield guard

    monkeypatch.setattr(pi_provider, "acquisition_guard", paused)
    materializing = asyncio.create_task(acquired.materialize())
    await wait(entered)
    deadline = acquired.resource.deadline
    assert deadline is not None
    await asyncio.sleep(.1)  # Actual budget is consumed while physical entry is pending.
    release.set()
    await materializing
    assert acquired.resource.deadline == deadline
    before = asyncio.get_running_loop().time()
    outcome = await acquired.resource.execute(
        TaskSpec(instruction="Analyze fixture.txt"), workspace=view.resource,
        grants=ctx.binding.effective_grants,
    )
    assert outcome.status == "success"
    assert 0 < launcher.timeouts[0] <= deadline - before
    assert launcher.timeouts[0] < ctx.binding.effective_grants.timeout_s - .1
    await provider.close(acquired, "release")
    await world[3].close(view, "release")


async def test_buffered_success_refuses_workspace_control_loss_after_exchange(world, monkeypatch):
    ctx, acquired, view = await acquired_pair(world)
    lost = False

    def workspace_control():
        if lost:
            raise ContractViolation("workspace lost after joined exchange")

    original_context = view.resource.context
    object.__setattr__(view.resource, "context", replace(original_context,
                                                         check_control=workspace_control))
    original_exchange = world[4].exchange

    async def positive_then_lose(*args, **kwargs):
        nonlocal lost
        result = await original_exchange(*args, **kwargs)
        assert world[4].joined and world[4].eof and result.returncode == 0
        lost = True
        return result

    monkeypatch.setattr(world[4], "exchange", positive_then_lose)
    with pytest.raises(ContractViolation, match="workspace lost"):
        await acquired.resource.execute(
            TaskSpec(instruction="Analyze fixture.txt"), workspace=view.resource,
            grants=ctx.binding.effective_grants,
        )
    object.__setattr__(view.resource, "context", original_context)
    await world[2].close(acquired, "discard")
    await world[3].close(view, "discard")


async def test_active_relinquishment_joins_despite_repeated_cancel(world, monkeypatch):
    provider = world[2]
    original_guard = pi_provider.acquisition_guard

    @asynccontextmanager
    async def failed_release(paths):
        async with original_guard(paths) as descriptor:
            yield descriptor
        raise OSError("scripted guard release failed")

    monkeypatch.setattr(pi_provider, "acquisition_guard", failed_release)
    ctx, acquired, view = await acquired_pair(world)
    entered, stopping, join = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def active(*args, **kwargs):
        entered.set()
        try:
            await wait(asyncio.Event())
        except asyncio.CancelledError:
            stopping.set()
            await wait(join)
            raise

    monkeypatch.setattr(world[4], "exchange", active)
    execution = asyncio.create_task(acquired.resource.execute(
        TaskSpec(instruction="Analyze fixture.txt"), workspace=view.resource,
        grants=ctx.binding.effective_grants,
    ))
    closing = marker = None
    try:
        await wait(entered)
        held = dict(world[4].held_guards)
        assert len(held) == 2
        closing = asyncio.create_task(provider.relinquish(acquired))
        marker = asyncio.create_task(wait(stopping))
        done, _pending = await asyncio.wait((closing, marker), timeout=10,
                                           return_when=asyncio.FIRST_COMPLETED)
        assert marker in done and stopping.is_set() and not closing.done()
        await marker
        closing.cancel()
        await asyncio.sleep(0)
        closing.cancel()
        assert not closing.done() and world[4].held_guards == held
        assert not provider.closure.is_closed(acquired.resource.paths)
        join.set()
        observed = None
        try:
            await closing
        except BaseException as error:
            observed = error
        assert isinstance(observed, BaseExceptionGroup)
        assert any(isinstance(error, OSError) for error in observed.exceptions)
        assert any(isinstance(error, asyncio.CancelledError) for error in observed.exceptions)
        with pytest.raises(asyncio.CancelledError):
            await execution
        assert not world[4].held_guards and not provider.closure.is_closed(acquired.resource.paths)
    finally:
        join.set()
        execution.cancel()
        if marker is not None:
            marker.cancel()
        await asyncio.gather(execution, *(task for task in (closing, marker) if task is not None),
                             return_exceptions=True)
        if closing is None:
            await asyncio.gather(provider.relinquish(acquired), return_exceptions=True)
        await world[3].close(view, "discard")


async def test_public_identity_binds_content_not_installation_locators(world, tmp_path):
    other = tmp_path / "other-installation"
    other.mkdir()
    seed_authority(other, {"fixture.txt": "equivalent workspace bytes"})
    launcher = PortableLauncher(other / "runtime")
    _system, _journal, provider, _workspace = await assemble(other, launcher)
    assert world[2].identity == provider.identity
    assert world[2].acquisition_root != provider.acquisition_root
    assert world[3].authority.repository_id != provider.workspace_provider.authority.repository_id


@pytest.mark.parametrize("field", ["acquisition", "workspace", "authority", "runtime"])
async def test_private_custody_locator_drift_refuses_materialization(world, field):
    provider = world[2]
    acquired = await provider.acquire(executor_context(provider))
    target, attribute = {
        "acquisition": (provider, "acquisition_root"), "workspace": (world[3], "root"),
        "authority": (world[3].authority, "_repo"), "runtime": (world[4], "root"),
    }[field]
    before = getattr(target, attribute)
    setattr(target, attribute, before / "changed")
    with pytest.raises(ContractViolation):
        await acquired.materialize()
    setattr(target, attribute, before)
    await provider.close(acquired, "discard")
    assert world[4].calls == 0


@pytest.mark.parametrize("field", ["reference", "paths", "lease_id", "context", "coordinated"])
async def test_handle_and_wrapper_coordinates_are_rederived_from_minted_context(world, field):
    from constructicon.core.address import ScopePath
    from constructicon.core.workspace import acquisition_id_for, lease_id_for
    from constructicon.substrate.git.acquisition import AcquisitionPaths

    provider = world[2]
    ctx = executor_context(provider)
    acquired = await provider.acquire(ctx)
    handle = acquired.resource
    scope = ScopePath(segments=("other", "worker"))
    changed = replace(ctx, path=ctx.path.model_copy(update={"scope": scope}))
    logical = lease_id_for(changed.run_lease.run_id, changed.path, changed.binding.binding)
    paths = AcquisitionPaths(provider.acquisition_root, acquisition_id_for(logical, 1))
    replacements = {"reference": provider._reference(changed), "paths": paths,
                    "lease_id": logical, "context": changed}
    before = {name: getattr(handle, name) for name in replacements}
    for name, value in replacements.items():
        if name == field or field == "coordinated":
            setattr(handle, name, value)
    wrapper = replace(acquired, lease_id=handle.lease_id,
                      acquisition_id=handle.paths.acquisition_id,
                       resource_ref=handle.reference)
    with pytest.raises(ContractViolation):
        await provider.close(wrapper, "discard")
    assert not provider.acquisition_root.exists()
    for name, value in before.items():
        setattr(handle, name, value)
    await provider.close(acquired, "discard")


async def test_provider_does_not_retain_completed_handle_strongly(world):
    import gc
    import weakref

    provider = world[2]
    acquired = await provider.acquire(executor_context(provider))
    observed = weakref.ref(acquired.resource)
    await provider.close(acquired, "discard")
    del acquired
    gc.collect()
    assert observed() is None and not provider._handles


@pytest.mark.parametrize("target", ["executor_closure", "workspace_closure",
                                  "executor_authority", "workspace_authority"])
async def test_closure_custody_is_rechecked_after_guard_wait(world, monkeypatch, target):
    from constructicon.substrate.git.acquisition import AcquisitionClosure

    provider, workspace = world[2], world[3]
    acquired = await provider.acquire(executor_context(provider))
    entered, release = asyncio.Event(), asyncio.Event()
    original_guard = pi_provider.acquisition_guard

    @asynccontextmanager
    async def paused(paths):
        async with original_guard(paths) as guard:
            entered.set()
            await wait(release)
            yield guard

    monkeypatch.setattr(pi_provider, "acquisition_guard", paused)
    pending = asyncio.create_task(acquired.materialize())
    await wait(entered)
    owner, attribute = {
        "executor_closure": (provider, "closure"),
        "workspace_closure": (workspace, "closure"),
        "executor_authority": (provider.closure, "authority"),
        "workspace_authority": (workspace.closure, "authority"),
    }[target]
    original = getattr(owner, attribute)
    replacement = AcquisitionClosure(workspace.authority) if attribute == "closure" else object()
    setattr(owner, attribute, replacement)
    release.set()
    try:
        with pytest.raises(ContractViolation):
            await pending
        with pytest.raises(ContractViolation):
            await provider.close(acquired, "discard")
        assert world[4].calls == 0
    finally:
        setattr(owner, attribute, original)
    assert not provider.closure.is_closed(acquired.resource.paths)
    assert not world[4].held_guards


async def test_public_deadline_cannot_extend_original_task_budget(world):
    ctx, acquired, view = await acquired_pair(world)
    deadline = acquired.resource.deadline
    with suppress(AttributeError):  # Public observation is intentionally read-only.
        acquired.resource.deadline = asyncio.get_running_loop().time() + 600
    outcome = await acquired.resource.execute(
        TaskSpec(instruction="Analyze fixture.txt"), workspace=view.resource,
        grants=ctx.binding.effective_grants,
    )
    assert outcome.status == "success"
    assert world[4].timeouts[0] <= ctx.binding.effective_grants.timeout_s
    assert acquired.resource.deadline == deadline
    await world[2].close(acquired, "release")
    await world[3].close(view, "release")


async def test_direct_private_deadline_never_expands_granted_timeout(world):
    from constructicon.substrate.executors.pi_read import PiReadExecutor

    ctx, acquired, view = await acquired_pair(world)
    async with view.resource.use() as workspace_guard:
        executor = PiReadExecutor(
            world[4], world[2].command,
            guard_fds=(acquired.resource._guard_fd, workspace_guard),
            _deadline=asyncio.get_running_loop().time() + 600,
        )
        outcome = await executor.execute(TaskSpec(instruction="Analyze fixture.txt"),
                                         workspace=view.resource,
                                         grants=ctx.binding.effective_grants)
    assert outcome.status == "success"
    assert world[4].timeouts[0] <= ctx.binding.effective_grants.timeout_s
    await world[2].close(acquired, "release")
    await world[3].close(view, "release")


@pytest.mark.parametrize("action", ["dispose", "execute"])
async def test_launcher_locator_drift_refuses_execution_but_not_owned_disposal(world, action):
    ctx, acquired, view = await acquired_pair(world)
    changed = world[4].root.with_name("relocated-runtime")
    shutil.copytree(world[4].root, changed)
    world[4].root = changed
    if action == "execute":
        with pytest.raises(ContractViolation):
            await acquired.resource.execute(
                TaskSpec(instruction="Analyze fixture.txt"), workspace=view.resource,
                grants=ctx.binding.effective_grants,
            )
    await world[2].close(acquired, "discard")
    await world[3].close(view, "discard")
    assert acquired.resource.closed and world[2].closure.is_closed(acquired.resource.paths)
    assert not world[4].held_guards and world[4].calls == 0
