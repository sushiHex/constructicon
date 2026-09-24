"""N3a custody and lifecycle laws at the Codex provider boundary."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.identity import digest
from constructicon.core.manifest import CapabilityLease
from constructicon.core.workspace import StaleAcquisition
from constructicon.substrate.executors import codex, operator_store
from constructicon.substrate.executors.codex import STORE_NOT_ESTABLISHED
from constructicon.substrate.executors.operator_store import BindingCheck
from constructicon.substrate.git import acquisition as acquisition_module
from constructicon.substrate.git.acquisition import AcquisitionClosure
from constructicon.substrate.git.authority import GitAuthority
from tests.gitworld import seed_authority
from tests.operator_store_world import StoreWorld
from tests.substrate.test_codex_adapter import (
    CONFIGURATION,
    GRANTS,
    ScriptedLauncher,
    bare_launcher,
    clean_native,
    context,
    provider_for,
)


@pytest.fixture
def store_lifecycle(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)

    def close_fd(fd):
        world.closed.append(fd)
        os.close(fd)

    monkeypatch.setattr(operator_store, "_close", close_fd)
    guard_fds: list[int] = []
    released_guards: list[int] = []

    @asynccontextmanager
    async def guard(paths):
        paths.guard.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(paths.guard, os.O_CREAT | os.O_RDWR, 0o600)
        guard_fds.append(descriptor)
        try:
            yield descriptor
        finally:
            os.close(descriptor)
            released_guards.append(descriptor)

    monkeypatch.setattr(codex, "acquisition_guard", guard)
    monkeypatch.setattr(acquisition_module, "acquisition_guard", guard)
    authority_root = tmp_path / "authority"
    authority_root.mkdir()
    closure = AcquisitionClosure(GitAuthority(
        seed_authority(authority_root),
        authority_root / "legacy",
    ))
    return world, world.binding(), closure, guard_fds, released_guards


def available_provider(tmp_path, store_lifecycle, launcher=None):
    return provider_for(
        bare_launcher() if launcher is None else launcher,
        unavailable_reasons=(),
        binding=store_lifecycle[1:3],
        root=tmp_path,
    )


async def test_empty_reasons_cannot_claim_an_absent_store_is_available():
    provider = provider_for(bare_launcher(), unavailable_reasons=())
    assert provider.unavailable_reasons == (STORE_NOT_ESTABLISHED,)
    with pytest.raises(ContractViolation, match="unavailable"):
        await provider.acquire(context())


async def test_unbound_provider_does_not_resolve_an_unused_acquisition_locator(
    tmp_path, monkeypatch,
):
    supplied_root = tmp_path / "unused-alias"
    resolved_root = tmp_path / "unused-target"
    original_resolve = Path.resolve
    resolved: list[Path] = []

    def mapped_resolve(path, *, strict=False):
        resolved.append(path)
        if path == supplied_root:
            return resolved_root
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", mapped_resolve)
    provider = provider_for(
        bare_launcher(), unavailable_reasons=(), root=supplied_root,
    )
    assert resolved == []
    assert provider.unavailable_reasons == (STORE_NOT_ESTABLISHED,)
    with pytest.raises(ContractViolation, match="unavailable"):
        await provider.acquire(context())


def test_acquisition_and_persistent_store_roots_must_be_disjoint(
    tmp_path, store_lifecycle,
):
    world, _, closure = store_lifecycle[:3]
    nested = operator_store.BindingStore(
        tmp_path / "acquisitions" / "trusted",
        world.key,
        world.sealed,
    )
    with pytest.raises(ContractViolation, match="must be disjoint"):
        provider_for(
            bare_launcher(),
            unavailable_reasons=(),
            binding=(nested, closure),
            root=tmp_path,
        )


async def test_one_canonical_acquisition_locator_feeds_handles_and_recovery(
    tmp_path, store_lifecycle, monkeypatch,
):
    """The disjointness observation is the locator every later consumer uses."""

    supplied_parent = tmp_path / "direct"
    canonical_root = supplied_parent / "acquisitions"
    provider = provider_for(
        bare_launcher(), unavailable_reasons=(), binding=store_lifecycle[1:3],
        root=supplied_parent,
    )
    acquired = await provider.acquire(context(epoch=1))
    assert acquired.resource.paths.root == canonical_root

    current = context(epoch=2)
    row = CapabilityLease(
        lease_id=acquired.lease_id, acquisition_epoch=1,
        run_id=current.run_lease.run_id, binding_id=current.binding.binding,
        path=current.path, state="active", resource_ref=acquired.resource_ref,
    )
    disposed: list[Path] = []

    async def dispose(closure, paths, **kwargs):
        disposed.append(paths.root)
        return False

    monkeypatch.setattr(codex, "dispose_acquisition", dispose)
    await provider.reconcile(
        current, (StaleAcquisition(lease=row, disposition="discard"),),
    )
    assert disposed == [canonical_root]


def test_binding_refuses_an_acquisition_locator_that_differs_from_its_resolution(
    tmp_path, store_lifecycle, monkeypatch,
):
    supplied_parent = tmp_path / "supplied"
    supplied_root = supplied_parent / "acquisitions"
    resolved_root = tmp_path / "resolved" / "acquisitions"
    original_resolve = Path.resolve

    def mapped_resolve(path, *, strict=False):
        if path == supplied_root:
            return resolved_root
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", mapped_resolve)
    with pytest.raises(ContractViolation, match="canonical path without symlink ancestry"):
        provider_for(
            bare_launcher(), unavailable_reasons=(), binding=store_lifecycle[1:3],
            root=supplied_parent,
        )


@pytest.mark.skipif(sys.platform != "linux", reason="real symlink proof runs in Linux CI")
def test_symlinked_acquisition_ancestry_is_refused_before_it_can_target_the_store(
    tmp_path, store_lifecycle,
):
    safe_parent = tmp_path / "safe"
    safe_root = safe_parent / "acquisitions"
    safe_root.mkdir(parents=True)
    root_link_parent = tmp_path / "root-link-parent"
    root_link_parent.mkdir()
    (root_link_parent / "acquisitions").symlink_to(
        safe_root, target_is_directory=True,
    )
    alias = tmp_path / "acquisition-alias"
    alias.symlink_to(safe_parent, target_is_directory=True)
    world, binding, closure = store_lifecycle[:3]
    vendor_root = world.root / "acquisitions"
    vendor_marker = vendor_root / "payloads" / "persistent"
    vendor_marker.parent.mkdir(parents=True)
    vendor_marker.write_text("keep me", encoding="utf-8")

    with pytest.raises(ContractViolation, match="canonical path without symlink ancestry"):
        provider_for(
            bare_launcher(), unavailable_reasons=(), binding=(binding, closure),
            root=root_link_parent,
        )
    with pytest.raises(ContractViolation, match="canonical path without symlink ancestry"):
        provider_for(
            bare_launcher(), unavailable_reasons=(), binding=(binding, closure), root=alias,
        )
    second_safe_parent = tmp_path / "second-safe"
    second_safe_parent.mkdir()
    for retarget in (second_safe_parent, world.root):
        alias.unlink()
        alias.symlink_to(retarget, target_is_directory=True)
        with pytest.raises(
            ContractViolation, match="canonical path without symlink ancestry",
        ):
            provider_for(
                bare_launcher(), unavailable_reasons=(), binding=(binding, closure), root=alias,
            )
    assert vendor_marker.read_text(encoding="utf-8") == "keep me"
    assert not (vendor_root / "guards").exists()


async def test_materialization_retains_one_store_lock_and_records_three_checks(
    tmp_path, store_lifecycle,
):
    world, _, closure, guard_fds, released_guards = store_lifecycle
    launcher = bare_launcher(clean_native())
    provider = available_provider(tmp_path, store_lifecycle, launcher)
    acquired = await provider.acquire(context())
    reference = json.loads(acquired.resource_ref)
    assert set(reference) == {
        "schema_version", "acquisition_id", "operator_binding_digest",
    }
    assert reference["acquisition_id"] == acquired.acquisition_id
    assert str(world.root) not in acquired.resource_ref and world.key not in acquired.resource_ref

    await acquired.materialize()
    handle = acquired.resource
    held = handle._store_lock
    assert held is not None and world.lock_attempts == 1
    assert handle.initial_check == BindingCheck(world.sealed.operator_binding_digest)
    os.fstat(held.lock_fd)
    os.fstat(guard_fds[0])

    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert outcome.status == "success"
    assert world.lock_attempts == 1, "execute reacquired rather than retaining the same OFD"
    call = launcher.calls[0]
    assert call["guard_fds"] == (guard_fds[0], held.lock_fd)
    mount = call["native_store"]
    assert mount.lock_fd == held.lock_fd
    # The zone receives exactly the credential descriptor opened relative to the
    # held store, and the configuration as this provider's own sealed bytes.
    assert world.credential_opens == [mount.credential_fd]
    assert world.configurations == [provider.configuration.encode("utf-8")]
    assert provider.configuration == CONFIGURATION
    for descriptor in mount.mount_fds:
        with pytest.raises(OSError):
            os.fstat(descriptor)  # released once the launcher returned
    expected = BindingCheck(world.sealed.operator_binding_digest)
    assert (handle.initial_check, handle.launch_check, handle.terminal_check) == (
        expected, expected, expected,
    )

    result = await provider.close(acquired, "release")
    assert result.disposition == "released"
    assert closure.is_closed(handle.paths)
    assert released_guards == guard_fds
    for descriptor in (held.lock_fd, guard_fds[0]):
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert (await provider.close(acquired, "release")).disposition == "released"
    with pytest.raises(ContractViolation, match="disposition"):
        await provider.close(acquired, "discard")


@dataclass(frozen=True, kw_only=True)
class MutatingLauncher(ScriptedLauncher):
    mutate: object

    async def exchange(self, *args, **kwargs):
        result = await super().exchange(*args, **kwargs)
        self.mutate()
        return result


async def test_terminal_binding_drift_discards_the_completed_turn(tmp_path, store_lifecycle):
    world = store_lifecycle[0]

    def replace_selection():
        world.write_descriptor(2)
        world.activate(2)

    base = bare_launcher(clean_native())
    launcher = MutatingLauncher(
        runtime_root=base.runtime_root,
        expected_runtime=base.expected_runtime,
        bubblewrap=base.bubblewrap,
        policy=base.policy,
        expected_policy_sha256=base.expected_policy_sha256,
        native=base.native,
        result=base.result,
        mutate=replace_selection,
    )
    provider = available_provider(tmp_path, store_lifecycle, launcher)
    acquired = await provider.acquire(context())
    await acquired.materialize()
    handle = acquired.resource
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert "terminal check failed" in outcome.error.detail
    assert outcome.output is None and outcome.raw_reply is None
    assert handle.launch_check is not None and handle.terminal_check is None
    await provider.close(acquired, "discard")


async def test_an_absent_initial_check_never_mints_readiness(
    tmp_path, store_lifecycle, monkeypatch,
):
    world, store = store_lifecycle[:2]
    monkeypatch.setattr(store, "check_held", lambda held: None)
    provider = available_provider(tmp_path, store_lifecycle)
    acquired = await provider.acquire(context())
    with pytest.raises(ContractViolation, match="affirmative sealed observation"):
        await acquired.materialize()
    assert not acquired.resource.ready and acquired.resource.initial_check is None
    assert len(world.closed) == 5


async def test_a_well_typed_check_for_another_binding_never_mints_readiness(
    tmp_path, store_lifecycle, monkeypatch,
):
    store = store_lifecycle[1]
    wrong = BindingCheck(digest("wrong-operator-binding", 1, "other"))
    monkeypatch.setattr(store, "check_held", lambda held: wrong)
    provider = available_provider(tmp_path, store_lifecycle)
    acquired = await provider.acquire(context())
    with pytest.raises(ContractViolation, match="affirmative sealed observation"):
        await acquired.materialize()
    assert not acquired.resource.ready and acquired.resource.initial_check is None


async def test_durable_closure_after_final_await_never_mints_readiness(
    tmp_path, store_lifecycle, monkeypatch,
):
    world, _, closure, _, released_guards = store_lifecycle
    original_require_open = closure.require_open
    observed = threading.Event()
    release = threading.Event()
    calls = 0

    def pause_after_real_open_observation(paths):
        nonlocal calls
        calls += 1
        original_require_open(paths)
        if calls == 4:
            observed.set()
            if not release.wait(5):
                raise TimeoutError("the closure race fixture was not released")

    monkeypatch.setattr(closure, "require_open", pause_after_real_open_observation)
    provider = available_provider(tmp_path, store_lifecycle)
    acquired = await provider.acquire(context())
    materializing = asyncio.create_task(acquired.materialize())
    assert await asyncio.to_thread(observed.wait, 5)
    try:
        closure.commit(acquired.resource.paths)
    finally:
        release.set()

    failure: BaseException | None = None
    try:
        try:
            await materializing
        except BaseException as exc:
            failure = exc
        assert isinstance(failure, ContractViolation)
        assert "permanently closed" in str(failure)
        assert not acquired.resource.ready
        assert acquired.resource.initial_check is None
        assert released_guards
        assert len(world.closed) >= 5
    finally:
        with pytest.raises(ContractViolation, match="permanently closed"):
            await provider.close(acquired, "discard")


async def test_one_acquisition_cannot_execute_a_second_task(tmp_path, store_lifecycle):
    launcher = bare_launcher(clean_native())
    provider = available_provider(tmp_path, store_lifecycle, launcher)
    acquired = await provider.acquire(context())
    await acquired.materialize()
    first = await acquired.resource.execute(
        TaskSpec(instruction="first"), workspace=None, grants=GRANTS,
    )
    assert first.status == "success" and len(launcher.calls) == 1
    with pytest.raises(ContractViolation, match="one task only"):
        await acquired.resource.execute(
            TaskSpec(instruction="second"), workspace=None, grants=GRANTS,
        )
    assert len(launcher.calls) == 1
    await provider.close(acquired, "release")


async def test_close_commits_closure_then_joins_materialization_waiting_for_lock(
    tmp_path, store_lifecycle,
):
    world, _, closure, _, released_guards = store_lifecycle
    world.lock_after = 10_000
    provider = available_provider(tmp_path, store_lifecycle)
    acquired = await provider.acquire(context())
    materializing = asyncio.create_task(acquired.materialize())
    while world.lock_attempts == 0:
        await asyncio.sleep(0)
    closed = await asyncio.wait_for(provider.close(acquired, "discard"), 5)
    assert closed.disposition == "discarded"
    with pytest.raises(asyncio.CancelledError):
        await materializing
    assert closure.is_closed(acquired.resource.paths)
    assert not acquired.resource.ready and released_guards
    assert len(world.closed) == 5


async def test_cleanup_releases_acquisition_guard_when_store_close_fails(
    tmp_path, store_lifecycle, monkeypatch,
):
    store = store_lifecycle[1]
    provider = available_provider(tmp_path, store_lifecycle)
    acquired = await provider.acquire(context())
    await acquired.materialize()
    held = acquired.resource._store_lock
    assert held is not None
    original = store.close_held

    def failing_close(value):
        original(value)
        raise OSError("store close failed")

    monkeypatch.setattr(store, "close_held", failing_close)
    with pytest.raises(OSError, match="store close failed"):
        await provider.close(acquired, "discard")
    assert store_lifecycle[4] == store_lifecycle[3]


async def test_reconcile_validates_the_complete_batch_before_any_closure(
    tmp_path, store_lifecycle, monkeypatch,
):
    provider = available_provider(tmp_path, store_lifecycle)
    current = context(epoch=3)
    first = await provider.acquire(context(epoch=1))
    second = await provider.acquire(context(epoch=2))

    def row(acquired, epoch):
        return CapabilityLease(
            lease_id=acquired.lease_id,
            acquisition_epoch=epoch,
            run_id=current.run_lease.run_id,
            binding_id=current.binding.binding,
            path=current.path,
            state="active",
            resource_ref=acquired.resource_ref,
        )

    good = StaleAcquisition(lease=row(first, 1), disposition="discard")
    bad_row = row(second, 2).model_copy(update={"binding_id": "other"})
    bad = StaleAcquisition(lease=bad_row, disposition="discard")
    disposed: list[str] = []

    async def dispose(closure, paths, **kwargs):
        disposed.append(paths.acquisition_id)
        return False

    monkeypatch.setattr(codex, "dispose_acquisition", dispose)
    with pytest.raises(ContractViolation, match="stale invocation"):
        await provider.reconcile(current, (good, bad))
    assert disposed == []


# --- the narrow layout's two descriptors (M8-N4-state-review.md, section 1) ---

CREDENTIAL_SHAPES = {
    "absent": None,
    "world-readable": (stat.S_IFREG | 0o644, 1, 1000),
    "second-name": (stat.S_IFREG | 0o600, 2, 1000),
    "other-owner": (stat.S_IFREG | 0o600, 1, 1001),
    "directory": (stat.S_IFDIR | 0o600, 1, 1000),
    "symlink": (stat.S_IFLNK | 0o600, 1, 1000),
}


@pytest.mark.parametrize("shape", sorted(CREDENTIAL_SHAPES))
async def test_an_unqualified_credential_file_refuses_before_any_launch(
    tmp_path, store_lifecycle, shape,
):
    world = store_lifecycle[0]
    world.credential = CREDENTIAL_SHAPES[shape]
    launcher = bare_launcher(clean_native())
    provider = available_provider(tmp_path, store_lifecycle, launcher)
    acquired = await provider.acquire(context())
    await acquired.materialize()
    outcome = await acquired.resource.execute(
        TaskSpec(instruction="x"), workspace=None, grants=GRANTS,
    )
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert outcome.error.detail == operator_store.CREDENTIAL_UNAVAILABLE
    assert launcher.calls == [] and world.configurations == []
    # A descriptor that was opened and refused is closed, never leaked.
    for descriptor in world.credential_opens:
        with pytest.raises(OSError):
            os.fstat(descriptor)  # closed in fact; numbers are reused
    await provider.close(acquired, "discard")


async def test_a_qualified_credential_file_is_the_accepting_twin(tmp_path, store_lifecycle):
    world = store_lifecycle[0]
    launcher = bare_launcher(clean_native())
    provider = available_provider(tmp_path, store_lifecycle, launcher)
    acquired = await provider.acquire(context())
    await acquired.materialize()
    outcome = await acquired.resource.execute(
        TaskSpec(instruction="x"), workspace=None, grants=GRANTS,
    )
    assert outcome.status == "success"
    assert len(launcher.calls) == 1 and len(world.credential_opens) == 1
    await provider.close(acquired, "release")


async def test_a_failed_seal_closes_the_credential_and_never_launches(
    tmp_path, store_lifecycle, monkeypatch,
):
    world = store_lifecycle[0]

    def refuse(data):
        raise ContractViolation("the sealed native data differs from what was written")

    monkeypatch.setattr(codex, "sealed_data_fd", refuse)
    launcher = bare_launcher(clean_native())
    provider = available_provider(tmp_path, store_lifecycle, launcher)
    acquired = await provider.acquire(context())
    await acquired.materialize()
    outcome = await acquired.resource.execute(
        TaskSpec(instruction="x"), workspace=None, grants=GRANTS,
    )
    assert outcome.status == "failure" and "sealed native data" in outcome.error.detail
    assert launcher.calls == []
    (credential,) = world.credential_opens
    with pytest.raises(OSError):
        os.fstat(credential)
    await provider.close(acquired, "discard")


async def test_a_cancelled_callers_mount_descriptors_close_only_after_its_exchange(
    tmp_path, store_lifecycle,
):
    """A number freed while the exchange still runs could be reused by a spawn."""

    release = asyncio.Event()
    entered = asyncio.Event()
    seen: dict[str, tuple[int, int]] = {}

    @dataclass(frozen=True, kw_only=True)
    class Holding(ScriptedLauncher):
        async def exchange(self, *args, native_store=None, **kwargs):
            seen["fds"] = native_store.mount_fds
            entered.set()
            try:
                await asyncio.shield(release.wait())
            except asyncio.CancelledError:
                for descriptor in native_store.mount_fds:
                    os.fstat(descriptor)  # still ours while the exchange runs
                await release.wait()
                raise
            return self.result

    base = bare_launcher(clean_native())
    launcher = Holding(
        runtime_root=base.runtime_root, expected_runtime=base.expected_runtime,
        bubblewrap=base.bubblewrap, policy=base.policy,
        expected_policy_sha256=base.expected_policy_sha256,
        native=base.native, result=base.result,
    )
    provider = available_provider(tmp_path, store_lifecycle, launcher)
    acquired = await provider.acquire(context())
    await acquired.materialize()
    caller = asyncio.create_task(acquired.resource.execute(
        TaskSpec(instruction="x"), workspace=None, grants=GRANTS,
    ))
    await entered.wait()
    caller.cancel()
    await asyncio.sleep(0.05)
    assert not caller.done(), "the cancelled caller returned before its exchange ended"
    for descriptor in seen["fds"]:
        os.fstat(descriptor)  # the exchange still runs, so both are still ours
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await caller
    for descriptor in seen["fds"]:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    await provider.close(acquired, "discard")
