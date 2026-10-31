"""WRITE exercises the same credential-free protocol owner as READ."""

import json

import pytest

from constructicon.core.executor import ExecutorFailure, ExecutorSuccess, TaskSpec
from constructicon.core.identity import digest
from constructicon.substrate.executors import claude_read
from constructicon.substrate.executors.claude_native import (
    ClaudeNativeRecipe,
    ClaudeNativeStoreMount,
    ClaudeNativeVendor,
)
from constructicon.substrate.executors.claude_protocol import ClaudeAuthMode
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.substrate.test_claude_read import Launcher, Peer, lifecycle, wire

WRITE = ClaudeNativeRecipe.STREAM_JSON_WRITE


def translate(value, *, writing):
    if isinstance(value, dict):
        return {({"path": "program"} if writing else {"program": "path"}).get(k, k):
                translate(v, writing=writing) for k, v in value.items()}
    if isinstance(value, list):
        return [translate(v, writing=writing) for v in value]
    pairs = {"constructicon_read": "constructicon_write", "read_file": "contained_python",
             "mcp__constructicon_read__read_file": WRITE.allowed_tool,
             "README.md": "print('ready')"}
    if not writing:
        pairs = {v: k for k, v in pairs.items()}
    return pairs.get(value, value) if isinstance(value, str) else value


class WritePeer(Peer):
    """Reuse the pinned SDK envelope fixture with a distinct hosted tool."""

    def __init__(self, *, count=1, argument=None, **kwargs):
        super().__init__(**kwargs)
        self.count, self.argument = count, argument
        self.original_writes = []

    def emit(self, value):
        value = translate(value, writing=True)
        if value.get("type") == "control_request":
            message = value["request"]["message"]
            if message.get("method") == "tools/call":
                ordinal = self.callback_replies
                message["id"] = 19 + ordinal
                value["request_id"] = f"outer-call-{ordinal}"
                if self.argument is not None:
                    message["params"]["arguments"] = self.argument
        super().emit(value)

    async def write(self, data):
        self.original_writes.append(json.loads(data))
        value = json.loads(data)
        if value["type"] == "control_response":
            response = value["response"]
            if response["request_id"] == "outer-tools/list":
                assert response["response"]["mcp_response"]["result"]["tools"] == [WRITE.tool]
                response["response"]["mcp_response"]["result"]["tools"] = [claude_read.READ_TOOL]
            if response["request_id"].startswith("outer-call-"):
                response["request_id"] = "outer-tools/call"
                response["response"]["mcp_response"]["id"] = 19
        await super().write(wire(translate(value, writing=False)))

    def terminal(self):
        if self.callback and self.callback_replies < self.count:
            self.mcp("tools/call", identifier=19)
        else:
            super().terminal()


async def run_write(peer, *, progress=None):
    calls = []

    async def worker(program, remaining):
        assert 0 < remaining <= 5
        calls.append(program)
        return "file text"

    launcher = Launcher(peer)
    result = await claude_read.run_read_transaction(
        launcher, ("fixed-nonvendor-peer",), TaskSpec(instruction="write the fixed file"),
        mode=ClaudeAuthMode.SUBSCRIPTION, model="model", effort="high", worker=worker,
        guard_fds=(), timeout_s=5, recipe=WRITE, progress=progress,
    )
    assert launcher.joined
    return result, calls


@pytest.mark.parametrize("count", [1, 2, 8])
async def test_sequential_write_callbacks_share_one_dispatch(count):
    peer, progress = WritePeer(count=count), []
    result, calls = await run_write(peer, progress=progress.append)
    assert isinstance(result, ExecutorSuccess)
    assert calls == ["print('ready')"] * count
    assert progress == ["started", "worker_success", "response_completed"] * count
    assert len(peer.users) == 1
    assert peer.handshake == ["initialize", "initialized", "list"]


@pytest.mark.parametrize("argument", [{"path": "ready.txt"}, {"program": 1},
                                      {"program": "x" * (128 * 1024 + 1)},
                                      {"program": "pass", "actor": "forged"}],
                         ids=["read-shape", "nontext", "program-bound", "extra-field"])
async def test_write_argument_refusal_precedes_worker(argument):
    result, calls = await run_write(WritePeer(argument=argument))
    assert isinstance(result, ExecutorFailure)
    assert calls == []


async def test_write_program_byte_bound_accepts_its_exact_boundary():
    program = "x" * (128 * 1024)
    result, calls = await run_write(WritePeer(argument={"program": program}))
    assert isinstance(result, ExecutorSuccess)
    assert calls == [program]


