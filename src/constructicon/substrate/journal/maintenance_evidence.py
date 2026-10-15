"""Fixed, private byte capture for offline maintenance diagnosis; never opens SQLite."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import TypedDict

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
CHUNK = 64 * 1024
NAMES = (
    "maintenance.sqlite", "maintenance.sqlite-wal", "maintenance.sqlite-shm",
    "maintenance.sqlite-journal", "maintenance-attempt.json", "maintenance-attempt.json.next",
    "maintenance-result.json",
)
FILES = (*NAMES, "application-run.json")


class EvidenceCaptureError(ValueError):
    """Closed refusal: incomplete private evidence is retained, never reused."""


class _Present(TypedDict):
    present: bool
    bytes: int
    sha256: str
    metadata: dict[str, int]


def _refuse() -> None:
    raise EvidenceCaptureError("maintenance evidence capture refused or incomplete")


def _custody(info: os.stat_result, *, private: bool) -> bool:
    """Only platform-bound ownership/mode predicate; portable tests substitute this."""
    uid = getattr(os, "getuid", lambda: -1)()
    return os.name == "posix" and uid > 0 and (
        info.st_uid == uid if private else info.st_uid in {0, uid}
    ) and not info.st_mode & (0o077 if private else 0o022)


def _metadata(info: os.stat_result) -> dict[str, int]:
    return dict(zip(("device", "inode", "mode", "uid", "gid", "nlink", "size",
                     "mtime_ns", "ctime_ns"),
                    (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                     info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns), strict=True))


def _directories(path: Path) -> dict[Path, tuple[int, ...]]:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        _refuse()
    result: dict[Path, tuple[int, ...]] = {}
    for entry in (path, *path.parents):
        info = entry.lstat()
        if not stat.S_ISDIR(info.st_mode) or not _custody(info, private=entry == path):
            _refuse()
        if entry == path and stat.S_IMODE(info.st_mode) != 0o700 and os.name == "posix":
            _refuse()
        # Ancestor timestamps can change when creating the distinct destination.
        result[entry] = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
    return result


def _inventory(root: Path) -> frozenset[str]:
    names = set()
    with os.scandir(root) as entries:
        for entry in entries:
            names.add(entry.name)
            if len(names) > 256:
                _refuse()
    return frozenset(names)


def _source(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not _custody(info, private=True):
        _refuse()
    if not 0 <= info.st_size <= MAX_FILE_BYTES:
        _refuse()
    return info


def _write_all(fd: int, raw: bytes) -> None:
    remaining = memoryview(raw)
    while remaining:
        count = os.write(fd, remaining)
        if count <= 0:
            _refuse()
        remaining = remaining[count:]


def _read(path: Path, expected: os.stat_result, output: Path | None) -> str:
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0))
    fd = os.open(path, flags)
    try:
        if _metadata(os.fstat(fd)) != _metadata(expected):
            _refuse()
        target = None
        try:
            if output is not None:
                target = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | getattr(os, "O_BINARY", 0), 0o600)
            digest = hashlib.sha256()
            count = 0
            while True:
                raw = os.read(fd, min(CHUNK, MAX_FILE_BYTES + 1 - count))
                if not raw:
                    break
                count += len(raw)
                if count > MAX_FILE_BYTES or count > expected.st_size:
                    _refuse()
                digest.update(raw)
                if target is not None:
                    _write_all(target, raw)
            if count != expected.st_size or _metadata(os.fstat(fd)) != _metadata(expected):
                _refuse()
            if target is not None:
                os.fsync(target)
        finally:
            if target is not None:
                os.close(target)
        if (following := _source(path)) is None or _metadata(following) != _metadata(expected):
            _refuse()
        return digest.hexdigest()
    finally:
        os.close(fd)


def capture_evidence(root: Path, destination: Path, *, command_report: Path) -> Path:
    """Capture fixed files after independently established quiescence, or refuse closed.

    Missing files are facts, not grants. The occupied destination and any partial
    bytes survive every failure. Original SQLite files are read only as bytes;
    atime is deliberately not an equality claim. Callers must never analyze the
    preserved capture in place.
    """
    try:
        roots = {root, command_report.parent}
        chains = {entry: _directories(entry) for entry in roots | {destination.parent}}
        if not destination.is_absolute() or destination.parent / destination.name != destination:
            _refuse()
        if any(destination.is_relative_to(entry) or entry.is_relative_to(destination)
               for entry in roots):
            _refuse()
        inventories = {entry: _inventory(entry) for entry in roots}
        paths = {name: root / name for name in NAMES}
        paths["application-run.json"] = command_report
        initial = {name: _source(path) for name, path in paths.items()}
        if sum(info.st_size for info in initial.values() if info is not None) > MAX_TOTAL_BYTES:
            _refuse()
        destination.mkdir(mode=0o700)
        destination_chain = _directories(destination)
        files: dict[str, _Present | dict[str, bool]] = {}
        for name, path in paths.items():
            info = initial[name]
            files[name] = {"present": False} if info is None else {
                "present": True, "bytes": info.st_size,
                "sha256": _read(path, info, destination / name), "metadata": _metadata(info),
            }
        for name, path in paths.items():
            following = _source(path)
            info = initial[name]
            if info is None:
                if following is not None:
                    _refuse()
            elif following is None or _metadata(following) != _metadata(info) or (
                _read(path, info, None) != files[name].get("sha256")
            ):
                _refuse()
        if any(_directories(entry) != chain for entry, chain in chains.items()):
            _refuse()
        if any(_inventory(entry) != names for entry, names in inventories.items()):
            _refuse()
        if _directories(destination) != destination_chain:
            _refuse()
        raw = (json.dumps({"schema_version": 1, "complete": True, "files": files},
                          sort_keys=True) + "\n").encode()
        fd = os.open(destination / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_BINARY", 0), 0o600)
        try:
            _write_all(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        if os.name == "posix":
            fd = os.open(destination, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return destination
    except (OSError, ValueError):
        raise EvidenceCaptureError("maintenance evidence capture refused or incomplete") from None
