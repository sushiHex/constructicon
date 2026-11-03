"""Real Pi startup on the existing owned, networkless Linux process seam."""

import json
import os
import secrets
import socket
from dataclasses import replace
from pathlib import Path

import pytest

from constructicon.core.grants import Posture
from constructicon.core.identity import Digest
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors.linux import ProcessExchangeError
from constructicon.substrate.executors.pi_read import PI_LIMITS
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from constructicon.substrate.git.authority import GitAuthority
from tests.gitworld import seed_authority
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence

PI = "/opt/pi-startup/pi/pi"
FLAGS = (
    "--mode", "rpc", "--offline", "--no-session", "--no-approve", "--no-extensions", "--no-mcp",
    "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files",
    "--tools", "read",
)
BOOTSTRAP = """
import json, os, socket, sys
from pathlib import Path

host_net, port, *command = sys.argv[1:]
home = Path(os.environ["HOME"])
assert home == Path("/tmp/home") and home.is_dir() and not list(home.iterdir())
assert Path.cwd() == Path("/workspace")
assert Path("fixture.txt").is_file() and Path(".pi/settings.json").is_file()
assert "PI_CODING_AGENT_DIR" not in os.environ and "HTTPS_PROXY" not in os.environ
namespace = os.readlink("/proc/self/ns/net")
assert namespace != host_net
with socket.socket() as probe:
    probe.settimeout(1)
    error = probe.connect_ex(("127.0.0.1", int(port)))
assert error != 0
print(json.dumps({"fresh_home": str(home), "workspace": str(Path.cwd()),
                  "net_namespace": namespace, "host_loopback_connect_errno": error}), flush=True)
os.execv(command[0], command)
"""


class StartupWire:
    def __init__(self, io):
        self.io = io
        self.pending = bytearray()

    async def record(self):
        while b"\n" not in self.pending:
            chunk = await self.io.read()
            assert chunk, "EOF before required startup record"
            self.pending.extend(chunk)
        raw, _, tail = self.pending.partition(b"\n")
        self.pending[:] = tail
        return json.loads(raw)

    async def get_state(self, nonce):
        await self.io.write(json.dumps({"type": "get_state", "id": nonce}).encode() + b"\n")
        response = await self.record()
        assert response["type"] == "response" and response["command"] == "get_state"
        assert response["id"] == nonce and response["success"] is True
        state = response["data"]
        assert isinstance(state["sessionId"], str) and state["sessionId"]
        assert state.get("sessionFile") is None  # undefined fields are omitted by Pi
        assert state["isStreaming"] is False and state["isCompacting"] is False
        assert state["messageCount"] == state["pendingMessageCount"] == 0
        await self.io.close_stdin()
        assert not self.pending and await self.io.read() == b"", "unexpected trailing output"
        return state


@pytest.fixture
def pi_startup_launcher(launcher):
    location = os.environ.get("M8_PI_STARTUP_ROOT")
    if not location:
        if os.environ.get("M8_PI_STARTUP_REQUIRED"):
            pytest.fail("required pinned Pi startup image missing")
        pytest.skip("pinned Pi startup image not provisioned")
    root = Path(location)
    receipt = json.loads(root.with_suffix(".json").read_text())
    return replace(launcher, runtime_root=root, limits=PI_LIMITS,
                   expected_runtime=Digest(receipt["runtime_digest"])), receipt


