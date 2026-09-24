"""Portable N3c maintenance, activation and publication-lock laws.

Only the Linux primitives are substituted (``StoreWorld``): the descriptor and
identity reads, flock, and the two metadata writers. Every rule under test is
the production helper's own code. These doubles prove ordering, parsing and
lifecycle logic only; flock, ownership, ``fsync`` and mounts are the Linux
unit and root lanes' evidence, never this file's.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.manifest import CapabilityLease
from constructicon.core.native_operator import operator_binding_digest
from constructicon.core.workspace import StaleAcquisition
from constructicon.substrate.executors import codex, operator_store
from constructicon.substrate.executors.operator_store import BindingCheck, StoreMaintenance
from constructicon.substrate.git.acquisition import AcquisitionClosure
from constructicon.substrate.git.authority import GitAuthority
from tests.gitworld import seed_authority
from tests.operator_store_world import StoreWorld, _identity
from tests.substrate.test_codex_adapter import (
    GRANTS,
    bare_launcher,
    clean_native,
    context,
    provider_for,
)
from tests.substrate.test_codex_adapter import substituted_guard as substituted_guard
from tests.substrate.test_codex_store import available_provider
from tests.substrate.test_codex_store import store_lifecycle as store_lifecycle


def maintain(world: StoreWorld, *, wait_s: float = 0):
    return operator_store.maintain_offline(world.root, world.key, wait_s=wait_s)


def activate(world: StoreWorld, generation: int, qualified=None, *, wait_s: float = 0) -> None:
    operator_store.activate_offline(
        world.root, world.key, generation,
        qualified=world.sealed_for(generation) if qualified is None else qualified,
        wait_s=wait_s,
    )


def publish(world: StoreWorld, monkeypatch, generation: int, *, wait_s: float = 0):
    with monkeypatch.context() as patch:
        patch.setattr(operator_store.sys, "platform", "linux")
        return operator_store.publish_descriptor_offline(
            world.root, world.key, generation, runtime_uid=1000,
            subscription_mode_adapter_revision=world.mode,
            store_conformance_revision=world.conformance, wait_s=wait_s,
        )


async def no_closure() -> None:
    return None


def withdrawn(world: StoreWorld) -> operator_store._Withdrawal:
    return operator_store._withdrawal(world.metadata["active.json"])


# --- maintenance -------------------------------------------------------------


def test_maintenance_withdraws_durably_before_it_exposes_the_store(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.events.clear()
    with maintain(world) as maintenance:
        # The body is the exposure. Everything below must already be true.
        assert world.events == ["open", "lock", "open", "inventory", "replace"]
        assert withdrawn(world) == operator_store._Withdrawal(world.key, 1)
        assert isinstance(maintenance, StoreMaintenance) and not maintenance.closed
        assert maintenance.store_path == world.root / "bundle" / "store"
        assert maintenance.generation_floor == 1
        world.events.append("body")
    assert world.events[-2:] == ["replace", "body"], "exit wrote or activated something"
    assert maintenance.closed and len(world.closed) == 10


@pytest.mark.parametrize("fault", ["held", "replace"])
def test_a_held_lock_or_a_failed_withdrawal_never_runs_the_body(tmp_path, monkeypatch, fault):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    before = dict(world.metadata)
    if fault == "held":
        world.lock_after = 10**9
        expected = "retained lock is held"
    else:
        def failing(directory_fd, name, raw):
            raise OSError("injected withdrawal failure /private/locator")

        monkeypatch.setattr(operator_store, "_replace_metadata", failing)
        expected = "maintenance is unavailable"
    body: list[bool] = []
    with pytest.raises(ContractViolation, match=expected) as refused, maintain(
        world, wait_s=0.05,
    ):
        body.append(True)
    assert body == [] and world.metadata == before
    assert "/private/locator" not in str(refused.value)
    if fault == "held":
        assert world.lock_attempts > 1, "a positive wait made only one attempt"
    assert len(world.closed) == (5 if fault == "held" else 10)


async def test_every_provider_refuses_inside_maintenance(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2)
    world.install(monkeypatch)
    control = world.binding().open_candidate()
    world.binding().close_candidate(control)
    with maintain(world) as maintenance:
        assert maintenance.generation_floor == 2
        for sealed in (world.sealed, world.sealed_for(2)):
            with pytest.raises(ContractViolation, match="active selection is unavailable"):
                world.binding(sealed).open_candidate()


@pytest.mark.parametrize("helper", ["maintain", "activate", "publish"])
@pytest.mark.parametrize("replaced", [None, "store", "lock", "bundle"])
def test_objects_replaced_during_the_lock_wait_refuse_with_nothing_written(
    tmp_path, monkeypatch, helper, replaced,
):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.install_publisher(monkeypatch)
    if helper == "activate":
        world.write_descriptor(2)
        world.withdraw(1)
    before = dict(world.metadata)
    world_flock = operator_store._flock
    world.lock_after = 1

    def swapping(fd: int) -> bool:
        acquired = world_flock(fd)
        if not acquired and replaced is not None:
            setattr(world, replaced, _identity(f"{replaced}-replaced-during-wait"))
        return acquired

    monkeypatch.setattr(operator_store, "_flock", swapping)
    if replaced is None:
        # Permit: the same wait over unchanged objects proceeds.
        if helper == "maintain":
            with maintain(world, wait_s=1):
                pass
        elif helper == "activate":
            activate(world, 2, wait_s=1)
        else:
            publish(world, monkeypatch, 2, wait_s=1)
        assert world.lock_attempts == 2 and world.metadata != before
        return
    with pytest.raises(ContractViolation, match="binding is unavailable"):
        if helper == "maintain":
            with maintain(world, wait_s=1):
                pytest.fail("maintenance exposed a store replaced during its wait")
        elif helper == "activate":
            activate(world, 2, wait_s=1)
        else:
            publish(world, monkeypatch, 2, wait_s=1)
    assert world.metadata == before
    assert "replace" not in world.events and "publish" not in world.events


def test_maintenance_exit_releases_the_lock_and_activates_nothing(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.exclusive = True
    world.install(monkeypatch)
    with maintain(world) as maintenance:
        assert world.holder is not None
        with pytest.raises(ContractViolation, match="retained lock is held"), maintain(world):
            pytest.fail("two maintenance contexts held one store")
    assert maintenance.closed
    assert world.holder is None, "maintenance exit left the retained lock held"
    assert withdrawn(world) == operator_store._Withdrawal(world.key, 1)
    with maintain(world):
        assert world.holder is not None
    assert world.holder is None


async def test_a_materializer_waiting_through_a_maintenance_cycle_refuses_after_it(
    tmp_path, monkeypatch,
):
    world = StoreWorld(tmp_path)
    world.lock_after = 2
    world.install(monkeypatch)
    candidate = world.binding().open_candidate()
    # Each resume of the wait sees the next step another process completed.
    steps = iter([
        lambda: world.withdraw(1),
        lambda: (world.write_descriptor(2), world.activate(2)),
    ])

    async def cycle() -> None:
        next(steps, lambda: None)()

    with pytest.raises(ContractViolation, match="binding is unavailable"):
        await world.binding().acquire_lock(candidate, lambda: None, cycle)
    assert candidate.closed and next(steps, None) is None
    current = world.binding(world.sealed_for(2))
    held = await current.acquire_lock(current.open_candidate(), lambda: None, no_closure)
    try:
        assert current.check_held(held) == BindingCheck(world.sealed_for(2).operator_binding_digest)
    finally:
        current.close_held(held)


async def test_maintenance_refuses_while_an_acquisition_is_materialized(
    tmp_path, monkeypatch, substituted_guard,
):
    world = StoreWorld(tmp_path)
    world.exclusive = True
    world.install(monkeypatch)
    authority = tmp_path / "authority"
    authority.mkdir()
    closure = AcquisitionClosure(GitAuthority(seed_authority(authority), authority / "legacy"))
    provider = provider_for(
        bare_launcher(), unavailable_reasons=(), binding=(world.binding(), closure), root=tmp_path,
    )
    acquired = await provider.acquire(context())
    await acquired.materialize()
    before = dict(world.metadata)
    with pytest.raises(ContractViolation, match="retained lock is held"), maintain(world):
        pytest.fail("maintenance exposed a store with a live acquisition")
    assert world.metadata == before
    await provider.close(acquired, "release")
    assert world.holder is None
    with maintain(world) as maintenance:
        assert maintenance.generation_floor == 1


# --- activation --------------------------------------------------------------


async def test_maintain_publish_activate_then_the_new_generation_executes(
    tmp_path, store_lifecycle, monkeypatch,
):
    world, _, closure, _, _ = store_lifecycle
    world.install_publisher(monkeypatch)
    with maintain(world) as maintenance:
        assert maintenance.generation_floor == 1
    sealed = publish(world, monkeypatch, 2)
    assert sealed == world.sealed_for(2)
    assert withdrawn(world).generation_floor == 1, "publication activated a generation"
    activate(world, 2, sealed)
    active = operator_store._active(world.metadata["active.json"])
    descriptor = operator_store._descriptor(world.metadata["2.json"])
    assert active == operator_store._Active(
        world.key, 2, descriptor.binding_digest, descriptor.descriptor_digest,
    )

    launcher = bare_launcher(clean_native())
    current = provider_for(
        launcher, unavailable_reasons=(), binding=(world.binding(sealed), closure), root=tmp_path,
    )
    acquired = await current.acquire(context())
    await acquired.materialize()
    assert acquired.resource.initial_check == BindingCheck(sealed.operator_binding_digest)
    outcome = await acquired.resource.execute(
        TaskSpec(instruction="x"), workspace=None, grants=GRANTS,
    )
    assert outcome.status == "success"
    await current.close(acquired, "release")

    retired = await available_provider(tmp_path, store_lifecycle).acquire(context(epoch=2))
    with pytest.raises(ContractViolation, match="binding"):
        await retired.materialize()


def test_a_descriptor_published_before_maintenance_cannot_be_activated(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.install_publisher(monkeypatch)
    early = publish(world, monkeypatch, 2)
    with maintain(world) as maintenance:
        assert maintenance.generation_floor == 2
    before = dict(world.metadata)
    with pytest.raises(ContractViolation, match="activation is unavailable"):
        activate(world, 2, early)
    assert world.metadata == before
    later = publish(world, monkeypatch, 3)
    activate(world, 3, later)
    assert operator_store._active(world.metadata["active.json"]).generation == 3


@pytest.mark.parametrize("state", ["withdrawn", "absent", "active", "malformed", "other-key"])
def test_activation_requires_a_durable_withdrawal_for_this_key(tmp_path, monkeypatch, state):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2)
    world.install(monkeypatch)
    if state == "withdrawn":
        world.withdraw(1)
    elif state == "absent":
        del world.metadata["active.json"]
    elif state == "malformed":
        world.metadata["active.json"] = b'{"generation_floor":1}'
    elif state == "other-key":
        world.metadata["active.json"] = operator_store.canonical_json({
            "generation_floor": 1, "key": "another-key", "schema_version": 1,
        }).encode()
    before = dict(world.metadata)
    if state == "withdrawn":
        activate(world, 2)
        assert operator_store._active(world.metadata["active.json"]).generation == 2
        return
    with pytest.raises(ContractViolation, match="native store"):
        activate(world, 2)
    assert world.metadata == before and "replace" not in world.events


@pytest.mark.parametrize(("floor", "generation"), [(1, 1), (2, 2), (2, 1)])
def test_a_generation_at_or_below_the_floor_is_never_activated(
    tmp_path, monkeypatch, floor, generation,
):
    world = StoreWorld(tmp_path)
    for published in range(2, floor + 2):
        world.write_descriptor(published)
    world.withdraw(floor)
    world.install(monkeypatch)
    before = dict(world.metadata)
    with pytest.raises(ContractViolation, match="activation is unavailable"):
        activate(world, generation)
    assert world.metadata == before
    activate(world, floor + 1)
    assert operator_store._active(world.metadata["active.json"]).generation == floor + 1


@pytest.mark.parametrize("fault", [
    "none", "previous-sealed", "wrong-law", "live-store", "live-lock", "key", "generation",
])
def test_activation_checks_the_descriptor_against_qualification_and_live_objects(
    tmp_path, monkeypatch, fault,
):
    world = StoreWorld(tmp_path)
    qualified = world.sealed_for(2)
    if fault == "key":
        # Coherent for another key: only the descriptor's own key disagrees.
        qualified = operator_store.store_identity_for(
            "another-key", 2, world.instance,
            subscription_mode_adapter_revision=world.mode,
            store_conformance_revision=world.conformance,
        )
        world.write_descriptor(
            2, key="another-key",
            binding_digest=operator_binding_digest("another-key", 2, world.instance),
        )
    elif fault == "generation":
        # Coherent for generation 3, stored under the name the operator asked for.
        qualified = world.sealed_for(3)
        world.metadata["2.json"] = operator_store.canonical_json(
            world.descriptor(3).body(),
        ).encode()
        world.names.append("2.json")
    else:
        world.write_descriptor(2)
    if fault == "previous-sealed":
        qualified = world.sealed
    elif fault == "wrong-law":
        qualified = qualified.model_copy(update={
            "layout_law_digest": operator_store.digest("wrong-runtime-law", 1, "layout"),
        })
    elif fault == "live-store":
        # The instance excludes the inode; only the live identity comparison sees it.
        world.store = replace(world.store, ino=world.store.ino + 1)
    elif fault == "live-lock":
        world.lock = replace(world.lock, ino=world.lock.ino + 1)
    world.withdraw(1)
    world.install(monkeypatch)
    before = dict(world.metadata)
    if fault == "none":
        activate(world, 2, qualified)
        assert operator_store._active(world.metadata["active.json"]).generation == 2
        return
    with pytest.raises(ContractViolation, match="native store"):
        activate(world, 2, qualified)
    assert world.metadata == before


# --- the descriptor inventory ------------------------------------------------


def test_an_orphaned_publication_temporary_disables_everything_until_removed(
    tmp_path, monkeypatch,
):
    real_names = operator_store._descriptor_names
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.install_publisher(monkeypatch)
    monkeypatch.setattr(operator_store, "_descriptor_names", real_names)
    orphans = [".pending-" + "c" * 32]

    class Entry:
        def __init__(self, name: str) -> None:
            self.name = name

    @contextmanager
    def scandir(fd):
        yield iter([Entry(name) for name in [*world.names, *orphans]])

    monkeypatch.setattr(operator_store.os, "scandir", scandir)
    before = dict(world.metadata)
    with pytest.raises(ContractViolation, match="descriptor inventory"):
        world.binding().open_candidate()
    with pytest.raises(ContractViolation, match="descriptor inventory"), maintain(world):
        pytest.fail("maintenance ran over an unrecognised descriptor name")
    with pytest.raises(ContractViolation, match="descriptor inventory"):
        publish(world, monkeypatch, 2)
    assert world.metadata == before

    orphans.clear()
    candidate = world.binding().open_candidate()
    world.binding().close_candidate(candidate)
    with maintain(world):
        pass
    publish(world, monkeypatch, 2)
    assert "2.json" in world.metadata


REAL_NAMES = operator_store._descriptor_names


def real_inventory(world: StoreWorld, monkeypatch) -> None:
    """Run production ``_descriptor_names`` over the world's names, in scan order."""

    class Entry:
        def __init__(self, name: str) -> None:
            self.name = name

    @contextmanager
    def scandir(fd):
        # Reverse insertion order: the scan order is never the answer.
        yield iter([Entry(name) for name in reversed(world.names)])

    monkeypatch.setattr(operator_store, "_descriptor_names", REAL_NAMES)
    monkeypatch.setattr(operator_store.os, "scandir", scandir)


