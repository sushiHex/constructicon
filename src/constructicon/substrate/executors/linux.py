"""One concrete, networkless Linux launch recipe and bounded subprocess pump.

Backend adapters and contained Git/gates consume this boundary; it knows no
models, command journal, lease disposition, or graph scheduling. Provisioning
is an operator action, never an import or runtime fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import os
import stat
import struct
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest, digest
from constructicon.core.process import ProcessIO
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors._egress_bridge import BRIDGE_SCRIPT
from constructicon.substrate.executors._supervisor import NAMESPACE_SCRIPT
from constructicon.substrate.executors.egress import ZONE_SOCKET, EgressSocket
from constructicon.substrate.executors.operator_store import CREDENTIAL_FILE, BindingCheck

SUPERVISOR_PATH = Path(NAMESPACE_SCRIPT.removeprefix("/"))
BWRAP_SHA256 = "e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71"
_PROBE = """
import ctypes, errno, json, os
from pathlib import Path
libc = ctypes.CDLL(None, use_errno=True)
nested = libc.unshare(0x10000000)
print(json.dumps({
    'namespaces': {n: os.readlink('/proc/self/ns/' + n)
                   for n in ('user', 'mnt', 'pid', 'ipc', 'uts', 'net')},
    'profile': Path('/proc/self/attr/current').read_text().strip(),
    'status': '\\n'.join(line for line in Path('/proc/self/status').read_text().splitlines()
                        if line.startswith(('NoNewPrivs:', 'CapEff:'))),
    'nested_denied': nested == -1 and ctypes.get_errno() in (errno.EACCES, errno.EPERM),
    'sys_absent': not Path('/sys').exists(),
}))
"""


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_fixed_artifact(path: Path) -> None:
    """The service cannot replace a trusted tool or any of its ancestors."""

    info = path.stat()
    if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o6022:
        raise ContractViolation("launcher artifacts must be fixed root-owned files")
    for parent in path.parents:
        info = parent.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ContractViolation(f"launcher ancestor {parent} must be root-owned")


def runtime_inventory(root: Path, *, require_immutable: bool = True) -> list[tuple[str, int, str]]:
    """Hash actual installed content and topology, never version text or paths.

    The operator supplies a dedicated root-owned closure. Symlink targets are
    bytes, not host paths to follow; no device, socket, or writable file belongs
    in an immutable userspace. Immutability prevents check-to-mount replacement.
    """

    if not root.is_dir() or root.is_symlink():
        raise ContractViolation("runtime root must be a real directory")
    entries: list[tuple[str, int, str]] = []
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if require_immutable and (
            info.st_uid != 0 or (not stat.S_ISLNK(info.st_mode) and mode & 0o6222)
        ):
            raise ContractViolation("runtime content must be root-owned and immutable")
        name = path.relative_to(root).as_posix()
        if stat.S_ISLNK(info.st_mode):
            if not path.resolve().is_relative_to(root.resolve()):
                raise ContractViolation("runtime symlink leaves the immutable closure")
            content = "link:" + os.readlink(path)
        elif stat.S_ISDIR(info.st_mode):
            content = "directory"
        elif stat.S_ISREG(info.st_mode):
            content = "sha256:" + _sha(path)
        else:
            raise ContractViolation("runtime contains a non-file entry")
        entries.append((name, mode, content))
    return entries


def runtime_digest(root: Path, *, require_immutable: bool = True) -> Digest:
    return digest(
        "linux-runtime-root", 1, runtime_inventory(root, require_immutable=require_immutable),
    )


@dataclass(frozen=True)
class ProcessLimits:
    input_bytes: int = 1024 * 1024
    artifact_bytes: int = 16 * 1024 * 1024
    stdout_bytes: int = 32 * 1024 * 1024
    record_bytes: int = 4 * 1024 * 1024
    stderr_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError("process byte limits must be positive integers")


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    elapsed_s: float
    timed_out: bool = False
    bound_exceeded: str | None = None
    # Only the private trusted-reaper channel can supply this observation.
    payload_returncode: int | None = None


DEFAULT_PROCESS_LIMITS = ProcessLimits()

Conversation = Callable[[ProcessIO], Awaitable[None]]


NATIVE_HOME = "/tmp/home/.codex"
"""The native zone's vendor home: a fresh tmpfs directory, disposable with it."""

