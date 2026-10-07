"""Opt-in physical placement proof. This is not native mediation qualification."""

import asyncio
import hashlib
import json
import os
import signal
import socket
import sys
import tempfile
from contextlib import asynccontextmanager, nullcontext
from dataclasses import asdict, fields, replace
from pathlib import Path

import pytest

from constructicon.core.executor import Usage
from constructicon.core.identity import Digest
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors.codex import CLIENT_NAME, CLIENT_VERSION, NATIVE_CWD
from constructicon.substrate.executors.codex_lane import PREPARE_MODEL
from constructicon.substrate.executors.codex_protocol import (
    CONTAINED_PYTHON_TOOL,
    encode_record,
    initialize_request,
    initialized_notification,
    observe_turn,
    parse_tool_call,
    thread_start_request,
    tool_call_response,
)
from constructicon.substrate.executors.linux import ProcessExchangeError
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests.native_codex_probe import ProbeRefused
from tests.native_inventory import offered_tools, probe_setup, tool_inventory
from tests.native_provider import provider_peer
from tests.native_startup import MODELS, DuplexWire, configuration, initialize
from tests.provider_placement import BOOTSTRAP, PLACEMENT_PROMPT, PlacementLauncher
from tests.substrate._provider_transport import CASE_SECONDS
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_linux_duplex import exchange
from tests.substrate.test_native_codex_mediation import write_evidence
from tests.substrate.test_native_startup import assert_outcome


def logged_turn(wire_log, *, answer_required=False):
    """The real binary's one turn, folded as the adapter's fold does.

    Every notification the wire logged after ``turn/start`` was sent, through the
    drain to EOF, in arrival order: evidence before the reply is included as the
    adapter holds it, and evidence after completion as the adapter's drain folds
    it. The probe still consumes notifications while it awaits the reply, so a
    completion arriving before the reply would stall the lane, never pass it.
    """
    start = next(index for index, entry in enumerate(wire_log)
                 if entry.get("sent", {}).get("method") == "turn/start")
    request = wire_log[start]["sent"]
    later = [entry["received"] for entry in wire_log[start + 1:] if "received" in entry]
    reply = next(value for value in later if value.get("id") == request["id"])
    return observe_turn(
        [encode_record(value) for value in later if "id" not in value],
        thread_id=request["params"]["threadId"], turn_id=reply["result"]["turn"]["id"],
        answer_required=answer_required,
    )


def assert_decoded_turn(observations, peer, *, answer=None):
    """The decoder against the real binary: the answer, and usage from zero.

    Each fake response reports one input and one output token
    (``tests/native_provider.py``), so the thread's total must be exactly the
    number of responses served: no baseline, and accumulation across a tool
    continuation (M8-N5-state-review.md, fact 4).
    """
    turn = logged_turn(observations["wire"], answer_required=answer is not None)
    assert turn.terminal and turn.first_error is None and turn.malformed_records == 0, turn
    served = len(peer.requests)
    assert turn.usage == Usage(input_tokens=served, output_tokens=served), turn.usage
    assert turn.served_model is None
    if answer is not None:
        assert turn.output == answer


def test_a_logged_turn_is_folded_from_the_turn_start_request_on():
    """Portable: early evidence before the reply counts, earlier records do not."""
    from tests.substrate.test_codex_protocol import completed, usage_update

    log = [
        {"received": usage_update(input_tokens=9, output_tokens=9, turn="turn-n2")},
        {"sent": {"id": 5, "method": "turn/start", "params": {"threadId": "thread-n2"}}},
        {"received": usage_update(input_tokens=1, output_tokens=1, turn="turn-n2")},
        {"received": {"id": 5, "result": {"turn": {"id": "turn-n2"}}}},
        {"received": {"id": 6, "method": "item/tool/call", "params": {}}},
        {"received": completed(answer="fixture complete", thread="thread-n2", turn="turn-n2")},
    ]
    turn = logged_turn(log, answer_required=True)
    assert turn.terminal and turn.first_error is None
    assert turn.output == "fixture complete"
    assert turn.usage == Usage(input_tokens=1, output_tokens=1)


