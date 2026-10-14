"""Private reviewed-bundle preparation; no model staging repository is imported."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from constructicon.core.address import GitSha
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import parse_json_value
from constructicon.core.maintenance import TARGET_PATH, VECTOR_PATH
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.git.process import GitProcess

SOURCE_FILES = (TARGET_PATH, "tests/test_plan_manifest_contribution.py",
                "src/constructicon/substrate/gates/maintenance.py")
SOURCE_HASHES = {
    TARGET_PATH: "90015debcf777e1a0d23b8484f04f8781ce96d6766183edcd07c09ac86feaa19",
    SOURCE_FILES[1]: "2460fe133113aaf1f6b8756a624fb73e0765295d0912dc9402ac0fc2f396399c",
    SOURCE_FILES[2]: "17cae803579f8ec4ebf1518a2beaa7533d0fc3cd16068c59cac55bbe92c7e28e",
}
CONFIG = b"[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = true\n"
MAX_BUNDLE_BYTES = 64 * 1024 * 1024


class SourcePin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_commit: GitSha = Field(pattern=r"^[0-9a-f]{40}$")
    target_ref: str = Field(pattern=r"^refs/heads/[A-Za-z0-9/_-]+$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sources: dict[str, str]


def private_root(root: Path) -> None:
    """Production custody; tests replace only this platform-bound predicate."""
    uid = getattr(os, "getuid", lambda: -1)()
    if os.name != "posix" or uid <= 0:
        raise ContractViolation("maintenance requires private service-owned POSIX custody")
    if not root.is_absolute() or root.resolve() != root:
        raise ContractViolation("maintenance root is not canonical")
    for path in (root, *root.parents):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, uid}:
            raise ContractViolation("maintenance ancestor custody differs")
        if info.st_mode & 0o022:
            raise ContractViolation("maintenance ancestors are writable by another principal")
    if root.stat().st_uid != uid or stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ContractViolation("maintenance root requires service-owned 0700 custody")


def read_bounded(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ContractViolation("maintenance evidence is not a bounded regular file")
        raw = os.read(fd, limit + 1)
        if len(raw) > limit:
            raise ContractViolation("maintenance evidence exceeds its byte bound")
        return raw
    finally:
        os.close(fd)


def write_once(path: Path, raw: bytes) -> None:
    """Publish exclusively and durably; partial publication is never reused."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    if os.name == "posix":
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


