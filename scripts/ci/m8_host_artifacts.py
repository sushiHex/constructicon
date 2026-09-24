"""Judge and verify the reviewed M8 artifacts on the private host (#94, #77).

Runs unprivileged only, as ``/usr/bin/python3 -I``, after stock git has proved
that this file is the blob at a commit on main, and refuses to run as root.
Between a judgement and its verification, root installs the artifacts with a
fixed sequence of stock tools. Two sets exist. The qualification set (``judge``,
``verify``) is docs/plans/handoffs/M8-D2-host-installation.md; the launch set
(``stage-launch``, ``judge-launch``, ``verify-launch``) is
docs/plans/handoffs/M8-N4-host-runtime.md. Stdlib only: no Constructicon
import, no network, no marker file, and children get a fixed environment. The
production root and every destination are fixed; the command line names only
the commit and the operator's private workspace.

A third set (``controller-wheels``, ``stage-controller``, ``judge-controller``,
``verify-controller``) is the service user's controller environment, in the
same document's addendum. Only the two stagers write, and only through
``materialize`` into a fresh staging directory in the workspace. Every judge proves each precondition of
root's sequence. Every verifier recomputes from scratch against the blobs at
the commit, the digests they pin and root-owned host files, never against the
staged copies. They read the kernel's loaded-profile list from standard input,
where root's ``cat`` saved it. The verdict (``ready``, ``installed`` or
``staged``) stays false unless every fixed check passed, and the exit status
follows it.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from base64 import urlsafe_b64encode
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from typing import IO

ROOT = Path("/")
ROOT_UID = 0
GIT = "/usr/bin/git"
ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/nonexistent",
    "LANG": "C.UTF-8",
    "GIT_CONFIG_NOSYSTEM": "1",
    # --no-replace-objects leaves info/grafts in force; this disables it.
    "GIT_GRAFT_FILE": "/nonexistent",
}
SCRIPT = "scripts/ci/m8_host_artifacts.py"
PROBE = "scripts/ci/qualify_m8_runner.py"
PROFILE = "scripts/ci/constructicon-m8-bwrap.apparmor"
BWRAP_SOURCE = "usr/bin/bwrap"
BWRAP_SHA256 = "e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71"
PARSER = "usr/sbin/apparmor_parser"
INSTALL = "usr/bin/install"
CAT = "usr/bin/cat"
# Every tool root runs in the runbook's R4, by these absolute paths.
ROOT_TOOLS = (INSTALL, CAT, PARSER)
PROFILE_NAMES = ("constructicon-m8-bwrap", "constructicon-m8-payload")
DIRECTORY = "opt/constructicon-m8-qualification"
DIRECTORY_MODE = 0o755
PROFILE_DESTINATION = "etc/apparmor.d/constructicon-m8-bwrap"
# Destination -> (reviewed source path, final mode). ``None`` is the host's
# pinned bubblewrap, which git cannot supply. Root installs them in this order,
# each reviewed file from ``<workspace>/staging/<destination's name>``.
FILES: dict[str, tuple[str | None, int]] = {
    DIRECTORY + "/probe.py": (PROBE, 0o444),
    DIRECTORY + "/bwrap": (None, 0o555),
    PROFILE_DESTINATION: (PROFILE, 0o444),
}
# Inside the operator's private workspace.
REPOSITORY = "source.git"
STAGING = "staging"
LISTING_LIMIT = 1 << 20

# The launch set (N4's host runtime). ``LAUNCH`` holds exactly LAUNCH_ENTRIES.
LAUNCH = "var/lib/constructicon-m8-launch"
LAUNCH_MODE = 0o755
LAUNCH_ENTRIES = (
    "bwrap", "codex-models.json", "native-codex", "operator-stores", "runtime", "runtime.json",
)  # fmt: skip
STORE_MODE = 0o750
LAUNCH_PROFILE = "scripts/ci/constructicon-m8-launch.apparmor"
LAUNCH_PROFILE_DESTINATION = "etc/apparmor.d/constructicon-m8-launch"
LAUNCH_PROFILE_NAMES = ("constructicon-m8-launch", "constructicon-m8-workload")
SUPERVISOR = "src/constructicon/substrate/executors/_supervisor.py"
BRIDGE = "src/constructicon/substrate/executors/_egress_bridge.py"
LAUNCHER = "src/constructicon/substrate/executors/linux.py"
WORKFLOW = ".github/workflows/m8-containment.yml"
LAUNCH_BLOBS = (SCRIPT, LAUNCH_PROFILE, SUPERVISOR, BRIDGE, LAUNCHER, WORKFLOW)
# Values with one reviewed home are read from its blob at the commit, never
# mirrored here; each pattern must match exactly once.
DERIVED: dict[str, tuple[str, bytes]] = {
    "bwrap_sha256": (LAUNCHER, rb'^BWRAP_SHA256 = "([0-9a-f]{64})"$'),
    "supervisor_path": (SUPERVISOR, rb'^NAMESPACE_SCRIPT = "(/usr/libexec/[a-z0-9.-]+)"$'),
    "bridge_path": (BRIDGE, rb'^BRIDGE_SCRIPT = "(/usr/libexec/[a-z0-9.-]+)"$'),
    "codex_sha256": (
        WORKFLOW, rb"printf '%s  %s\\n' ([0-9a-f]{64}) \"\$RUNNER_TEMP/codex\.tar\.gz\"",
    ),
    "catalog_sha256": (
        WORKFLOW, rb"printf '%s  %s\\n' ([0-9a-f]{64}) \"\$RUNNER_TEMP/codex-models\.json\"",
    ),
}  # fmt: skip
SERVICE = "m8-service"
CP = "usr/bin/cp"
# Every tool root runs in the launch runbook's R13, by these absolute paths.
LAUNCH_ROOT_TOOLS = (INSTALL, CAT, CP, PARSER)
# The loader resolves the closure's dependencies itself (``--list``, what ldd
# drives); it and the cache that decides resolution are custody-checked.
LOADER = "lib64/ld-linux-x86-64.so.2"
LOADER_CACHE = "etc/ld.so.cache"
ABI = "etc/apparmor.d/abi/4.0"
DPKG = "var/lib/dpkg"
PYTHON = "usr/bin/python3.12"
GIT_BINARY = "usr/bin/git"
LIBRARY = "usr/lib/python3.12"
IGNORED = frozenset({"__pycache__", "test", "tests", "ensurepip", "idlelib"})
RUNTIME_DIRECTORIES = ("proc", "dev", "tmp", "workspace")
"""No store mount point: the N4 layout binds the credential file into the
zone's own tmpfs home by descriptor (M8-N4-state-review.md, section 1)."""
EGRESS_LEAF = "vendor-egress.sock"
# Inside the operator's workspace: the pinned vendor inputs, and the staged set.
TARBALL = "codex.tar.gz"
CATALOG = "codex-models.json"
STAGED = ("codex-models.json", "constructicon-m8-launch", "native-codex", "runtime", "runtime.json")
ALIASES = (("/usr/lib64/", "/lib64/"), ("/usr/lib/", "/lib/"), ("/usr/sbin/", "/sbin/"),
           ("/usr/bin/", "/bin/"))  # fmt: skip