VENDOR_MOUNT = "/opt/codex"
CATALOG_MOUNT = "/opt/codex-models.json"
"""Where the launch set's vendor tree and model catalog appear in the zone.

The runtime image carries only the two empty mount points; the content is
bound read-only from the launch set (M8-N4-state-review.md, host-runtime
interface item 1)."""


def _require_root_fixed(info: os.stat_result, *, kind: int) -> None:
    if stat.S_IFMT(info.st_mode) != kind or info.st_uid != 0 or info.st_mode & 0o6022:
        raise ContractViolation("the native vendor content must be root-owned and fixed")


@dataclass(frozen=True)
class NativeVendor:
    """The launch set's installed vendor package and catalog, bound, never copied.

    verify-launch checks both against their pinned digests at installation and
    requalification. Rehashing the ~340 MB tree on every launch would cost each
    launch, containment test and mutant up to ~0.7 s, so a launch checks custody
    only (orchestrator decision, 2026-09-24):
    - every entry is a real directory or regular file, never a link or device;
    - every entry is root-owned, with no set-id bit and no group or other write;
    - every ancestor is root-owned and not group- or other-writable.

    Nothing but root can then change what the zone receives between this check
    and the mount.
    """

    tree: Path
    catalog: Path

    def check(self) -> None:
        for path in (self.tree, self.catalog):
            if not path.is_absolute():
                raise ContractViolation("the native vendor content needs absolute paths")
            for parent in path.parents:
                info = os.stat(parent)
                if info.st_uid != 0 or info.st_mode & 0o022:
                    raise ContractViolation(f"native vendor ancestor {parent} must be root-owned")
        _require_root_fixed(os.lstat(self.catalog), kind=stat.S_IFREG)
        pending = [self.tree]
        _require_root_fixed(os.lstat(self.tree), kind=stat.S_IFDIR)
        while pending:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    info = os.lstat(entry.path)
                    if stat.S_ISDIR(info.st_mode):
                        _require_root_fixed(info, kind=stat.S_IFDIR)
                        pending.append(Path(entry.path))
                    else:
                        _require_root_fixed(info, kind=stat.S_IFREG)


@dataclass(frozen=True)
class NativeStoreMount:
    """One trusted native-only layout, never a caller-selected mount catalogue.

    Exactly two host objects reach the zone, both by descriptor so the object
    mounted is the object checked (M8-N4-state-review.md, section 1): the sealed
    configuration, read-only, and the store's one credential file, read/write
    for the vendor's in-place refresh. The binding owns its retained lock; the
    launcher rechecks it after its asynchronous probe. The egress leaf travels
    only with the native store, so no worker launch can carry it.
    """

    lock_fd: int
    configuration_fd: int
    credential_fd: int
    before_spawn: Callable[[], BindingCheck]
    egress: EgressSocket | None = None

    def __post_init__(self) -> None:
        fds = (self.lock_fd, self.configuration_fd, self.credential_fd)
        if any(type(fd) is not int or fd < 0 for fd in fds) or len(set(fds)) != len(fds):
            raise ContractViolation("the native store requires three distinct descriptors")

    @property
    def mount_fds(self) -> tuple[int, int]:
        """The descriptors bubblewrap itself must receive, in argv order."""

        return (self.configuration_fd, self.credential_fd)


_F_LINUX_SPECIFIC_BASE = 1024
_UAPI_SEALS = {
    # Linux UAPI include/uapi/linux/fcntl.h: F_ADD_SEALS and F_GET_SEALS are
    # F_LINUX_SPECIFIC_BASE + 9 and + 10; the seal bits are 1, 2, 4 and 8.
    "F_ADD_SEALS": _F_LINUX_SPECIFIC_BASE + 9,
    "F_GET_SEALS": _F_LINUX_SPECIFIC_BASE + 10,
    "F_SEAL_SEAL": 0x0001,
    "F_SEAL_SHRINK": 0x0002,
    "F_SEAL_GROW": 0x0004,
    "F_SEAL_WRITE": 0x0008,
}
_UAPI_MEMFD = {
    # Linux UAPI include/uapi/linux/memfd.h.
    "MFD_CLOEXEC": 0x0001,
    "MFD_ALLOW_SEALING": 0x0002,
}


