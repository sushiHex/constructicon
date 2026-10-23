"""Bounded no-model Claude maintenance mode observation.

This observes native mode only. It cannot login, register tools, dispatch a
message, establish refresh completion, or qualify production availability.
"""

from __future__ import annotations

import asyncio
import math
import secrets
from contextlib import suppress
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import parse_json_value
from constructicon.core.process import ProcessIO
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.claude_initialize import _cancelled, _clean
from constructicon.substrate.executors.claude_native import (
    ClaudeNativeRecipe,
    ClaudeNativeStoreMount,
)
from constructicon.substrate.executors.claude_native_events import exact_ui_invalidate
from constructicon.substrate.executors.claude_protocol import (
    RECORD_BYTES,
    ClaudeInitializeVerdict,
    ClaudeModeMismatchReason,
    ClaudePlan,
    classify_initialize,
    initialize_request,
)
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.executors.operator_store import BindingCheck

INPUT_BYTES = 8 * 1024
OUTPUT_BYTES = 512 * 1024
UI_RECORDS = 8
SPACING_SECONDS = 30.0
LIFETIME_SECONDS = 120.0


class ClaudeMaintenancePhase(StrEnum):
    OBSERVE = "observe"
    RELOAD = "reload"


class ClaudeMaintenanceLifecycle(StrEnum):
    OBSERVED = "observed"
    REFUSED = "refused"
    INCOMPLETE = "incomplete"
    PROCESS_REFUSED = "process-refused"


class ClaudeMaintenanceRefusalCode(StrEnum):
    """First observed guard failure, never inferred from a reply or exception text."""

    STATE = "state"
    DEADLINE = "deadline"
    READ_CONTRACT = "read-contract"
    READ_ERROR = "read-error"
    READ_UNAVAILABLE = "read-unavailable"
    OUTPUT_LIMIT = "output-limit"
    RECORD_LIMIT = "record-limit"
    RECORD_FORMAT = "record-format"
    UI_RECORD = "ui-record"
    UNEXPECTED_RECORD = "unexpected-record"
    PARTIAL_RECORD = "partial-record"
    EOF = "eof"
    WRITE_LIMIT = "write-limit"
    REQUEST_ID_REUSE = "request-id-reuse"
    INPUT_LIMIT = "input-limit"
    RESPONSE_VERDICT = "response-verdict"


@dataclass(frozen=True, slots=True)
class ClaudeMaintenanceObservation:
    phase: ClaudeMaintenancePhase
    mode_verdict: ClaudeInitializeVerdict | None
    lifecycle: ClaudeMaintenanceLifecycle
    request_writes: int
    ui_records: int
    stdin_closed: bool
    eof: bool
    mode_mismatch_reason: ClaudeModeMismatchReason | None = None
    classified_responses: int | None = None
    refusal_code: ClaudeMaintenanceRefusalCode | None = None

    def __post_init__(self) -> None:
        if (type(self.phase) is not ClaudeMaintenancePhase
                or (self.mode_verdict is not None
                    and type(self.mode_verdict) is not ClaudeInitializeVerdict)
                or (self.mode_mismatch_reason is not None
                    and (type(self.mode_mismatch_reason) is not ClaudeModeMismatchReason
                         or self.mode_verdict is not ClaudeInitializeVerdict.MODE_MISMATCH))
                or type(self.lifecycle) is not ClaudeMaintenanceLifecycle
                or type(self.request_writes) is not int
                or not 0 <= self.request_writes <= (
                    2 if self.phase is ClaudeMaintenancePhase.OBSERVE else 1
                )
                or (self.classified_responses is not None
                    and (type(self.classified_responses) is not int
                         or not 0 <= self.classified_responses <= self.request_writes
                         or (self.classified_responses > 0) != (self.mode_verdict is not None)))
                or (self.mode_mismatch_reason is not None
                    and self.classified_responses is None)
                or (self.refusal_code is not None
                    and type(self.refusal_code) is not ClaudeMaintenanceRefusalCode)
                or type(self.ui_records) is not int or not 0 <= self.ui_records <= UI_RECORDS
                or type(self.stdin_closed) is not bool or type(self.eof) is not bool):
            raise ValueError("invalid Claude maintenance observation")
        if (self.lifecycle is ClaudeMaintenanceLifecycle.OBSERVED
                and (self.mode_verdict is not ClaudeInitializeVerdict.MODE_MATCH
                     or not self.request_writes or not self.stdin_closed or not self.eof
                     or self.refusal_code is not None)):
            raise ValueError("observed maintenance requires joined mode evidence")


class _Refused(Exception):
    """Static internal refusal; never carry wire bytes."""


