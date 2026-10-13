"""One owned Claude initialize transaction, never a full startup clearance.

Only fixed credential-free workers exercise this binding. No native store or
Claude launch recipe is supplied, no model request is possible, and local read
order/correlation cannot prove physical arrival freshness or vendor honesty.
The existing launcher owns the deadline, byte scope, process tree and joins.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.process import ProcessIO
from constructicon.substrate.executors.claude_protocol import (
    RECORD_BYTES,
    ClaudeInitializeVerdict,
    ClaudePlan,
    initialize_request,
    judge_initialize,
)
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessResult


class ClaudeLifecycleVerdict(StrEnum):
    INITIALIZATION_OBSERVED = "initialization-observed"
    REFUSED = "refused"
    INCOMPLETE = "incomplete"
    PROCESS_REFUSED = "process-refused"


@dataclass(frozen=True, slots=True)
class ClaudeInitializationObservation:
    mode_verdict: ClaudeInitializeVerdict | None
    lifecycle: ClaudeLifecycleVerdict

    def __post_init__(self) -> None:
        if ((self.mode_verdict is not None
                and type(self.mode_verdict) is not ClaudeInitializeVerdict)
                or type(self.lifecycle) is not ClaudeLifecycleVerdict):
            raise ValueError("invalid Claude initialization observation")
        if (self.lifecycle is ClaudeLifecycleVerdict.INITIALIZATION_OBSERVED
                and self.mode_verdict is not ClaudeInitializeVerdict.MODE_MATCH):
            raise ValueError("observed initialization requires mode match")


class ClaudeInitialization:
    """Single-use callback; no process, task, public gate latch or retry owner."""

    def __init__(self, *, selected_plan: ClaudePlan, input_limit: int) -> None:
        if (type(selected_plan) is not ClaudePlan or type(input_limit) is not int
                or input_limit <= 0):
            raise ValueError("invalid Claude initialization parameters")
        self._selected_plan = selected_plan
        self._input_limit = input_limit
        self._state: Literal["new", "incomplete", "refused", "completed"] = "new"
        self._mode: ClaudeInitializeVerdict | None = None

    def _continuing(self) -> bool:
        return self._state == "incomplete"

    async def __call__(self, io: ProcessIO) -> None:
        if self._state != "new":
            self._state = "refused"
            raise ContractViolation("Claude initialization callback is single-use")
        self._state = "incomplete"
        request_id = secrets.token_hex(16)
        request = initialize_request(request_id)
        if len(request) > self._input_limit:
            self._state = "refused"
            return
        await io.write(request)
        if not self._continuing():
            return
        buffered = bytearray()
        while True:
            maximum = min(8192, RECORD_BYTES - len(buffered))
            chunk = await io.read(maximum)
            if not self._continuing():
                return
            if type(chunk) is not bytes or len(chunk) > maximum:
                self._state = "refused"
                return
            if not chunk:
                return
            newline = chunk.find(b"\n")
            before = len(buffered)
            buffered.extend(chunk)
            if newline >= 0:
                end = before + newline + 1
                break
            if len(buffered) == RECORD_BYTES:
                self._state = "refused"
                return
        self._mode = judge_initialize(
            bytes(buffered[:end]), expected_request_id=request_id,
            selected_plan=self._selected_plan,
        )
        if self._mode is not ClaudeInitializeVerdict.MODE_MATCH or end != len(buffered):
            self._state = "refused"
            return
        await io.close_stdin()
        if not self._continuing():
            return
        tail = await io.read(1)
        if not self._continuing():
            return
        if type(tail) is not bytes or tail:
            self._state = "refused"
            return
        self._state = "completed"


def _cancelled(error: BaseException) -> bool:
    if isinstance(error, asyncio.CancelledError):
        return True
    if isinstance(error, BaseExceptionGroup):
        return any(_cancelled(child) for child in error.exceptions)
    return False


def _clean(result: ProcessResult) -> bool:
    return (
        type(result) is ProcessResult
        and type(result.returncode) is int and result.returncode == 0
        and type(result.payload_returncode) is int and result.payload_returncode == 0
        and result.timed_out is False and result.bound_exceeded is None
    )


async def observe_initialization(
    launcher: LinuxLauncher, command: tuple[str, ...], *, selected_plan: ClaudePlan,
    guard_fds: tuple[int, ...], timeout_s: float,
) -> ClaudeInitializationObservation:
    """Judge only this joined exchange; never accept a supplied result or latch.

    Ordinary/cancellation failures leave no published result, original exception
    or chain. Fatal noncancellation BaseExceptions remain outside that policy.
    """
    cancelled = False
    try:
        conversation = ClaudeInitialization(selected_plan=selected_plan,
                                              input_limit=launcher.limits.input_bytes)
        result = await launcher.exchange(
            command, workspace=None, posture=Posture.READ, guard_fds=guard_fds,
            conversation=conversation, timeout_s=timeout_s,
        )
    except (Exception, asyncio.CancelledError, BaseExceptionGroup) as error:
        cancelled = _cancelled(error)
        if not cancelled and not isinstance(error, Exception):
            raise  # Fatal noncancellation groups are not converted to reports.
    else:
        verdict = ClaudeLifecycleVerdict
        if not _clean(result):
            lifecycle = verdict.PROCESS_REFUSED
        elif conversation._state == "refused":
            lifecycle = verdict.REFUSED
        elif conversation._state != "completed":
            lifecycle = verdict.INCOMPLETE
        else:
            lifecycle = verdict.INITIALIZATION_OBSERVED
        return ClaudeInitializationObservation(mode_verdict=conversation._mode, lifecycle=lifecycle)
    # Outside the catch: from None suppresses chaining, and no caught exception
    # is active here to become this fresh exception's context.
    if cancelled:
        raise asyncio.CancelledError("Claude initialization cancelled") from None
    raise ContractViolation("Claude initialization launch failed") from None
