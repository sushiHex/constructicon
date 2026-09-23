"""Judge and verify the reviewed M8 qualification artifacts on the private host (#94).

Runs unprivileged only, as ``/usr/bin/python3 -I``, after stock git has proved
that this file is the blob at a commit on main, and refuses to run as root. It
never writes: between ``judge`` and ``verify``, root installs the artifacts with
a fixed sequence of stock tools. That sequence, the procedure and their limits
are in docs/plans/handoffs/M8-D2-host-installation.md. Stdlib only: no
Constructicon import, no network, no marker file, and children get a fixed
environment. The production root and every destination are fixed; the command
line names only the commit and the operator's private workspace.

``judge`` proves every precondition of root's sequence. ``verify`` recomputes
everything from scratch against the blobs at the commit, never against the
staged copies. Both read the kernel's loaded-profile list from standard input,
where root's ``cat`` pipes it. The verdict (``ready`` or ``installed``) stays
false unless every fixed check passed, and the exit status follows it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

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


def prove(commit: str, repository: Path, record: dict) -> dict[str, bytes]:
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
    for path in (SCRIPT, PROBE, PROFILE):
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
    require(not loaded_profiles(listing), "a constructicon-m8 profile is already loaded")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("judge", "verify"))
    parser.add_argument("commit")
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)
    verdict = "ready" if args.command == "judge" else "installed"
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
        command = judge if args.command == "judge" else verify
        command(args.commit, ROOT, args.workspace, listing, record)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        record["failure"] = f"{type(exc).__name__}: {exc}"[:2048]
        record["observed"] = observe(ROOT, listing)
    print(json.dumps(record, sort_keys=True, indent=2))
    return 0 if record[verdict] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
