"""WRITE callback lifecycle proofs outside the protocol-builder test module.

These are portable state-machine tests.  They use the production conversation
and the existing scripted byte transport, but never claim an OS containment or
vendor-session proof; those belong to the Linux qualification lane.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from constructicon.core.executor import TaskSpec
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.core.manifest import CapabilityBinding
from constructicon.substrate.executors import codex
from constructicon.substrate.executors.codex import (
    CodexConversation,
    CodexOperatorProvider,
    launch_identity,
)
from constructicon.substrate.executors.codex_protocol import CONTAINED_PYTHON_CATALOG
from constructicon.substrate.git import acquisition, contained
from constructicon.substrate.git.acquisition import AcquisitionClosure
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.capture import (
    ContainedWriteWorkspace,
    ContainedWriteWorkspaceProvider,
)
from tests.gitworld import seed_authority
from tests.native_operator_world import native_egress
from tests.operator_store_world import StoreWorld
from tests.substrate.test_codex_adapter import (
    BINARY,
    CONFIGURATION,
    EXPECTED,
    FINISHED,
    GRANTS,
    THREAD,
    TURN,
    ScriptedLauncher,
    ScriptedNative,
    codex_profile,
    context,
)

CALL_ID = "write-call-1"
REQUEST_ID = "write-request-1"
PROGRAM = "print('one owned write')"
CALL = {
    "id": REQUEST_ID,
    "method": "item/tool/call",
    "params": {
        "threadId": THREAD,
        "turnId": TURN,
        "callId": CALL_ID,
        "tool": "contained_python",
        "arguments": {"program": PROGRAM},
    },
}


class ResponseLossNative(ScriptedNative):
    """Accept the callback effect, then lose precisely its one response write."""

    async def write(self, data: bytes) -> None:
        lines = [line for line in data.split(b"\n") if line]
        if len(lines) == 1:
            value = json.loads(lines[0])
            if value.get("id") == REQUEST_ID and "method" not in value:
                self.raw_received.append(data)
                self.received.append(value)
                raise OSError("peer vanished after the owned callback completed")
        await super().write(data)


async def test_lost_callback_response_never_replays_the_spent_write_call():
    """Response loss refuses the turn, while preserving one physical callback."""

    native = ResponseLossNative(
        accounts=[
            {"result": {"account": {"type": "chatgpt", "planType": "pro"},
                        "requiresOpenaiAuth": True}},
            {"result": {"account": {"type": "chatgpt", "planType": "pro"},
                        "requiresOpenaiAuth": True}},
        ],
        records=[CALL],
    )
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "worker completed once"

    conversation = CodexConversation(
        task=TaskSpec(instruction="perform the owned write"), grants=_write_grants(),
        expected=EXPECTED, input_limit=1024 * 1024,
        catalog=("contained_python",), worker=worker,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    await asyncio.wait_for(conversation(native), 5)

    assert calls == [PROGRAM]
    responses = [
        record for record in native.received
        if record.get("id") == REQUEST_ID and "method" not in record
    ]
    assert len(responses) == 1
    assert conversation.faults
    assert not conversation.gate_completed


async def test_native_eof_cancels_a_callback_that_is_still_running():
    """A dead native peer may not leave its owned WRITE worker running."""

    native = ScriptedNative(
        accounts=[{"result": {"account": {"type": "chatgpt", "planType": "pro"},
                              "requiresOpenaiAuth": True}}],
        records=[CALL], hangs_up_after_turn=True,
    )
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def worker(_program: str) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return "unreachable"

    conversation = CodexConversation(
        task=TaskSpec(instruction="perform the owned write"), grants=_write_grants(),
        expected=EXPECTED, input_limit=1024 * 1024,
        catalog=("contained_python",), worker=worker,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    running = asyncio.create_task(conversation(native))
    cancellation_observer = asyncio.create_task(cancelled.wait())
    try:
        await asyncio.wait_for(started.wait(), 5)
        assert native.eof
        done, _ = await asyncio.wait((cancellation_observer,), timeout=0.5)
        assert cancellation_observer in done and cancelled.is_set(), (
            "native EOF did not cancel the active callback before its deadline"
        )
    finally:
        if not cancellation_observer.done():
            cancellation_observer.cancel()
            await asyncio.gather(cancellation_observer, return_exceptions=True)
        if not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)


async def test_native_eof_preserves_a_callback_cleanup_failure():
    """Cancellation joins must not turn a worker cleanup failure into silence."""

    native = ScriptedNative(
        accounts=[{"result": {"account": {"type": "chatgpt", "planType": "pro"},
                              "requiresOpenaiAuth": True}}],
        records=[CALL], hangs_up_after_turn=True,
    )

    async def worker(_program: str) -> str:
        try:
            await asyncio.Event().wait()
        finally:
            raise RuntimeError("owned worker cleanup failed")

    conversation = CodexConversation(
        task=TaskSpec(instruction="perform the owned write"), grants=_write_grants(),
        expected=EXPECTED, input_limit=1024 * 1024,
        catalog=("contained_python",), worker=worker,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    await asyncio.wait_for(conversation(native), 5)
    assert any("RuntimeError" in fault for fault in conversation.faults)


async def test_callback_cleanup_failure_keeps_outer_cancellation():
    """A cleanup fault augments cancellation; it must not replace it."""

    native = ScriptedNative(
        accounts=[{"result": {"account": {"type": "chatgpt", "planType": "pro"},
                              "requiresOpenaiAuth": True}}],
        records=[CALL],
    )
    started = asyncio.Event()

    async def worker(_program: str) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            raise RuntimeError("owned worker cleanup failed")

    conversation = CodexConversation(
        task=TaskSpec(instruction="perform the owned write"), grants=_write_grants(),
        expected=EXPECTED, input_limit=1024 * 1024,
        catalog=("contained_python",), worker=worker,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    running = asyncio.create_task(conversation(native))
    await asyncio.wait_for(started.wait(), 5)
    running.cancel()
    with pytest.raises(BaseExceptionGroup) as raised:
        await running
    assert raised.value.subgroup(asyncio.CancelledError) is not None


@dataclass(frozen=True, kw_only=True)
class BlockingWorkerLauncher(ScriptedLauncher):
    """A portable launcher that makes the callback's guard exit observable."""

    worker_entered: asyncio.Event = field(default_factory=asyncio.Event)
    worker_cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    events: list[str] = field(default_factory=list)
    exchange_timeout_s: float | None = None
    worker_timeout_s: float | None = None

    async def exchange(self, command, **kwargs):
        object.__setattr__(self, "exchange_timeout_s", kwargs["timeout_s"])
        await asyncio.sleep(0.03)  # Spend time after the handle chose its deadline.
        return await super().exchange(command, **kwargs)

    async def run(self, command, **kwargs):
        object.__setattr__(self, "worker_timeout_s", kwargs["timeout_s"])
        self.events.append("worker-enter")
        self.worker_entered.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.events.append("worker-cancelled")
            self.worker_cancelled.set()
            raise


