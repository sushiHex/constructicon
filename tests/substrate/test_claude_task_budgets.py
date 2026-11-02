"""Credential-free reproductions of pinned producer payload amplification."""

from dataclasses import replace

import pytest

from constructicon.core.executor import ExecutorFailure, ExecutorSuccess, TaskSpec
from constructicon.substrate.executors import claude_read
from constructicon.substrate.executors.claude_native import ClaudeNativeRecipe
from constructicon.substrate.executors.claude_protocol import ClaudeAuthMode
from tests.substrate.test_claude_read import (
    NATIVE_UUID,
    SESSION,
    Launcher,
    Peer,
    classifier_sideband,
    lifecycle,
    run,
    wire,
)
from tests.substrate.test_claude_write_protocol import WritePeer


@pytest.mark.parametrize("echo", [False, True])
async def test_control_character_read_reply_and_producer_echo_complete(echo):
    class EchoPeer(Peer):
        def terminal(self):
            if echo:
                content = [{"type": "text", "text": self.reply_text}]
                self.emit({"type": "user", "session_id": SESSION, "uuid": NATIVE_UUID,
                           "parent_tool_use_id": None,
                           "message": {"role": "user", "content": [
                               {"type": "tool_result", "tool_use_id": "tool-use-id",
                                "content": content}]}, "tool_use_result": content})
            super().terminal()

    peer = EchoPeer()
    peer.reply_text = "\x00" * claude_read.TEXT_BYTES
    launcher = Launcher(peer)
    launcher.limits = replace(launcher.limits, input_bytes=claude_read.task_input_bytes(
        ClaudeNativeRecipe.STREAM_JSON), record_bytes=claude_read.task_record_bytes(
            ClaudeNativeRecipe.STREAM_JSON))
    calls = []

    async def worker(path, remaining):
        calls.append(path)
        return peer.reply_text

    result, _ = await run(launcher, worker=worker)
    assert calls == ["README.md"]
    assert isinstance(result, ExecutorSuccess), result
    assert peer.callback_replies == 1 and launcher.joined


@pytest.mark.parametrize("budget", ["task", "legacy"])
async def test_eight_full_write_programs_fit_producer_stdout(budget):
    program = "#" + "x" * (128 * 1024 - 1)

    class ProducerPeer(WritePeer):
        def emit(self, value):
            if value.get("type") == "assistant":
                value["message"]["content"][0]["input"] = {"program": program}
            if (value.get("type") == "control_request"
                    and value["request"]["message"].get("method") == "tools/call"
                    and self.callback_replies):
                super().emit({"type": "assistant", "session_id": SESSION,
                              "uuid": NATIVE_UUID, "parent_tool_use_id": None,
                              "message": {"role": "assistant", "content": [
                                  {"type": "tool_use", "id": "tool-use-id",
                                   "name": ClaudeNativeRecipe.STREAM_JSON_WRITE.allowed_tool,
                                   "input": {"program": program}}]}})
            super().emit(value)

        def terminal(self):
            content = [{"type": "text", "text": self.reply_text}]
            self.emit({"type": "user", "session_id": SESSION, "uuid": NATIVE_UUID,
                       "parent_tool_use_id": None,
                       "message": {"role": "user", "content": [
                           {"type": "tool_result", "tool_use_id": "tool-use-id",
                            "content": content}]}, "tool_use_result": content})
            super().terminal()

    peer = ProducerPeer(count=8, argument={"program": program})
    peer.reply_text = "\x00" * (32 * 1024)
    launcher = Launcher(peer)
    launcher.limits = replace(launcher.limits, input_bytes=claude_read.task_input_bytes(
        ClaudeNativeRecipe.STREAM_JSON_WRITE), stdout_bytes=(claude_read.task_output_bytes(
            ClaudeNativeRecipe.STREAM_JSON_WRITE) if budget == "task" else 512 * 1024),
        record_bytes=claude_read.task_record_bytes(
                ClaudeNativeRecipe.STREAM_JSON_WRITE))
    calls = []

    async def worker(value, remaining):
        calls.append(value)
        return peer.reply_text

    result = await claude_read.run_read_transaction(
        launcher, ("fixed-nonvendor-peer",), TaskSpec(instruction="write"),
        mode=ClaudeAuthMode.SUBSCRIPTION, model="model", effort="high", worker=worker,
        guard_fds=(), timeout_s=5, recipe=ClaudeNativeRecipe.STREAM_JSON_WRITE,
    )
    if budget == "task":
        assert isinstance(result, ExecutorSuccess), (result, len(calls))
        assert calls == [program] * 8 and peer.callback_replies == 8
    else:
        assert isinstance(result, ExecutorFailure) and calls == []


