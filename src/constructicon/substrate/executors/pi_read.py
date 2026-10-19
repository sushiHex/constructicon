"""One credential-free scripted READ task on the existing owned process seam.

This direct executor publishes no provider descriptor or availability. Leased
assembly and durable recovery are deliberately subsequent work; trusted tests
supply an existing acquisition's guards. No Pi binary or provider is launched.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from pathlib import Path

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorGrantPolicy,
    ExecutorOutcome,
    ExecutorProfile,
    TaskSpec,
)
from constructicon.core.grants import EffectiveGrants, IsolationProfile, Posture
from constructicon.core.process import ProcessIO
from constructicon.core.workspace import WorkspaceView
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessLimits
from constructicon.substrate.executors.pi_protocol import PiDecoder, encoded

PI_LIMITS = ProcessLimits(input_bytes=65536, stdout_bytes=1048576,
                          record_bytes=65536, stderr_bytes=16384)
PI_PROFILE = ExecutorProfile(
    name="scripted-pi-read", structured_output=False, postures=frozenset({Posture.READ}),
    isolation=IsolationProfile(filesystem="read_only_snapshot", process_tree_owned=True,
                               environment_allowlisted=True, network_enforced=True),
    accepted_efforts=frozenset({"off"}),
    grant_policy=ExecutorGrantPolicy(tool_sets=(("read",),), network_modes=("none",),
                                    network_access="none", environment_names=(),
                                    workspace_required=True),
)


class PiReadConversation:
    """One reader before dispatch; sole writer; terminal half-close then EOF."""

    def __init__(self, task: TaskSpec, *, input_limit: int) -> None:
        self.decoder = PiDecoder(task.instruction)
        self.input_limit = input_limit
        self.spent = 0
        self.entered = self.poisoned = False
        self.changed = asyncio.Event()

    async def __call__(self, io: ProcessIO) -> None:
        if self.entered:
            self.poisoned = True
            self.decoder.refused = True
            raise ContractViolation("Pi fixture conversation is single-use")
        self.entered = True
        read_entered = asyncio.Event()

        async def read() -> None:
            try:
                while True:
                    read_entered.set()
                    chunk = await io.read(8192)
                    if type(chunk) is not bytes or len(chunk) > 8192:
                        raise ContractViolation("Pi byte reader violated its bound")
                    if not chunk:
                        self.decoder.finish()
                        return
                    self.decoder.feed(chunk)
                    self.changed.set()
            finally:
                self.changed.set()

        reader = asyncio.create_task(read(), name="pi-read-reader")

        async def wait_for(predicate: Callable[[], bool]) -> None:
            while not predicate() and not self.decoder.stopped and not self.poisoned:
                self.changed.clear()
                if reader.done():
                    await reader
                    return
                await self.changed.wait()

        async def send(command: str) -> None:
            identifier = secrets.token_hex(16)
            payload = {"type": command, "id": identifier}
            if command == "prompt":
                payload["message"] = self.decoder.instruction
            raw = encoded(payload) + b"\n"
            self.spent += len(raw)
            if self.spent > self.input_limit:
                self.decoder.refused = True
                return
            self.decoder.request(command, identifier)
            if not self.decoder.stopped:
                await io.write(raw)

        primary: BaseException | None = None
        try:
            await read_entered.wait()  # Reader has entered read before any write can deliver.
            await send("get_state")
            await wait_for(lambda: self.decoder.state_observed)
            if not self.decoder.stopped and not self.poisoned:
                await send("prompt")
                await wait_for(lambda: self.decoder.accepted and self.decoder.settled)
            await io.close_stdin()
            await reader  # EOF is affirmative, including every trailing byte.
        except BaseException as error:
            primary = error
            self.poisoned = True
            self.decoder.refused = True
            raise
        finally:
            if not reader.done():
                reader.cancel()
            try:
                await finish_owned(reader)
            except asyncio.CancelledError:
                if primary is None:
                    raise
            except BaseException as secondary:
                if primary is None or secondary is primary:
                    raise
                raise primary from secondary


class PiReadExecutor:
    """Single-use task adapter for an already-owned scripted fixture launch."""

    def __init__(self, launcher: LinuxLauncher, command: tuple[str, ...], *,
                 guard_fds: tuple[int, ...],
                 check_control: Callable[[], None] | None = None) -> None:
        if launcher.limits != PI_LIMITS or launcher.vendor is not None:
            raise ContractViolation("Pi fixture requires its exact networkless launch profile")
        if not command or not guard_fds:
            raise ContractViolation("Pi fixture requires a fixed command and acquisition guards")
        self.launcher = launcher
        self.command = command
        self.guard_fds = guard_fds
        self.check_control = check_control
        self.entered = False
        self.conversation: PiReadConversation | None = None

    @property
    def profile(self) -> ExecutorProfile:
        return PI_PROFILE

    def validate_grants(self, grants: EffectiveGrants) -> tuple[str, ...]:
        faults = self.profile.grant_faults(grants)
        if (grants.model_selection.kind != "explicit"
                or grants.model_selection.model != "fixture/pi-read"):
            faults += ("Pi fixture requires fixture/pi-read",)
        if grants.effort != "off":
            faults += ("Pi fixture requires explicit effort off",)
        return faults

    async def execute(self, task: TaskSpec, *, workspace: WorkspaceView | None,
                      grants: EffectiveGrants) -> ExecutorOutcome:
        if self.entered:
            if self.conversation is not None:
                self.conversation.poisoned = True
                self.conversation.decoder.refused = True
                self.conversation.changed.set()
            raise ContractViolation("Pi fixture executor is single-use")
        self.entered = True
        faults = self.validate_grants(grants)
        if not isinstance(workspace, WorkspaceView):
            faults += ("Pi fixture requires an admitted workspace",)
        if task.context or task.response_schema is not None:
            faults += ("Pi fixture supports instruction-only tasks",)
        if self.launcher.limits != PI_LIMITS or self.launcher.vendor is not None:
            faults += ("Pi fixture launch inputs changed",)
        if faults:
            return ExecutorFailure(error=ExecutorError(
                kind="unavailable", detail="Pi fixture profile refused",
            ))
        assert workspace is not None
        if self.check_control is not None:
            self.check_control()
        self.conversation = PiReadConversation(task, input_limit=PI_LIMITS.input_bytes)
        result = await self.launcher.exchange(
            self.command, workspace=Path(workspace.path), posture=Posture.READ,
            guard_fds=self.guard_fds, conversation=self.conversation,
            timeout_s=grants.timeout_s,
        )
        if self.check_control is not None:
            self.check_control()
        return self.conversation.decoder.outcome(result)