@pytest.mark.parametrize(("published", "accepted"), [
    ((9, 10), 11),  # lexicographic order would put 9.json last
    ((3,), 4),  # a gap: the count, 2, is not the maximum, 3
], ids=["numeric-order", "gapped"])
def test_the_floor_is_the_numeric_maximum_of_the_inventory(
    tmp_path, monkeypatch, published, accepted,
):
    world = StoreWorld(tmp_path)
    for generation in published:
        world.write_descriptor(generation)
    world.install(monkeypatch)
    real_inventory(world, monkeypatch)
    with maintain(world) as maintenance:
        assert maintenance.generation_floor == max(published)
    before = dict(world.metadata)
    with pytest.raises(ContractViolation, match="activation is unavailable"):
        activate(world, max(published))
    assert world.metadata == before
    world.write_descriptor(accepted)
    activate(world, accepted)
    assert operator_store._active(world.metadata["active.json"]).generation == accepted


# --- persistence and recovery across a generation ---------------------------


async def test_close_reconcile_and_maintenance_leave_store_content_byte_identical(
    tmp_path, store_lifecycle,
):
    world = store_lifecycle[0]
    store = world.root / "bundle" / "store"
    store.mkdir(parents=True)
    marker = store / "harmless-marker"
    marker.write_bytes(b"harmless vendor state\n")
    provider = available_provider(tmp_path, store_lifecycle, bare_launcher(clean_native()))
    stale = await provider.acquire(context(epoch=1))
    acquired = await provider.acquire(context(epoch=2))
    await acquired.materialize()
    await acquired.resource.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    await provider.close(acquired, "release")
    assert marker.read_bytes() == b"harmless vendor state\n"
    current = context(epoch=3)
    row = CapabilityLease(
        lease_id=stale.lease_id, acquisition_epoch=1, run_id=current.run_lease.run_id,
        binding_id=current.binding.binding, path=current.path, state="active",
        resource_ref=stale.resource_ref,
    )
    reaped = await provider.reconcile(
        current, (StaleAcquisition(lease=row, disposition="discard"),),
    )
    assert reaped.reaped == (stale.resource_ref,)
    with maintain(world):
        pass
    world.write_descriptor(2)
    activate(world, 2)
    assert marker.read_bytes() == b"harmless vendor state\n"
    assert sorted(path.name for path in store.iterdir()) == ["harmless-marker"]


