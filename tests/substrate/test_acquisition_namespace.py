"""Real Linux namespace custody with credential-free Git and flock.

These bounded races exercise replacement of path names, not an attacker with
arbitrary same-UID access to edit the retained guard inode itself.
"""

from __future__ import annotations

import asyncio
import errno
import os
import sys
import threading

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.git import acquisition
from constructicon.substrate.git.acquisition import (
    AcquisitionClosure,
    AcquisitionPaths,
    acquisition_guard,
    dispose_acquisition,
)
from constructicon.substrate.git.authority import GitAuthority
from tests.gitworld import seed_authority


@pytest.fixture(autouse=True)
def linux_namespace():
    if sys.platform != "linux":
        if os.environ.get("M8_CONTAINMENT_REQUIRED"):
            pytest.fail("the required Linux acquisition namespace proof is unavailable")
        pytest.skip("physical acquisition namespace custody requires Linux")


@pytest.fixture
def world(tmp_path):
    closure = AcquisitionClosure(GitAuthority(seed_authority(tmp_path), tmp_path / "legacy"))
    paths = AcquisitionPaths(tmp_path / "owned", acquisition_id_for("namespace-proof", 1))
    paths.payload.mkdir(parents=True)
    (paths.payload / "owned-sentinel").write_text("owned")
    outside = tmp_path / "outside"
    outside_paths = AcquisitionPaths(outside, paths.acquisition_id)
    outside_paths.payload.mkdir(parents=True)
    (outside_paths.payload / "outside-sentinel").write_text("outside")
    return closure, paths, outside_paths


async def observed(event):
    assert await asyncio.to_thread(event.wait, 5), "the bounded worker seam was not reached"


def replace_root(paths, outside_paths):
    retained = paths.root.with_name("retained")
    paths.root.rename(retained)
    paths.root.symlink_to(outside_paths.root, target_is_directory=True)
    return AcquisitionPaths(retained, paths.acquisition_id)


def outside_intact(outside_paths):
    assert (outside_paths.payload / "outside-sentinel").read_text() == "outside"
    assert sorted(child.name for child in outside_paths.root.iterdir()) == ["payloads"]


def assert_descriptors_open(descriptors):
    for fd in descriptors:
        try:
            os.fstat(fd)
        except OSError:
            opened = False
        else:
            opened = True
        assert opened, "namespace descriptor closed before its worker joined"


async def test_namespace_accepts_real_guard_and_disposes_only_its_payload(world):
    closure, paths, outside_paths = world
    (paths.payload / "outside-link").symlink_to(outside_paths.payload, target_is_directory=True)
    assert not closure.is_closed(paths)
    assert await dispose_acquisition(closure, paths) is True
    assert closure.is_closed(paths) and not paths.payload.exists()
    assert paths.guard.is_file()
    outside_intact(outside_paths)
    assert await dispose_acquisition(closure, paths) is False
    assert closure.is_closed(paths) and paths.guard.is_file()


@pytest.mark.parametrize("component", ["root", "ancestor", "guards", "payloads"])
async def test_redirected_namespace_refuses_before_committing_fence(world, component):
    closure, paths, outside_paths = world
    if component == "root":
        paths.root.rename(paths.root.with_name("original"))
        paths.root.symlink_to(outside_paths.root, target_is_directory=True)
    elif component == "ancestor":
        alias = paths.root.parent / "alias"
        alias.symlink_to(paths.root.parent, target_is_directory=True)
        paths = AcquisitionPaths(alias / paths.root.name, paths.acquisition_id)
    else:
        target = paths.root / component
        if target.exists():
            target.rename(paths.root / "original-payloads")
        target.symlink_to(outside_paths.root, target_is_directory=True)
    with pytest.raises(ContractViolation):
        await dispose_acquisition(closure, paths)
    assert not closure.is_closed(paths), "refused namespace must not invent durable closure"
    outside_intact(outside_paths)


async def test_payload_leaf_symlink_refuses_after_committing_fence(world):
    closure, paths, outside_paths = world
    paths.payload.rename(paths.payload.with_name("original"))
    paths.payload.symlink_to(outside_paths.payload, target_is_directory=True)
    with pytest.raises(ContractViolation):
        await dispose_acquisition(closure, paths)
    assert closure.is_closed(paths), "physical refusal must retain the committed Git fence"
    assert paths.payload.is_symlink()
    outside_intact(outside_paths)