async def test_full_startup_allowance_preserves_mandatory_post_result_controls():
    class CountingPeer(Peer):
        def __init__(self):
            super().__init__()
            self.post_bytes = 0

        async def write(self, raw):
            if self.post:
                self.post_bytes += len(raw)
            await super().write(raw)

    baseline = Launcher(CountingPeer())
    result, _ = await run(baseline)
    assert isinstance(result, ExecutorSuccess)
    used = sum(len(raw) for raw in baseline.peer.writes) - baseline.peer.post_bytes
    used -= sum(len(raw) for raw in baseline.peer.writes
                if b'"request_id":"outer-tools/call"' in raw)
    instruction = "read the file" + "x" * (claude_read.STARTUP_INPUT_BYTES - used)
    launcher = Launcher(CountingPeer())
    launcher.limits = replace(launcher.limits, input_bytes=claude_read.task_input_bytes(
        ClaudeNativeRecipe.STREAM_JSON))

    async def worker(path, remaining):
        return launcher.peer.reply_text

    result = await claude_read.run_read_transaction(
        launcher, ("fixed-nonvendor-peer",), TaskSpec(instruction=instruction),
        mode=ClaudeAuthMode.SUBSCRIPTION, model="model", effort="high", worker=worker,
        guard_fds=(), timeout_s=5,
    )
    assert isinstance(result, ExecutorSuccess), result
    assert launcher.peer.callback_replies == 1


@pytest.mark.parametrize("extra", [0, -1])
async def test_exact_id_reply_capacity_is_checked_before_worker(extra):
    outer, identifier = "\x00" * 128, "\x01" * 128

    class EscapedIds(Peer):
        def emit(self, value):
            if (value.get("type") == "control_request"
                    and value["request"]["message"].get("method") == "tools/call"):
                value["request_id"] = outer
                value["request"]["message"]["id"] = identifier
            super().emit(value)

        async def write(self, raw):
            import json

            value = json.loads(raw)
            if value.get("type") == "control_response" and value["response"]["request_id"] == outer:
                value["response"]["request_id"] = "outer-tools/call"
                value["response"]["response"]["mcp_response"]["id"] = 19
                raw = wire(value)
            await super().write(raw)

    startup = []
    baseline = Launcher(EscapedIds())

    async def measure(path, remaining):
        startup.append(baseline.conversation._input_bytes)
        return baseline.peer.reply_text

    result, _ = await run(baseline, worker=measure)
    assert isinstance(result, ExecutorSuccess)
    maximum = len(claude_read._callback_response(outer, identifier, {
        "content": [{"type": "text", "text": "\x00" * claude_read.TEXT_BYTES}], "isError": False,
    }))
    launcher = Launcher(EscapedIds())
    launcher.peer.reply_text = "\x00" * claude_read.TEXT_BYTES
    launcher.limits = replace(launcher.limits, input_bytes=(
        startup[0] + maximum + claude_read.POST_RESULT_INPUT_BYTES + extra))
    calls = []

    async def worker(path, remaining):
        calls.append(path)
        return launcher.peer.reply_text

    result, _ = await run(launcher, worker=worker)
    assert isinstance(result, ExecutorSuccess if extra == 0 else ExecutorFailure), result
    assert calls == (["README.md"] if extra == 0 else [])
    assert launcher.peer.callback_replies == (1 if extra == 0 else 0)


