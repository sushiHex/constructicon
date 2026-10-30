"""Export and verify exact Git blob bytes for one explicitly pinned commit.

Run this file with isolated Python (-I -S -B) and either:
    export --repository REPO --commit SHA --out FRESH
    verify --repository REPO --commit SHA --source TREE

No archive, checkout conversion, or source normalization participates. Verification
includes every file and directory, including unexpected caches. This is a local
preparation check, not custody against a concurrent writer: callers keep the
repository, Git executable and source parents trusted while checking and using it.
A failed export can leave a partial directory; it is never resumed or replaced.
POSIX executable bits are preserved/checked; Windows supplies no such mode proof.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

MAX_ENTRIES = 100_000
MAX_BLOB_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_LISTING_BYTES = 16 * 1024 * 1024
TIMEOUT_S = 60
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


class Refused(ValueError):
    """The selected source could not be proved; no native action is involved."""


def require(condition: bool) -> None:
    if not condition:
        raise Refused("reviewed source refused")


def _git(repository: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    # Local object reads only. Ignore ambient Git repository/configuration overrides
    # and prohibit lazy fetch, replacement objects and interactive prompting.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="")
    result = subprocess.run(
        ["git", "--no-replace-objects", "-c", "protocol.allow=never",
         "-C", str(repository), *arguments],
        input=input_bytes, stdin=subprocess.DEVNULL if input_bytes is None else None,
        capture_output=True, check=False, timeout=TIMEOUT_S, env=environment,
    )
    require(result.returncode == 0 and result.stderr == b"")
    return result.stdout


def _path(raw: bytes) -> str:
    name = raw.decode("utf-8")
    parts = name.split("/")
    require(bool(name) and all(
        part not in ("", ".", "..") and part.casefold() != ".git"
        and not part.endswith((".", " "))
        and not any(ord(char) < 32 or ord(char) == 127 or char in '\\:<>"|?*' for char in part)
        and part.split(".", 1)[0].casefold() not in _RESERVED
        for part in parts
    ))
    return name


def _snapshot(repository: Path, commit: str) -> tuple[set[str], dict[str, tuple[str, bytes]]]:
    require(type(commit) is str and re.fullmatch(r"[0-9a-f]{40}", commit) is not None)
    require(_git(repository, "cat-file", "-t", commit) == b"commit\n")
    listing = _git(repository, "ls-tree", "-r", "-t", "-z", "--long", "--full-tree", commit)
    require(len(listing) <= MAX_LISTING_BYTES and (not listing or listing.endswith(b"\0")))
    directories: set[str] = set()
    entries: dict[str, tuple[str, str, int]] = {}
    objects: dict[str, int] = {}
    seen: set[str] = set()
    total = 0
    for row in listing.split(b"\0")[:-1]:
        metadata, raw_path = row.split(b"\t", 1)
        mode, kind, oid_raw, size_raw = metadata.split()
        name = _path(raw_path)
        require(name.casefold() not in seen and len(seen) < MAX_ENTRIES)
        seen.add(name.casefold())
        require(re.fullmatch(rb"[0-9a-f]{40}", oid_raw) is not None)
        if mode == b"040000" and kind == b"tree" and size_raw == b"-":
            directories.add(name)
            continue
        require(mode in (b"100644", b"100755") and kind == b"blob" and size_raw.isdigit())
        size, oid = int(size_raw), oid_raw.decode("ascii")
        total += size
        require(size <= MAX_BLOB_BYTES and total <= MAX_TOTAL_BYTES)
        require(oid not in objects or objects[oid] == size)
        objects[oid] = size
        entries[name] = (mode.decode("ascii"), oid, size)
    folded_directories = {path.casefold() for path in directories}
    for name in seen:
        require(all("/".join(name.split("/")[:i]) in folded_directories
                    for i in range(1, len(name.split("/")))))
    blobs: dict[str, bytes] = {}
    if objects:
        # Explicit finite pipe input, never inherited/interactive stdin. --batch
        # emits raw objects, independent of attributes, filters and autocrlf.
        output = _git(repository, "cat-file", "--batch",
                      input_bytes="".join(oid + "\n" for oid in objects).encode("ascii"))
        require(len(output) <= sum(objects.values()) + 128 * len(objects))
        at = 0
        for oid, size in objects.items():
            header = f"{oid} blob {size}\n".encode("ascii")
            require(output[at:at + len(header)] == header)
            at += len(header)
            body = output[at:at + size]
            at += size
            require(len(body) == size and output[at:at + 1] == b"\n")
            at += 1
            blobs[oid] = body
        require(at == len(output))
    return directories, {name: (mode, blobs[oid]) for name, (mode, oid, _) in entries.items()}


def _regular(info: os.stat_result, directory: bool = False) -> bool:
    return ((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and not getattr(info, "st_file_attributes", 0) & 0x400)


def export(repository: Path, commit: str, source: Path) -> int:
    directories, files = _snapshot(repository, commit)
    source.mkdir(mode=0o700)  # Exclusive claim, including dangling symlinks.
    for name in sorted(directories, key=lambda path: (path.count("/"), path)):
        (source / name).mkdir()
    for name, (mode, body) in files.items():
        path = source / name
        with path.open("xb") as stream:
            stream.write(body)
        if os.name != "nt":
            path.chmod(0o755 if mode == "100755" else 0o644)
    verify(repository, commit, source)
    return len(files)


def verify(repository: Path, commit: str, source: Path) -> int:
    directories, files = _snapshot(repository, commit)
    require(_regular(source.lstat(), directory=True))
    actual_directories: set[str] = set()
    actual_files: set[str] = set()
    pending = [(source, "")]
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as children:
            for child in children:
                name = prefix + child.name
                # Windows DirEntry.stat reports zero for inode/link fields.
                # lstat obtains the actual identity used by the opened-file check.
                info = Path(child.path).lstat()
                if _regular(info, directory=True):
                    require(name in directories)
                    actual_directories.add(name)
                    pending.append((Path(child.path), name + "/"))
                    continue
                require(_regular(info) and info.st_nlink == 1 and name in files)
                mode, expected = files[name]
                require(info.st_size == len(expected))
                if os.name != "nt":
                    require(info.st_mode & 0o111 == (0o111 if mode == "100755" else 0))
                with open(child.path, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    require(_regular(opened) and opened.st_nlink == 1
                            and (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino))
                    require(stream.read(len(expected) + 1) == expected)
                actual_files.add(name)
    require(actual_files == set(files) and actual_directories == directories)
    return len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("export", "verify"):
        action = actions.add_parser(name)
        action.add_argument("--repository", type=Path, required=True)
        action.add_argument("--commit", required=True)
        action.add_argument("--out" if name == "export" else "--source",
                            dest="source", type=Path, required=True)
    options = parser.parse_args(argv)
    try:
        count = (export if options.action == "export" else verify)(
            options.repository, options.commit, options.source,
        )
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        sys.stderr.buffer.write(b"reviewed-source-refused\n")
        return 1
    sys.stdout.buffer.write(
        f"reviewed-source-{options.action}-checked {options.commit} {count}\n".encode("ascii")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