async def test_real_pi_starts_and_drains(pi_startup_launcher, tmp_path):
    launcher, receipt = pi_startup_launcher
    bait = {
        "fixture.txt": "admitted read fixture",
        "AGENTS.md": "Project context must not be loaded for this startup.",
        ".pi/settings.json": '{"extensions":["./extensions/bait.ts"]}',
        ".pi/extensions/bait.ts": 'throw new Error("project Pi extension bait");\n',
        ".pi/skills/bait/SKILL.md": "---\nname: bait\ndescription: project bait\n---\n",
        ".pi/prompts/bait.md": "Project prompt bait",
    }
    authority = GitAuthority(seed_authority(tmp_path, bait), tmp_path / "snapshots")
    head = authority.read_ref("refs/heads/main")
    assert head is not None
    workspace = authority.read_snapshot(head)
    snapshot = Path(workspace.path)
    before = {name: (snapshot / name).read_bytes() for name in bait}
    host_net = os.readlink("/proc/self/ns/net")
    observations = {}

    async def conversation(io):
        wire = StartupWire(io)
        bootstrap = await wire.record()
        assert bootstrap["net_namespace"] != host_net
        assert bootstrap["host_loopback_connect_errno"] != 0
        assert bootstrap["fresh_home"] == "/tmp/home" and bootstrap["workspace"] == "/workspace"
        nonce = secrets.token_hex(16)
        observations.update(bootstrap=bootstrap, request_id=nonce)
        observations["state"] = await wire.get_state(nonce)
        observations["stdout_eof"] = True

    paths = AcquisitionPaths(tmp_path / "guards", acquisition_id_for("real-pi-startup", 1))
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                connected, _ = listener.accept()
                connected.close()
            async with acquisition_guard(paths) as guard:
                result = await launcher.exchange(
                    ("/usr/bin/python3", "-I", "-c", BOOTSTRAP, host_net, str(port), PI, *FLAGS),
                    workspace=snapshot, posture=Posture.READ, guard_fds=(guard,),
                    conversation=conversation, timeout_s=20,
                )
    except ProcessExchangeError as exc:
        pytest.fail(f"Pi startup exchange failed: {exc}; {exc.result!r}")
    finally:
        assert {name: (snapshot / name).read_bytes() for name in bait} == before
        authority.discard_snapshot(workspace)
    assert observations["stdout_eof"] is True
    assert result.returncode == result.payload_returncode == 0, result
    assert not result.timed_out and result.bound_exceeded is None
    assert b"project Pi extension bait" not in result.stderr
    assert not snapshot.exists()
    assert authority.read_ref("refs/heads/main") == head
    write_evidence("duplex-real-pi-startup.json", {
        "scope": "startup only; project discovery and effective tools unmeasured; no model request",
        "release": receipt, "launch_revision": str(launcher.revision), "flags": FLAGS,
        "observations": observations, "returncode": result.returncode,
        "payload_returncode": result.payload_returncode, "stderr_hex": result.stderr.hex(),
    })


@pytest.mark.parametrize("fault", [None, "id", "persisted", "trailing", "missing"])
async def test_startup_exchange_demands_matched_memory_only_state_and_eof(fault):
    class Peer:
        def __init__(self):
            self.closed = False
            self.records = []

        async def write(self, raw):
            assert json.loads(raw) == {"type": "get_state", "id": "startup-nonce"}
            if fault == "missing":
                return
            state = {
                "sessionId": "memory-session", "isStreaming": False, "isCompacting": False,
                "messageCount": 0, "pendingMessageCount": 0,
            }
            if fault == "persisted":
                state["sessionFile"] = "/tmp/session.jsonl"
            response = json.dumps({
                "type": "response", "command": "get_state", "success": True,
                "id": "unrelated" if fault == "id" else "startup-nonce", "data": state,
            }).encode() + b"\n"
            self.records = [response[:8], response[8:]]
            if fault == "trailing":
                self.records.append(b'{"type":"unexpected"}\n')

        async def read(self):
            return self.records.pop(0) if self.records else b""

        async def close_stdin(self):
            self.closed = True

    peer = Peer()
    wire = StartupWire(peer)
    if fault is None:
        assert (await wire.get_state("startup-nonce"))["sessionId"] == "memory-session"
        assert peer.closed and not peer.records
    else:
        with pytest.raises(AssertionError):
            await wire.get_state("startup-nonce")