def stale_row(acquired, current, *, epoch=1):
    return StaleAcquisition(lease=CapabilityLease(
        lease_id=acquired.lease_id, acquisition_epoch=epoch, run_id=current.run_lease.run_id,
        binding_id=current.binding.binding, path=current.path, state="active",
        resource_ref=acquired.resource_ref,
    ), disposition="discard")


async def test_an_old_generation_provider_disposes_but_never_materializes_after_activation(
    tmp_path, store_lifecycle,
):
    world = store_lifecycle[0]
    old = available_provider(tmp_path, store_lifecycle)
    stale = await old.acquire(context(epoch=1))
    with maintain(world):
        pass
    world.write_descriptor(2)
    activate(world, 2)
    current = context(epoch=3)
    reaped = await old.reconcile(current, (stale_row(stale, current),))
    assert reaped.reaped == (stale.resource_ref,)
    fresh = await old.acquire(context(epoch=4))
    with pytest.raises(ContractViolation, match="binding"):
        await fresh.materialize()
    assert not fresh.resource.ready


async def test_a_new_generation_provider_refuses_an_old_reference_without_disposal(
    tmp_path, store_lifecycle, monkeypatch,
):
    world, _, closure, _, _ = store_lifecycle
    old = available_provider(tmp_path, store_lifecycle)
    stale = await old.acquire(context(epoch=1))
    world.write_descriptor(2)
    world.withdraw(2)
    world.write_descriptor(3)
    activate(world, 3)
    new = provider_for(
        bare_launcher(), unavailable_reasons=(),
        binding=(world.binding(world.sealed_for(3)), closure), root=tmp_path,
    )
    own = await new.acquire(context(epoch=2))
    disposed: list[str] = []

    async def dispose(closure, paths, **kwargs):
        disposed.append(paths.acquisition_id)
        return False

    monkeypatch.setattr(codex, "dispose_acquisition", dispose)
    current = context(epoch=3)
    with pytest.raises(ContractViolation, match="contradicts its durable row"):
        await new.reconcile(current, (stale_row(stale, current),))
    assert disposed == []
    reaped = await new.reconcile(current, (stale_row(own, current, epoch=2),))
    assert reaped.reaped == (own.resource_ref,) and disposed == [own.acquisition_id]


