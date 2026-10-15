"""Byte capture, not SQLite opening; substitute only Windows filesystem predicates."""

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.substrate.journal import maintenance_evidence as evidence


@pytest.fixture
def layout(monkeypatch):
    if os.name == "nt":
        monkeypatch.setattr(evidence, "_custody", lambda info, *, private: True)
        original = evidence._metadata

        def metadata(info):
            # Windows fstat and lstat disagree on ctime; retain every other real field.
            return {**original(info), "ctime_ns": 0}

        monkeypatch.setattr(evidence, "_metadata", metadata)
    with tempfile.TemporaryDirectory(prefix="maintenance-evidence-test-", dir=Path.home()) as temp:
        parent = Path(temp).resolve()
        parent.chmod(0o700)
        root = parent / "app"
        reports = parent / "state"
        root.mkdir(mode=0o700)
        reports.mkdir(mode=0o700)
        report = reports / "application-run.json"
        for path, raw in [(root / "maintenance.sqlite", b"database"),
                          (root / "maintenance.sqlite-wal", b"committed-wal"),
                          (root / "maintenance-attempt.json", b'{"phase":"intent"}'),
                          (report, b'{"accepted":false}')]:
            path.write_bytes(raw)
            path.chmod(0o600)
        yield root, parent / "captured", report


def capture(layout):
    root, destination, report = layout
    return evidence.capture_evidence(root, destination, command_report=report)


def original_snapshot(layout):
    root, _, report = layout
    return {
        directory: {path.name: (path.read_bytes(), evidence._metadata(path.lstat()))
                    for path in directory.iterdir() if path.is_file()}
        for directory in (root, report.parent)
    }


