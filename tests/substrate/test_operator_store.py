"""Portable descriptor/state proof for N3a operator-store custody."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import operator_store
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.operator_store_world import StoreWorld, _identity


async def _open_and_hold(world: StoreWorld):
    binding = world.binding()
    candidate = binding.open_candidate()

    async def closure() -> None:
        return None

    held = await binding.acquire_lock(candidate, lambda: None, closure)
    return binding, held


async def test_active_exact_descriptor_is_a_positive_binding_check(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    binding, held = await _open_and_hold(world)
    try:
        check = binding.check_held(held)
        assert check == BindingCheck(world.sealed.operator_binding_digest)
        assert check.binding_digest == world.sealed.operator_binding_digest
        assert held.store_path == world.root / "bundle" / "store"
    finally:
        binding.close_held(held)


@pytest.mark.parametrize("state", ["missing", "wrong-generation", "noncanonical"])
def test_no_absent_or_ambiguous_active_selection_is_accepted(tmp_path, monkeypatch, state):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    if state == "missing":
        del world.metadata["active.json"]
    elif state == "wrong-generation":
        world.write_descriptor(2)
        world.activate(2)
    else:
        world.metadata["active.json"] += b"\n"
    with pytest.raises(ContractViolation, match="native store"):
        world.binding().open_candidate()


def test_active_generation_never_falls_back_to_an_old_matching_descriptor(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2)
    world.activate(2)
    world.install(monkeypatch)
    with pytest.raises(ContractViolation, match="binding"):
        world.binding().open_candidate()


@pytest.mark.parametrize("name", ["anchor.json", "active.json", "1.json"])
@pytest.mark.parametrize("version", [True, 1.0])
def test_schema_version_requires_an_exact_integer(tmp_path, monkeypatch, name, version):
    world = StoreWorld(tmp_path)
    body = operator_store.parse_json_value(world.metadata[name].decode())
    assert isinstance(body, dict)
    body["schema_version"] = version
    world.metadata[name] = operator_store.canonical_json(body).encode()
    world.install(monkeypatch)
    with pytest.raises(ContractViolation, match="native store"):
        world.binding().open_candidate()


@pytest.mark.parametrize("field", ["layout_law_digest", "mount_lock_law_digest"])
def test_selection_requires_the_current_runtime_law_not_only_matching_configuration(
    tmp_path, monkeypatch, field,
):
    world = StoreWorld(tmp_path)
    wrong_law = operator_store.digest("wrong-runtime-law", 1, field)
    world.sealed = world.sealed.model_copy(update={field: wrong_law})
    world.write_descriptor(1, **{field: wrong_law})
    world.activate(1)
    world.install(monkeypatch)
    with pytest.raises(ContractViolation, match="binding"):
        world.binding().open_candidate()


def test_selection_rederives_the_publisher_instance_from_the_live_store(
    tmp_path, monkeypatch,
):
    world = StoreWorld(tmp_path)
    # Model a coherent, but falsely labelled, replacement world: nothing in the
    # descriptor or active record may assert a caller-selected old instance.
    del world.metadata["1.json"]
    world.names.remove("1.json")
    world.store = _identity("replacement")
    world.sealed = operator_store.store_identity_for(
        world.key, 2, world.instance,
        subscription_mode_adapter_revision=world.mode,
        store_conformance_revision=world.conformance,
    )
    world.write_descriptor(2, store=world.store)
    world.activate(2)
    world.install(monkeypatch)
    with pytest.raises(ContractViolation, match="binding"):
        world.binding().open_candidate()


def test_store_directory_link_count_is_not_a_restart_identity_component(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.store = replace(world.store, nlink=world.store.nlink + 1)
    world.install(monkeypatch)
    opened = None
    try:
        opened = world.binding().open_candidate()
    except ContractViolation as exc:
        pytest.fail(f"a growing store directory changed its binding identity: {exc}")
    finally:
        if opened is not None:
            world.binding().close_candidate(opened)


async def test_terminal_identity_drift_refuses_after_an_initial_acceptance(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    binding, held = await _open_and_hold(world)
    try:
        assert binding.check_held(held).binding_digest == world.sealed.operator_binding_digest
        world.store = _identity("replacement")
        with pytest.raises(ContractViolation, match="binding"):
            binding.check_held(held)
    finally:
        binding.close_held(held)


async def test_path_replacement_while_waiting_cannot_transfer_initial_check(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.lock_after = 1
    world.install(monkeypatch)
    candidate = world.binding().open_candidate()

    async def closure() -> None:
        world.store = _identity("replacement-during-wait")

    with pytest.raises(ContractViolation, match="binding"):
        await world.binding().acquire_lock(candidate, lambda: None, closure)
    assert candidate.closed


async def test_same_instance_historical_root_or_lock_remap_refuses(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2, store=_identity("old-replacement"))
    world.install(monkeypatch)
    with pytest.raises(ContractViolation, match="instance history"):
        world.binding().open_candidate()


async def test_lock_wait_rechecks_control_and_closure_then_closes_candidate(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.lock_after = 100
    world.install(monkeypatch)
    candidate = world.binding().open_candidate()
    control = 0

    def check_control() -> None:
        nonlocal control
        control += 1

    async def closure() -> None:
        if control >= 2:
            raise ContractViolation("acquisition closed")

    with pytest.raises(ContractViolation, match="acquisition closed"):
        await world.binding().acquire_lock(candidate, check_control, closure)
    assert control == 2 and candidate.closed
    assert len(world.closed) == 5


async def test_cancellation_while_waiting_closes_every_candidate_descriptor(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.lock_after = 1000
    world.install(monkeypatch)
    candidate = world.binding().open_candidate()

    async def closure() -> None:
        return None

    task = asyncio.create_task(world.binding().acquire_lock(candidate, lambda: None, closure))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert candidate.closed and len(world.closed) == 5


def test_candidate_close_attempts_every_fd_when_one_close_fails(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    candidate = world.binding().open_candidate()
    closed: list[int] = []

    def close(fd: int) -> None:
        closed.append(fd)
        if len(closed) == 1:
            raise OSError("injected close failure")

    monkeypatch.setattr(operator_store, "_close", close)
    with pytest.raises(OSError, match="injected"):
        world.binding().close_candidate(candidate)
    assert candidate.closed and len(closed) == 5


def test_instance_is_derived_from_the_physical_root_not_a_caller_label(tmp_path, monkeypatch):
    first = StoreWorld(tmp_path / "one")
    second = StoreWorld(tmp_path / "two")
    assert first.instance == second.instance
    second.store = _identity("different-store")
    assert first.instance != __import__(
        "constructicon.substrate.executors.operator_store", fromlist=["_identity_instance"],
    )._identity_instance(second.store)