# --- mount topology ---------------------------------------------------------


STORE = PurePosixPath("/srv/operator/bundle/store")


@pytest.mark.parametrize(("lines", "accepted"), [
    (["20 1 8:1 / / rw", "36 20 8:1 / /srv rw"], True),
    (["20 1 8:1 / / rw", "36 20 8:1 / /srv/operator/bundle/store rw"], True),
    (["20 1 8:1 / / rw", "37 20 8:1 / /srv/operator/bundle/store rw"], False),
    (["20 1 8:1 / / rw", "38 36 8:1 / /srv/operator/bundle/store/sub rw"], False),
    (["20 1 8:1 / / rw", "38 36 8:1 / /srv/operator/bundle/store/a\\040b rw"], False),
    (["20 1 8:1 / / rw", "39 20 8:1 / /srv/operator/bundle/store-sibling rw"], True),
    (["20 1 8:1 / / rw", "40 20 8:1 / /srv/operator/bundle/store\\040x rw"], True),
], ids=["none", "own-root", "other-at-root", "below", "below-escaped", "sibling", "escaped"])
def test_a_mount_at_or_below_the_store_is_refused(monkeypatch, lines, accepted):
    monkeypatch.setattr(
        operator_store, "_read_mountinfo", lambda: ("\n".join(lines) + "\n").encode(),
    )
    if accepted:
        operator_store._mounts_below(STORE, 36)
        return
    with pytest.raises(ContractViolation, match="mount topology"):
        operator_store._mounts_below(STORE, 36)


