"""One concrete, networkless Linux launch recipe and bounded subprocess pump.

Backend adapters and contained Git/gates consume this boundary; it knows no
models, command journal, lease disposition, or graph scheduling. Provisioning
is an operator action, never an import or runtime fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import stat
import sys
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest, digest
from constructicon.substrate._lifetime import finish_owned

SUPERVISOR_PATH = Path("usr/libexec/constructicon-supervisor.py")
BWRAP_SHA256 = "52231e1caf55bcbc667b269f49c63599a6f7db4767ae6a039580d0ff853db712"
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


DEFAULT_PROCESS_LIMITS = ProcessLimits()


@dataclass(frozen=True, kw_only=True)
class LinuxLauncher:
    """A trusted assembly binds exact artifacts before any acquired call."""

    runtime_root: Path
    expected_runtime: Digest
    bubblewrap: Path
    policy: Path
    expected_policy_sha256: str
    limits: ProcessLimits = DEFAULT_PROCESS_LIMITS

    @property
    def root(self) -> Path:
        return self.runtime_root

    def check_artifacts(self) -> None:
        if sys.platform != "linux" or os.getuid() == 0:
            raise ContractViolation("Linux containment requires a non-root Linux service user")
        for path in (self.bubblewrap, self.policy, self.root):
            info = path.stat()
            if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o6022:
                raise ContractViolation("launcher artifacts must be fixed root-owned files")
            for parent in path.parents:
                info = parent.stat()
                if info.st_uid != 0 or info.st_mode & 0o022:
                    raise ContractViolation(f"launcher ancestor {parent} must be root-owned")
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
            "policy": self.expected_policy_sha256,
            "limits": asdict(self.limits),
        })

    def argv(
        self, command: tuple[str, ...], *, workspace: Path | None, posture: Posture,
    ) -> list[str]:
        if sys.platform != "linux":
            raise ContractViolation("contained command construction requires Linux")
        if not command or not command[0].startswith("/") or any("\0" in item for item in command):
            raise ContractViolation("contained command requires a fixed absolute executable")
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

        started = time.monotonic()
        deadline = asyncio.get_running_loop().time() + timeout_s
        limit = self.limits.artifact_bytes if input_kind == "artifact" else self.limits.input_bytes
        if len(stdin) > limit or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ContractViolation("contained input/deadline exceeds the launch contract")
        try:
            async with asyncio.timeout_at(deadline):
                await self.probe(deadline=deadline)
        except TimeoutError:
            return ProcessResult(125, b"", b"", time.monotonic() - started, timed_out=True)
        result = await self._run(
            command, workspace=workspace, posture=posture, guard_fds=guard_fds,
            stdin=stdin, deadline=deadline,
        )
        return replace(result, elapsed_s=time.monotonic() - started)

    async def probe(self, *, deadline: float | None = None) -> None:
        """Benign, mount-free prerequisite proof through the identical recipe.

        An anonymous lifetime fd is not a persistent pre-record allocation.
        No cached boolean can skip the next launch's physical recheck.
        """

        if deadline is None:
            deadline = asyncio.get_running_loop().time() + 10
        self.check_artifacts()
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
    ) -> ProcessResult:
        if not guard_fds or len(set(guard_fds)) != len(guard_fds):
            raise ContractViolation("contained work requires its distinct acquisition guards")
        if asyncio.get_running_loop().time() >= deadline:
            return ProcessResult(125, b"", b"", 0, timed_out=True)
        args = self.argv(command, workspace=workspace, posture=posture)
        # asyncio may use another clock origin; the child needs Linux's shared
        # monotonic clock, with only the already-remaining budget transferred.
        child_deadline = time.monotonic() + (deadline - asyncio.get_running_loop().time())
        owner_read, owner_write = os.pipe()
        process: asyncio.subprocess.Process | None = None
        started = time.monotonic()
        stdout = bytearray()
        stderr_head = bytearray()
        stderr_tail = bytearray()
        bound: str | None = None
        timed_out = False
        tasks: list[asyncio.Task[None]] = []
        completion: asyncio.Task[None] | None = None

        def stop() -> None:
            nonlocal owner_write
            if owner_write >= 0:
                os.close(owner_write)
                owner_write = -1

        async def drain(stream: asyncio.StreamReader, *, output: bool) -> None:
            nonlocal bound
            line_bytes = 0
            while chunk := await stream.read(8192):
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
                        stop()
                else:
                    half = self.limits.stderr_bytes // 2
                    room = max(0, half - len(stderr_head))
                    stderr_head.extend(chunk[:room])
                    stderr_tail.extend(chunk[room:])
                    del stderr_tail[:max(0, len(stderr_tail) - (self.limits.stderr_bytes - half))]

        async def feed(stream: asyncio.StreamWriter) -> None:
            try:
                for offset in range(0, len(stdin), 8192):
                    stream.write(stdin[offset:offset + 8192])
                    await stream.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                stream.close()

        async def finish() -> None:
            if process is not None:
                await process.wait()
            if tasks:
                await asyncio.gather(*tasks)

        try:
            # Shield spawn so cancellation cannot discard a successfully created
            # supervisor handle. Its private pipe also covers owner death here.
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                str(self.root / "lib64/ld-linux-x86-64.so.2"),
                "--library-path",
                f"{self.root}/lib/x86_64-linux-gnu:{self.root}/usr/lib/x86_64-linux-gnu",
                str(self.root / "usr/bin/python3.12"), "-I", str(self.root / SUPERVISOR_PATH),
                str(owner_read), ",".join(str(fd) for fd in guard_fds),
                str(child_deadline), *args,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, close_fds=True,
                pass_fds=(owner_read, *guard_fds), env={"LANG": "C.UTF-8"},
            ))
            cancelled = False
            try:
                async with asyncio.timeout_at(deadline):
                    process = await asyncio.shield(spawn)
            except TimeoutError:
                timed_out = True
                stop()
            except asyncio.CancelledError:
                cancelled = True
                stop()
            while True:
                try:
                    process = await asyncio.shield(spawn)
                    break
                except asyncio.CancelledError:
                    cancelled = True
                    stop()
            assert process.stdin is not None and process.stdout is not None
            assert process.stderr is not None
            tasks = [
                asyncio.create_task(feed(process.stdin)),
                asyncio.create_task(drain(process.stdout, output=True)),
                asyncio.create_task(drain(process.stderr, output=False)),
            ]
            if cancelled:
                raise asyncio.CancelledError
            if owner_write >= 0:
                # Refused/expired setup retains its observable exit status.
                with suppress(BrokenPipeError):
                    os.write(owner_write, b"\x01")
            completion = asyncio.create_task(finish())
            try:
                async with asyncio.timeout_at(deadline):
                    await asyncio.shield(completion)
            except TimeoutError:
                timed_out = True
        finally:
            os.close(owner_read)
            stop()
            cleanup = completion or asyncio.create_task(finish())
            await finish_owned(cleanup)
        assert process is not None and process.returncode is not None
        return ProcessResult(
            process.returncode, bytes(stdout), bytes(stderr_head + stderr_tail),
            time.monotonic() - started,
            timed_out or asyncio.get_running_loop().time() >= deadline, bound,
        )
