"""Linux unit proofs of the real N3c metadata writers, unprivileged.

``_replace_metadata`` and ``_publish_new`` run for real on a temporary
directory. The ownership law changes only the group, to the directory's own,
so the test user can exercise the exact primitive; root ownership is the root
lane's assertion. Where a helper is driven end to end, only the descriptor,
identity and flock reads are substituted and the metadata lives on disk.
These are skipped off Linux, and a skip is not a pass.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import operator_store
from tests.operator_store_world import StoreWorld, _identity

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="the real metadata writers need Linux descriptors",
)


def directory_fd(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def pending(path: Path) -> list[str]:
    return [name for name in os.listdir(path) if name.startswith(".pending-")]


@pytest.fixture
def metadata_directory(tmp_path):
    target = tmp_path / "bundle"
    target.mkdir(mode=0o750)
    # A supplementary group makes the directory's group differ from the
    # process's, so the group assertion binds; the recorder binds either way.
    others = [group for group in os.getgroups() if group != os.getegid()]
    if others:
        os.chown(target, -1, others[0])
    previous = target / "active.json"
    previous.write_bytes(b"previous selection")
    previous.chmod(0o640)
    descriptor = directory_fd(target)
    try:
        yield target, descriptor
    finally:
        os.close(descriptor)


@pytest.fixture
def recorded(monkeypatch):
    events: list[tuple[object, ...]] = []
    fsync, rename, write, fchown = os.fsync, os.replace, os.write, operator_store._fchown

    def recording_fsync(fd):
        events.append(("fsync", "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"))
        fsync(fd)

    def recording_replace(source, target, **kwargs):
        events.append(("replace", target))
        rename(source, target, **kwargs)

    def recording_write(fd, data):
        events.append(("write",))
        return write(fd, data)

    def recording_fchown(fd, uid, gid):
        events.append(("fchown", uid, gid))
        fchown(fd, uid, gid)

    monkeypatch.setattr(operator_store.os, "fsync", recording_fsync)
    monkeypatch.setattr(operator_store.os, "replace", recording_replace)
    monkeypatch.setattr(operator_store.os, "write", recording_write)
    monkeypatch.setattr(operator_store, "_fchown", recording_fchown)
    return events


def test_replace_writes_seals_syncs_replaces_then_syncs_the_directory(
    metadata_directory, recorded,
):
    target, descriptor = metadata_directory
    group = os.stat(target).st_gid
    operator_store._replace_metadata(descriptor, "active.json", b"new selection")
    assert recorded == [
        ("write",), ("fchown", -1, group), ("fsync", "file"),
        ("replace", "active.json"), ("fsync", "directory"),
    ]
    info = os.stat(target / "active.json")
    assert (target / "active.json").read_bytes() == b"new selection"
    assert stat.S_IMODE(info.st_mode) == 0o440
    assert info.st_gid == group and info.st_uid == os.geteuid()
    assert pending(target) == []


def test_publication_seals_a_new_descriptor_by_the_same_law(metadata_directory, recorded):
    target, descriptor = metadata_directory
    group = os.stat(target).st_gid
    operator_store._publish_new(descriptor, "1.json", b"descriptor")
    assert ("fchown", -1, group) in recorded
    info = os.stat(target / "1.json")
    assert (target / "1.json").read_bytes() == b"descriptor"
    assert stat.S_IMODE(info.st_mode) == 0o440 and info.st_gid == group
    assert pending(target) == []


@pytest.mark.parametrize("fault", ["write", "fsync", "replace"])
def test_a_failed_replace_leaves_the_previous_file_and_no_temporary(
    metadata_directory, monkeypatch, fault,
):
    target, descriptor = metadata_directory

    def failing(*args, **kwargs):
        raise OSError(f"injected {fault} failure")

    if fault == "write":
        monkeypatch.setattr(operator_store.os, "write", lambda fd, data: 0)
    else:
        monkeypatch.setattr(operator_store.os, fault, failing)
    expected = "short write" if fault == "write" else f"injected {fault} failure"
    with pytest.raises(OSError, match=expected):
        operator_store._replace_metadata(descriptor, "active.json", b"new selection")
    assert (target / "active.json").read_bytes() == b"previous selection"
    assert pending(target) == []


class DiskWorld(StoreWorld):
    """StoreWorld whose metadata lives in real directories and real writers."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path)
        self.bundle_path = tmp_path / "disk-bundle"
        (self.bundle_path / "descriptors").mkdir(parents=True)
        for name, raw in self.metadata.items():
            self.path(name).write_bytes(raw)

    def path(self, name: str) -> Path:
        if name in {"anchor.json", "active.json"}:
            return self.bundle_path / name
        return self.bundle_path / "descriptors" / name

    def install(self, monkeypatch) -> None:
        real_replace = operator_store._replace_metadata
        real_names = operator_store._descriptor_names
        super().install(monkeypatch)
        monkeypatch.setattr(operator_store, "_replace_metadata", real_replace)
        monkeypatch.setattr(operator_store, "_descriptor_names", real_names)
        monkeypatch.setattr(
            operator_store, "_read_metadata", lambda opened, name: self.path(name).read_bytes(),
        )

        def opened(root, token):
            devnull = lambda: os.open(os.devnull, os.O_RDONLY)  # noqa: E731
            return operator_store.OpenedBundle(
                self.bundle_path, self.bundle_path / "store", devnull(),
                directory_fd(self.bundle_path), directory_fd(self.bundle_path / "descriptors"),
                devnull(), devnull(), self.bundle, self.store, self.lock,
            )

        monkeypatch.setattr(operator_store, "_open_bundle", opened)

    def add_descriptor(self, generation: int) -> None:
        self.write_descriptor(generation)
        self.path(f"{generation}.json").write_bytes(self.metadata[f"{generation}.json"])