def seal_constants(fcntl_module: object) -> tuple[int, int, int]:
    """``(F_ADD_SEALS, F_GET_SEALS, the four seals)``: the module's, else the UAPI's.

    Some CPython builds, including CI's uv-managed 3.11, omit the seal names. A
    wrong fallback cannot pass silently: :func:`sealed_data_fd` reads the seals
    back and refuses anything but exactly the four it applied.
    """

    value = {name: getattr(fcntl_module, name, uapi) for name, uapi in _UAPI_SEALS.items()}
    return value["F_ADD_SEALS"], value["F_GET_SEALS"], (
        value["F_SEAL_WRITE"] | value["F_SEAL_GROW"] | value["F_SEAL_SHRINK"]
        | value["F_SEAL_SEAL"]
    )


def memfd_flags(os_module: object) -> int:
    """``MFD_CLOEXEC | MFD_ALLOW_SEALING``: the module's, else the UAPI's."""

    return int(getattr(os_module, "MFD_CLOEXEC", _UAPI_MEMFD["MFD_CLOEXEC"])) | int(
        getattr(os_module, "MFD_ALLOW_SEALING", _UAPI_MEMFD["MFD_ALLOW_SEALING"]),
    )


def sealed_data_fd(data: bytes) -> int:
    """A sealed memfd holding exactly ``data``, positioned for bubblewrap's read.

    Sealing makes the content immutable before anything checks it, so the bytes
    verified here are the bytes ``--ro-bind-data`` copies into the zone. The
    seals are read back and must be exactly the four applied: an affirmative
    fact, never an assumption about which constants this build exposes.
    """

    if sys.platform != "linux":
        raise ContractViolation("sealed native configuration requires Linux")
    import fcntl

    if not hasattr(os, "memfd_create"):
        raise ContractViolation("this Python cannot create a memfd")
    add_seals, get_seals, seals = seal_constants(fcntl)
    fd = os.memfd_create("constructicon-native-data", memfd_flags(os))
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise ContractViolation("the sealed native data was not written")
            view = view[written:]
        fcntl.fcntl(fd, add_seals, seals)
        if fcntl.fcntl(fd, get_seals) != seals:
            raise ContractViolation("the native data is not sealed exactly as applied")
        if os.pread(fd, len(data) + 1, 0) != data:
            raise ContractViolation("the sealed native data differs from what was written")
        os.lseek(fd, 0, os.SEEK_SET)
    except BaseException:
        os.close(fd)
        raise
    return fd


class ProcessExchangeError(Exception):
    """A failed conversation with captured evidence after completed teardown."""

    def __init__(self, result: ProcessResult) -> None:
        super().__init__("contained process conversation failed")
        self.result = result


class _OwnedStop(ContractViolation):
    """An interrupted operation belongs to the owner's initiating stop cause."""