async def test_guard_leaf_symlink_refuses_without_opening_the_outside_file(world):
    closure, paths, outside_paths = world
    paths.guard.parent.mkdir(parents=True)
    paths.guard.symlink_to(outside_paths.payload / "outside-sentinel")
    with pytest.raises(OSError) as caught:
        async with acquisition_guard(paths):
            pass
    assert caught.value.errno == errno.ELOOP
    assert not closure.is_closed(paths)
    assert (paths.payload / "owned-sentinel").read_text() == "owned"
    outside_intact(outside_paths)


@pytest.mark.parametrize("redirect", [False, True])
async def test_payloads_created_after_namespace_pin_use_the_pinned_root(
    world, monkeypatch, redirect,
):
    closure, paths, outside_paths = world
    retained_payloads = paths.root / "initial-payloads"
    paths.payload.parent.rename(retained_payloads)
    entered, release = threading.Event(), threading.Event()
    commit = closure.commit

    def stalled_commit(*args, **kwargs):
        entered.set()
        assert release.wait(5), "closure worker was not released"
        return commit(*args, **kwargs)

    monkeypatch.setattr(closure, "commit", stalled_commit)
    disposing = asyncio.create_task(dispose_acquisition(closure, paths))
    try:
        await observed(entered)
        assert not closure.is_closed(paths)
        if redirect:
            paths.payload.parent.symlink_to(
                outside_paths.payload.parent, target_is_directory=True,
            )
            original = paths
        else:
            original = replace_root(paths, outside_paths)
            original.payload.mkdir(parents=True)
            (original.payload / "late-owned-sentinel").write_text("late owned")
    finally:
        release.set()
    if redirect:
        with pytest.raises(ContractViolation):
            await asyncio.wait_for(disposing, 5)
        assert original.payload.parent.is_symlink()
    else:
        assert await asyncio.wait_for(disposing, 5) is True
        assert not original.payload.exists()
        assert original.guard.is_file()
    assert closure.is_closed(paths), "late physical outcomes retain the committed Git fence"
    retained = original.root / retained_payloads.name / paths.acquisition_id
    assert (retained / "owned-sentinel").read_text() == "owned"
    outside_intact(outside_paths)


async def test_root_replacement_during_closure_await_uses_original_namespace(world, monkeypatch):
    closure, paths, outside_paths = world
    entered, release = threading.Event(), threading.Event()
    commit = closure.commit

    def stalled_commit(*args, **kwargs):
        entered.set()
        assert release.wait(5), "closure worker was not released"
        return commit(*args, **kwargs)

    monkeypatch.setattr(closure, "commit", stalled_commit)
    disposing = asyncio.create_task(dispose_acquisition(closure, paths))
    try:
        await observed(entered)
        assert not closure.is_closed(paths)
        original = replace_root(paths, outside_paths)
    finally:
        release.set()
    assert await asyncio.wait_for(disposing, 5) is True
    assert closure.is_closed(paths) and not original.payload.exists()
    assert original.guard.is_file()
    outside_intact(outside_paths)


@pytest.mark.parametrize("component", ["guards", "payloads"])
async def test_child_namespace_replacement_after_pin_uses_retained_descriptions(
    world, monkeypatch, component,
):
    closure, paths, outside_paths = world
    entered, release = threading.Event(), threading.Event()
    commit = closure.commit

    def stalled_commit(*args, **kwargs):
        entered.set()
        assert release.wait(5), "closure worker was not released"
        return commit(*args, **kwargs)

    monkeypatch.setattr(closure, "commit", stalled_commit)
    disposing = asyncio.create_task(dispose_acquisition(closure, paths))
    retained = paths.root / ("retained-" + component)
    try:
        await observed(entered)
        assert not closure.is_closed(paths)
        (paths.root / component).rename(retained)
        target = outside_paths.root if component == "guards" else outside_paths.payload.parent
        (paths.root / component).symlink_to(target, target_is_directory=True)
    finally:
        release.set()
    assert await asyncio.wait_for(disposing, 5) is True
    assert closure.is_closed(paths)
    if component == "guards":
        assert (retained / paths.acquisition_id).is_file()
        assert not paths.payload.exists()
    else:
        assert not (retained / paths.acquisition_id).exists()
        assert paths.guard.is_file()
    outside_intact(outside_paths)


