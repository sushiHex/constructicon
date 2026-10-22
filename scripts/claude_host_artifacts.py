"""Unprivileged, offline Claude artifact staging and host verification.

This is a candidate for a separately reviewed private-host procedure, not an
installer to run from CI or as root. Root's fixed stock-tool installation is
outside this program. Nothing here starts the vendor or accesses a credential.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

HOST_ROOT = Path("/")
ROOT_UID = 0
SCRIPT = "scripts/claude_host_artifacts.py"
POLICY_SOURCE = "scripts/constructicon-m8-claude.apparmor"
SUPERVISOR = "src/constructicon/substrate/executors/_supervisor.py"
BRIDGE = "src/constructicon/substrate/executors/_egress_bridge.py"
LAUNCHER = "src/constructicon/substrate/executors/linux.py"
PROTOCOL = "src/constructicon/substrate/executors/claude_protocol.py"
SOURCE_BLOBS = (SCRIPT, POLICY_SOURCE, SUPERVISOR, BRIDGE, LAUNCHER, PROTOCOL)
INSTALL_ROOT = "var/lib/constructicon-m8-claude"
POLICY_DEST = "etc/apparmor.d/constructicon-m8-claude"
STAGING = "staging"
REPOSITORY = "source.git"
ARCHIVE = "claude.tgz"
SELECTION = "selection.json"
CONFIG_BYTES = 8192
SELECTION_BYTES = 4096
ARCHIVE_BYTES = 268435456
ARCHIVE_MEMBERS = 32
ARCHIVE_SHA256 = "eef5a2e2b09a5e7d2ce784d1b3ba335ae7fc6c7f6256c802a0ebf2c21e4fd0e1"
MEMBER = "package/claude"
MEMBER_SIZE = 257068216
MEMBER_SHA256 = "24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de"
BWRAP_SHA256 = "e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71"
VERSION = "2.1.296"
CLAUDE_PROFILES = (
    "constructicon-m8-claude-launch (enforce)\n"
    "constructicon-m8-claude-bootstrap (enforce)\n"
    "constructicon-m8-claude-native (enforce)\n"
)
PROFILE_NAMES = ("constructicon-m8-claude-launch", "constructicon-m8-claude-bootstrap",
                 "constructicon-m8-claude-native")
GIT = "/usr/bin/git"
GIT_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_GRAFT_FILE": "/nonexistent"}
RUNTIME_LIMIT = 20000
FILE_BYTES = 64 << 20
LIBRARY = "usr/lib/python3.12"
PYTHON = "usr/bin/python3.12"
GIT_BINARY = "usr/bin/git"
TRUST_BUNDLE = "etc/ssl/certs/ca-certificates.crt"
LOADER = "lib64/ld-linux-x86-64.so.2"
LOADER_CACHE = "etc/ld.so.cache"
ABI = "etc/apparmor.d/abi/4.0"
HOST_LIB = "usr/lib/x86_64-linux-gnu"
EXTRA_LIBRARIES = ("librt.so.1", "libpthread.so.0", "libdl.so.2")
IGNORED = frozenset({"__pycache__", "test", "tests", "ensurepip", "idlelib"})
PHASE_HOSTS = {"login": {"platform.claude.com"},
               "observe": {"platform.claude.com", "api.anthropic.com"},
               "reload": {"platform.claude.com", "api.anthropic.com"}}
SELECTION_FIELDS = {"schema_version", "model", "effort", "egress"}
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
EFFORTS = {"low", "medium", "high", "xhigh", "max"}


@dataclass(frozen=True)
class Entry:
    name: str
    kind: str
    mode: int
    source: object


@dataclass(frozen=True)
class Plan:
    entries: tuple[Entry, ...]
    inventory: tuple[tuple[str, int, str], ...]
    policy: bytes
    config: bytes
    config_sha256: str
    vendor: bytes
    runtime_digest: str
    vendor_digest: str
    policy_sha256: str


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def exact_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, "duplicate selection key")
        result[key] = value
    return result


def read_selection(raw: bytes) -> dict:
    """The only private configuration input, with no command or path selector."""
    require(0 < len(raw) <= SELECTION_BYTES, "invalid selection size")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=exact_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid selection JSON") from exc
    require(type(value) is dict and set(value) == SELECTION_FIELDS, "invalid selection fields")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1,
            "invalid selection schema")
    require(type(value["model"]) is str and MODEL.fullmatch(value["model"]) is not None,
            "invalid selected model")
    require(type(value["effort"]) is str and value["effort"] in EFFORTS,
            "invalid selected effort")
    egress = value["egress"]
    require(type(egress) is dict and set(egress) == set(PHASE_HOSTS),
            "invalid selection phases")
    for phase, expected in PHASE_HOSTS.items():
        policy = egress[phase]
        require(type(policy) is dict and set(policy) == {"destinations", "connections"},
                "invalid phase policy")
        count = policy["connections"]
        require(type(count) is int and 0 < count <= 1024, "invalid connection budget")
        destinations = policy["destinations"]
        require(type(destinations) is list and len(destinations) == len(expected),
                "invalid phase destinations")
        hosts = []
        for item in destinations:
            require(type(item) is list and len(item) == 3, "invalid destination")
            host, port, address = item
            require(type(host) is str and type(port) is int and port == 443
                    and type(address) is str, "invalid destination fields")
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError as exc:
                raise ValueError("invalid destination address") from exc
            require(parsed.is_global and str(parsed) == address,
                    "destination must be a canonical globally routable address")
            hosts.append(host)
        require(set(hosts) == expected and len(set(hosts)) == len(hosts),
                "invalid phase hosts")
    return value


def read_bounded_regular(path: Path, limit: int) -> bytes:
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= limit,
            "source is not a bounded regular file")
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
             | getattr(os, "O_BINARY", 0))
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        require(stat.S_ISREG(opened.st_mode)
                and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
                "source changed before opening")
        parts = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(1 << 20, remaining))
            if not chunk:
                break
            parts.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(parts)
        require(len(raw) <= limit and len(raw) == opened.st_size,
                "source exceeds its byte bound or changed")
        return raw
    finally:
        os.close(descriptor)


def read_vendor(path: Path) -> bytes:
    """Select the one pinned member from one bounded immutable byte snapshot."""
    raw = read_bounded_regular(path, ARCHIVE_BYTES)
    require(sha256(raw) == ARCHIVE_SHA256, "archive differs from reviewed bytes")
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as package:
            selected = []
            for index, member in enumerate(package):
                require(index < ARCHIVE_MEMBERS, "archive has too many members")
                if member.name == MEMBER:
                    selected.append(member)
            require(len(selected) == 1, "archive lacks one selected member")
            member = selected[0]
            require(member.isreg() and member.size == MEMBER_SIZE,
                    "selected member kind or size differs")
            stream = package.extractfile(member)
            require(stream is not None, "selected member is unreadable")
            assert stream is not None
            with stream:
                payload = stream.read(MEMBER_SIZE + 1)
            require(len(payload) == MEMBER_SIZE and sha256(payload) == MEMBER_SHA256,
                    "selected member differs from reviewed bytes")
            return payload
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ValueError("archive cannot be parsed") from exc


def identity_digest(domain: str, value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)
    material = "\0".join(("constructicon", domain, "1", body))
    return "sha256:" + sha256(material.encode("utf-8"))


def configuration_bytes(selection: dict, *, runtime_digest: str, vendor_digest: str,
                        policy_sha256: str) -> bytes:
    value = {
        "schema_version": 1, "launch_root": "/" + INSTALL_ROOT,
        "runtime_digest": runtime_digest, "bubblewrap_sha256": BWRAP_SHA256,
        "launch_policy": "/" + POLICY_DEST,
        "launch_policy_sha256": policy_sha256,
        "vendor_tree": "/" + INSTALL_ROOT + "/vendor", "vendor_digest": vendor_digest,
        "vendor_version": VERSION, "model": selection["model"],
        "effort": selection["effort"], "egress": selection["egress"],
    }
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    require(len(raw) <= CONFIG_BYTES, "emitted configuration exceeds its byte bound")
    return raw


def run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, input=b"", capture_output=True, check=False,
                          timeout=30, env=GIT_ENV)


def git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return run([GIT, "--no-replace-objects", f"--git-dir={repository}", *arguments])


def require_unprivileged() -> None:
    require(sys.platform == "linux" and os.geteuid() != 0,
            "host artifact helper requires a non-root Linux operator")


def operator_uid() -> int:
    return os.geteuid() if hasattr(os, "geteuid") else Path.cwd().stat().st_uid


def require_ancestors(path: Path, owners: tuple[int, ...]) -> None:
    for parent in path.parents:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid in owners
                and not info.st_mode & 0o022, "artifact ancestor is not in trusted custody")
        if parent == HOST_ROOT:
            break


def require_custody(workspace: Path) -> None:
    require(workspace.is_absolute() and ".." not in workspace.parts,
            "workspace must be an absolute private path")
    owner = os.geteuid()
    info = workspace.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == owner
            and not info.st_mode & 0o077, "workspace is not private to the operator")
    repository = workspace / REPOSITORY
    require(stat.S_ISDIR(repository.lstat().st_mode), "source.git is not a real directory")
    require_ancestors(workspace, (ROOT_UID, owner))


def require_root_file(path: Path) -> None:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == ROOT_UID
            and not info.st_mode & 0o6022, "host source is not root-owned and fixed")
    require_ancestors(path, (ROOT_UID,))


def require_original_path(path: Path, host_root: Path) -> None:
    """Root owns each original lookup component, including usr-merge links."""
    require(path.is_relative_to(host_root), "host source leaves root")
    current = host_root
    for part in path.relative_to(host_root).parts[:-1]:
        current /= part
        info = current.lstat()
        fixed_directory = (stat.S_ISDIR(info.st_mode)
                           and not info.st_mode & 0o022)
        fixed_link = stat.S_ISLNK(info.st_mode)
        require(info.st_uid == ROOT_UID and (fixed_directory or fixed_link),
                "host source lookup is not root-held")
        resolved = current.resolve(strict=True)
        require(resolved.is_relative_to(host_root.resolve()),
                "host source lookup escapes root")
        target = resolved.lstat()
        require(stat.S_ISDIR(target.st_mode) and target.st_uid == ROOT_UID
                and not target.st_mode & 0o022,
                "host source lookup target is not a fixed root directory")


def require_tools(host_root: Path) -> None:
    for name in ("usr/bin/install", "usr/bin/cp", "usr/bin/cat",
                 "usr/sbin/apparmor_parser", "usr/bin/bwrap"):
        require_root_file(host_root / name)


def require_destination_ancestors(host_root: Path) -> None:
    for name in (INSTALL_ROOT, POLICY_DEST):
        require_ancestors(host_root / name, (ROOT_UID,))


def prove_sources(commit: str, workspace: Path) -> dict[str, bytes]:
    """Prove raw non-executable blobs on fetched main's first-parent line."""
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None,
            "commit must be exactly forty lowercase hex digits")
    repository = workspace / REPOSITORY
    main = git(repository, "rev-parse", "--verify", "refs/heads/main^{commit}")
    require(main.returncode == 0, "fetched main is missing")
    line = git(repository, "rev-list", "--first-parent", main.stdout.decode().strip())
    require(line.returncode == 0 and commit in line.stdout.decode().split(),
            "commit is not on main's first-parent line")
    blobs: dict[str, bytes] = {}
    for path in SOURCE_BLOBS:
        listed = git(repository, "ls-tree", "-z", "--full-tree", commit, "--", path)
        match = re.fullmatch(rb"(\d{6}) blob ([0-9a-f]{40})\t([^\x00]+)\x00",
                             listed.stdout)
        require(listed.returncode == 0 and match is not None
                and match[1] == b"100644" and match[3] == path.encode(),
                "required source is not one regular blob")
        assert match is not None
        blob = git(repository, "cat-file", "blob", match[2].decode())
        require(blob.returncode == 0, "source blob cannot be read")
        blobs[path] = blob.stdout
    require(blobs[SCRIPT] == Path(__file__).read_bytes(),
            "running host helper differs from commit blob")
    return blobs