class _ProcessIO:
    def __init__(
        self, writer: asyncio.StreamWriter, output: bytearray, input_limit: int,
    ) -> None:
        self._writer = writer
        self._output = output
        self.input_limit = input_limit
        self.spent = 0
        self.offset = 0
        self.changed = asyncio.Event()
        self.eof = False
        self.active = True
        self.stopping = False
        self.stdin_closed = False
        self.reading = False
        self.writing = False
        self._draining: asyncio.Future[None] | None = None
        self._interrupted_drain: asyncio.Future[None] | None = None

    def require_active(self) -> None:
        if self.stopping:
            raise _OwnedStop("process conversation is closed")
        if not self.active:
            raise ContractViolation("process conversation is closed")

    def invalidate(self, *, stopping: bool = False) -> None:
        if (
            stopping and not self.stopping and self._draining is not None
            and not self._draining.done()
        ):
            self._interrupted_drain = self._draining
        self.stopping |= stopping
        self.active = False
        self.stdin_closed = True
        self.changed.set()
        self._writer.close()

    async def write(self, data: bytes) -> None:
        self.require_active()
        if self.writing or self.stdin_closed:
            raise ContractViolation("process stdin is closed or has a pending writer")
        if not isinstance(data, bytes) or len(data) > self.input_limit - self.spent:
            raise ContractViolation("process write exceeds the cumulative input budget")
        self.spent += len(data)
        self.writing = True
        try:
            for offset in range(0, len(data), 8192):
                self.require_active()
                self._writer.write(data[offset:offset + 8192])
                self._draining = asyncio.ensure_future(self._writer.drain())
                try:
                    await asyncio.shield(self._draining)
                except asyncio.CancelledError:
                    # A settled failure predates this cancellation. Shielding
                    # keeps it intact even if its waiter has not resumed yet.
                    if self._draining.done() and not self._draining.cancelled():
                        self._draining.result()
                    self._draining.cancel()
                    await asyncio.gather(self._draining, return_exceptions=True)
                    raise
                self.require_active()
        except OSError as exc:
            if self._draining is not None and self._draining is self._interrupted_drain:
                raise _OwnedStop from exc
            raise
        except asyncio.CancelledError as exc:
            if self.stopping:
                raise _OwnedStop from exc
            raise
        finally:
            self._draining = None
            self.writing = False

    async def read(self, maximum: int = 8192) -> bytes:
        self.require_active()
        if type(maximum) is not int or not 1 <= maximum <= 8192 or self.reading:
            raise ContractViolation("process read requires one reader and a bound in 1..8192")
        self.reading = True
        try:
            while self.offset == len(self._output) and not self.eof:
                self.changed.clear()
                await self.changed.wait()
                self.require_active()
            end = min(len(self._output), self.offset + maximum)
            data = bytes(self._output[self.offset:end])
            self.offset = end
            return data
        except asyncio.CancelledError as exc:
            if self.stopping:
                raise _OwnedStop from exc
            raise
        finally:
            self.reading = False

    async def close_stdin(self) -> None:
        self.require_active()
        if self.writing:
            raise ContractViolation("process stdin has a pending writer")
        self.stdin_closed = True
        self._writer.close()


