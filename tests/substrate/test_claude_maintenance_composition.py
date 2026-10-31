"""Credential-free composition of separate Claude maintenance phases.

The launcher is fake: these tests prove callback, custody, and session assembly,
not the physical native recipe or vendor behavior.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

import pytest

from constructicon.core.identity import digest
from constructicon.substrate.executors import claude_lane, egress
from constructicon.substrate.executors import claude_maintenance_session as session
from constructicon.substrate.executors.claude_maintenance_mode import (
    ClaudeMaintenanceLifecycle,
)
from constructicon.substrate.executors.claude_maintenance_session import (
    ClaudeMaintenanceSessionLifecycle,
    ClaudeMaintenanceSessionPhase,
)
from constructicon.substrate.executors.claude_native import (
    LOGIN_COMMAND,
    ClaudeNativeRecipe,
)
from constructicon.substrate.executors.claude_protocol import ClaudeAuthMode
from constructicon.substrate.executors.egress import (
    EgressDestination,
    EgressPolicy,
    EgressSocket,
)
from constructicon.substrate.executors.linux import ProcessLimits, ProcessResult
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.substrate.test_claude_lane import args, configuration

MARKER = b"synthetic-retained-mode-state"
STREAM_COMMAND = ("synthetic-claude-stream",)


def _policy(*hosts: str) -> EgressPolicy:
    return EgressPolicy(
        tuple(EgressDestination(host, 443, "8.8.8.8") for host in hosts), 3,
    )


def _response(identifier: str) -> bytes:
    return json.dumps({"type": "control_response", "response": {
        "subtype": "success", "request_id": identifier,
        "response": {"claude_code_version": "2.1.296", "session_state": "idle",
                     "account": {"apiProvider": "firstParty",
                                 "subscriptionType": "Claude Pro"}},
        "pending_permission_requests": [], "pending_user_dialog_requests": [],
    }}, separators=(",", ":")).encode() + b"\n"


class RetainedCustody:
    """Stable synthetic binding and one real retained file, no real credentials."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.binding = BindingCheck(digest("composition-binding", 1, "retained"))
        self.lock_fd = os.open(path.parent / "synthetic-lock", os.O_CREAT | os.O_RDWR, 0o600)
        self.created = 0
        self.opened: list[int] = []
        self.checks = 0

    def check(self) -> BindingCheck:
        self.checks += 1
        return self.binding

    def create_credential(self) -> None:
        self.created += 1
        with self.path.open("xb"):
            pass

    def open_credential(self) -> int:
        fd = os.open(self.path, os.O_RDWR)
        self.opened.append(fd)
        return fd

    def close(self) -> None:
        os.close(self.lock_fd)


class Operator:
    def __init__(self) -> None:
        self.stdout: list[bytes] = []
        self.stderr: list[bytes] = []
        self.invalidated = False

    async def read_line(self) -> bytes:
        return b"synthetic-operator-line\n"

    async def write_stdout(self, data: bytes) -> None:
        self.stdout.append(data)

    async def write_stderr(self, data: bytes) -> None:
        self.stderr.append(data)

    def invalidate(self) -> None:
        self.invalidated = True


class NativeIO:
    def __init__(self, phase: ClaudeMaintenanceSessionPhase, persisted: bool) -> None:
        self.phase = phase
        self.persisted = persisted
        self.output = bytearray()
        self.changed = asyncio.Event()
        self.writes: list[bytes] = []
        self.stdin_closed = False
        self.active_readers = 0
        self.max_readers = 0

    async def read(self, maximum: int = 8192) -> bytes:
        self.active_readers += 1
        self.max_readers = max(self.max_readers, self.active_readers)
        try:
            while not self.output and not self.stdin_closed:
                self.changed.clear()
                await self.changed.wait()
            chunk = bytes(self.output[:maximum])
            del self.output[:maximum]
            return chunk
        finally:
            self.active_readers -= 1

    async def write(self, raw: bytes) -> None:
        self.writes.append(raw)
        if self.phase is ClaudeMaintenanceSessionPhase.LOGIN:
            assert raw == b"synthetic-operator-line\n"
            return
        request = json.loads(raw)
        assert request == {"type": "control_request", "request_id": request["request_id"],
                           "request": {"subtype": "initialize"}}
        # No persisted bytes means no mode evidence, even if a prior process
        # happened to hold favorable state in memory.
        if self.persisted:
            self.output.extend(_response(request["request_id"]))
        else:
            self.output.extend(b'{"type":"control_request"}\n')
        self.changed.set()

    async def close_stdin(self) -> None:
        self.stdin_closed = True
        self.changed.set()


