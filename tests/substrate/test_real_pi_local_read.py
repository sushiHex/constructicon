"""Manual-only one-shot local model READ through the fixed acquisition peer."""

import asyncio
import json
import os
import re
import secrets
from dataclasses import replace
from pathlib import Path

import pytest

from constructicon.core.executor import TaskSpec
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors._egress_bridge import PI_PORT
from constructicon.substrate.executors.pi_peer import PiPeerRoute
from constructicon.substrate.executors.pi_read import PiReadConversation
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence
from tests.substrate.test_real_pi_startup import FLAGS, PI, StartupWire
from tests.substrate.test_real_pi_startup import pi_startup_launcher as pi_startup_launcher

SERVER = r"""
import http.client, json, os, socket, subprocess, time
p = subprocess.Popen(['/opt/pi-local/llama-server', '--host', '/workspace/pi.sock',
                      '-m', '/opt/pi-local/model.gguf', '--ctx-size', '1024',
                      '--threads', '2', '--parallel', '1', '--n-predict', '128',
                      '--alias', 'pi-read', '--reasoning', 'off', '--jinja'],
                     stdout=subprocess.DEVNULL)
try:
    until = time.monotonic() + 180
    while time.monotonic() < until:
        if p.poll() is not None:
            raise RuntimeError('server exited before ready')
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(1)
                s.connect('/workspace/pi.sock')
                s.sendall(b'GET /health HTTP/1.0\r\n\r\n')
                # b12069, server-http.cpp:308-320 refuses while loading;
                # server-context.cpp:5728-5739 calls ok() (5290-5293: 200).
                # Parse HTTP status; TCP/Unix stream reads can split a line.
                with http.client.HTTPResponse(s) as response:
                    response.begin()
                    healthy = response.status == 200
                if healthy:
                    st = os.lstat('/workspace/pi.sock')
                    print(json.dumps({'ready': [st.st_dev, st.st_ino],
                                      'net': os.readlink('/proc/self/ns/net')}), flush=True)
                    break
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(.2)
    else:
        raise RuntimeError('server readiness deadline')
    p.wait()
finally:
    if p.poll() is None:
        p.terminate()
        p.wait(timeout=5)
"""

BOOT = r"""
import os, sys
from pathlib import Path
model, *command = sys.argv[1:]
config = Path.home() / '.pi' / 'agent'
config.mkdir(parents=True)
(config / 'models.json').write_text(model)
(config / 'settings.json').write_text(
    '{"compaction":{"enabled":false},"retry":{"enabled":false,"provider":{"maxRetries":0}},'
    '"cacheWarming":"off"}')
os.execv(command[0], command)
"""


def answer_matches(answer, value):
    """Accept only the exact value, optionally in a single Markdown fence."""
    answer = answer.strip()
    if answer == value:
        return True
    return re.fullmatch(r"```[A-Za-z0-9_-]*[ \t]*\r?\n" + re.escape(value)
                        + r"\r?\n```", answer) is not None


def tool_text_matches(content, value):
    return (isinstance(content, list) and len(content) == 1
            and isinstance(content[0], dict) and content[0].get("type") == "text"
            and content[0].get("text") == value)