@pytest.mark.parametrize(("store", "line", "accepted"), [
    ("/srv/operator bundle/store", "36 20 8:1 / /srv/operator\\040bundle/store rw", True),
    ("/srv/operator bundle/store", "37 20 8:1 / /srv/operator\\040bundle/store rw", False),
    ("/srv/operator bundle/store", "38 36 8:1 / /srv/operator\\040bundle/store/sub rw", False),
    ("/srv/tab\tbundle/store", "37 20 8:1 / /srv/tab\\011bundle/store rw", False),
    ("/srv/back\\slash/store", "37 20 8:1 / /srv/back\\134slash/store rw", False),
], ids=["own-escaped", "other-at-escaped-root", "below-escaped-root", "tab", "backslash"])
def test_mountinfo_escapes_are_decoded_before_comparison(monkeypatch, store, line, accepted):
    """Each refusal here is invisible to a comparison of the undecoded field."""
    monkeypatch.setattr(
        operator_store, "_read_mountinfo", lambda: f"20 1 8:1 / / rw\n{line}\n".encode(),
    )
    if accepted:
        operator_store._mounts_below(PurePosixPath(store), 36)
        return
    with pytest.raises(ContractViolation, match="mount topology"):
        operator_store._mounts_below(PurePosixPath(store), 36)


