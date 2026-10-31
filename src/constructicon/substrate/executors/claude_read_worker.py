"""One fixed file reader composed with existing READ workspace custody.

No native/vendor process, provider availability or physical qualification lives
here. The launcher supplies the networkless boundary; portable doubles test
only this controller. The acquisition owner retains disposal responsibility.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import textwrap
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import ClassVar

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.workspace import LeaseContext, WorkspaceView
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessLimits, ProcessResult
from constructicon.substrate.git.contained import ContainedWorkspace, ContainedWorkspaceProvider

PATH_BYTES = 1024
READ_BYTES = 64 * 1024
READ_WORKER_LIMITS = ProcessLimits(
    input_bytes=1, artifact_bytes=1, stdout_bytes=READ_BYTES,
    record_bytes=READ_BYTES, stderr_bytes=1024,
)


def validate_read_path(value: object) -> bool:
    """One relative POSIX path law, shared by host and fixed worker source."""
    if type(value) is not str or not value or value.startswith("/"):
        return False
    if any(character in value for character in ("\\", ":", "\x00")):
        return False
    try:
        if len(value.encode("utf-8")) > PATH_BYTES:
            return False
    except UnicodeError:
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


READ_PROGRAM = (
    "import os, stat, sys\n"
    f"PATH_BYTES = {PATH_BYTES}\nREAD_BYTES = {READ_BYTES}\n"
    + textwrap.dedent(inspect.getsource(validate_read_path))
    + """
def read():
    if len(sys.argv) != 2 or not validate_read_path(sys.argv[1]):
        raise ValueError('invalid path')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open('.', flags)
    leaf = None
    try:
        parts = sys.argv[1].split('/')
        for part in parts[:-1]:
            next_directory = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                       | os.O_CLOEXEC, dir_fd=directory)
        info = os.fstat(leaf)
        if not stat.S_ISREG(info.st_mode) or info.st_size > READ_BYTES:
            raise ValueError('not a bounded regular file')
        content = bytearray()
        while True:
            chunk = os.read(leaf, READ_BYTES + 1 - len(content))
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > READ_BYTES:
                raise ValueError('file grew beyond bound')
        bytes(content).decode('utf-8', errors='strict')
        sys.stdout.buffer.write(content)
        sys.stdout.buffer.flush()
    finally:
        if leaf is not None:
            os.close(leaf)
        os.close(directory)
try:
    read()
except (OSError, ValueError, UnicodeError):
    raise SystemExit(2)