@pytest.mark.parametrize("damaged", [
    b'{"method": "a"}',  # truncated at EOF
    b'{"method": "a", "method": "b"}\n',  # a duplicate key the adapter refuses
    b"{not json\n",
])
async def test_the_wire_drain_reads_as_strictly_as_before_the_terminal(damaged):
    class Chunks:
        def __init__(self, *chunks):
            self.chunks = list(chunks)

        async def read(self, maximum):
            return self.chunks.pop(0) if self.chunks else b""

    with pytest.raises(ProbeRefused):
        await DuplexWire(Chunks(damaged), []).drain()


async def test_the_wire_drain_logs_every_record_to_eof():
    class Chunks:
        def __init__(self, *chunks):
            self.chunks = list(chunks)

        async def read(self, maximum):
            return self.chunks.pop(0) if self.chunks else b""

    log = []
    await DuplexWire(Chunks(b'{"method": "a"}\n{"meth', b'od": "b"}\n'), log).drain()
    assert log == [{"received": {"method": "a"}}, {"received": {"method": "b"}}]


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
async def placement(image, *, timeout=CASE_SECONDS, model=MODELS[0],
                    scenario=PLACEMENT_PROMPT, tool=None, arguments=None, request_check=None,
                    namespace=None, directory=None):
    deadline = asyncio.get_running_loop().time() + timeout  # Before peer setup.
    storage = (tempfile.TemporaryDirectory(prefix="m8-placement-") if directory is None
               else nullcontext(directory))
    with storage as directory:
        endpoint = Path(directory) / "provider.sock"
        # These ordinary siblings must never appear in the contained namespace.
        (endpoint.parent / "journal.sqlite").write_text("inert host-only marker")
        record = {}
        composed = peer = None
        try:
            async with provider_peer(tool=tool, arguments=arguments, path=endpoint,
                                     deadline=deadline, model=model,
                                     scenario=scenario, request_check=request_check,
                                     namespace=namespace) as peer:
                identity = endpoint.stat()
                composed = PlacementLauncher(
                    **{field.name: getattr(image, field.name) for field in fields(image)},
                    endpoint=endpoint, endpoint_identity=(identity.st_dev, identity.st_ino),
                )
                yield composed, peer, record
        finally:
            if composed is not None:
                evidence(composed, peer, record)


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
    composed, peer, guard_root, *, probe=None, query=None, identity=None, fault="none", record=None,
    config=None, files=None, arguments=(), guard_fd=None,
):
    setup = {
        "files": {} if files is None else files,
        "config": configuration(peer.model) if config is None else config,
        "arguments": list(arguments),
        "placement": {
            "identity": list(composed.endpoint_identity) if identity is None else identity,
            "deadline": peer.deadline, "probe": probe, "fault": fault,
        },
    }
    raw = (json.dumps(setup) + "\n").encode()
    observations = {} if record is None else record
    observations.update({"setup": setup, "records": [], "resident": {}})

    async def conversation(io):
        await io.write(raw)
        wire = DuplexWire(io, observations.setdefault("wire", []))
        if query is not None:
            await query(wire, observations)
        else:
            while chunk := await io.read():
                observations["records"].append(chunk.hex())

    result = None
    try:
        remaining = peer.deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("placement case expired before launch")
        result = await exchange(
            composed, guard_root, conversation, command=("/usr/bin/python3", "-I", BOOTSTRAP),
            timeout=remaining, guard_fd=guard_fd,
        )
    except ProcessExchangeError as exc:
        result = exc.result
        observations["failure"] = repr(exc.__cause__)
        raise
    except BaseException as exc:
        observations["failure"] = type(exc).__name__
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
    key = [os.environ.get("PYTEST_CURRENT_TEST", "placement"), str(composed.endpoint)]
    name = hashlib.sha256(json.dumps(key).encode()).hexdigest()
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
            "input": [{"type": "text", "text": PLACEMENT_PROMPT}],
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
                await wire.drain()
                return

    async with placement(placement_image) as (composed, peer, record):
        observations, result = await observe(composed, peer, tmp_path, record=record, query=turn)
    assert_outcome(result)
    assert len(peer.requests) == peer.budget.connections == 1 and not peer.failures
    assert "fixture complete" in json.dumps(observations["records"])
    assert_decoded_turn(observations, peer, answer="fixture complete")
    assert observations["placement"]["interfaces"] == ["lo"]
    assert observations["placement"]["routes"] == []
    assert observations["placement"]["identity"] == list(composed.endpoint_identity)
    assert set(observations["placement"]["fds_after_setup"]) == {"0", "1", "2"}
    bridge_fds = observations["placement"]["bridge_fds_at_entry"]
    assert len(bridge_fds) == 5 and bridge_fds["0"] == bridge_fds["1"] == "/dev/null"
    assert observations["resident"]
    assert all(birth(pid) != started for pid, started in observations["resident"].items())