@dataclass(frozen=True, kw_only=True)
class LinuxLauncher:
    """A trusted assembly binds exact artifacts before any acquired call."""

    runtime_root: Path
    expected_runtime: Digest
    bubblewrap: Path
    policy: Path
    expected_policy_sha256: str
    limits: ProcessLimits = DEFAULT_PROCESS_LIMITS
    vendor: NativeVendor | None = None

    @property
    def root(self) -> Path:
        return self.runtime_root

    def check_artifacts(self) -> None:
        if sys.platform != "linux" or os.getuid() == 0:
            raise ContractViolation("Linux containment requires a non-root Linux service user")
        for path in (self.bubblewrap, self.policy, self.root):
            require_fixed_artifact(path)
        if self.vendor is not None:
            self.vendor.check()
        if _sha(self.bubblewrap) != BWRAP_SHA256:
            raise ContractViolation("bubblewrap content differs from the supported build")
        if _sha(self.policy) != self.expected_policy_sha256:
            raise ContractViolation("launch policy content changed")
        if runtime_digest(self.root) != self.expected_runtime:
            raise ContractViolation("runtime content differs from the admitted identity")
        restriction = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
        if restriction.read_text().strip() != "1":
            raise ContractViolation("the required AppArmor user-namespace restriction is absent")

    @property
    def revision(self) -> Digest:
        return digest("linux-launch", 1, {
            "runtime": self.expected_runtime,
            "bubblewrap": BWRAP_SHA256,
            "recipe": _sha(Path(__file__)),
            "io_contract": digest("process-io-contract", 1, inspect.getsource(ProcessIO)),
            "lifetime": digest("owned-lifetime", 1, inspect.getsource(finish_owned)),
            "policy": self.expected_policy_sha256,
            "limits": asdict(self.limits),
            "vendor": None if self.vendor is None else [
                str(self.vendor.tree), str(self.vendor.catalog),
            ],
        })

    def argv(
        self, command: tuple[str, ...], *, workspace: Path | None, posture: Posture,
        native_store: NativeStoreMount | None = None,
    ) -> list[str]:
        if sys.platform != "linux":
            raise ContractViolation("contained command construction requires Linux")
        if not command or not command[0].startswith("/") or any("\0" in item for item in command):
            raise ContractViolation("contained command requires a fixed absolute executable")
        if native_store is not None and workspace is not None:
            raise ContractViolation("a native store and worker workspace cannot share a namespace")
        args = [
            str(self.bubblewrap), "--unshare-user", "--unshare-pid", "--unshare-ipc",
            "--unshare-uts", "--unshare-net", "--new-session", "--die-with-parent",
            "--cap-drop", "ALL", "--uid", str(os.getuid()), "--gid", str(os.getgid()),
            "--clearenv", "--ro-bind", str(self.root), "/", "--proc", "/proc",
            "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/tmp/home",
            "--setenv", "HOME", "/tmp/home", "--setenv", "PATH", "/usr/bin:/bin",
            "--setenv", "LANG", "C.UTF-8",
        ]
        if workspace is not None:
            args += [
                "--ro-bind" if posture is Posture.READ else "--bind",
                str(workspace), "/workspace",
            ]
        if native_store is not None:
            args += [
                "--dir", NATIVE_HOME,
                "--ro-bind-data", str(native_store.configuration_fd), f"{NATIVE_HOME}/config.toml",
                "--bind-fd", str(native_store.credential_fd), f"{NATIVE_HOME}/{CREDENTIAL_FILE}",
                "--setenv", "CODEX_HOME", NATIVE_HOME,
            ]
            if self.vendor is not None:
                # Checked in ``check_artifacts`` on this launch's probe.
                args += [
                    "--ro-bind", str(self.vendor.tree), VENDOR_MOUNT,
                    "--ro-bind", str(self.vendor.catalog), CATALOG_MOUNT,
                ]
            if native_store.egress is not None:
                native_store.egress.require_current()
                args += ["--ro-bind", str(native_store.egress.path), ZONE_SOCKET]
                # The proxy bridge travels only with the leaf (M8-N4-proxy-bridge.md).
                command = ("/usr/bin/python3", "-I", BRIDGE_SCRIPT, *command)
        args += ["--chdir", "/workspace" if workspace is not None else "/tmp", "--", *command]
        return args

    async def run(
        self,
        command: tuple[str, ...],
        *,
        workspace: Path | None,
        posture: Posture,
        guard_fds: tuple[int, ...],
        stdin: bytes = b"",
        input_kind: Literal["task", "artifact"] = "task",
        timeout_s: float,
    ) -> ProcessResult:
        """The caller holds and validates the acquisition before entering here."""

        limit = self.limits.artifact_bytes if input_kind == "artifact" else self.limits.input_bytes
        return await self._launch(
            command, workspace=workspace, posture=posture, guard_fds=guard_fds,
            stdin=stdin, input_limit=limit, conversation=None, timeout_s=timeout_s,
        )

    async def exchange(
        self, command: tuple[str, ...], *, workspace: Path | None, posture: Posture,
        guard_fds: tuple[int, ...], conversation: Conversation, timeout_s: float,
        native_store: NativeStoreMount | None = None,
    ) -> ProcessResult:
        """Exchange bytes within the same owned, networkless process lifetime."""

        return await self._launch(
            command, workspace=workspace, posture=posture, guard_fds=guard_fds,
            stdin=b"", input_limit=self.limits.input_bytes,
            conversation=conversation, timeout_s=timeout_s, native_store=native_store,
        )

    async def _launch(
        self, command: tuple[str, ...], *, workspace: Path | None, posture: Posture,
        guard_fds: tuple[int, ...], stdin: bytes, input_limit: int,
        conversation: Conversation | None, timeout_s: float,
        native_store: NativeStoreMount | None = None,
    ) -> ProcessResult:

        started = time.monotonic()
        deadline = asyncio.get_running_loop().time() + timeout_s
        if len(stdin) > input_limit or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ContractViolation("contained input/deadline exceeds the launch contract")
        try:
            async with asyncio.timeout_at(deadline):
                await self.probe(deadline=deadline)
        except TimeoutError:
            return ProcessResult(125, b"", b"", time.monotonic() - started, timed_out=True)
        try:
            result = await self._run(
                command, workspace=workspace, posture=posture, guard_fds=guard_fds,
                stdin=stdin, deadline=deadline, input_limit=input_limit, conversation=conversation,
                native_store=native_store,
            )
        except ProcessExchangeError as exc:
            exc.result = replace(exc.result, elapsed_s=time.monotonic() - started)
            raise
        return replace(result, elapsed_s=time.monotonic() - started)

    async def probe(self, *, deadline: float | None = None) -> None:
        """Benign, mount-free prerequisite proof through the identical recipe.

        An anonymous lifetime fd is not a persistent pre-record allocation.
        No cached boolean can skip the next launch's physical recheck.
        """

        if deadline is None:
            deadline = asyncio.get_running_loop().time() + 10
        # Hashing trusted artifacts must not stall heartbeats. Join the read-only
        # worker before propagating expiry/cancellation; it can never launch work.
        await finish_owned(asyncio.create_task(asyncio.to_thread(self.check_artifacts)))
        if sys.platform != "linux":
            raise ContractViolation("physical launch probes require Linux")
        fd = os.memfd_create("constructicon-availability", os.MFD_CLOEXEC)
        try:
            result = await self._run(
                ("/usr/bin/python3", "-I", "-c", _PROBE), workspace=None,
                posture=Posture.READ, guard_fds=(fd,),
                deadline=deadline,
            )
        finally:
            os.close(fd)
        if result.timed_out:
            raise TimeoutError("the physical Linux launch probe expired")
        if result.returncode or result.bound_exceeded:
            raise ContractViolation("the physical Linux launch probe failed")
        try:
            facts = json.loads(result.stdout)
            correct = (
                facts["profile"] == "constructicon-m8-launch//&constructicon-m8-workload (enforce)"
                and facts["nested_denied"] and facts["sys_absent"]
                and "NoNewPrivs:\t1" in facts["status"]
                and "CapEff:\t0000000000000000" in facts["status"]
                and all(
                    facts["namespaces"][name] != os.readlink(f"/proc/self/ns/{name}")
                    for name in ("user", "mnt", "pid", "ipc", "uts", "net")
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ContractViolation("the physical Linux launch probe is malformed") from exc
        if not correct:
            raise ContractViolation("the physical Linux launch probe contradicts containment")

    async def _run(
        self, command: tuple[str, ...], *, workspace: Path | None, posture: Posture,
        guard_fds: tuple[int, ...], stdin: bytes = b"", deadline: float,
        input_limit: int | None = None, conversation: Conversation | None = None,
        native_store: NativeStoreMount | None = None,
    ) -> ProcessResult:
        if sys.platform != "linux":
            raise ContractViolation("contained process ownership requires Linux")
        if not guard_fds or len(set(guard_fds)) != len(guard_fds):
            raise ContractViolation("contained work requires its distinct acquisition guards")
        if asyncio.get_running_loop().time() >= deadline:
            return ProcessResult(125, b"", b"", 0, timed_out=True)
        args = self.argv(
            command, workspace=workspace, posture=posture, native_store=native_store,
        )
        if native_store is not None:
            if native_store.lock_fd not in guard_fds:
                raise ContractViolation("the native store requires its retained supervisor guard")
            if set(native_store.mount_fds) & set(guard_fds):
                raise ContractViolation("a native mount descriptor cannot also be a guard")
            checked = native_store.before_spawn()
            if not isinstance(checked, BindingCheck):
                raise ContractViolation("the native store did not complete its binding check")
        # Only bubblewrap consumes these; the supervisor passes them through.
        mount_fds = native_store.mount_fds if native_store is not None else ()
        mount_argument = (
            (f"--mount-fds={','.join(str(fd) for fd in mount_fds)}",) if mount_fds else ()
        )
        # asyncio may use another clock origin; the child needs Linux's shared
        # monotonic clock, with only the already-remaining budget transferred.
        child_deadline = time.monotonic() + (deadline - asyncio.get_running_loop().time())
        owner_read, owner_write = os.pipe()
        report_read, report_write = os.pipe()
        os.set_blocking(report_read, False)
        process: asyncio.subprocess.Process | None = None
        started = time.monotonic()
        stdout = bytearray()
        stderr_head = bytearray()
        stderr_tail = bytearray()
        raw_report = b""
        bound: str | None = None
        timed_out = False
        tasks: list[asyncio.Task[None]] = []
        completion: asyncio.Task[None] | None = None
        protocol: asyncio.Task[None] | None = None
        channel: _ProcessIO | None = None
        stopped = asyncio.get_running_loop().create_future()
        stop_reason: str | None = None
        errors: list[BaseException] = []
        cleanup_errors: list[BaseException] = []
        cancellation: asyncio.CancelledError | None = None
        protocol_observed = False

        def close_fd(fd: int) -> None:
            try:
                os.close(fd)
            except OSError as exc:
                cleanup_errors.append(exc)

        def remember(error: BaseException) -> None:
            if not any(error is old for old in errors):
                errors.append(error)

        def observe_protocol() -> None:
            nonlocal protocol_observed
            if protocol is None or not protocol.done() or protocol_observed:
                return
            protocol_observed = True
            try:
                protocol.result()
            except BaseException as exc:
                if stop_reason is not None and isinstance(
                    exc, (_OwnedStop, asyncio.CancelledError),
                ):
                    return
                remember(exc)

        def stop(reason: str = "complete") -> None:
            nonlocal owner_write, stop_reason
            initiating = stop_reason is None
            if initiating:
                observe_protocol()
                stop_reason = reason
            try:
                if channel is not None:
                    channel.invalidate(stopping=True)
            finally:
                if owner_write >= 0:
                    fd, owner_write = owner_write, -1
                    close_fd(fd)
                if initiating and protocol is not None and not protocol.done():
                    protocol.cancel()
                if not stopped.done():
                    stopped.set_result(None)

        async def capture(stream: asyncio.StreamReader, *, output: bool) -> None:
            nonlocal bound
            line_bytes = 0
            while True:
                # Owner shutdown yields EOF here, not permission to discard
                # independent failures: the read transport is never cancelled.
                chunk = await stream.read(8192)
                if not chunk:
                    break
                if output:
                    room = max(0, self.limits.stdout_bytes - len(stdout))
                    stdout.extend(chunk[:room])
                    if len(chunk) > room:
                        bound = bound or "stdout"
                    pieces = chunk.split(b"\n")
                    for index, piece in enumerate(pieces):
                        line_bytes += len(piece)
                        if line_bytes > self.limits.record_bytes:
                            bound = bound or "record"
                        if index < len(pieces) - 1:
                            line_bytes = 0
                    if bound:
                        stop("bound")
                    if channel is not None:
                        channel.changed.set()
                else:
                    half = self.limits.stderr_bytes // 2
                    room = max(0, half - len(stderr_head))
                    stderr_head.extend(chunk[:room])
                    stderr_tail.extend(chunk[room:])
                    del stderr_tail[:max(0, len(stderr_tail) - (self.limits.stderr_bytes - half))]
            if output and channel is not None:
                channel.eof = True
                channel.changed.set()

        async def drain(stream: asyncio.StreamReader, *, output: bool) -> None:
            try:
                await capture(stream, output=output)
            except BaseException as exc:
                remember(exc)
                stop("failure")

        async def converse() -> None:
            assert channel is not None
            try:
                if conversation is not None:
                    await conversation(channel)
                else:
                    # Historical batch delivery may end at peer EOF.
                    with suppress(BrokenPipeError, ConnectionResetError):
                        await channel.write(stdin)
            finally:
                channel.invalidate()

        async def finish() -> None:
            if process is not None:
                await process.wait()
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                failed = [result for result in results if isinstance(result, BaseException)]
                if failed:
                    raise BaseExceptionGroup("contained pipe drain failed", failed)

        try:
            # Shield spawn so cancellation cannot discard a successfully created
            # supervisor handle. Its private pipe also covers owner death here.
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                str(self.root / "lib64/ld-linux-x86-64.so.2"),
                "--library-path",
                f"{self.root}/lib/x86_64-linux-gnu:{self.root}/usr/lib/x86_64-linux-gnu",
                str(self.root / "usr/bin/python3.12"), "-I", str(self.root / SUPERVISOR_PATH),
                str(owner_read), ",".join(str(fd) for fd in guard_fds),
                str(child_deadline), f"--report-fd={report_write}", *mount_argument, *args,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, close_fds=True,
                pass_fds=(owner_read, report_write, *guard_fds, *mount_fds),
                env={"LANG": "C.UTF-8"},
            ))
            try:
                async with asyncio.timeout_at(deadline):
                    process = await asyncio.shield(spawn)
            except TimeoutError:
                timed_out = True
                stop("deadline")
            except asyncio.CancelledError as exc:
                cancellation = cancellation or exc
                stop("cancel")
            while True:
                try:
                    process = await asyncio.shield(spawn)
                    break
                except asyncio.CancelledError as exc:
                    cancellation = cancellation or exc
                    stop()
            assert process.stdin is not None and process.stdout is not None
            assert process.stderr is not None
            channel = _ProcessIO(
                process.stdin, stdout,
                self.limits.input_bytes if input_limit is None else input_limit,
            )
            tasks = [
                asyncio.create_task(drain(process.stdout, output=True)),
                asyncio.create_task(drain(process.stderr, output=False)),
            ]
            if cancellation is not None:
                raise cancellation
            if stop_reason is None:
                protocol = asyncio.create_task(converse())
            if owner_write >= 0:
                # Refused/expired setup retains its observable exit status.
                with suppress(BrokenPipeError):
                    os.write(owner_write, b"\x01")
            completion = asyncio.create_task(finish())
            try:
                async with asyncio.timeout_at(deadline):
                    if protocol is not None:
                        await asyncio.wait((protocol, stopped), return_when=asyncio.FIRST_COMPLETED)
                        observe_protocol()
                        if errors:
                            stop("failure")
                    await asyncio.shield(completion)
            except TimeoutError:
                timed_out = True
                stop("deadline")
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
        except BaseException as exc:
            remember(exc)
        finally:
            close_fd(owner_read)
            try:
                stop("cancel" if cancellation is not None else "failure" if errors else "complete")
            except BaseException as exc:
                cleanup_errors.append(exc)
            cleanup = completion or asyncio.create_task(finish())
            try:
                try:
                    await finish_owned(cleanup)
                except asyncio.CancelledError as exc:
                    cancellation = cancellation or exc
                except BaseException as exc:
                    cleanup_errors.append(exc)
                if protocol is not None:
                    async def join_protocol() -> None:
                        await asyncio.gather(protocol, return_exceptions=True)

                    try:
                        await finish_owned(asyncio.create_task(join_protocol()))
                    except asyncio.CancelledError as exc:
                        cancellation = cancellation or exc
                    except BaseException as exc:
                        cleanup_errors.append(exc)
                    observe_protocol()
                with suppress(BlockingIOError):
                    raw_report = os.read(report_read, 5)
            except BaseException as exc:
                cleanup_errors.append(exc)
            finally:
                close_fd(report_read)
                close_fd(report_write)
        payload_returncode = None
        try:
            if len(raw_report) == 4:
                payload_returncode = struct.unpack("!i", raw_report)[0]
                if not 0 <= payload_returncode <= 255:
                    raise ContractViolation("invalid private payload exit report")
            elif raw_report:
                raise ContractViolation("malformed private payload exit report")
        except BaseException as exc:
            cleanup_errors.append(exc)
        if cleanup_errors:
            failures = [*errors, *cleanup_errors]
            if cancellation is not None:
                failures.insert(0, cancellation)
            if len(failures) == 1:
                raise failures[0]
            raise BaseExceptionGroup("contained process cleanup failed", failures)
        if cancellation is not None:
            if errors:
                raise cancellation from BaseExceptionGroup("conversation failed", errors)
            raise cancellation
        if process is None:
            assert errors
            raise errors[0]
        assert process is not None and process.returncode is not None
        result = ProcessResult(
            process.returncode, bytes(stdout), bytes(stderr_head + stderr_tail),
            time.monotonic() - started, timed_out or asyncio.get_running_loop().time() >= deadline,
            bound, payload_returncode,
        )
        if errors:
            failure = (
                errors[0] if len(errors) == 1 else BaseExceptionGroup("conversation failed", errors)
            )
            if conversation is not None:
                raise ProcessExchangeError(result) from failure
            raise failure
        return result