async def test_root_replacement_during_guard_wait_cannot_redirect_lock_or_delete(
    world, monkeypatch,
):
    closure, paths, outside_paths = world
    waiting = asyncio.Event()
    sleep = asyncio.sleep

    async def observe_wait(delay):
        if delay == 0.01:
            waiting.set()
        await sleep(delay)

    monkeypatch.setattr(acquisition.asyncio, "sleep", observe_wait)
    async with acquisition_guard(paths):
        disposing = asyncio.create_task(dispose_acquisition(closure, paths))
        await asyncio.wait_for(waiting.wait(), 5)
        assert closure.is_closed(paths), "guard wait follows the durable fence"
        original = replace_root(paths, outside_paths)
        await sleep(0.03)
        assert not disposing.done(), "replacement must not provide a disjoint lock"
        assert (original.payload / "owned-sentinel").read_text() == "owned"
        outside_intact(outside_paths)
    assert await asyncio.wait_for(disposing, 5) is True
    assert not original.payload.exists() and original.guard.is_file()
    outside_intact(outside_paths)


@pytest.mark.parametrize("cancel", [False, True])
async def test_worker_schedule_replacement_and_cancellation_retain_namespace_until_join(
    world, monkeypatch, cancel,
):
    import fcntl

    closure, paths, outside_paths = world
    entered, release = threading.Event(), threading.Event()
    remove = acquisition._remove_at_namespace
    descriptors = []

    def stalled_remove(pinned_paths, namespace):
        descriptors.extend(fd for fd in (
            namespace.root_fd, namespace.guards_fd, namespace.payloads_fd,
        ) if fd is not None)
        entered.set()
        assert release.wait(5), "removal worker was not released"
        assert_descriptors_open(descriptors)
        return remove(pinned_paths, namespace)

    monkeypatch.setattr(acquisition, "_remove_at_namespace", stalled_remove)
    disposing = asyncio.create_task(dispose_acquisition(closure, paths))
    contender = None
    try:
        await observed(entered)
        assert closure.is_closed(paths)
        original = replace_root(paths, outside_paths)
        contender = os.open(original.guard, os.O_RDWR | os.O_CLOEXEC)
        if cancel:
            disposing.cancel("owner stopped")
            await asyncio.sleep(0)
            disposing.cancel("owner stopped again")
            await asyncio.sleep(0)
        assert not disposing.done()
        assert len(descriptors) == 3
        assert_descriptors_open(descriptors)
        with pytest.raises(BlockingIOError):
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        outside_intact(outside_paths)
    finally:
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError, match="owner stopped"):
                await asyncio.wait_for(disposing, 5)
        else:
            assert await asyncio.wait_for(disposing, 5) is True
        if contender is not None:
            os.close(contender)
    assert not original.payload.exists() and original.guard.is_file()
    for fd in descriptors:
        with pytest.raises(OSError) as caught:
            os.fstat(fd)
        assert caught.value.errno == errno.EBADF
    outside_intact(outside_paths)


async def test_guard_closes_only_its_copy_and_never_explicitly_unlocks(world, monkeypatch):
    import fcntl

    _, paths, _ = world
    flock = fcntl.flock
    operations = []

    def record_flock(fd, operation):
        operations.append(operation)
        return flock(fd, operation)

    monkeypatch.setattr(fcntl, "flock", record_flock)
    async with acquisition_guard(paths) as guard:
        inherited = os.dup(guard)
    contender = os.open(paths.guard, os.O_RDWR | os.O_CLOEXEC)
    try:
        with pytest.raises(BlockingIOError):
            flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert operations == [fcntl.LOCK_EX | fcntl.LOCK_NB]
        assert not any(operation & fcntl.LOCK_UN for operation in operations)
        os.close(inherited)
        inherited = None
        flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        if inherited is not None:
            os.close(inherited)
        os.close(contender)
