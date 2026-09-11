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
from constructicon.substrate.executors._supervisor import NAMESPACE_SCRIPT

SUPERVISOR_PATH = Path(NAMESPACE_SCRIPT.removeprefix("/"))
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

    def require_active(self) -> None:
        if self.stopping:
            raise _OwnedStop("process conversation is closed")
        if not self.active:
            raise ContractViolation("process conversation is closed")

    def invalidate(self, *, stopping: bool = False) -> None:
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
                await self._writer.drain()
                self.require_active()
        except (OSError, asyncio.CancelledError) as exc:
            if self.stopping:
                raise _OwnedStop from exc
            raise
        finally:
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

    @property
    def root(self) -> Path:
        return self.runtime_root

    def check_artifacts(self) -> None:
        if sys.platform != "linux" or os.getuid() == 0:
            raise ContractViolation("Linux containment requires a non-root Linux service user")
        for path in (self.bubblewrap, self.policy, self.root):
            require_fixed_artifact(path)
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

        limit = self.limits.artifact_bytes if input_kind == "artifact" else self.limits.input_bytes
        return await self._launch(
            command, workspace=workspace, posture=posture, guard_fds=guard_fds,
            stdin=stdin, input_limit=limit, conversation=None, timeout_s=timeout_s,
        )

    async def exchange(
        self, command: tuple[str, ...], *, workspace: Path | None, posture: Posture,
        guard_fds: tuple[int, ...], conversation: Conversation, timeout_s: float,
    ) -> ProcessResult:
        """Exchange bytes within the same owned, networkless process lifetime."""

        return await self._launch(
            command, workspace=workspace, posture=posture, guard_fds=guard_fds,
            stdin=b"", input_limit=self.limits.input_bytes,
            conversation=conversation, timeout_s=timeout_s,
        )

    async def _launch(
        self, command: tuple[str, ...], *, workspace: Path | None, posture: Posture,
        guard_fds: tuple[int, ...], stdin: bytes, input_limit: int,
        conversation: Conversation | None, timeout_s: float,
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
    ) -> ProcessResult:
        if sys.platform != "linux":
            raise ContractViolation("contained process ownership requires Linux")
        if not guard_fds or len(set(guard_fds)) != len(guard_fds):
            raise ContractViolation("contained work requires its distinct acquisition guards")
        if asyncio.get_running_loop().time() >= deadline:
            return ProcessResult(125, b"", b"", 0, timed_out=True)
        args = self.argv(command, workspace=workspace, posture=posture)
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
        caller_cancelled = False
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
                try:
                    chunk = await stream.read(8192)
                except OSError:
                    if stop_reason is not None:
                        return  # This pending pipe operation was stopped by its owner.
                    raise
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
                str(child_deadline), f"--report-fd={report_write}", *args,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, close_fds=True,
                pass_fds=(owner_read, report_write, *guard_fds), env={"LANG": "C.UTF-8"},
            ))
            cancelled = False
            try:
                async with asyncio.timeout_at(deadline):
                    process = await asyncio.shield(spawn)
            except TimeoutError:
                timed_out = True
                stop("deadline")
            except asyncio.CancelledError:
                cancelled = True
                stop("cancel")
            while True:
                try:
                    process = await asyncio.shield(spawn)
                    break
                except asyncio.CancelledError:
                    cancelled = True
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
            if cancelled:
                raise asyncio.CancelledError
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
        except asyncio.CancelledError:
            caller_cancelled = True
        except BaseException as exc:
            remember(exc)
        finally:
            close_fd(owner_read)
            try:
                stop("cancel" if caller_cancelled else "failure" if errors else "complete")
            except BaseException as exc:
                cleanup_errors.append(exc)
            cleanup = completion or asyncio.create_task(finish())
            try:
                try:
                    await finish_owned(cleanup)
                except asyncio.CancelledError:
                    caller_cancelled = True
                except BaseException as exc:
                    cleanup_errors.append(exc)
                if protocol is not None:
                    async def join_protocol() -> None:
                        await asyncio.gather(protocol, return_exceptions=True)

                    try:
                        await finish_owned(asyncio.create_task(join_protocol()))
                    except asyncio.CancelledError:
                        caller_cancelled = True
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
            if caller_cancelled:
                failures.insert(0, asyncio.CancelledError())
            if len(failures) == 1:
                raise failures[0]
            raise BaseExceptionGroup("contained process cleanup failed", failures)
        if caller_cancelled:
            if errors:
                raise asyncio.CancelledError from BaseExceptionGroup("conversation failed", errors)
            raise asyncio.CancelledError
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
