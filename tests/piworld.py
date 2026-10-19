"""Source-shaped scripted Pi peer, never a vendor or model transcript."""

import asyncio
import inspect
import json
import sys
from pathlib import Path

from constructicon.substrate.executors.linux import ProcessResult


def record(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


def state(identifier):
    return {"type": "response", "id": identifier, "command": "get_state", "success": True,
            "data": {"model": {"provider": "fixture", "id": "pi-read"},
                     "thinkingLevel": "off", "isStreaming": False, "isCompacting": False,
                     "autoCompactionEnabled": False, "messageCount": 0,
                     "pendingMessageCount": 0}}


def assistant(content, reason, *, usage=True):
    message = {"role": "assistant", "content": content, "stopReason": reason,
               "api": "fixture", "provider": "fixture", "model": "pi-read", "timestamp": 2}
    if usage:
        message["usage"] = {"input": 3, "output": 2, "cacheRead": 0, "cacheWrite": 0,
                            "totalTokens": 5}
    return message


def cycle(instruction, text):
    user = {"role": "user", "content": instruction, "timestamp": 1}
    tool = {"type": "toolCall", "id": "read-1", "name": "read",
            "arguments": {"path": "fixture.txt"}}
    request = assistant([tool], "toolUse")
    result = {"role": "toolResult", "toolCallId": "read-1", "toolName": "read",
              "content": [{"type": "text", "text": text}], "isError": False, "timestamp": 3}
    final = assistant([{"type": "text", "text": "Read: " + text}], "stop")
    messages = [user, request, result, final]
    return [
        {"type": "agent_start"}, {"type": "turn_start"},
        {"type": "message_start", "message": user}, {"type": "message_end", "message": user},
        {"type": "message_start", "message": {**request, "content": [], "stopReason": "pending"}},
        {"type": "message_end", "message": request},
        {"type": "tool_execution_start", "toolCallId": "read-1", "toolName": "read",
         "args": tool["arguments"]},
        {"type": "tool_execution_update", "toolCallId": "read-1", "toolName": "read",
         "args": tool["arguments"], "partialResult": {"content": result["content"]}},
        {"type": "tool_execution_end", "toolCallId": "read-1", "toolName": "read",
         "result": {"content": result["content"]}, "isError": False},
        {"type": "message_start", "message": result},
        {"type": "message_end", "message": result},
        {"type": "turn_end", "message": request, "toolResults": [result]},
        {"type": "turn_start"},
        {"type": "message_start", "message": {**final, "content": [], "stopReason": "pending"}},
        {"type": "message_update", "usage": final["usage"],
         "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "ignored"}},
        {"type": "message_end", "message": final},
        {"type": "turn_end", "message": final, "toolResults": []},
        {"type": "agent_end", "messages": messages, "willRetry": False},
        {"type": "agent_settled", "aborted": False},
    ]


class PeerIO:
    """A real workspace read behind the same bounded byte conversation seam."""

    def __init__(self, workspace, *, transform=None, fragment=8192, block=None):
        self.workspace = Path(workspace)
        self.transform = transform or (lambda records: records)
        self.fragment = fragment
        self.block = block
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.available = asyncio.Event()
        self.buffer = bytearray()
        self.history = bytearray()
        self.writes = []
        self.closed = self.eof = False
        self.read_entered = False

    async def write(self, data):
        assert self.read_entered
        self.writes.append(data)
        command = json.loads(data)
        if command["type"] == "get_state":
            records = [state(command["id"])]
        else:
            assert command["type"] == "prompt"
            # The answer depends on actual admitted bytes, not an instruction lookup.
            text = (self.workspace / "fixture.txt").read_text("utf-8")
            records = self.transform(cycle(command["message"], text))
            # Deliberately complete before acknowledging dispatch.
            records.append({"type": "response", "id": command["id"], "command": "prompt",
                            "success": True, "data": {"disposition": "started"}})
        self.buffer.extend(b"".join(record(item) for item in records))
        self.available.set()
        if self.block == command["type"]:
            self.entered.set()
            await self.release.wait()

    async def read(self, maximum=8192):
        self.read_entered = True
        while not self.buffer and not self.closed:
            self.available.clear()
            await self.available.wait()
        amount = min(maximum, self.fragment, len(self.buffer))
        chunk = bytes(self.buffer[:amount])
        del self.buffer[:amount]
        self.history.extend(chunk)
        self.eof = not chunk
        return chunk

    async def close_stdin(self):
        self.closed = True
        self.available.set()


class PeerLauncher:
    """Only the platform primitive is substituted; no containment claim."""

    vendor = None

    def __init__(self, io, *, result=None):
        from constructicon.substrate.executors.pi_read import PI_LIMITS

        self.limits = PI_LIMITS
        self.io = io
        self.result = result
        self.joined = False
        self.calls = []

    async def exchange(self, command, **kwargs):
        self.calls.append((command, kwargs))
        try:
            try:
                async with asyncio.timeout(kwargs["timeout_s"]):
                    await kwargs["conversation"](self.io)
            except TimeoutError:
                return ProcessResult(125, bytes(self.io.history), b"", 0.01, timed_out=True)
            return self.result or ProcessResult(0, bytes(self.io.history), b"", 0.01,
                                               payload_returncode=0)
        finally:
            self.joined = True


def peer_source():
    """Identical harmless peer for native portable pipes and contained Linux."""
    return "import json, sys\nfrom pathlib import Path\n" + "\n".join(
        inspect.getsource(function) for function in (record, state, assistant, cycle)
    ) + """
command = json.loads(sys.stdin.buffer.readline())
assert command['type'] == 'get_state'
sys.stdout.buffer.write(record(state(command['id'])))
sys.stdout.buffer.flush()
command = json.loads(sys.stdin.buffer.readline())
assert command['type'] == 'prompt'
text = Path('fixture.txt').read_text(encoding='utf-8')
for event in cycle(command['message'], text):
    sys.stdout.buffer.write(record(event))
sys.stdout.buffer.write(record({'type':'response', 'id':command['id'], 'command':'prompt',
                               'success':True, 'data':{'disposition':'started'}}))
sys.stdout.buffer.flush()
assert sys.stdin.buffer.read() == b''
"""


class SubprocessLauncher:
    """Portable substitution of OS containment only; real pipes and child bytes.

    Uses the existing ProcessIO implementation. Payload status is this test
    double's observation, not the launcher's private supervisor attestation.
    """

    vendor = None

    def __init__(self):
        from constructicon.substrate.executors.pi_read import PI_LIMITS

        self.limits = PI_LIMITS
        self.joined = self.eof = False

    async def exchange(self, command, **kwargs):
        from constructicon.substrate.executors.linux import _ProcessIO

        process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", peer_source(), cwd=kwargs["workspace"], env={},
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output = bytearray()
        io = _ProcessIO(process.stdin, output, self.limits.input_bytes)

        async def capture():
            while chunk := await process.stdout.read(8192):
                output.extend(chunk)
                assert len(output) <= self.limits.stdout_bytes
                io.changed.set()
            self.eof = io.eof = True
            io.changed.set()

        reader = asyncio.create_task(capture())
        try:
            async with asyncio.timeout(kwargs["timeout_s"]):
                await kwargs["conversation"](io)
                await reader
                stderr = await process.stderr.read(self.limits.stderr_bytes + 1)
                status = await process.wait()
                assert len(stderr) <= self.limits.stderr_bytes
                return ProcessResult(status, bytes(output), stderr, .01, payload_returncode=status)
        finally:
            io.invalidate()
            if process.returncode is None:
                process.kill()
            await process.wait()
            await reader
            self.joined = True