def _write_grants():
    return GRANTS.model_copy(update={
        "posture": Posture.WRITE,
        "allowed_tools": CONTAINED_PYTHON_CATALOG,
        "timeout_s": 1,
    })


def _write_profile():
    read = codex_profile()
    policy = read.grant_policy.model_copy(update={
        "tool_sets": (CONTAINED_PYTHON_CATALOG,), "workspace_required": True,
    })
    return read.model_copy(update={
        "name": "codex-operator-write", "posture": Posture.WRITE,
        "grant_policy": policy,
        "isolation": read.isolation.model_copy(update={"filesystem": "workspace_only"}),
    })


@asynccontextmanager
async def _portable_guard(paths):
    paths.guard.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(paths.guard, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


async def test_close_joins_worker_before_workspace_exit_and_uses_remaining_deadline(
    tmp_path, monkeypatch,
):
    """The actual WRITE handle owns both cancellation ordering and one deadline.

    Linux guard semantics and containment are substituted only at their platform
    boundary.  The provider, binding-store checks, workspace provenance,
    conversation, task ownership and close path are production code.
    """

    monkeypatch.setattr(codex, "acquisition_guard", _portable_guard)
    monkeypatch.setattr(contained, "acquisition_guard", _portable_guard)
    monkeypatch.setattr(acquisition, "acquisition_guard", _portable_guard)
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    authority_root = tmp_path / "authority"
    authority_root.mkdir()
    closure = AcquisitionClosure(GitAuthority(
        seed_authority(authority_root), authority_root / "legacy",
    ))
    grants = _write_grants()
    native = ScriptedNative(
        accounts=[
            {"result": {"account": {"type": "chatgpt", "planType": "pro"},
                        "requiresOpenaiAuth": True}},
            {"result": {"account": {"type": "chatgpt", "planType": "pro"},
                        "requiresOpenaiAuth": True}},
        ],
        records=[CALL],
    )
    launcher = BlockingWorkerLauncher(
        runtime_root=Path("/opt/codex-runtime"),
        expected_runtime=digest("test-codex-runtime", 1, "runtime"),
        bubblewrap=Path("/usr/bin/bwrap"),
        policy=Path("/etc/apparmor.d/constructicon-m8-launch"),
        expected_policy_sha256="0" * 64,
        native=native,
        result=FINISHED,
    )
    profile = _write_profile()
    identity = launch_identity(
        launcher=launcher, profile=profile, egress=native_egress(), store=world.sealed,
        executable_digest=digest("test-codex-executable", 1, BINARY),
        configuration=CONFIGURATION, catalog=CONTAINED_PYTHON_CATALOG,
        authenticated_startup_conformance_revision=digest("test-codex-startup", 1, "x"),
        subscription_mode_conformance_revision=digest("test-codex-mode", 1, "x"),
    )
    provider = CodexOperatorProvider(
        launcher=launcher, profile=profile, identity=identity, expected_account=EXPECTED,
        binary=BINARY, configuration=CONFIGURATION, catalog=CONTAINED_PYTHON_CATALOG,
        acquisition_root=tmp_path / "executor", unavailable_reasons=(),
        binding_store=world.binding(), closure=closure,
    )
    executor_context = context(grants=grants)
    acquired = await provider.acquire(executor_context)
    await acquired.materialize()

    workspace_authority_root = tmp_path / "workspace-authority"
    workspace_authority_root.mkdir()
    workspace_provider = ContainedWriteWorkspaceProvider(
        GitAuthority(
            seed_authority(workspace_authority_root), tmp_path / "workspace-legacy",
        ),
        root=tmp_path / "workspaces", target_ref="refs/heads/main", provider_id="lifecycle",
        posture=Posture.WRITE, launcher=launcher,
    )
    workspace_context = replace(executor_context, binding=CapabilityBinding(
        scope=executor_context.binding.scope, binding="workspace", capability_id="workspace",
        revision=workspace_provider.revision, effective_grants=grants,
    ))
    workspace_acquired = await workspace_provider.acquire(workspace_context)
    workspace = workspace_acquired.resource
    assert isinstance(workspace, ContainedWriteWorkspace)
    Path(workspace.path).mkdir(parents=True)
    workspace._phase.entered = workspace._phase.ready = True

    original_use = ContainedWriteWorkspace.use

    @asynccontextmanager
    async def observed_use(self):
        launcher.events.append("workspace-enter")
        try:
            async with original_use(self) as guard:
                yield guard
        finally:
            launcher.events.append("workspace-exit")

    monkeypatch.setattr(ContainedWriteWorkspace, "use", observed_use)
    running = None
    try:
        running = asyncio.create_task(acquired.resource.execute(
            TaskSpec(instruction="call the fixed worker"), workspace=workspace, grants=grants,
        ))
        await asyncio.wait_for(launcher.worker_entered.wait(), 5)
        assert launcher.exchange_timeout_s is not None and launcher.worker_timeout_s is not None
        assert 0 < launcher.worker_timeout_s < launcher.exchange_timeout_s

        await provider.close(acquired, "discard")
        assert launcher.worker_cancelled.is_set()
        assert launcher.events.index("worker-cancelled") < launcher.events.index("workspace-exit")
        assert acquired.resource.worker_active is None
        with pytest.raises(asyncio.CancelledError):
            await running
    finally:
        if running is not None and not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        if not acquired.resource.closed:
            await provider.close(acquired, "discard")
        # Windows does not provide the production fd-safe rmtree primitive.
        # Remove this known-empty, test-created payload only after the worker
        # and executor have joined, so provider.close can still commit its
        # closure and exercise its ordinary no-payload cleanup branch.
        if workspace.paths.payload.exists():
            Path(workspace.path).rmdir()
            workspace.paths.payload.rmdir()
        await workspace_provider.close(workspace_acquired, "discard")
