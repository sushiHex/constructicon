"""Internal fake-first persistent Claude READ transaction, never availability.

The caller owns the sealed physical recipe and the fixed contained READ worker.
This module supplies neither a native store nor an ExecutorProvider. Correlation
accounts for received bytes; it cannot establish unread-buffer arrival freshness.
"""

from __future__ import annotations

import asyncio
import json
import math
import secrets
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import replace
from typing import Literal

from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorOutcome,
    ExecutorSuccess,
    RateLimitInfo,
    TaskSpec,
    Usage,
)
from constructicon.core.grants import Posture
from constructicon.core.identity import parse_json_value
from constructicon.core.process import ProcessIO
from constructicon.substrate.executors.claude_initialize import _cancelled, _clean
from constructicon.substrate.executors.claude_native import ClaudeNativeStoreMount
from constructicon.substrate.executors.claude_native_events import exact_ui_invalidate
from constructicon.substrate.executors.claude_protocol import (
    RECORD_BYTES,
    ClaudeInitializeVerdict,
    ClaudePlan,
    initialize_request,
    judge_initialize,
)
from constructicon.substrate.executors.claude_read_worker import validate_read_path
from constructicon.substrate.executors.claude_startup import (
    ClaudeStartupVerdict,
    hooks_request,
    judge_hooks,
    judge_settings,
    settings_request,
)
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.executors.operator_store import BindingCheck

TEXT_BYTES = 64 * 1024
CALL_LIMIT = 1
UI_RECORDS = 8
SERVER = "constructicon_read"
READ_TOOL: dict[str, object] = {
    "name": "read_file", "description": "Read one relative workspace file.",
    "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                    "required": ["path"], "additionalProperties": False},
}
ReadWorker = Callable[[str, float], Awaitable[str]]


class _Refused(Exception):
    """Private static refusal; no wire value is included."""