"""
)


class _ClaudeWorkspaceWorker:
    """Private shared custody loop for the two fixed Claude worker recipes."""

    _posture: ClassVar[Posture] = Posture.READ
    _limits: ClassVar[ProcessLimits] = READ_WORKER_LIMITS
    _provider_kind: ClassVar[type[ContainedWorkspaceProvider]] = ContainedWorkspaceProvider
    _name: ClassVar[str] = "Claude READ"

    def __init__(
        self, *, provider: ContainedWorkspaceProvider, context: LeaseContext,
        workspace: WorkspaceView, launcher: LinuxLauncher,
        observe_result: Callable[[ProcessResult], None] | None = None,
    ) -> None:
        if (type(provider) is not self._provider_kind
                or type(context) is not LeaseContext or not isinstance(launcher, LinuxLauncher)):
            raise ContractViolation(f"{self._name} worker requires assembled workspace custody")
        self._provider, self._context = provider, context
        self._workspace, self._launcher = workspace, launcher
        self._observe_result = observe_result
        self._active = False
        self._poisoned = False
        self._owned()

    def _owned(self) -> ContainedWorkspace:
        if self._poisoned:
            raise ContractViolation(f"{self._name} worker is permanently refused")
        if (self._provider.posture is not self._posture or self._launcher.vendor is not None
                or self._launcher.claude is not None
                or self._launcher.limits != self._limits):
            raise ContractViolation(f"{self._name} worker requires its fixed networkless launcher")
        owned = self._provider.owned_view(self._workspace, self._context)
        if owned.context.run_lease.owner_id != self._context.run_lease.owner_id:
            raise ContractViolation(f"{self._name} workspace belongs to another lease owner")
        if self._context.check_control is not None:
            self._context.check_control()
        if owned.context.check_control is not None:
            owned.context.check_control()
        return owned

    async def _open(self, owned: ContainedWorkspace, deadline: float) -> None:
        self._owned()
        await finish_owned(asyncio.create_task(asyncio.to_thread(
            self._provider.closure.require_open, owned.paths,
        )))
        self._owned()
        # The thread may have observed absence before closure was published;
        # the authority transfer itself must not contain another await.
        self._provider.closure.require_open(owned.paths)
        if asyncio.get_running_loop().time() >= deadline:
            raise ContractViolation(f"{self._name} worker deadline expired")

    def _input(self, argument: str) -> tuple[tuple[str, ...], bytes]:
        raise NotImplementedError

    async def _run_process(self, task: asyncio.Task[ProcessResult]) -> ProcessResult:
        result: ProcessResult | None = None
        errors: list[BaseException] = []
        try:
            result = await asyncio.shield(task)
        except BaseException as primary:
            errors.append(primary)
            if not task.done():
                task.cancel()
            try:
                await finish_owned(task)
            except asyncio.CancelledError:
                pass
            except BaseException as cleanup:
                failure: BaseException | None
                if isinstance(cleanup, BaseExceptionGroup):
                    _, failure = cleanup.split(asyncio.CancelledError)
                else:
                    failure = cleanup if cleanup is not primary else None
                if failure is not None:
                    errors.append(failure)
        # A native-read race may cancel this owner after the process completed.
        # Observe its real result before later custody/output checks discard it.
        if result is None and task.done() and not task.cancelled():
            with suppress(BaseException):  # No process result is an unknown observation.
                result = task.result()
        if type(result) is ProcessResult and self._observe_result is not None:
            try:
                self._observe_result(result)
            except BaseException as observation:
                errors.append(observation)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("Claude worker failed while joining", errors) from None
        assert result is not None
        return result

    async def __call__(self, path: str, remaining_s: float) -> str:
        if self._active or self._poisoned:
            self._poisoned = True
            raise ContractViolation(f"{self._name} callbacks must remain sequential")
        self._active = True  # Reentry is visible before the first await.
        try:
            if (type(remaining_s) not in (int, float)
                    or not math.isfinite(remaining_s) or remaining_s <= 0):
                raise ContractViolation(f"{self._name} worker arguments refused")
            command, stdin = self._input(path)
            deadline = asyncio.get_running_loop().time() + remaining_s
            owned = self._owned()
            async with owned.use() as guard:
                await self._open(owned, deadline)
                task = asyncio.create_task(self._launcher.run(
                    command,
                    workspace=Path(owned.path), posture=self._posture, guard_fds=(guard,),
                    stdin=stdin, input_kind="task",
                    timeout_s=deadline - asyncio.get_running_loop().time(),
                ))
                result = await self._run_process(task)
                await self._open(owned, deadline)
                if (type(result) is not ProcessResult
                        or type(result.returncode) is not int or result.returncode != 0
                        or type(result.payload_returncode) is not int
                        or result.payload_returncode != 0
                        or result.timed_out is not False or result.bound_exceeded is not None
                        or type(result.stdout) is not bytes
                        or len(result.stdout) > self._limits.stdout_bytes
                        or type(result.stderr) is not bytes
                        or len(result.stderr) > self._limits.stderr_bytes):
                    raise ContractViolation(f"{self._name} worker process refused")
                try:
                    text = result.stdout.decode("utf-8", errors="strict")
                except UnicodeError:
                    raise ContractViolation(f"{self._name} worker output refused") from None
            # A guard-release await can observe closure/reentry after a clean
            # worker. Recheck before returning any workspace bytes.
            await self._open(owned, deadline)
            return text
        except BaseException:
            self._poisoned = True
            raise
        finally:
            self._active = False


class ClaudeReadWorker(_ClaudeWorkspaceWorker):
    """Sequential fixed reader; any interrupted/refused use poisons this owner."""

    def _input(self, argument: str) -> tuple[tuple[str, ...], bytes]:
        if not validate_read_path(argument):
            raise ContractViolation("Claude READ worker arguments refused")
        return ("/usr/bin/python3", "-I", "-c", READ_PROGRAM, argument), b""
