"""One withdrawn-store Claude maintenance or startup-qualification phase.

The caller owns the maintenance lock and the operator transport. This seam
owns only the credential descriptor it opens, its relay, and one joined native
process. Each invocation is one explicit phase; no phase advances another.
"""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from constructicon.core.grants import Posture
from constructicon.substrate.executors.claude_initialize import _cancelled, _clean
from constructicon.substrate.executors.claude_maintenance_login import (
    LIFETIME_SECONDS as LOGIN_SECONDS,
)
from constructicon.substrate.executors.claude_maintenance_login import (
    ClaudeLoginConversation,
    ClaudeLoginConversationFacts,
    ClaudeLoginConversationLifecycle,
    PrivateLoginIO,
)
from constructicon.substrate.executors.claude_maintenance_mode import (
    INPUT_BYTES as MODE_INPUT_BYTES,
)
from constructicon.substrate.executors.claude_maintenance_mode import (
    LIFETIME_SECONDS as MODE_SECONDS,
)
from constructicon.substrate.executors.claude_maintenance_mode import (
    OUTPUT_BYTES as MODE_OUTPUT_BYTES,
)
from constructicon.substrate.executors.claude_maintenance_mode import (
    ClaudeMaintenanceLifecycle,
    ClaudeMaintenanceObservation,
    ClaudeMaintenancePhase,
    observe_maintenance_mode,
)
from constructicon.substrate.executors.claude_native import (
    ClaudeNativeRecipe,
    ClaudeNativeStoreMount,
)
from constructicon.substrate.executors.claude_operator_io import (
    LINE_BYTES as LOGIN_INPUT_BYTES,
)
from constructicon.substrate.executors.claude_operator_io import (
    STDERR_BYTES,
)
from constructicon.substrate.executors.claude_operator_io import (
    STDOUT_BYTES as LOGIN_OUTPUT_BYTES,
)
from constructicon.substrate.executors.claude_protocol import RECORD_BYTES, ClaudePlan
from constructicon.substrate.executors.claude_startup_qualification import (
    ClaudeQualificationLifecycle,
    ClaudeStartupQualification,
    ClaudeStartupQualificationFacts,
)
from constructicon.substrate.executors.egress import EgressPolicy, EgressRelay
from constructicon.substrate.executors.linux import (
    LinuxLauncher,
    ProcessExchangeError,
    ProcessLimits,
    ProcessResult,
)
from constructicon.substrate.executors.operator_store import BindingCheck, StoreMaintenance


class PrivateMaintenanceIO(PrivateLoginIO, Protocol):
    """Private borrowed operator transport, also used for post-join stderr."""

    async def write_stderr(self, data: bytes) -> None: ...


class ClaudeMaintenanceSessionPhase(StrEnum):
    LOGIN = "login"
    OBSERVE = "observe"
    RELOAD = "reload"
    QUALIFY = "qualify"


class ClaudeMaintenanceSessionLifecycle(StrEnum):
    JOINED_CLEAN = "joined-clean"  # Joined phase only; not auth or persistence.
    REFUSED = "refused"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class ClaudeMaintenanceSessionFacts:
    phase: ClaudeMaintenanceSessionPhase
    lifecycle: ClaudeMaintenanceSessionLifecycle
    login_facts: ClaudeLoginConversationFacts | None
    mode_observation: ClaudeMaintenanceObservation | None
    process_clean: bool | None
    relay_closed: bool | None
    custody_current: bool | None
    credential_closed: bool | None
    qualification: ClaudeStartupQualificationFacts | None = None

    def __post_init__(self) -> None:
        if (type(self.phase) is not ClaudeMaintenanceSessionPhase
                or type(self.lifecycle) is not ClaudeMaintenanceSessionLifecycle
                or (self.login_facts is not None
                    and type(self.login_facts) is not ClaudeLoginConversationFacts)
                or (self.mode_observation is not None
                    and type(self.mode_observation) is not ClaudeMaintenanceObservation)
                or (self.qualification is not None
                    and type(self.qualification) is not ClaudeStartupQualificationFacts)
                or any(value is not None and type(value) is not bool for value in (
                    self.process_clean, self.relay_closed, self.custody_current,
                    self.credential_closed,
                ))):
            raise ValueError("invalid Claude maintenance session facts")
        if self.phase is ClaudeMaintenanceSessionPhase.LOGIN:
            if self.mode_observation is not None or self.qualification is not None:
                raise ValueError("login cannot carry mode observation")
        elif self.phase is ClaudeMaintenanceSessionPhase.QUALIFY:
            if self.login_facts is not None or self.mode_observation is not None:
                raise ValueError("qualification cannot carry maintenance observation")
        elif (self.login_facts is not None or self.process_clean is not None
              or self.qualification is not None
              or (self.mode_observation is not None
                  and self.mode_observation.phase.value != self.phase.value)):
            raise ValueError("mode phase cannot carry login evidence")
        if self.lifecycle is ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN:
            if not (self.relay_closed is True and self.custody_current is True
                    and self.credential_closed is True):
                raise ValueError("joined phase needs affirmative cleanup and custody")
            if self.phase is ClaudeMaintenanceSessionPhase.LOGIN:
                if (self.process_clean is not True or self.login_facts is None
                        or self.login_facts.lifecycle
                        is not ClaudeLoginConversationLifecycle.COMPLETED):
                    raise ValueError("joined login needs affirmative process evidence")
            elif self.phase is ClaudeMaintenanceSessionPhase.QUALIFY:
                if (self.process_clean is not True or self.qualification is None
                        or self.qualification.lifecycle
                        is not ClaudeQualificationLifecycle.QUALIFIED):
                    raise ValueError("joined qualification needs affirmative evidence")
            elif (self.mode_observation is None or self.mode_observation.lifecycle
                  is not ClaudeMaintenanceLifecycle.OBSERVED):
                raise ValueError("joined mode needs affirmative observation")