def _wire(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


def _parse(raw: bytes) -> dict[str, object]:
    try:
        value = parse_json_value(raw[:-1].decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        raise _Refused() from None
    if type(value) is not dict or b"\r" in raw:
        raise _Refused()
    return value


def _text(value: object, limit: int) -> bool:
    if type(value) is not str:
        return False
    try:
        return len(value.encode("utf-8")) <= limit
    except UnicodeError:
        return False


def _uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _nonnegative(value: object) -> bool:
    if type(value) is int:
        return value >= 0
    return type(value) is float and math.isfinite(value) and value >= 0


def _result_metadata(value: dict[str, object]) -> bool:
    """Judge terminal fields; bounded extra timing detail stays unjudged/private."""
    required = {"duration_ms", "duration_api_ms", "num_turns", "stop_reason", "total_cost_usd",
                "usage", "modelUsage", "permission_denials"}
    if not required <= set(value):
        return False
    if (any(not _nonnegative(value[key]) for key in
            ("duration_ms", "duration_api_ms", "total_cost_usd"))
            or type(value["num_turns"]) is not int or value["num_turns"] < 0
            or not (value["stop_reason"] is None or _text(value["stop_reason"], 128))
            or value["permission_denials"] != []):
        return False
    for key in ("queued_turn_count", "result_index"):
        if key in value and (type(value[key]) is not int or value[key] != 0):
            return False
    usage, models = value["usage"], value["modelUsage"]
    if (type(usage) is not dict or type(models) is not dict
            or not {"input_tokens", "output_tokens"} <= set(usage)):
        return False
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens"):
        if key in usage and (type(usage[key]) is not int or usage[key] < 0):
            return False
    for model, counts in models.items():
        if not _text(model, 256) or type(counts) is not dict:
            return False
        for key, count in counts.items():
            if key in ("canonicalModel", "provider", "costBasis"):
                if not _text(count, 256):
                    return False
            elif not _nonnegative(count):
                return False
    if "safety_stops" in value and (type(value["safety_stops"]) is not int
                                    or value["safety_stops"] != 0):
        return False
    if "subagent_stats" in value:
        # HX's fresh-session snapshot. This recipe admits no agent tool/call.
        empty = {"spawned": 0, "requested": {"background": 0, "foreground": 0, "unset": 0},
                 "started_in_background": 0, "max_depth": 0, "spawned_by_subagents": 0,
                 "completed": 0, "failed": 0, "killed": {"parent": 0, "user": 0, "system": 0},
                 "refused": {"depth_limit": 0, "concurrency_limit": 0, "budget": 0}, "by_type": {}}
        # Canonical JSON distinguishes false from zero as well as extra keys.
        if json.dumps(value["subagent_stats"], sort_keys=True) != json.dumps(empty, sort_keys=True):
            return False
    return True


class ClaudeReadTransaction:
    """Single use, one pending read, one dispatch, and at most one READ call."""

    def __init__(
        self, task: TaskSpec, *, selected_plan: ClaudePlan, model: str, effort: str,
        worker: ReadWorker, input_limit: int, output_limit: int, deadline: float,
        before_user: Callable[[], None] | None = None,
        check_control: Callable[[], None] | None = None,
    ) -> None:
        self._task, self._plan, self._model, self._effort = task, selected_plan, model, effort
        self._worker = worker
        self._before_user, self._check_control = before_user, check_control
        self._input_limit, self._output_limit, self._deadline = input_limit, output_limit, deadline
        self._state: Literal["new", "startup", "ready", "dispatched", "terminal",
                             "checked", "drained", "refused"] = "new"
        self._input_bytes = self._output_bytes = 0
        self._buffer = bytearray()
        self._records: list[bytes] = []
        self._pending: asyncio.Task[bytes] | None = None
        self._io: ProcessIO | None = None
        self._eof = False
        self._user_uuid = str(uuid.uuid4())
        self._session: str | None = None
        self._startup_session: str | None = None
        self._handshake = 0
        self._outer_ids: set[str] = set()
        self._rpc_ids: set[tuple[type[object], str | int]] = set()
        self._calls = 0
        self._calls_completed = 0
        self._ui_records = 0
        self._reply: str | None = None
        self._rate_limit: RateLimitInfo | None = None
        self._usage: Usage | None = None

    def _check(self) -> None:
        if self._check_control is not None:
            self._check_control()
        task = asyncio.current_task()
        if (self._state == "refused" or asyncio.get_running_loop().time() >= self._deadline
                or (task is not None and task.cancelling())):
            self._state = "refused"
            raise _Refused()

    def _start_read(self) -> None:
        assert self._io is not None
        self._pending = asyncio.create_task(self._io.read(8192))

    def _receive(self, chunk: bytes) -> None:
        if type(chunk) is not bytes or len(chunk) > 8192:
            raise _Refused()
        self._output_bytes += len(chunk)
        if self._output_bytes > self._output_limit:
            raise _Refused()
        if not chunk:
            self._eof = True
            return
        self._buffer.extend(chunk)
        while (newline := self._buffer.find(b"\n")) >= 0:
            if newline + 1 > RECORD_BYTES:
                raise _Refused()
            self._records.append(bytes(self._buffer[:newline + 1]))
            del self._buffer[:newline + 1]
        if len(self._buffer) >= RECORD_BYTES:
            raise _Refused()
        self._start_read()

    def _audit(self) -> None:
        self._check()
        if self._pending is not None and self._pending.done():
            pending, self._pending = self._pending, None
            self._receive(pending.result())

    async def _next(self) -> bytes:
        self._audit()
        while not self._records:
            if self._eof or self._pending is None:
                raise _Refused()
            pending, self._pending = self._pending, None
            chunk = await pending
            self._check()
            self._receive(chunk)
        return self._records.pop(0)

    def _background(self, value: dict[str, object]) -> bool:
        return (set(value) == {"type", "subtype", "tasks", "uuid", "session_id"}
                and value.get("type") == "system"
                and value.get("subtype") == "background_tasks_changed"
                and value.get("tasks") == [] and _uuid(value.get("session_id"))
                and value.get("session_id") == (self._session or self._startup_session)
                and _uuid(value.get("uuid")))

    def _ui(self, value: dict[str, object]) -> bool:
        if value.get("type") != "system" or value.get("subtype") != "ui_invalidate":
            return False
        if not exact_ui_invalidate(value) or self._ui_records >= UI_RECORDS:
            raise _Refused()
        self._ui_records += 1
        return True

    def _quiet(self) -> None:
        self._audit()
        while self._records:
            value = _parse(self._records[0])
            if not (self._background(value) or self._ui(value)):
                break
            self._records.pop(0)
        if self._records or self._buffer or self._eof:
            raise _Refused()

    async def _write(self, raw: bytes, *, user: bool = False) -> None:
        self._check()
        self._input_bytes += len(raw)  # Spent before delivery, including uncertain writes.
        if self._input_bytes > self._input_limit or len(raw) > RECORD_BYTES:
            raise _Refused()
        assert self._io is not None
        if user and self._before_user is not None:
            self._before_user()
        await self._io.write(raw)
        self._audit()

    async def _control(self, kind: str, *, register: bool = False) -> None:
        self._quiet()
        identifier = secrets.token_hex(16)
        if kind == "initialize":
            raw = initialize_request(identifier)
            if register:
                value = json.loads(raw)
                value["request"]["sdkMcpServers"] = [SERVER]
                raw = _wire(value)
        elif kind == "get_settings":
            raw = settings_request(identifier)
        else:
            raw = hooks_request(identifier)
        await self._write(raw)
        while True:
            response = await self._next()
            value = _parse(response)
            if self._ui(value) or self._background(value):
                continue
            if register and value.get("type") == "control_request":
                await self._mcp(value, handshake=True)
                continue
            if kind == "initialize":
                verdict = judge_initialize(response, expected_request_id=identifier,
                                           selected_plan=self._plan)
                if verdict is not ClaudeInitializeVerdict.MODE_MATCH:
                    raise _Refused()
            elif kind == "get_settings":
                if judge_settings(response, expected_request_id=identifier, model=self._model,
                                  effort=self._effort) is not ClaudeStartupVerdict.MATCH:
                    raise _Refused()
            elif (judge_hooks(response, expected_request_id=identifier)
                  is not ClaudeStartupVerdict.MATCH):
                raise _Refused()
            break
        if kind == "initialize" and (register or self._state == "terminal"):
            while True:
                snapshot = _parse(await self._next())
                if self._ui(snapshot):
                    continue
                if register and snapshot.get("type") == "control_request":
                    await self._mcp(snapshot, handshake=True)
                    continue
                if register and self._startup_session is None:
                    if not _uuid(snapshot.get("session_id")):
                        raise _Refused()
                    self._startup_session = str(snapshot["session_id"])
                if not self._background(snapshot):
                    raise _Refused()
                break

    async def _observations(self) -> None:
        for kind in ("initialize", "get_settings", "get_hooks_listing"):
            await self._control(kind)

    async def _mcp(self, value: dict[str, object], *, handshake: bool = False) -> None:
        if set(value) != {"type", "request_id", "request"}:
            raise _Refused()
        outer, request = value["request_id"], value["request"]
        if (not _text(outer, 128) or not outer or outer in self._outer_ids
                or type(request) is not dict
                or set(request) != {"subtype", "server_name", "message"}
                or request.get("subtype") != "mcp_message" or request.get("server_name") != SERVER):
            raise _Refused()
        assert isinstance(outer, str)
        self._outer_ids.add(outer)
        message = request["message"]
        if type(message) is not dict or message.get("jsonrpc") != "2.0":
            raise _Refused()
        method, identifier = message.get("method"), message.get("id")
        notification = method == "notifications/initialized"
        if not set(message) <= {"jsonrpc", "id", "method", "params"}:
            raise _Refused()
        if notification:
            if "id" in message or message.get("params", {}) != {}:
                raise _Refused()
            identifier = 0  # Pinned SDK synthetic acknowledgement for native notification.
        else:
            if type(identifier) not in (int, str) or not _text(str(identifier), 128):
                raise _Refused()
            assert isinstance(identifier, (int, str))
            key = (type(identifier), identifier)
            if key in self._rpc_ids:
                raise _Refused()
            self._rpc_ids.add(key)
        result: dict[str, object]
        if handshake:
            expected = ("initialize", "notifications/initialized", "tools/list")
            if self._handshake >= 3 or method != expected[self._handshake]:
                raise _Refused()
            if method == "initialize":
                params = message.get("params")
                if (type(params) is not dict
                        or set(params) != {"protocolVersion", "capabilities", "clientInfo"}
                        or params.get("protocolVersion") != "2025-11-25"
                        or params.get("capabilities") != {}):
                    raise _Refused()
                client = params["clientInfo"]
                if (type(client) is not dict or client.get("name") != "claude-code"
                        or client.get("version") != "2.1.296"
                        or not set(client) <= {"name", "version", "title", "description",
                                              "websiteUrl"}
                        or any(not _text(item, 1024) for item in client.values())):
                    raise _Refused()
                result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                          "serverInfo": {"name": SERVER, "version": "1"}}
            elif notification:
                result = {}
            else:
                if message.get("params", {}) != {}:
                    raise _Refused()
                result = {"tools": [READ_TOOL]}
            self._handshake += 1
        else:
            if (self._state != "dispatched" or self._session is None
                    or method != "tools/call" or self._calls >= CALL_LIMIT):
                raise _Refused()
            params = message.get("params")
            if (type(params) is not dict or set(params) != {"name", "arguments"}
                    or params.get("name") != "read_file"):
                raise _Refused()
            arguments = params["arguments"]
            if type(arguments) is not dict or set(arguments) != {"path"}:
                raise _Refused()
            path = arguments["path"]
            if not validate_read_path(path):
                raise _Refused()
            assert isinstance(path, str)
            self._quiet()  # A terminal or partial frame in this chunk defeats worker authority.
            self._calls += 1  # ID and admitted start are spent before the worker's first await.
            text = await self._read_worker(path)
            if not _text(text, TEXT_BYTES):
                raise _Refused()
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        await self._write(_wire({"type": "control_response", "response": {
            "subtype": "success", "request_id": outer,
            "response": {"mcp_response": {"jsonrpc": "2.0", "id": identifier, "result": result}},
        }}))
        if not handshake:
            self._calls_completed += 1

    async def _read_worker(self, path: str) -> str:
        remaining = self._deadline - asyncio.get_running_loop().time()
        task = asyncio.ensure_future(self._worker(path, remaining))
        try:
            while not task.done():
                assert self._pending is not None
                await asyncio.wait((task, self._pending), return_when=asyncio.FIRST_COMPLETED)
                self._quiet()  # Read wins even when worker and EOF/terminal finish together.
            text = await task
            self._quiet()
            return text
        except BaseException as error:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except BaseException as cleanup:
                if cleanup is not error:
                    raise BaseExceptionGroup("Claude READ worker failed",
                                             [error, cleanup]) from None
            raise

    async def _body(self) -> None:
        await self._observations()
        await self._control("initialize", register=True)
        while self._handshake != 3:
            await self._mcp(_parse(await self._next()), handshake=True)
        self._quiet()
        self._state = "ready"
        self._state = "dispatched"
        await self._write(_wire({"type": "user", "uuid": self._user_uuid,
                                 "message": {"role": "user", "content": self._task.instruction},
                                 "parent_tool_use_id": None, "client_composed": True}), user=True)
        while True:
            value = _parse(await self._next())
            if self._ui(value):
                continue
            if value.get("type") == "control_request":
                await self._mcp(value)
            elif value.get("type") == "system" and value.get("subtype") == "init":
                if (self._session is not None or not _uuid(value.get("session_id"))
                        or value.get("session_id") != self._startup_session
                        or not _uuid(value.get("uuid")) or value.get("model") != self._model
                        or value.get("tools") != ["mcp__constructicon_read__read_file"]
                        or value.get("mcp_servers") != [{"name": SERVER, "status": "connected"}]):
                    raise _Refused()
                self._session = str(value["session_id"])
            elif value.get("type") in ("assistant", "user"):
                if (self._session is None or value.get("session_id") != self._session
                        or not _uuid(value.get("uuid"))
                        or value.get("parent_tool_use_id") is not None
                        or type(value.get("message")) is not dict):
                    raise _Refused()
                message = value["message"]
                assert isinstance(message, dict)
                if (message.get("role") != value["type"] or "error" in value
                        or "aborted" in value or "agent_id" in value
                        or value.get("user_message_uuid", self._user_uuid) != self._user_uuid
                        or value.get("user_message_uuids", [self._user_uuid]) != [self._user_uuid]):
                    raise _Refused()
                if value["type"] == "user":
                    content = message.get("content")
                    if (self._calls_completed != 1 or type(content) is not list or not content
                            or any(type(block) is not dict or block.get("type") != "tool_result"
                                   for block in content)):
                        raise _Refused()
            elif value.get("type") == "rate_limit_event":
                info = value.get("rate_limit_info")
                if (set(value) != {"type", "rate_limit_info", "uuid", "session_id"}
                        or self._session is None or value.get("session_id") != self._session
                        or not _uuid(value.get("uuid")) or type(info) is not dict
                        or info.get("status") not in ("allowed", "allowed_warning", "rejected")):
                    raise _Refused()
                overage = info.get("isUsingOverage")
                if "isUsingOverage" in info and type(overage) is not bool:
                    raise _Refused()
                self._rate_limit = RateLimitInfo(
                    is_using_overage=overage if type(overage) is bool else None,
                    detail={"status": info["status"]},
                )
                if info["status"] == "rejected":
                    raise _Refused()
            elif value.get("type") == "result":
                allowed = {"type", "subtype", "is_error", "session_id", "user_message_uuid",
                           "result", "uuid", "duration_ms", "duration_api_ms", "num_turns",
                           "stop_reason", "total_cost_usd", "usage", "modelUsage",
                           "permission_denials", "queued_turn_count", "result_index",
                           "user_message_uuids", "request_sent_wall_ms", "ttft_ms",
                           "ttft_stream_ms",
                           "time_to_request_ms", "first_content_frame_ms", "time_origin_ms",
                           "time_to_request_from_spawn_ms", "terminal_reason", "fast_mode_state",
                           "fast_mode_disabled_reason", "api_error_status", "origin",
                           "safety_stops", "subagent_stats", "time_to_request_phases_ms",
                           "turn_start_resume_kind", "process_turn_index",
                           "time_to_request_loop_lag_ms", "time_to_request_cpu_ms",
                           "time_to_request_major_faults", "input_attachments_detail",
                           "resume_store_confirm_detail", "first_stream_post_ms",
                           "first_stream_post_ack_ms", "first_stream_post_queue_wait_ms",
                           "first_stream_post_queued_behind", "first_text_post_ms",
                           "first_text_post_queue_wait_ms", "first_text_post_queued_behind",
                           "first_request_input_tokens", "user_message_server_received_wall_ms",
                           "first_stream_post_wall_ms", "first_text_post_wall_ms",
                           "frame_received_wall_ms", "frame_enqueued_wall_ms",
                           "turn_started_wall_ms", "frame_intake_phases_ms",
                           "turn_start_phases_ms", "turn_start_control_requests_ms",
                           "warm_spare_claimed", "flag_fetch_kick"}
                if (not set(value) <= allowed or not _result_metadata(value)
                        or self._session is None
                        or value.get("subtype") != "success"
                        or type(value.get("is_error")) is not bool
                        or value.get("session_id") != self._session
                        or not _uuid(value.get("uuid"))
                        or value.get("user_message_uuid") != self._user_uuid
                        or value.get("user_message_uuids", [self._user_uuid]) != [self._user_uuid]):
                    raise _Refused()
                terminal_usage = value["usage"]
                assert isinstance(terminal_usage, dict)
                # These emitted counts cover this turn's main loop, not all
                # provider requests/helpers or the cumulative modelUsage map.
                self._usage = Usage(input_tokens=terminal_usage["input_tokens"],
                                    output_tokens=terminal_usage["output_tokens"])
                if (not _text(value.get("result"), TEXT_BYTES)
                        or value.get("is_error") is not False):
                    raise _Refused()
                self._reply = str(value["result"])
                break
            else:
                raise _Refused()
        self._state = "terminal"
        await self._observations()
        self._quiet()
        self._state = "checked"
        assert self._io is not None
        await self._io.close_stdin()
        self._audit()
        while not self._eof or self._records:
            if self._records:
                value = _parse(self._records.pop(0))
                if not (self._ui(value) or self._background(value)):
                    raise _Refused()
            elif self._pending is not None:
                pending, self._pending = self._pending, None
                chunk = await pending
                self._check()
                self._receive(chunk)
            else:
                raise _Refused()
        if self._buffer:
            raise _Refused()
        self._check()
        self._state = "drained"

    async def __call__(self, io: ProcessIO) -> None:
        if self._state != "new":
            self._state = "refused"
            raise _Refused()
        self._state, self._io = "startup", io
        self._start_read()
        try:
            await self._body()
        except BaseException as error:
            self._state = "refused"
            if self._pending is not None:
                pending, self._pending = self._pending, None
                if not pending.done():
                    pending.cancel()
                try:
                    await pending
                except asyncio.CancelledError:
                    pass
                except BaseException as cleanup:
                    raise BaseExceptionGroup("Claude READ reader failed",
                                             [error, cleanup]) from None
            raise


async def run_read_transaction(
    launcher: LinuxLauncher, command: tuple[str, ...], task: TaskSpec, *,
    selected_plan: ClaudePlan, model: str, effort: str, worker: ReadWorker,
    guard_fds: tuple[int, ...], timeout_s: float,
    native_store: ClaudeNativeStoreMount | None = None,
    before_user: Callable[[], None] | None = None,
    check_control: Callable[[], None] | None = None,
) -> ExecutorOutcome:
    """Publish only after this same exchange and all owned work have joined."""
    if (type(selected_plan) is not ClaudePlan or not _text(model, 256) or not model
            or not _text(effort, 32) or not effort or type(timeout_s) not in (int, float)
            or not math.isfinite(timeout_s)
            or not 0 < timeout_s < 3600 or task.context or task.response_schema is not None):
        raise ValueError("invalid Claude READ transaction parameters")
    cancelled = False
    success = False
    timed_out = False
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    conversation = ClaudeReadTransaction(
        task, selected_plan=selected_plan, model=model, effort=effort, worker=worker,
        input_limit=launcher.limits.input_bytes, output_limit=launcher.limits.stdout_bytes,
        deadline=started_at + timeout_s,
        before_user=before_user, check_control=check_control,
    )
    try:
        launch_store = native_store
        if native_store is not None:
            if (type(native_store) is not ClaudeNativeStoreMount
                    or native_store.lock_fd not in guard_fds or launcher.claude is None
                    or command != launcher.claude.command
                    or model != launcher.claude.model or effort != launcher.claude.effort):
                raise _Refused()
            initial_binding = native_store.before_spawn()
            if type(initial_binding) is not BindingCheck:
                raise _Refused()

            def check_binding() -> BindingCheck:
                checked = native_store.before_spawn()
                if type(checked) is not BindingCheck or checked != initial_binding:
                    raise _Refused()
                return checked

            launch_store = replace(native_store, before_spawn=check_binding)
        try:
            async with asyncio.timeout_at(started_at + timeout_s):
                result = await launcher.exchange(
                    command, workspace=None, posture=Posture.READ, guard_fds=guard_fds,
                    conversation=conversation, timeout_s=started_at + timeout_s - loop.time(),
                    native_store=launch_store,
                )
        except BaseException:
            if launch_store is not None:
                # exchange has joined; check retained custody on every outcome.
                # Its primary cancellation/fatal failure must remain primary.
                with suppress(BaseException):
                    launch_store.before_spawn()
            raise
        if launch_store is not None:
            launch_store.before_spawn()
        conversation._check()
        success = _clean(result) and conversation._state == "drained"
        timed_out = result.timed_out is True
    except (Exception, asyncio.CancelledError, BaseExceptionGroup) as error:
        conversation._state = "refused"
        current = asyncio.current_task()
        cancelled = _cancelled(error) or (current is not None and current.cancelling() > 0)
        timed_out = isinstance(error, TimeoutError)
        if not cancelled and not isinstance(error, Exception):
            raise
    if cancelled:
        raise asyncio.CancelledError("Claude READ cancelled") from None
    elapsed_s = loop.time() - started_at
    if success:
        return ExecutorSuccess(raw_reply=conversation._reply, requested_model=model,
                               usage=conversation._usage, elapsed_s=elapsed_s,
                               rate_limit=conversation._rate_limit)
    return ExecutorFailure(requested_model=model,
                           usage=conversation._usage, elapsed_s=elapsed_s,
                           rate_limit=conversation._rate_limit,
                           error=ExecutorError(kind="timeout" if timed_out else "exit",
                                               detail="Claude READ refused"))
