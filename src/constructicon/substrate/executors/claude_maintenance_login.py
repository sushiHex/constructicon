"""One attended Claude login byte conversation, without login qualification.

The operator waits for the vendor prompt as a host-procedure requirement. This
module forwards opaque stdout; it neither recognizes prompts nor interprets the
single opaque response line. Store, process, egress and post-join private stderr
ownership stay with the later caller of this conversation.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Coroutine
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from constructicon.core.errors import ContractViolation
from constructicon.core.process import ProcessIO
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.claude_operator_io import LINE_BYTES, STDOUT_BYTES

LIFETIME_SECONDS = 600.0


class LoginConversationRefused(Exception):
    """Fixed displayed refusal; internal exception context must remain private."""


class PrivateLoginIO(Protocol):
    """The borrowed operator transport, exercised by the FD adapter and fakes."""

    async def read_line(self) -> bytes: ...

    async def write_stdout(self, data: bytes) -> None: ...

    def invalidate(self) -> None: ...


class ClaudeLoginConversationLifecycle(StrEnum):
    NEW = "new"
    RUNNING = "running"
    COMPLETED = "completed"  # Callback only; no process, credential or mode claim.
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class ClaudeLoginConversationFacts:
    lifecycle: ClaudeLoginConversationLifecycle
    input_write_attempted: bool
    stdin_closed: bool
    stdout_eof: bool
    stdout_bytes: int  # Accepted within budget, not necessarily delivered.

    def __post_init__(self) -> None:
        if (type(self.lifecycle) is not ClaudeLoginConversationLifecycle
                or type(self.input_write_attempted) is not bool
                or type(self.stdin_closed) is not bool
                or type(self.stdout_eof) is not bool
                or type(self.stdout_bytes) is not int
                or not 0 <= self.stdout_bytes <= STDOUT_BYTES):
            raise ValueError("invalid Claude login conversation facts")
        if (self.lifecycle is ClaudeLoginConversationLifecycle.COMPLETED
                and not (self.input_write_attempted and self.stdin_closed and self.stdout_eof)):
            raise ValueError("completed conversation requires byte lifecycle evidence")


class ClaudeLoginConversation:
    """Single-use owner of one native reader and one operator input attempt."""

    def __init__(self, operator: PrivateLoginIO, *, deadline: float) -> None:
        now = asyncio.get_running_loop().time()
        if (type(deadline) is not float or not math.isfinite(deadline)
                or not now < deadline <= now + LIFETIME_SECONDS):
            raise ValueError("invalid Claude login deadline")
        self._operator = operator
        self._deadline = deadline
        self._state = ClaudeLoginConversationLifecycle.NEW
        self._owner: asyncio.Task[None] | None = None
        self._tasks: list[asyncio.Task[object]] = []
        self._input_write_attempted = False
        self._stdin_closed = False
        self._stdout_eof = False
        self._stdout_bytes = 0

    @property
    def facts(self) -> ClaudeLoginConversationFacts:
        return ClaudeLoginConversationFacts(
            self._state, self._input_write_attempted, self._stdin_closed,
            self._stdout_eof, self._stdout_bytes,
        )

    def _check(self) -> None:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError()
        if (self._state is not ClaudeLoginConversationLifecycle.RUNNING
                or asyncio.get_running_loop().time() >= self._deadline):
            raise LoginConversationRefused("Claude login conversation refused")

    def _own(self, coroutine: Coroutine[Any, Any, object]) -> asyncio.Task[object]:
        task = asyncio.create_task(coroutine)
        self._tasks.append(task)
        return task

    async def _pump(self, native: ProcessIO) -> None:
        while True:
            self._check()
            chunk = await native.read(8192)
            self._check()
            if type(chunk) is not bytes or len(chunk) > 8192:
                raise LoginConversationRefused("Claude login conversation refused")
            if not chunk:
                self._stdout_eof = True
                return
            if len(chunk) > STDOUT_BYTES - self._stdout_bytes:
                raise LoginConversationRefused("Claude login conversation refused")
            self._stdout_bytes += len(chunk)
            await self._operator.write_stdout(chunk)
            self._check()

    async def _write_line(
        self, native: ProcessIO, line: bytes, pump: asyncio.Task[object],
    ) -> None:
        self._check()
        if pump.done():  # Re-audit after task scheduling, before spending input.
            self._result(pump)
            raise LoginConversationRefused("Claude login conversation refused")
        self._input_write_attempted = True  # Uncertain delivery spends the attempt.
        await native.write(line)
        self._check()

    @staticmethod
    def _result(task: asyncio.Task[object]) -> object:
        try:
            return task.result()
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise LoginConversationRefused("Claude login conversation refused") from None

    async def _drive(self, native: ProcessIO) -> None:
        pump = self._own(self._pump(native))
        line_task = self._own(self._operator.read_line())
        await asyncio.wait((pump, line_task), return_when=asyncio.FIRST_COMPLETED)
        self._check()
        if pump.done():  # Observed EOF or failure wins even when input is ready.
            self._result(pump)
            raise LoginConversationRefused("Claude login conversation refused")
        line = self._result(line_task)
        if (type(line) is not bytes or not 0 < len(line) <= LINE_BYTES
                or not line.endswith(b"\n") or b"\n" in line[:-1]):
            raise LoginConversationRefused("Claude login conversation refused")
        self._check()
        if pump.done():
            self._result(pump)
            raise LoginConversationRefused("Claude login conversation refused")
        write = self._own(self._write_line(native, line, pump))
        await asyncio.wait((pump, write), return_when=asyncio.FIRST_COMPLETED)
        self._check()
        if pump.done():
            self._result(pump)
            raise LoginConversationRefused("Claude login conversation refused")
        self._result(write)
        try:
            await native.close_stdin()
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise LoginConversationRefused("Claude login conversation refused") from None
        self._check()
        self._stdin_closed = True
        try:
            await pump
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise LoginConversationRefused("Claude login conversation refused") from None
        self._check()

    async def _cleanup(self) -> None:
        invalidation_failed = False
        if self._state is ClaudeLoginConversationLifecycle.REFUSED:
            try:
                self._operator.invalidate()
            except BaseException:
                invalidation_failed = True
        for task in self._tasks:
            if not task.done():
                task.cancel()

        async def join() -> None:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        try:
            await finish_owned(asyncio.create_task(join()))
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise LoginConversationRefused("Claude login conversation refused") from None
        if invalidation_failed:
            raise LoginConversationRefused("Claude login conversation refused") from None

    async def __call__(self, native: ProcessIO) -> None:
        if self._state is not ClaudeLoginConversationLifecycle.NEW:
            if self._state is ClaudeLoginConversationLifecycle.RUNNING:
                self._state = ClaudeLoginConversationLifecycle.REFUSED
                owner = self._owner
                if owner is not None and owner is not asyncio.current_task() and not owner.done():
                    owner.cancel()
            raise ContractViolation("Claude login conversation is single-use")
        self._state = ClaudeLoginConversationLifecycle.RUNNING
        self._owner = asyncio.current_task()
        body_error: BaseException | None = None
        try:
            async with asyncio.timeout_at(self._deadline):
                await self._drive(native)
        except BaseException as error:
            body_error = error
            self._state = ClaudeLoginConversationLifecycle.REFUSED
        cleanup_error: BaseException | None = None
        try:
            await self._cleanup()  # No timeout: joined ownership before return.
        except BaseException as error:
            cleanup_error = error
            self._state = ClaudeLoginConversationLifecycle.REFUSED
            with suppress(BaseException):
                self._operator.invalidate()
        finally:
            self._owner = None
        if isinstance(body_error, asyncio.CancelledError):
            if cleanup_error is not None and not isinstance(cleanup_error, asyncio.CancelledError):
                raise BaseExceptionGroup("Claude login cleanup refused", [
                    body_error, LoginConversationRefused("Claude login conversation refused"),
                ]) from None
            raise body_error
        if isinstance(cleanup_error, asyncio.CancelledError):
            raise cleanup_error
        if cleanup_error is not None:
            raise LoginConversationRefused("Claude login conversation refused") from None
        if body_error is not None:
            raise body_error
        if self._state is not ClaudeLoginConversationLifecycle.RUNNING:
            raise LoginConversationRefused("Claude login conversation refused")
        self._state = ClaudeLoginConversationLifecycle.COMPLETED
