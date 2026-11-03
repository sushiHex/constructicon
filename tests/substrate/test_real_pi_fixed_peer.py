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
from constructicon.core.grants import Posture
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors._egress_bridge import PI_PORT
from constructicon.substrate.executors.pi_peer import PiPeerRoute
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

# This peer sees only its private directory; its own network namespace has no
# external interfaces. It has no forwarding code, route or proxy handling.
PEER = r"""
import http.server, json, os, socketserver

class Server(socketserver.UnixStreamServer):
    def get_request(self):
        sock, address = super().get_request()
        return sock, ("unix", 0)

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        assert self.headers["Authorization"] == "Bearer fixture-key"
        size = int(self.headers["Content-Length"])
        assert 0 < size < 65536
        request = json.loads(self.rfile.read(size))
        print(json.dumps({"request": request}), flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for delta, finish in [({"role": "assistant", "content": "fixed peer reply"}, None),
                              ({}, "stop")]:
            chunk = {"id": "fixture-reply", "object": "chat.completion.chunk", "created": 1,
                     "model": "fixture-model",
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

host_net, alternate, model, *command = sys.argv[1:]
net = os.readlink("/proc/self/ns/net")
assert net != host_net
assert not any(k.lower().endswith("_proxy") for k in os.environ)
assert not Path("pi.sock").exists()
assert Path("fixture.txt").read_text() == "read fixture"
with socket.socket() as probe:
    probe.settimeout(1)
    denied = probe.connect_ex(("127.0.0.1", int(alternate)))
assert denied != 0
print(json.dumps({"net": net, "alternate_errno": denied}), flush=True)
config = Path.home() / ".pi" / "agent"
config.mkdir(parents=True)
(config / "models.json").write_text(model)
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
    (workspace / "fixture.txt").write_bytes(b"read fixture")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    route = PiPeerRoute(private)
    host_net = os.readlink("/proc/self/ns/net")
    ready = asyncio.get_running_loop().create_future()
    captured = asyncio.get_running_loop().create_future()
    observations = {}
    model = json.dumps({"providers": {"fixture": {
        "baseUrl": f"http://127.0.0.1:{PI_PORT}/v1", "api": "openai-completions",
        "apiKey": "fixture-key", "models": [{"id": "fixture-model"}],
    }}})

    async def peer_conversation(io):
        wire = StartupWire(io)
        first = await wire.record()
        assert first["net"] != host_net
        route.ready(tuple(first["ready"]))
        ready.set_result(first["net"])
        captured.set_result((await wire.record())["request"])
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
        wire = StartupWire(io)
        observations["bootstrap"] = await wire.record()
        nonce = secrets.token_hex(16)
        prompt = {"id": nonce, "type": "prompt", "message": nonce}
        await io.write(json.dumps(prompt).encode() + b"\n")
        response = None
        while True:
            record = await wire.record()
            if record["type"] == "response":
                assert record["id"] == nonce and record["command"] == "prompt"
                assert record["success"] is True
                response = record
            if record["type"] == "agent_settled":
                assert record["aborted"] is False
                break
            if record["type"] == "agent_end":
                message = record["messages"][-1]
                assert message["role"] == "assistant" and message["stopReason"] == "stop"
                assert message["content"] == [{"type": "text", "text": "fixed peer reply"}]
                observations["reply"] = message["content"]
        assert response is not None and "reply" in observations
        request = await captured
        assert request["model"] == "fixture-model" and request["stream"] is True
        user = request["messages"][-1]
        assert user["role"] == "user"
        assert user["content"] in (nonce, [{"type": "text", "text": nonce}])
        assert len(request["tools"]) == 1
        tool = request["tools"][0]
        assert tool["type"] == "function" and tool["function"]["name"] == "read"
        assert tool["function"]["parameters"] == PARAMETERS
        observations["tools"] = request["tools"]
        observations["rpc_id"] = nonce
        await io.close_stdin()
        assert not wire.pending and await io.read() == b""

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
                result = await pi_launcher.exchange(
                    ("/usr/bin/python3", "-I", "-c", PI_BOOT, host_net, str(port), model,
                     PI, *FLAGS, "--provider", "fixture", "--model", "fixture-model",
                     "--thinking", "off"),
                    workspace=workspace, posture=Posture.READ, guard_fds=(guard,),
                    conversation=proof, timeout_s=25, pi_peer=route,
                )
            assert result.returncode == result.payload_returncode == 0, result
            assert not result.timed_out and result.bound_exceeded is None
            assert observations["bootstrap"]["net"] != observations["peer_net"]

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
    assert (workspace / "fixture.txt").read_bytes() == b"read fixture"
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