def _monotonic() -> float:
    """The platform clock seam; tests can advance only this primitive."""
    return asyncio.get_running_loop().time()


def exact_ambiguous_api_mode(
    record: bytes, *, expected_request_id: str, selected_plan: ClaudePlan,
) -> bool:
    """Recognize only an idle, correlated first-party Claude API projection.

    The shared classifier retains every envelope, pending-action, version,
    idle and account check before identifying this exact ambiguity.
    """
    _, reason = classify_initialize(
        record, expected_request_id=expected_request_id, selected_plan=selected_plan,
    )
    return reason is ClaudeModeMismatchReason.AMBIGUOUS_API


class ClaudeMaintenanceConversation:
    """Single-use owner of one continuously active read task and serial writes."""

    def __init__(
        self, *, phase: ClaudeMaintenancePhase, selected_plan: ClaudePlan,
        input_limit: int, output_limit: int, deadline: float,
    ) -> None:
        if (type(phase) is not ClaudeMaintenancePhase or type(selected_plan) is not ClaudePlan
                or type(input_limit) is not int or input_limit <= 0
                or type(output_limit) is not int or output_limit <= 0
                or type(deadline) is not float or not math.isfinite(deadline)):
            raise ValueError("invalid Claude maintenance parameters")
        self.phase, self.plan = phase, selected_plan
        self.input_limit = min(input_limit, INPUT_BYTES)
        self.output_limit = min(output_limit, OUTPUT_BYTES)
        self.deadline = deadline
        self._state: Literal["new", "running", "completed", "refused"] = "new"
        self.mode_verdict: ClaudeInitializeVerdict | None = None
        self.mode_mismatch_reason: ClaudeModeMismatchReason | None = None
        self.classified_responses = 0
        self.refusal_code: ClaudeMaintenanceRefusalCode | None = None
        self.request_writes = self.ui_records = self.input_bytes = self.output_bytes = 0
        self.stdin_closed = self.eof = False
        self._buffer = bytearray()
        self._records: list[bytes] = []
        self._ids: set[str] = set()
        self._reader: asyncio.Task[bytes] | None = None
        self._owner: asyncio.Task[None] | None = None
        self._io: ProcessIO | None = None

    def _latch(self, code: ClaudeMaintenanceRefusalCode) -> None:
        if self.refusal_code is None:
            self.refusal_code = code

    def _check(self) -> None:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError()
        if self._state != "running":
            self._latch(ClaudeMaintenanceRefusalCode.STATE)
            raise _Refused()
        if _monotonic() >= self.deadline:
            self._latch(ClaudeMaintenanceRefusalCode.DEADLINE)
            raise TimeoutError()

    def _start_read(self) -> None:
        assert self._io is not None
        self._reader = asyncio.create_task(self._io.read(8192))

    def _receive(self, chunk: bytes) -> None:
        if type(chunk) is not bytes or len(chunk) > 8192:
            self._latch(ClaudeMaintenanceRefusalCode.READ_CONTRACT)
            raise _Refused()
        self.output_bytes += len(chunk)
        if self.output_bytes > self.output_limit:
            self._latch(ClaudeMaintenanceRefusalCode.OUTPUT_LIMIT)
            raise _Refused()
        if not chunk:
            self.eof = True
            return
        self._buffer.extend(chunk)
        while (newline := self._buffer.find(b"\n")) >= 0:
            if newline + 1 > RECORD_BYTES:
                self._latch(ClaudeMaintenanceRefusalCode.RECORD_LIMIT)
                raise _Refused()
            self._records.append(bytes(self._buffer[:newline + 1]))
            del self._buffer[:newline + 1]
        if len(self._buffer) >= RECORD_BYTES:
            self._latch(ClaudeMaintenanceRefusalCode.RECORD_LIMIT)
            raise _Refused()
        self._start_read()

    def _audit(self) -> None:
        self._check()
        while self._reader is not None and self._reader.done():
            reader, self._reader = self._reader, None
            try:
                chunk = reader.result()
            except Exception:
                self._latch(ClaudeMaintenanceRefusalCode.READ_ERROR)
                raise
            self._receive(chunk)

    async def _next(self) -> bytes:
        self._audit()
        while not self._records:
            if self.eof or self._reader is None:
                self._latch(ClaudeMaintenanceRefusalCode.EOF if self.eof
                            else ClaudeMaintenanceRefusalCode.READ_UNAVAILABLE)
                raise _Refused()
            reader = self._reader
            try:
                chunk = await reader
            except Exception:
                self._latch(ClaudeMaintenanceRefusalCode.READ_ERROR)
                raise
            self._reader = None
            self._check()
            self._receive(chunk)
        return self._records.pop(0)

    def _ui(self, record: bytes) -> bool:
        if b"\r" in record:
            self._latch(ClaudeMaintenanceRefusalCode.RECORD_FORMAT)
            raise _Refused()
        try:
            value = parse_json_value(record[:-1].decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            self._latch(ClaudeMaintenanceRefusalCode.RECORD_FORMAT)
            raise _Refused() from None
        if type(value) is dict and value.get("type") == "system":
            if not exact_ui_invalidate(value) or self.ui_records >= UI_RECORDS:
                self._latch(ClaudeMaintenanceRefusalCode.UI_RECORD)
                raise _Refused()
            self.ui_records += 1
            return True
        return False

    def _consume_ui_records(self) -> None:
        while self._records:
            if not self._ui(self._records.pop(0)):
                self._latch(ClaudeMaintenanceRefusalCode.UNEXPECTED_RECORD)
                raise _Refused()

    async def _response(self, identifier: str) -> tuple[bool, float]:
        while True:
            record = await self._next()
            if self._ui(record):
                continue
            self.mode_verdict, self.mode_mismatch_reason = classify_initialize(
                record, expected_request_id=identifier, selected_plan=self.plan,
            )
            self.classified_responses += 1
            received_at = _monotonic()
            if self.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH:
                return True, received_at
            if (self.phase is ClaudeMaintenancePhase.OBSERVE and self.request_writes == 1
                    and self.mode_mismatch_reason is ClaudeModeMismatchReason.AMBIGUOUS_API):
                return False, received_at
            self._latch(ClaudeMaintenanceRefusalCode.RESPONSE_VERDICT)
            raise _Refused()

    async def _write(self) -> str:
        self._audit()
        if self._records or self._buffer or self.eof:
            self._latch(ClaudeMaintenanceRefusalCode.UNEXPECTED_RECORD if self._records else
                        ClaudeMaintenanceRefusalCode.PARTIAL_RECORD if self._buffer else
                        ClaudeMaintenanceRefusalCode.EOF)
            raise _Refused()
        if self.request_writes >= (2 if self.phase is ClaudeMaintenancePhase.OBSERVE else 1):
            self._latch(ClaudeMaintenanceRefusalCode.WRITE_LIMIT)
            raise _Refused()
        identifier = secrets.token_hex(16)
        if identifier in self._ids:
            self._latch(ClaudeMaintenanceRefusalCode.REQUEST_ID_REUSE)
            raise _Refused()
        raw = initialize_request(identifier)
        proposed_bytes = self.input_bytes + len(raw)
        if proposed_bytes > self.input_limit:
            self._latch(ClaudeMaintenanceRefusalCode.INPUT_LIMIT)
            raise _Refused()
        self._ids.add(identifier)
        self.request_writes += 1  # Uncertain write attempts remain spent.
        self.input_bytes = proposed_bytes
        assert self._io is not None
        await self._io.write(raw)
        self._audit()
        return identifier

    async def _spacing(self, first_response_at: float) -> None:
        boundary = first_response_at + SPACING_SECONDS
        while True:
            self._audit()
            self._consume_ui_records()  # Duplicate, callback or early reply refuses.
            if self.eof:
                self._latch(ClaudeMaintenanceRefusalCode.PARTIAL_RECORD if self._buffer
                            else ClaudeMaintenanceRefusalCode.EOF)
                raise _Refused()
            if self._buffer:
                await self._next_ui()  # Finish this bounded frame before any later write.
                continue
            if _monotonic() >= boundary:
                self._audit()  # Completed read at the timer edge wins over write.
                if self._records or self._buffer or self.eof:
                    continue
                return
            assert self._reader is not None
            await asyncio.wait((self._reader,), timeout=boundary - _monotonic(),
                               return_when=asyncio.FIRST_COMPLETED)
            self._check()

    async def _drain(self) -> None:
        while True:
            self._audit()
            self._consume_ui_records()
            if self.eof:
                if self._buffer:
                    self._latch(ClaudeMaintenanceRefusalCode.PARTIAL_RECORD)
                    raise _Refused()
                return
            await self._next_ui()

    async def _next_ui(self) -> None:
        if self._reader is None:
            self._latch(ClaudeMaintenanceRefusalCode.READ_UNAVAILABLE)
            raise _Refused()
        reader = self._reader
        try:
            chunk = await reader
        except Exception:
            self._latch(ClaudeMaintenanceRefusalCode.READ_ERROR)
            raise
        self._reader = None
        self._check()
        self._receive(chunk)

    async def __call__(self, io: ProcessIO) -> None:
        if self._state != "new":
            self._latch(ClaudeMaintenanceRefusalCode.STATE)
            self._state = "refused"
            owner = self._owner
            if owner is not None and owner is not asyncio.current_task() and not owner.done():
                owner.cancel()
            raise ContractViolation("Claude maintenance conversation is single-use")
        self._state, self._io = "running", io
        self._owner = asyncio.current_task()
        self._start_read()
        try:
            identifier = await self._write()
            matched, received_at = await self._response(identifier)
            if not matched:
                await self._spacing(received_at)
                identifier = await self._write()
                matched, _ = await self._response(identifier)
            if not matched:
                self._latch(ClaudeMaintenanceRefusalCode.RESPONSE_VERDICT)
                raise _Refused()
            self._audit()
            self._consume_ui_records()
            if self.eof:
                self._latch(ClaudeMaintenanceRefusalCode.EOF)
                raise _Refused()
            assert self._io is not None
            await self._io.close_stdin()
            self._check()
            self.stdin_closed = True
            await self._drain()
            self._check()
            self._state = "completed"
        except BaseException:
            self._state = "refused"
            raise
        finally:
            try:
                if self._reader is not None:
                    reader, self._reader = self._reader, None
                    if not reader.done():
                        reader.cancel()

                    async def join_reader() -> None:
                        with suppress(asyncio.CancelledError):
                            await reader

                    await finish_owned(asyncio.create_task(join_reader()))
            finally:
                self._owner = None


async def observe_maintenance_mode(
    launcher: LinuxLauncher, native_store: ClaudeNativeStoreMount, *,
    phase: ClaudeMaintenancePhase, selected_plan: ClaudePlan, timeout_s: float = LIFETIME_SECONDS,
) -> ClaudeMaintenanceObservation:
    """Observe one process with existing store custody and joined teardown."""
    if (type(phase) is not ClaudeMaintenancePhase or type(selected_plan) is not ClaudePlan
            or type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
            or not 0 < timeout_s <= LIFETIME_SECONDS):
        raise ValueError("invalid Claude maintenance parameters")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    conversation = ClaudeMaintenanceConversation(
        phase=phase, selected_plan=selected_plan,
        input_limit=launcher.limits.input_bytes, output_limit=launcher.limits.stdout_bytes,
        deadline=_monotonic() + timeout_s,
    )
    lifecycle = ClaudeMaintenanceLifecycle.REFUSED
    work_timeout = asyncio.timeout_at(deadline)
    try:
        if (type(native_store) is not ClaudeNativeStoreMount or launcher.claude is None
                or launcher.claude_recipe is not ClaudeNativeRecipe.STREAM_JSON
                or native_store.lock_fd < 0):
            raise _Refused()
        initial = native_store.before_spawn()
        if type(initial) is not BindingCheck:
            raise _Refused()

        def check_binding() -> BindingCheck:
            current = native_store.before_spawn()
            if type(current) is not BindingCheck or current != initial:
                raise _Refused()
            return current

        launch_store = replace(native_store, before_spawn=check_binding)
        try:
            async with work_timeout:
                result = await launcher.exchange(
                    launcher.claude.command, workspace=None, posture=Posture.READ,
                    guard_fds=(native_store.lock_fd,), conversation=conversation,
                    timeout_s=deadline - loop.time(),
                    native_store=launch_store,
                )
        except BaseException:
            with suppress(BaseException):
                check_binding()
            raise
        check_binding()
        if loop.time() >= deadline:
            lifecycle = ClaudeMaintenanceLifecycle.INCOMPLETE
        elif not _clean(result):
            lifecycle = ClaudeMaintenanceLifecycle.PROCESS_REFUSED
        elif conversation._state == "completed":
            lifecycle = ClaudeMaintenanceLifecycle.OBSERVED
        elif conversation._state == "new":
            lifecycle = ClaudeMaintenanceLifecycle.INCOMPLETE
    except (Exception, asyncio.CancelledError, BaseExceptionGroup) as error:
        if _cancelled(error):
            raise asyncio.CancelledError("Claude maintenance cancelled") from None
        if not isinstance(error, Exception):
            raise
        if isinstance(error, TimeoutError) and work_timeout.expired():
            conversation._latch(ClaudeMaintenanceRefusalCode.DEADLINE)
        if isinstance(error, TimeoutError) and conversation._state != "refused":
            lifecycle = ClaudeMaintenanceLifecycle.INCOMPLETE
    return ClaudeMaintenanceObservation(
        phase, conversation.mode_verdict, lifecycle, conversation.request_writes,
        conversation.ui_records, conversation.stdin_closed, conversation.eof,
        conversation.mode_mismatch_reason,
        conversation.classified_responses,
        conversation.refusal_code,
    )