async def test_write_callback_ceiling_refuses_ninth_effect():
    result, calls = await run_write(WritePeer(count=9))
    assert isinstance(result, ExecutorFailure)
    assert len(calls) == 8


async def test_write_requires_a_completed_callback():
    result, calls = await run_write(WritePeer(callback=False))
    assert isinstance(result, ExecutorFailure)
    assert calls == []


async def test_lost_write_response_is_not_recorded_completed():
    progress = []
    result, calls = await run_write(WritePeer(defect="callback-write"), progress=progress.append)
    assert isinstance(result, ExecutorFailure)
    assert len(calls) == 1
    assert progress == ["started", "worker_success"]


async def test_progress_persistence_failure_refuses_before_effect():
    def refuse(event):
        raise OSError("observation not durable")

    result, calls = await run_write(WritePeer(), progress=refuse)
    assert isinstance(result, ExecutorFailure)
    assert calls == []


async def test_completed_response_persistence_failure_cannot_publish_success():
    events = []

    def record(event):
        events.append(event)
        if event == "response_completed":
            raise OSError("completion not durable")

    result, calls = await run_write(WritePeer(), progress=record)
    assert isinstance(result, ExecutorFailure)
    assert len(calls) == 1
    assert events == ["started", "worker_success", "response_completed"]


async def test_buffered_parallel_write_call_refuses_before_effect():
    class Parallel(WritePeer):
        def __init__(self):
            super().__init__()
            self.extra = False

        def emit(self, value):
            super().emit(value)
            if (not self.extra and value.get("type") == "control_request"
                    and value["request"]["message"].get("method") == "tools/call"):
                self.extra = True
                self.mcp("tools/call", identifier=20)

    result, calls = await run_write(Parallel())
    assert isinstance(result, ExecutorFailure)
    assert calls == []


@pytest.mark.parametrize("fragmented", [False, True])
async def test_completed_command_buffered_before_next_callback_refuses(fragmented):
    class CompletedBetweenCalls(WritePeer):
        def terminal(self):
            if self.callback_replies == 1:
                self.mcp("tools/call", identifier=20)
                if fragmented:
                    # A partial completed frame is not evidence of a quiet channel.
                    self.output.extend(wire(lifecycle(self))[:-1])
                    self.ready.set()
                else:
                    self.emit(lifecycle(self))
            else:
                super().terminal()

    progress = []
    result, calls = await run_write(CompletedBetweenCalls(count=2), progress=progress.append)
    assert isinstance(result, ExecutorFailure)
    assert calls == ["print('ready')"]
    assert progress == ["started", "worker_success", "response_completed"]


def test_closed_native_recipes_never_enable_builtin_tools(tmp_path):
    vendor = ClaudeNativeVendor(tmp_path, "model", "low", "sha256:" + "0" * 64)
    read = ClaudeNativeRecipe.STREAM_JSON.command(vendor)
    write = WRITE.command(vendor)
    assert read == vendor.command
    assert write[write.index("--tools") + 1] == ""
    assert write[write.index("--allowedTools") + 1] == WRITE.allowed_tool
    assert sum(a != b for a, b in zip(read, write, strict=True)) == 1
    assert ClaudeNativeRecipe.STREAM_JSON.tool == claude_read.READ_TOOL


@pytest.mark.parametrize("selected", [ClaudeNativeRecipe.STREAM_JSON, WRITE])
async def test_write_native_recipe_is_checked_before_store_or_dispatch(tmp_path, selected):
    launcher = Launcher(WritePeer())
    launcher.claude_recipe = selected
    launcher.claude = ClaudeNativeVendor(tmp_path, "model", "high", digest("test", 1, "vendor"))
    checks, calls = [], []

    def check():
        checks.append(launcher.joined)
        return BindingCheck(digest("test", 1, "binding"))

    async def worker(program, remaining):
        calls.append(program)
        return "file text"

    result = await claude_read.run_read_transaction(
        launcher, WRITE.command(launcher.claude), TaskSpec(instruction="write the fixed file"),
        mode=ClaudeAuthMode.SUBSCRIPTION, model="model", effort="high", worker=worker,
        guard_fds=(42,), timeout_s=5, recipe=WRITE,
        native_store=ClaudeNativeStoreMount(42, 43, check),
    )
    if selected is WRITE:
        assert isinstance(result, ExecutorSuccess)
        assert calls == ["print('ready')"]
        assert checks == [False, False, True]
    else:
        assert isinstance(result, ExecutorFailure)
        assert checks == calls == []