def test_a_directory_sync_failure_after_the_replace_never_exposes_the_store(
    tmp_path, monkeypatch,
):
    world = DiskWorld(tmp_path)
    world.install(monkeypatch)
    bundle = os.stat(world.bundle_path).st_ino
    fsync = os.fsync
    failing = True

    def directory_fails(fd):
        if failing and os.fstat(fd).st_ino == bundle:
            raise OSError("injected directory fsync failure")
        fsync(fd)

    monkeypatch.setattr(operator_store.os, "fsync", directory_fails)
    body: list[bool] = []
    with (
        pytest.raises(ContractViolation, match="maintenance is unavailable"),
        operator_store.maintain_offline(world.root, world.key, wait_s=0),
    ):
        body.append(True)
    assert body == []
    visible = operator_store._withdrawal(world.path("active.json").read_bytes())
    assert visible == operator_store._Withdrawal(world.key, 1), "the replace did not happen"
    assert pending(world.bundle_path) == []

    # Defined rerun: another maintenance withdraws again and exposes the store.
    failing = False
    with operator_store.maintain_offline(world.root, world.key, wait_s=0) as maintenance:
        body.append(True)
        assert maintenance.generation_floor == 1
    assert body == [True]

    world.add_descriptor(2)
    failing = True
    with pytest.raises(ContractViolation, match="activation is unavailable"):
        operator_store.activate_offline(
            world.root, world.key, 2, qualified=world.sealed_for(2), wait_s=0,
        )
    assert operator_store._active(world.path("active.json").read_bytes()).generation == 2
    failing = False
    # Activation is not repeatable over an active state; maintenance is.
    with pytest.raises(ContractViolation, match="withdrawal is unavailable"):
        operator_store.activate_offline(
            world.root, world.key, 2, qualified=world.sealed_for(2), wait_s=0,
        )


@pytest.fixture
def fixed_layout(tmp_path, monkeypatch):
    root = tmp_path / "root"
    token = "a" * 64
    bundle = root / token
    (bundle / "descriptors").mkdir(parents=True)
    (bundle / "store").mkdir()
    (bundle / "retained.lock").touch()
    modes = {"root": 0o755, "bundle": 0o750, "descriptors": 0o750, "store": 0o700,
             "lock": 0o600}
    paths = {"root": root, "bundle": bundle, "descriptors": bundle / "descriptors",
             "store": bundle / "store", "lock": bundle / "retained.lock"}
    mounts = dict.fromkeys(paths, 7)
    by_inode = {os.stat(path).st_ino: name for name, path in paths.items()}

    def identity(fd):
        name = by_inode[os.fstat(fd).st_ino]
        return replace(_identity(name), mount_id=mounts[name], mode=modes[name])

    monkeypatch.setattr(
        operator_store, "_open_trusted_directory", lambda path: directory_fd(path),
    )
    monkeypatch.setattr(operator_store, "_trusted_directory", lambda fd: None)
    monkeypatch.setattr(operator_store, "_identity", identity)
    return root, token, mounts


@pytest.mark.parametrize("moved", [None, "store", "lock", "descriptors", "bundle"])
def test_a_child_on_another_mount_than_its_root_is_refused(fixed_layout, moved):
    root, token, mounts = fixed_layout
    if moved is None:
        opened = operator_store._open_bundle(root, token)
        assert opened.store_identity.mount_id == 7
        operator_store._close_opened(opened)
        return
    mounts[moved] = 8
    with pytest.raises(ContractViolation, match="mount topology"):
        operator_store._open_bundle(root, token)
