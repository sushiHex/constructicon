"""The lane's side of a root-held maintenance: custody proven, never taken.

Portable: only the identity read and the ``/proc/self/fdinfo`` read are
substituted (``StoreWorld.install_inheritance``). The Linux unit tests run the
real kernel report, including a real inherited description in a child process
(M8-N4-state-review.md, host-runtime interface item 4).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.substrate.executors import operator_store
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.operator_store_world import StoreWorld

PARENT = 4242


def world_with_inheritance(tmp_path, monkeypatch, *, floor: int = 1):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.withdraw(floor)
    return world, world.install_inheritance(monkeypatch, parent=PARENT)


def inherit(world: StoreWorld, fd: int, *, floor: int = 1, parent: int = PARENT):
    return operator_store.inherit_maintenance(
        world.root, world.key, fd, generation_floor=floor, parent=parent,
    )


def test_the_real_inherited_lock_is_accepted_and_carries_the_launch(tmp_path, monkeypatch):
    world, fd = world_with_inheritance(tmp_path, monkeypatch)
    with inherit(world, fd) as maintenance:
        assert maintenance.lock_fd == fd and maintenance.generation_floor == 1
        assert maintenance.check() == BindingCheck(digest("native-operator-maintenance", 1, {
            "key": world.key, "generation_floor": 1,
        }))
        credential = maintenance.open_credential()
        assert world.credential_opens == [credential]
        os.close(credential)
    assert maintenance.closed
    assert "lock" not in world.events and "replace" not in world.events, "it took or wrote"
    assert fd not in world.closed, "the inherited description is the helper's to release"
    os.fstat(fd)
    os.close(fd)


def other_lock(world: StoreWorld) -> operator_store.FileHandleV1:
    return replace(world.lock, handle_hex="00" + world.lock.handle_hex)


REFUSALS = {
    # No lock was inherited: the number names nothing this process holds.
    "not-inherited": lambda world, fd: (world.inherited.clear(), world.fdinfos.clear()),
    # The retained lock, opened afresh: the same object, but not the holding description.
    "stranger": lambda world, fd: world.fdinfos.update({fd: world.fdinfo()}),
    "wrong-identity": lambda world, fd: world.inherited.update({fd: other_lock(world)}),
    "self-taken": lambda world, fd: world.fdinfos.update(
        {fd: world.fdinfo(world.flock_line(PARENT + 1))},
    ),
    "other-inode": lambda world, fd: world.fdinfos.update(
        {fd: world.fdinfo(world.flock_line(PARENT, ino=world.lock.ino + 1))},
    ),
    "two-locks": lambda world, fd: world.fdinfos.update(
        {fd: world.fdinfo(world.flock_line(PARENT), world.flock_line(PARENT))},
    ),
    "shared": lambda world, fd: world.fdinfos.update(
        {fd: world.fdinfo(world.flock_line(PARENT, kind="FLOCK  ADVISORY  READ"))},
    ),
    "posix": lambda world, fd: world.fdinfos.update(
        {fd: world.fdinfo(world.flock_line(PARENT, kind="POSIX  ADVISORY  WRITE"))},
    ),
    "oversized": lambda world, fd: world.fdinfos.update({fd: world.fdinfos[fd] + b"x" * (
        operator_store.MAX_FDINFO_BYTES + 1
    )}),
    "active": lambda world, fd: world.activate(world.generation),
    "other-key": lambda world, fd: world.metadata.update({
        "active.json": operator_store.canonical_json({
            "generation_floor": 1, "key": "another-key", "schema_version": 1,
        }).encode(),
    }),
    # The record's floor differs from the inventory's highest generation.
    "record-floor": lambda world, fd: world.withdraw(0),
    # A generation above the recorded floor is present.
    "inventory-floor": lambda world, fd: world.write_descriptor(2),
    "other-anchor": lambda world, fd: world.metadata.update({
        "anchor.json": operator_store.canonical_json({
            "schema_version": 1, "key": world.key, "bundle": other_lock(world).model_dump(),
        }).encode(),
    }),
}


@pytest.mark.parametrize("change", REFUSALS)
def test_custody_that_is_not_proven_refuses_before_anything_is_exposed(
    tmp_path, monkeypatch, change,
):
    world, fd = world_with_inheritance(tmp_path, monkeypatch)
    REFUSALS[change](world, fd)
    try:
        with pytest.raises(ContractViolation), inherit(world, fd):
            pytest.fail("custody that was not proven exposed the store")
        assert world.credential_opens == []
        assert "lock" not in world.events and "replace" not in world.events
    finally:
        os.close(fd)


@pytest.mark.parametrize("floor", [0, 2], ids=["lower", "higher"])
def test_the_helpers_floor_must_be_the_recorded_one(tmp_path, monkeypatch, floor):
    world, fd = world_with_inheritance(tmp_path, monkeypatch)
    try:
        with pytest.raises(ContractViolation), inherit(world, fd, floor=floor):
            pytest.fail("another floor was accepted")
    finally:
        os.close(fd)


@pytest.mark.parametrize("arguments", [
    {"lock_fd": -1}, {"lock_fd": True}, {"generation_floor": -1}, {"generation_floor": 1.0},
    {"parent": 0}, {"parent": "4242"},
])
def test_malformed_custody_arguments_refuse_before_any_open(tmp_path, monkeypatch, arguments):
    world, fd = world_with_inheritance(tmp_path, monkeypatch)
    options = {"lock_fd": fd, "generation_floor": 1, "parent": PARENT, **arguments}
    lock_fd = options.pop("lock_fd")
    try:
        with (
            pytest.raises(ContractViolation),
            operator_store.inherit_maintenance(world.root, world.key, lock_fd, **options),
        ):
            pytest.fail("a malformed argument was accepted")
        assert "open" not in world.events
    finally:
        os.close(fd)


# --- root's side: the maintenance helper starts the lane ------------------------


class Recorded:
    def __init__(self, events: list, value: object) -> None:
        self.events, self.value = events, value

    def __enter__(self):
        self.events.append("enter")
        return self.value

    def __exit__(self, *_):
        self.events.append("exit")
        return False


class Child:
    def __init__(self, events: list, code: int, interrupt: bool) -> None:
        self.events, self.code, self.interrupt = events, code, interrupt
        self.killed = False

    def wait(self):
        self.events.append("wait")
        if self.interrupt and not self.killed:
            raise KeyboardInterrupt
        return self.code

    def kill(self):
        self.events.append("kill")
        self.killed = True


def helper(monkeypatch, *, code: int = 0, interrupt: bool = False) -> dict[str, Any]:
    """Substitute maintenance, the spawn and the user lookup; record the order."""

    seen: dict[str, Any] = {"events": []}
    withdrawn = SimpleNamespace(lock_fd=11, generation_floor=4)

    def maintain(root, key, *, wait_s):
        seen["maintained"] = (root, key, wait_s)
        return Recorded(seen["events"], withdrawn)

    def popen(argv, **options):
        seen["events"].append("spawn")
        seen["argv"], seen["options"] = argv, options
        return Child(seen["events"], code, interrupt)

    monkeypatch.setattr(operator_store, "maintain_offline", maintain)
    monkeypatch.setattr(operator_store.subprocess, "Popen", popen)
    monkeypatch.setattr(
        operator_store, "_service", lambda name: {"m8-service": (1001, 1002)}[name],
    )
    return seen


LANE = ["/usr/bin/python3", "-I", "lane.py", "startup", "--policy", "/p"]


def test_the_helper_starts_the_lane_as_the_service_with_only_the_lock(monkeypatch):
    seen = helper(monkeypatch, code=3)
    assert operator_store.main([
        "maintain", "--store-root", "/s", "--key", "k", "--wait", "2", "--", *LANE,
    ]) == 3
    assert seen["maintained"] == (Path("/s"), "k", 2.0)
    assert seen["events"] == ["enter", "spawn", "wait", "exit"], "maintenance ended early"
    assert seen["argv"] == [
        *LANE, f"--store-root={Path('/s')}", "--key=k", "--custody=maintenance",
        "--lock-fd=11", "--floor=4",
    ]
    assert seen["options"] == {
        "user": 1001, "group": 1002, "extra_groups": [],
        "env": {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, "cwd": "/",
        "close_fds": True, "pass_fds": (11,),
    }


def test_an_interrupted_helper_stops_the_lane_before_leaving_maintenance(monkeypatch):
    seen = helper(monkeypatch, interrupt=True)
    with pytest.raises(KeyboardInterrupt):
        operator_store.run_under_maintenance(
            Path("/s"), "k", ("lane",), service=(1001, 1002), wait_s=0,
        )
    assert seen["events"] == ["enter", "spawn", "wait", "kill", "wait", "exit"]


@pytest.mark.parametrize("service", [(0, 1002), (1001, 0)], ids=["root-user", "root-group"])
def test_the_helper_never_starts_a_root_lane(monkeypatch, service):
    seen = helper(monkeypatch)
    with pytest.raises(ContractViolation):
        operator_store.run_under_maintenance(
            Path("/s"), "k", ("lane",), service=service, wait_s=0,
        )
    assert seen["events"] == [], "maintenance began for a lane that would run as root"


@pytest.mark.parametrize("argument", [
    "--custody", "--custody=active", "--sealed=/x", "--lock-fd=3", "--floor=0",
    "--store-root=/other", "--key=other",
], ids=["custody", "custody-value", "sealed", "lock-fd", "floor", "store-root", "key"])
def test_only_the_helper_sets_the_store_the_key_and_the_custody(monkeypatch, argument):
    seen = helper(monkeypatch)
    with pytest.raises(SystemExit):
        operator_store.main([
            "maintain", "--store-root", "/s", "--key", "k", "--", *LANE, argument,
        ])
    assert seen["events"] == []


@pytest.mark.parametrize("argv", [
    ["maintain", "--store-root", "/s", "--key", "k", *LANE],
    ["maintain", "--store-root", "/s", "--key", "k", "--"],
    ["publish", "--store-root", "/s", "--key", "k", "--", *LANE],
], ids=["no-separator", "no-command", "other-helper"])
def test_the_helper_requires_a_lane_command_after_a_separator(monkeypatch, argv):
    seen = helper(monkeypatch)
    with pytest.raises(SystemExit):
        operator_store.main(argv)
    assert seen["events"] == []


# --- the real kernel report (Linux unit tests; no root) ------------------------

INHERITED_CHILD = """
import os, sys
from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import operator_store
fd, ino = int(sys.argv[1]), int(sys.argv[2])
lock = operator_store.FileHandleV1('', 0, 0, '', 0, ino, 0, 0, 0)
try:
    operator_store._require_inherited_hold(fd, lock, os.getppid())