INVENTORY = json.loads(Path(__file__).parents[1].joinpath(
    "fixtures", "native_production_inventory.json").read_text())
"""Measured on the real binary (M8-N5-native-tool-inventory.md): the sealed offer
as sent, and the names each removed layer lets back in."""

CALLBACK_OUTPUT = "contained fixture output"


async def inventory_turn(image, tmp_path, *, without=(), write=False, tool=None, arguments=None,
                         namespace=None):
    """One production turn of the mode at ``gpt-6.1-sol``, its layers less ``without``.

    Initialize, the thread and the turn are the adapter's own requests. A
    callback is answered as the adapter answers it; any other server request
    fails the lane, since nothing else may reach the client.
    """

    config, files = probe_setup(*without)
    callbacks = []

    async def turn(wire, observed):
        observed["placement"] = (await wire.read())["placement"]
        observed["bootstrap"] = await wire.read()
        opened = initialize_request(0, client=CLIENT_NAME, version=CLIENT_VERSION,
                                    experimental_api=write)
        await wire.rpc("initialize", opened["params"])
        await wire.send(initialized_notification())
        thread = await wire.rpc("thread/start", thread_start_request(
            0, cwd=NATIVE_CWD, dynamic_tools=(CONTAINED_PYTHON_TOOL,) if write else (),
        )["params"])
        started = await wire.rpc("turn/start", {
            "threadId": thread["thread"]["id"],
            "input": [{"type": "text", "text": PLACEMENT_PROMPT}],
        })
        while (message := await wire.read()).get("method") != "turn/completed":
            if "id" in message:
                call = parse_tool_call(message, thread_id=thread["thread"]["id"],
                                       turn_id=started["turn"]["id"])
                callbacks.append(call.program)
                await wire.send(tool_call_response(call, CALLBACK_OUTPUT))
        assert message["params"]["turn"]["status"] == "completed", message
        await wire.io.close_stdin()
        await wire.drain()

    async with placement(image, model=PREPARE_MODEL, tool=tool, arguments=arguments,
                         namespace=namespace) as (composed, peer, record):
        _observations, result = await observe(
            composed, peer, tmp_path, record=record, query=turn, config=config, files=files,
        )
    assert_outcome(result)
    assert not peer.failures
    return peer.requests, callbacks


def call_outputs(request):
    return [item for item in request["input"]
            if item.get("type") in {"function_call_output", "custom_tool_call_output"}]


async def test_a_sealed_read_turn_offers_the_model_nothing(placement_image, tmp_path):
    requests, callbacks = await inventory_turn(placement_image, tmp_path)
    assert len(requests) == 1 and not callbacks
    assert offered_tools(requests[0]) == INVENTORY["sealed"]["read"] == []


async def test_a_sealed_write_turn_offers_only_the_callback_and_it_answers(
    placement_image, tmp_path,
):
    """The offer as sent, then the callback round trip without an environment."""

    requests, callbacks = await inventory_turn(
        placement_image, tmp_path, write=True, tool="contained_python",
        arguments={"program": "print('fixture')"},
    )
    assert offered_tools(requests[0]) == INVENTORY["sealed"]["write"]
    assert tool_inventory(requests[0]) == ["functions.contained_python"]
    assert callbacks == ["print('fixture')"] and len(requests) == 2
    (output,) = call_outputs(requests[1])
    # One text item is sent as a plain string (``core/src/tools/context.rs:584-588``).
    assert output == {"type": "function_call_output", "call_id": "call_probe",
                      "output": CALLBACK_OUTPUT}


