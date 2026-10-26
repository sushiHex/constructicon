"""Credential-free persistent READ peers; no vendor code is run or imported."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.executor import ExecutorFailure, ExecutorSuccess, TaskSpec, Usage
from constructicon.core.identity import digest
from constructicon.substrate.executors import claude_read
from constructicon.substrate.executors.claude_native import (
    ClaudeNativeStoreMount,
    ClaudeNativeVendor,
)
from constructicon.substrate.executors.claude_protocol import ClaudePlan
from constructicon.substrate.executors.linux import (
    DEFAULT_PROCESS_LIMITS,
    ProcessExchangeError,
    ProcessResult,
)
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.substrate._claude_wire import commands_changed, hooks_body, settings_body

SESSION = "00000000-0000-4000-8000-000000000001"
NATIVE_UUID = "00000000-0000-4000-8000-000000000002"


def wire(value):
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


def ui_invalidate(**changes):
    return {"type": "system", "subtype": "ui_invalidate", "event": "ui.render",
            "uuid": "opaque", "session_id": "", **changes}


class Peer:
    def __init__(self, *, plan=ClaudePlan.PRO, callback=True, fragment=8192, defect=None):
        self.plan, self.callback, self.fragment, self.defect = plan, callback, fragment, defect
        self.output = bytearray()
        self.ready = asyncio.Event()
        self.writes = []
        self.closed = False
        self.users = []
        self.handshake = []
        self.post = False
        self.callback_replies = 0
        self.registration = False

    def emit(self, value):
        if self.defect == "terminal-session" and value.get("type") == "result":
            value["session_id"] = NATIVE_UUID
        if self.defect == "terminal-uuid" and value.get("type") == "result":
            value["user_message_uuid"] = NATIVE_UUID
        if self.defect == "terminal-error" and value.get("type") == "result":
            value["is_error"] = True
        if self.defect == "terminal-large" and value.get("type") == "result":
            value["result"] = "x" * (claude_read.TEXT_BYTES + 1)
        if self.defect == "post-mode" and self.post and value.get("type") == "control_response":
            body = value["response"]["response"]
            if "account" in body:
                body["account"]["apiProvider"] = "private-other-provider"
        if self.defect == "post-callback" and self.post and value.get("type") == "control_response":
            self.defect = None
            self.mcp("tools/call", identifier="late")
        if self.defect == "wrong-server" and value.get("type") == "control_request":
            value["request"]["server_name"] = "wrong"
        self.output.extend(wire(value))
        self.ready.set()

    def success(self, request_id, body, *, initialize=False):
        response = {"subtype": "success", "request_id": request_id, "response": body}
        if initialize:
            response.update(pending_permission_requests=[], pending_user_dialog_requests=[])
        self.emit({"type": "control_response", "response": response})

    def mcp(self, method, *, identifier=7, arguments=None):
        message = {"jsonrpc": "2.0", "method": method}
        if identifier is not None:
            message["id"] = identifier
        if method == "initialize":
            message["params"] = {"protocolVersion": "2025-11-25", "capabilities": {},
                                 "clientInfo": {"name": "claude-code", "version": "2.1.296"}}
        if method == "tools/call":
            message["params"] = {"name": "read_file",
                                 "arguments": arguments or {"path": "README.md"}}
        self.emit({"type": "control_request", "request_id": "outer-" + method,
                   "request": {"subtype": "mcp_message", "server_name": "constructicon_read",
                               "message": message}})

    def terminal(self):
        self.post = True
        self.emit({"type": "result", "subtype": "success", "is_error": False,
                   "session_id": SESSION, "user_message_uuid": self.users[0]["uuid"],
                   "result": "task output", "uuid": NATIVE_UUID,
                   "duration_ms": 1, "duration_api_ms": 1, "num_turns": 1,
                   "stop_reason": "end_turn", "total_cost_usd": 0,
                   "usage": {"input_tokens": 1, "output_tokens": 1},
                   "modelUsage": {"model": {"inputTokens": 1, "outputTokens": 1,
                       "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0,
                       "webSearchRequests": 0, "costUSD": 0, "contextWindow": 200000,
                       "maxOutputTokens": 1000, "canonicalModel": "model",
                       "provider": "firstParty", "costBasis": "list"}},
                   "permission_denials": [], "queued_turn_count": 0,
                   "result_index": 0, "user_message_uuids": [self.users[0]["uuid"]],
                   "safety_stops": 0,
                   "subagent_stats": {"spawned": 0, "requested": {"background": 0,
                                     "foreground": 0, "unset": 0}, "started_in_background": 0,
                                     "max_depth": 0, "spawned_by_subagents": 0, "completed": 0,
                                     "failed": 0, "killed": {"parent": 0, "user": 0, "system": 0},
                                     "refused": {"depth_limit": 0, "concurrency_limit": 0,
                                                 "budget": 0}, "by_type": {}}})

    async def write(self, data):
        self.writes.append(data)
        value = json.loads(data)
        if value["type"] == "user":
            self.users.append(value)
            if self.defect == "user-write":
                raise OSError("private uncertain write")
            self.emit({"type": "system", "subtype": "init", "session_id": SESSION,
                       "model": "model", "tools": ["mcp__constructicon_read__read_file"],
                       "mcp_servers": [{"name": "constructicon_read", "status": "connected"}],
                       "uuid": NATIVE_UUID})
            content = [{"type": "text", "text": "task output"}]
            if self.callback:
                content = [{"type": "tool_use", "id": "tool-use-id",
                            "name": "mcp__constructicon_read__read_file",
                            "input": {"path": "README.md"}}]
            self.emit({"type": "assistant", "session_id": SESSION, "uuid": NATIVE_UUID,
                       "parent_tool_use_id": None,
                       "message": {"role": "assistant", "content": content}})
            if self.callback:
                self.mcp("tools/call", identifier=19)
                if self.defect == "co-buffered-terminal":
                    self.terminal()
            else:
                self.terminal()
            return
        if value["type"] == "control_response":
            response = value["response"]
            message = response["response"]["mcp_response"]
            if response["request_id"] == "outer-initialize":
                assert message["id"] == 7
                self.handshake.append("initialize")
                self.mcp("notifications/initialized", identifier=None)
            elif response["request_id"] == "outer-notifications/initialized":
                assert message["id"] == 0
                self.handshake.append("initialized")
                self.mcp("tools/list", identifier="list-id")
            elif response["request_id"] == "outer-tools/list":
                assert message["id"] == "list-id"
                assert message["result"]["tools"] == [claude_read.READ_TOOL]
                self.handshake.append("list")
            else:
                assert response["request_id"] == "outer-tools/call"
                assert message["id"] == 19
                assert message["result"] == {"content": [{"type": "text", "text": "file text"}],
                                             "isError": False}
                self.callback_replies += 1
                if self.defect == "callback-write":
                    raise OSError("private response drain")
                if self.defect == "duplicate-callback":
                    self.mcp("tools/call", identifier=19)
                    return
                self.terminal()
            return
        request, identifier = value["request"], value["request_id"]
        subtype = request["subtype"]
        if subtype == "initialize":
            self.registration = "sdkMcpServers" in request
            self.success(identifier, {"account": {"apiProvider": "firstParty",
                                                  "subscriptionType": self.plan.value,
                                                  "email": "private-account"},
                                      "claude_code_version": "2.1.296", "session_state": "idle"},
                         initialize=True)
            if self.registration:
                self.mcp("initialize")
            if self.registration or self.post:
                self.emit({"type": "system", "subtype": "background_tasks_changed", "tasks": [],
                           "uuid": NATIVE_UUID, "session_id": SESSION})
        elif subtype == "get_settings":
            self.success(identifier, settings_body(model="model", effort="high"))
        elif subtype == "get_hooks_listing":
            self.success(identifier, hooks_body())
        else:
            raise AssertionError(subtype)

    async def read(self, maximum=8192):
        while not self.output and not self.closed:
            self.ready.clear()
            await self.ready.wait()
        size = min(len(self.output), maximum, self.fragment)
        data = bytes(self.output[:size])
        del self.output[:size]
        return data

    async def close_stdin(self):
        self.closed = True
        self.ready.set()


class Launcher:
    limits = DEFAULT_PROCESS_LIMITS

    def __init__(self, peer=None, *, result=None):
        self.peer = peer or Peer()
        self.result = result or ProcessResult(0, b"private stdout", b"private stderr", .1,
                                             payload_returncode=0)
        self.joined = False
        self.spawned = False
        self.conversation = None

    async def exchange(self, command, **kwargs):
        self.conversation = kwargs["conversation"]
        assert kwargs["workspace"] is None and kwargs["posture"].value == "read"
        try:
            if kwargs.get("native_store") is not None:
                await asyncio.sleep(0)  # The launcher's prerequisite probe may yield.
                checked = kwargs["native_store"].before_spawn()
                if not isinstance(checked, BindingCheck):
                    raise OSError("pre-spawn binding absent")
            self.spawned = True
            await self.conversation(self.peer)
            return self.result
        finally:
            self.joined = True


async def run(launcher, *, worker=None, plan=ClaudePlan.PRO, timeout=5):
    calls = []

    async def read_file(path, remaining):
        calls.append((path, remaining))
        return "file text"

    outcome = await claude_read.run_read_transaction(
        launcher, ("fixed-nonvendor-peer",), TaskSpec(instruction="read the file"),
        selected_plan=plan, model="model", effort="high", worker=worker or read_file,
        guard_fds=(), timeout_s=timeout,
    )
    return outcome, calls


@pytest.mark.parametrize("wrapped", [False, True])
async def test_initialization_refusal_retains_only_finite_source_tags_before_user(wrapped):
    class SourcePeer(Peer):
        def success(self, request_id, body, *, initialize=False):
            if initialize:
                body["account"].update(tokenSource="none", apiKeySource="private-source-sentinel")
            super().success(request_id, body, initialize=initialize)

    class JoinedLauncher(Launcher):
        async def exchange(self, command, **kwargs):
            try:
                return await super().exchange(command, **kwargs)
            except claude_read._InitializeRefused as error:
                if wrapped:
                    raise ProcessExchangeError(self.result) from error
                raise

    launcher = JoinedLauncher(SourcePeer())
    outcome, calls = await run(launcher)
    assert isinstance(outcome, ExecutorFailure) and outcome.error.kind == "exit"
    assert outcome.error.detail == (
        "Claude READ refused [initialize observed: verdict=mode-mismatch; "
        "reason=credential-source-present; token_source=none; api_key_source=unknown]"
    )
    assert len(outcome.error.detail.encode()) <= 256
    assert "private" not in outcome.error.detail
    assert launcher.joined and not calls and not launcher.peer.users
    assert len(launcher.peer.writes) == 1


@pytest.mark.parametrize("later", ["timeout", "cleanup", "group"])
async def test_later_failure_does_not_misattribute_initialization_observation(later):
    class SourcePeer(Peer):
        def success(self, request_id, body, *, initialize=False):
            if initialize:
                body["account"]["tokenSource"] = "none"
            super().success(request_id, body, initialize=initialize)

    class FailedLauncher(Launcher):
        async def exchange(self, command, **kwargs):
            try:
                return await super().exchange(command, **kwargs)
            except claude_read._InitializeRefused as error:
                if later == "timeout":
                    raise TimeoutError("private later timeout") from error
                if later == "cleanup":
                    raise OSError("private cleanup failure") from error
                raise BaseExceptionGroup(
                    "private joined failures", [error, OSError("private")],
                ) from None

    outcome, calls = await run(FailedLauncher(SourcePeer()))
    assert isinstance(outcome, ExecutorFailure)
    assert outcome.error.kind == ("timeout" if later == "timeout" else "exit")
    assert outcome.error.detail == "Claude READ refused" and not calls


async def test_non_initialization_refusal_keeps_generic_detail():
    launcher = Launcher(Peer(defect="user-write"))
    outcome, _ = await run(launcher)
    assert isinstance(outcome, ExecutorFailure)
    assert outcome.error.detail == "Claude READ refused"
    assert launcher.conversation.initialize_observation.verdict.value == "mode-match"


@pytest.mark.parametrize("refuse", [False, True])
async def test_before_user_hook_is_after_startup_and_immediately_before_one_user_write(refuse):
    launcher = Launcher()
    called = []

    def before_user():
        assert launcher.peer.handshake == ["initialize", "initialized", "list"]
        assert not launcher.peer.users
        called.append("intent")
        if refuse:
            raise OSError("private failed durable intent")

    async def worker(path, remaining):
        assert called == ["intent"]
        return "file text"

    outcome = await claude_read.run_read_transaction(
        launcher, ("fixed-nonvendor-peer",), TaskSpec(instruction="read the file"),
        selected_plan=ClaudePlan.PRO, model="model", effort="high", worker=worker,
        guard_fds=(), timeout_s=5, before_user=before_user,
    )
    assert isinstance(outcome, ExecutorFailure if refuse else ExecutorSuccess)
    assert called == ["intent"]
    assert len(launcher.peer.users) == (0 if refuse else 1)
    assert launcher.joined


async def test_control_check_refuses_at_read_resume_before_any_user_write():
    launcher = Launcher()
    checked = []

    def control():
        checked.append(len(launcher.peer.writes))
        if launcher.peer.writes:
            raise OSError("private lost ownership")

    async def worker(path, remaining):
        raise AssertionError("closed invocation cannot authorize worker")

    outcome = await claude_read.run_read_transaction(
        launcher, ("fixed-nonvendor-peer",), TaskSpec(instruction="read the file"),
        selected_plan=ClaudePlan.PRO, model="model", effort="high", worker=worker,
        guard_fds=(), timeout_s=5, check_control=control,
    )
    assert isinstance(outcome, ExecutorFailure)
    assert checked and checked[-1] == 1
    assert not launcher.peer.users and launcher.joined


@pytest.mark.parametrize("defect", [None, "initial-absent", "terminal-absent", "changed",
                                   "guard", "model", "effort", "command"])
async def test_native_read_binding_is_checked_before_dispatch_and_after_join(defect):
    launcher = Launcher()
    launcher.claude = ClaudeNativeVendor(
        Path("/fixed-vendor"), "model", "high", digest("test", 1, "vendor"),
    )
    checked = []
    initial = BindingCheck(digest("test", 1, "binding"))

    def check():
        checked.append(launcher.joined)
        if ((defect == "initial-absent" and not launcher.joined)
                or (defect == "terminal-absent" and launcher.joined)):
            return None
        if defect == "changed" and launcher.joined:
            return BindingCheck(digest("test", 1, "replacement"))
        return initial

    store = ClaudeNativeStoreMount(lock_fd=42, credential_fd=43, before_spawn=check)

    async def worker(path, remaining):
        assert checked == [False, False]
        return "file text"

    outcome = await claude_read.run_read_transaction(
        launcher, ("/wrong",) if defect == "command" else launcher.claude.command,
        TaskSpec(instruction="read the file"), selected_plan=ClaudePlan.PRO,
        model="wrong" if defect == "model" else "model",
        effort="low" if defect == "effort" else "high", worker=worker,
        guard_fds=() if defect == "guard" else (42,), timeout_s=5, native_store=store,
    )
    assert isinstance(outcome, ExecutorSuccess if defect is None else ExecutorFailure)
    if defect in {"guard", "model", "effort", "command"}:
        assert checked == [] and not launcher.peer.users
    elif defect == "initial-absent":
        assert checked == [False] and not launcher.peer.users
    else:
        assert checked == [False, False, True] and launcher.joined
        assert len(launcher.peer.users) == 1


@pytest.mark.parametrize("sequence", ["same", "spawn-changed", "spawn-absent",
                                      "terminal-changed", "terminal-absent", "initial-absent"])
async def test_native_binding_is_pinned_across_async_probe_and_terminal_join(sequence):
    launcher = Launcher()
    launcher.claude = ClaudeNativeVendor(
        Path("/fixed-vendor"), "model", "high", digest("test", 1, "vendor"),
    )
    initial = BindingCheck(digest("test", 1, "binding-a"))
    replacement = BindingCheck(digest("test", 1, "binding-b"))
    values = [initial, initial, initial]
    changed_index = 0 if sequence == "initial-absent" else (
        1 if sequence.startswith("spawn-") else 2)
    if sequence != "same":
        values[changed_index] = None if sequence.endswith("absent") else replacement
    checked = []

    def check():
        checked.append(launcher.joined)
        return values[len(checked) - 1]

    store = ClaudeNativeStoreMount(lock_fd=42, credential_fd=43, before_spawn=check)

    async def worker(_path, _remaining):
        return "file text"

    outcome = await claude_read.run_read_transaction(
        launcher, launcher.claude.command, TaskSpec(instruction="read the file"),
        selected_plan=ClaudePlan.PRO, model="model", effort="high", worker=worker,
        guard_fds=(42,), timeout_s=5, native_store=store,
    )
    assert isinstance(outcome, ExecutorSuccess if sequence == "same" else ExecutorFailure)
    assert checked == ([False] if sequence == "initial-absent" else [False, False, True])
    permitted_spawn = sequence in {"same", "terminal-changed", "terminal-absent"}
    assert launcher.spawned is permitted_spawn
    assert len(launcher.peer.users) == int(permitted_spawn)
    assert store.before_spawn is check


@pytest.mark.parametrize("exchange_error", ["operational", "timeout", "explicit-cancel",
                                            "task-cancel", "fatal", "fatal-group"])
@pytest.mark.parametrize("terminal", ["valid", "changed", "raises"])
async def test_joined_exchange_failure_still_checks_binding_and_preserves_control_flow(
    exchange_error, terminal,
):
    launcher = Launcher(Peer(callback=False))
    launcher.claude = ClaudeNativeVendor(
        Path("/fixed-vendor"), "model", "high", digest("test", 1, "vendor"),
    )
    initial = BindingCheck(digest("test", 1, "binding"))
    checked = []

    def check():
        checked.append(launcher.joined)
        if launcher.joined:
            if terminal == "raises":
                raise OSError("private terminal binding failure")
            if terminal == "changed":
                return BindingCheck(digest("test", 1, "replacement"))
        return initial

    store = ClaudeNativeStoreMount(lock_fd=42, credential_fd=43, before_spawn=check)
    original_exchange = launcher.exchange

    class Fatal(BaseException):
        pass

    primary = {
        "operational": OSError("private joined exchange failure"),
        "timeout": TimeoutError("private joined timeout"),
        "explicit-cancel": asyncio.CancelledError("private explicit cancellation"),
        "fatal": Fatal("private fatal failure"),
        "fatal-group": BaseExceptionGroup("private fatal group", [Fatal("private fatal")]),
    }.get(exchange_error)

    async def exchange(command, **arguments):
        await original_exchange(command, **arguments)
        if exchange_error == "task-cancel":
            asyncio.current_task().cancel()
            await asyncio.sleep(0)
        raise primary

    launcher.exchange = exchange

    async def worker(_path, _remaining):
        pytest.fail("zero-callback transaction cannot invoke its worker")

    failure, outcome = None, None
    try:
        outcome = await claude_read.run_read_transaction(
            launcher, launcher.claude.command, TaskSpec(instruction="read the file"),
            selected_plan=ClaudePlan.PRO, model="model", effort="high", worker=worker,
            guard_fds=(42,), timeout_s=5, native_store=store,
        )
    except BaseException as error:
        failure = error
    assert checked == [False, False, True] and launcher.joined
    if exchange_error in {"explicit-cancel", "task-cancel"}:
        assert isinstance(failure, asyncio.CancelledError), failure
    elif exchange_error in {"fatal", "fatal-group"}:
        assert failure is primary
    else:
        assert failure is None, failure
        assert isinstance(outcome, ExecutorFailure)
        assert outcome.error.kind == ("timeout" if exchange_error == "timeout" else "exit")
        assert outcome.usage == Usage(input_tokens=1, output_tokens=1)


@pytest.mark.parametrize("plan", list(ClaudePlan))
@pytest.mark.parametrize("fragment", [1, 8192])
async def test_accepting_one_read_joins_native_and_worker_with_fresh_checks(plan, fragment):
    launcher = Launcher(Peer(plan=plan, fragment=fragment))
    outcome, calls = await run(launcher, plan=plan)
    assert isinstance(outcome, ExecutorSuccess)
    assert outcome.raw_reply == "task output" and outcome.requested_model == "model"
    assert outcome.served_model is None and outcome.usage == Usage(input_tokens=1, output_tokens=1)
    assert launcher.joined and launcher.peer.closed
    assert launcher.peer.handshake == ["initialize", "initialized", "list"]
    assert len(launcher.peer.users) == 1 and len(calls) == 1
    assert calls[0][0] == "README.md" and 0 < calls[0][1] <= 5
    assert launcher.peer.callback_replies == 1
    assert [json.loads(raw)["request"]["subtype"] for raw in launcher.peer.writes
            if json.loads(raw)["type"] == "control_request"] == [
                "initialize", "get_settings", "get_hooks_listing", "initialize",
                "initialize", "get_settings", "get_hooks_listing",
            ]
    assert "private" not in outcome.model_dump_json()


async def test_zero_callback_is_a_real_permitting_path():
    outcome, calls = await run(Launcher(Peer(callback=False)))
    assert isinstance(outcome, ExecutorSuccess) and calls == []


@pytest.mark.parametrize("extra_tail", [0, 1])
@pytest.mark.parametrize("notification_kind", ["ui", "commands", "mixed"])
async def test_exact_ui_notifications_are_inert_but_counted_across_read_lifetime(
    extra_tail, notification_kind,
):
    peer = Peer()
    original_emit = peer.emit
    notifications = 0

    def notification():
        nonlocal notifications
        notifications += 1
        return (commands_changed() if notification_kind == "commands"
                or (notification_kind == "mixed" and notifications % 2) else ui_invalidate())

    inserted = {"initial": False, "registration": False, "body": False,
                "result": False, "terminal": False}

    def emit(value):
        if (value.get("type") == "control_response" and not inserted["initial"]):
            inserted["initial"] = True
            original_emit(notification())
            original_emit(notification())
        elif (value.get("subtype") == "background_tasks_changed"
              and peer.registration and not peer.post and not inserted["registration"]):
            inserted["registration"] = True
            original_emit(notification())
            original_emit(notification())
        elif value.get("subtype") == "init" and not inserted["body"]:
            inserted["body"] = True
            original_emit(notification())
        elif value.get("type") == "result" and not inserted["result"]:
            inserted["result"] = True
            original_emit(notification())
        elif (value.get("subtype") == "background_tasks_changed"
              and peer.post and not inserted["terminal"]):
            inserted["terminal"] = True
            original_emit(notification())
        original_emit(value)

    peer.emit = emit
    original_close = peer.close_stdin

    async def close():
        peer.output.extend(b"".join(wire(notification()) for _ in range(1 + extra_tail)))
        await original_close()

    peer.close_stdin = close
    launcher = Launcher(peer)
    outcome, calls = await run(launcher)
    assert inserted == dict.fromkeys(inserted, True)
    assert launcher.conversation._ui_records == 8
    assert len(peer.users) == 1 and len(calls) == 1 and launcher.joined
    assert isinstance(outcome, ExecutorSuccess if extra_tail == 0 else ExecutorFailure)
    assert "private" not in outcome.model_dump_json()
    assert all(b"private-command" not in raw and b"private-alias" not in raw
               for raw in peer.writes)


@pytest.mark.parametrize("stage", ["initialize", "body", "worker", "terminal"])
async def test_malformed_commands_notification_is_never_inert_at_any_read_stage(stage):
    peer = Peer()
    original_emit = peer.emit
    malformed = commands_changed()
    malformed["commands"][0]["builtin"] = 1

    def emit(value):
        if ((stage == "initialize" and value.get("type") == "control_response"
             and not peer.users)
                or (stage == "body" and value.get("subtype") == "init")
                or (stage == "terminal" and value.get("type") == "result")):
            original_emit(malformed)
        original_emit(value)

    async def worker(path, remaining):
        if stage == "worker":
            original_emit(malformed)
        return "file text"

    peer.emit = emit
    launcher = Launcher(peer)
    outcome, _ = await run(launcher, worker=worker)
    assert isinstance(outcome, ExecutorFailure) and launcher.joined
    assert launcher.conversation._ui_records == 0
    assert "private" not in outcome.model_dump_json()
    assert len(peer.users) == (0 if stage == "initialize" else 1)


@pytest.mark.parametrize("damage", ["missing-snapshot", "missing-terminal-snapshot",
                                    "wrong-startup-session", "wrong-session", "nonempty",
                                    "extension", "wrong-event", "carriage-return",
                                    "unknown-system"])
async def test_ui_cannot_replace_snapshot_or_admit_malformed_system_record(damage):
    peer = Peer()
    original_emit = peer.emit

    def emit(value):
        if value.get("subtype") == "background_tasks_changed" and (
            peer.registration or peer.post
        ):
            if damage == "missing-snapshot" and peer.registration:
                original_emit(ui_invalidate())
                return
            if damage == "missing-terminal-snapshot" and peer.post:
                original_emit(ui_invalidate())
                return
            if damage == "wrong-session" and peer.post:
                value["session_id"] = NATIVE_UUID
            if damage == "wrong-startup-session" and peer.registration:
                value["session_id"] = NATIVE_UUID
            if damage == "nonempty":
                value["tasks"] = [{}]
        if value.get("subtype") == "init":
            if damage == "extension":
                original_emit(ui_invalidate(extra="private"))
            elif damage == "wrong-event":
                original_emit(ui_invalidate(event="other"))
            elif damage == "carriage-return":
                peer.output.extend(wire(ui_invalidate()).replace(b"\n", b"\r\n"))
            elif damage == "unknown-system":
                original_emit({"type": "system", "subtype": "other"})
        original_emit(value)

    peer.emit = emit
    outcome, calls = await run(
        Launcher(peer), timeout=.1 if damage.startswith("missing-") else 5,
    )
    assert isinstance(outcome, ExecutorFailure)
    if damage in {"missing-snapshot", "nonempty"}:
        assert calls == [] and peer.users == []
    elif damage in {"wrong-startup-session", "extension", "wrong-event",
                    "carriage-return", "unknown-system"}:
        assert calls == [] and len(peer.users) == 1
    else:
        assert len(calls) == 1 and len(peer.users) == 1


async def test_ui_during_worker_is_inert_without_weakening_pending_record_checks():
    peer = Peer()
    observed = []

    async def worker(path, remaining):
        observed.append(path)
        peer.emit(ui_invalidate())
        await asyncio.sleep(0)
        return "file text"

    launcher = Launcher(peer)
    outcome, _ = await run(launcher, worker=worker)
    assert isinstance(outcome, ExecutorSuccess)
    assert observed == ["README.md"] and launcher.conversation._ui_records == 1


@pytest.mark.parametrize("defect", ["user-write", "callback-write", "co-buffered-terminal"])
async def test_uncertain_writes_and_terminal_during_worker_never_publish_or_retry(defect):
    launcher = Launcher(Peer(defect=defect))
    outcome, calls = await run(launcher)
    assert isinstance(outcome, ExecutorFailure)
    assert outcome.raw_reply is None and launcher.joined
    assert len(launcher.peer.users) == 1
    assert launcher.peer.callback_replies <= 1
    if defect == "co-buffered-terminal":
        assert calls == [] and launcher.peer.callback_replies == 0


async def test_clean_unentered_exchange_cannot_create_acceptance():
    class Skipping(Launcher):
        async def exchange(self, command, **kwargs):
            return self.result

    outcome, calls = await run(Skipping())
    assert isinstance(outcome, ExecutorFailure) and calls == []


@pytest.mark.parametrize("changes", [{"returncode": 1}, {"payload_returncode": None},
                                     {"payload_returncode": False}, {"timed_out": True},
                                     {"bound_exceeded": "stdout"}])
async def test_joined_process_evidence_is_required(changes):
    launcher = Launcher()
    launcher.result = replace(launcher.result, **changes)
    outcome, _ = await run(launcher)
    assert isinstance(outcome, ExecutorFailure) and outcome.raw_reply is None


@pytest.mark.parametrize("defect", ["terminal-session", "terminal-uuid", "terminal-error",
                                     "terminal-large", "post-mode", "post-callback",
                                     "wrong-server", "duplicate-callback"])
async def test_identity_shape_mode_and_replayed_callback_refusals(defect):
    launcher = Launcher(Peer(defect=defect))
    outcome, calls = await run(launcher)
    assert isinstance(outcome, ExecutorFailure) and outcome.raw_reply is None
    assert launcher.joined and len(calls) <= 1
    assert launcher.peer.callback_replies <= 1
    assert "private" not in outcome.model_dump_json()


@pytest.mark.parametrize("kind", ["eof", "terminal", "partial", "malformed"])
async def test_native_damage_cancels_and_joins_active_worker_before_response(kind):
    launcher = Launcher()
    joined = False

    async def worker(path, remaining):
        nonlocal joined
        if kind == "eof":
            launcher.peer.closed = True
            launcher.peer.ready.set()
        elif kind == "terminal":
            launcher.peer.terminal()
        else:
            launcher.peer.output.extend(b"{" if kind == "partial" else b"invalid\n")
            launcher.peer.ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            joined = True

    try:
        outcome, _ = await asyncio.wait_for(run(launcher, worker=worker), 1)
    except TimeoutError:
        pytest.fail("observed native damage must join the worker before the acquisition deadline")
    assert isinstance(outcome, ExecutorFailure) and joined and launcher.joined
    assert launcher.peer.callback_replies == 0


async def test_worker_finishing_simultaneously_with_eof_cannot_respond():
    launcher = Launcher()

    async def worker(path, remaining):
        launcher.peer.closed = True
        launcher.peer.ready.set()
        await asyncio.sleep(0)  # Put the pending reader's EOF before this worker's completion.
        return "file text"

    outcome, _ = await run(launcher, worker=worker)
    assert isinstance(outcome, ExecutorFailure) and launcher.peer.callback_replies == 0


@pytest.mark.parametrize("limit", ["input", "output", "worker"])
async def test_cumulative_native_and_per_worker_bounds_bind(limit):
    launcher = Launcher()
    if limit == "input":
        launcher.limits = replace(launcher.limits, input_bytes=1)
    if limit == "output":
        launcher.limits = replace(launcher.limits, stdout_bytes=1)

    async def worker(path, remaining):
        return "x" * (claude_read.TEXT_BYTES + 1)

    outcome, _ = await run(launcher, worker=worker if limit == "worker" else None)
    assert isinstance(outcome, ExecutorFailure) and launcher.joined
    assert launcher.peer.callback_replies == 0
    assert not [raw for raw in launcher.peer.writes
                if json.loads(raw).get("response", {}).get("request_id") == "outer-tools/call"]
    if limit == "input":
        assert launcher.peer.writes == []


@pytest.mark.parametrize("phase", ["user-write", "worker", "close", "join"])
async def test_cancellation_at_owned_awaits_is_static_and_joins(phase):
    launcher = Launcher()
    entered = asyncio.Event()
    worker_joined = False
    original_write, original_close = launcher.peer.write, launcher.peer.close_stdin

    async def write(data):
        await original_write(data)
        if phase == "user-write" and json.loads(data)["type"] == "user":
            entered.set()
            await asyncio.Event().wait()

    async def close():
        if phase == "close":
            entered.set()
            await asyncio.Event().wait()
        await original_close()

    async def worker(path, remaining):
        nonlocal worker_joined
        try:
            if phase == "worker":
                entered.set()
                await asyncio.Event().wait()
            return "file text"
        finally:
            worker_joined = True

    original_exchange = launcher.exchange

    async def exchange(command, **kwargs):
        result = await original_exchange(command, **kwargs)
        if phase == "join":
            entered.set()
            await asyncio.Event().wait()
        return result

    launcher.peer.write, launcher.peer.close_stdin = write, close
    launcher.exchange = exchange
    running = asyncio.create_task(run(launcher, worker=worker))
    await asyncio.wait_for(entered.wait(), 1)
    running.cancel("private cancel")
    with pytest.raises(asyncio.CancelledError) as caught:
        await running
    assert str(caught.value) == "Claude READ cancelled"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert launcher.joined and launcher.conversation._state == "refused"
    assert len(launcher.peer.users) == 1
    if phase != "user-write":
        assert worker_joined


async def test_reentry_poison_survives_resumption_without_a_second_dispatch():
    launcher = Launcher()
    entered, release = asyncio.Event(), asyncio.Event()
    original = launcher.peer.write

    async def write(data):
        await original(data)
        if json.loads(data)["type"] == "user":
            entered.set()
            await release.wait()

    launcher.peer.write = write
    running = asyncio.create_task(run(launcher))
    await asyncio.wait_for(entered.wait(), 1)
    other = Peer()
    with pytest.raises(claude_read._Refused):
        await launcher.conversation(other)
    release.set()
    outcome, _ = await running
    assert isinstance(outcome, ExecutorFailure) and launcher.conversation._state == "refused"
    assert len(launcher.peer.users) == 1 and other.writes == []


@pytest.mark.parametrize("defect", ["bad-path", "wrong-tool", "rpc-bool", "outer-duplicate",
                                     "extra-argument", "pre-dispatch-call"])
async def test_callback_identity_and_exact_admitted_operation_before_worker(defect):
    peer = Peer()
    original = peer.emit

    def emit(value):
        if value.get("type") == "control_request":
            message = value["request"]["message"]
            if message.get("method") == "tools/call":
                if defect == "bad-path":
                    message["params"]["arguments"]["path"] = "../private"
                if defect == "wrong-tool":
                    message["params"]["name"] = "execute"
                if defect == "rpc-bool":
                    message["id"] = True
                if defect == "outer-duplicate":
                    value["request_id"] = "outer-initialize"
                if defect == "extra-argument":
                    message["params"]["arguments"]["command"] = "private-command"
            if defect == "pre-dispatch-call" and message.get("method") == "initialize":
                message["method"] = "tools/call"
        original(value)

    peer.emit = emit
    outcome, calls = await run(Launcher(peer))
    assert isinstance(outcome, ExecutorFailure) and calls == [] and peer.callback_replies == 0


@pytest.mark.parametrize("tail", [b"invalid\n", b"{", wire({"type": "result"})])
async def test_tail_must_reach_actual_clean_eof_without_unclassified_bytes(tail):
    peer = Peer()
    original = peer.close_stdin

    async def close():
        peer.output.extend(tail)
        await original()

    peer.close_stdin = close
    outcome, _ = await run(Launcher(peer))
    assert isinstance(outcome, ExecutorFailure) and outcome.raw_reply is None


async def test_missing_eof_is_timeout():
    peer = Peer()

    async def close():
        pass  # Silence is not EOF.

    peer.close_stdin = close
    launcher = Launcher(peer)
    outcome, calls = await run(launcher, timeout=.05)
    assert isinstance(outcome, ExecutorFailure) and outcome.error.kind == "timeout"
    assert launcher.joined and len(calls) == 1


async def test_worker_gets_remaining_absolute_deadline_without_renewal(monkeypatch):
    observed = []

    async def worker(path, remaining):
        observed.append(remaining)
        return "file text"

    transaction = claude_read.ClaudeReadTransaction(
        TaskSpec(instruction="read"), selected_plan=ClaudePlan.PRO, model="model", effort="high",
        worker=worker, input_limit=1000, output_limit=1000, deadline=110,
    )
    transaction._state = "dispatched"
    pending = asyncio.create_task(asyncio.Event().wait())
    transaction._pending = pending
    monkeypatch.setattr(claude_read.asyncio, "get_running_loop",
                        lambda: SimpleNamespace(time=lambda: 108))
    try:
        assert await transaction._read_worker("README.md") == "file text"
        assert observed == [2]
    finally:
        pending.cancel()
        with suppress(asyncio.CancelledError):
            await pending


async def test_known_launcher_timeout_is_not_reported_as_an_exit():
    launcher = Launcher()
    launcher.result = replace(launcher.result, timed_out=True)
    outcome, _ = await run(launcher)
    assert isinstance(outcome, ExecutorFailure) and outcome.error.kind == "timeout"


async def test_public_output_is_bounded_task_text_not_private_control_metadata():
    peer = Peer(callback=False)
    original = peer.emit

    def emit(value):
        if value.get("type") == "result":
            value["result"] = "intentional private-account task output"
        original(value)

    peer.emit = emit
    outcome, _ = await run(Launcher(peer))
    assert isinstance(outcome, ExecutorSuccess)
    assert outcome.raw_reply == "intentional private-account task output"
    public = outcome.model_dump()
    assert public == {"status": "success", "raw_reply": outcome.raw_reply, "output": None,
                      "requested_model": "model", "served_model": None,
                      "usage": {"input_tokens": 1, "output_tokens": 1},
                      "rate_limit": None, "elapsed_s": outcome.elapsed_s}
    assert 0 <= outcome.elapsed_s <= 5
    assert len(outcome.raw_reply.encode()) <= claude_read.TEXT_BYTES


@pytest.mark.parametrize("timeout", [True, False, None, float("nan"), float("inf"), 0, 3600])
async def test_timeout_policy_is_exact_finite_and_below_policy_poll(timeout):
    with pytest.raises(ValueError, match="invalid Claude READ transaction parameters"):
        await run(Launcher(), timeout=timeout)


@pytest.mark.parametrize("overage", [None, False, True])
@pytest.mark.parametrize("terminal_error", [False, True])
@pytest.mark.parametrize("status", ["allowed", "allowed_warning", "rejected"])
async def test_emitted_overage_observation_is_preserved_on_success_and_refusal(
    overage, terminal_error, status,
):
    peer = Peer(callback=False, defect="terminal-error" if terminal_error else None)
    original = peer.emit

    def emit(value):
        if value.get("type") == "result":
            info = {"status": status}
            if overage is not None:
                info["isUsingOverage"] = overage
            original({"type": "rate_limit_event", "session_id": SESSION,
                      "uuid": NATIVE_UUID, "rate_limit_info": info})
        original(value)

    peer.emit = emit
    outcome, _ = await run(Launcher(peer))
    assert isinstance(outcome, ExecutorFailure if terminal_error or status == "rejected"
                      else ExecutorSuccess)
    assert outcome.rate_limit is not None
    assert outcome.rate_limit.is_using_overage is overage
    assert outcome.rate_limit.detail == {"status": status}


@pytest.mark.parametrize(("field", "value"), [
    ("duration_ms", {}), ("duration_api_ms", True), ("total_cost_usd", -1),
    ("num_turns", False), ("stop_reason", {}), ("usage", "malformed"),
    ("modelUsage", []), ("permission_denials", "malformed"),
    ("queued_turn_count", False), ("result_index", False),
    ("usage", {"input_tokens": False, "output_tokens": 1}),
    ("modelUsage", {"model": {"inputTokens": False}}),
])
async def test_terminal_metadata_is_exact_typed_and_never_coerced(field, value):
    peer = Peer(callback=False)
    original = peer.emit

    def emit(record):
        if record.get("type") == "result":
            record[field] = value
        original(record)

    peer.emit = emit
    outcome, _ = await run(Launcher(peer))
    assert isinstance(outcome, ExecutorFailure) and outcome.raw_reply is None


@pytest.mark.parametrize("field", ["duration_ms", "duration_api_ms", "num_turns", "stop_reason",
                                    "total_cost_usd", "usage", "modelUsage", "permission_denials"])
async def test_terminal_producer_metadata_cannot_be_omitted(field):
    peer = Peer(callback=False)
    original = peer.emit

    def emit(record):
        if record.get("type") == "result":
            del record[field]
        original(record)

    peer.emit = emit
    outcome, _ = await run(Launcher(peer))
    assert isinstance(outcome, ExecutorFailure)


async def test_host_instruction_is_literal_with_no_command_or_attachment_expansion():
    peer = Peer(callback=False)
    task = TaskSpec(instruction="/model other-model @private-file @server:resource")

    async def worker(path, remaining):
        pytest.fail("the literal zero-callback task grants no worker")

    outcome = await claude_read.run_read_transaction(
        Launcher(peer), ("fixed-nonvendor-peer",), task, selected_plan=ClaudePlan.PRO,
        model="model", effort="high", worker=worker, guard_fds=(), timeout_s=5,
    )
    assert isinstance(outcome, ExecutorSuccess)
    assert len(peer.users) == 1
    assert peer.users[0] == {"type": "user", "uuid": peer.users[0]["uuid"],
                             "message": {"role": "user", "content": task.instruction},
                             "parent_tool_use_id": None, "client_composed": True}


@pytest.mark.parametrize("failure", [None, "post-mode", "process", "cleanup", "terminal-error"])
async def test_terminal_usage_and_measured_elapsed_survive_later_refusal(monkeypatch, failure):
    peer = Peer(callback=False, defect=failure)
    original_emit = peer.emit

    def emit(value):
        if value.get("type") == "result":
            value["usage"]["input_tokens"] = 17
            value["usage"]["output_tokens"] = 23
            value["modelUsage"]["model"]["inputTokens"] = 1700
            value["modelUsage"]["model"]["outputTokens"] = 2300
        original_emit(value)

    peer.emit = emit
    launcher = Launcher(peer)
    if failure == "process":
        launcher.result = replace(launcher.result, payload_returncode=1)
    original_exchange = launcher.exchange
    started_time = asyncio.get_running_loop().time()
    observed_time = started_time

    async def exchange(command, **arguments):
        nonlocal observed_time
        try:
            result = await original_exchange(command, **arguments)
            if failure == "cleanup":
                raise OSError("private joined teardown error")
            return result
        finally:
            observed_time = started_time + 3.25

    launcher.exchange = exchange
    monkeypatch.setattr(claude_read.asyncio, "get_running_loop",
                        lambda: SimpleNamespace(time=lambda: observed_time))
    outcome, _ = await run(launcher)
    assert isinstance(outcome, ExecutorSuccess if failure is None else ExecutorFailure)
    assert launcher.joined
    # Native terminal usage is main-loop per-turn evidence, not modelUsage totals.
    assert outcome.usage == Usage(input_tokens=17, output_tokens=23)
    assert outcome.elapsed_s == 3.25
    if failure is not None:
        assert outcome.raw_reply is None


@pytest.mark.parametrize("defect", ["user-write", "terminal-session", "terminal-uuid"])
async def test_missing_or_uncorrelated_terminal_does_not_invent_usage(defect):
    outcome, _ = await run(Launcher(Peer(callback=False, defect=defect)))
    assert isinstance(outcome, ExecutorFailure) and outcome.usage is None


@pytest.mark.parametrize(("field", "value"), [("subtype", "unknown"), ("is_error", "false")])
async def test_unrecognized_terminal_schema_does_not_publish_usage(field, value):
    peer = Peer(callback=False)
    original = peer.emit

    def emit(record):
        if record.get("type") == "result":
            record[field] = value
        original(record)

    peer.emit = emit
    outcome, _ = await run(Launcher(peer))
    assert isinstance(outcome, ExecutorFailure) and outcome.usage is None