async def git(root: Path, *args: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise ContractViolation("maintenance trusted Git is unavailable")
    return await GitProcess(str(Path(executable).resolve()), ProcessLimits()).run(*args, cwd=root)


async def prepare_source(
    root: Path, bundle: Path, *, bundle_sha256: str, base_commit: GitSha, target_ref: str,
) -> SourcePin:
    """Require a new private root and review-pinned bytes before Git parses them."""
    if root.exists() or not root.is_absolute() or root.parent.resolve() != root.parent:
        raise ContractViolation("maintenance preparation requires a fresh canonical root")
    raw = read_bounded(bundle, MAX_BUNDLE_BYTES)
    if hashlib.sha256(raw).hexdigest() != bundle_sha256:
        raise ContractViolation("maintenance reviewed bundle digest differs")
    # Validate caller-selected base/ref before passing either to Git.
    SourcePin(bundle_sha256=bundle_sha256, base_commit=base_commit, target_ref=target_ref,
              config_sha256="0" * 64, sources={})
    root.mkdir(mode=0o700)
    private_root(root)
    reviewed = root / "reviewed.bundle"
    write_once(reviewed, raw)
    for name in ("authority.git", "authority-workspaces", "workspace-acquisitions",
                 "gate-acquisitions"):
        (root / name).mkdir(mode=0o700)
    await git(root / "authority.git", "init", "--bare", "--template=",
              "--object-format=sha1", ".")
    (root / "authority.git/hooks").mkdir(mode=0o700)
    (root / "authority.git/config").unlink()
    write_once(root / "authority.git/config", CONFIG)
    await git(root / "authority.git", "bundle", "verify", str(reviewed))
    await git(root / "authority.git", "-c", "protocol.file.allow=always",
              "fetch", "--no-tags", "--no-write-fetch-head",
              str(reviewed), str(base_commit))
    await git(root / "authority.git", "update-ref", target_ref, str(base_commit))
    await git(root / "authority.git", "symbolic-ref", "HEAD", target_ref)
    sources = {}
    for name in SOURCE_FILES:
        source = await git(root / "authority.git", "show", f"{base_commit}:{name}")
        # The ordinary consumer and trusted harness must be the installed exam.
        if hashlib.sha256(source).hexdigest() != SOURCE_HASHES[name]:
            raise ContractViolation("maintenance base does not contain the installed consumer")
        sources[name] = hashlib.sha256(source).hexdigest()
    if await git(root / "authority.git", "ls-tree", str(base_commit), "--", VECTOR_PATH):
        raise ContractViolation("maintenance base already has a vector contribution")
    pin = SourcePin(bundle_sha256=bundle_sha256, base_commit=base_commit, target_ref=target_ref,
        config_sha256=hashlib.sha256((root / "authority.git/config").read_bytes()).hexdigest(),
        sources=sources)
    write_once(root / "source-pin.json", pin.model_dump_json().encode())
    return pin


async def inspect_source(root: Path) -> SourcePin:
    """Before constructors: refuse redirected metadata, hooks, config and base drift."""
    private_root(root)
    pin = SourcePin.model_validate(parse_json_value(
        read_bounded(root / "source-pin.json", 8192).decode("utf-8", errors="strict"),
    ))
    if set(pin.sources) != set(SOURCE_FILES):
        raise ContractViolation("maintenance source pin omits the ordinary consumer")
    for name in ("source-pin.json", "reviewed.bundle", "maintenance.sqlite",
                 "maintenance.sqlite-wal", "maintenance.sqlite-shm",
                 "maintenance-attempt.json", "maintenance-result.json"):
        path = root / name
        if not os.path.lexists(path):
            continue
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.resolve() != path:
            raise ContractViolation("maintenance command metadata is redirected")
        if os.name == "posix" and (
            info.st_uid != getattr(os, "getuid", lambda: -1)() or info.st_mode & 0o022
        ):
            raise ContractViolation("maintenance command metadata custody differs")
    repo = root / "authority.git"
    for child in (repo, root / "authority-workspaces", root / "workspace-acquisitions",
                  root / "gate-acquisitions", repo / "hooks"):
        private_root(child)
    # Reject redirected metadata before any Git or authority constructor runs.
    for directory, children, files in os.walk(repo, followlinks=False):
        for name in (*children, *files):
            path = Path(directory) / name
            info = path.lstat()
            if path.is_symlink() or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ContractViolation("maintenance authority metadata is redirected")
            if os.name == "posix" and (
                info.st_uid != getattr(os, "getuid", lambda: -1)() or info.st_mode & 0o022
            ):
                raise ContractViolation("maintenance authority metadata custody differs")
    if (repo / "refs/replace").exists() or (repo / "info/grafts").exists():
        raise ContractViolation("maintenance authority rewrites commit ancestry")
    # A prepared bare repository has only our deny hook.
    for hook in (repo / "hooks").iterdir():
        if hook.is_symlink() or hook.name != "pre-receive":
            raise ContractViolation("maintenance authority contains an unreviewed hook")
        if hook.name == "pre-receive" and read_bounded(hook, 4096) != (
            b"#!/bin/sh\necho 'constructicon authority: pushes are refused;"
            b" the only install path is merge_verified' >&2\n"
            b"exit 1\n"
        ):
            raise ContractViolation("maintenance authority deny hook differs")
    alternates = repo / "objects/info/alternates"
    if alternates.exists() or alternates.is_symlink():
        raise ContractViolation("maintenance authority has object alternates")
    config = read_bounded(repo / "config", 8192)
    if config != CONFIG or hashlib.sha256(config).hexdigest() != pin.config_sha256:
        raise ContractViolation("maintenance authority configuration differs")
    base = (await git(repo, "rev-parse", "--verify", pin.target_ref)).strip().decode()
    if base != pin.base_commit:
        raise ContractViolation("maintenance authority base drifted")
    for name in SOURCE_FILES:
        source = await git(repo, "show", f"{pin.base_commit}:{name}")
        if hashlib.sha256(source).hexdigest() != pin.sources[name] or (
            hashlib.sha256(source).hexdigest() != SOURCE_HASHES[name]
        ):
            raise ContractViolation("maintenance immutable consumer differs")
    return pin