TREE_SUMMARY = 32
UNATTRIBUTED_LIMIT = 64
# The controller environment (owner decision 2): C's package and its runtime
# closure from C's uv.lock, unpacked flat; the service user's one sys.path entry.
CONTROLLER = "opt/constructicon-m8-controller"
LOCK = "uv.lock"
PACKAGE = "constructicon"
PACKAGE_SOURCE = "src/constructicon"
CONTROLLER_BLOBS = (SCRIPT, LOCK)
WHEELS = "wheels"
CONTROLLER_STAGED = "controller"
PYTHON_VERSION = (3, 12)
WHEEL_MEMBERS = 4096
WHEEL_NAME_BYTES = 255
WHEEL_BYTES = 64 << 20
LEGACY_MANYLINUX = {"manylinux1": 5, "manylinux2010": 12, "manylinux2014": 17}
# Every module the proofs import; N4 adds its lane module in the change that lands it.
PROOF_MODULES = (
    "constructicon.api",
    "constructicon.substrate.executors.linux",
    "constructicon.substrate.executors.codex",
    "pydantic_core._pydantic_core",
)
VERDICTS = {
    "judge": "ready", "verify": "installed", "stage-launch": "staged",
    "judge-launch": "ready", "verify-launch": "installed", "controller-wheels": "listed",
    "stage-controller": "staged", "judge-controller": "ready", "verify-controller": "installed",
}  # fmt: skip
# (name, kind, final mode, source); ``.`` is the tree's own root. A file's
# source is ("host", real path), ("bytes", data) or ("tar", member name); a
# link's is its target.
Entry = tuple[str, str, int, object]
Inventory = list[tuple[str, int, str]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        env=ENVIRONMENT,
    )


def git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    # A replacement ref could otherwise substitute another object for the one
    # the commit names.
    return run([GIT, "--no-replace-objects", f"--git-dir={repository}", *arguments])


def prove(
    commit: str, repository: Path, record: dict, paths: tuple[str, ...] = (SCRIPT, PROBE, PROFILE)
) -> dict[str, bytes]:
    """Stock git proves the commit is on main; returns its raw blobs, never a checkout."""

    require(
        re.fullmatch("[0-9a-f]{40}", commit) is not None,
        "commit must be exactly 40 lowercase hex digits",
    )
    main = git(repository, "rev-parse", "--verify", "refs/heads/main^{commit}")
    require(main.returncode == 0, "the source repository has no fetched main")
    record["main"] = main.stdout.decode().strip()
    # Ancestry alone is too weak: a merge commit makes a PR branch's unreviewed
    # intermediate commits ancestors of main. Membership of main's first-parent
    # line proves ancestry and excludes them, and only commits appear on it.
    line = git(repository, "rev-list", "--first-parent", record["main"])
    record["first_parent"] = line.returncode == 0 and commit in line.stdout.decode().split()
    require(record["first_parent"], "commit is not on the first-parent line of the fetched main")
    blobs: dict[str, bytes] = {}
    record["blobs"] = {}
    for path in paths:
        listing = git(repository, "ls-tree", "-z", "--full-tree", commit, "--", path)
        entry = re.fullmatch(rb"(\d{6}) \w+ ([0-9a-f]{40})\t([^\x00]*)\x00", listing.stdout)
        require(
            listing.returncode == 0
            and entry is not None
            and entry[3] == path.encode()
            and entry[1] == b"100644",
            f"{path} is not one regular non-executable blob at commit",
        )
        oid = entry[2].decode()
        # Raw blob bytes: git archive or a working tree may convert line endings.
        blob = git(repository, "cat-file", "blob", oid)
        require(blob.returncode == 0, f"{path} blob is unreadable")
        blobs[path] = blob.stdout
        record["blobs"][path] = {"oid": oid, "sha256": sha256(blob.stdout)}
    # Catches accidental drift (a stale or line-ending-converted copy); R3's
    # stock-git extraction, not this check, excludes a deliberately edited one.
    require(
        blobs[SCRIPT] == Path(__file__).read_bytes(),
        "the running script is not the script at commit",
    )
    record["script_matches_commit"] = True
    return blobs


def require_unprivileged() -> None:
    # Root executes no repository code; root's part is the runbook's stock tools.
    require(os.geteuid() != 0, "this script never runs as root")


def require_ancestors(path: Path, owners: tuple[int, ...], who: str) -> None:
    """Only ``owners`` can create, rename or re-permission anything along the path."""

    for parent in path.parents:
        info = os.lstat(parent)
        require(
            stat.S_ISDIR(info.st_mode) and info.st_uid in owners and not info.st_mode & 0o022,
            f"{parent} must be a real directory owned by {who} that group and others cannot write",
        )
        if parent == ROOT:
            break


def require_root_alone(path: Path) -> None:
    """Only root can replace or rewrite this file, or anything along its path."""

    info = os.lstat(path)
    require(
        stat.S_ISREG(info.st_mode) and info.st_uid == ROOT_UID and not info.st_mode & 0o022,
        f"{path} must be a regular file owned by root that group and others cannot write",
    )
    require_ancestors(path, (ROOT_UID,), "root")


def require_custody(workspace: Path) -> None:
    """Nobody but this account and root can change the workspace between two steps."""

    require(
        workspace.is_absolute() and ".." not in workspace.parts,
        f"{workspace} must be an absolute path",
    )
    owner = os.geteuid()
    info = os.lstat(workspace)
    require(
        stat.S_ISDIR(info.st_mode) and info.st_uid == owner and not info.st_mode & 0o077,
        f"{workspace} must be a private directory owned by this account",
    )
    repository = workspace / REPOSITORY
    require(stat.S_ISDIR(os.lstat(repository).st_mode), f"{repository} must be a real directory")
    require_ancestors(workspace, (ROOT_UID, owner), "root or this account")


def read_regular(path: Path) -> bytes:
    # O_NONBLOCK: a FIFO in place of the file must refuse, not block the open.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), f"{path} is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def absent(path: Path) -> bool:
    """Only ENOENT is absence; a lookup that fails otherwise proves nothing."""

    try:
        os.lstat(path)
    except FileNotFoundError:
        return True
    return False


def loaded_profiles(listing: str) -> list[str]:
    """The kernel's list as root's ``cat`` piped it; empty or malformed input proves nothing."""

    lines = listing.splitlines()
    require(
        bool(lines) and all(re.fullmatch(r"\S.* \([a-z]+\)", line) for line in lines),
        "the loaded-profile list is empty or not in the kernel's format",
    )
    return [line for line in lines if line.startswith("constructicon-m8-")][:16]


def loaded_among(listing: str, names: tuple[str, ...]) -> list[str]:
    """Which of ``names`` the list shows loaded, in any mode."""

    return [line for line in loaded_profiles(listing) if line.rsplit(" (", 1)[0] in names]