def _limits_ok(limits: object, *, login: bool) -> bool:
    if type(limits) is not ProcessLimits:
        return False
    return (
        limits.input_bytes <= (LOGIN_INPUT_BYTES if login else MODE_INPUT_BYTES)
        and limits.stdout_bytes <= (LOGIN_OUTPUT_BYTES if login else MODE_OUTPUT_BYTES)
        and limits.record_bytes <= RECORD_BYTES
        and limits.stderr_bytes <= STDERR_BYTES
    )


def _policy_ok(policy: object, phase: ClaudeMaintenanceSessionPhase) -> bool:
    if type(policy) is not EgressPolicy:
        return False
    hosts = {(item.host, item.port) for item in policy.destinations}
    required = {("platform.claude.com", 443)}
    if phase is not ClaudeMaintenanceSessionPhase.LOGIN:
        required.add(("api.anthropic.com", 443))
    return hosts == required


async def run_maintenance_session(
    custody: StoreMaintenance, launcher: LinuxLauncher, policy: EgressPolicy,
    lane_dir: Path, *, phase: ClaudeMaintenanceSessionPhase,
    selected_plan: ClaudePlan | None = None,
    operator: PrivateMaintenanceIO | None = None, first_login: bool = False,
    deadline: float | None = None,
) -> ClaudeMaintenanceSessionFacts:
    """Run one attended login, mode observation or no-dispatch qualification.

    ``deadline`` is the loop's absolute monotonic deadline. A caller using an
    FD operator must construct it with this same deadline. Prompt-first input
    remains an operator procedure; opaque stdout does not prove a prompt.
    """
    loop = asyncio.get_running_loop()
    now = loop.time()
    login = phase is ClaudeMaintenanceSessionPhase.LOGIN
    maximum = LOGIN_SECONDS if login else MODE_SECONDS
    end = now + maximum if deadline is None else deadline
    initial: BindingCheck | None = None
    credential_fd: int | None = None
    relay: EgressRelay | None = None
    result: ProcessResult | None = None
    login_conversation: ClaudeLoginConversation | None = None
    qualification_conversation: ClaudeStartupQualification | None = None
    observation: ClaudeMaintenanceObservation | None = None
    body_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    credential_closed: bool | None = None
    custody_current: bool | None = None
    relay_closed: bool | None = None

    try:
        if (type(phase) is not ClaudeMaintenanceSessionPhase
                or type(first_login) is not bool
                or not isinstance(lane_dir, Path) or not lane_dir.is_absolute()
                or type(end) is not float or not math.isfinite(end)
                or not now < end <= now + maximum
                or not _policy_ok(policy, phase)
                or not _limits_ok(launcher.limits, login=login)
                or launcher.claude is None
                or launcher.claude_recipe is not (
                    ClaudeNativeRecipe.LOGIN if login else ClaudeNativeRecipe.STREAM_JSON
                )
                or (login and (operator is None or selected_plan is not None))
                or (not login and (operator is not None or first_login
                                   or type(selected_plan) is not ClaudePlan))):
            raise ValueError("Claude maintenance phase refused")
        initial = custody.check()
        if type(initial) is not BindingCheck:
            raise ValueError("Claude maintenance custody refused")

        def check_binding() -> BindingCheck:
            current = custody.check()
            if (type(current) is not BindingCheck or current != initial
                    or loop.time() >= end):
                raise ValueError("Claude maintenance custody refused")
            return current

        check_binding()
        if first_login:
            custody.create_credential()
            check_binding()
        opened_fd = custody.open_credential()
        if (type(opened_fd) is not int or opened_fd < 0
                or opened_fd == custody.lock_fd):
            raise ValueError("Claude maintenance credential refused")
        credential_fd = opened_fd
        check_binding()
        def relay_check() -> None:
            check_binding()

        relay = EgressRelay(policy, lane_dir, end, relay_check)
        async with relay as egress:
            check_binding()
            native_store = ClaudeNativeStoreMount(
                custody.lock_fd, credential_fd, check_binding, egress,
            )
            if login:
                assert operator is not None
                login_conversation = ClaudeLoginConversation(operator, deadline=end)
                async with asyncio.timeout_at(end):
                    result = await launcher.exchange(
                        ClaudeNativeRecipe.LOGIN.command(launcher.claude),
                        workspace=None, posture=Posture.READ,
                        guard_fds=(custody.lock_fd,), conversation=login_conversation,
                        timeout_s=end - loop.time(), native_store=native_store,
                    )
            elif phase is ClaudeMaintenanceSessionPhase.QUALIFY:
                assert selected_plan is not None and launcher.claude is not None
                qualification_conversation = ClaudeStartupQualification(
                    selected_plan=selected_plan, model=launcher.claude.model,
                    effort=launcher.claude.effort,
                    input_limit=launcher.limits.input_bytes,
                    output_limit=launcher.limits.stdout_bytes, deadline=end,
                    check_control=relay_check,
                )
                async with asyncio.timeout_at(end):
                    result = await launcher.exchange(
                        launcher.claude.command, workspace=None, posture=Posture.READ,
                        guard_fds=(custody.lock_fd,),
                        conversation=qualification_conversation,
                        timeout_s=end - loop.time(), native_store=native_store,
                    )
            else:
                assert selected_plan is not None
                async with asyncio.timeout_at(end):
                    observation = await observe_maintenance_mode(
                        launcher, native_store,
                        phase=(ClaudeMaintenancePhase.OBSERVE
                               if phase is ClaudeMaintenanceSessionPhase.OBSERVE
                               else ClaudeMaintenancePhase.RELOAD),
                        selected_plan=selected_plan, timeout_s=min(
                            MODE_SECONDS, end - loop.time(),
                        ),
                    )
        relay_closed = relay.closed is True
    except BaseException as error:
        body_error = error
        if isinstance(error, ProcessExchangeError):
            result = error.result
        if relay is not None:
            relay_closed = relay.closed is True

    # The relay and process have joined. Private stderr is not a public report.
    if ((login or phase is ClaudeMaintenanceSessionPhase.QUALIFY)
            and result is not None and (type(result) is not ProcessResult
                                          or type(result.stdout) is not bytes
                                          or (login and len(result.stdout) > LOGIN_OUTPUT_BYTES)
                                          or (phase is ClaudeMaintenanceSessionPhase.QUALIFY
                                              and len(result.stdout) > MODE_OUTPUT_BYTES)
                                          or type(result.stderr) is not bytes
                                          or len(result.stderr) > STDERR_BYTES)):
        cleanup_errors.append(ValueError("Claude maintenance process output refused"))
    if (login and operator is not None and result is not None and relay_closed is True
            and loop.time() < end and not cleanup_errors and result.stderr
            and (body_error is None or (isinstance(body_error, Exception)
                                        and not _cancelled(body_error)))):
        try:
            async with asyncio.timeout_at(end):
                await operator.write_stderr(result.stderr)
        except BaseException as error:
            cleanup_errors.append(error)
    if operator is not None:
        try:
            operator.invalidate()
        except BaseException as error:
            cleanup_errors.append(error)
    if credential_fd is not None:
        try:
            os.close(credential_fd)
            credential_closed = True
        except BaseException as error:
            credential_closed = False
            cleanup_errors.append(error)
    if initial is not None:
        try:
            terminal = custody.check()
            custody_current = type(terminal) is BindingCheck and terminal == initial
        except BaseException as error:
            custody_current = False
            cleanup_errors.append(error)

    if ((body_error is not None and _cancelled(body_error))
            or any(_cancelled(error) for error in cleanup_errors)):
        raise asyncio.CancelledError("Claude maintenance session cancelled") from None
    if body_error is not None and not isinstance(body_error, Exception):
        raise body_error
    for cleanup_failure in cleanup_errors:
        if not isinstance(cleanup_failure, Exception):
            raise cleanup_failure
    login_facts = login_conversation.facts if login_conversation is not None else None
    process_clean = _clean(result) if (
        login or phase is ClaudeMaintenanceSessionPhase.QUALIFY
    ) and result is not None else None
    qualification = (qualification_conversation.facts
                     if qualification_conversation is not None else None)
    complete = (
        body_error is None and not cleanup_errors and loop.time() < end
        and relay_closed is True and credential_closed is True and custody_current is True
        and ((login and process_clean is True and login_facts is not None
              and login_facts.lifecycle is ClaudeLoginConversationLifecycle.COMPLETED)
             or (not login and observation is not None
                 and observation.lifecycle is ClaudeMaintenanceLifecycle.OBSERVED)
             or (phase is ClaudeMaintenanceSessionPhase.QUALIFY
                 and process_clean is True and qualification is not None
                 and qualification.lifecycle is ClaudeQualificationLifecycle.QUALIFIED))
    )
    incomplete = (isinstance(body_error, TimeoutError)
                  or (observation is not None
                      and observation.lifecycle is ClaudeMaintenanceLifecycle.INCOMPLETE)
                  or (initial is not None and loop.time() >= end))
    lifecycle = (ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN if complete
                 else ClaudeMaintenanceSessionLifecycle.INCOMPLETE if incomplete
                 else ClaudeMaintenanceSessionLifecycle.REFUSED)
    return ClaudeMaintenanceSessionFacts(
        phase, lifecycle, login_facts, observation, process_clean, relay_closed,
        custody_current, credential_closed, qualification,
    )