def test_the_mountinfo_bound_binds_at_its_limit(monkeypatch):
    line = b"20 1 8:1 / / rw\n"
    exact = line * (operator_store.MAX_MOUNTINFO_BYTES // len(line))
    assert len(exact) == operator_store.MAX_MOUNTINFO_BYTES
    over = exact[:-len(line)] + b"20 1 8:1 / /  rw\n"  # one byte more, still well formed
    monkeypatch.setattr(operator_store, "_read_mountinfo", lambda: exact)
    operator_store._mounts_below(STORE, 36)
    monkeypatch.setattr(operator_store, "_read_mountinfo", lambda: over)
    with pytest.raises(ContractViolation, match="mount topology"):
        operator_store._mounts_below(STORE, 36)


@pytest.mark.parametrize(
    "line", ["20 1 8:1 /", "x1 1 8:1 / /srv rw"], ids=["short", "non-digit-id"],
)
def test_a_malformed_mountinfo_line_is_refused(monkeypatch, line):
    monkeypatch.setattr(
        operator_store, "_read_mountinfo", lambda: f"20 1 8:1 / / rw\n{line}\n".encode(),
    )
    with pytest.raises(ContractViolation, match="mount topology"):
        operator_store._mounts_below(STORE, 36)


# --- waiting and the publication lock ---------------------------------------


@pytest.mark.parametrize("holder", ["handle", "maintenance"])
async def test_publication_waits_for_every_holder_and_publishes_after_it(
    tmp_path, monkeypatch, holder,
):
    world = StoreWorld(tmp_path)
    world.exclusive = True
    world.install(monkeypatch)
    world.install_publisher(monkeypatch)
    before = dict(world.metadata)
    if holder == "handle":
        binding = world.binding()
        held = await binding.acquire_lock(binding.open_candidate(), lambda: None, no_closure)
        with pytest.raises(ContractViolation, match="retained lock is held"):
            publish(world, monkeypatch, 2)
        assert world.metadata == before and "publish" not in world.events
        binding.close_held(held)
    else:
        with maintain(world):
            before = dict(world.metadata)
            with pytest.raises(ContractViolation, match="retained lock is held"):
                publish(world, monkeypatch, 2)
            assert world.metadata == before and "publish" not in world.events
    assert world.holder is None
    sealed = publish(world, monkeypatch, 2)
    assert sealed == world.sealed_for(2) and "2.json" in world.metadata


@pytest.mark.parametrize("helper", ["maintain", "activate", "publish"])
@pytest.mark.parametrize(
    "wait_s", [True, -1, -0.5, float("nan"), float("inf"), "1", None],
    ids=["bool", "negative-int", "negative-float", "nan", "inf", "text", "none"],
)
def test_an_invalid_wait_refuses_before_any_lock_attempt(
    tmp_path, monkeypatch, helper, wait_s,
):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2)
    world.withdraw(1)
    world.install(monkeypatch)
    world.install_publisher(monkeypatch)
    before = dict(world.metadata)
    with pytest.raises(ContractViolation, match="wait is invalid"):
        if helper == "maintain":
            with maintain(world, wait_s=wait_s):
                pytest.fail("an invalid wait reached the body")
        elif helper == "activate":
            activate(world, 2, wait_s=wait_s)
        else:
            publish(world, monkeypatch, 3, wait_s=wait_s)
    assert world.lock_attempts == 0 and world.metadata == before
    assert world.events == []


@pytest.mark.parametrize("helper", ["maintain", "activate", "publish"])
def test_a_zero_wait_is_exactly_one_attempt_and_a_finite_wait_is_accepted(
    tmp_path, monkeypatch, helper,
):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2)
    world.withdraw(1)
    world.install(monkeypatch)
    world.install_publisher(monkeypatch)
    world.lock_after = 10**9
    with pytest.raises(ContractViolation, match="retained lock is held"):
        if helper == "maintain":
            with maintain(world, wait_s=0):
                pytest.fail("a held lock reached the body")
        elif helper == "activate":
            activate(world, 2, wait_s=0)
        else:
            publish(world, monkeypatch, 3, wait_s=0)
    assert world.lock_attempts == 1
    world.lock_after = 0
    # Permit: a finite int and a finite float both proceed.
    if helper == "maintain":
        for wait_s in (1, 0.5):
            with maintain(world, wait_s=wait_s):
                pass
    elif helper == "activate":
        activate(world, 2, wait_s=1)
        with maintain(world, wait_s=0.5):
            pass
        world.write_descriptor(3)
        activate(world, 3, wait_s=0.5)
        assert operator_store._active(world.metadata["active.json"]).generation == 3
    else:
        publish(world, monkeypatch, 3, wait_s=1)
        publish(world, monkeypatch, 4, wait_s=0.5)
        assert {"3.json", "4.json"} <= set(world.metadata)


