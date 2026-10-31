"""Fixed contained Python WRITE worker; no native/vendor authority."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import canonical_json
from constructicon.core.qualification_write import WorkerResultCategory
from constructicon.core.workspace import LeaseContext, WorkspaceView
from constructicon.substrate.executors.claude_read_worker import _ClaudeWorkspaceWorker
from constructicon.substrate.executors.codex_protocol import (
    TOOL_OUTPUT_BYTES as WRITE_OUTPUT_BYTES,
)
from constructicon.substrate.executors.codex_protocol import (
    TOOL_PROGRAM_BYTES as WRITE_PROGRAM_BYTES,
)
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessLimits, ProcessResult
from constructicon.substrate.git.capture import (
    ContainedWriteWorkspace,
    ContainedWriteWorkspaceProvider,
)
from constructicon.substrate.git.contained import ContainedWorkspace

__all__ = [
    "WRITE_OUTPUT_BYTES", "WRITE_PROGRAM_BYTES", "WRITE_WORKER_COMMAND", "WRITE_WORKER_LIMITS",
    "ClaudeWriteWorker", "validate_write_program",
]

WRITE_WORKER_COMMAND = ("/usr/bin/python3", "-I", "-c", "import sys; exec(sys.stdin.read())")
WRITE_WORKER_LIMITS = ProcessLimits(
    input_bytes=WRITE_PROGRAM_BYTES, artifact_bytes=1, stdout_bytes=WRITE_OUTPUT_BYTES,
    record_bytes=WRITE_OUTPUT_BYTES, stderr_bytes=1024,
)


def validate_write_program(value: object) -> bool:
    """Program bytes are bounded task data, never a host executable selector."""
    if type(value) is not str:
        return False
    try:
        return len(value.encode("utf-8")) <= WRITE_PROGRAM_BYTES
    except UnicodeError:
        return False


class ClaudeWriteWorker(_ClaudeWorkspaceWorker):
    """Sequential WRITE execution sharing READ's owned join and resume law."""

    _posture = Posture.WRITE
    _limits = WRITE_WORKER_LIMITS
    _provider_kind = ContainedWriteWorkspaceProvider
    _name = "Claude WRITE"

    def __init__(
        self, *, provider: ContainedWriteWorkspaceProvider, context: LeaseContext,
        workspace: WorkspaceView, launcher: LinuxLauncher,
        observe_result: Callable[[WorkerResultCategory], None] | None = None,
    ) -> None:
        def observed(result: ProcessResult) -> None:
            if observe_result is not None:
                observe_result(_result_category(result))

        super().__init__(provider=provider, context=context, workspace=workspace,
                         launcher=launcher, observe_result=observed)

    def _owned(self) -> ContainedWorkspace:
        owned = _ClaudeWorkspaceWorker._owned(self)
        actual = owned.context
        provider = cast(ContainedWriteWorkspaceProvider, self._provider)
        if (type(owned) is not ContainedWriteWorkspace
                or actual.binding.revision != provider.revision
                or canonical_json(actual.binding.effective_grants)
                != canonical_json(self._context.binding.effective_grants)
                or actual.check_control is None or self._context.check_control is None):
            raise ContractViolation("Claude WRITE requires its exact admitted workspace grants")
        return owned

    def _input(self, argument: str) -> tuple[tuple[str, ...], bytes]:
        if not validate_write_program(argument):
            raise ContractViolation("Claude WRITE worker arguments refused")
        return WRITE_WORKER_COMMAND, argument.encode("utf-8")


def _result_category(result: ProcessResult) -> WorkerResultCategory:
    """An actual process result is evidence; later custody is a separate fact."""
    if result.timed_out is True:
        return "timeout"
    if result.bound_exceeded is not None:
        return "output_bound"
    if (type(result.returncode) is not int or type(result.payload_returncode) is not int
            or result.payload_returncode != result.returncode or result.timed_out is not False
            or type(result.stdout) is not bytes or type(result.stderr) is not bytes):
        return "incomplete"
    if result.returncode != 0:
        return "nonzero"
    if (len(result.stdout) > WRITE_WORKER_LIMITS.stdout_bytes
            or len(result.stderr) > WRITE_WORKER_LIMITS.stderr_bytes):
        return "output_bound"
    try:
        result.stdout.decode("utf-8", errors="strict")
    except UnicodeError:
        return "invalid_utf8"
    return "success"