def derive_one(blob: bytes, pattern: bytes) -> str:
    matches = re.findall(pattern, blob, re.M)
    require(len(matches) == 1, "reviewed source value is ambiguous")
    return matches[0].decode("ascii")


def verify_source_constants(blobs: dict[str, bytes]) -> tuple[str, str]:
    require(derive_one(blobs[LAUNCHER],
                       rb'^BWRAP_SHA256 = "([0-9a-f]{64})"$') == BWRAP_SHA256,
            "bubblewrap source identity differs")
    require(derive_one(blobs[PROTOCOL],
                       rb'^CLAUDE_CODE_VERSION = "([0-9.]+)"$') == VERSION,
            "Claude version source identity differs")
    supervisor_path = derive_one(
        blobs[SUPERVISOR], rb'^NAMESPACE_SCRIPT = "(/usr/libexec/[a-z0-9.-]+)"$')
    bridge_path = derive_one(
        blobs[BRIDGE], rb'^BRIDGE_SCRIPT = "(/usr/libexec/[a-z0-9.-]+)"$')
    return supervisor_path, bridge_path


def require_policy(policy: bytes) -> None:
    try:
        source = policy.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Claude policy is not UTF-8") from exc
    names = re.findall(r"^profile ([a-z0-9-]+)\b", source, re.M)
    require(names == list(PROFILE_NAMES), "Claude policy has unexpected profiles")
    require(f"profile {PROFILE_NAMES[0]} /{INSTALL_ROOT}/bwrap " in source,
            "Claude launch profile names another executable")


