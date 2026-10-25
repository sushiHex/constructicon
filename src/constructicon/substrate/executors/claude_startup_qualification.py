"""One no-dispatch authenticated Claude startup observation, not availability."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum

from constructicon.core.errors import ContractViolation
from constructicon.core.process import ProcessIO
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.claude_maintenance_mode import (
    INPUT_BYTES,
    LIFETIME_SECONDS,
    OUTPUT_BYTES,
    ClaudeMaintenanceConversation,
    ClaudeMaintenancePhase,
)
from constructicon.substrate.executors.claude_protocol import (
    RECORD_BYTES,
    ClaudeApiKeySourceCategory,
    ClaudeInitializeVerdict,
    ClaudeModeMismatchReason,
    ClaudePlan,
    ClaudeTokenSourceCategory,
    initialize_diagnostics_valid,
    initialize_request,
    observe_initialize,
)
from constructicon.substrate.executors.claude_startup import (
    ClaudeSettingsMismatchReason,
    ClaudeStartupVerdict,
    classify_settings,
    hooks_request,
    judge_hooks,
    settings_request,
)


class ClaudeQualificationLifecycle(StrEnum):
    QUALIFIED = "qualified"
    REFUSED = "refused"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class ClaudeStartupQualificationFacts:
    lifecycle: ClaudeQualificationLifecycle
    initialize_verdict: ClaudeInitializeVerdict | None
    settings_verdict: ClaudeStartupVerdict | None
    hooks_verdict: ClaudeStartupVerdict | None
    request_writes: int
    ui_records: int
    stdin_closed: bool
    eof: bool
    settings_mismatch_reason: ClaudeSettingsMismatchReason | None = None
    mode_mismatch_reason: ClaudeModeMismatchReason | None = None
    token_source_category: ClaudeTokenSourceCategory | None = None
    api_key_source_category: ClaudeApiKeySourceCategory | None = None

    def __post_init__(self) -> None:
        if (not initialize_diagnostics_valid(
                self.initialize_verdict, self.mode_mismatch_reason,
                self.token_source_category, self.api_key_source_category,
            ) or type(self.lifecycle) is not ClaudeQualificationLifecycle
                or (self.initialize_verdict is not None
                    and type(self.initialize_verdict) is not ClaudeInitializeVerdict)
                or (self.settings_verdict is not None
                    and type(self.settings_verdict) is not ClaudeStartupVerdict)
                or (self.hooks_verdict is not None
                    and type(self.hooks_verdict) is not ClaudeStartupVerdict)
                or (self.settings_mismatch_reason is not None
                    and (type(self.settings_mismatch_reason) is not ClaudeSettingsMismatchReason
                         or self.settings_verdict is not
                         ClaudeStartupVerdict.CONFIGURATION_MISMATCH))
                or ((self.settings_verdict is ClaudeStartupVerdict.CONFIGURATION_MISMATCH)
                    != (self.settings_mismatch_reason is not None))
                or type(self.request_writes) is not int or not 0 <= self.request_writes <= 3
                or type(self.ui_records) is not int or not 0 <= self.ui_records <= 8
                or type(self.stdin_closed) is not bool or type(self.eof) is not bool):
            raise ValueError("invalid Claude qualification facts")
        if self.lifecycle is ClaudeQualificationLifecycle.QUALIFIED and not (
            self.initialize_verdict is ClaudeInitializeVerdict.MODE_MATCH
            and self.settings_verdict is ClaudeStartupVerdict.MATCH
            and self.hooks_verdict is ClaudeStartupVerdict.MATCH
            and self.request_writes == 3 and self.stdin_closed and self.eof
        ):
            raise ValueError("qualification needs three closed observations")


class _Refused(Exception):
    """Static private refusal; never include native bytes."""


class ClaudeStartupQualification(ClaudeMaintenanceConversation):
    """Single-use three-control qualification over the existing owned reader."""

    def __init__(
        self, *, selected_plan: ClaudePlan, model: str, effort: str,
        input_limit: int, output_limit: int, deadline: float,
        check_control: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(phase=ClaudeMaintenancePhase.RELOAD, selected_plan=selected_plan,
                         input_limit=input_limit, output_limit=output_limit,
                         deadline=deadline)
        if (type(model) is not str or not model or len(model) > 128
                or type(effort) is not str or not effort or len(effort) > 32):
            raise ValueError("invalid sealed Claude selection")
        self.model, self.effort = model, effort
        self._check_control = check_control
        self.initialize_verdict: ClaudeInitializeVerdict | None = None
        self.settings_verdict: ClaudeStartupVerdict | None = None
        self.settings_mismatch_reason: ClaudeSettingsMismatchReason | None = None
        self.hooks_verdict: ClaudeStartupVerdict | None = None

    def _check(self) -> None:
        super()._check()
        if self._check_control is not None:
            self._check_control()

    @property
    def facts(self) -> ClaudeStartupQualificationFacts:
        lifecycle = (ClaudeQualificationLifecycle.QUALIFIED if self._state == "completed"
                     else ClaudeQualificationLifecycle.INCOMPLETE if self._state == "new"
                     else ClaudeQualificationLifecycle.REFUSED)
        return ClaudeStartupQualificationFacts(
            lifecycle, self.initialize_verdict, self.settings_verdict,
            self.hooks_verdict, self.request_writes, self.ui_records,
            self.stdin_closed, self.eof, self.settings_mismatch_reason,
            self.mode_mismatch_reason, self.token_source_category, self.api_key_source_category,
        )

    async def _write_control(self, kind: str) -> str:
        self._audit()
        self._consume_ui_records()
        if self._records or self._buffer or self.eof or self.request_writes >= 3:
            raise _Refused()
        identifier = secrets.token_hex(16)
        if identifier in self._ids:
            raise _Refused()
        raw = (initialize_request(identifier) if kind == "initialize" else
               settings_request(identifier) if kind == "get_settings" else
               hooks_request(identifier))
        proposed = self.input_bytes + len(raw)
        if len(raw) > RECORD_BYTES or proposed > min(self.input_limit, INPUT_BYTES):
            raise _Refused()
        self._ids.add(identifier)
        self.request_writes += 1  # Reserve before uncertain delivery.
        self.input_bytes = proposed
        assert self._io is not None
        await self._io.write(raw)
        self._audit()
        return identifier

    async def _judge_control(self, kind: str, identifier: str) -> None:
        while True:
            record = await self._next()
            if self._ui(record):
                continue
            if kind == "initialize":
                observation = observe_initialize(
                    record, expected_request_id=identifier, selected_plan=self.plan,
                )
                self.initialize_verdict = observation.verdict
                self.mode_mismatch_reason = observation.reason
                self.token_source_category = observation.token_source_category
                self.api_key_source_category = observation.api_key_source_category
                if self.initialize_verdict is not ClaudeInitializeVerdict.MODE_MATCH:
                    raise _Refused()
            elif kind == "get_settings":
                self.settings_verdict, self.settings_mismatch_reason = classify_settings(
                    record, expected_request_id=identifier,
                    model=self.model, effort=self.effort,
                )
                if self.settings_verdict is not ClaudeStartupVerdict.MATCH:
                    raise _Refused()
            else:
                self.hooks_verdict = judge_hooks(record, expected_request_id=identifier)
                if self.hooks_verdict is not ClaudeStartupVerdict.MATCH:
                    raise _Refused()
            return

    async def __call__(self, io: ProcessIO) -> None:
        if self._state != "new":
            self._state = "refused"
            owner = self._owner
            if owner is not None and owner is not asyncio.current_task() and not owner.done():
                owner.cancel()
            raise ContractViolation("Claude qualification conversation is single-use")
        self._state, self._io = "running", io
        self._owner = asyncio.current_task()
        self._start_read()
        try:
            for kind in ("initialize", "get_settings", "get_hooks_listing"):
                identifier = await self._write_control(kind)
                await self._judge_control(kind, identifier)
            self._audit()
            self._consume_ui_records()
            if self.eof:
                raise _Refused()
            await io.close_stdin()
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


QUALIFICATION_SECONDS = LIFETIME_SECONDS
QUALIFICATION_INPUT_BYTES = INPUT_BYTES
QUALIFICATION_OUTPUT_BYTES = OUTPUT_BYTES