@pytest.mark.parametrize("without", [
    ("catalog",), ("catalog", "environment"), ("controls",),
], ids="+".join)
async def test_each_layer_holds_its_own_native_tools(placement_image, tmp_path, without):
    """Each layer removed alone lets back exactly what it held: a positive control
    for every layer, so the sealed offer cannot pass vacuously."""

    requests, _ = await inventory_turn(placement_image, tmp_path, without=without)
    assert tool_inventory(requests[0]) == INVENTORY["+".join(without)]


REFUSED = [
    # (tool, namespace, arguments, refusal): every name the unsealed recipe
    # offered, and every environment-backed tool.
    ("exec", None, {"code": "text('inert fixture')"}, "unsupported custom tool call: exec"),
    ("apply_patch", None, {"patch": "*** Begin Patch\n*** End Patch\n"},
     "unsupported custom tool call: apply_patch"),
    *((name, None, {}, f"unsupported call: {name}") for name in (
        "wait", "request_user_input", "request_user_input_async", "exec_command",
        "write_stdin", "view_image", "request_permissions",
    )),
    *((name, namespace, {}, f"unsupported call: {namespace}{name}") for namespace, name in (
        ("clock", "curr_time"), ("clock", "sleep"), ("image_gen", "imagegen"),
        ("collaboration", "spawn_agent"), ("collaboration", "send_message"),
        ("collaboration", "followup_task"), ("collaboration", "wait_agent"),
        ("collaboration", "interrupt_agent"), ("collaboration", "list_agents"),
    )),
]


@pytest.mark.parametrize("tool,namespace,arguments,refusal", REFUSED,
                         ids=[f"{namespace or 'functions'}.{tool}"
                              for tool, namespace, _, _ in REFUSED])
async def test_a_sealed_turn_refuses_every_known_native_name(
    placement_image, tmp_path, tool, namespace, arguments, refusal,
):
    """Dispatch is by name and never checks the offer (``registry.rs:551-573``),
    so an unoffered name must also be unregistered: the model's call comes back
    refused, and nothing reaches the client."""

    requests, callbacks = await inventory_turn(
        placement_image, tmp_path, tool=tool, namespace=namespace, arguments=arguments,
    )
    assert not callbacks and len(requests) == 2
    (output,) = call_outputs(requests[1])
    assert output["output"] == refusal


async def test_actual_mount_mismatch_refuses_before_native_exec(placement_image, tmp_path):
    async with placement(placement_image) as (composed, peer, record):
        _observations, result = await observe(
            composed, peer, tmp_path, record=record, identity=[0, 0],
        )
    assert_outcome(result, status=1)
    assert b"mounted endpoint differs" in result.stderr
    assert not result.stdout and not peer.requests and peer.budget.connections == 0


async def test_private_loopback_does_not_expose_host_or_socket_siblings(placement_image, tmp_path):
    with socket.socket() as host, socket.socket(socket.AF_UNIX) as sibling:
        host.bind(("127.0.0.2", 0))
        host.listen(1)
        async with placement(placement_image) as (composed, peer, record):
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
    assert host.connect_ex(("127.0.0.2", {host.getsockname()[1]})) != 0
print(json.dumps({{"unreachable": paths}}), flush=True)
'''
            _observations, result = await observe(
                composed, peer, tmp_path, record=record, probe=probe,
            )
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
        observations["resident"] = dict(observed)
        entered.set()
        await wire.read()

    probe = f'''
import json, os, signal, time
read_fd, write_fd = os.pipe()
if os.fork() == 0:
    os.close(read_fd)
    os.setsid()
    if {mode == "cancel"!r}:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.write(write_fd, b"R")
    time.sleep(100)