def source_path(host_root: Path, path: Path) -> Path:
    require_original_path(path, host_root)
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(host_root.resolve()), "host source escapes root")
    require_root_file(resolved)
    return resolved


def resolve_dependencies(loader: Path, binary: Path) -> list[str]:
    result = run([str(loader), "--list", str(binary)])
    output = result.stdout.decode("utf-8", errors="strict")
    require(result.returncode == 0 and "not found" not in output,
            "trusted host loader cannot resolve a runtime source")
    return re.findall(r"(?:=>\s+)?(/[\w./+-]+)", output)


def checked_dependencies(host_root: Path, binary: Path) -> list[str]:
    """No host loader or candidate library executes before root-custody proof."""
    loader = host_root / LOADER
    for path in (loader, binary):
        real = source_path(host_root, path)
        require(0 < real.stat().st_size <= FILE_BYTES,
                "loader input is not a bounded regular file")
    return resolve_dependencies(loader, binary)


def runtime_plan(host_root: Path, blobs: dict[str, bytes]) -> list[Entry]:
    """Fresh Python/Git/shell closure with Claude's sole vendor mountpoint."""
    supervisor_path, bridge_path = verify_source_constants(blobs)
    require_root_file(host_root / LOADER_CACHE)
    entries: dict[str, Entry] = {".": Entry(".", "directory", 0o555, None)}
    visited_directories: set[Path] = set()

    def directory(name: str) -> None:
        parts = PurePosixPath(name).parts
        require(len(parts) <= 32, "runtime path exceeds its depth bound")
        for index in range(1, len(parts) + 1):
            parent = "/".join(parts[:index])
            entries.setdefault(parent, Entry(parent, "directory", 0o555, None))

    def host_file(name: str, source: Path, *, allow_empty: bool = False) -> None:
        require(re.fullmatch(r"[\w.+-]+(/[\w.+-]+)*", name) is not None,
                "runtime path is not plain and relative")
        require(all(part not in (".", "..") for part in name.split("/")),
                "runtime path traverses a parent")
        if name in entries:
            return
        require(len(entries) < RUNTIME_LIMIT, "runtime has too many entries")
        real = source_path(host_root, source)
        info = real.stat()
        require(stat.S_ISREG(info.st_mode)
                and (allow_empty or info.st_size > 0) and info.st_size <= FILE_BYTES,
                "host source is not a bounded regular file")
        directory(str(PurePosixPath(name).parent))
        entries[name] = Entry(name, "file", 0o555 if info.st_mode & 0o111 else 0o444,
                              ("host", real))

    def tree(source: Path, name: str) -> None:
        require_original_path(source, host_root)
        real = source.resolve(strict=True)
        require(real.is_relative_to(host_root.resolve()) and real not in visited_directories,
                "runtime source directory escapes or repeats")
        info = real.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == ROOT_UID
                and not info.st_mode & 0o022,
                "runtime source directory is not fixed")
        visited_directories.add(real)
        directory(name)
        for child in sorted(os.scandir(source), key=lambda value: value.name):
            if child.name in IGNORED:
                continue
            dest = f"{name}/{child.name}"
            if child.is_dir():
                tree(Path(child.path), dest)
            else:
                host_file(dest, Path(child.path), allow_empty=True)

    for name in (PYTHON, GIT_BINARY, TRUST_BUNDLE, "bin/sh", LOADER):
        host_file(name, host_root / name)
    tree(host_root / LIBRARY, LIBRARY)
    binaries = [host_root / name for name in (PYTHON, GIT_BINARY, "bin/sh")]
    binaries.extend(sorted((host_root / LIBRARY).rglob("*.so")))
    for binary in binaries:
        for dependency in checked_dependencies(host_root, binary):
            host_file(dependency.lstrip("/"), host_root / dependency.lstrip("/"))
    for name in EXTRA_LIBRARIES:
        host_file(f"lib/x86_64-linux-gnu/{name}", host_root / HOST_LIB / name)
    for path, data in ((supervisor_path, blobs[SUPERVISOR]),
                       (bridge_path, blobs[BRIDGE])):
        name = path.removeprefix("/")
        require(name not in entries, "trusted helper would replace a runtime source")
        directory(str(PurePosixPath(name).parent))
        entries[name] = Entry(name, "file", 0o444, ("bytes", data))
    for name in ("proc", "dev", "tmp", "workspace", "opt/claude", "etc/claude-code"):
        directory(name)
    for name in ("etc/claude-code/managed-settings.json",
                 "etc/claude-code/managed-mcp.json", "vendor-egress.sock"):
        entries[name] = Entry(name, "file", 0o444, ("bytes", b""))
    directory("usr/bin")
    entries["usr/bin/python3"] = Entry("usr/bin/python3", "link", 0o777, "python3.12")
    require(len(entries) <= RUNTIME_LIMIT, "runtime has too many entries")
    return sorted(entries.values(), key=lambda entry: PurePosixPath(entry.name).parts)


