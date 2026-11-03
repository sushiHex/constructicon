"""Credential-free wire proof through the real Linux launcher and pinned Pi."""

import asyncio
import json
import os
import secrets
import socket
import sys
from contextlib import suppress

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.grants import Posture
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors._egress_bridge import PI_PORT
from constructicon.substrate.executors.linux import ProcessExchangeError
from constructicon.substrate.executors.pi_peer import PiPeerRoute
from constructicon.substrate.executors.pi_read import PI_LIMITS, PiReadConversation
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence
from tests.substrate.test_real_pi_startup import FLAGS, PI, StartupWire
from tests.substrate.test_real_pi_startup import pi_startup_launcher as pi_startup_launcher

# Pinned producer: packages/coding-agent/src/core/tools/read.ts and
# packages/ai/src/api/openai-completions.ts at 71023aec1546d6d677a65669c5665c0927ce0dd0.
PARAMETERS = {
    "type": "object",
    "required": ["path"],
    "properties": {
        "path": {
            "type": "string", "description": "Path to the file to read (relative or absolute)",
        },
        "offset": {
            "type": "number", "description": "Line number to start reading from (1-indexed)",
        },
        "limit": {"type": "number", "description": "Maximum number of lines to read"},
    },
}

PROMPT = "Read fixture.txt once, then repeat its contents exactly."
CALL_ID = "call_fixture_read"

# This peer sees only its private directory; its own network namespace has no
# external interfaces. It has no forwarding code, route or proxy handling.
PEER = r"""
import http.server, json, os, socketserver

class Server(socketserver.UnixStreamServer):
    def get_request(self):
        sock, address = super().get_request()
        return sock, ("unix", 0)

class Handler(http.server.BaseHTTPRequestHandler):
    requests = 0

    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        assert self.headers["Authorization"] == "Bearer fixture-key"
        size = int(self.headers["Content-Length"])
        assert 0 < size < 65536
        request = json.loads(self.rfile.read(size))
        type(self).requests += 1
        print(json.dumps({"request": request}), flush=True)
        if self.requests == 1:
            deltas = [
                ({"role": "assistant", "tool_calls": [
                    {"index": 0, "id": "call_fixture_read", "type": "function",
                     "function": {"name": "read", "arguments": '{"path":'}}]}, None),
                ({"tool_calls": [
                    {"index": 0, "function": {"arguments": '"fixture.txt"}'}}]}, None),
                ({}, "tool_calls"),
            ]
        else:
            assert self.requests == 2
            tool = request["messages"][-1]
            assert tool["role"] == "tool" and tool["tool_call_id"] == "call_fixture_read"
            content = tool["content"]
            if isinstance(content, list):
                assert len(content) == 1 and content[0]["type"] == "text"
                content = content[0]["text"]
            assert isinstance(content, str) and 0 < len(content) <= 128
            deltas = [
                ({"role": "assistant", "content": content[:8]}, None),
                ({"content": content[8:]}, None),
                ({}, "stop"),
            ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for delta, finish in deltas:
            chunk = {"id": "fixture-reply", "object": "chat.completion.chunk", "created": 1,
                     "model": "pi-read",
                     "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")

    def do_GET(self):
        assert self.path == "/hold"
        self.wfile.write(b"H")
        assert self.rfile.read(1) == b"X"
        self.wfile.write(b"A")
        # Owner revocation has to close this already accepted stream.
        self.rfile.read(1)

with Server("pi.sock", Handler) as server:
    st = os.lstat("pi.sock")
    print(json.dumps({"ready": [st.st_dev, st.st_ino],
                      "net": os.readlink("/proc/self/ns/net")}), flush=True)
    server.serve_forever()
"""

PI_BOOT = r"""
import json, os, socket, sys
from pathlib import Path

host_net, alternate, model, value, *command = sys.argv[1:]
net = os.readlink("/proc/self/ns/net")
assert net != host_net
assert not any(k.lower().endswith("_proxy") for k in os.environ)
assert not Path("pi.sock").exists()
assert Path("fixture.txt").read_text() == value
with socket.socket() as probe:
    probe.settimeout(1)
    denied = probe.connect_ex(("127.0.0.1", int(alternate)))
assert denied != 0
print(json.dumps({"net": net, "alternate_errno": denied}), flush=True)
config = Path.home() / ".pi" / "agent"
config.mkdir(parents=True)
(config / "models.json").write_text(model)
(config / "settings.json").write_text(
    '{"compaction":{"enabled":false},"retry":{"enabled":false,"provider":{"maxRetries":0}},'
    '"cacheWarming":"off"}')
os.execv(command[0], command)
"""