class Launcher:
    def __init__(self, phase: ClaudeMaintenanceSessionPhase, *, persist_login: bool = True) -> None:
        self.phase = phase
        self.persist_login = persist_login
        self.claude_recipe = (
            ClaudeNativeRecipe.LOGIN if phase is ClaudeMaintenanceSessionPhase.LOGIN
            else ClaudeNativeRecipe.STREAM_JSON
        )
        self.claude = type("SyntheticVendor", (), {"command": STREAM_COMMAND})()
        self.limits = ProcessLimits(
            input_bytes=4096 if phase is ClaudeMaintenanceSessionPhase.LOGIN else 8192,
            stdout_bytes=256 * 1024 if phase is ClaudeMaintenanceSessionPhase.LOGIN else 512 * 1024,
            record_bytes=256 * 1024, stderr_bytes=64 * 1024,
        )
        self.calls: list[tuple[str, ...]] = []
        self.io: NativeIO | None = None
        self.joined = False
        self.memory_only = False

    async def exchange(self, command: tuple[str, ...], **kwargs: Any) -> ProcessResult:
        assert not self.calls
        self.calls.append(command)
        mount = kwargs["native_store"]
        mount.before_spawn()
        assert kwargs["guard_fds"] == (mount.lock_fd,)
        assert kwargs["workspace"] is None
        os.lseek(mount.credential_fd, 0, os.SEEK_SET)
        persisted = os.read(mount.credential_fd, 1024) == MARKER
        self.io = NativeIO(self.phase, persisted)
        try:
            if self.phase is ClaudeMaintenanceSessionPhase.LOGIN:
                assert command == LOGIN_COMMAND
                self.memory_only = True
                if self.persist_login:
                    os.ftruncate(mount.credential_fd, 0)
                    os.lseek(mount.credential_fd, 0, os.SEEK_SET)
                    os.write(mount.credential_fd, MARKER)
                    os.fsync(mount.credential_fd)
            else:
                assert command == STREAM_COMMAND
                assert not self.memory_only  # A fresh process has no login state.
            await kwargs["conversation"](self.io)
            return ProcessResult(0, b"", b"", 0.0, payload_returncode=0)
        finally:
            assert self.io.active_readers == 0
            self.joined = True