except ContractViolation:
    print('refused')
else:
    print('accepted')
"""


def identity_with(ino: int) -> operator_store.FileHandleV1:
    return operator_store.FileHandleV1("", 0, 0, "", 0, ino, 0, 0, 0)


@pytest.mark.skipif(sys.platform != "linux", reason="fdinfo lock reports run in the Linux job")
def test_the_kernel_reports_a_flock_only_under_the_holding_description(tmp_path):
    import fcntl

    path = tmp_path / "retained.lock"
    path.write_bytes(b"")
    holder = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    stranger = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    lock = identity_with(os.fstat(holder).st_ino)
    try:
        with pytest.raises(ContractViolation):
            operator_store._require_inherited_hold(holder, lock, os.getpid())
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        operator_store._require_inherited_hold(holder, lock, os.getpid())
        with pytest.raises(ContractViolation):
            operator_store._require_inherited_hold(stranger, lock, os.getpid())
        with pytest.raises(ContractViolation):
            operator_store._require_inherited_hold(holder, lock, os.getppid())
        with pytest.raises(ContractViolation):
            operator_store._require_inherited_hold(holder, identity_with(lock.ino + 1), os.getpid())

        def child(fd: int) -> str:
            result = subprocess.run(
                [sys.executable, "-c", INHERITED_CHILD, str(fd), str(lock.ino)],
                pass_fds=(fd,), capture_output=True, text=True, timeout=30, check=True,
            )
            return result.stdout.strip()

        assert child(holder) == "accepted", "an inherited holding description was refused"
        assert child(stranger) == "refused", "a stranger's description passed as the holder"
    finally:
        os.close(stranger)
        os.close(holder)
