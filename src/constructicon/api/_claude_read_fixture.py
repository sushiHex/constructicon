"""One private, immutable Git fixture for Claude's admitted READ proof.

The only readable source file is harmless literal data. Preparation is an
operator action on a fresh private root; inspection precedes construction of
GitAuthority, whose constructor installs a hook.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import stat
from dataclasses import replace
from pathlib import Path

from constructicon.api._qualification_write_assembly import _CONFIG, _git
from constructicon.core.address import GitSha
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest, digest
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessLimits
from constructicon.substrate.git import acquisition, authority, contained
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.contained import ContainedWorkspaceProvider

TARGET = "refs/heads/claude-read"
FILE = "ready.txt"
CONTENT = b"ready\n"
WORKSPACE_CAPABILITY = "claude-read-workspace"
# Git archive of the one-file literal seed is 10,240 bytes. This bound is
# deliberately separate from the one-byte native worker artifact budget.
MATERIALIZATION_LIMITS = ProcessLimits(
    input_bytes=1, artifact_bytes=32 * 1024, stdout_bytes=1,
    record_bytes=1, stderr_bytes=1024,
)
_CHILDREN = ("authority.git", "authority-workspaces", "workspace-acquisitions")
_ACQUISITION = ("workspace-acquisitions/guards", "workspace-acquisitions/payloads")
_BLOB = hashlib.sha1(b"blob " + str(len(CONTENT)).encode() + b"\0" + CONTENT).hexdigest()
_TREE_BYTES = b"100644 " + FILE.encode() + b"\0" + bytes.fromhex(_BLOB)
_TREE = hashlib.sha1(b"tree " + str(len(_TREE_BYTES)).encode() + b"\0"
                     + _TREE_BYTES).hexdigest()
_SEED = (
    f"tree {_TREE}\n"
    "author constructicon <authority@constructicon.invalid> 1767225600 +0000\n"
    "committer constructicon <authority@constructicon.invalid> 1767225600 +0000\n"
    "\nconstructicon Claude READ fixture\n"
).encode("ascii")
BASE = GitSha("841fb659ad76d0bd140bae9842675e6d6822da17")
if hashlib.sha1(b"commit " + str(len(_SEED)).encode() + b"\0" + _SEED).hexdigest() != BASE:
    raise ContractViolation("Claude READ literal fixture commit disagrees with its seed")

def _revision() -> str:
    """Close the fixture's safety-relevant source over its reused Git laws."""
    return str(digest("claude-read-fixture-source", 1, {
        "fixture": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "shared_config": hashlib.sha256(_CONFIG).hexdigest(),
        "shared_git": hashlib.sha256(inspect.getsource(_git).encode()).hexdigest(),
        "git_authority": hashlib.sha256(inspect.getsource(authority).encode()).hexdigest(),
        "contained_workspace": hashlib.sha256(inspect.getsource(contained).encode()).hexdigest(),
        "acquisition": hashlib.sha256(inspect.getsource(acquisition).encode()).hexdigest(),
    }))


REVISION = _revision()


def _service_owner(info: os.stat_result) -> None:
    uid = getattr(os, "getuid", lambda: -1)()
    if os.name != "posix" or uid <= 0 or info.st_uid != uid or info.st_mode & 0o022:
        raise ContractViolation("Claude READ fixture requires private service-owned POSIX custody")


def _trusted_ancestors(path: Path) -> None:
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or parent.resolve() != parent:
            raise ContractViolation("Claude READ fixture ancestors are not canonical directories")
        _ancestor_owner(info)


def _ancestor_owner(info: os.stat_result) -> None:
    uid = getattr(os, "getuid", lambda: -1)()
    if os.name == "posix" and (info.st_uid not in (0, uid) or info.st_mode & 0o022):
        raise ContractViolation("Claude READ fixture ancestors lack trusted custody")


def _directory(path: Path) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise ContractViolation("Claude READ fixture path is not canonical")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ContractViolation("Claude READ fixture contains a non-directory")
    _service_owner(info)
    if os.name == "posix" and stat.S_IMODE(info.st_mode) != 0o700:
        raise ContractViolation("Claude READ fixture directories require mode 0700")