class Relay:
    instances: ClassVar[list[Relay]] = []

    def __init__(self, policy: EgressPolicy, directory: Path, deadline: float,
                 check_control: Any) -> None:
        self.policy, self.check_control = policy, check_control
        self.closed = False
        self.instances.append(self)

    async def __aenter__(self) -> EgressSocket:
        self.check_control()
        return EgressSocket(Path("/synthetic/egress.sock"), (1, 2))

    async def __aexit__(self, *_args: object) -> None:
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("persist_login", [True, False])
async def test_separate_joined_phases_require_retained_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, persist_login: bool,
) -> None:
    monkeypatch.setattr(session, "EgressRelay", Relay)
    Relay.instances.clear()
    custody = RetainedCustody(tmp_path / "synthetic-auth.json")
    operator = Operator()
    phases = (
        ClaudeMaintenanceSessionPhase.LOGIN,
        ClaudeMaintenanceSessionPhase.OBSERVE,
        ClaudeMaintenanceSessionPhase.RELOAD,
    ) if persist_login else (
        ClaudeMaintenanceSessionPhase.LOGIN, ClaudeMaintenanceSessionPhase.RELOAD,
    )
    launchers: list[Launcher] = []
    try:
        for index, phase in enumerate(phases):
            # Every next phase starts only after the previous launcher and
            # relay have joined, with a fresh process double and fresh fd.
            assert all(item.joined for item in launchers)
            assert all(item.closed for item in Relay.instances)
            launcher = Launcher(phase, persist_login=persist_login)
            launchers.append(launcher)
            facts = await session.run_maintenance_session(
                custody, launcher,
                _policy("platform.claude.com", *(
                    () if phase is ClaudeMaintenanceSessionPhase.LOGIN
                    else ("api.anthropic.com",)
                )),
                tmp_path / f"lane-{index}", phase=phase,
                operator=operator if phase is ClaudeMaintenanceSessionPhase.LOGIN else None,
                first_login=phase is ClaudeMaintenanceSessionPhase.LOGIN,
                mode=(
                    None if phase is ClaudeMaintenanceSessionPhase.LOGIN
                    else ClaudeAuthMode.SUBSCRIPTION
                ),
            )
            assert launcher.joined and Relay.instances[-1].closed
            assert facts.relay_closed is facts.custody_current is facts.credential_closed is True
            assert facts.phase is phase
            if phase is ClaudeMaintenanceSessionPhase.LOGIN:
                assert facts.login_facts is not None
            else:
                assert facts.login_facts is None
            if phase is ClaudeMaintenanceSessionPhase.LOGIN:
                assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN
                assert facts.process_clean is True and operator.invalidated
                assert launcher.io is not None
                assert launcher.io.writes == [b"synthetic-operator-line\n"]
                assert custody.path.read_bytes() == (MARKER if persist_login else b"")
            elif persist_login:
                assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN
                assert facts.mode_observation is not None
                assert facts.mode_observation.lifecycle is ClaudeMaintenanceLifecycle.OBSERVED
                assert facts.mode_observation.request_writes == 1
                assert facts.mode_observation.stdin_closed and facts.mode_observation.eof
                assert launcher.io is not None and len(launcher.io.writes) == 1
                assert launcher.io.max_readers == 1
            else:
                assert phase is ClaudeMaintenanceSessionPhase.RELOAD
                assert facts.lifecycle is ClaudeMaintenanceSessionLifecycle.REFUSED
                assert facts.mode_observation is not None
                assert facts.mode_observation.lifecycle is ClaudeMaintenanceLifecycle.REFUSED
                assert launcher.io is not None and len(launcher.io.writes) == 1
            assert launcher.calls == [
                LOGIN_COMMAND if phase is ClaudeMaintenanceSessionPhase.LOGIN else STREAM_COMMAND
            ]
            assert len(custody.opened) == index + 1
            with pytest.raises(OSError):
                os.fstat(custody.opened[-1])
        assert custody.created == 1
        assert custody.checks >= len(phases) * 3
    finally:
        custody.close()


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux pathname Unix socket")
@pytest.mark.asyncio
async def test_login_relay_denies_api_key_destination_before_dial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    attempts: list[object] = []

    def forbidden_upstream(_family: object) -> object:
        attempts.append(_family)
        raise AssertionError("denied destination reached upstream allocation")

    monkeypatch.setattr(egress, "_upstream", forbidden_upstream)
    loop = asyncio.get_running_loop()
    relay = egress.EgressRelay(
        _policy("platform.claude.com"), tmp_path / "relay", loop.time() + 5.0,
        lambda: None,
    )
    async with relay as socket:
        reader, writer = await asyncio.open_unix_connection(str(socket.path))
        writer.write(b"CONNECT api.anthropic.com:443 HTTP/1.1\r\n\r\n")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 1) == b""
        writer.close()
        await writer.wait_closed()
        assert relay.denied == {"denied:destination": 1}
        assert attempts == []
    assert relay.closed