def entry_bytes(source: object) -> bytes:
    kind, value = source  # type: ignore[misc]
    if kind == "host":
        return read_bounded_regular(value, FILE_BYTES)
    return value


def inventory(entries: list[Entry]) -> tuple[tuple[str, int, str], ...]:
    result = []
    for entry in sorted(entries, key=lambda item: PurePosixPath(item.name).parts):
        if entry.kind == "directory":
            content = "directory"
        elif entry.kind == "link":
            content = "link:" + str(entry.source)
        else:
            content = "sha256:" + sha256(entry_bytes(entry.source))
        result.append((entry.name, entry.mode, content))
    return tuple(result)


def prefixed_inventory(
    prefix: str, entries: tuple[tuple[str, int, str], ...],
) -> tuple[tuple[str, int, str], ...]:
    """Reuse captured content identities without reopening source files."""
    return tuple((prefix if name == "." else f"{prefix}/{name}", mode, content)
                 for name, mode, content in entries)


def ordered_inventory(
    entries: tuple[tuple[str, int, str], ...],
) -> tuple[tuple[str, int, str], ...]:
    return tuple(sorted(entries, key=lambda item: PurePosixPath(item[0]).parts))


def plan(commit: str, workspace: Path, host_root: Path) -> Plan:
    require_unprivileged()
    require_custody(workspace)
    blobs = prove_sources(commit, workspace)
    verify_source_constants(blobs)
    selected = read_selection(read_bounded_regular(workspace / SELECTION, SELECTION_BYTES))
    vendor = read_vendor(workspace / ARCHIVE)
    bwrap = host_root / "usr/bin/bwrap"
    require_root_file(bwrap)
    require(sha256(read_bounded_regular(bwrap, FILE_BYTES)) == BWRAP_SHA256,
            "host bubblewrap differs from the supported build")
    runtime = runtime_plan(host_root, blobs)
    runtime_inventory = inventory(runtime)
    runtime_digest = identity_digest("linux-runtime-root", runtime_inventory)
    vendor_entries = [Entry(".", "directory", 0o555, None),
                      Entry("claude", "file", 0o555, ("bytes", vendor))]
    vendor_inventory = inventory(vendor_entries)
    vendor_digest = identity_digest("linux-runtime-root", vendor_inventory)
    policy = blobs[POLICY_SOURCE]
    require_policy(policy)
    policy_sha256 = sha256(policy)
    abi = host_root / ABI
    require_root_file(abi)
    abi_bytes = read_bounded_regular(abi, FILE_BYTES)
    require(bool(abi_bytes), "apparmor ABI is empty")
    abi_sha256 = sha256(abi_bytes)
    config = configuration_bytes(selected, runtime_digest=runtime_digest,
                                 vendor_digest=vendor_digest,
                                 policy_sha256=policy_sha256)
    runtime_document = (json.dumps({
        "runtime_digest": runtime_digest, "entries": runtime_inventory,
        "bubblewrap_sha256": BWRAP_SHA256,
        "apparmor_policy_sha256": policy_sha256,
        "apparmor_abi_sha256": abi_sha256,
    }, sort_keys=True) + "\n").encode()

    def prefixed(prefix: str, source: list[Entry]) -> list[Entry]:
        return [Entry(prefix if item.name == "." else f"{prefix}/{item.name}",
                      item.kind, item.mode, item.source) for item in source]

    entries = [Entry(".", "directory", 0o755, None),
               Entry("bwrap", "file", 0o555, ("host", bwrap)),
               *prefixed("runtime", runtime), *prefixed("vendor", vendor_entries),
               Entry("runtime.json", "file", 0o444, ("bytes", runtime_document)),
               Entry("launch-config.json", "file", 0o444, ("bytes", config))]
    complete_inventory = ordered_inventory((
        (".", 0o755, "directory"),
        ("bwrap", 0o555, "sha256:" + BWRAP_SHA256),
        *prefixed_inventory("runtime", runtime_inventory),
        *prefixed_inventory("vendor", vendor_inventory),
        ("runtime.json", 0o444, "sha256:" + sha256(runtime_document)),
        ("launch-config.json", 0o444, "sha256:" + sha256(config)),
    ))
    return Plan(tuple(entries), complete_inventory, policy, config, sha256(config),
                vendor, runtime_digest, vendor_digest, policy_sha256)