# --- the anchor, the withdrawal record and activation's arguments -----------


def anchor_for(key: str, bundle: operator_store.FileHandleV1) -> bytes:
    return operator_store.canonical_json({
        "schema_version": 1, "key": key, "bundle": bundle.model_dump(),
    }).encode()


@pytest.mark.parametrize("helper", ["maintain", "activate"])
@pytest.mark.parametrize("anchor", ["other-key", "other-bundle"])
def test_offline_helpers_require_this_bindings_anchor(tmp_path, monkeypatch, helper, anchor):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2)
    world.withdraw(1)
    if anchor == "other-key":
        world.metadata["anchor.json"] = anchor_for("another-key", world.bundle)
    else:
        # The same boot: a different object, not a reboot.
        world.metadata["anchor.json"] = anchor_for(
            world.key, replace(world.bundle, ino=world.bundle.ino + 1),
        )
    world.install(monkeypatch)
    before = dict(world.metadata)
    with pytest.raises(ContractViolation, match="anchor is unavailable"):
        if helper == "maintain":
            with maintain(world):
                pytest.fail("maintenance ran under another binding's anchor")
        else:
            activate(world, 2)
    assert world.metadata == before and "lock" not in world.events


@pytest.mark.parametrize("record", ["schema-2", "extra-key", "bool-floor"])
def test_activation_refuses_a_malformed_withdrawal_record(tmp_path, monkeypatch, record):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2)
    body: dict[str, object] = {"generation_floor": 1, "key": world.key, "schema_version": 1}
    if record == "schema-2":
        body["schema_version"] = 2
    elif record == "extra-key":
        body["generation"] = 2
    else:
        body["generation_floor"] = True
    world.metadata["active.json"] = operator_store.canonical_json(body).encode()
    world.install(monkeypatch)
    before = dict(world.metadata)
    with pytest.raises(ContractViolation, match="withdrawal is unavailable"):
        activate(world, 2)
    assert world.metadata == before


@pytest.mark.parametrize(
    "generation", [0, -1, True, 2.0, "2"], ids=["zero", "negative", "bool", "float", "text"],
)
def test_activation_refuses_a_non_generation_before_filesystem_entry(
    tmp_path, monkeypatch, generation,
):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2)
    world.withdraw(1)
    world.install(monkeypatch)
    world.events.clear()
    with pytest.raises(ContractViolation, match="activation is unavailable"):
        operator_store.activate_offline(
            world.root, world.key, generation, qualified=world.sealed_for(2), wait_s=0,
        )
    assert world.events == [], "activation entered the bundle before refusing its argument"


def test_activation_refuses_a_look_alike_of_the_sealed_identity(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2)
    world.withdraw(1)
    world.install(monkeypatch)
    sealed = world.sealed_for(2)
    look_alike = SimpleNamespace(**dict(sealed))
    world.events.clear()
    with pytest.raises(ContractViolation, match="activation is unavailable"):
        activate(world, 2, look_alike)
    assert world.events == []
    activate(world, 2, sealed)
    assert operator_store._active(world.metadata["active.json"]).generation == 2


# --- reboot: maintenance re-anchors only the same physical bundle ----------