def _custody(root: Path) -> None:
    try:
        _trusted_ancestors(root)
        for path in (root, *(root / child for child in _CHILDREN),
                     *(root / child for child in _ACQUISITION),
                     root / "authority.git" / "hooks"):
            _directory(path)
        for path in (root / "authority.git").rglob("*"):
            info = path.lstat()
            if (not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                raise ContractViolation("Claude READ authority has an unsafe entry")
            _service_owner(info)
        for forbidden in ("objects/info/alternates", "info/grafts", "refs/replace"):
            if (root / "authority.git" / forbidden).exists():
                raise ContractViolation("Claude READ authority has alternate object authority")
    except OSError as error:
        raise ContractViolation("Claude READ fixture custody is unavailable") from error


def _identity(root: Path) -> Digest:
    return digest("claude-read-fixture", 1, {
        "root": str(root), "target": TARGET, "base": BASE,
        "file": FILE, "content_sha256": hashlib.sha256(CONTENT).hexdigest(),
        "source_revision": REVISION,
    })


def prepare_fixture(root: Path) -> Digest:
    """Create the one fixed seed only below a fresh canonical private root."""
    if (not root.is_absolute() or root.resolve() != root or root.exists()
            or root.is_symlink()):
        raise ContractViolation("Claude READ preparation requires a fresh canonical root")
    _trusted_ancestors(root)
    _service_owner(root.parent.stat())
    root.mkdir(mode=0o700)
    for child in (*_CHILDREN, *_ACQUISITION):
        (root / child).mkdir(mode=0o700, parents=True, exist_ok=True)
    _git(root, "init", "--bare", "--shared=0600", "--object-format=sha1", "--template=")
    (root / "authority.git" / "config").write_bytes(_CONFIG)
    (root / "authority.git" / "hooks").mkdir(mode=0o700, exist_ok=True)
    blob = _git(root, "hash-object", "-w", "--stdin", stdin=CONTENT).strip().decode()
    if blob != _BLOB:
        raise ContractViolation("trusted Git produced another Claude READ blob")
    tree = _git(root, "mktree", stdin=(f"100644 blob {blob}\t{FILE}\n").encode()).strip().decode()
    if tree != _TREE:
        raise ContractViolation("trusted Git produced another Claude READ tree")
    commit = _git(root, "hash-object", "-t", "commit", "-w", "--stdin",
                  stdin=_SEED).strip().decode()
    if commit != BASE:
        raise ContractViolation("trusted Git produced another Claude READ commit")
    _git(root, "update-ref", TARGET, BASE)
    _git(root, "symbolic-ref", "HEAD", TARGET)
    return inspect_fixture(root)


def inspect_fixture(root: Path) -> Digest:
    """Recheck metadata, exact Git configuration/ref and literal object bytes."""
    _custody(root)
    if _revision() != REVISION:
        raise ContractViolation("Claude READ fixture source changed")
    if (root / "authority.git" / "config").read_bytes() != _CONFIG:
        raise ContractViolation("Claude READ fixture has unreviewed Git configuration")
    if (
        _git(root, "rev-parse", "--is-bare-repository").strip() != b"true"
        or _git(root, "rev-parse", "--show-object-format").strip() != b"sha1"
        or _git(root, "symbolic-ref", "HEAD").strip().decode() != TARGET
        or _git(root, "rev-parse", "--verify", TARGET).strip().decode() != BASE
        or _git(root, "cat-file", "commit", BASE) != _SEED
        or _git(root, "cat-file", "tree", _TREE) != _TREE_BYTES
        or _git(root, "cat-file", "blob", _BLOB) != CONTENT
    ):
        raise ContractViolation("Claude READ fixture is not the fixed one-file seed")
    return _identity(root)


def workspace_provider(root: Path, launcher: LinuxLauncher) -> ContainedWorkspaceProvider:
    """Inspect before GitAuthority's hook write; use only the fixed target ref."""
    inspect_fixture(root)
    authority = GitAuthority(root / "authority.git", root / "authority-workspaces")
    return ContainedWorkspaceProvider(
        authority, root=root / "workspace-acquisitions", target_ref=TARGET,
        provider_id=WORKSPACE_CAPABILITY, posture=Posture.READ,
        launcher=replace(launcher, limits=MATERIALIZATION_LIMITS),
    )
