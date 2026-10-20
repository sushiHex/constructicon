"""Portable fixture behavior, never Linux descriptor-confinement evidence."""

import shutil
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.git import acquisition


@pytest.fixture
def portable_removal(monkeypatch, request):
    # Exercise the opted-in substitute on every host; restore the real platform
    # before any path operation or test body runs.
    with monkeypatch.context() as platform:
        platform.setattr(sys, "platform", "portable-fixture")
        request.getfixturevalue("portable_acquisition_namespace")

    removed = []

    def remove(path):
        removed.append(path)
        if isinstance(path, Path):
            shutil.rmtree(path)

    remove.avoids_symlink_attacks = True
    monkeypatch.setattr(acquisition, "shutil", SimpleNamespace(rmtree=remove))
    return acquisition._remove_at_namespace, remove, removed


def test_portable_removal_accepts_real_directory_then_absence(tmp_path, portable_removal):
    remove, _rmtree, removed = portable_removal
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "fixture.txt").write_text("disposable fixture", encoding="utf-8")
    paths = SimpleNamespace(payload=payload)

    assert remove(paths, paths) is True
    assert not payload.exists()
    assert removed == [payload]
    assert remove(paths, paths) is False
    assert removed == [payload]


@pytest.mark.parametrize("mode,attributes", [
    (stat.S_IFLNK, 0),
    (stat.S_IFDIR, stat.FILE_ATTRIBUTE_REPARSE_POINT),
    (stat.S_IFLNK, stat.FILE_ATTRIBUTE_REPARSE_POINT),
    (stat.S_IFREG, 0),
])
def test_portable_removal_refuses_redirected_or_non_directory_root(
    portable_removal, mode, attributes,
):
    # Synthetic lstat metadata keeps link/reparse refusal executable without
    # Windows symlink privileges; this is not a physical junction witness.
    remove, _rmtree, removed = portable_removal
    info = SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
    payload = SimpleNamespace(lstat=lambda: info)
    paths = SimpleNamespace(payload=payload)

    with pytest.raises(ContractViolation, match="must be a real directory"):
        remove(paths, paths)
    assert removed == []


def test_portable_removal_propagates_unobserved_payload_error(portable_removal):
    remove, _rmtree, removed = portable_removal
    error = PermissionError("scripted lstat refusal")

    def lstat():
        raise error

    paths = SimpleNamespace(payload=SimpleNamespace(lstat=lstat))
    with pytest.raises(PermissionError) as caught:
        remove(paths, paths)
    assert caught.value is error
    assert removed == []


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows junction witness")
def test_portable_removal_refuses_native_windows_junction(tmp_path, portable_removal):
    import _winapi

    remove, _rmtree, removed = portable_removal
    target = tmp_path / "target"
    target.mkdir()
    sentinel = target / "fixture.txt"
    sentinel.write_text("retained fixture", encoding="utf-8")
    junction = tmp_path / "junction"
    _winapi.CreateJunction(str(target), str(junction))
    try:
        assert not junction.is_symlink()
        assert junction.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        paths = SimpleNamespace(payload=junction)
        with pytest.raises(ContractViolation, match="must be a real directory"):
            remove(paths, paths)
        assert removed == []
        assert sentinel.read_text(encoding="utf-8") == "retained fixture"
    finally:
        # Unlink only the junction, never recursively remove its target.
        junction.rmdir()
    assert sentinel.read_text(encoding="utf-8") == "retained fixture"


def test_portable_removal_refuses_unsafe_tree_removal(tmp_path, portable_removal):
    remove, rmtree, removed = portable_removal
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "fixture.txt").write_text("retained fixture", encoding="utf-8")
    paths = SimpleNamespace(payload=payload)
    rmtree.avoids_symlink_attacks = False

    with pytest.raises(ContractViolation, match="symlink-safe acquisition disposal"):
        remove(paths, paths)
    assert removed == []
    assert (payload / "fixture.txt").read_text(encoding="utf-8") == "retained fixture"