def test_after_a_reboot_only_maintenance_restores_the_binding(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.install_publisher(monkeypatch)
    retired = world.sealed
    world.reboot()
    before = dict(world.metadata)
    # Providers and the other two helpers keep refusing: no silent reuse.
    with pytest.raises(ContractViolation, match="anchor is unavailable"):
        world.binding(retired).open_candidate()
    with pytest.raises(ContractViolation, match="anchor is unavailable"):
        publish(world, monkeypatch, 2)
    world.write_descriptor(2)
    world.withdraw(1)
    staged = dict(world.metadata)
    with pytest.raises(ContractViolation, match="anchor is unavailable"):
        activate(world, 2)
    assert world.metadata == staged
    world.metadata = before
    world.names.remove("2.json")
    world.events.clear()
    with maintain(world) as maintenance:
        anchor = operator_store._anchor(world.metadata["anchor.json"])
        assert anchor == operator_store._Anchor(world.key, world.bundle), "not re-anchored"
        assert withdrawn(world) == operator_store._Withdrawal(world.key, 1)
        assert world.events.count("replace") == 2
        assert maintenance.generation_floor == 1
    sealed = publish(world, monkeypatch, 2)
    assert sealed == world.sealed_for(2) and sealed != retired
    activate(world, 2, sealed)
    candidate = world.binding(sealed).open_candidate()
    world.binding(sealed).close_candidate(candidate)
    with pytest.raises(ContractViolation, match="binding"):
        world.binding(retired).open_candidate()


@pytest.mark.parametrize("changed", [
    None, "same-boot", "handle_type", "handle_hex", "dev", "ino", "mode", "uid", "nlink",
])
def test_maintenance_re_anchors_only_the_same_physical_bundle(tmp_path, monkeypatch, changed):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    if changed == "same-boot":
        world.bundle = replace(world.bundle, mount_id=world.bundle.mount_id + 1)
    else:
        world.reboot()
    if changed in {"handle_type", "dev", "ino", "mode", "uid", "nlink"}:
        world.bundle = replace(world.bundle, **{changed: getattr(world.bundle, changed) + 1})
    elif changed == "handle_hex":
        world.bundle = replace(world.bundle, handle_hex="ff" + world.bundle.handle_hex)
    before = dict(world.metadata)
    if changed is None:
        with maintain(world):
            pass
        assert operator_store._anchor(world.metadata["anchor.json"]).bundle == world.bundle
        return
    with pytest.raises(ContractViolation, match="anchor is unavailable"), maintain(world):
        pytest.fail("maintenance re-anchored a substituted bundle")
    assert world.metadata == before and "replace" not in world.events


def test_a_failed_re_anchor_leaves_the_withdrawal_and_a_rerun_completes(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.reboot()
    stale_anchor = world.metadata["anchor.json"]
    replace_metadata = operator_store._replace_metadata

    def anchor_fails(directory_fd, name, raw):
        if name == "anchor.json":
            # Decision 7's order: the re-anchor follows the recorded withdrawal.
            assert b'"generation_floor"' in world.metadata["active.json"], (
                "re-anchored before the withdrawal was recorded"
            )
            raise OSError("injected anchor replace failure")
        replace_metadata(directory_fd, name, raw)

    monkeypatch.setattr(operator_store, "_replace_metadata", anchor_fails)
    with pytest.raises(ContractViolation, match="maintenance is unavailable"), maintain(world):
        pytest.fail("the store was exposed before the anchor was repaired")
    assert withdrawn(world).generation_floor == 1
    assert world.metadata["anchor.json"] == stale_anchor
    monkeypatch.setattr(operator_store, "_replace_metadata", replace_metadata)
    with maintain(world):
        assert operator_store._anchor(world.metadata["anchor.json"]).bundle == world.bundle


def test_an_anchor_substituted_during_the_lock_wait_is_refused_under_the_lock(
    tmp_path, monkeypatch,
):
    """Pre-lock the anchor names a genuine reboot; during the wait it comes to
    name another object. Only the decision made again under the lock refuses."""
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    previous = world.bundle
    world.reboot()
    substituted = anchor_for(world.key, replace(previous, ino=previous.ino + 1))
    world_flock = operator_store._flock
    world.lock_after = 1

    def swapping(fd: int) -> bool:
        acquired = world_flock(fd)
        if not acquired:
            world.metadata["anchor.json"] = substituted
        return acquired

    monkeypatch.setattr(operator_store, "_flock", swapping)
    active = world.metadata["active.json"]
    with (
        pytest.raises(ContractViolation, match="anchor is unavailable"),
        maintain(world, wait_s=1),
    ):
        pytest.fail("maintenance re-anchored over an anchor substituted during its wait")
    assert world.lock_attempts == 2, "the substitution never happened inside the wait"
    assert world.metadata["anchor.json"] == substituted
    assert world.metadata["active.json"] == active and "replace" not in world.events


@pytest.mark.parametrize("site", ["publish", "activate"])
@pytest.mark.parametrize("lock", ["unchanged", "replaced"])
def test_a_lock_replaced_across_a_reboot_is_refused_under_the_same_store(
    tmp_path, monkeypatch, site, lock,
):
    """The instance changes with the boot; the physical store and lock do not.

    A retained lock is never replaced while its binding exists (ADR 0020), so
    history matches the store by its boot-independent fields and then requires
    the same of the lock.
    """
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.install_publisher(monkeypatch)
    world.reboot()
    if lock == "replaced":
        world.lock = replace(
            world.lock, ino=world.lock.ino + 1, handle_hex="ee" + world.lock.handle_hex,
        )
    with maintain(world):
        pass
    if site == "activate":
        # Staged directly, so activation's own history check is the one tested.
        world.write_descriptor(2)
    before = dict(world.metadata)

    def attempt() -> None:
        if site == "publish":
            publish(world, monkeypatch, 2)
        else:
            activate(world, 2)

    if lock == "unchanged":
        attempt()
        assert "2.json" in world.metadata
        return
    with pytest.raises(ContractViolation, match="instance history"):
        attempt()
    assert world.metadata == before
