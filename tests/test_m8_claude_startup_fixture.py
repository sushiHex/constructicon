"""Pinned installation proof uses synthetic archives, never vendor execution."""

from __future__ import annotations

import hashlib
import io
import json
import os
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
        assert (path / "claude").read_bytes() == payload
        return "vendor-pin"

    monkeypatch.setattr(fixture, "ROOT", root)
    monkeypatch.setattr(fixture, "MEMBER_SIZE", len(payload))
    monkeypatch.setattr(fixture, "MEMBER_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(fixture, "runtime_inventory", inventory)
    monkeypatch.setattr(fixture, "runtime_digest", tree_digest)
    monkeypatch.setattr(Path, "chmod", chmod)
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
    assert calls == [root / "runtime", root / "pinned-vendor"]
    assert list((root / "runtime").iterdir()) == []
    assert (root / "fixture.json").read_text() == '{"runtime_digest":"runtime-pin"}'
    assert modes == {root / "pinned-vendor/claude": 0o555,
                     root / "pinned-vendor": 0o555, root / "pinned-startup.json": 0o444}
    assert json.loads((root / "pinned-startup.json").read_text()) == report
    assert report["vendor_digest"] == "vendor-pin"
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
                                      "report", "runtime"])
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