async def test_one_local_model_read(pi_startup_launcher, tmp_path):
    if os.environ.get("M8_PI_LOCAL_REQUIRED") != "1":
        pytest.skip("manual local READ was not explicitly selected")
    location = os.environ.get("M8_PI_LOCAL_ROOT")
    if not location:
        pytest.fail("required local model runtime missing")
    root = Path(location)
    receipt = json.loads(root.with_suffix(".json").read_text())
    pi_launcher = pi_startup_launcher[0]
    server_launcher = replace(pi_launcher, runtime_root=root,
                              expected_runtime=Digest(receipt["runtime_digest"]))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    value = secrets.token_hex(12)
    fixture = workspace / "fixture.txt"
    fixture.write_text(value, encoding="utf-8")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    route = PiPeerRoute(private)
    ready = asyncio.get_running_loop().create_future()
    peer_net = None
    host_net = os.readlink("/proc/self/ns/net")
    paths = AcquisitionPaths(tmp_path / "guards", acquisition_id_for("pi-local-read", 1))
    model = json.dumps({"providers": {"fixture": {
        "baseUrl": f"http://127.0.0.1:{PI_PORT}/v1", "api": "openai-completions",
        "apiKey": "fixture-key", "models": [{"id": "pi-read", "maxTokens": 128}],
    }}})
    conversation = PiReadConversation(TaskSpec(instruction=(
        "Use the read tool once to read fixture.txt. Reply with its exact content only, "
        "either bare or in a single Markdown code fence."
    )), input_limit=65536)

    async def observe(io):
        nonlocal peer_net
        record = await StartupWire(io).record()
        peer_net = record["net"]
        assert peer_net != host_net
        route.ready(tuple(record["ready"]))
        ready.set_result(True)
        await asyncio.Future()

    checks = {"tool_result_matches": None, "answer_matches": None,
              "peer_live_through_exchange": None, "peer_joined": None,
              "workspace_unchanged": None}
    async with acquisition_guard(paths) as guard:
        peer = asyncio.create_task(server_launcher.exchange(
            ("/usr/bin/python3", "-I", "-c", SERVER), workspace=private,
            posture=Posture.WRITE, guard_fds=(guard,), conversation=observe, timeout_s=420,
        ))
        try:
            async with asyncio.timeout(200):
                done, _ = await asyncio.wait((peer, ready), return_when=asyncio.FIRST_COMPLETED)
                assert peer not in done, peer.result() if peer in done else None
            result = await pi_launcher.exchange(
                ("/usr/bin/python3", "-I", "-c", BOOT, model, PI, *FLAGS,
                 "--provider", "fixture", "--model", "pi-read", "--thinking", "off"),
                workspace=workspace, posture=Posture.READ, guard_fds=(guard,),
                conversation=conversation, timeout_s=200, pi_peer=route,
            )
            decoder = conversation.decoder
            # Never include raw stdout/stderr, prompts, replies, IDs, or the
            # decoder's excerpt in CI failure output.
            diagnostics = {
                "state_observed": decoder.state_observed, "prompt_accepted": decoder.accepted,
                "agent_started": decoder.started, "agent_ended": decoder.ended,
                "eof": decoder.eof, "settled": decoder.settled, "refused": decoder.refused,
                "damage_count": decoder.damage_count, "first_error": decoder.error,
                "records": decoder.count, "stdout_bytes": decoder.total,
                "stderr_bytes": len(result.stderr),
                "returncode": result.returncode, "payload_returncode": result.payload_returncode,
                "timed_out": result.timed_out, "limit_exceeded": result.bound_exceeded is not None,
                "read_calls": len(decoder.calls), "final_observed": decoder.final is not None,
            }
            # Pytest short tracebacks can elide dictionary entries. Keep the
            # complete bounded progress record even when acceptance fails.
            write_evidence("duplex-real-pi-local-progress.json", diagnostics)
            checks["peer_live_through_exchange"] = not peer.done()
            if len(decoder.calls) == 1:
                call = next(iter(decoder.calls.values()))
                checks["tool_result_matches"] = tool_text_matches(call.content, value)
            if decoder.final is not None:
                checks["answer_matches"] = answer_matches(decoder.final, value)
            assert result.returncode == result.payload_returncode == 0
            assert not result.timed_out and result.bound_exceeded is None
            assert decoder.eof and decoder.settled, json.dumps(diagnostics)
            assert not decoder.damage_count and not decoder.refused, json.dumps(diagnostics)
            assert len(decoder.calls) == 1
            call = next(iter(decoder.calls.values()))
            call_valid = call.arguments == {"path": "fixture.txt"} and call.started and call.ended
            assert call_valid
            assert call.result is not None and decoder.final is not None
            assert checks["tool_result_matches"] is True
            assert checks["answer_matches"] is True
            assert checks["peer_live_through_exchange"] is True
        finally:
            try:
                route.revoke()
            finally:
                peer.cancel()
                try:
                    await finish_owned(peer)
                except asyncio.CancelledError:
                    checks["peer_joined"] = peer.cancelled()
                    if not checks["peer_joined"]:
                        raise
                except BaseException:
                    checks["peer_joined"] = False
                    raise
                else:
                    checks["peer_joined"] = True
                finally:
                    try:
                        checks["workspace_unchanged"] = (
                            sorted(path.name for path in workspace.iterdir()) == ["fixture.txt"]
                            and fixture.read_text(encoding="utf-8") == value
                        )
                    finally:
                        write_evidence("duplex-real-pi-local-checks.json", checks)
    assert checks["peer_joined"] is True
    assert checks["workspace_unchanged"] is True
    write_evidence("duplex-real-pi-local-read.json", {
        "scope": "one bounded local Pi READ", "server_runtime": receipt,
        "server_archive_sha256": "70df3ef8becd405b9ebc13b925387715ae7dccb0f034fd5f46a4034b350130a1",
        "model_sha256": "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031",
        "peer_namespace": peer_net, "one_read": True, "peer_joined": True,
    })
