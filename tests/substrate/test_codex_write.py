"""Portable accepting and refusing tests for the N2 WRITE mediation path."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.grants import EffectiveGrants, Posture
from constructicon.core.identity import digest
from constructicon.core.native_operator import (
    NativeOperatorExecutorProfileV3,
    NativeOperatorGrantPolicyV3,
    NativeOperatorIsolationProfileV3,
)
from constructicon.substrate.executors import codex as codex_module
from constructicon.substrate.executors.codex import (
    CodexConversation,
    CodexOperatorProvider,
    launch_identity,
)
from constructicon.substrate.executors.codex_protocol import (
    CONTAINED_PYTHON_CATALOG,
    MAX_TOOL_CALLS,
    TOOL_OUTPUT_BYTES,
    ExpectedAccount,
)
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessResult
from constructicon.substrate.executors.operator_store import BindingStore
from constructicon.substrate.git import contained as contained_module
from constructicon.substrate.git.acquisition import AcquisitionClosure
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.capture import (
    ContainedWriteWorkspace,
    ContainedWriteWorkspaceProvider,
)
from tests.gitworld import seed_authority
from tests.native_operator_world import native_egress
from tests.substrate.test_codex_adapter import (
    BINARY,
    CONFIGURATION,
    EXPECTED,
    FINISHED,
    MANAGED_RESULT,
    PLAN,
    ScriptedLauncher,
    ScriptedNative,
    clean_native,
    context,
)
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_protocol import completed

WRITE_GRANTS = EffectiveGrants(
    posture=Posture.WRITE,
    model_selection={"kind": "explicit", "model": "gpt-5.6-sol"},
    effort="low",
    allowed_tools=CONTAINED_PYTHON_CATALOG,
    env_allowlist=(),
    network="allow",
    timeout_s=600,
)


def write_profile() -> NativeOperatorExecutorProfileV3:
    return NativeOperatorExecutorProfileV3(
        name="codex-operator-write",
        posture=Posture.WRITE,
        structured_output=True,
        accepted_efforts=("low", "medium"),
        grant_policy=NativeOperatorGrantPolicyV3(
            tool_sets=(CONTAINED_PYTHON_CATALOG,),
            model_ids=("gpt-5.6-sol",),
            environment_names=(),
            workspace_required=True,
            network_modes=("allow",),
            network_access="native_vendor_session_only",
            tool_path="mediated_callbacks_only",
        ),
        isolation=NativeOperatorIsolationProfileV3(
            filesystem="workspace_only",
            process_tree_owned=True,
            environment_allowlisted=True,
            network_enforced=True,
            native_workspace="none",
            worker_network="none",
            credential_state="narrow_vendor_store_rw",
            zones="native_and_worker_separate",
        ),
        authentication="vendor_managed_subscription",
        account_assurance="operator_bound_vendor_identity_unverified",
        # Forbidden is forced unavailable; see codex_profile() in test_codex_adapter.
        subscription_overage="operator_authorized",
    )


class WriteNative(ScriptedNative):
    """A scripted peer that waits for the callback response before completion."""

    def __init__(
        self, program: str, *, callback_before_turn_reply: bool = False,
        callbacks: list[dict[str, object]] | None = None,
    ) -> None:
        self.program = program
        self.callback_before_turn_reply = callback_before_turn_reply
        self.callback_responses: list[dict] = []
        self.callbacks = callbacks or [self._callback_for("server-1", "call-1", program)]
        self.callback_index = 0
        super().__init__(
            accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}],
            records=(),
        )
        if not callback_before_turn_reply:
            self.records.append(self.callbacks[0])

    def _callback(self) -> dict[str, object]:
        return self.callbacks[0]

    @staticmethod
    def _callback_for(request_id: int | str, call_id: str, program: str) -> dict[str, object]:
        return {
            "id": request_id,
            "method": "item/tool/call",
            "params": {
                "threadId": "thread-n2",
                "turnId": "turn-n2",
                "callId": call_id,
                "tool": "contained_python",
                "arguments": {"program": program},
            },
        }

    def _respond(self, raw: bytes) -> None:
        request = json.loads(raw)
        if request.get("method") == "turn/start" and self.callback_before_turn_reply:
            self.received.append(request)
            self._emit(self._callback())
            self._emit({"id": request["id"], "result": {"turn": {"id": self.turn}}})
            return
        active = (
            self.callbacks[self.callback_index]
            if self.callback_index < len(self.callbacks)
            else None
        )
        if (
            active is not None
            and request.get("method") is None
            and request.get("id") == active["id"]
        ):
            self.received.append(request)
            self.callback_responses.append(request)
            self.callback_index += 1
            if self.callback_index < len(self.callbacks):
                self._emit(self.callbacks[self.callback_index])
            else:
                self._emit(completed(output={"summary": "done"}, model="gpt-5.6-sol"))
            return
        super()._respond(raw)


def write_native(*, program: str = "print('ok')") -> WriteNative:
    return WriteNative(program)


def write_provider(
    launcher: LinuxLauncher, *,
    binding: tuple[BindingStore, AcquisitionClosure], root: Path,
) -> CodexOperatorProvider:
    store, closure = binding
    profile = write_profile()
    identity = launch_identity(
        launcher=launcher,
        profile=profile,
        egress=native_egress(),
        store=store.sealed,
        executable_digest=digest("test-write-binary", 1, BINARY),
        configuration=CONFIGURATION,
        catalog=CONTAINED_PYTHON_CATALOG,
        authenticated_startup_conformance_revision=digest("test-write-startup", 1, "fixture"),
        subscription_mode_conformance_revision=digest("test-write-mode", 1, "fixture"),
    )
    return CodexOperatorProvider(
        launcher=launcher,
        profile=profile,
        identity=identity,
        expected_account=EXPECTED,
        binary=BINARY,
        configuration=CONFIGURATION,
        catalog=CONTAINED_PYTHON_CATALOG,
        acquisition_root=root,
        unavailable_reasons=(),
        binding_store=store,
        closure=closure,
    )


async def run_write_conversation(native: ScriptedNative, worker) -> CodexConversation:
    conversation = CodexConversation(
        task=TaskSpec(instruction="change the workspace"),
        grants=WRITE_GRANTS,
        expected=EXPECTED,
        input_limit=1024 * 1024,
        catalog=CONTAINED_PYTHON_CATALOG,
        worker=worker,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    running = asyncio.create_task(conversation(native))
    try:
        done, _ = await asyncio.wait((running,), timeout=6)
        assert running in done, "WRITE conversation exceeded its shared deadline"
        await running
        return conversation
    finally:
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)


async def test_conversation_dispatches_one_callback_and_completes_its_response():
    native = write_native(program="print('changed')")
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "worker-output"

    conversation = CodexConversation(
        task=TaskSpec(instruction="change the workspace"),
        grants=WRITE_GRANTS,
        expected=ExpectedAccount(plan_type=PLAN),
        input_limit=1024 * 1024,
        catalog=CONTAINED_PYTHON_CATALOG,
        worker=worker,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    await asyncio.wait_for(conversation(native), 5)
    assert calls == ["print('changed')"]
    assert conversation.faults == () and conversation.gate_completed
    assert native.callback_responses == [{
        "id": "server-1",
        "result": {
            "contentItems": [{"type": "inputText", "text": "worker-output"}],
            "success": True,
        },
    }]


async def test_server_request_and_client_reply_ids_have_distinct_domains():
    # Five is the next client RPC id (the pre-acceptance account/read). The
    # callback may use it without answering or consuming that future request.
    callback = WriteNative._callback_for(5, "call-collision", "print('once')")
    native = WriteNative("print('once')", callbacks=[callback])
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "done"

    conversation = await run_write_conversation(native, worker)
    assert conversation.faults == () and conversation.gate_completed
    assert calls == ["print('once')"]
    assert [item["method"] for item in native.received if "method" in item][-1] == (
        "account/read"
    )


async def test_duplicate_inbound_request_id_refuses_without_a_second_effect():
    callbacks = [
        WriteNative._callback_for("same-request", "call-1", "first"),
        WriteNative._callback_for("same-request", "call-2", "second"),
    ]
    native = WriteNative("first", callbacks=callbacks)
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "done"

    conversation = await run_write_conversation(native, worker)
    assert calls == ["first"]
    assert "the native client repeated a callback request id" in conversation.faults


async def test_duplicate_call_id_refuses_without_a_second_effect():
    callbacks = [
        WriteNative._callback_for("request-1", "same-call", "first"),
        WriteNative._callback_for("request-2", "same-call", "second"),
    ]
    native = WriteNative("first", callbacks=callbacks)
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "done"

    conversation = await run_write_conversation(native, worker)
    assert calls == ["first"]
    assert "the native client repeated a callback call id" in conversation.faults


async def test_callback_ceiling_binds_on_the_first_excess_call():
    callbacks = [
        WriteNative._callback_for(f"request-{index}", f"call-{index}", str(index))
        for index in range(MAX_TOOL_CALLS + 1)
    ]
    native = WriteNative("0", callbacks=callbacks)
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "done"

    conversation = await run_write_conversation(native, worker)
    assert calls == [str(index) for index in range(MAX_TOOL_CALLS)]
    assert "the native client exceeded the callback call ceiling" in conversation.faults


async def test_parallel_exact_requests_are_held_and_effects_stay_sequential():
    callbacks = [
        WriteNative._callback_for(f"request-{index}", f"call-{index}", str(index))
        for index in range(3)
    ]

    class ParallelNative(WriteNative):
        def _respond(self, raw: bytes) -> None:
            request = json.loads(raw)
            if request.get("method") == "turn/start":
                self.received.append(request)
                self._emit({"id": request["id"], "result": {"turn": {"id": self.turn}}})
                for callback in self.callbacks:
                    self._emit(callback)
                return
            active = (
                self.callbacks[self.callback_index]
                if self.callback_index < len(self.callbacks)
                else None
            )
            if (
                active is not None
                and request.get("method") is None
                and request.get("id") == active["id"]
            ):
                self.received.append(request)
                self.callback_responses.append(request)
                self.callback_index += 1
                if self.callback_index == len(self.callbacks):
                    self._emit(completed(output={"summary": "done"}, model="gpt-5.6-sol"))
                return
            ScriptedNative._respond(self, raw)

    native = ParallelNative("0", callbacks=callbacks)
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return f"done-{program}"

    conversation = await run_write_conversation(native, worker)
    assert calls == ["0", "1", "2"]
    assert len(native.callback_responses) == 3
    assert conversation.faults == () and conversation.gate_completed


@pytest.mark.parametrize("pending,expected", [
    ("terminal", "the turn completed while a callback was active"),
    ("notification-flood", "the native client flooded an active callback"),
    ("byte-flood", "pending callback requests exceeded their byte ceiling"),
], ids=("terminal", "notification-flood", "byte-flood"))
async def test_active_callback_refuses_terminal_or_bounded_pending_flood(
    pending, expected,
):
    callback = WriteNative._callback_for("active-request", "active-call", "active")
    if pending == "terminal":
        trailing = [completed(output={"summary": "too early"})]
    elif pending == "notification-flood":
        trailing = [
            {"method": "warning", "params": {"index": index}}
            for index in range(codex_module.CALLBACK_PENDING_RECORDS + 1)
        ]
    else:
        trailing = [
            WriteNative._callback_for(f"held-{index}", f"held-call-{index}", "x" * 131_000)
            for index in range(2)
        ]
    native = ScriptedNative(
        accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}],
        records=[callback, *trailing],
    )
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def worker(_program: str) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return "unreachable"

    conversation = await run_write_conversation(native, worker)
    assert started.is_set() and cancelled.is_set()
    assert expected in conversation.faults and not conversation.gate_completed
    assert not [item for item in native.received if item.get("id") == "active-request"]


@pytest.mark.parametrize("duplicate,expected", [
    ("active-request", "the native client repeated a pending callback request id"),
    ("held-request", "the native client repeated a pending callback request id"),
    ("active-call", "the native client repeated a pending callback call id"),
    ("held-call", "the native client repeated a pending callback call id"),
], ids=("active-request", "held-request", "active-call", "held-call"))
async def test_active_callback_reserves_pending_request_and_call_ids(duplicate, expected):
    active = WriteNative._callback_for("active-request", "active-call", "active")
    held = WriteNative._callback_for("pending-request", "pending-call", "pending")
    repeated = {
        "active-request": WriteNative._callback_for(
            "active-request", "second-call", "repeated",
        ),
        "held-request": WriteNative._callback_for(
            "pending-request", "second-call", "repeated",
        ),
        "active-call": WriteNative._callback_for(
            "second-request", "active-call", "repeated",
        ),
        "held-call": WriteNative._callback_for(
            "second-request", "pending-call", "repeated",
        ),
    }[duplicate]
    records = [active, repeated]
    if duplicate.startswith("held-"):
        records.insert(1, held)
    native = ScriptedNative(
        accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}],
        records=records,
    )
    cancelled = asyncio.Event()

    async def worker(_program: str) -> str:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return "unreachable"

    conversation = await run_write_conversation(native, worker)
    assert cancelled.is_set() and expected in conversation.faults


async def test_active_callback_pending_count_ceiling_binds_before_an_excess_effect():
    active = WriteNative._callback_for("active-request", "active-call", "active")
    pending = [
        WriteNative._callback_for(f"pending-{index}", f"pending-call-{index}", str(index))
        for index in range(MAX_TOOL_CALLS)
    ]
    native = ScriptedNative(
        accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}],
        records=[active, *pending],
    )
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        await asyncio.Event().wait()
        return "unreachable"

    conversation = await run_write_conversation(native, worker)
    assert calls == ["active"]
    assert "the native client exceeded the callback call ceiling" in conversation.faults


async def test_unknown_pre_account_and_late_requests_never_dispatch():
    unknown = WriteNative._callback_for("request", "call", "must not run")
    unknown["method"] = "process/exec"
    callback = WriteNative._callback_for("request", "call", "must not run")
    natives = (
        ScriptedNative(
            accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}],
            records=[unknown],
        ),
        ScriptedNative(
            accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}],
            early=[callback],
        ),
        ScriptedNative(
            accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}],
            records=[completed(output={"summary": "early"}), callback],
        ),
    )
    for native in natives:
        calls: list[str] = []

        async def worker(program: str, observed=calls) -> str:
            observed.append(program)
            return "unexpected"

        conversation = await run_write_conversation(native, worker)
        assert calls == [] and conversation.faults


async def test_worker_exception_and_output_bound_are_refusals_after_one_effect():
    for failure in ("exception", "output"):
        native = write_native(program="one call")
        calls: list[str] = []

        async def worker(program: str, observed=calls, mode=failure) -> str:
            observed.append(program)
            if mode == "exception":
                raise RuntimeError("worker failed")
            return "x" * (TOOL_OUTPUT_BYTES + 1)

        conversation = await run_write_conversation(native, worker)
        assert calls == ["one call"] and conversation.faults
        assert not native.callback_responses
        assert not conversation.gate_completed


async def test_callback_can_be_buffered_before_the_turn_reply_without_early_effect():
    native = WriteNative("print('changed')", callback_before_turn_reply=True)
    calls: list[str] = []

    async def worker(program: str) -> str:
        assert native.methods[-1] == "turn/start"
        calls.append(program)
        return "done"

    conversation = CodexConversation(
        task=TaskSpec(instruction="change"), grants=WRITE_GRANTS, expected=EXPECTED,
        input_limit=1024 * 1024, catalog=CONTAINED_PYTHON_CATALOG,
        worker=worker, deadline=asyncio.get_running_loop().time() + 5,
    )
    await asyncio.wait_for(conversation(native), 5)
    assert calls == ["print('changed')"] and conversation.faults == ()


async def test_callback_after_a_buffered_completion_is_never_dispatched():
    class TerminalFirstNative(WriteNative):
        def _respond(self, raw: bytes) -> None:
            request = json.loads(raw)
            if request.get("method") == "turn/start":
                self.received.append(request)
                self._emit(completed(output={"summary": "early"}, model="gpt-5.6-sol"))
                self._emit(self._callback())
                self._emit({"id": request["id"], "result": {"turn": {"id": self.turn}}})
                return
            super()._respond(raw)

    native = TerminalFirstNative("print('must not run')", callback_before_turn_reply=True)
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "unexpected"

    conversation = CodexConversation(
        task=TaskSpec(instruction="change"), grants=WRITE_GRANTS, expected=EXPECTED,
        input_limit=1024 * 1024, catalog=CONTAINED_PYTHON_CATALOG,
        worker=worker, deadline=asyncio.get_running_loop().time() + 5,
    )
    await asyncio.wait_for(conversation(native), 5)
    assert calls == []
    assert "a callback request arrived after the deferred turn completion" in (
        conversation.faults
    )


async def test_buffered_callback_and_completion_refuse_before_dispatch():
    class CallbackThenTerminalNative(WriteNative):
        def _respond(self, raw: bytes) -> None:
            request = json.loads(raw)
            if request.get("method") == "turn/start":
                self.received.append(request)
                self._emit(self._callback())
                self._emit(completed(output={"summary": "early"}, model="gpt-5.6-sol"))
                self._emit({"id": request["id"], "result": {"turn": {"id": self.turn}}})
                return
            super()._respond(raw)

    native = CallbackThenTerminalNative("must not run", callback_before_turn_reply=True)
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "unexpected"

    conversation = await run_write_conversation(native, worker)
    assert calls == []
    assert "the turn completed before its deferred callback was answered" in (
        conversation.faults
    )


async def test_read_conversation_bytes_remain_without_opt_in_or_catalog():
    native = clean_native()
    conversation = CodexConversation(
        task=TaskSpec(instruction="summarize"),
        grants=WRITE_GRANTS.model_copy(update={"posture": Posture.READ, "allowed_tools": ()}),
        expected=EXPECTED,
        input_limit=1024 * 1024,
    )
    await asyncio.wait_for(conversation(native), 5)
    assert native.received[0]["params"]["capabilities"] == {}
    assert "dynamicTools" not in native.received[3]["params"]


def test_write_helpers_build_the_exact_profile_catalog_coherence():
    native = write_native()
    launcher = ScriptedLauncher(
        runtime_root=Path("/opt/codex-runtime"),
        expected_runtime=digest("test-write-runtime", 1, "fixture"),
        bubblewrap=Path("/usr/bin/bwrap"),
        policy=Path("/etc/apparmor.d/constructicon-m8-launch"),
        expected_policy_sha256="0" * 64,
        native=native,
        result=FINISHED,
    )
    assert write_profile().grant_policy.tool_sets == (CONTAINED_PYTHON_CATALOG,)
    assert launcher.native is native


@pytest.mark.parametrize("mismatch", ["owner", "epoch", "path", "revision", "grants"])
async def test_write_handle_refuses_foreign_workspace_identity_before_native_io(
    mismatch, tmp_path, portable_binding,
):
    native = write_native()
    launcher = ScriptedLauncher(
        runtime_root=Path("/opt/codex-runtime"),
        expected_runtime=digest("test-write-runtime", 1, "workspace"),
        bubblewrap=Path("/usr/bin/bwrap"),
        policy=Path("/etc/apparmor.d/constructicon-m8-launch"),
        expected_policy_sha256="0" * 64,
        native=native,
        result=FINISHED,
    )
    executor = write_provider(
        launcher, binding=portable_binding[1:3], root=tmp_path / "executor",
    )
    executor_context = context(grants=WRITE_GRANTS)
    acquired = await executor.acquire(executor_context)
    handle = acquired.resource
    handle.ready = True
    workspace_provider = ContainedWriteWorkspaceProvider(
        GitAuthority(
            seed_authority(tmp_path / "workspace-authority"),
            tmp_path / "workspace-legacy",
        ),
        root=tmp_path / "workspaces",
        target_ref="refs/heads/main",
        provider_id="write-matrix",
        posture=Posture.WRITE,
        launcher=launcher,
    )
    workspace_context = replace(
        executor_context,
        binding=executor_context.binding.model_copy(update={
            "binding": "workspace",
            "capability_id": "workspace",
            "revision": workspace_provider.revision,
        }),
    )
    if mismatch == "owner":
        workspace_context = replace(
            workspace_context,
            run_lease=workspace_context.run_lease.model_copy(update={"owner_id": "foreign"}),
        )
    elif mismatch == "epoch":
        workspace_context = replace(
            workspace_context,
            run_lease=workspace_context.run_lease.model_copy(update={"epoch": 2}),
        )
    elif mismatch == "path":
        workspace_context = replace(
            workspace_context,
            path=ExecutionPath(scope=ScopePath(segments=("root", "foreign"))),
        )
    elif mismatch == "grants":
        workspace_context = replace(
            workspace_context,
            binding=workspace_context.binding.model_copy(update={
                "effective_grants": WRITE_GRANTS.model_copy(update={"timeout_s": 599}),
            }),
        )
    workspace_acquired = await workspace_provider.acquire(workspace_context)
    workspace = workspace_acquired.resource
    assert isinstance(workspace, ContainedWriteWorkspace)
    workspace._phase.ready = True
    if mismatch == "revision":
        object.__setattr__(
            workspace,
            "context",
            replace(
                workspace.context,
                binding=workspace.context.binding.model_copy(update={"revision": "drifted"}),
            ),
        )
    with pytest.raises(ContractViolation):
        handle._validated_workspace(workspace, WRITE_GRANTS)
    assert launcher.calls == []
    await workspace_provider.close(workspace_acquired, "discard")
    await executor.close(acquired, "discard")


@asynccontextmanager
async def portable_guard(paths):
    paths.guard.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(paths.guard, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@dataclass(frozen=True, kw_only=True)
class ControlledWorkerLauncher(ScriptedLauncher):
    worker_result: ProcessResult
    worker_calls: list[dict[str, object]] = field(default_factory=list)

    async def run(self, command, **kwargs):
        self.worker_calls.append({"command": command, **kwargs})
        return self.worker_result


@pytest.mark.parametrize("worker_result,accept", [
    (ProcessResult(0, b"worker-output", b"", 0.1, payload_returncode=0), True),
    (ProcessResult(2, b"", b"failed", 0.1, payload_returncode=0), False),
    (ProcessResult(0, b"", b"failed", 0.1, payload_returncode=2), False),
    (ProcessResult(0, b"", b"", 0.1, timed_out=True, payload_returncode=0), False),
    (ProcessResult(0, b"", b"", 0.1, bound_exceeded="stdout", payload_returncode=0), False),
    (ProcessResult(0, b"", b"", 0.1, payload_returncode=None), False),
], ids=(
    "success", "supervisor-exit", "payload-exit", "timed-out", "output-bound",
    "missing-payload",
))
async def test_public_write_handle_accepts_only_a_complete_contained_worker(
    worker_result, accept, tmp_path, portable_binding, monkeypatch,
):
    monkeypatch.setattr(codex_module, "acquisition_guard", portable_guard)
    monkeypatch.setattr(contained_module, "acquisition_guard", portable_guard)
    native = write_native(program="print('one call')")
    launcher = ControlledWorkerLauncher(
        runtime_root=Path("/opt/codex-runtime"),
        expected_runtime=digest("test-write-runtime", 1, "handle"),
        bubblewrap=Path("/usr/bin/bwrap"),
        policy=Path("/etc/apparmor.d/constructicon-m8-launch"),
        expected_policy_sha256="0" * 64,
        native=native,
        result=FINISHED,
        worker_result=worker_result,
    )
    executor = write_provider(
        launcher, binding=portable_binding[1:3], root=tmp_path / "executor",
    )
    executor_context = context(grants=WRITE_GRANTS)
    acquired = await executor.acquire(executor_context)
    await acquired.materialize()
    workspace_provider = ContainedWriteWorkspaceProvider(
        GitAuthority(
            seed_authority(tmp_path / "handle-authority"),
            tmp_path / "handle-legacy",
        ),
        root=tmp_path / "workspaces",
        target_ref="refs/heads/main",
        provider_id="write-handle",
        posture=Posture.WRITE,
        launcher=launcher,
    )
    workspace_context = replace(
        executor_context,
        binding=executor_context.binding.model_copy(update={
            "binding": "workspace",
            "capability_id": "workspace",
            "revision": workspace_provider.revision,
        }),
    )
    workspace_acquired = await workspace_provider.acquire(workspace_context)
    workspace = workspace_acquired.resource
    assert isinstance(workspace, ContainedWriteWorkspace)
    Path(workspace.path).mkdir(parents=True)
    workspace._phase.ready = True
    try:
        outcome = await acquired.resource.execute(
            TaskSpec(instruction="call the fixed worker"),
            workspace=workspace,
            grants=WRITE_GRANTS,
        )
        assert outcome.status == ("success" if accept else "failure")
        assert len(launcher.worker_calls) == 1
        worker_call = launcher.worker_calls[0]
        assert worker_call["command"] == (
            "/usr/bin/python3", "-I", "-c", "import sys; exec(sys.stdin.read())",
        )
        assert worker_call["workspace"] == Path(workspace.path)
        assert worker_call["posture"] is Posture.WRITE
        assert worker_call["stdin"] == b"print('one call')"
        assert len(worker_call["guard_fds"]) == 1
        assert "native_store" not in worker_call
        if accept:
            assert native.callback_responses[0]["result"]["contentItems"][0]["text"] == (
                "worker-output"
            )
        else:
            assert native.callback_responses == []
    finally:
        await executor.close(acquired, "discard")
        await workspace_provider.close(workspace_acquired, "discard")
