"""Opt-in physical placement proof. This is not native mediation qualification."""

import asyncio
import hashlib
import json
import os
import signal
import socket
import sys
import tempfile
from contextlib import asynccontextmanager
from dataclasses import asdict, fields, replace
from pathlib import Path

import pytest

from constructicon.core.identity import Digest
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors.linux import ProcessExchangeError
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests.native_provider import provider_peer
from tests.native_startup import MODELS, DuplexWire, configuration, initialize
from tests.provider_placement import BOOTSTRAP, PlacementLauncher
from tests.substrate._provider_transport import CASE_SECONDS
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_linux_duplex import exchange
from tests.substrate.test_native_codex_mediation import write_evidence
from tests.substrate.test_native_startup import assert_outcome


@pytest.fixture
def placement_image(launcher):
    root = os.environ.get("M8_PLACEMENT_ROOT")
    if not root:
        if os.environ.get("M8_PLACEMENT_REQUIRED"):
            pytest.fail("required immutable placement image missing")
        pytest.skip("placement image not provisioned")
    root = Path(root)
    identity = json.loads(root.with_suffix(".json").read_text())["runtime_digest"]
    return replace(launcher, runtime_root=root, expected_runtime=Digest(identity))


@asynccontextmanager
async def placement(image, *, timeout=CASE_SECONDS):
    deadline = asyncio.get_running_loop().time() + timeout  # Before peer setup.
    with tempfile.TemporaryDirectory(prefix="m8-placement-") as directory:
        endpoint = Path(directory) / "provider.sock"
        # These ordinary siblings must never appear in the contained namespace.
        (endpoint.parent / "journal.sqlite").write_text("inert host-only marker")
        async with provider_peer(path=endpoint, deadline=deadline, model=MODELS[0]) as peer:
            identity = endpoint.stat()
            composed = PlacementLauncher(
                **{field.name: getattr(image, field.name) for field in fields(image)},
                endpoint=endpoint, endpoint_identity=(identity.st_dev, identity.st_ino),
            )
            yield composed, peer