def materialize(entries: list[Entry], destination: Path) -> None:
    """Write only a new private staging tree; never replace an existing path."""
    directories: list[tuple[Path, int]] = []
    for entry in entries:
        name = entry.name
        path = PurePosixPath(name)
        require(name == "." or (not path.is_absolute() and "." not in path.parts
                                     and ".." not in path.parts), "invalid planned path")
        target = destination if name == "." else destination / name
        if entry.kind == "directory":
            os.mkdir(target, 0o700)
            directories.append((target, entry.mode))
        elif entry.kind == "link":
            os.symlink(str(entry.source), target)
        else:
            flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
            descriptor = os.open(target, flags, 0o600)
            try:
                data = entry_bytes(entry.source)
                view = memoryview(data)
                while view:
                    view = view[os.write(descriptor, view):]
                if hasattr(os, "fchmod"):
                    os.fchmod(descriptor, entry.mode)
                else:  # Portable fake proof; production is Linux with fchmod.
                    os.chmod(target, entry.mode)
            finally:
                os.close(descriptor)
    for target, mode in reversed(directories):
        os.chmod(target, mode)


def tree_inventory(top: Path) -> tuple[tuple[str, int, str, int], ...]:
    require(stat.S_ISDIR(top.lstat().st_mode), "artifact tree is not a real directory")
    entries = []
    for path in (top, *sorted(top.rglob("*"))):
        info = path.lstat()
        name = path.relative_to(top).as_posix()
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            require((path.parent / target).resolve().is_relative_to(top.resolve()),
                    "artifact symlink leaves its tree")
            content = "link:" + target
        elif stat.S_ISDIR(info.st_mode):
            content = "directory"
        elif stat.S_ISREG(info.st_mode):
            maximum = MEMBER_SIZE if name in (
                "vendor/claude", "constructicon-m8-claude/vendor/claude"
            ) else FILE_BYTES
            content = "sha256:" + sha256(
                read_bounded_regular(path, maximum))
        else:
            raise ValueError("artifact tree contains a non-file entry")
        entries.append((name, stat.S_IMODE(info.st_mode), content, info.st_uid))
    return tuple(entries)