@pytest.mark.parametrize("recipe", [ClaudeNativeRecipe.STREAM_JSON,
                                   ClaudeNativeRecipe.STREAM_JSON_WRITE])
@pytest.mark.parametrize("field", ["input_bytes", "stdout_bytes", "record_bytes"])
@pytest.mark.parametrize("extra", [0, 1])
def test_task_launcher_profile_bounds_are_exact(recipe, field, extra):
    from constructicon.substrate.executors.claude_maintenance_session import _limits_ok
    from constructicon.substrate.executors.linux import ProcessLimits

    limits = ProcessLimits(input_bytes=claude_read.task_input_bytes(recipe),
                           stdout_bytes=claude_read.task_output_bytes(recipe),
                           record_bytes=claude_read.task_record_bytes(recipe),
                           stderr_bytes=64 * 1024)
    limits = replace(limits, **{field: getattr(limits, field) + extra})
    assert _limits_ok(limits, login=False, recipe=recipe) == (extra == 0)


@pytest.mark.parametrize("recipe,count", [(ClaudeNativeRecipe.STREAM_JSON, 2),
                                         (ClaudeNativeRecipe.STREAM_JSON_WRITE, 31)])
@pytest.mark.parametrize("queued", [False, True], ids=["parsed", "queued"])
async def test_consumed_stdout_refuses_before_worker_echo_cannot_fit(recipe, count, queued):
    base = Peer if recipe is ClaudeNativeRecipe.STREAM_JSON else WritePeer

    class Consumed(base):
        def mcp(self, method, **kwargs):
            if queued:
                super().mcp(method, **kwargs)
            if method == "tools/call":
                for _ in range(count):
                    self.emit(classifier_sideband("task_summary", detail="x" * 700000))
            if not queued:
                super().mcp(method, **kwargs)

        async def read(self, maximum=8192):
            # Split exactly after the callback. The next owned read need not
            # have started when admission inspects the transport's snapshot.
            newline = self.output.find(b"\n")
            if newline >= 0:
                maximum = min(maximum, newline + 1)
            return await super().read(maximum)

        def terminal(self):
            content = [{"type": "text", "text": self.reply_text}]
            self.emit({"type": "user", "session_id": SESSION, "uuid": NATIVE_UUID,
                       "parent_tool_use_id": None,
                       "message": {"role": "user", "content": [
                           {"type": "tool_result", "tool_use_id": "tool-use-id",
                            "content": content}]}, "tool_use_result": content})
            super().terminal()

    peer = Consumed()
    peer.reply_text = "\x00" * (65536 if recipe is ClaudeNativeRecipe.STREAM_JSON else 32768)
    launcher = Launcher(peer)
    launcher.limits = replace(launcher.limits, input_bytes=claude_read.task_input_bytes(recipe),
                              stdout_bytes=claude_read.task_output_bytes(recipe),
                              record_bytes=claude_read.task_record_bytes(recipe))
    calls, progress = [], []

    async def worker(argument, remaining):
        calls.append(argument)
        return peer.reply_text

    result = await claude_read.run_read_transaction(
        launcher, ("fixed-nonvendor-peer",), TaskSpec(instruction="task"),
        mode=ClaudeAuthMode.SUBSCRIPTION, model="model", effort="high", worker=worker,
        guard_fds=(), timeout_s=5, recipe=recipe, progress=progress.append,
    )
    assert isinstance(result, ExecutorFailure), result
    assert calls == progress == [] and peer.callback_replies == 0
    assert launcher.conversation._output_bytes < launcher.limits.stdout_bytes
    assert launcher.conversation._output_bytes == peer.stdout_bytes_received


@pytest.mark.parametrize("snapshot", [True, -1, 0, 5000000])
async def test_invalid_captured_stdout_snapshot_refuses_before_worker(snapshot):
    class Invalid(Peer):
        @property
        def stdout_bytes_received(self):
            return snapshot

    launcher = Launcher(Invalid())
    launcher.limits = replace(launcher.limits, stdout_bytes=claude_read.task_output_bytes(
        ClaudeNativeRecipe.STREAM_JSON))
    result, calls = await run(launcher)
    assert isinstance(result, ExecutorFailure)
    assert calls == [] and launcher.peer.callback_replies == 0