@pytest.mark.parametrize("persist_login", [True, False])
def test_cli_composes_real_phases_and_publishes_finite_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    persist_login: bool,
) -> None:
    """The full command path runs; only physical/interactive primitives are fake."""
    configuration(tmp_path)
    Relay.instances.clear()
    custody = RetainedCustody(tmp_path / "synthetic-auth.json")
    operator = Operator()
    launchers: list[Launcher] = []
    inherited = 0
    operator_creations = 0

    class EntryLauncher(Launcher):
        revision = digest("composition-launcher-revision", 1, "synthetic")

    @contextmanager
    def inherit(root: Path, key: str, lock_fd: int, *, generation_floor: int,
                parent: int) -> Any:
        nonlocal inherited
        assert root == tmp_path / "store"
        assert key == "test-claude" and lock_fd == 9
        assert generation_floor == 0 and parent == os.getppid()
        inherited += 1
        yield custody

    def build_launcher(_config: claude_lane.LaneConfiguration,
                       phase: ClaudeMaintenanceSessionPhase, *,
                       recipe: ClaudeNativeRecipe = ClaudeNativeRecipe.STREAM_JSON,
                       ) -> EntryLauncher:
        assert recipe is ClaudeNativeRecipe.STREAM_JSON
        assert all(item.joined for item in launchers)
        assert all(item.closed for item in Relay.instances)
        launcher = EntryLauncher(phase, persist_login=persist_login)
        launchers.append(launcher)
        return launcher

    def private_operator(*, input_fd: int, output_fd: int, error_fd: int,
                         deadline: float) -> Operator:
        nonlocal operator_creations
        assert (input_fd, output_fd, error_fd) == (0, 1, 2)
        assert deadline > 0
        operator_creations += 1
        return operator

    monkeypatch.setattr(claude_lane, "inherit_maintenance", inherit)
    monkeypatch.setattr(claude_lane.LaneConfiguration, "launcher", build_launcher)
    monkeypatch.setattr(claude_lane, "ClaudeOperatorFDIO", private_operator)
    monkeypatch.setattr(session, "EgressRelay", Relay)
    phases = (
        ClaudeMaintenanceSessionPhase.LOGIN,
        ClaudeMaintenanceSessionPhase.OBSERVE,
        ClaudeMaintenanceSessionPhase.RELOAD,
    ) if persist_login else (
        ClaudeMaintenanceSessionPhase.LOGIN, ClaudeMaintenanceSessionPhase.RELOAD,
    )
    try:
        for index, phase in enumerate(phases):
            selector = (["--first-login"] if phase is ClaudeMaintenanceSessionPhase.LOGIN
                        else ["--mode", "subscription"])
            command = args(tmp_path, phase.value, *selector)
            command[command.index("--lane-dir") + 1] = str(tmp_path / f"entry-lane-{index}")
            evidence_path = tmp_path / f"entry-evidence-{index}.json"
            command[command.index("--evidence") + 1] = str(evidence_path)
            expected_clean = persist_login or phase is ClaudeMaintenanceSessionPhase.LOGIN
            assert claude_lane.main(command) == (0 if expected_clean else 1)
            assert launchers[-1].joined and Relay.instances[-1].closed
            assert len(launchers) == len(Relay.instances) == index + 1
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            assert evidence["completed"] is True
            assert evidence["subscription_qualified"] is False
            assert evidence["production_available"] is False
            assert evidence["facts"]["phase"] == phase.value
            assert evidence["facts"]["lifecycle"] == (
                "joined-clean" if expected_clean else "refused"
            )
            assert evidence["facts"]["relay_closed"] is True
            assert evidence["facts"]["custody_current"] is True
            assert evidence["facts"]["credential_closed"] is True
            assert launchers[-1].calls == [
                LOGIN_COMMAND if phase is ClaudeMaintenanceSessionPhase.LOGIN
                else STREAM_COMMAND
            ]
            if phase is ClaudeMaintenanceSessionPhase.LOGIN:
                assert evidence["facts"]["login"]["lifecycle"] == "completed"
                assert evidence["facts"]["mode"] is None
                assert custody.path.read_bytes() == (MARKER if persist_login else b"")
            else:
                assert evidence["facts"]["login"] is None
                assert evidence["facts"]["mode"]["request_writes"] == 1
                assert evidence["facts"]["mode"]["lifecycle"] == (
                    "observed" if persist_login else "refused"
                )
                assert launchers[-1].io is not None
                assert len(launchers[-1].io.writes) == 1
            serialized = json.dumps(evidence)
            assert str(tmp_path) not in serialized
            assert "synthetic-operator-line" not in serialized
            with pytest.raises(OSError):
                os.fstat(custody.opened[-1])
        assert inherited == len(phases)
        assert operator_creations == 1
        assert custody.created == 1
        assert capsys.readouterr().err == ""
    finally:
        custody.close()