def differences(observed: tuple[tuple[str, int, str, int], ...],
                expected: tuple[tuple[str, int, str], ...], owner: int) -> list[str]:
    found = {name: (mode, content, uid) for name, mode, content, uid in observed}
    wanted = {name: (mode, content) for name, mode, content in expected}
    return [name for name in sorted(set(found) | set(wanted))
            if name not in found or name not in wanted
            or found[name][:2] != wanted[name] or found[name][2] != owner]


def staging_entries(current: Plan) -> list[Entry]:
    return [Entry(".", "directory", 0o700, None),
            *[Entry("constructicon-m8-claude" if item.name == "." else
                    f"constructicon-m8-claude/{item.name}",
                    item.kind, item.mode, item.source) for item in current.entries],
            Entry("constructicon-m8-claude.apparmor", "file", 0o444,
                  ("bytes", current.policy))]


def staging_inventory(current: Plan) -> tuple[tuple[str, int, str], ...]:
    return ordered_inventory((
        (".", 0o700, "directory"),
        *prefixed_inventory("constructicon-m8-claude", current.inventory),
        ("constructicon-m8-claude.apparmor", 0o444,
         "sha256:" + current.policy_sha256),
    ))


def stage(commit: str, workspace: Path, *, host_root: Path = HOST_ROOT) -> dict:
    current = plan(commit, workspace, host_root)
    staging = workspace / STAGING
    require(not staging.exists() and not staging.is_symlink(),
            "staging must be fresh")
    entries = staging_entries(current)
    materialize(entries, staging)
    expected = staging_inventory(current)
    drift = differences(tree_inventory(staging), expected, operator_uid())
    require(not drift, "staging differs from reviewed plan: " + repr(drift[:8]))
    return {"staged": True, "launch_config_sha256": current.config_sha256,
            "runtime_digest": current.runtime_digest,
            "vendor_digest": current.vendor_digest,
            "policy_sha256": current.policy_sha256}