@pytest.mark.parametrize("recipe", [ClaudeNativeRecipe.STREAM_JSON,
                                   ClaudeNativeRecipe.STREAM_JSON_WRITE])
@pytest.mark.parametrize("boundary", ["completed", "cancelled", "eof"])
async def test_already_captured_lifecycle_and_eof_precede_worker_authority(recipe, boundary):
    base = Peer if recipe is ClaudeNativeRecipe.STREAM_JSON else WritePeer

    class Boundary(base):
        def mcp(self, method, **kwargs):
            super().mcp(method, **kwargs)
            if method == "tools/call":
                if boundary == "eof":
                    self.closed = True
                else:
                    self.emit(lifecycle(self, boundary))

        async def read(self, maximum=8192):
            newline = self.output.find(b"\n")
            if newline >= 0:
                maximum = min(maximum, newline + 1)
            return await super().read(maximum)

    peer, calls, progress = Boundary(), [], []
    launcher = Launcher(peer)

    async def worker(argument, remaining):
        calls.append(argument)
        return peer.reply_text

    result = await claude_read.run_read_transaction(
        launcher, ("fixed-nonvendor-peer",), TaskSpec(instruction="task"),
        mode=ClaudeAuthMode.SUBSCRIPTION, model="model", effort="high", worker=worker,
        guard_fds=(), timeout_s=5, recipe=recipe, progress=progress.append,
    )
    assert isinstance(result, ExecutorFailure), result
    assert calls == progress == [] and peer.callback_replies == 0
    if boundary == "eof":
        assert peer.stdout_eof_received is True
        assert peer.stdout_bytes_received == launcher.conversation._output_bytes
        assert launcher.conversation._eof is True
    else:
        assert launcher.conversation._output_bytes == peer.stdout_bytes_received
        if boundary == "completed":
            assert launcher.conversation._command_completed is True


@pytest.mark.parametrize("fault", ["byte-type", "byte-regression", "byte-overflow", "eof-type",
                                   "eof-regression", "bytes-after-eof", "parsed-eof-conflict"])
async def test_capture_snapshot_rejects_contradictory_or_nonmonotonic_facts(fault):
    import asyncio
    from types import SimpleNamespace

    transaction = claude_read.ClaudeReadTransaction(
        TaskSpec(instruction="task"), mode=ClaudeAuthMode.SUBSCRIPTION, model="model",
        effort="high", worker=lambda argument, remaining: asyncio.sleep(0, "text"),
        input_limit=1000, output_limit=100, deadline=asyncio.get_running_loop().time() + 5,
    )
    channel = SimpleNamespace(stdout_bytes_received=8, stdout_eof_received=False)
    transaction._io = channel
    assert transaction._capture_snapshot() == (8, False)
    if fault == "byte-type":
        channel.stdout_bytes_received = True
    elif fault == "byte-regression":
        channel.stdout_bytes_received = 7
    elif fault == "byte-overflow":
        channel.stdout_bytes_received = 101
    elif fault == "eof-type":
        channel.stdout_eof_received = 1
    elif fault == "parsed-eof-conflict":
        transaction._eof = True
    else:
        channel.stdout_eof_received = True
        assert transaction._capture_snapshot() == (8, True)
        if fault == "eof-regression":
            channel.stdout_eof_received = False
        else:
            channel.stdout_bytes_received = 9
    with pytest.raises(claude_read._Refused):
        transaction._capture_snapshot()


async def test_cumulative_stdout_ceiling_binds_without_callback_admission():
    launcher = Launcher(Peer(callback=False))
    launcher.limits = replace(launcher.limits, stdout_bytes=1)
    result, calls = await run(launcher)
    assert isinstance(result, ExecutorFailure) and calls == []
    assert "known_refusal=stream-bound" in result.error.detail