def test_fixed_capture_preserves_originals_and_records_absences(layout, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("capture opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    before = original_snapshot(layout)
    root, destination, report = layout
    assert capture(layout) == destination
    manifest = json.loads((destination / "manifest.json").read_bytes())
    assert manifest["schema_version"] == 1 and manifest["complete"] is True
    assert set(manifest["files"]) == {*evidence.NAMES, "application-run.json"}
    assert set(path.name for path in destination.iterdir()) == {
        "manifest.json", "maintenance.sqlite", "maintenance.sqlite-wal",
        "maintenance-attempt.json", "application-run.json",
    }
    for name, record in manifest["files"].items():
        source = report if name == "application-run.json" else root / name
        if source.exists():
            raw = source.read_bytes()
            assert record == {"present": True, "bytes": len(raw),
                              "sha256": hashlib.sha256(raw).hexdigest(),
                              "metadata": evidence._metadata(source.lstat())}
            assert (destination / name).read_bytes() == raw
            assert (destination / name).stat().st_ino != source.stat().st_ino
            if os.name == "posix":
                assert (destination / name).stat().st_mode & 0o077 == 0
        else:
            assert record == {"present": False}
    assert before == original_snapshot(layout)


def test_missing_database_and_command_report_are_explicit_facts(layout):
    root, destination, report = layout
    (root / "maintenance.sqlite").unlink()
    report.unlink()
    capture(layout)
    files = json.loads((destination / "manifest.json").read_bytes())["files"]
    assert files["maintenance.sqlite"] == files["application-run.json"] == {"present": False}


def test_pending_attempt_is_preserved_not_promoted(layout):
    root, destination, _ = layout
    pending = root / "maintenance-attempt.json.next"
    pending.write_bytes(b'{"phase":"outcome"}')
    pending.chmod(0o600)
    capture(layout)
    assert (destination / pending.name).is_file()
    assert (destination / pending.name).read_bytes() == pending.read_bytes()
    assert (destination / "maintenance-attempt.json").read_bytes() == b'{"phase":"intent"}'


def test_owner_and_private_mode_predicate_is_closed(monkeypatch):
    monkeypatch.setattr(evidence, "os", SimpleNamespace(name="posix", getuid=lambda: 1001))
    assert evidence._custody(SimpleNamespace(st_uid=1001, st_mode=0o100600), private=True)
    assert not evidence._custody(SimpleNamespace(st_uid=1002, st_mode=0o100600), private=True)
    assert not evidence._custody(SimpleNamespace(st_uid=1001, st_mode=0o100640), private=True)
    assert evidence._custody(SimpleNamespace(st_uid=0, st_mode=0o40755), private=False)
    assert not evidence._custody(SimpleNamespace(st_uid=0, st_mode=0o40775), private=False)


def test_final_source_bytes_are_compared_even_if_metadata_repeats(layout, monkeypatch):
    root, destination, _ = layout
    metadata = evidence._metadata
    monkeypatch.setattr(evidence, "_metadata", lambda info: {
        **metadata(info), "mtime_ns": 0, "ctime_ns": 0,
    })
    original = evidence._read
    changed = False

    def read(path, info, output):
        nonlocal changed
        result = original(path, info, output)
        if not changed:
            changed = True
            (root / "maintenance.sqlite").write_bytes(b"modified")
        return result

    monkeypatch.setattr(evidence, "_read", read)
    with pytest.raises(evidence.EvidenceCaptureError):
        capture(layout)
    assert changed and (destination / "maintenance.sqlite").read_bytes() == b"database"
    assert not (destination / "manifest.json").exists()


@pytest.mark.parametrize("name", ["maintenance.sqlite", "maintenance.sqlite-wal",
                                 "maintenance-attempt.json.next", "application-run.json"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory"])
def test_unsafe_fixed_source_refuses(layout, name, kind):
    root, destination, report = layout
    path = report if name == "application-run.json" else root / name
    if path.exists():
        path.unlink()
    target = root / "target"
    target.write_bytes(b"private")
    target.chmod(0o600)
    if kind == "symlink":
        try:
            path.symlink_to(target)
        except OSError:
            pytest.skip("symlink primitive unavailable")
    elif kind == "hardlink":
        os.link(target, path)
    else:
        path.mkdir()
    with pytest.raises(evidence.EvidenceCaptureError, match=r"^maintenance evidence capture"):
        capture(layout)
    assert not destination.exists()


@pytest.mark.parametrize("fault", ["file", "total"])
def test_real_bounds_bind(layout, monkeypatch, fault):
    root, destination, report = layout
    monkeypatch.setattr(evidence, "MAX_FILE_BYTES", 16)
    if fault == "file":
        (root / "maintenance.sqlite").write_bytes(b"x" * 17)
    else:
        for path in [*root.iterdir(), report]:
            path.write_bytes(b"x" * 8)
        monkeypatch.setattr(evidence, "MAX_TOTAL_BYTES", 31)
    with pytest.raises(evidence.EvidenceCaptureError):
        capture(layout)
    assert not destination.exists()


@pytest.mark.parametrize("fault", ["bytes", "replacement", "absence", "inventory", "parent"])
def test_source_change_refuses_and_retains_partial_capture(layout, monkeypatch, fault):
    root, destination, _ = layout
    original = evidence._read
    changed = False

    def read(path, info, output):
        nonlocal changed
        result = original(path, info, output)
        if not changed:
            changed = True
            if fault == "bytes":
                path.write_bytes(b"changed!")
            elif fault == "replacement":
                path.unlink()
                path.write_bytes(b"database")
                path.chmod(0o600)
            elif fault == "absence":
                following = root / "maintenance-result.json"
                following.write_bytes(b"new")
                following.chmod(0o600)
            elif fault == "inventory":
                (root / "unrelated-new-entry").mkdir()
            else:
                root.rename(root.with_name("retained-old-root"))
                root.mkdir(mode=0o700)
        return result

    monkeypatch.setattr(evidence, "_read", read)
    with pytest.raises(evidence.EvidenceCaptureError):
        capture(layout)
    assert changed and destination.is_dir()
    assert (destination / "maintenance.sqlite").read_bytes() == b"database"
    assert not (destination / "manifest.json").exists()
    with pytest.raises(evidence.EvidenceCaptureError):
        capture(layout)


@pytest.mark.parametrize("location", ["root", "report", "occupied"])
def test_destination_must_be_fresh_and_outside_both_sources(layout, location):
    root, destination, report = layout
    if location == "root":
        destination = root / "capture"
    elif location == "report":
        destination = report.parent / "capture"
    else:
        destination.mkdir(mode=0o700)
        (destination / "sentinel").write_bytes(b"retain")
    with pytest.raises(evidence.EvidenceCaptureError):
        evidence.capture_evidence(root, destination, command_report=report)
    if location == "occupied":
        assert (destination / "sentinel").read_bytes() == b"retain"
    else:
        assert not destination.exists()


@pytest.mark.skipif(os.name != "posix", reason="real Linux custody predicate")
@pytest.mark.parametrize("unsafe", ["file", "root", "parent"])
def test_real_unsafe_modes_refuse(layout, unsafe):
    root, destination, _ = layout
    path = root / "maintenance.sqlite" if unsafe == "file" else (
        root if unsafe == "root" else root.parent)
    path.chmod(0o666 if unsafe == "file" else 0o777)
    try:
        with pytest.raises(evidence.EvidenceCaptureError):
            capture(layout)
        assert not destination.exists()
    finally:
        path.chmod(0o600 if unsafe == "file" else 0o700)