HOLD = r"""
import socket, sys
target = ("127.0.0.1", int(sys.argv[1]))
with socket.create_connection(target, timeout=8) as stream:
    stream.sendall(b"GET /hold HTTP/1.0\r\n\r\n")
    assert stream.recv(1) == b"H"
    stream.sendall(b"X")
    assert stream.recv(1) == b"A"
    print('{"accepted":true}', flush=True)
    assert sys.stdin.buffer.readline() == b"deny\n"
    with socket.socket() as new:
        new.settimeout(1)
        # The bridge still accepts TCP; the acquired inode denies new connects.
        assert new.connect_ex(target) == 0
        try:
            new.sendall(b"GET /hold HTTP/1.0\r\n\r\n")
            assert new.recv(1) == b""
        except (BrokenPipeError, ConnectionResetError):
            pass
    print('{"new_connect_denied":true}', flush=True)
    assert stream.recv(1) == b""
print('{"revoked":true}', flush=True)
"""


async def test_pinned_pi_fixed_peer_wire_and_active_revocation(pi_startup_launcher, tmp_path):
    pi_launcher, receipt = pi_startup_launcher
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fixture = workspace / "fixture.txt"
    value = secrets.token_hex(12)
    fixture.write_bytes(value.encode())
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    route = PiPeerRoute(private)
    host_net = os.readlink("/proc/self/ns/net")
    ready = asyncio.get_running_loop().create_future()
    captured = asyncio.get_running_loop().create_future()
    requests = []
    conversation = PiReadConversation(
        TaskSpec(instruction=PROMPT), input_limit=PI_LIMITS.input_bytes,
    )
    decoder = conversation.decoder
    observations = {}
    model = json.dumps({"providers": {"fixture": {
        "baseUrl": f"http://127.0.0.1:{PI_PORT}/v1", "api": "openai-completions",
        "apiKey": "fixture-key", "models": [{"id": "pi-read"}],
    }}})

    async def peer_conversation(io):
        wire = StartupWire(io)
        first = await wire.record()
        assert first["net"] != host_net
        route.ready(tuple(first["ready"]))
        ready.set_result(first["net"])
        for _ in range(2):
            requests.append((await wire.record())["request"])
        captured.set_result(tuple(requests))
        await asyncio.Future()

    async def run_peer(guard):
        try:
            return await pi_launcher.exchange(
                ("/usr/bin/python3", "-I", "-c", PEER), workspace=private,
                posture=Posture.WRITE, guard_fds=(guard,), conversation=peer_conversation,
                timeout_s=80,
            )
        finally:
            route.revoke()

    async def stop_peer(peer):
        try:
            route.revoke()
        finally:
            peer.cancel()
            with suppress(asyncio.CancelledError):
                await peer

    async def proof(io):
        # Consume exactly the bootstrap line; every Pi byte goes to the real decoder.
        bootstrap = bytearray()
        while not bootstrap.endswith(b"\n"):
            chunk = await io.read(1)
            assert chunk and len(bootstrap) < 1024
            bootstrap.extend(chunk)
        observations["bootstrap"] = json.loads(bootstrap)
        await conversation(io)

    def diagnostics(result):
        # This lane carries only synthetic fixture data. Retain the first
        # offending RPC excerpt and capped stderr to diagnose pinned wire drift.
        return {
            "scope": "scripted Pi READ; no model inference",
            "release": receipt,
            "request_count": len(requests),
            "returncode": result.returncode,
            "payload_returncode": result.payload_returncode,
            "timed_out": result.timed_out,
            "bound_exceeded": result.bound_exceeded,
            "state_observed": decoder.state_observed,
            "prompt_accepted": decoder.accepted,
            "agent_started": decoder.started,
            "agent_ended": decoder.ended,
            "settled": decoder.settled,
            "eof": decoder.eof,
            "refused": decoder.refused,
            "damage_count": decoder.damage_count,
            "first_error": decoder.error,
            "first_damaged_record": decoder.excerpt,
            "read_count": len(decoder.calls),
            "final_observed": decoder.final is not None,
            "records": decoder.count,
            "stdout_bytes": decoder.total,
            "stderr_excerpt": result.stderr[:1024].decode("utf-8", errors="replace"),
        }

    paths = AcquisitionPaths(tmp_path / "guards", acquisition_id_for("pi-fixed-peer", 1))
    # Both sequential worker launches share this one acquisition and peer.
    # The guard and private directory outlive both workers and peer shutdown.
    async with acquisition_guard(paths) as guard:
        peer = asyncio.create_task(run_peer(guard))
        try:
            async with asyncio.timeout(25):
                done, _ = await asyncio.wait((peer, ready), return_when=asyncio.FIRST_COMPLETED)
                assert peer not in done, peer.result() if peer in done else None
                observations["peer_net"] = ready.result()
            with socket.create_server(("127.0.0.1", 0)) as alternate:
                port = alternate.getsockname()[1]
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    connected, _ = alternate.accept()
                    connected.close()
                try:
                    result = await pi_launcher.exchange(
                        ("/usr/bin/python3", "-I", "-c", PI_BOOT, host_net, str(port), model,
                         value, PI, *FLAGS, "--provider", "fixture", "--model", "pi-read",
                         "--thinking", "off"),
                        workspace=workspace, posture=Posture.READ, guard_fds=(guard,),
                        conversation=proof, timeout_s=25, pi_peer=route,
                    )
                except ProcessExchangeError as exc:
                    write_evidence(
                        "duplex-real-pi-fixed-peer-progress.json", diagnostics(exc.result),
                    )
                    raise
            progress = diagnostics(result)
            write_evidence("duplex-real-pi-fixed-peer-progress.json", progress)
            assert result.returncode == result.payload_returncode == 0, progress
            assert not result.timed_out and result.bound_exceeded is None, progress
            assert observations["bootstrap"]["net"] != observations["peer_net"]
            assert decoder.state_observed and decoder.accepted and decoder.started, progress
            assert decoder.ended and decoder.eof and decoder.settled, progress
            assert not decoder.damage_count and not decoder.refused, progress
            assert set(decoder.calls) == {CALL_ID}
            call = decoder.calls[CALL_ID]
            assert call.arguments == {"path": "fixture.txt"} and call.started and call.ended
            expected = [{"type": "text", "text": value}]
            assert call.result is not None and call.content == expected
            assert decoder.final == value

            first, second = await asyncio.wait_for(captured, timeout=5)
            for request in (first, second):
                assert request["model"] == "pi-read" and request["stream"] is True
                assert len(request["tools"]) == 1
                tool = request["tools"][0]
                assert tool["type"] == "function" and tool["function"]["name"] == "read"
                assert tool["function"]["parameters"] == PARAMETERS
            user = first["messages"][-1]
            assert user["role"] == "user"
            assert user["content"] in (PROMPT, [{"type": "text", "text": PROMPT}])
            assistant, tool_result = second["messages"][-2:]
            assert assistant["role"] == "assistant"
            assert len(assistant["tool_calls"]) == 1
            tool_call = assistant["tool_calls"][0]
            assert tool_call["id"] == tool_result["tool_call_id"] == CALL_ID
            assert tool_call["function"]["name"] == "read"
            assert json.loads(tool_call["function"]["arguments"]) == {"path": "fixture.txt"}
            assert tool_result["role"] == "tool" and tool_result["content"] in (value, expected)
            observations["tools"] = first["tools"]
            observations["one_read"] = observations["exact_final"] = observations["eof"] = True

            async def active(io):
                wire = StartupWire(io)
                assert await wire.record() == {"accepted": True}
                route.revoke()
                await io.write(b"deny\n")
                assert await wire.record() == {"new_connect_denied": True}
                assert not peer.done()
                await stop_peer(peer)
                assert peer.done()
                assert await wire.record() == {"revoked": True}
                await io.close_stdin()
                assert not wire.pending and await io.read() == b""

            hold = await pi_launcher.exchange(
                ("/usr/bin/python3", "-I", "-c", HOLD, str(PI_PORT)),
                workspace=workspace, posture=Posture.READ, guard_fds=(guard,),
                conversation=active, timeout_s=25, pi_peer=route,
            )
            assert hold.returncode == hold.payload_returncode == 0, hold
            assert not hold.timed_out and hold.bound_exceeded is None
        finally:
            await finish_owned(asyncio.create_task(stop_peer(peer)))
    assert sorted(item.name for item in workspace.iterdir()) == ["fixture.txt"]
    assert fixture.read_bytes() == value.encode()
    (private / "pi.sock").unlink()
    private.rmdir()
    write_evidence("duplex-real-pi-fixed-peer.json", {
        "scope": "credential-free Pi READ wire proof; no live model",
        "release": receipt, "observations": observations,
        "accepted_stream_closed": True, "peer_joined": peer.done(),
        "new_connect_denied_before_peer_exit": True,
    })


@pytest.mark.skipif(sys.platform != "linux", reason="Linux Unix-socket inode semantics")
def test_revoking_replaced_peer_leaf_affects_only_original_socket(tmp_path):
    route = PiPeerRoute(tmp_path)
    leaf = tmp_path / "pi.sock"
    original = tmp_path / "original.sock"
    target = tmp_path / "target"
    target.write_bytes(b"unrelated")
    mode = target.stat().st_mode
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(leaf))
        listener.listen()
        info = leaf.lstat()
        route.ready((info.st_dev, info.st_ino))
        leaf.rename(original)
        leaf.symlink_to(target)
        with pytest.raises(ContractViolation, match="owned socket"):
            route.require_current()
        route.revoke()
        assert original.stat().st_mode & 0o777 == 0
        assert target.stat().st_mode == mode
        with pytest.raises(ContractViolation, match="cannot become ready"):
            route.ready((info.st_dev, info.st_ino))