def loaded_claude_profiles(listing: str) -> list[str]:
    lines = listing.splitlines()
    require(bool(lines) and all(re.fullmatch(r"\S.* \([a-z]+\)", line)
                                for line in lines), "invalid loaded-profile list")
    return [line for line in lines if line.startswith("constructicon-m8-claude-")]


def check_config_pin(current: Plan, expected_sha256: str) -> None:
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None
            and current.config_sha256 == expected_sha256,
            "configuration differs from independent reviewed hash")


def judge(commit: str, workspace: Path, *, expected_sha256: str,
          profile_list: str, host_root: Path = HOST_ROOT) -> dict:
    try:
        current = plan(commit, workspace, host_root)
        check_config_pin(current, expected_sha256)
        require_tools(host_root)
        require_destination_ancestors(host_root)
        staging = workspace / STAGING
        require(not differences(tree_inventory(staging), staging_inventory(current),
                                operator_uid()),
                "staging differs from reviewed plan")
        require(not (host_root / INSTALL_ROOT).exists()
                and not (host_root / INSTALL_ROOT).is_symlink(),
                "Claude installation destination already exists")
        require(not (host_root / POLICY_DEST).exists()
                and not (host_root / POLICY_DEST).is_symlink(),
                "Claude policy destination already exists")
        require(not loaded_claude_profiles(profile_list),
                "Claude profiles already loaded")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"ready": False}
    return {"ready": True, "launch_config_sha256": current.config_sha256,
            "runtime_digest": current.runtime_digest,
            "vendor_digest": current.vendor_digest,
            "policy_sha256": current.policy_sha256}