def birth(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return None


def descendants(pid):
    observed = {}
    pending = [pid]
    while pending:
        parent = pending.pop()
        try:
            children = Path(f"/proc/{parent}/task/{parent}/children").read_text().split()
        except FileNotFoundError:
            continue
        for child in children:
            started = birth(int(child))
            if started is not None:
                observed[int(child)] = started
                pending.append(int(child))
    return observed


async def observe(
    composed, peer, guard_root, *, probe=None, query=None, identity=None, fault="none",
):
    setup = {
        "files": {}, "config": configuration(MODELS[0]), "arguments": [],
        "placement": {
            "identity": list(composed.endpoint_identity) if identity is None else identity,
            "deadline": peer.deadline, "probe": probe, "fault": fault,
        },
    }
    raw = (json.dumps(setup) + "\n").encode()
    observations = {"setup": setup, "records": [], "resident": {}}

    async def conversation(io):
        await io.write(raw)
        wire = DuplexWire(io)
        if query is not None:
            await query(wire, observations)
        else:
            while chunk := await io.read():
                observations["records"].append(chunk.hex())

    result = None
    try:
        result = await exchange(
            composed, guard_root, conversation, command=("/usr/bin/python3", "-I", BOOTSTRAP),
            timeout=max(.001, peer.deadline - asyncio.get_running_loop().time()),
        )
    except ProcessExchangeError as exc:
        result = exc.result
        raise
    finally:
        if result is not None:
            observations["outcome"] = {
                **asdict(result), "stdout": result.stdout.hex(), "stderr": result.stderr.hex(),
            }
            observations["revision"] = str(composed.revision)
            observations["runtime"] = str(composed.expected_runtime)
    return observations, result


def evidence(composed, peer, observations):
    # Call only after the peer context has joined all handlers. Late failures count.
    assert not peer.active and all(task.done() for task in peer.handlers)
    value = {**observations, "peer": {
        "requests": peer.requests, "failures": peer.failures,
        "budget": asdict(peer.budget), "endpoint": str(composed.endpoint),
    }}
    name = hashlib.sha256(os.environ.get("PYTEST_CURRENT_TEST", "placement").encode()).hexdigest()
    write_evidence("codex-placement-" + name[:16] + ".json", value)


async def test_native_reaches_only_the_fixed_peer(placement_image, tmp_path):
    async def turn(wire, observed):
        observed["placement"] = (await wire.read())["placement"]
        observed["bootstrap"] = await wire.read()
        await initialize(wire)
        thread = await wire.rpc("thread/start", {
            "model": MODELS[0], "modelProvider": "probe", "cwd": "/tmp/native-startup",
            "approvalPolicy": "never", "sandbox": "danger-full-access", "ephemeral": True,
        })
        started = await wire.rpc("turn/start", {
            "threadId": thread["thread"]["id"],
            "input": [{"type": "text", "text": "Return the inert placement fixture response."}],
        })
        while True:
            message = await wire.read()
            observed["records"].append(message)
            assert "id" not in message, "placement authorizes no tool execution"
            if message.get("method") == "turn/completed":
                assert message["params"]["threadId"] == thread["thread"]["id"]
                assert message["params"]["turn"]["id"] == started["turn"]["id"]
                assert message["params"]["turn"]["status"] == "completed"
                observed["resident"] = descendants(os.getpid())
                await wire.io.close_stdin()
                return

    async with placement(placement_image) as (composed, peer):
        observations, result = await observe(composed, peer, tmp_path, query=turn)
    evidence(composed, peer, observations)
    assert_outcome(result)
    assert len(peer.requests) == peer.budget.connections == 1 and not peer.failures
    assert "fixture complete" in json.dumps(observations["records"])
    assert observations["placement"]["interfaces"] == ["lo"]
    assert observations["placement"]["routes"] == []
    assert observations["resident"]
    assert all(birth(pid) != started for pid, started in observations["resident"].items())


async def test_actual_mount_mismatch_refuses_before_native_exec(placement_image, tmp_path):
    async with placement(placement_image) as (composed, peer):
        observations, result = await observe(composed, peer, tmp_path, identity=[0, 0])
    evidence(composed, peer, observations)
    assert_outcome(result, status=1)
    assert b"mounted endpoint differs" in result.stderr
    assert not result.stdout and not peer.requests and peer.budget.connections == 0


async def test_private_loopback_does_not_expose_host_or_socket_siblings(placement_image, tmp_path):
    with socket.socket() as host, socket.socket(socket.AF_UNIX) as sibling:
        host.bind(("127.0.0.1", 0))
        host.listen(1)
        async with placement(placement_image) as (composed, peer):
            other = composed.endpoint.parent / "other.sock"
            sibling.bind(str(other))
            sibling.listen(1)
            probe = f'''
import json, pathlib, socket, sys
paths = {json.dumps([str(other), str(composed.endpoint.parent / "journal.sqlite"),
                    str(composed.endpoint), "/opt/native-startup/other.sock",
                    "/opt/native-startup/journal.sqlite"])}
assert all(not pathlib.Path(path).exists() for path in paths)
with socket.socket() as host:
    host.settimeout(1)
    assert host.connect_ex(("127.0.0.1", {host.getsockname()[1]})) != 0
print(json.dumps({{"unreachable": paths}}), flush=True)
'''
            observations, result = await observe(composed, peer, tmp_path, probe=probe)
    evidence(composed, peer, observations)
    assert_outcome(result)
    assert b"unreachable" in result.stdout
    assert not peer.requests
    # Ready retained its first connection; exiting without using it is incomplete.
    assert peer.budget.connections == 1 and peer.failures


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
async def test_existing_owner_reaps_bridge_and_session_changed_descendant(
    placement_image, tmp_path, mode,
):
    entered = asyncio.Event()
    observed = {}

    async def blocked(wire, observations):
        observations["placement"] = (await wire.read())["placement"]
        assert (await wire.read())["descendant_ready"]
        observed.update(descendants(os.getpid()))
        entered.set()
        await wire.read()

    probe = '''
import json, os, signal, time
read_fd, write_fd = os.pipe()
if os.fork() == 0:
    os.close(read_fd)
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.write(write_fd, b"R")
    time.sleep(100)
else:
    os.close(write_fd)
    assert os.read(read_fd, 1) == b"R"
    print(json.dumps({"descendant_ready": True}), flush=True)
    time.sleep(100)
'''
    async with placement(placement_image, timeout=5) as (composed, peer):
        task = asyncio.create_task(observe(composed, peer, tmp_path, probe=probe, query=blocked))
        await asyncio.wait_for(entered.wait(), 4)
        assert len(observed) >= 4
        if mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            observations, result = await task
            assert_outcome(result, status=143, timed_out=True)
    if mode == "timeout":
        evidence(composed, peer, observations)
    assert all(birth(pid) != started for pid, started in observed.items())
    assert not peer.active and all(task.done() for task in peer.handlers)


def http_probe(raw, *, complete):
    return f'''
import json, socket, sys
with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=2) as client:
    client.sendall({raw!r})
    client.shutdown(socket.SHUT_WR)
    response = bytearray()
    try:
        while chunk := client.recv(8192): response.extend(chunk)
    except ConnectionError:
        pass
    assert (b'response.completed' in response) is {complete!r}, bytes(response)
    print(json.dumps({{"received": bytes(response).hex()}}), flush=True)
'''


@pytest.mark.parametrize("fault", ["none", "before_ready", "request", "response", "response_eof"])
async def test_transport_loss_and_the_unobserved_final_exit(placement_image, tmp_path, fault):
    body = json.dumps({"model": MODELS[0]}).encode()
    raw = b"POST /v1/responses HTTP/1.1\r\n" + (
        f"Content-Length: {len(body)}\r\n\r\n".encode() + body
    )
    async with placement(placement_image) as (composed, peer):
        observations, result = await observe(
            composed, peer, tmp_path, fault=fault,
            probe=http_probe(raw, complete=fault in {"none", "response_eof"}),
        )
    evidence(composed, peer, observations)
    assert_outcome(result, status=1 if fault == "before_ready" else 0)
    if fault == "before_ready":
        assert b"bridge not ready" in result.stderr and not result.stdout
    else:
        assert b"received" in result.stdout
    if fault in {"none", "response", "response_eof"}:
        assert len(peer.requests) == 1 and not peer.failures
    else:
        assert not peer.requests and peer.failures
    if fault == "response_eof":
        # All bytes arrived, but exit 7 of the bridge is intentionally unobserved.
        assert "bridge_returncode" not in observations["outcome"]


@pytest.mark.parametrize("raw,reason", [
    (b"not HTTP\r\n\r\n", "request target"),
    (b"POST /v1/responses HTTP/1.1\r\nContent-Length: 1048577\r\n\r\n", "body bound"),
])
async def test_bad_bytes_through_bridge_fail_the_external_peer(
    placement_image, tmp_path, raw, reason,
):
    async with placement(placement_image) as (composed, peer):
        observations, result = await observe(composed, peer, tmp_path,
                                             probe=http_probe(raw, complete=False))
    evidence(composed, peer, observations)
    assert_outcome(result)
    assert not peer.requests and any(reason in item for item in peer.failures)


async def test_lost_endpoint_refuses_readiness(placement_image, tmp_path):
    async with placement(placement_image) as (composed, peer):
        peer.stop()  # Retain the leaf inode but remove the listening service.
        observations, result = await observe(composed, peer, tmp_path)
    evidence(composed, peer, observations)
    assert_outcome(result, status=1)
    assert not result.stdout and b"bridge not ready" in result.stderr
    assert not peer.requests and not peer.failures


async def test_owner_death_keeps_guard_until_every_placement_descendant_is_reaped(
    placement_image, tmp_path,
):
    async with placement(placement_image) as (composed, peer):
        owner = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "tests.substrate._placement_owner", str(composed.endpoint),
            str(tmp_path), str(peer.deadline), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        reaper, waiter = None, None
        acquired = []

        async def wait_guard():
            paths = AcquisitionPaths(tmp_path, acquisition_id_for("duplex-proof", 1))
            async with acquisition_guard(paths):
                acquired.append(True)

        try:
            assert await asyncio.wait_for(owner.stdout.readline(), 8) == b"ready\n"
            resident = descendants(owner.pid)
            children = Path(f"/proc/{owner.pid}/task/{owner.pid}/children").read_text().split()
            assert len(children) == 1 and len(resident) >= 4
            reaper = int(children[0])
            os.kill(reaper, signal.SIGSTOP)
            owner.kill()
            await owner.wait()
            waiter = asyncio.create_task(wait_guard())
            await asyncio.sleep(.05)
            assert not waiter.done() and not acquired, "live placement lost its acquisition guard"
            os.kill(reaper, signal.SIGCONT)
            reaper = None
            await asyncio.wait_for(waiter, 8)
            assert acquired == [True]
            assert all(birth(pid) != started for pid, started in resident.items())
        finally:
            if reaper is not None:
                os.kill(reaper, signal.SIGCONT)
            if owner.returncode is None:
                owner.kill()
            await owner.wait()
            if waiter is not None:
                await waiter
    assert peer.failures and not peer.requests  # Readiness alone does not complete a request.
    assert not peer.active and all(task.done() for task in peer.handlers)
