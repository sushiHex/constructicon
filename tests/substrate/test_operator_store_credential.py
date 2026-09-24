"""The narrow layout's one store file, checked and handed over as a descriptor.

Portable: only the Linux open and ``fstat`` primitives are substituted. The
rule itself, the owner it is compared with and the descriptor's ownership stay
production code (M8-N4-state-review.md, section 1).
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import linux, operator_store
from tests.operator_store_world import StoreWorld

REGULAR = stat.S_IFREG | 0o600


async def held_store(world: StoreWorld):
    binding = world.binding()

    async def closure() -> None:
        return None

    return binding, await binding.acquire_lock(binding.open_candidate(), lambda: None, closure)


async def test_the_qualified_credential_is_handed_over_as_the_checked_descriptor(
    tmp_path, monkeypatch,
):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    binding, held = await held_store(world)
    try:
        fd = binding.open_credential(held)
        assert world.credential_opens == [fd]
        os.fstat(fd)  # the caller owns it, still open
        os.close(fd)
    finally:
        binding.close_held(held)


@pytest.mark.parametrize("facts", [
    (stat.S_IFREG | 0o644, 1, 1000),
    (stat.S_IFREG | 0o400, 1, 1000),
    (stat.S_IFREG | 0o600, 2, 1000),
    (stat.S_IFREG | 0o600, 1, 1001),
    (stat.S_IFDIR | 0o600, 1, 1000),
    (stat.S_IFLNK | 0o600, 1, 1000),
    None,
], ids=["group-readable", "read-only", "second-name", "other-owner", "directory",
        "symlink", "absent"])
async def test_an_unqualified_credential_refuses_and_closes_what_it_opened(
    tmp_path, monkeypatch, facts,
):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.credential = facts
    binding, held = await held_store(world)
    try:
        with pytest.raises(ContractViolation) as caught:
            binding.open_credential(held)
        assert str(caught.value) == operator_store.CREDENTIAL_UNAVAILABLE
        assert str(world.root) not in str(caught.value)
        # Closed in fact, not merely recorded: descriptor numbers are reused.
        for fd in world.credential_opens:
            with pytest.raises(OSError):
                os.fstat(fd)
    finally:
        binding.close_held(held)


async def test_the_owner_is_the_store_directorys_not_a_process_uid(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.store = replace(world.store, uid=4242)
    world.install(monkeypatch)
    world.credential = (REGULAR, 1, 4242)
    opened = world._opened()
    try:
        try:
            fd = operator_store.open_credential(opened)
        except ContractViolation:
            pytest.fail("the store owner's own 0600 credential was refused")
        os.close(fd)
        world.credential = (REGULAR, 1, 1000)
        with pytest.raises(ContractViolation):
            operator_store.open_credential(opened)
    finally:
        operator_store._close_opened(opened)


async def test_a_closed_hold_opens_nothing(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    binding, held = await held_store(world)
    binding.close_held(held)
    with pytest.raises(ContractViolation, match="lock is unavailable"):
        binding.open_credential(held)
    assert world.credential_opens == []


def test_the_real_open_is_path_only_no_follow_and_relative_to_the_store(monkeypatch):
    recorded = []

    def record_open(name, flags, mode=0o777, *, dir_fd=None):
        recorded.append((name, flags, dir_fd))
        return 99

    def refuse_read(*args, **kwargs):
        raise AssertionError("the credential file was read")

    monkeypatch.setattr(operator_store, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(operator_store, "_O_PATH", 0o10000000)
    monkeypatch.setattr(operator_store, "_O_NOFOLLOW", 0o400000)
    monkeypatch.setattr(operator_store, "_O_CLOEXEC", 0o2000000)
    monkeypatch.setattr(operator_store, "os", SimpleNamespace(
        **{**vars(os), "open": record_open, "read": refuse_read},
    ))
    assert operator_store._open_credential_fd(7) == 99
    assert recorded == [("auth.json", 0o10000000 | 0o400000 | 0o2000000, 7)]


def test_the_real_open_refuses_off_linux(monkeypatch):
    monkeypatch.setattr(operator_store, "sys", SimpleNamespace(platform="win32"))
    with pytest.raises(ContractViolation, match="requires Linux"):
        operator_store._open_credential_fd(7)


@pytest.mark.parametrize("mode", [0o600, 0o700, 0o660, 0o640, 0o604, 0o4600])
def test_only_mode_0600_passes(monkeypatch, mode):
    monkeypatch.setattr(
        operator_store, "_credential_facts", lambda descriptor: (stat.S_IFREG | mode, 1, 5),
    )
    if mode == 0o600:
        operator_store.check_credential(3, 5)
    else:
        with pytest.raises(ContractViolation):
            operator_store.check_credential(3, 5)


@pytest.mark.skipif(sys.platform != "linux", reason="memfd sealing runs in the Linux verify job")
def test_the_sealed_configuration_is_immutable_and_positioned_for_bwrap():
    import fcntl

    data = b'model = "fixture-only"\n'
    fd = linux.sealed_data_fd(data)
    try:
        # --ro-bind-data reads from the current offset, so it must be zero.
        assert os.read(fd, len(data) + 1) == data
        _, get_seals, required = linux.seal_constants(fcntl)
        assert fcntl.fcntl(fd, get_seals) == required
        with pytest.raises(PermissionError):
            os.pwrite(fd, b"x", 0)
        with pytest.raises(PermissionError):
            os.ftruncate(fd, 0)
        assert os.get_inheritable(fd) is False
    finally:
        os.close(fd)


def test_an_unstatable_descriptor_is_unavailable_not_an_escape(monkeypatch):
    def failing(fd):
        raise OSError("gone")

    monkeypatch.setattr(operator_store, "_credential_facts", failing)
    with pytest.raises(ContractViolation, match="no qualified credential file"):
        operator_store.check_credential(3, 5)


# --- seal constants: this build's, else the Linux UAPI's (CI lacked the names) ---


def test_absent_seal_names_fall_back_to_the_linux_uapi_values():
    assert linux.seal_constants(SimpleNamespace()) == (1033, 1034, 1 | 2 | 4 | 8)
    assert linux.memfd_flags(SimpleNamespace()) == 1 | 2


def test_present_seal_names_are_the_ones_used():
    module = SimpleNamespace(
        F_ADD_SEALS=7, F_GET_SEALS=9, F_SEAL_SEAL=16, F_SEAL_SHRINK=32,
        F_SEAL_GROW=64, F_SEAL_WRITE=128,
    )
    assert linux.seal_constants(module) == (7, 9, 16 | 32 | 64 | 128)
    assert linux.memfd_flags(SimpleNamespace(MFD_CLOEXEC=4, MFD_ALLOW_SEALING=8)) == 12