def verify(commit: str, workspace: Path, *, expected_sha256: str,
           profile_list: str, host_root: Path = HOST_ROOT) -> dict:
    try:
        current = plan(commit, workspace, host_root)
        check_config_pin(current, expected_sha256)
        require_destination_ancestors(host_root)
        installed = host_root / INSTALL_ROOT
        require(not differences(tree_inventory(installed), current.inventory, ROOT_UID),
                "installed Claude tree differs from reviewed plan")
        policy = host_root / POLICY_DEST
        info = policy.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == ROOT_UID
                and stat.S_IMODE(info.st_mode) == 0o444
                and sha256(read_bounded_regular(policy, FILE_BYTES)) == current.policy_sha256,
                "installed policy differs from reviewed source")
        require(sorted(loaded_claude_profiles(profile_list))
                == sorted(CLAUDE_PROFILES.splitlines()),
                "Claude enforce profiles differ from reviewed policy")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"installed": False}
    return {"installed": True, "launch_config_sha256": current.config_sha256,
            "runtime_digest": current.runtime_digest,
            "vendor_digest": current.vendor_digest,
            "policy_sha256": current.policy_sha256}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "judge", "verify"))
    parser.add_argument("commit")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--launch-config-sha256")
    options = parser.parse_args(argv)
    try:
        if options.command == "stage":
            require(options.launch_config_sha256 is None,
                    "stage cannot self-approve its configuration")
            require(not sys.stdin.buffer.read(1), "stage stdin must be closed")
            result = stage(options.commit, options.workspace, host_root=HOST_ROOT)
            verdict = "staged"
        else:
            require(options.launch_config_sha256 is not None,
                    "judge/verify need an independent configuration hash")
            raw = sys.stdin.buffer.read(1 << 20)
            require(len(raw) < 1 << 20, "loaded-profile list exceeds its bound")
            listing = raw.decode("utf-8", errors="strict")
            if options.command == "judge":
                result = judge(options.commit, options.workspace,
                               expected_sha256=options.launch_config_sha256,
                               profile_list=listing, host_root=HOST_ROOT)
                verdict = "ready"
            else:
                result = verify(options.commit, options.workspace,
                                expected_sha256=options.launch_config_sha256,
                                profile_list=listing, host_root=HOST_ROOT)
                verdict = "installed"
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        verdict = {"stage": "staged", "judge": "ready", "verify": "installed"}[options.command]
        result = {verdict: False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result[verdict] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
