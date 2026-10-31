"""Credential-free composition checks for the attended maintenance session."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from dataclasses import fields
from pathlib import Path
from typing import Any, ClassVar

import pytest

from constructicon.core.identity import digest
from constructicon.substrate.executors.claude_maintenance_mode import (
    ClaudeMaintenanceLifecycle,
    ClaudeMaintenanceObservation,
    ClaudeMaintenancePhase,
)
from constructicon.substrate.executors.claude_maintenance_session import (
    ClaudeMaintenanceSessionLifecycle,
    ClaudeMaintenanceSessionPhase,
    run_maintenance_session,
)
from constructicon.substrate.executors.claude_native import ClaudeNativeRecipe
from constructicon.substrate.executors.claude_protocol import (
    ClaudeApiKeySourceCategory,
    ClaudeAuthMode,
    ClaudeInitializeVerdict,
    ClaudeTokenSourceCategory,
)
from constructicon.substrate.executors.egress import EgressDestination, EgressPolicy, EgressSocket
from constructicon.substrate.executors.linux import ProcessLimits, ProcessResult
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.substrate.test_claude_startup_qualification import Channel


class Custody:
    lock_fd = 40

    def __init__(self) -> None:
        self.binding = BindingCheck(digest("test-maintenance", 1, "one"))
        self.checks = 0
        self.opened = 0
        self.created = 0
        self.fd: int | None = None
        self.other_fd: int | None = None
        self.changed = False

    def check(self) -> BindingCheck:
        self.checks += 1
        if self.changed:
            return BindingCheck(digest("test-maintenance", 1, "other"))
        return self.binding

    def open_credential(self) -> int:
        self.opened += 1
        self.fd, self.other_fd = os.pipe()
        return self.fd

    def create_credential(self) -> None:
        self.created += 1

    def finish(self) -> None:
        if self.other_fd is not None:
            os.close(self.other_fd)


class Operator:
    def __init__(self) -> None:
        self.stdout: list[bytes] = []
        self.stderr: list[bytes] = []
        self.invalidated = 0

    async def read_line(self) -> bytes:
        return b"opaque response\n"

    async def write_stdout(self, data: bytes) -> None:
        self.stdout.append(data)

    async def write_stderr(self, data: bytes) -> None:
        self.stderr.append(data)

    def invalidate(self) -> None:
        self.invalidated += 1


class NativeIO:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False
        self.eof = asyncio.Event()

    async def read(self, maximum: int = 8192) -> bytes:
        if not self.closed:
            await self.eof.wait()
        return b""

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def close_stdin(self) -> None:
        self.closed = True
        self.eof.set()


class Launcher:
    claude = object()
    claude_recipe = ClaudeNativeRecipe.LOGIN
    limits = ProcessLimits(input_bytes=4096, stdout_bytes=256 * 1024,
                           record_bytes=256 * 1024, stderr_bytes=64 * 1024)

    def __init__(self) -> None:
        self.calls = 0
        self.native = NativeIO()
        self.fail = False

    async def exchange(self, command: tuple[str, ...], **kwargs: Any) -> ProcessResult:
        self.calls += 1
        kwargs["native_store"].before_spawn()
        await kwargs["conversation"](self.native)
        if self.fail:
            return ProcessResult(1, b"", b"private", 0, payload_returncode=1)
        return ProcessResult(0, b"", b"private", 0, payload_returncode=0)


class QualificationLauncher(Launcher):
    claude_recipe = ClaudeNativeRecipe.STREAM_JSON
    claude = type("Vendor", (), {"command": ("fixed-claude-stream",),
                                 "model": "claude-sonnet-4-6", "effort": "low"})()
    limits = ProcessLimits(input_bytes=8192, stdout_bytes=512 * 1024,
                           record_bytes=256 * 1024, stderr_bytes=64 * 1024)

    def __init__(self, *, mode: str = "Claude Pro", clean: bool = True,
                 stdout: bytes = b"") -> None:
        super().__init__()
        self.native = Channel(mode=mode)
        self.clean = clean
        self.stdout = stdout
        self.joined = False

    async def exchange(self, command: tuple[str, ...], **kwargs: Any) -> ProcessResult:
        self.calls += 1
        kwargs["native_store"].before_spawn()
        try:
            await kwargs["conversation"](self.native)
            return ProcessResult(0 if self.clean else 1, self.stdout, b"", 0,
                                 payload_returncode=0 if self.clean else 1)
        finally:
            self.joined = True


@pytest.mark.asyncio
async def test_qualification_requires_three_controls_and_joined_lifecycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher = Custody(), QualificationLauncher()
    try:
        facts = await run_maintenance_session(
            custody, launcher, policy("platform.claude.com", "api.anthropic.com"),
            tmp_path / "lane", phase=ClaudeMaintenanceSessionPhase.QUALIFY,
            mode=ClaudeAuthMode.SUBSCRIPTION,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN
        assert facts.qualification is not None
        assert facts.qualification.request_writes == 3
        assert facts.process_clean is True
        assert facts.custody_current is facts.credential_closed is facts.relay_closed is True
        assert custody.checks >= 8
        assert launcher.joined is True
        assert launcher.native.writes == ["initialize", "get_settings", "get_hooks_listing"]
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_qualification_custody_change_during_initialize_blocks_later_controls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher = Custody(), QualificationLauncher()

    class ChangeDuringInitialize(Channel):
        async def write(self, raw: bytes) -> None:
            await super().write(raw)
            custody.changed = True

    launcher.native = ChangeDuringInitialize()
    try:
        facts = await run_maintenance_session(
            custody, launcher, policy("platform.claude.com", "api.anthropic.com"),
            tmp_path / "lane", phase=ClaudeMaintenanceSessionPhase.QUALIFY,
            mode=ClaudeAuthMode.SUBSCRIPTION,
        )
        assert launcher.native.writes == ["initialize"]
        assert launcher.joined is True
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert facts.custody_current is False
        assert facts.relay_closed is facts.credential_closed is True
    finally:
        custody.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,clean", [("Claude API", True), ("Claude Pro", False)])
async def test_qualification_refuses_ambiguity_or_unclean_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str, clean: bool,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher = Custody(), QualificationLauncher(mode=mode, clean=clean)
    try:
        try:
            facts = await run_maintenance_session(
                custody, launcher, policy("platform.claude.com", "api.anthropic.com"),
                tmp_path / "lane", phase=ClaudeMaintenanceSessionPhase.QUALIFY,
                mode=ClaudeAuthMode.SUBSCRIPTION,
            )
        except ValueError:
            pytest.fail("an unclean process must return finite refusal facts")
        assert facts.lifecycle is not ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN
        assert facts.custody_current is facts.credential_closed is facts.relay_closed is True
        if mode == "Claude API":
            assert launcher.native.writes == ["initialize"]
        else:
            assert facts.process_clean is False
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_qualification_policy_refuses_before_store_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher = Custody(), QualificationLauncher()
    facts = await run_maintenance_session(
        custody, launcher, policy("platform.claude.com"), tmp_path / "lane",
        phase=ClaudeMaintenanceSessionPhase.QUALIFY, mode=ClaudeAuthMode.SUBSCRIPTION,
    )
    assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
    assert launcher.calls == custody.opened == custody.created == 0
    assert facts.qualification is None


@pytest.mark.asyncio
async def test_qualification_malicious_result_bound_refuses_after_join(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher = Custody(), QualificationLauncher(stdout=b"x" * (512 * 1024 + 1))
    try:
        facts = await run_maintenance_session(
            custody, launcher, policy("platform.claude.com", "api.anthropic.com"),
            tmp_path / "lane", phase=ClaudeMaintenanceSessionPhase.QUALIFY,
            mode=ClaudeAuthMode.SUBSCRIPTION,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert facts.qualification is not None
        assert facts.qualification.lifecycle.value == "qualified"
        assert facts.custody_current is facts.credential_closed is facts.relay_closed is True
    finally:
        custody.finish()


class Relay:
    instances: ClassVar[list[Relay]] = []

    def __init__(self, policy: EgressPolicy, directory: Path, deadline: float,
                 check_control: Any) -> None:
        self.policy = policy
        self.check_control = check_control
        self.closed = False
        self.entered = False
        self.instances.append(self)

    async def __aenter__(self) -> EgressSocket:
        self.entered = True
        self.check_control()
        return EgressSocket(Path("/tmp/fake-maintenance.sock"), (1, 2))

    async def __aexit__(self, *_args: object) -> None:
        self.closed = True


def policy(*hosts: str) -> EgressPolicy:
    return EgressPolicy(tuple(EgressDestination(host, 443, "8.8.8.8") for host in hosts), 3)


@pytest.mark.asyncio
async def test_login_joined_but_not_authentication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher, operator = Custody(), Launcher(), Operator()
    try:
        facts = await run_maintenance_session(
            custody, launcher, policy("platform.claude.com"), tmp_path / "lane",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator, first_login=True,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN
        assert facts.process_clean is True
        assert facts.relay_closed is True
        assert facts.custody_current is True
        assert facts.credential_closed is True
        assert facts.login_facts is not None
        assert facts.mode_observation is None
        assert operator.stderr == [b"private"]
        assert operator.invalidated == 1
        assert launcher.native.writes == [b"opaque response\n"]
        assert custody.created == custody.opened == 1
        assert custody.checks >= 3
        assert custody.fd is not None
        with pytest.raises(OSError):
            os.fstat(custody.fd)
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_login_preflight_refuses_before_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher, operator = Custody(), Launcher(), Operator()
    facts = await run_maintenance_session(
        custody, launcher, policy("platform.claude.com", "api.anthropic.com"),
        tmp_path / "lane", phase=ClaudeMaintenanceSessionPhase.LOGIN,
        operator=operator,
    )
    assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
    assert launcher.calls == custody.opened == custody.created == 0
    assert operator.invalidated == 1
    assert not Relay.instances or Relay.instances[-1].policy != policy(
        "platform.claude.com", "api.anthropic.com")


@pytest.mark.asyncio
async def test_mode_observation_is_one_separate_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    calls: list[tuple[ClaudeMaintenancePhase, ClaudeAuthMode]] = []

    async def fake_observe(_launcher: Any, native_store: Any, *,
                           phase: ClaudeMaintenancePhase, mode: ClaudeAuthMode,
                           timeout_s: float) -> ClaudeMaintenanceObservation:
        assert timeout_s > 0
        native_store.before_spawn()
        calls.append((phase, mode))
        return ClaudeMaintenanceObservation(
            phase, ClaudeInitializeVerdict.MODE_MATCH,
            ClaudeMaintenanceLifecycle.OBSERVED, 1, 0, True, True,
            token_source_category=ClaudeTokenSourceCategory.ABSENT,
            api_key_source_category=ClaudeApiKeySourceCategory.ABSENT,
        )

    monkeypatch.setattr(session, "EgressRelay", Relay)
    monkeypatch.setattr(session, "observe_maintenance_mode", fake_observe)
    custody, launcher = Custody(), Launcher()
    launcher.claude_recipe = ClaudeNativeRecipe.STREAM_JSON
    try:
        facts = await run_maintenance_session(
            custody, launcher, policy("platform.claude.com", "api.anthropic.com"),
            tmp_path / "lane", phase=ClaudeMaintenanceSessionPhase.RELOAD,
            mode=ClaudeAuthMode.SUBSCRIPTION,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN
        assert facts.process_clean is None
        assert facts.login_facts is None
        assert facts.mode_observation is not None
        assert calls == [(ClaudeMaintenancePhase.RELOAD, ClaudeAuthMode.SUBSCRIPTION)]
        assert launcher.calls == custody.created == 0
        assert custody.opened == 1
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_bad_process_and_changed_terminal_custody_demote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher, operator = Custody(), Launcher(), Operator()
    launcher.fail = True
    try:
        facts = await run_maintenance_session(
            custody, launcher, policy("platform.claude.com"), tmp_path / "lane",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert facts.process_clean is False
        assert facts.credential_closed is True
        assert custody.created == 0  # Existing store; never infer first login.
    finally:
        custody.finish()

    custody, launcher, operator = Custody(), Launcher(), Operator()
    original_exchange = launcher.exchange

    async def changing_exchange(*args: Any, **kwargs: Any) -> ProcessResult:
        result = await original_exchange(*args, **kwargs)
        custody.changed = True
        return result

    launcher.exchange = changing_exchange  # type: ignore[method-assign]
    try:
        facts = await run_maintenance_session(
            custody, launcher, policy("platform.claude.com"), tmp_path / "other",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert facts.process_clean is True
        assert facts.custody_current is False
        assert facts.credential_closed is True
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_cancellation_joins_relay_before_return(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    started, joined, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class WaitingRelay(Relay):
        async def __aexit__(self, *_args: object) -> None:
            joined.set()
            await release.wait()
            self.closed = True

    class WaitingLauncher(Launcher):
        async def exchange(self, command: tuple[str, ...], **kwargs: Any) -> ProcessResult:
            kwargs["native_store"].before_spawn()
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    monkeypatch.setattr(session, "EgressRelay", WaitingRelay)
    custody, operator = Custody(), Operator()
    try:
        task = asyncio.create_task(run_maintenance_session(
            custody, WaitingLauncher(), policy("platform.claude.com"), tmp_path / "lane",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator,
        ))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.wait_for(joined.wait(), 1)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert custody.checks >= 3
        assert operator.invalidated == 1
        assert custody.fd is not None
        with pytest.raises(OSError):
            os.fstat(custody.fd)
    finally:
        release.set()
        custody.finish()


@pytest.mark.asyncio
async def test_postjoin_cancellation_survives_invalidation_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    class FailingOperator(Operator):
        async def write_stderr(self, data: bytes) -> None:
            raise asyncio.CancelledError("private stderr transport")

        def invalidate(self) -> None:
            self.invalidated += 1
            raise RuntimeError("private invalidation")

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, operator = Custody(), FailingOperator()
    try:
        cancelled = False
        try:
            await run_maintenance_session(
                custody, Launcher(), policy("platform.claude.com"), tmp_path / "lane",
                phase=ClaudeMaintenanceSessionPhase.LOGIN,
                operator=operator,
            )
        except asyncio.CancelledError:
            cancelled = True
        assert cancelled
        assert operator.invalidated == 1
        assert custody.checks >= 3
        assert custody.fd is not None
        with pytest.raises(OSError):
            os.fstat(custody.fd)
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_failed_final_invalidation_cannot_publish_joined_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    class FailingOperator(Operator):
        def invalidate(self) -> None:
            self.invalidated += 1
            raise RuntimeError("private invalidation")

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, operator = Custody(), FailingOperator()
    try:
        facts = await run_maintenance_session(
            custody, Launcher(), policy("platform.claude.com"), tmp_path / "lane",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert facts.process_clean is True
        assert facts.credential_closed is True
        assert operator.invalidated == 1
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_preflight_requires_login_recipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher, operator = Custody(), Launcher(), Operator()
    launcher.claude_recipe = ClaudeNativeRecipe.STREAM_JSON
    facts = await run_maintenance_session(
        custody, launcher, policy("platform.claude.com"), tmp_path / "lane",
        phase=ClaudeMaintenanceSessionPhase.LOGIN,
        operator=operator,
    )
    assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
    assert custody.checks == custody.opened == custody.created == launcher.calls == 0
    assert operator.invalidated == 1


@pytest.mark.asyncio
async def test_login_launcher_input_budget_is_preflight_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher, operator = Custody(), Launcher(), Operator()
    launcher.limits = ProcessLimits(
        input_bytes=4097, stdout_bytes=256 * 1024,
        record_bytes=256 * 1024, stderr_bytes=64 * 1024,
    )
    facts = await run_maintenance_session(
        custody, launcher, policy("platform.claude.com"), tmp_path / "lane",
        phase=ClaudeMaintenanceSessionPhase.LOGIN,
        operator=operator,
    )
    assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
    assert custody.checks == custody.opened == launcher.calls == 0


@pytest.mark.asyncio
async def test_borrowed_lock_is_never_closed_on_bad_credential_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    class AliasedCustody(Custody):
        def open_credential(self) -> int:
            self.opened += 1
            return self.lock_fd

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, operator = AliasedCustody(), Operator()
    lock, other = os.pipe()
    custody.lock_fd = lock
    try:
        facts = await run_maintenance_session(
            custody, Launcher(), policy("platform.claude.com"), tmp_path / "lane",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert facts.credential_closed is None
        assert custody.opened == 1
        try:
            os.fstat(lock)
            lock_alive = True
        except OSError:
            lock_alive = False
        assert lock_alive
    finally:
        # Preserve the body assertion if a mutant closed the borrowed lock.
        with suppress(OSError):
            os.close(lock)
        os.close(other)


@pytest.mark.asyncio
async def test_malformed_private_result_never_becomes_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    class MalformedLauncher(Launcher):
        async def exchange(self, command: tuple[str, ...], **kwargs: Any) -> ProcessResult:
            kwargs["native_store"].before_spawn()
            await kwargs["conversation"](self.native)
            return ProcessResult(0, b"", 123, 0, payload_returncode=0)  # type: ignore[arg-type]

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, operator = Custody(), Operator()
    try:
        facts = await run_maintenance_session(
            custody, MalformedLauncher(), policy("platform.claude.com"), tmp_path / "lane",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert facts.process_clean is True  # Process codes only; output guard separately refuses.
        assert operator.stderr == []
        assert facts.credential_closed is True
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_expired_or_overlong_deadline_refuses_before_custody(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, operator = Custody(), Operator()
    now = asyncio.get_running_loop().time()
    for end in (now - 1, now + 601):
        facts = await run_maintenance_session(
            custody, Launcher(), policy("platform.claude.com"), tmp_path / "lane",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator, deadline=end,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert custody.checks == custody.opened == 0
    assert operator.invalidated == 2


@pytest.mark.asyncio
async def test_preparation_consumes_the_same_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    loop = asyncio.get_running_loop()
    base = loop.time()
    offset = [0.0]
    monkeypatch.setattr(loop, "time", lambda: base + offset[0])

    class SlowCustody(Custody):
        def check(self) -> BindingCheck:
            if self.checks == 0:
                offset[0] = 11.0
            return super().check()

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody = SlowCustody()
    facts = await run_maintenance_session(
        custody, Launcher(), policy("platform.claude.com"), tmp_path / "lane",
        phase=ClaudeMaintenanceSessionPhase.LOGIN,
        operator=Operator(), deadline=base + 10.0,
    )
    assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.INCOMPLETE
    assert custody.opened == 0
    assert custody.checks >= 3  # Terminal check occurs after elapsed D.


@pytest.mark.asyncio
async def test_malicious_result_byte_bounds_refuse_joined_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    class OversizedLauncher(Launcher):
        def __init__(self, *, stdout: bool) -> None:
            super().__init__()
            self.stdout = stdout

        async def exchange(self, command: tuple[str, ...], **kwargs: Any) -> ProcessResult:
            kwargs["native_store"].before_spawn()
            await kwargs["conversation"](self.native)
            return ProcessResult(
                0, b"x" * (256 * 1024 + 1) if self.stdout else b"",
                b"x" * (64 * 1024 + 1) if not self.stdout else b"", 0,
                payload_returncode=0,
            )

    monkeypatch.setattr(session, "EgressRelay", Relay)
    for stdout in (True, False):
        custody, operator = Custody(), Operator()
        try:
            facts = await run_maintenance_session(
                custody, OversizedLauncher(stdout=stdout),
                policy("platform.claude.com"), tmp_path / f"lane-{stdout}",
                phase=ClaudeMaintenanceSessionPhase.LOGIN,
                operator=operator,
            )
            assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
            assert facts.process_clean is True
            assert operator.stderr == []
            assert facts.credential_closed is True
        finally:
            custody.finish()


@pytest.mark.asyncio
async def test_prelaunch_binding_mismatch_never_opens_credential(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    class ChangingCustody(Custody):
        def check(self) -> BindingCheck:
            result = super().check()
            if self.checks == 1:
                self.changed = True
            return result

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody = ChangingCustody()
    facts = await run_maintenance_session(
        custody, Launcher(), policy("platform.claude.com"), tmp_path / "lane",
        phase=ClaudeMaintenanceSessionPhase.LOGIN,
        operator=Operator(), first_login=True,
    )
    assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
    assert facts.custody_current is False
    assert custody.opened == custody.created == 0
    assert custody.checks >= 3


@pytest.mark.asyncio
async def test_first_login_creation_failure_is_not_reinterpreted_as_existing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    class ExistingCustody(Custody):
        def create_credential(self) -> None:
            self.created += 1
            raise FileExistsError("existing private credential")

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody = ExistingCustody()
    facts = await run_maintenance_session(
        custody, Launcher(), policy("platform.claude.com"), tmp_path / "lane",
        phase=ClaudeMaintenanceSessionPhase.LOGIN,
        operator=Operator(), first_login=True,
    )
    assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
    assert custody.created == 1
    assert custody.opened == 0
    assert facts.credential_closed is None


@pytest.mark.asyncio
async def test_deadline_does_not_abandon_relay_join_or_start_new_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    loop = asyncio.get_running_loop()
    base = loop.time()
    offset = [0.0]
    monkeypatch.setattr(loop, "time", lambda: base + offset[0])

    class SlowExitRelay(Relay):
        async def __aexit__(self, *_args: object) -> None:
            offset[0] = 11.0
            self.closed = True

    monkeypatch.setattr(session, "EgressRelay", SlowExitRelay)
    custody, operator = Custody(), Operator()
    try:
        facts = await run_maintenance_session(
            custody, Launcher(), policy("platform.claude.com"), tmp_path / "lane",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator, deadline=base + 10.0,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.INCOMPLETE
        assert facts.process_clean is True
        assert facts.login_facts is not None
        assert facts.login_facts.lifecycle.value == "completed"
        assert facts.relay_closed is True
        assert facts.custody_current is True
        assert facts.credential_closed is True
        assert operator.stderr == []
        assert operator.invalidated == 1
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_relay_exit_failure_and_missing_callback_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    class FailedExitRelay(Relay):
        async def __aexit__(self, *_args: object) -> None:
            raise RuntimeError("private relay exit")

    monkeypatch.setattr(session, "EgressRelay", FailedExitRelay)
    custody, operator = Custody(), Operator()
    try:
        facts = await run_maintenance_session(
            custody, Launcher(), policy("platform.claude.com"), tmp_path / "lane",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert facts.relay_closed is False
        assert facts.credential_closed is True
        assert operator.stderr == []
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_terminal_check_requires_exact_positive_binding_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    class EqualImpostor:
        def __init__(self, original: BindingCheck) -> None:
            self.original = original

        def __eq__(self, other: object) -> bool:
            return other == self.original

    class TerminalImpostorCustody(Custody):
        def check(self) -> BindingCheck:
            self.checks += 1
            if self.checks >= 7:
                return EqualImpostor(self.binding)  # type: ignore[return-value]
            return self.binding

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, operator = TerminalImpostorCustody(), Operator()
    try:
        facts = await run_maintenance_session(
            custody, Launcher(), policy("platform.claude.com"), tmp_path / "lane",
            phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=operator,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert facts.custody_current is False
        assert facts.process_clean is True
        assert custody.checks >= 7
    finally:
        custody.finish()


@pytest.mark.asyncio
async def test_missing_login_callback_cannot_claim_joined_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from constructicon.substrate.executors import claude_maintenance_session as session

    class NoCallbackLauncher(Launcher):
        async def exchange(self, command: tuple[str, ...], **kwargs: Any) -> ProcessResult:
            kwargs["native_store"].before_spawn()
            return ProcessResult(0, b"", b"", 0, payload_returncode=0)

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody = Custody()
    try:
        facts = await run_maintenance_session(
            custody, NoCallbackLauncher(), policy("platform.claude.com"),
            tmp_path / "other", phase=ClaudeMaintenanceSessionPhase.LOGIN,
            operator=Operator(),
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
        assert facts.process_clean is True
        assert facts.login_facts is not None
        assert facts.login_facts.lifecycle.value == "new"
    finally:
        custody.finish()


def test_public_shape_is_finite() -> None:
    assert {item.name for item in fields(session_facts_type())} == {
        "phase", "lifecycle", "login_facts", "mode_observation", "process_clean",
        "relay_closed", "custody_current", "credential_closed", "qualification",
    }


def session_facts_type() -> type[Any]:
    from constructicon.substrate.executors.claude_maintenance_session import (
        ClaudeMaintenanceSessionFacts,
    )

    return ClaudeMaintenanceSessionFacts


@pytest.mark.asyncio
async def test_write_qualification_executes_selected_command(monkeypatch, tmp_path):
    from constructicon.substrate.executors import claude_maintenance_session as session

    monkeypatch.setattr(session, "EgressRelay", Relay)
    custody, launcher = Custody(), QualificationLauncher()
    launcher.claude_recipe = ClaudeNativeRecipe.STREAM_JSON_WRITE
    launcher.claude = type("Vendor", (), {
        "command": ("fixed", "--allowedTools", "mcp__constructicon_read__read_file"),
        "model": "claude-sonnet-4-6", "effort": "low",
    })()
    original = launcher.exchange
    commands = []

    async def record(command, **kwargs):
        commands.append(command)
        return await original(command, **kwargs)

    launcher.exchange = record
    try:
        facts = await run_maintenance_session(
            custody, launcher, policy("platform.claude.com", "api.anthropic.com"),
            tmp_path / "lane", phase=ClaudeMaintenanceSessionPhase.QUALIFY,
            mode=ClaudeAuthMode.SUBSCRIPTION,
        )
        assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN
        assert commands == [(
            "fixed", "--allowedTools", "mcp__constructicon_write__contained_python",
        )]
    finally:
        custody.finish()