else:
    os.close(write_fd)
    assert os.read(read_fd, 1) == b"R"
    print(json.dumps({{"descendant_ready": True}}), flush=True)
    time.sleep(100)
'''
    async with placement(placement_image, timeout=5) as (composed, peer, record):
        task = asyncio.create_task(observe(
            composed, peer, tmp_path, record=record, probe=probe, query=blocked,
        ))
        await asyncio.wait_for(entered.wait(), 4)
        assert len(observed) >= 4
        if mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            _observations, result = await task
            # This TERM-cooperative case requires an observed native exit.
            # Forced teardown is proved separately through cancellation and
            # controller death: outer KILL can preempt the optional exit report.
            assert_outcome(result, status=143, timed_out=True)
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
    body = json.dumps({"model": MODELS[0], "inert_padding": "x" * 16000,
                       "input": [{"role": "user", "content": [
                           {"type": "input_text", "text": PLACEMENT_PROMPT}]}]}).encode()
    raw = b"POST /v1/responses HTTP/1.1\r\n" + (
        f"Content-Length: {len(body)}\r\n\r\n".encode() + body
    )
    async with placement(placement_image) as (composed, peer, record):
        observations, result = await observe(
            composed, peer, tmp_path, record=record, fault=fault,
            probe=http_probe(raw, complete=fault in {"none", "response_eof"}),
        )
    assert_outcome(result, status=1 if fault == "before_ready" else 0)
    if fault == "before_ready":
        assert b"bridge not ready" in result.stderr and not result.stdout
    else:
        assert b"received" in result.stdout
    if fault in {"none", "response", "response_eof"}:
        assert len(peer.requests) == 1 and not peer.failures
    else:
        assert not peer.requests and peer.failures
        if fault == "request":
            assert 0 < peer.budget.total < len(raw)
            assert any("incomplete" in failure for failure in peer.failures)
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
    async with placement(placement_image) as (composed, peer, record):
        _observations, result = await observe(composed, peer, tmp_path, record=record,
                                             probe=http_probe(raw, complete=False))
    assert_outcome(result)
    assert not peer.requests and any(reason in item for item in peer.failures)


async def test_lost_endpoint_refuses_readiness(placement_image, tmp_path):
    async with placement(placement_image) as (composed, peer, record):
        peer.stop()  # Retain the leaf inode but remove the listening service.
        _observations, result = await observe(composed, peer, tmp_path, record=record)
    assert_outcome(result, status=1)
    assert not result.stdout and b"bridge not ready" in result.stderr
    assert not peer.requests and not peer.failures


async def test_owner_death_keeps_guard_until_every_placement_descendant_is_reaped(
    placement_image, tmp_path,
):
    async with placement(placement_image) as (composed, peer, record):
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
            resident.pop(reaper)  # Its adopting host parent, not our namespace, reaps this owner.
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
            record.update({"termination": "controller killed", "resident": resident,
                           "guard_acquired_after_reaping": acquired})
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


async def test_two_invocations_cannot_select_each_others_endpoint(placement_image, tmp_path):
    body = json.dumps({"model": MODELS[0], "input": [{"role": "user", "content": [
        {"type": "input_text", "text": PLACEMENT_PROMPT}]}]}).encode()
    raw = (b"POST /v1/responses HTTP/1.1\r\n"
           + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    async with (
        placement(placement_image) as (first, first_peer, first_record),
        placement(placement_image) as (second, second_peer, second_record),
    ):
        assert first.endpoint_identity != second.endpoint_identity
        assert first.revision == second.revision
        for index, (own, peer, record, other) in enumerate((
            (first, first_peer, first_record, second),
            (second, second_peer, second_record, first),
        )):
            probe = (f"import pathlib\nassert not pathlib.Path({str(other.endpoint)!r}).exists()\n"
                     + http_probe(raw, complete=True))
            _, result = await observe(own, peer, tmp_path / str(index), record=record, probe=probe)
            assert_outcome(result)
            assert len(first_peer.requests) == 1
            assert len(second_peer.requests) == index
    assert not first_peer.failures and not second_peer.failures
