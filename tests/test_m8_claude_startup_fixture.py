"""Pinned installation proof uses synthetic archives, never vendor execution."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import sys
import tarfile
from pathlib import Path

import pytest
from scripts.ci import build_m8_claude_startup_fixture as fixture


@pytest.fixture
def installation(monkeypatch, tmp_path):
    root = tmp_path / "fixture"
    root.mkdir()
    (root / "runtime").mkdir()
    (root / "fixture.json").write_text('{"runtime_digest":"runtime-pin"}')
    archive = tmp_path / "archive.tgz"
    payload = b"nonexecutable synthetic pinned member"
    calls = []
    modes = {}
    original_chmod = Path.chmod
    original_lstat = Path.lstat
    host_lib = tmp_path / "host-lib"
    host_lib.mkdir()
    for name in ("librt.so.1", "libpthread.so.0", "libdl.so.2"):
        (host_lib / name).write_bytes(("synthetic " + name).encode())

    def lstat(path, *args, **kwargs):
        observed = original_lstat(path, *args, **kwargs)
        if path == host_lib or path in host_lib.parents or path.parent == host_lib:
            facts = list(observed)
            facts[4] = 0  # Substitute only the hosted root-custody primitive.
            facts[0] &= ~0o022
            return os.stat_result(facts)
        return observed

    def chmod(path, mode, *args, **kwargs):
        modes[path] = mode
        original_chmod(path, mode, *args, **kwargs)

    def pack(*, name="package/claude", size=None, kind=tarfile.REGTYPE, duplicate=False,
             prelude=0):
        with tarfile.open(archive, "w:gz") as output:
            for index in range(prelude):
                output.addfile(tarfile.TarInfo(f"package/unused-{index}"))
            for _ in range(2 if duplicate else 1):
                info = tarfile.TarInfo(name)
                info.type = kind
                info.size = len(payload) if size is None else size
                info.linkname = "elsewhere" if kind == tarfile.SYMTYPE else ""
                output.addfile(info, io.BytesIO(payload) if info.isreg() else None)
        monkeypatch.setattr(fixture, "ARCHIVE_SHA256",
                            hashlib.sha256(archive.read_bytes()).hexdigest())

    def inventory(path):
        calls.append(path)
        return []

    def tree_digest(path):
        if path == root / "runtime":
            return "runtime-pin"
        if path == root / "pinned-runtime":
            return "pinned-runtime-pin"
        assert (path / "claude").read_bytes() == payload
        return "vendor-pin"

    monkeypatch.setattr(fixture, "ROOT", root)
    monkeypatch.setattr(fixture, "HOST_LIB", host_lib, raising=False)
    monkeypatch.setattr(fixture, "MEMBER_SIZE", len(payload))
    monkeypatch.setattr(fixture, "MEMBER_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(fixture, "runtime_inventory", inventory)
    monkeypatch.setattr(fixture, "runtime_digest", tree_digest)
    monkeypatch.setattr(Path, "chmod", chmod)
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(sys, "argv", ["proof", str(archive)])
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    pack()
    return root, archive, payload, pack, calls, modes


def test_pinned_builder_copies_only_verified_member_and_publishes_last(installation):
    root, _, payload, _, calls, modes = installation
    report = fixture.build()
    assert (root / "pinned-vendor/claude").read_bytes() == payload
    assert sorted(path.name for path in (root / "pinned-vendor").iterdir()) == ["claude"]
    assert calls == [root / "runtime", root / "pinned-vendor", root / "pinned-runtime"]
    assert list((root / "runtime").iterdir()) == []
    assert (root / "fixture.json").read_text() == '{"runtime_digest":"runtime-pin"}'
    assert modes[root / "pinned-vendor/claude"] == 0o555
    assert modes[root / "pinned-vendor"] == 0o555
    assert modes[root / "pinned-startup.json"] == 0o444
    assert json.loads((root / "pinned-startup.json").read_text()) == report
    assert report["vendor_digest"] == "vendor-pin"
    assert report["runtime_digest"] == "pinned-runtime-pin"
    assert set(report["added_libraries"]) == {"librt.so.1", "libpthread.so.0", "libdl.so.2"}
    expected_libraries = {}
    for name in ("librt.so.1", "libpthread.so.0", "libdl.so.2"):
        copied = root / "pinned-runtime/lib/x86_64-linux-gnu" / name
        expected = ("synthetic " + name).encode()
        assert copied.read_bytes() == expected
        assert modes[copied] == 0o444
        expected_libraries[name] = hashlib.sha256(expected).hexdigest()
    assert report["added_libraries"] == expected_libraries
    assert modes[root / "pinned-runtime"] == 0o555
    assert report["scope"] == "credential_free_native_startup_fixture"
    assert report["production_available"] is False
    assert report["subscription_qualified"] is False
    assert report["claude_qualified"] is False
    if os.name != "nt":
        assert (root / "pinned-vendor/claude").stat().st_mode & 0o777 == 0o555
        assert (root / "pinned-vendor").stat().st_mode & 0o777 == 0o555
        assert (root / "pinned-startup.json").stat().st_mode & 0o777 == 0o444


@pytest.mark.parametrize("defect", ["archive", "member", "missing", "duplicate", "symlink",
                                      "size", "oversize", "nonregular", "count", "existing",
                                      "report", "runtime", "runtime-destination"])
def test_pinned_builder_refuses_without_publishing(installation, monkeypatch, defect):
    root, archive, _, pack, _, _ = installation
    if defect == "archive":
        monkeypatch.setattr(fixture, "ARCHIVE_SHA256", "0" * 64)
    elif defect == "member":
        monkeypatch.setattr(fixture, "MEMBER_SHA256", "0" * 64)
    elif defect == "missing":
        pack(name="package/elsewhere")
    elif defect == "duplicate":
        pack(duplicate=True)
    elif defect == "symlink":
        pack(kind=tarfile.SYMTYPE)
    elif defect == "size":
        monkeypatch.setattr(fixture, "MEMBER_SIZE", 1)
    elif defect == "oversize":
        monkeypatch.setattr(fixture, "ARCHIVE_BYTES", archive.stat().st_size - 1)
    elif defect == "nonregular":
        archive.unlink()
        archive.mkdir()
    elif defect == "count":
        pack(prelude=32)
    elif defect == "existing":
        (root / "pinned-vendor").mkdir()
    elif defect == "report":
        (root / "pinned-startup.json").write_text("existing")
    elif defect == "runtime":
        (root / "fixture.json").write_text('{"runtime_digest":"different"}')
    elif defect == "runtime-destination":
        (root / "pinned-runtime").mkdir()
    caught = None
    try:
        fixture.build()
    except Exception as error:
        caught = error
    assert isinstance(caught, ValueError), defect
    expected = {
        "archive": "archive differs from the pinned source",
        "member": "selected member differs from the pinned source",
        "missing": "archive must contain exactly one selected member",
        "duplicate": "archive must contain exactly one selected member",
        "symlink": "selected member must be regular, not a link",
        "size": "selected member has the wrong size",
        "oversize": "archive exceeds the download bound",
        "nonregular": "archive must be a regular file",
        "count": "archive member count exceeds its bound",
        "existing": "startup fixture must be fresh",
        "report": "startup fixture must be fresh",
        "runtime": "existing runtime differs from the fake fixture",
        "runtime-destination": "startup fixture must be fresh",
    }
    assert str(caught) == expected[defect]
    if defect == "report":
        assert (root / "pinned-startup.json").read_text() == "existing"
    else:
        assert not (root / "pinned-startup.json").exists()
    if defect not in ("member", "existing"):
        assert not (root / "pinned-vendor").exists()


@pytest.mark.parametrize("defect", ["platform", "root", "host", "arguments", "relative"])
def test_pinned_builder_refuses_unsupported_invocations(installation, monkeypatch, defect):
    root, _, _, _, _, _ = installation
    if defect == "platform":
        monkeypatch.setattr(sys, "platform", "win32")
    elif defect == "root":
        monkeypatch.setattr(os, "geteuid", lambda: 1000)
    elif defect == "host":
        monkeypatch.setenv("RUNNER_ENVIRONMENT", "self-hosted")
    elif defect == "arguments":
        monkeypatch.setattr(sys, "argv", ["proof"])
    else:
        monkeypatch.setattr(sys, "argv", ["proof", "relative.tgz"])
    caught = None
    try:
        fixture.build()
    except Exception as error:
        caught = error
    assert isinstance(caught, ValueError), defect
    assert not (root / "pinned-vendor").exists()


@pytest.mark.parametrize("defect", ["source-owner", "source-write", "source-nonregular",
                                     "ancestor-owner", "ancestor-write", "ancestor-nonregular",
                                     "escape", "oversize"])
def test_pinned_runtime_refuses_untrusted_library_sources(installation, monkeypatch, defect):
    root, _, _, _, _, _ = installation
    host = fixture.HOST_LIB
    library = host / "librt.so.1"
    original_lstat, original_resolve = Path.lstat, Path.resolve

    def lstat(path, *args, **kwargs):
        observed = original_lstat(path, *args, **kwargs)
        facts = list(observed)
        if path == library:
            if defect == "source-owner":
                facts[4] = 1000
            elif defect == "source-write":
                facts[0] |= 0o020
            elif defect == "source-nonregular":
                facts[0] = stat.S_IFIFO | 0o444
        if path == host:
            if defect == "ancestor-owner":
                facts[4] = 1000
            elif defect == "ancestor-write":
                facts[0] |= 0o020
            elif defect == "ancestor-nonregular":
                facts[0] = stat.S_IFLNK | 0o755
        return os.stat_result(facts)

    monkeypatch.setattr(Path, "lstat", lstat)
    if defect == "escape":
        monkeypatch.setattr(Path, "resolve", lambda path, *a, **kw:
                            root / "outside" if path == library
                            else original_resolve(path, *a, **kw))
    if defect == "oversize":
        monkeypatch.setattr(fixture, "LIBRARY_BYTES", 1, raising=False)
    caught = None
    try:
        fixture.build()
    except Exception as error:
        caught = error
    assert isinstance(caught, ValueError), defect
    assert not (root / "pinned-startup.json").exists()


def test_pinned_runtime_clones_readonly_base_without_mutating_it(installation):
    root, _, _, _, _, modes = installation
    original = root / "runtime/lib/x86_64-linux-gnu/libc.so.6"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"preexisting curated library")
    original.chmod(0o444)
    original.parent.chmod(0o555)
    original.parent.parent.chmod(0o555)
    (root / "runtime").chmod(0o555)
    fixture.build()
    copied = root / "pinned-runtime/lib/x86_64-linux-gnu/libc.so.6"
    assert copied.read_bytes() == original.read_bytes() == b"preexisting curated library"
    assert modes[root / "runtime"] == modes[original.parent] == 0o555
    assert not (original.parent / "librt.so.1").exists()
    assert (root / "pinned-runtime/lib/x86_64-linux-gnu/librt.so.1").is_file()
    assert modes[copied] == 0o444


@pytest.mark.parametrize("defect", ["file", "link"])
def test_pinned_runtime_refuses_non_directory_library_placement(installation, monkeypatch, defect):
    root, _, _, _, _, _ = installation
    original_is_symlink = Path.is_symlink
    if defect == "file":
        (root / "runtime/lib").write_bytes(b"unchanged non-directory")
    else:
        (root / "runtime/lib").mkdir()
        monkeypatch.setattr(Path, "is_symlink", lambda path:
                            path == root / "pinned-runtime/lib" or original_is_symlink(path))
    caught = None
    try:
        fixture.build()
    except Exception as error:
        caught = error
    assert isinstance(caught, ValueError), defect
    assert str(caught) == "runtime library destination must be a real directory"
    assert not (root / "pinned-startup.json").exists()


def test_pinned_runtime_never_overwrites_a_preexisting_curated_library(installation):
    root, _, _, _, _, _ = installation
    original = root / "runtime/lib/x86_64-linux-gnu/librt.so.1"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"preserved existing library")
    caught = None
    try:
        fixture.build()
    except Exception as error:
        caught = error
    assert isinstance(caught, FileExistsError)
    assert original.read_bytes() == b"preserved existing library"
    assert (root / "pinned-runtime/lib/x86_64-linux-gnu/librt.so.1").read_bytes() == (
        b"preserved existing library"
    )
    assert not (root / "pinned-startup.json").exists()