def judge(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
    """Every precondition of root's stock-tool sequence, before its first write."""

    require_unprivileged()
    require_custody(workspace)
    blobs = prove(commit, workspace / REPOSITORY, record)
    staging = workspace / STAGING
    require(stat.S_ISDIR(os.lstat(staging).st_mode), f"{staging} must be a real directory")
    for destination, (source, _) in FILES.items():
        if source is not None:
            name = PurePosixPath(destination).name
            require(
                read_regular(staging / name) == blobs[source],
                f"the staged {name} is not the blob at commit",
            )
    # Root's install reopens bubblewrap by path, and root runs each tool by
    # path; neither may be replaceable by another account after this check.
    for path in (BWRAP_SOURCE, *ROOT_TOOLS):
        require_root_alone(root / path)
    bwrap = read_regular(root / BWRAP_SOURCE)
    require(sha256(bwrap) == BWRAP_SHA256, "host bubblewrap is not the pinned build")
    for destination in (DIRECTORY, *FILES):
        require(
            absent(root / destination),
            f"/{destination} already exists; installation is fresh-only",
        )
    # With every ancestor root's alone, no other account can put anything at a
    # destination before root's install reaches it.
    for destination in (DIRECTORY, PROFILE_DESTINATION):
        require_ancestors(root / destination, (ROOT_UID,), "root")
    # Only its own two: the launch set's profiles may be loaded beside them.
    require(not loaded_among(listing, PROFILE_NAMES), "a qualification profile is already loaded")
    record["ready"] = True


def observe(root: Path, listing: str) -> dict[str, object]:
    """Fresh state of every destination, never remembered from an earlier step."""

    observed: dict[str, object] = {}
    for destination in (DIRECTORY, *FILES):
        path = root / destination
        try:
            info = os.lstat(path)
            entry: dict[str, object] = {"uid": info.st_uid, "mode": oct(stat.S_IMODE(info.st_mode))}
            if stat.S_ISDIR(info.st_mode):
                entry["state"] = "directory"
                entry["entries"] = sorted(os.listdir(path))[:16]
            elif stat.S_ISREG(info.st_mode):
                entry["state"] = "file"
                entry["sha256"] = sha256(read_regular(path))
            else:
                entry["state"] = "symlink" if stat.S_ISLNK(info.st_mode) else "other"
        except FileNotFoundError:
            entry = {"state": "absent"}
        except (OSError, ValueError) as exc:
            entry = {"state": f"unobservable: {type(exc).__name__}"}
        observed["/" + destination] = entry
    try:
        observed["loaded_profiles"] = loaded_profiles(listing)
    except ValueError as exc:
        observed["loaded_profiles"] = f"unobservable: {type(exc).__name__}"
    return observed


def expected(blobs: dict[str, bytes]) -> dict[str, tuple[str, int, object]]:
    names = sorted(
        PurePosixPath(destination).name
        for destination in FILES
        if PurePosixPath(destination).parent == PurePosixPath(DIRECTORY)
    )
    table: dict[str, tuple[str, int, object]] = {DIRECTORY: ("directory", DIRECTORY_MODE, names)}
    for destination, (source, mode) in FILES.items():
        digest = BWRAP_SHA256 if source is None else sha256(blobs[source])
        table[destination] = ("file", mode, digest)
    return table


def assess(observed: dict, table: dict[str, tuple[str, int, object]]) -> None:
    checked = 0
    for destination, (kind, mode, content) in table.items():
        entry = observed["/" + destination]
        require(entry.get("state") == kind, f"/{destination} is not a {kind}")
        require(entry.get("uid") == ROOT_UID, f"/{destination} is not root-owned")
        require(entry.get("mode") == oct(mode), f"/{destination} mode is not {oct(mode)}")
        found = entry.get("sha256" if kind == "file" else "entries")
        require(found == content, f"/{destination} is not the reviewed content")
        checked += 1
    require(checked == 4, "the fixed inventory of four entries was not completely verified")
    profiles = observed["loaded_profiles"]
    require(
        isinstance(profiles, list)
        and all(f"{name} (enforce)" in profiles for name in PROFILE_NAMES),
        "both reviewed profiles must be loaded in enforce mode",
    )


def verify(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
    """Recomputes the installation from the blobs at the commit; staging is never read."""

    require_unprivileged()
    require_custody(workspace)
    blobs = prove(commit, workspace / REPOSITORY, record)
    record["observed"] = observe(root, listing)
    assess(record["observed"], expected(blobs))
    for destination in FILES:
        require_ancestors(root / destination, (ROOT_UID,), "root")
    record["installed"] = True


# --- the launch set ---------------------------------------------------------


def derive(blobs: dict[str, bytes], record: dict) -> dict[str, str]:
    """Each value from its one reviewed home at the commit; zero or two matches refuse."""

    values: dict[str, str] = {}
    for key, (path, pattern) in DERIVED.items():
        found = re.findall(pattern, blobs[path], re.MULTILINE)
        require(len(found) == 1, f"{path} does not name exactly one {key}")
        values[key] = found[0].decode()
    record["derived"] = dict(values)
    return values


def lookup_service() -> tuple[int, int, str, list[str]]:
    """Platform primitive: the service account's uid, gid, group name and other groups."""

    import grp
    import pwd

    try:
        entry = pwd.getpwnam(SERVICE)
        group = grp.getgrgid(entry.pw_gid).gr_name
    except KeyError as exc:
        raise ValueError(f"the {SERVICE} account or its group is missing") from exc
    others = [g.gr_name for g in grp.getgrall() if SERVICE in g.gr_mem]
    return entry.pw_uid, entry.pw_gid, group, others


def service_account(record: dict) -> int:
    """The unprivileged service account, in its own group only; returns its gid."""

    uid, gid, group, others = lookup_service()
    record["service"] = {"uid": uid, "gid": gid, "group": group, "other_groups": others[:16]}
    require(
        uid != 0 and gid != 0 and group == SERVICE and not others,
        f"{SERVICE} must be unprivileged, in its own group and no other",
    )
    return gid


def hash_regular(path: Path, algorithm: str = "sha256") -> str:
    """Streams one regular file through the same no-follow open as ``read_regular``."""

    with open_regular(path) as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


@contextmanager
def open_regular(path: Path) -> Iterator[IO[bytes]]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), f"{path} is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            yield stream
    finally:
        os.close(descriptor)


def resolve(loader: Path, binary: Path) -> list[str]:
    """The loader's own trace of one binary's dependencies, as absolute host paths."""

    traced = run([str(loader), "--list", str(binary)])
    output = traced.stdout.decode("utf-8", errors="strict")
    require(
        traced.returncode == 0 and "not found" not in output,
        f"{binary} has unresolved dependencies",
    )
    return re.findall(r"(?:=>\s+)?(/[\w./+-]+)", output)


def real_source(root: Path, path: Path) -> Path:
    real = Path(os.path.realpath(path))
    require(real == root or real.is_relative_to(root), f"{path} resolves outside the host root")
    return real


def runtime_plan(
    root: Path, supervisor: bytes, bridge: bytes, supervisor_path: str, bridge_path: str,
) -> list[Entry]:  # fmt: skip
    """The immutable runtime closure; CI's builder takes its entries from here too.

    Python and Git, the ``/usr/lib/python3.12`` tree without IGNORED names, the
    loader-resolved closure of both binaries and of every ``*.so`` under the
    UNFILTERED tree (as CI always enumerated it), the fixed supervisor, bridge,
    directories and egress leaf, and the ``python3`` link. Files keep their
    first source, are ``0555`` if the source is executable and ``0444``
    otherwise; directories are ``0555``. The vendor is bound, not baked: N4's
    launcher binds the launch root's ``native-codex`` and catalog read-only
    into the zone, so no vendor file belongs here (M8-N4-host-runtime.md,
    owner decision 4).
    """

    entries: dict[str, Entry] = {".": (".", "directory", 0o555, None)}

    def directories(name: str) -> None:
        parts = PurePosixPath(name).parts
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            entries.setdefault(parent, (parent, "directory", 0o555, None))

    def host_file(name: str, source: Path) -> None:
        require(
            re.fullmatch(r"[\w.+-]+(/[\w.+-]+)*", name) is not None
            and ".." not in PurePosixPath(name).parts,
            f"{name} is not a plain relative runtime path",
        )
        if name in entries:
            return
        real = real_source(root, source)
        info = os.stat(real)
        require(stat.S_ISREG(info.st_mode), f"{source} is not a regular file")
        directories(name)
        entries[name] = (name, "file", 0o555 if info.st_mode & 0o111 else 0o444, ("host", real))

    def tree(source: Path, name: str) -> None:
        directories(name)
        entries.setdefault(name, (name, "directory", 0o555, None))
        for child in sorted(os.scandir(source), key=lambda item: item.name):
            if child.name in IGNORED:
                continue
            if child.is_dir():  # follows a link, as copytree without symlinks does
                tree(Path(child.path), f"{name}/{child.name}")
            else:
                host_file(f"{name}/{child.name}", Path(child.path))

    library = root / LIBRARY
    host_file(PYTHON, root / PYTHON)
    host_file(GIT_BINARY, root / GIT_BINARY)
    tree(library, LIBRARY)
    # By its canonical path, as ldd runs it: the trace names the loader by the
    # path it was started as. Only root can change the links along that path;
    # the judge proves the real file root's alone.
    for binary in (root / PYTHON, root / GIT_BINARY, *sorted(library.rglob("*.so"))):
        for value in resolve(root / LOADER, binary):
            host_file(value.lstrip("/"), root / value.lstrip("/"))
    for path, data in ((supervisor_path, supervisor), (bridge_path, bridge)):
        name = path.removeprefix("/")
        require(name not in entries, f"{name} would replace a runtime file")
        directories(name)
        entries[name] = (name, "file", 0o444, ("bytes", data))
    for name in RUNTIME_DIRECTORIES:
        entries[name] = (name, "directory", 0o555, None)
    entries[EGRESS_LEAF] = (EGRESS_LEAF, "file", 0o444, ("bytes", b""))
    entries["usr/bin/python3"] = ("usr/bin/python3", "link", 0o777, "python3.12")
    return sorted(entries.values(), key=lambda entry: PurePosixPath(entry[0]).parts)


def vendor_plan(archive: tarfile.TarFile) -> tuple[list[Entry], dict[str, str]]:
    """The pinned package as CI extracts it: only directories and regular files.

    Group and other write are cleared as CI's ``chmod -R go-w`` clears them; a
    special bit, a link, a device, an unsafe or a duplicate name refuses.
    Entries keep the archive's order, so extraction reads it forwards.
    """

    entries: dict[str, Entry] = {".": (".", "directory", 0o755, None)}
    digests: dict[str, str] = {}
    for member in archive:
        name = member.name
        require(
            re.fullmatch(r"[\w.+-]+(/[\w.+-]+)*", name) is not None
            and ".." not in PurePosixPath(name).parts,
            f"archive member {name!r} is not a plain relative path",
        )
        require(member.isdir() or member.isreg(), f"archive member {name} is not a file or directory")
        require(not member.mode & 0o7000, f"archive member {name} carries a special mode bit")
        require(name not in entries, f"archive member {name} is duplicated")
        parts = PurePosixPath(name).parts
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            entries.setdefault(parent, (parent, "directory", 0o755, None))
        mode = member.mode & 0o755
        if member.isdir():
            entries[name] = (name, "directory", mode, None)
            continue
        stream = archive.extractfile(member)
        require(stream is not None, f"archive member {name} is unreadable")
        assert stream is not None
        digests[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        entries[name] = (name, "file", mode, ("tar", name))
    return list(entries.values()), digests


@contextmanager
def open_vendor(path: Path, pinned: str) -> Iterator[tarfile.TarFile]:
    """One open of the pinned archive: hashed, then parsed from the same descriptor."""

    with open_regular(path) as stream:
        require(
            hashlib.file_digest(stream, "sha256").hexdigest() == pinned,
            f"{path.name} is not the pinned package",
        )
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:gz") as archive:
            yield archive


def expected_inventory(
    entries: list[Entry], digests: Callable[[Entry], str],
) -> Inventory:  # fmt: skip
    """The inventory ``runtime_inventory`` would record for the materialized plan."""

    inventory: Inventory = []
    for entry in sorted(entries, key=lambda item: PurePosixPath(item[0]).parts):
        name, kind, mode, source = entry
        if kind == "directory":
            content = "directory"
        elif kind == "link":
            content = f"link:{source}"
        else:
            content = "sha256:" + digests(entry)
        inventory.append((name, mode, content))
    return inventory


def identity_digest(domain: str, schema_version: int, payload: object) -> str:
    """Constructicon's identity law (core/identity.py), in the stdlib; a test holds them equal."""

    body = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    material = "\0".join(("constructicon", domain, str(schema_version), body))
    return "sha256:" + sha256(material.encode("utf-8"))


def runtime_json(inventory: Inventory, bwrap: str, policy: str, abi: str) -> bytes:
    """``runtime.json`` with CI's keys and bytes (build_m8_runtime.py)."""

    return (json.dumps({
        "runtime_digest": identity_digest("linux-runtime-root", 1, inventory),
        "entries": inventory,
        "bubblewrap_sha256": bwrap,
        "apparmor_policy_sha256": policy,
        "apparmor_abi_sha256": abi,
    }, sort_keys=True) + "\n").encode()  # fmt: skip


def tree_inventory(top: Path) -> list[tuple[str, int, str, int]]:
    """``runtime_inventory`` (linux.py) in the stdlib, with each entry's owner."""

    require(stat.S_ISDIR(os.lstat(top).st_mode), f"{top} is not a real directory")
    entries = []
    for path in [top, *sorted(top.rglob("*"))]:
        info = os.lstat(path)
        name = path.relative_to(top).as_posix()
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            require(
                (path.parent / target).resolve().is_relative_to(top.resolve()),
                f"{name} links outside its tree",
            )
            content = "link:" + target
        elif stat.S_ISDIR(info.st_mode):
            content = "directory"
        elif stat.S_ISREG(info.st_mode):
            content = "sha256:" + hash_regular(path)
        else:
            raise ValueError(f"{name} is not a file, directory or link")
        entries.append((name, stat.S_IMODE(info.st_mode), content, info.st_uid))
    return entries


def compare(
    observed: list[tuple[str, int, str, int]], expected: Inventory, owner: int
) -> list[dict[str, object]]:
    """Every entry that differs in name, mode, content or owner; the one ownership check."""

    seen = {name: (mode, content, uid) for name, mode, content, uid in observed}
    wanted = {name: (mode, content) for name, mode, content in expected}
    differences: list[dict[str, object]] = []
    for name in sorted(set(seen) | set(wanted)):
        found, reviewed = seen.get(name), wanted.get(name)
        if found is None or reviewed is None or found[:2] != reviewed or found[2] != owner:
            differences.append({
                "path": name,
                "expected": None if reviewed is None else [*reviewed, owner],
                "observed": None if found is None else list(found),
            })  # fmt: skip
    return differences


def attribution(root: Path, sources: list[Path], read: Callable[[Path], bytes]) -> dict:
    """Which installed package owns each host source, and whether dpkg's digest matches.

    Evidence, not the trust anchor (custody is). A mismatch refuses; a file no
    package claims is listed as unattributed. ``/usr``-merge spellings match
    both ways. Diversions are not read.
    """

    wanted: dict[str, str] = {}
    for real in sources:
        host = "/" + real.relative_to(root).as_posix()
        wanted[host] = host
        for merged, legacy in ALIASES:
            for old, new in ((merged, legacy), (legacy, merged)):
                if host.startswith(old):
                    wanted[new + host.removeprefix(old)] = host
    database = root / DPKG
    versions: dict[str, str] = {}
    conffiles: dict[str, tuple[str, str]] = {}
    for stanza in read(database / "status").decode("utf-8", errors="replace").split("\n\n"):
        fields = dict(re.findall(r"^([A-Za-z-]+): ?(.*)$", stanza, re.MULTILINE))
        if "Package" not in fields or not fields.get("Status", "").endswith(" installed"):
            continue
        key = fields["Package"]
        versions[key] = versions[key + ":" + fields.get("Architecture", "")] = fields.get(
            "Version", ""
        )
        for path, digest in re.findall(r"^ (/\S+) ([0-9a-f]{32})", stanza, re.MULTILINE):
            conffiles[path] = (key, digest)
    owners: dict[str, str] = {}
    info = database / "info"
    for listing in sorted(os.listdir(info)):
        if listing.endswith(".list"):
            for line in read(info / listing).decode("utf-8", errors="replace").splitlines():
                if line in wanted:
                    owners.setdefault(wanted[line], listing.removesuffix(".list"))
    sums: dict[str, dict[str, str]] = {}
    packages: dict[str, str] = {}
    unattributed: list[str] = []
    for host in sorted(set(wanted.values())):
        data = read(root / host.lstrip("/"))
        actual = hashlib.md5(data, usedforsecurity=False).hexdigest()
        if host in conffiles:
            package, digest = conffiles[host]
            candidates = {digest}
        elif host in owners:
            package = owners[host]
            if package not in sums:
                sums[package] = {}
                table = info / f"{package}.md5sums"
                if os.path.lexists(table):
                    for line in read(table).decode("utf-8", errors="replace").splitlines():
                        digest, _, path = line.partition("  ")
                        sums[package]["/" + path] = digest
            candidates = {sums[package][s] for s, h in wanted.items() if h == host and s in sums[package]}
        else:
            unattributed.append(host)
            continue
        packages[package] = versions.get(package, "unknown")
        require(not candidates or actual in candidates, f"{host} differs from {package}'s dpkg digest")
    return {
        "packages": dict(sorted(packages.items())),
        "unattributed": unattributed[:UNATTRIBUTED_LIMIT],
        "unattributed_count": len(unattributed),
    }


def launch_expectation(
    root: Path, workspace: Path, blobs: dict[str, bytes], values: dict[str, str], record: dict,
    archive: tarfile.TarFile,
) -> dict:  # fmt: skip
    """Everything the launch set must be, recomputed from the commit, the pins and the host."""

    loader = real_source(root, root / LOADER)
    for path in (loader, root / LOADER_CACHE, root / ABI):
        require_root_alone(path)
    plan = runtime_plan(
        root, blobs[SUPERVISOR], blobs[BRIDGE], values["supervisor_path"], values["bridge_path"]
    )
    sources = sorted({entry[3][1] for entry in plan if entry[1] == "file" and entry[3][0] == "host"})  # type: ignore[index]
    # Custody is the anchor: only root can have changed what the closure copies.
    for source in sources:
        require_root_alone(source)

    def custodial(path: Path) -> bytes:
        # dpkg's database is read under custody; the sources' was proven above,
        # once, so that check alone decides it.
        if path.is_relative_to(root / DPKG):
            require_root_alone(path)
        return read_regular(path)

    record.update(attribution(root, sources, custodial))

    def digest(entry: Entry) -> str:
        kind, value = entry[3]  # type: ignore[misc]
        return hash_regular(value) if kind == "host" else sha256(value)

    runtime = expected_inventory(plan, digest)
    vendor, digests = vendor_plan(archive)
    catalog = read_regular(workspace / CATALOG)
    require(sha256(catalog) == values["catalog_sha256"], f"{CATALOG} is not the pinned catalog")
    document = runtime_json(
        runtime, values["bwrap_sha256"], sha256(blobs[LAUNCH_PROFILE]), hash_regular(root / ABI)
    )
    record["runtime_digest"] = identity_digest("linux-runtime-root", 1, runtime)
    record["runtime_entries"] = len(runtime)
    return {
        "plan": plan,
        "runtime": runtime,
        "vendor_plan": vendor,
        "vendor": expected_inventory(vendor, lambda entry: digests[entry[0]]),
        "runtime.json": document,
        "catalog": catalog,
    }


def materialize(
    entries: list[Entry], destination: Path, content: Callable[[object], IO[bytes]]
) -> None:
    """The script's only writer: a fresh tree, exclusively created, never followed.

    Directories are created owner-only and receive their final mode after their
    contents; files are written through ``O_CREAT|O_EXCL|O_NOFOLLOW``.
    """

    finals: list[tuple[Path, int]] = []
    for name, kind, mode, source in entries:
        path = PurePosixPath(name)
        require(
            name == "." or (not path.is_absolute() and "." not in path.parts
                            and ".." not in path.parts),
            f"{name} is not a plain relative path",
        )  # fmt: skip
        target = destination if name == "." else destination / name
        if kind == "directory":
            os.mkdir(target, 0o700)
            finals.append((target, mode))
        elif kind == "link":
            os.symlink(str(source), target)
        else:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptor = os.open(target, flags, 0o600)
            try:
                with content(source) as stream:
                    while chunk := stream.read(1 << 20):
                        view = memoryview(chunk)
                        while view:
                            view = view[os.write(descriptor, view) :]
                os.fchmod(descriptor, mode)
            finally:
                os.close(descriptor)
    for target, mode in reversed(finals):
        os.chmod(target, mode)


def contents(archive: tarfile.TarFile | None = None) -> Callable[[object], IO[bytes]]:
    """Opens each planned source: a host file (no-follow), bytes, or an archive member."""

    def opened(source: object) -> IO[bytes]:
        kind, value = source  # type: ignore[misc]
        if kind == "host":
            return open_regular(value)  # type: ignore[return-value]
        if kind == "bytes":
            return io.BytesIO(value)
        assert archive is not None
        member = archive.extractfile(value)
        require(member is not None, f"archive member {value} is unreadable")
        return member  # type: ignore[return-value]

    return opened


def launch_inputs(commit: str, workspace: Path, record: dict) -> tuple[dict, dict]:
    require_unprivileged()
    require_custody(workspace)
    blobs = prove(commit, workspace / REPOSITORY, record, LAUNCH_BLOBS)
    return blobs, derive(blobs, record)


def stage_launch(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
    """Writes the launch set into a fresh ``staging``; the judge proves it afterwards."""

    blobs, values = launch_inputs(commit, workspace, record)
    service_account(record)
    with open_vendor(workspace / TARBALL, values["codex_sha256"]) as archive:
        expected = launch_expectation(root, workspace, blobs, values, record, archive)

        def under(prefix: str, entries: list[Entry]) -> list[Entry]:
            return [
                (prefix if name == "." else f"{prefix}/{name}", kind, mode, source)
                for name, kind, mode, source in entries
            ]

        plan: list[Entry] = [
            (".", "directory", 0o700, None),
            ("constructicon-m8-launch", "file", 0o444, ("bytes", blobs[LAUNCH_PROFILE])),
            ("runtime.json", "file", 0o444, ("bytes", expected["runtime.json"])),
            ("codex-models.json", "file", 0o444, ("bytes", expected["catalog"])),
            *under("runtime", expected["plan"]),
            *under("native-codex", expected["vendor_plan"]),
        ]
        materialize(plan, workspace / STAGING, contents(archive))
    record["staged"] = True


def judge_launch(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
    """Every precondition of root's R13 sequence, before its first write."""

    blobs, values = launch_inputs(commit, workspace, record)
    service_account(record)
    with open_vendor(workspace / TARBALL, values["codex_sha256"]) as archive:
        expected = launch_expectation(root, workspace, blobs, values, record, archive)
    staging = workspace / STAGING
    require(stat.S_ISDIR(os.lstat(staging).st_mode), f"{staging} must be a real directory")
    require(sorted(os.listdir(staging)) == list(STAGED), "staging must hold exactly the staged set")
    for name, data in (
        ("constructicon-m8-launch", blobs[LAUNCH_PROFILE]),
        ("runtime.json", expected["runtime.json"]),
        ("codex-models.json", expected["catalog"]),
    ):
        require(read_regular(staging / name) == data, f"the staged {name} is not the reviewed file")
    for tree, reviewed in (("runtime", expected["runtime"]), ("native-codex", expected["vendor"])):
        differences = compare(tree_inventory(staging / tree), reviewed, os.geteuid())
        record[f"staged_{tree}_differences"] = differences[:TREE_SUMMARY]
        require(not differences, f"the staged {tree} is not the reviewed plan")
    # Root's install reopens bubblewrap by path, and root runs each tool by path.
    for path in (BWRAP_SOURCE, *LAUNCH_ROOT_TOOLS):
        require_root_alone(root / path)
    bwrap = read_regular(root / BWRAP_SOURCE)
    require(sha256(bwrap) == values["bwrap_sha256"], "host bubblewrap is not the pinned build")
    for destination in (LAUNCH, LAUNCH_PROFILE_DESTINATION):
        require(absent(root / destination), f"/{destination} already exists; installation is fresh-only")
    for destination in (LAUNCH, LAUNCH_PROFILE_DESTINATION):
        require_ancestors(root / destination, (ROOT_UID,), "root")
    require(not loaded_among(listing, LAUNCH_PROFILE_NAMES), "a launch profile is already loaded")
    record["ready"] = True


def observe_launch(root: Path, listing: str, expected: dict | None = None) -> dict[str, object]:
    """Fresh state of every launch destination; trees are summarized, never dumped."""

    trees = {} if expected is None else {
        LAUNCH + "/runtime": expected["runtime"], LAUNCH + "/native-codex": expected["vendor"],
    }  # fmt: skip
    observed: dict[str, object] = {}
    destinations = (LAUNCH, *(f"{LAUNCH}/{name}" for name in LAUNCH_ENTRIES),
                    LAUNCH_PROFILE_DESTINATION)  # fmt: skip
    for destination in destinations:
        path = root / destination
        try:
            info = os.lstat(path)
            entry: dict[str, object] = {
                "uid": info.st_uid, "gid": info.st_gid, "mode": oct(stat.S_IMODE(info.st_mode)),
            }  # fmt: skip
            if stat.S_ISDIR(info.st_mode) and destination in trees:
                differences = compare(tree_inventory(path), trees[destination], ROOT_UID)
                entry["state"] = "tree"
                entry["different"] = len(differences)
                entry["differences"] = differences[:TREE_SUMMARY]
            elif stat.S_ISDIR(info.st_mode):
                entry["state"] = "directory"
                listed = sorted(os.listdir(path))
                entry["entries"] = listed[:16]
                entry["count"] = len(listed)
            elif stat.S_ISREG(info.st_mode):
                entry["state"] = "file"
                entry["sha256"] = hash_regular(path)
            else:
                entry["state"] = "symlink" if stat.S_ISLNK(info.st_mode) else "other"
        except FileNotFoundError:
            entry = {"state": "absent"}
        except (OSError, ValueError) as exc:
            entry = {"state": f"unobservable: {type(exc).__name__}"}
        observed["/" + destination] = entry
    try:
        observed["loaded_profiles"] = loaded_profiles(listing)
    except ValueError as exc:
        observed["loaded_profiles"] = f"unobservable: {type(exc).__name__}"
    return observed


def launch_table(
    expected: dict, blobs: dict[str, bytes], values: dict[str, str], gid: int
) -> dict[str, tuple[str, int, object]]:
    """Destination -> (kind, mode, content): the reviewed installation."""

    return {
        LAUNCH: ("directory", LAUNCH_MODE, sorted(LAUNCH_ENTRIES)),
        LAUNCH + "/bwrap": ("file", 0o555, values["bwrap_sha256"]),
        LAUNCH_PROFILE_DESTINATION: ("file", 0o444, sha256(blobs[LAUNCH_PROFILE])),
        LAUNCH + "/runtime": ("tree", 0, None),
        LAUNCH + "/runtime.json": ("file", 0o444, sha256(expected["runtime.json"])),
        LAUNCH + "/native-codex": ("tree", 0, None),
        LAUNCH + "/codex-models.json": ("file", 0o444, values["catalog_sha256"]),
        LAUNCH + "/operator-stores": ("store", STORE_MODE, gid),
    }


def assess_launch(observed: dict, table: dict[str, tuple[str, int, object]]) -> None:
    for destination, (kind, mode, content) in table.items():
        entry = observed["/" + destination]
        if kind == "tree":
            # Each entry's name, mode, content and owner were compared by ``compare``.
            require(
                entry.get("state") == "tree" and entry.get("different") == 0,
                f"/{destination} is not the reviewed tree",
            )
            continue
        state = "file" if kind == "file" else "directory"
        require(entry.get("state") == state, f"/{destination} is not a {state}")
        require(entry.get("uid") == ROOT_UID, f"/{destination} is not root-owned")
        require(entry.get("mode") == oct(mode), f"/{destination} mode is not {oct(mode)}")
        if kind == "store":
            require(entry.get("gid") == content, f"/{destination} is not the {SERVICE} group's")
        else:
            found = entry.get("sha256" if kind == "file" else "entries")
            require(found == content, f"/{destination} is not the reviewed content")
    profiles = observed["loaded_profiles"]
    require(
        isinstance(profiles, list)
        and all(f"{name} (enforce)" in profiles for name in LAUNCH_PROFILE_NAMES),
        "both launch profiles must be loaded in enforce mode",
    )


def verify_launch(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
    """Recomputes the launch set from the commit, its pins and the host; staging is never read."""

    blobs, values = launch_inputs(commit, workspace, record)
    gid = service_account(record)
    with open_vendor(workspace / TARBALL, values["codex_sha256"]) as archive:
        expected = launch_expectation(root, workspace, blobs, values, record, archive)
    record["observed"] = observe_launch(root, listing, expected)
    assess_launch(record["observed"], launch_table(expected, blobs, values, gid))
    for destination in (LAUNCH, LAUNCH_PROFILE_DESTINATION):
        require_ancestors(root / destination, (ROOT_UID,), "root")
    record["installed"] = True


# --- the controller environment -------------------------------------------


def controller_command(path: str = "/" + CONTROLLER) -> tuple[str, ...]:
    """How the service user runs a module from the tree: its one ``sys.path`` entry.

    ``-S`` also drops the distribution's ``dist-packages``; ``-B`` keeps the
    interpreter from writing into the read-only tree. The module name is
    popped, so the module sees ``argv`` as ``python -m`` would give it.
    """

    return (
        "/usr/bin/python3", "-I", "-S", "-B", "-c",
        f'import sys; sys.path.insert(0, "{path}"); import runpy; '
        'runpy.run_module(sys.argv.pop(1), run_name="__main__", alter_sys=True)',
    )  # fmt: skip


def controller_check(path: str = "/" + CONTROLLER) -> str:
    """The import check the service user runs (runbook R19) and CI runs on a copy.

    It imports the modules named as arguments and passes only if every loaded
    module's file lies in the tree or the interpreter's standard library.
    """

    return (
        "import importlib, json, sys, sysconfig; "
        f'sys.path.insert(0, "{path}"); '
        "[importlib.import_module(m) for m in sys.argv[1:]]; "
        f'roots = ("{path}/", sysconfig.get_paths()["stdlib"] + "/", '
        'sysconfig.get_paths()["platstdlib"] + "/"); '
        'files = sorted({f for f in (getattr(m, "__file__", None) '
        "for m in list(sys.modules.values())) if f}); "
        "outside = [f for f in files if not f.startswith(roots)]; "
        'print(json.dumps({"files": len(files), "outside": outside, "passed": not outside})); '
        "raise SystemExit(1 if outside else 0)"
    )


def controller_closure(lock: bytes) -> list[dict]:
    """The runtime closure of the editable package in the lock: dependencies only.

    No extra, no dev group. A qualified dependency (marker, version, source)
    or a name the lock lists twice refuses: no marker evaluator exists yet.
    """

    packages: dict[str, dict] = {}
    for package in tomllib.loads(lock.decode("utf-8")).get("package", []):
        require(package.get("name") not in packages, f"{package.get('name')} is locked twice")
        packages[package["name"]] = package
    root = packages.get(PACKAGE)
    require(
        root is not None and root.get("source") == {"editable": "."},
        f"the lock has no editable {PACKAGE}",
    )
    assert root is not None
    closure: dict[str, dict] = {}
    pending = [root]
    while pending:
        for dependency in pending.pop().get("dependencies", []):
            require(set(dependency) == {"name"}, f"{dependency} is a qualified dependency")
            name = dependency["name"]
            require(name in packages, f"{name} is not in the lock")
            if name not in closure:
                closure[name] = packages[name]
                pending.append(packages[name])
    return [closure[name] for name in sorted(closure)]


def platform_tags(glibc_minor: int) -> set[str]:
    tags = {f"manylinux_2_{minor}_x86_64" for minor in range(5, glibc_minor + 1)}
    tags |= {f"{name}_x86_64" for name, minor in LEGACY_MANYLINUX.items() if minor <= glibc_minor}
    return tags


def accepted_triples(glibc_minor: int) -> set[tuple[str, str, str]]:
    """An explicit subset of CPython 3.12's ``sys_tags()`` on x86_64 Linux."""

    triples: set[tuple[str, str, str]] = set()
    for platform in platform_tags(glibc_minor):
        triples.add(("cp312", "cp312", platform))
        triples |= {(f"cp3{minor}", "abi3", platform) for minor in range(2, 13)}
        triples |= {(python, "none", platform) for python in ("cp312", "py312", "py3")}
    triples |= {(python, "none", "any") for python in ("cp312", "py312", "py3")}
    return triples


def wheel_triples(filename: str) -> set[tuple[str, str, str]]:
    """PEP 427: the last three dash-separated fields, each a dotted tag set."""

    require(filename.endswith(".whl"), f"{filename} is not a wheel")
    fields = filename.removesuffix(".whl").split("-")
    require(len(fields) in (5, 6), f"{filename} is not a wheel name")
    pythons, abis, platforms = (field.split(".") for field in fields[-3:])
    return {(p, a, s) for p in pythons for a in abis for s in platforms}


def select_wheel(package: dict, glibc_minor: int) -> dict[str, str]:
    """Exactly one wheel whose expanded tags meet the accepted triples, or refuse."""

    accepted = accepted_triples(glibc_minor)
    found = []
    for wheel in package.get("wheels", []):
        filename = wheel["url"].rsplit("/", 1)[-1]
        if wheel_triples(filename) & accepted:
            found.append(wheel)
    name = package["name"]
    require(len(found) == 1, f"{name} has {len(found)} compatible wheels, not one")
    (wheel,) = found
    digest = wheel.get("hash", "")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None, f"{name} has no sha256")
    filename = wheel["url"].rsplit("/", 1)[-1]
    require(re.fullmatch(r"[\w.+-]+\.whl", filename) is not None, f"{filename} is not plain")
    return {"name": name, "file": filename, "url": wheel["url"], "sha256": digest[7:]}


def needs_zip64(info: zipfile.ZipInfo) -> bool:
    return max(info.file_size, info.compress_size, info.header_offset) >= 0xFFFFFFFF


def wheel_entries(archive: zipfile.ZipFile, wheel: str) -> tuple[list[Entry], dict[str, str]]:
    """One pinned wheel as ``pip --target`` lays it out; every refusal before any write.

    Only regular files and directories, plain unique names, no ``.data``,
    bounded counts and sizes, no ZIP64, and members exactly as ``RECORD``
    lists them. A member with no type bits is a regular file.
    """

    infos = archive.infolist()
    require(len(infos) <= WHEEL_MEMBERS, f"{wheel} has too many members")
    require(sum(i.file_size for i in infos) <= WHEEL_BYTES, f"{wheel} unpacks too large")
    entries: dict[str, Entry] = {}
    files: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        name = info.filename.rstrip("/") if info.is_dir() else info.filename
        require(
            re.fullmatch(r"[\w.+-]+(/[\w.+-]+)*", name) is not None
            and ".." not in PurePosixPath(name).parts
            and len(name.encode()) <= WHEEL_NAME_BYTES,
            f"{wheel} member {name!r} is not a plain relative path",
        )
        require(not needs_zip64(info), f"{wheel} needs ZIP64")
        require(not name.split("/")[0].endswith(".data"), f"{wheel} has a .data directory")
        require(name not in entries and name not in files, f"{wheel} repeats {name}")
        kind = stat.S_IFMT(info.external_attr >> 16)
        if info.is_dir():
            entries[name] = (name, "directory", 0o555, None)
            continue
        require(kind in (0, stat.S_IFREG), f"{wheel} member {name} is not a regular file")
        files[name] = info
    digests: dict[str, str] = {}
    recorded: dict[str, str] = {}
    for name, info in files.items():
        with archive.open(info) as stream:
            digest = hashlib.file_digest(stream, "sha256")
        digests[name] = digest.hexdigest()
        encoded = urlsafe_b64encode(digest.digest()).rstrip(b"=").decode()
        recorded[name] = f"sha256={encoded}"
        parts = PurePosixPath(name).parts
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            entries.setdefault(parent, (parent, "directory", 0o555, None))
        mode = 0o555 if (info.external_attr >> 16) & 0o111 else 0o444
        entries[name] = (name, "file", mode, ("zip", wheel, name))
    records = [name for name in files if re.fullmatch(r"[^/]+\.dist-info/RECORD", name)]
    require(len(records) == 1, f"{wheel} has no single RECORD")
    listed: dict[str, str] = {}
    for line in archive.read(records[0]).decode("utf-8").splitlines():
        path, digest, _ = line.rsplit(",", 2)
        listed[path] = digest
    require(listed.pop(records[0], None) == "", f"{wheel} RECORD does not list itself unhashed")
    del recorded[records[0]]
    require(listed == recorded, f"{wheel} members are not its RECORD")
    return list(entries.values()), digests


def package_blobs(commit: str, repository: Path) -> dict[str, bytes]:
    """Every blob under ``src/constructicon`` at the commit, raw; mode 100644 only."""

    listing = git(repository, "ls-tree", "-r", "-z", "--full-tree", commit, "--", PACKAGE_SOURCE)
    require(listing.returncode == 0, f"{PACKAGE_SOURCE} is unreadable at commit")
    blobs: dict[str, bytes] = {}
    for line in listing.stdout.split(b"\x00")[:-1]:
        entry = re.fullmatch(rb"(\d{6}) (\w+) ([0-9a-f]{40})\t(.+)", line)
        require(entry is not None, f"unexpected tree entry {line[:128]!r}")
        assert entry is not None
        path = entry[4].decode()
        require(entry[1] == b"100644" and entry[2] == b"blob", f"{path} is not a regular blob")
        blob = git(repository, "cat-file", "blob", entry[3].decode())
        require(blob.returncode == 0, f"{path} blob is unreadable")
        blobs[path] = blob.stdout
    require(PACKAGE_SOURCE + "/__init__.py" in blobs, f"{PACKAGE_SOURCE} is not a package")
    return blobs


def controller_entries(
    blobs: dict[str, bytes], wheels: list[tuple[list[Entry], dict[str, str]]]
) -> tuple[list[Entry], dict[str, str]]:
    """The package's files and every wheel's, in one tree; a path twice refuses."""

    entries: dict[str, Entry] = {".": (".", "directory", 0o555, None)}
    digests: dict[str, str] = {}

    def add(entry: Entry) -> None:
        name = entry[0]
        if entry[1] == "directory" and entries.get(name, entry) == entry:
            entries[name] = entry
            return
        require(name not in entries, f"{name} would be installed twice")
        entries[name] = entry

    for path, data in sorted(blobs.items()):
        name = PACKAGE + path.removeprefix(PACKAGE_SOURCE)
        parts = PurePosixPath(name).parts
        for index in range(1, len(parts)):
            add(("/".join(parts[:index]), "directory", 0o555, None))
        add((name, "file", 0o444, ("bytes", data)))
        digests[name] = sha256(data)
    for members, sums in wheels:
        for entry in members:
            add(entry)
        digests.update(sums)
    return sorted(entries.values(), key=lambda e: PurePosixPath(e[0]).parts), digests


def interpreter() -> tuple[str, tuple[int, int]]:
    """Platform primitive: the interpreter this script runs as, which runs the controller."""

    return sys.implementation.name, (sys.version_info[0], sys.version_info[1])


def host_glibc() -> int:
    """Platform primitive: the host's glibc minor version; major 2 or refuse."""

    reported = os.confstr("CS_GNU_LIBC_VERSION") or ""
    found = re.fullmatch(r"glibc 2\.(\d+)", reported)
    require(found is not None, f"unexpected libc {reported!r}")
    assert found is not None
    return int(found[1])


def controller_selection(commit: str, workspace: Path, record: dict) -> tuple[dict, list[dict]]:
    """Custody, provenance and the pinned wheel list: every command's first steps."""

    require_unprivileged()
    require_custody(workspace)
    blobs = prove(commit, workspace / REPOSITORY, record, CONTROLLER_BLOBS)
    name, version = interpreter()
    record["interpreter"] = f"{name} {version[0]}.{version[1]}"
    require(name == "cpython" and version == PYTHON_VERSION, "the controller needs CPython 3.12")
    glibc = host_glibc()
    record["glibc_minor"] = glibc
    selected = [select_wheel(package, glibc) for package in controller_closure(blobs[LOCK])]
    record["wheels"] = selected
    return blobs, selected


def require_locked(stream: IO[bytes], wheel: dict[str, str]) -> None:
    """The wheel file is the one the lock pins; the stream is left at its start."""

    require(
        hashlib.file_digest(stream, "sha256").hexdigest() == wheel["sha256"],
        f"{wheel['file']} is not the locked wheel",
    )
    stream.seek(0)


@contextmanager
def controller_plan(
    commit: str, workspace: Path, record: dict
) -> Iterator[tuple[list[Entry], Inventory, dict[str, zipfile.ZipFile]]]:
    """The whole tree from the commit and the pinned wheels; archives stay open for staging."""

    _, selected = controller_selection(commit, workspace, record)
    with ExitStack() as stack:
        archives: dict[str, zipfile.ZipFile] = {}
        planned = []
        for wheel in selected:
            stream = stack.enter_context(open_regular(workspace / WHEELS / wheel["file"]))
            require_locked(stream, wheel)
            try:
                archive = stack.enter_context(zipfile.ZipFile(stream))
                planned.append(wheel_entries(archive, wheel["file"]))
            except zipfile.BadZipFile as exc:
                raise ValueError(f"{wheel['file']} is not a readable wheel") from exc
            archives[wheel["file"]] = archive
        blobs = package_blobs(commit, workspace / REPOSITORY)
        entries, digests = controller_entries(blobs, planned)
        inventory = expected_inventory(entries, lambda entry: digests[entry[0]])
        record["controller_entries"] = len(inventory)
        yield entries, inventory, archives


def controller_contents(archives: dict[str, zipfile.ZipFile]) -> Callable[[object], IO[bytes]]:
    def opened(source: object) -> IO[bytes]:
        if source[0] == "zip":  # type: ignore[index]
            _, wheel, member = source  # type: ignore[misc]
            return archives[wheel].open(member)
        return contents()(source)

    return opened


def controller_wheels(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
    """Read-only: the locked wheels for this interpreter and glibc, for the operator's curl."""

    controller_selection(commit, workspace, record)
    record["listed"] = True


def stage_controller(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
    with controller_plan(commit, workspace, record) as (entries, _, archives):
        plan: list[Entry] = [(".", "directory", 0o700, None)] + [
            (CONTROLLER_STAGED if name == "." else f"{CONTROLLER_STAGED}/{name}", kind, mode, src)
            for name, kind, mode, src in entries
        ]
        materialize(plan, workspace / STAGING, controller_contents(archives))
    record["staged"] = True


def judge_controller(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
    """Every precondition of root's one ``cp``, before it runs."""

    with controller_plan(commit, workspace, record) as (_, inventory, _):
        pass
    staging = workspace / STAGING
    require(stat.S_ISDIR(os.lstat(staging).st_mode), f"{staging} must be a real directory")
    require(os.listdir(staging) == [CONTROLLER_STAGED], "staging must hold exactly the controller")
    differences = compare(tree_inventory(staging / CONTROLLER_STAGED), inventory, os.geteuid())
    record["staged_differences"] = differences[:TREE_SUMMARY]
    require(not differences, "the staged controller is not the reviewed plan")
    require_root_alone(root / CP)
    require(absent(root / CONTROLLER), f"/{CONTROLLER} already exists; installation is fresh-only")
    require_ancestors(root / CONTROLLER, (ROOT_UID,), "root")
    record["ready"] = True


def observe_controller(
    root: Path, listing: str, inventory: Inventory | None = None
) -> dict[str, object]:
    path = root / CONTROLLER
    try:
        info = os.lstat(path)
        entry: dict[str, object] = {"uid": info.st_uid, "mode": oct(stat.S_IMODE(info.st_mode))}
        if stat.S_ISDIR(info.st_mode) and inventory is not None:
            differences = compare(tree_inventory(path), inventory, ROOT_UID)
            entry.update(state="tree", different=len(differences))
            entry["differences"] = differences[:TREE_SUMMARY]
        else:
            entry["state"] = "directory" if stat.S_ISDIR(info.st_mode) else "other"
    except FileNotFoundError:
        entry = {"state": "absent"}
    except (OSError, ValueError) as exc:
        entry = {"state": f"unobservable: {type(exc).__name__}"}
    return {"/" + CONTROLLER: entry}


def verify_controller(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
    """Recomputes the tree from the commit and the pinned wheels; staging is never read."""

    with controller_plan(commit, workspace, record) as (_, inventory, _):
        pass
    record["observed"] = observe_controller(root, listing, inventory)
    entry = record["observed"]["/" + CONTROLLER]
    require(
        entry.get("state") == "tree" and entry.get("different") == 0,
        f"/{CONTROLLER} is not the reviewed tree",
    )
    require_ancestors(root / CONTROLLER, (ROOT_UID,), "root")
    record["installed"] = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=tuple(VERDICTS))
    parser.add_argument("commit")
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)
    verdict = VERDICTS[args.command]
    record: dict[str, object] = {
        "schema_version": 2,
        "command": args.command,
        "commit": args.commit[:64],
        verdict: False,
    }
    listing = ""
    try:
        raw = sys.stdin.buffer.read(LISTING_LIMIT + 1)
        # The list must end within the bound; a truncated one proves nothing.
        require(len(raw) <= LISTING_LIMIT, "the loaded-profile list exceeds its bound")
        listing = raw.decode("utf-8", errors="replace")
        commands = {
            "judge": judge, "verify": verify, "stage-launch": stage_launch,
            "judge-launch": judge_launch, "verify-launch": verify_launch,
            "controller-wheels": controller_wheels, "stage-controller": stage_controller,
            "judge-controller": judge_controller, "verify-controller": verify_controller,
        }  # fmt: skip
        commands[args.command](args.commit, ROOT, args.workspace, listing, record)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        record["failure"] = f"{type(exc).__name__}: {exc}"[:2048]
        observer = (
            observe_launch if args.command.endswith("-launch")
            else observe_controller if "controller" in args.command
            else observe
        )  # fmt: skip
        # A verifier that already observed keeps that record, with its tree differences.
        if "observed" not in record:
            record["observed"] = observer(ROOT, listing)
    print(json.dumps(record, sort_keys=True, indent=2))
    return 0 if record[verdict] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
