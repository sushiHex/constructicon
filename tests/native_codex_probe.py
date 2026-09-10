"""Credential-free investigation instrument, NOT a production executor.

One app-server, thread and turn per probe. The only client-dispatched operation
is a supplied test worker; it never interprets a workspace, grant or identity
from model arguments. Scripted peers exercise this instrument independently of
the native CLI. No result here changes an ExecutorProfile's availability.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field

from constructicon.core.identity import parse_json_value
from constructicon.substrate._lifetime import finish_owned

RECORD_BYTES = 256 * 1024
TOTAL_BYTES = 2 * 1024 * 1024
CANARY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1s"
    "AAAAASUVORK5CYII="
)
TOOL = {
    "type": "function", "name": "contained_python",
    "description": "Run Python in the invocation's isolated test worker.",
    "inputSchema": {
        "type": "object", "properties": {"program": {"type": "string"}},
        "required": ["program"], "additionalProperties": False,
    },
}


class ProbeRefused(ValueError):
    """Damaged or out-of-scope protocol; no recovery/re-execution is attempted."""


@dataclass
class Dispatch:
    thread_id: str
    turn_id: str
    worker: Callable[[str], Awaitable[str]]
    seen: set[str] = field(default_factory=set)

    async def answer(self, message):
        params = message.get("params", {})
        if (
            message.get("method") != "item/tool/call"
            or type(message.get("id")) not in (str, int)
            or not isinstance(params, dict)
            or set(params) - {"threadId", "turnId", "callId", "tool", "arguments", "namespace"}
            or params.get("threadId") != self.thread_id
            or params.get("turnId") != self.turn_id
            or params.get("tool") != TOOL["name"]
            or params.get("namespace") is not None
        ):
            raise ProbeRefused("unknown operation or foreign invocation")
        call_id = params.get("callId")
        arguments = params.get("arguments")
        if (
            not isinstance(call_id, str) or not call_id or call_id in self.seen
            or not isinstance(arguments, dict) or set(arguments) != {"program"}
            or not isinstance(arguments["program"], str)
            or len(arguments["program"].encode()) > RECORD_BYTES
        ):
            raise ProbeRefused("invalid or repeated tool call")
        # Spend the call before awaiting the worker. Response loss never reruns it.
        self.seen.add(call_id)
        output = await self.worker(arguments["program"])
        if not isinstance(output, str) or len(output.encode()) > RECORD_BYTES:
            raise ProbeRefused("worker output bound")
        return {"id": message["id"], "result": {
            "contentItems": [{"type": "inputText", "text": output}], "success": True,
        }}


class Wire:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.received = 0
        self.sent = 0
        self.sequence = 0
        self.observed_methods = set()
        self.warnings = []

    async def read(self):
        try:
            raw = await self.reader.readline()
        except (ValueError, asyncio.LimitOverrunError) as exc:
            raise ProbeRefused("record bound") from exc
        self.received += len(raw)
        if not raw.endswith(b"\n") or len(raw) > RECORD_BYTES or self.received > TOTAL_BYTES:
            raise ProbeRefused("missing, truncated or oversized protocol")
        try:
            value = parse_json_value(raw.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ProbeRefused("malformed protocol") from exc
        if not isinstance(value, dict):
            raise ProbeRefused("protocol record is not an object")
        if "method" in value:
            if not isinstance(value["method"], str):
                raise ProbeRefused("invalid method")
            self.observed_methods.add(value["method"])
            if value["method"] in {"warning", "configWarning"}:
                self.warnings.append(value)
        return value

    async def send(self, value):
        raw = (json.dumps(value, ensure_ascii=True) + "\n").encode()
        self.sent += len(raw)
        if len(raw) > RECORD_BYTES or self.sent > TOTAL_BYTES:
            raise ProbeRefused("outbound protocol bound")
        self.writer.write(raw)
        await self.writer.drain()

    async def rpc(self, method, params):
        self.sequence += 1
        expected = self.sequence
        await self.send({"id": expected, "method": method, "params": params})
        while True:
            value = await self.read()
            if "id" not in value and "method" in value:
                continue  # Bounded notifications, never tool authority.
            if type(value.get("id")) is not int or value["id"] != expected:
                raise ProbeRefused("unexpected RPC response/request")
            if "error" in value or "result" not in value or "method" in value:
                raise ProbeRefused(f"RPC refused: {value}")
            return value["result"]


async def conversation(wire, cwd, worker):
    await wire.rpc("initialize", {
        "clientInfo": {"name": "constructicon_probe", "version": "0"},
        "capabilities": {"experimentalApi": True},
    })
    await wire.send({"method": "initialized"})
    started = await wire.rpc("thread/start", {
        "model": "probe-model", "modelProvider": "probe", "cwd": str(cwd),
        "approvalPolicy": "never", "sandbox": "danger-full-access",
        "ephemeral": True, "dynamicTools": [TOOL],
    })
    thread = started["thread"]["id"]
    turn = await wire.rpc("turn/start", {
        "threadId": thread,
        "input": [{"type": "text", "text": "Run the deterministic offline fixture."}],
    })
    dispatch = Dispatch(thread, turn["turn"]["id"], worker)
    while True:
        value = await wire.read()
        if "id" in value:
            await wire.send(await dispatch.answer(value))
        elif value.get("method") == "turn/completed":
            params = value["params"]
            if (
                params.get("threadId") != thread
                or params["turn"]["id"] != dispatch.turn_id
                or params["turn"]["status"] != "completed"
            ):
                raise ProbeRefused(f"turn failed or changed identity: {params}")
            return {"calls": sorted(dispatch.seen), "methods": sorted(wire.observed_methods),
                    "warnings": wire.warnings}


async def run_probe(argv, *, cwd, env, worker, timeout=30):
    """The native lane has an outer network/PID namespace and no credentials.

    Process-group cleanup here is lab hygiene, NOT escaped-descendant proof.
    The production Linux launcher owns and reaps the untrusted worker instead.
    """
    process = None
    stderr = bytearray()
    stopped = False

    async def drain():
        while chunk := await process.stderr.read(8192):
            stderr.extend(chunk)
            if len(stderr) > RECORD_BYTES:
                raise ProbeRefused("stderr bound")

    def stop():
        nonlocal stopped
        if process is None or stopped:
            return
        stopped = True
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        elif process.returncode is None:
            process.kill()

    async def close():
        stop()
        if process is not None:
            # Readers have left their TaskGroup. Drain killed-child pipes so a
            # paused asyncio transport cannot keep wait() blocked indefinitely.
            async with asyncio.timeout(5):
                await process.communicate()

    try:
        async with asyncio.timeout(timeout):
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=RECORD_BYTES, start_new_session=os.name == "posix",
            )
            async with asyncio.TaskGroup() as group:
                group.create_task(drain())
                wire = Wire(process.stdout, process.stdin)
                result = await conversation(wire, cwd, worker)
                stop()
                while chunk := await process.stdout.read(8192):
                    wire.received += len(chunk)
                    if wire.received > TOTAL_BYTES:
                        raise ProbeRefused("trailing stdout bound")
                await process.wait()
                # Join stderr through EOF: a terminal notification cannot hide
                # overflow already waiting in the other pipe.
            result["stderr_observed"] = stderr.decode("utf-8", errors="replace")
            return result
    except BaseException as exc:
        exc.add_note("probe stderr (bounded): " + stderr[:4096].decode("utf-8", errors="replace"))
        raise
    finally:
        await finish_owned(asyncio.create_task(close()))
