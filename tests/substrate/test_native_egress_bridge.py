"""N4-preparation proofs of the proxy bridge inside the real native zone.

Foundation lane, as ``m8-service``, with the production runtime, the N3a store
fixture and the N3b throwaway-CA peers. No credentials, login or model request.
The first case is a harmless in-zone client that takes its proxy from the
environment the bridge gives it. The second is the pinned Codex binary, which
exports its process-start metric to a controlled peer when it shuts down
(design: ``M8-N4-proxy-bridge.md``). The relay's parser is wrapped to record
every CONNECT head it judged, so the preface is observed, not inferred.
"""

from __future__ import annotations

import errno
import gzip
import hashlib
import io
import json
import os
import socket
import ssl
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.grants import Posture
from constructicon.core.identity import Digest
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors import codex, codex_lane, egress, operator_store
from constructicon.substrate.executors._egress_bridge import PROXY_PORT
from constructicon.substrate.executors.codex_lane import (
    DENIAL_FAULT,
    LOGIN_ARGUMENTS,
    RUNTIME_CATALOG,
    STARTUP_METHODS,
    active_custody,
    launch,
    production_configuration,
    run_login,
    run_startup,
    vendor_executable,
)
from constructicon.substrate.executors.codex_protocol import (
    IDENTITY_FAULT,
    NO_ACCOUNT_FAULT,
    NO_RESULT_FAULT,
    UNSEALED_BACKEND_FAULT,
    ExpectedAccount,
    named_method,
)
from constructicon.substrate.executors.egress import identity_digests
from constructicon.substrate.executors.linux import (
    CATALOG_MOUNT,
    ENVIRONMENTS_MOUNT,
    NATIVE_ENVIRONMENTS,
    NativeVendor,
    sealed_catalog,
)
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests import native_account
from tests.native_startup import (
    BOOTSTRAP,
    MODELS,
    DuplexWire,
    configuration,
    initialize,
)
from tests.substrate.test_egress import CONTROLLED, until
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence
from tests.substrate.test_native_egress_containment import (
    ALLOWED,
    DECOY,
    PeerConnection,
    TlsPeer,
    facts_of,
    plan_for,
    policy_for,
    run_native,
)
from tests.substrate.test_native_egress_containment import controlled_peers as controlled_peers
from tests.substrate.test_native_egress_containment import pki as pki
from tests.substrate.test_native_egress_containment import short_root as short_root
from tests.substrate.test_operator_store_containment import binding as binding
from tests.substrate.test_operator_store_containment import collect, hold, native_mount

PROXY = f"http://127.0.0.1:{PROXY_PORT}"
ZONE_ENVIRONMENT = {
    "HOME": "/tmp/home", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PWD": "/tmp",
    # The N4 layout names the vendor home explicitly on every native launch.
    "CODEX_HOME": "/tmp/home/.codex",
    "CODEX_CA_CERTIFICATE": "/etc/ssl/certs/ca-certificates.crt",
}

CLIENT = r"""
import errno, json, os, socket, sys
plan = json.loads(sys.stdin.readline())
try:
    import ssl
except ImportError:
    print(json.dumps({'ssl': False}), flush=True)
    raise SystemExit(0)
context = ssl.create_default_context(cadata=plan['ca'])
proxy_host, _, proxy_port = os.environ['HTTPS_PROXY'].removeprefix('http://').rpartition(':')

def listening():
    found = []
    for kind in ('tcp', 'tcp6', 'udp', 'udp6'):
        for line in open('/proc/net/' + kind).read().splitlines()[1:]:
            fields = line.split()
            if kind.startswith('tcp') and fields[3] != '0A':
                continue
            address, port = fields[1].split(':')
            raw = bytes.fromhex(address)
            host = socket.inet_ntoa(raw[::-1]) if len(raw) == 4 else address
            found.append([kind, host, int(port, 16)])
    return sorted(found)

def tunnel(host, port):
    sock = socket.create_connection((proxy_host, int(proxy_port)), timeout=10)
    sock.sendall(f'CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n'.encode())
    reply = b''
    try:
        while b'\r\n\r\n' not in reply:
            chunk = sock.recv(4096)
            if not chunk:
                break
            reply += chunk
    except OSError:
        pass
    if not reply.startswith(b'HTTP/1.1 200 '):
        sock.close()
        return None
    return sock

def https(host, port):
    sock = tunnel(host, port)
    if sock is None:
        return {'connect': 'refused'}
    try:
        tls = context.wrap_socket(sock, server_hostname=host)
    except OSError:
        sock.close()
        return {'connect': 'ok', 'tls': 'refused'}
    tls.sendall(f'GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'.encode())
    data = b''
    try:
        while chunk := tls.recv(8192):
            data += chunk
    except OSError:
        pass
    tls.close()
    head, _, body = data.partition(b'\r\n\r\n')
    return {'connect': 'ok', 'tls': 'ok',
            'status': head.split(b' ')[1].decode() if head else None,
            'body': body.decode('latin-1')}

def errno_of(action):
    try:
        action()
    except OSError as exc:
        return exc.errno
    return 0

def forwarders():
    # The forwarder is a child of this process: the bridge forked it, then
    # exec'd this client in its own place.
    me = os.getpid()
    children = open(f'/proc/{me}/task/{me}/children').read().split()
    return [{name: os.readlink(f'/proc/{child}/fd/{name}')
             for name in os.listdir(f'/proc/{child}/fd')} for child in children]

results = {
    'ssl': True,
    'environment': dict(os.environ),
    'listening': listening(),
    'forwarders': forwarders(),
    'accepted': https(plan['allowed'], plan['allowed_port']),
    'decoy': https(plan['decoy'], plan['decoy_port']),
    'direct': errno_of(lambda: socket.create_connection(('192.0.2.1', 443), timeout=5)),
}
print(json.dumps(results), flush=True)
"""


@pytest.fixture
def heads(monkeypatch):
    """Every CONNECT head the relay's parser judged, in order."""
    judged: list[bytes] = []
    parse = egress.parse_connect

    def recording(head: bytes):
        judged.append(head)
        return parse(head)

    monkeypatch.setattr(egress, "parse_connect", recording)
    return judged


def preface(host: str, port: int) -> bytes:
    return f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n".encode()


async def test_an_environment_proxy_client_reaches_only_the_pinned_peer(
    binding, launcher, pki, short_root, heads,
):
    allowed, decoy = TlsPeer(pki.server("allowed")), TlsPeer(pki.server("decoy"))
    try:
        # Positive control: the decoy is live and verifies against the same CA.
        control = ssl.create_default_context(cadata=pki.ca)
        with socket.create_connection(("127.0.0.1", decoy.port), timeout=5) as raw, \
                control.wrap_socket(raw, server_hostname=DECOY) as tls:
            tls.sendall(b"GET / HTTP/1.1\r\nHost: decoy.invalid\r\n\r\n")
            tls.recv(64)
        assert await until(lambda: len(decoy.connections) == 1 and decoy.connections[0].eof)
        policy = policy_for(allowed.port)
        result, relay, output = await run_native(
            launcher, binding, short_root, "n4-bridge-proof",
            plan_for(pki, allowed, decoy_port=decoy.port), policy=policy,
            command=("/usr/bin/python3", "-I", "-c", CLIENT),
        )
        facts = facts_of(result, output)
    finally:
        for item in (allowed, decoy):
            item.close()

    assert facts["environment"] == {**ZONE_ENVIRONMENT, "HTTPS_PROXY": PROXY}
    assert facts["listening"] == [["tcp", "127.0.0.1", PROXY_PORT]]
    assert facts["accepted"] == {"connect": "ok", "tls": "ok", "status": "200",
                                 "body": "harmless-peer"}
    assert facts["decoy"] == {"connect": "refused"}
    assert facts["direct"] == errno.ENETUNREACH
    assert len(facts["forwarders"]) == 1, facts["forwarders"]
    descriptors = facts["forwarders"][0]
    assert {descriptors[name] for name in ("0", "1", "2")} == {"/dev/null"}, descriptors
    rest = [target for name, target in descriptors.items() if name not in {"0", "1", "2"}]
    assert rest and all(target.startswith("socket:") for target in rest), descriptors
    assert [head.startswith(preface(host, port)) for head, (host, port) in zip(
        heads, [(ALLOWED, allowed.port), (DECOY, decoy.port)], strict=True,
    )] == [True, True], heads
    observed = {key: value for key, value in relay.observed.items() if key != "reset"}
    assert observed == {"accepted": 1, "denied:destination": 1}
    assert relay.closed
    assert len(allowed.connections) == 1 and allowed.connections[0].handshake
    assert len(decoy.connections) == 1, "the decoy saw a connection besides the host control"
    write_evidence("n4-bridge.json", {
        "schema_version": 1, "credential_free_fixture": True,
        "vendor_conformance_qualified": False,
        "launch_revision": str(launcher.revision),
        "egress_identity": {key: str(value) for key, value in identity_digests(policy).items()},
        "observed": dict(relay.observed),
        "connect_heads": [head.decode("ascii") for head in heads],
        "zone": {key: facts[key] for key in ("environment", "listening", "direct")},
        "forwarder_fds": descriptors,
    })


class MetricsPeer(TlsPeer):
    """The N3b TLS peer, keeping each request's head and Content-Length body."""

    def __init__(self, context: ssl.SSLContext) -> None:
        self.requests: list[tuple[bytes, bytes]] = []
        super().__init__(context)

    def _session(self, raw: socket.socket, record: PeerConnection) -> None:
        try:
            with self.context.wrap_socket(raw, server_side=True) as tls:
                record.handshake = True
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = tls.recv(65536)
                    if not chunk:
                        return
                    data += chunk
                head, _, body = data.partition(b"\r\n\r\n")
                fields = {}
                for line in head.split(b"\r\n")[1:]:
                    name, _, value = line.partition(b":")
                    fields[name.strip().lower()] = value.strip()
                length = int(fields.get(b"content-length", b"0"))
                while len(body) < length and (chunk := tls.recv(65536)):
                    body += chunk
                if fields.get(b"content-encoding") == b"gzip":
                    body = gzip.decompress(body)
                record.bytes += len(head) + len(body)
                self.requests.append((head, body))
                tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                            b"Content-Length: 2\r\nConnection: close\r\n\r\n{}")
        except (OSError, ValueError):
            pass
        finally:
            record.eof = True


@pytest.fixture
def bridge_launcher(launcher):
    location = os.environ.get("M8_BRIDGE_ROOT")
    if not location:
        if os.environ.get("M8_BRIDGE_REQUIRED"):
            pytest.fail("the required pinned-binary bridge fixture is missing")
        pytest.skip("the pinned-binary bridge fixture is not provisioned")
    root = Path(location)
    pinned = json.loads(root.with_suffix(".json").read_text())["runtime_digest"]
    return replace(launcher, runtime_root=root, expected_runtime=Digest(pinned))


def telemetry_to(port: int) -> str:
    """Trusted test configuration: one metrics exporter, one controlled peer."""
    return (
        "[analytics]\nenabled = true\n[otel]\n"
        'metrics_exporter = { otlp-http = { endpoint = "https://'
        f'{ALLOWED}:{port}/v1/metrics", protocol = "json", '
        'tls = { ca-certificate = "/tmp/native-startup/ca.pem" } } }\n'
    )


async def test_the_pinned_client_reaches_a_controlled_peer_through_the_bridge(
    binding, bridge_launcher, pki, short_root, heads,
):
    """No login and no model request: at shutdown the app-server flushes its
    process-start metric with a bare reqwest client, which takes the proxy
    from the environment the bridge gave it."""
    peer = MetricsPeer(pki.server("allowed"))
    setup = {
        "config": configuration(MODELS[0]) + telemetry_to(peer.port),
        "files": {"/tmp/native-startup/ca.pem": pki.ca}, "arguments": [],
    }
    observations: dict = {}

    async def conversation(io):
        await io.write((json.dumps(setup) + "\n").encode())
        wire = DuplexWire(io)
        observations["bootstrap"] = await wire.read()
        observations["initialize"] = await initialize(wire)
        await io.close_stdin()
        while await io.read():
            pass

    try:
        result, relay, _ = await run_native(
            bridge_launcher, binding, short_root, "n4-pinned-client", {},
            policy=policy_for(peer.port), command=("/usr/bin/python3", "-I", BOOTSTRAP),
            conversation=conversation, configuration=setup["config"].encode(),
        )
    finally:
        peer.close()
    assert result.returncode == result.payload_returncode == 0, result
    assert observations["bootstrap"]["bootstrap_environment"] == {
        **ZONE_ENVIRONMENT, "HTTPS_PROXY": PROXY,
    }
    ours = [head for head in heads if head.startswith(preface(ALLOWED, peer.port))]
    assert ours, heads
    assert relay.observed["accepted"] >= 1, dict(relay.observed)
    metrics = [body for head, body in peer.requests
               if head.startswith(b"POST /v1/metrics HTTP/1.1\r\n")]
    assert any(b"codex.process.start" in body for body in metrics), peer.requests
    assert relay.closed
    write_evidence("n4-pinned-client.json", {
        "schema_version": 1, "credential_free_fixture": True, "model_requests": 0,
        "vendor_conformance_qualified": False,
        "launch_revision": str(bridge_launcher.revision),
        "observed": dict(relay.observed),
        "connect_heads": [head.decode("ascii", "replace") for head in heads],
        "peer_request_lines": [
            head.split(b"\r\n", 1)[0].decode("latin-1") for head, _ in peer.requests
        ],
        "process_start_exported": True,
    })


@pytest.mark.parametrize(("reported", "message"), [
    ({}, "absent"), ({"ssl": False}, "cannot import"),
])
def test_the_ssl_precondition_names_an_absent_fact_apart_from_a_failed_import(
    reported, message,
):
    """Portable: first Linux run of this file failed on a client that never
    reported the fact, under a message claiming the import had failed."""
    result = SimpleNamespace(returncode=0, payload_returncode=0)
    output = bytearray((json.dumps(reported) + "\n").encode())
    with pytest.raises(AssertionError, match=message):
        facts_of(result, output)
    assert facts_of(result, bytearray(b'{"ssl": true}\n')) == {"ssl": True}


def test_the_bridge_client_reports_the_ssl_fact():
    assert "'ssl': True" in CLIENT.split("results = {", 1)[1]


# --- N4 lanes with the pinned binary (M8-N4-state-review.md, L2 and L3) --------

EMPTY_AUTH = b"{}\n"
"""An ``AuthDotJson`` with every field absent: no login, parsed rather than
malformed, so the pinned client reports no account."""


@pytest.fixture
def vendor_launcher(bridge_launcher):
    """The launch set's own vendor tree and catalog, bound as production binds them."""
    launch = Path(os.environ.get("M8_LINUX_ROOT", "/var/lib/constructicon-m8-launch"))
    return replace(bridge_launcher, vendor=NativeVendor(
        launch / "native-codex", launch / "codex-models.json",
    ))


ZONE_FILES = r"""
import hashlib, json
print(json.dumps({path: hashlib.sha256(open(path, 'rb').read()).hexdigest()
                  for path in PATHS}), flush=True)
"""


async def test_a_vendored_native_zone_reads_the_seal_never_the_installed_catalog(
    binding, vendor_launcher, tmp_path,
):
    """Production's own launch path, not a fixture (M8-N5-native-tool-inventory.md):
    the zone's catalog is the launcher's seal of the launch set's catalog, the
    digest the lane evidence records, and its environment file is the launcher's.
    The placement lane proves what those bytes offer the model."""

    paths = (CATALOG_MOUNT, ENVIRONMENTS_MOUNT)
    source = ZONE_FILES.replace("PATHS", repr(paths))
    held = await hold(binding)
    try:
        async with acquisition_guard(AcquisitionPaths(
            tmp_path, acquisition_id_for("n5-seal-proof", 1),
        )) as guard:
            with native_mount(binding, held) as mount:
                result = await vendor_launcher.exchange(
                    ("/usr/bin/python3", "-I", "-c", source), workspace=None,
                    posture=Posture.READ, guard_fds=(guard, held.lock_fd), timeout_s=10,
                    conversation=collect, native_store=mount,
                )
    finally:
        binding.close_held(held)
    assert result.returncode == result.payload_returncode == 0, result
    seen = json.loads(result.stdout)
    installed = vendor_launcher.vendor.catalog.read_bytes()
    assert seen[CATALOG_MOUNT] == hashlib.sha256(sealed_catalog(installed)).hexdigest()
    assert seen[CATALOG_MOUNT] == vendor_executable(vendor_launcher).sealed_catalog_sha256
    assert seen[CATALOG_MOUNT] != hashlib.sha256(installed).hexdigest()
    assert seen[ENVIRONMENTS_MOUNT] == hashlib.sha256(NATIVE_ENVIRONMENTS).hexdigest()


def test_the_production_configuration_is_the_reviewed_literal():
    expected = (
        # Decision 3: the pinned catalog's newest ``sol`` at its lowest effort; CI
        # checks both against the catalog it installed.
        'model = "gpt-6.1-sol"\nmodel_reasoning_effort = "low"\n'
        f'model_catalog_json = "{RUNTIME_CATALOG}"\n'
        'cli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\n'
        'check_for_update_on_startup = false\nweb_search = "disabled"\n'
        "[analytics]\nenabled = false\n[features]\nplugins = false\n"
        "apps = false\nshell_tool = false\nunified_exec = false\nview_image = false\n"
        # ``goals`` is stable and on by default at both pins; from rust-v0.160
        # its three tools are visible on ephemeral threads too (``ext/goal``
        # ``tools_visible``), so every request carried a built-in tool surface.
        "multi_agent = false\ncode_mode = false\ngoals = false\n"
        # Default-on since rust-v0.160: it re-sends the account GETs through the
        # system proxy after a 5 s timeout, so their count and timing drift.
        "system_proxy_fallback = false\n"
        # The configuration's share of the tool inventory: the default-on gates
        # the sealed catalog and the absent environment leave, collisions fatal,
        # collaboration off over any catalog (M8-N5-native-tool-inventory.md).
        "image_generation = false\nsleep_tool = false\nmulti_agent_v2 = false\n"
        "[features.tool_registry]\nerror_on_tool_collisions = true\n"
        "[agents]\nenabled = false\n"
        "[tools.experimental_request_user_input]\nenabled = false\n"
    )
    assert production_configuration() == expected
    # The containment control differs in exactly one value.
    assert production_configuration(control=True) == expected.replace(
        "[analytics]\nenabled = false\n", "[analytics]\nenabled = true\n",
    )


ANALYTICS_EXPORTER = "ab.chatgpt.com:443"
"""The release build's default metrics endpoint (``core/src/otel_init.rs:68-77``)."""


def decoy_policy() -> egress.EgressPolicy:
    """A sealed policy naming only a decoy: every vendor CONNECT is a denial."""
    return egress.EgressPolicy((egress.EgressDestination(DECOY, 443, "8.8.8.8"),), 8)


NO_LOGIN = frozenset({
    # An empty ``auth.json`` makes ``account/read`` the pinned client's error
    # reply, so ``account_faults`` (codex_protocol.py) sees no result object
    # and returns only this one fault before any other check can run.
    NO_RESULT_FAULT,
    # No module constant names these three: they are the ``checks`` tuple
    # inline in ``codex_lane.run_startup`` (codex_lane.py lines 411-414),
    # copied verbatim from there rather than retyped from memory. With the
    # gate refused at ``account/read``, the gate never completes, the fourth
    # method (``rate_limits/read``) is never sent, and no readback is judged.
    "the startup gate did not complete",
    "the startup did not send exactly the four authorized methods",
    "no spend readback was judged",
})
"""The verdict's exact fault set with no login (state review, section 2)."""


@pytest.fixture
def empty_auth(binding):
    store = Path(binding.root) / operator_store._bundle_token("n3a-fixture") / "store"
    credential = store / "auth.json"
    original = credential.read_bytes()
    credential.write_bytes(EMPTY_AUTH)
    try:
        yield credential
    finally:
        credential.write_bytes(original)


async def test_the_production_configuration_makes_no_startup_connection_at_all(
    binding, vendor_launcher, short_root, heads, empty_auth, monkeypatch,
):
    """L2: zero denials, beside a same-step control that counts.

    The client runs from the launch set's bound vendor tree and reads the bound
    catalog, so this also proves the bind (host-runtime interface item 1).
    """
    runs = {}
    phase = ["startup"]
    events: list[dict[str, object]] = []
    omitted = [0]
    clients: dict[int, int] = {}

    def note(event: str, **detail: object) -> None:
        if len(events) < 64:
            events.append({"event": event, "phase": phase[0], **detail})
        else:
            omitted[0] += 1

    receive = egress._receive
    handle = egress.EgressRelay._handle
    finish = codex.CodexConversation._finish
    relay_exit = egress.EgressRelay.__aexit__

    async def observed_handle(self, client):
        clients[id(client)] = len(clients) + 1
        note("accepted-socket", client=clients[id(client)])
        try:
            await handle(self, client)
        finally:
            note("handler-ended", client=clients[id(client)])

    async def observed_receive(sock, count):
        try:
            data = await receive(sock, count)
        except OSError as exc:
            if sock.family == socket.AF_UNIX:
                note("client-read-error", client=clients.get(id(sock)), error=type(exc).__name__)
            raise
        if sock.family == socket.AF_UNIX:
            note("client-read", client=clients.get(id(sock)), bytes=len(data))
        return data

    async def observed_finish(self, io):
        phase[0] = "protocol-drain"
        note("protocol-drain-start")
        try:
            await finish(self, io)
        finally:
            phase[0] = "protocol-drain-complete"
            note("protocol-drain-complete")

    async def observed_relay_exit(self, kind, error, traceback):
        phase[0] = "relay-exit"
        note("relay-exit-start")
        return await relay_exit(self, kind, error, traceback)

    monkeypatch.setattr(egress, "_receive", observed_receive)
    monkeypatch.setattr(egress.EgressRelay, "_handle", observed_handle)
    monkeypatch.setattr(codex.CodexConversation, "_finish", observed_finish)
    monkeypatch.setattr(egress.EgressRelay, "__aexit__", observed_relay_exit)
    executable = vendor_executable(vendor_launcher)
    for control in (False, True):
        heads.clear()
        phase[0] = "startup"
        events.clear()
        omitted[0] = 0
        clients.clear()
        async with active_custody(binding) as custody:
            runs[control] = await run_startup(
                custody, vendor_launcher, decoy_policy(), executable=executable,
                configuration=production_configuration(control=control),
                expected=ExpectedAccount(plan_type="pro", alternatives=("prolite",)),
                lane_dir=short_root / f"lane-{int(control)}", deadline_s=30,
                expect_denial=control,
            )
        runs[control]["heads"] = [head.split(b"\r\n", 1)[0].decode() for head in heads]
        runs[control]["phases"] = list(events)
        runs[control]["phases_omitted"] = omitted[0]
    clean, control = runs[False], runs[True]
    # Preserve the phase trace on an assertion failure, without any socket or
    # credential bytes. The scheduled CI lane is the only place this pin runs.
    evidence = {
        "schema_version": 1, "credential_free_fixture": True, "model_requests": 0,
        "vendor_conformance_qualified": False, "vendor_bound": True,
        "assertions_passed": False,
        "executable": clean["executable"],
        "clean": {key: clean[key] for key in ("methods_sent", "relay", "heads", "faults",
                                               "phases", "phases_omitted")},
        "control": {key: control[key] for key in ("relay", "heads", "phases",
                                                   "phases_omitted")},
    }
    write_evidence("n4-lane-startup.json", evidence)
    # The fact this test exists for, independent of the verdict: the production
    # configuration made no connection at all. The bridge records every CONNECT
    # head and the relay every accepted or denied connection, whatever the
    # conversation concluded, so a refusal cannot hide one.
    assert clean["relay"] == {"destinations": {}, "denied": {}, "closed": True}, clean["relay"]
    assert clean["heads"] == [], clean["heads"]
    # With no login the verdict refuses, affirmatively and for exactly these
    # reasons: the account reading is the pinned client's error reply, so the
    # gate, the fourth method and the readback are each reported missing. No
    # launch fact failed (clean exit, closed relay, bound 0600 credential).
    assert set(clean["faults"]) == NO_LOGIN, clean["faults"]
    assert clean["methods_sent"] == ["'initialize'", "'initialized'", "'account/read'"]
    assert clean["readback"] is None and clean["gate"]["completed"] is False
    assert clean["executable"]["path"] == "/opt/codex/bin/codex"
    # The same-run positive control: the same refusal at the same point, and the
    # analytics exporter's CONNECT, whose flush the process awaits before
    # exiting, was seen and denied. Its own head is required, so another
    # background connection cannot stand in for it. Its denials are destination
    # denials only: an EOF before a complete head is a background request racing
    # shutdown, the plugins control's flake under #110, never the declaration.
    assert control["methods_sent"] == clean["methods_sent"]
    assert set(control["faults"]) == NO_LOGIN, control["faults"]
    assert set(control["relay"]["denied"]) == {"denied:destination"}, control["relay"]
    assert any(
        head.startswith(f"CONNECT {ANALYTICS_EXPORTER} ") for head in control["heads"]
    ), control["heads"]
    assert empty_auth.read_bytes() == EMPTY_AUTH
    evidence["assertions_passed"] = True
    write_evidence("n4-lane-startup.json", evidence)


async def test_the_pinned_device_login_reaches_only_the_relay_and_keeps_nothing(
    binding, vendor_launcher, short_root, heads, empty_auth,
):
    """L3: the login's CONNECT is denied, its output is never evidence.

    A login runs only in maintenance (CC-1). The service cannot enter one on
    this fixture, so the test relabels the fixture's held custody as a
    maintenance custody; nothing in production can build one this way.
    """
    out = io.BytesIO()
    async with active_custody(binding) as held:
        custody = replace(held, kind="maintenance", detail={"test_only": True})
        evidence = await run_login(
            custody, vendor_launcher, decoy_policy(),
            executable=vendor_executable(vendor_launcher),
            configuration=production_configuration(),
            lane_dir=short_root / "lane-login", deadline_s=60, out=out,
        )
    lines = [head.split(b"\r\n", 1)[0].decode() for head in heads]
    assert "CONNECT auth.openai.com:443 HTTP/1.1" in lines, lines
    assert evidence["relay"]["denied"].get("denied:destination", 0) >= 1
    assert evidence["process"]["returncode"] != 0
    printed = out.getvalue().decode(errors="replace").strip()
    assert not printed or printed not in json.dumps(evidence)
    # The pre-login logout's unlink met the bind (EBUSY) and was ignored.
    assert empty_auth.is_file() and empty_auth.stat().st_mode & 0o777 == 0o600
    write_evidence("n4-lane-login.json", {
        "schema_version": 1, "credential_free_fixture": True,
        "vendor_conformance_qualified": False, "connect_heads": lines,
        "relay": evidence["relay"], "process": evidence["process"],
        "credential_still_bound_file": True,
    })


# --- the zone's trust store (#77, S3) -------------------------------------------


@pytest.fixture
def trust_launcher(vendor_launcher):
    """The bridge image plus one throwaway CA in its trust store (build_m8_trust_fixture)."""
    location = os.environ.get("M8_TRUST_ROOT")
    if not location:
        if os.environ.get("M8_BRIDGE_REQUIRED"):
            pytest.fail("the required trust-store fixture is missing")
        pytest.skip("the trust-store fixture is not provisioned")
    root = Path(location)
    pinned = json.loads(root.with_suffix(".json").read_text())["runtime_digest"]
    return replace(vendor_launcher, runtime_root=root, expected_runtime=Digest(pinned))


class IssuerPeer:
    """A controlled issuer that records, per connection, one affirmative outcome.

    The outcome is the TLS alert the client sent (its certificate verdict) or
    the request line it sent after a completed handshake. A session that ends
    any other way records the error's name, and the test refuses it, so a
    reset, a deadline or a peer fault can never pass as a rejection.
    """

    def __init__(self, leaf: str) -> None:
        directory = Path(os.environ["M8_TRUST_PKI"])
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(directory / f"{leaf}.pem", directory / f"{leaf}.key")
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.sessions: list[dict] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                raw, _ = self.server.accept()
            except OSError:
                return
            session: dict = {"done": False, "alert": None, "error": None, "request": None}
            self.sessions.append(session)
            threading.Thread(target=self._session, args=(raw, session), daemon=True).start()

    def _session(self, raw: socket.socket, session: dict) -> None:
        try:
            with self.context.wrap_socket(raw, server_side=True) as tls:
                head = b""
                while b"\r\n\r\n" not in head and (chunk := tls.recv(8192)):
                    head += chunk
                session["request"] = head.split(b"\r\n", 1)[0].decode(errors="replace")
                tls.sendall(b"HTTP/1.1 503 Service Unavailable\r\n"
                            b"Content-Length: 0\r\nConnection: close\r\n\r\n")
        except ssl.SSLError as exc:
            session["alert"] = exc.reason
        except OSError as exc:
            session["error"] = type(exc).__name__
        finally:
            raw.close()
            session["done"] = True

    def close(self) -> None:
        self.server.close()


async def device_login_to(peer: IssuerPeer, launcher, binding, root: Path) -> dict:
    """The pinned client's own device login, its issuer moved to the peer's port.

    ``--experimental_issuer`` (cli/src/main.rs:522 at the pin) changes only the
    issuer URL, so the auth client, its TLS stack and the relay path are the
    production ones. The relay pins ``auth.openai.com`` at that port to the peer.
    """
    policy = egress.EgressPolicy(
        (egress.EgressDestination("auth.openai.com", peer.port, CONTROLLED),), 8,
    )
    command = (
        vendor_executable(launcher).path, *LOGIN_ARGUMENTS,
        "--experimental_issuer", f"https://auth.openai.com:{peer.port}",
    )

    async def drain(io) -> None:
        while await io.read(8192):
            pass
        await io.close_stdin()

    async with active_custody(binding) as held:
        custody = replace(held, kind="maintenance", detail={"test_only": True})
        launched = await launch(
            custody, launcher, policy, command, drain,
            configuration=production_configuration(), lane_dir=root, deadline_s=60,
        )
    assert await until(lambda: all(session["done"] for session in peer.sessions), 10)
    peer.close()
    return {
        "accepted": launched.destinations.get(f"accepted:auth.openai.com:{peer.port}", 0),
        "sessions": [{key: session[key] for key in ("alert", "error", "request")}
                     for session in peer.sessions],
        "returncode": launched.result.returncode,
        "stderr_bytes": len(launched.result.stderr),
        "stderr": launched.result.stderr.decode(errors="replace")[:600],
        "credential_changed": launched.credential["mtime_changed"],
    }


async def test_the_zone_trust_store_decides_what_the_device_login_trusts(
    binding, vendor_launcher, trust_launcher, short_root, empty_auth,
):
    """A CA in the zone's store, named by CODEX_CA_CERTIFICATE, is what the auth client needs.

    This proves the store necessary and sufficient for a CA the client does not
    otherwise trust. It does not prove the store exclusive: the pinned HTTP
    stack may also carry compiled-in roots (UNVERIFIED; implementation record).
    - Refused: the production image's store lacks the throwaway CA. The client
      sends an unknown-CA alert before any request. This is the host's S3
      failure mode: a relayed connection, then a refusal.
    - Accepted: with the CA in the store, the same client and relay complete TLS
      and send the device-code request (``POST .../deviceauth/usercode``,
      login/src/device_code_auth.rs:68 at the pin). The peer's reply is not the
      vendor's, so the login still fails, and no credential is written.
    - Wrong name: the CA is trusted but the leaf names another host. Refused by
      certificate alert.
    """
    refused = await device_login_to(IssuerPeer("issuer"), vendor_launcher, binding,
                                    short_root / "tr-r")
    accepted = await device_login_to(IssuerPeer("issuer"), trust_launcher, binding,
                                     short_root / "tr-a")
    stranger = await device_login_to(IssuerPeer("stranger"), trust_launcher, binding,
                                     short_root / "tr-s")
    for run in (refused, accepted, stranger):
        assert run["accepted"] >= 1 and run["sessions"], run
        assert run["returncode"] != 0 and run["credential_changed"] is False, run
        assert all(session["error"] is None for session in run["sessions"]), run
    assert {s["alert"] for s in refused["sessions"]} == {"TLSV1_ALERT_UNKNOWN_CA"}, refused
    assert all(s["request"] is None for s in refused["sessions"]), refused
    requests = [s["request"] for s in accepted["sessions"] if s["request"]]
    assert requests and requests[0].startswith("POST "), accepted
    assert "/deviceauth/usercode " in requests[0], accepted
    assert all(s["alert"] is None for s in accepted["sessions"]), accepted
    assert {s["alert"] for s in stranger["sessions"]} <= {
        "SSLV3_ALERT_BAD_CERTIFICATE", "SSLV3_ALERT_CERTIFICATE_UNKNOWN",
    }, stranger
    assert all(s["request"] is None for s in stranger["sessions"]), stranger
    assert empty_auth.read_bytes() == EMPTY_AUTH
    write_evidence("n4-lane-trust.json", {
        "schema_version": 1, "credential_free_fixture": True,
        "vendor_conformance_qualified": False,
        "trust_bundle": "/etc/ssl/certs/ca-certificates.crt",
        "refused": refused, "accepted": accepted, "stranger": stranger,
    })


# --- account/read recovery (M8-N5-account-read-recovery.md) ---------------------


def account_policy(connections: int, hosts=(native_account.BACKEND, native_account.ISSUER),
                   ) -> egress.EgressPolicy:
    """Production's shape, the hosts at 443 pinned to the fake, under a bound."""
    return egress.EgressPolicy(tuple(
        egress.EgressDestination(host, 443, CONTROLLED) for host in hosts
    ), connections)


def case_policy(case: str) -> egress.EgressPolicy:
    """``bounded`` narrows the bound; ``unrouted`` is the runbook's S6b policy,
    which removes ``chatgpt.com``; every other case is production's."""
    if case == "bounded":
        return account_policy(BOUNDED_CONNECTIONS)
    if case == "unrouted":
        return account_policy(8, hosts=(native_account.ISSUER,))
    return account_policy(8)


@pytest.fixture
def fixture_credential(binding):
    """The store's credential swapped for the recovery fixture, its bytes restored after."""
    credential = Path(binding.root) / operator_store._bundle_token("n3a-fixture") / "store" / (
        "auth.json")
    original, seeded = credential.read_bytes(), native_account.credential()
    credential.write_bytes(seeded)
    try:
        yield credential, seeded
    finally:
        credential.write_bytes(original)


def vendor_errors(stdout: list[bytes]) -> list[str]:
    """The vendor's JSON-RPC error messages, which carry no token, in order."""
    messages = []
    for line in b"".join(stdout).splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("error"), dict):
            messages.append(str(record["error"].get("message"))[:200])
    return messages


UNAUTHORIZED = "workspace routing discovery unauthorized (401)"
ACCOUNT_CHANGED = "account changed during workspace routing discovery"
DISCOVERY_FAILED = "workspace routing discovery failed"
"""The vendor's messages (``workspace_routing.rs:66-71`` at rust-v0.160.1)."""


def step(entry: dict) -> tuple[str, str | None, int]:
    """One logged request as (endpoint, token class, status); no token value."""
    endpoint = entry["path"].rsplit("/", 1)[-1].removeprefix("rate-limit-")
    kind = "refresh_token" if endpoint == "token" else "bearer"
    return endpoint, entry.get(kind), entry["status"]


OLD_CHECK = ("check", "old", 401)
FIXTURE = native_account.FIXTURE_ACCOUNT.identity.root
"""The identity the fixture credential's account has: what every reading names."""
STOPPED = NO_LOGIN - {NO_RESULT_FAULT}
"""The lane's three faults for a gate that stopped at ``account/read``."""


BOUNDED_CONNECTIONS = 3
"""The ``bounded`` case's egress bound: exactly the recovery's fixed opening, two
checks and one refresh, so the next connection any caller attempts is refused."""


@pytest.mark.parametrize("case", native_account.CASES)
async def test_account_read_recovers_from_a_401_exactly_as_its_case_allows(
    binding, trust_launcher, short_root, fixture_credential, monkeypatch, case,
):
    """Production's startup lane, configuration, command and egress bound, with
    only the destinations faked: a 401, then a refresh, then a clean or refused
    reading, while the store, the credential's mode, the sealed configuration and
    the egress policy hold. ``bounded`` alone narrows the bound, to prove it
    refuses deterministically."""

    credential, seeded = fixture_credential
    stdout: list[bytes] = []
    read = codex_lane.RecordingIO.read

    async def recording(self, maximum=8192):
        data = await read(self, maximum)
        stdout.append(data)
        return data

    monkeypatch.setattr(codex_lane.RecordingIO, "read", recording)
    inode = credential.stat().st_ino
    policy = case_policy(case)
    peer = native_account.AccountPeer(case, Path(os.environ["M8_TRUST_PKI"]))
    try:
        async with active_custody(binding) as custody:
            run = await run_startup(
                custody, trust_launcher, policy,
                executable=vendor_executable(trust_launcher),
                configuration=production_configuration(),
                expected=native_account.STRANGER_ACCOUNT if case == "stranger"
                else native_account.FIXTURE_ACCOUNT,
                lane_dir=short_root / f"acct-{case}", deadline_s=45,
                expect_denial=case == "unrouted",
            )
        assert await until(lambda: all(session["done"] for session in peer.sessions), 10)
    finally:
        peer.close()
    errors = vendor_errors(stdout)
    # Published unproved first, and marked proved only once every assertion holds.
    evidence = {
        "schema_version": 1, "credential_free_fixture": True,
        "vendor_conformance_qualified": False, "case": case, "assertions_passed": False,
        "connections": policy.connections,
        "methods_sent": run["methods_sent"], "faults": run["faults"], "gate": run["gate"],
        "refresh": run["refresh"], "relay": run["relay"], "credential": run["credential"],
        "requests": peer.log, "sessions": peer.sessions, "vendor_errors": errors,
    }
    write_evidence(f"n5-account-{case}.json", evidence)
    judge(case, run, peer, errors, policy, credential, seeded, inode)
    evidence["assertions_passed"] = True
    write_evidence(f"n5-account-{case}.json", evidence)


def judge(case, run, peer, errors, policy, credential, seeded, inode) -> None:
    """Every assertion of one recovery case; it returns only if all hold."""

    log = peer.log
    posts = [entry for entry in log if entry["path"] == native_account.TOKEN]
    # Every case: the egress, the sessions, the store, the credential's mode and identity.
    hosts = {f"{host}:443" for host in (native_account.BACKEND, native_account.ISSUER)}
    accepted = sum(count for key, count in run["relay"]["destinations"].items()
                   if key.startswith("accepted:"))
    denied = set(run["relay"]["denied"])
    assert {key.split(":", 1)[1] for key in run["relay"]["destinations"]} <= hosts, run["relay"]
    assert run["relay"]["closed"] is True, run["relay"]
    assert accepted <= policy.connections, run["relay"]
    # Each accepted connection is one answered session and one logged request:
    # a failed, unanswered or unlogged session cannot stand in for an answer.
    assert all(s["answered"] and s["alert"] is None and s["error"] is None
               for s in peer.sessions), peer.sessions
    assert len(peer.sessions) == len(log) == accepted, (peer.sessions, accepted)
    assert {s["sni"] for s in peer.sessions} <= {native_account.BACKEND, native_account.ISSUER}
    assert all(entry["account"] == "fixture" for entry in log if entry["bearer"]), log
    assert all(entry["grant"] for entry in posts), log
    assert sorted(os.listdir(credential.parent)) == ["auth.json"]
    assert credential.stat().st_ino == inode and run["credential"]["regular_0600"], run
    stored = json.loads(credential.read_bytes())["tokens"]
    assert stored["account_id"] == native_account.ACCOUNT_ID
    held = (native_account.classify(stored["access_token"], "access"),
            native_account.classify(stored["refresh_token"], "refresh"))
    if case == "unrouted":
        # The runbook's S6b: without chatgpt.com, account/read's own workspace
        # check is denied at the relay. The reading fails before any request
        # reaches a host, nothing is refreshed, and no readback is judged.
        # The relay is the only path to either host, and it records every
        # connection synchronously within the run: none was accepted, so the
        # fake's empty log is evidence, not a race against its accept thread.
        assert run["relay"]["destinations"] == {}, run["relay"]
        assert log == [] and peer.sessions == [], log
        assert run["credential"]["mtime_changed"] is False, run["credential"]
        assert set(run["relay"]["denied"]) == {"denied:destination"}, run["relay"]
        assert run["methods_sent"] == [named_method(method) for method in STARTUP_METHODS[:3]]
        assert set(run["faults"]) == STOPPED | {NO_RESULT_FAULT}, run["faults"]
        assert run["gate"] == {"completed": False, "plan": None, "account": None}, run["gate"]
        assert run["readback"] is None and errors == [DISCOVERY_FAILED], errors
        assert credential.read_bytes() == seeded
        return
    assert denied <= {"denied:connection_bound"}, run["relay"]
    # Every case opens as the pin's recovery does: the old bearer's check 401,
    # the reload, its check 401 again, then one refresh with the old token. What
    # follows races among the vendor's three discovery callers, so it is asserted
    # by meaning, not by schedule.
    steps = [step(entry) for entry in log]
    assert steps[:3] == [OLD_CHECK, OLD_CHECK, ("token", "old", 401 if case == "refused" else 200)]
    after = steps[3:]

    if case == "clean":
        assert run["faults"] == [], run["faults"]
        assert run["methods_sent"] == [named_method(method) for method in STARTUP_METHODS]
        assert run["gate"] == {"completed": True, "plan": "pro", "account": FIXTURE} and (
            run["refresh"] == "measured")
        assert not denied and len(posts) == 1, run["relay"]
        # Only the new bearer from here: its checks, and the readback's two requests.
        checks = [s for s in after if s[0] == "check"]
        assert checks and set(checks) == {("check", "new", 200)}, steps
        assert sorted(s for s in after if s[0] != "check") == [
            ("reset-credits", "new", 404), ("usage", "new", 200)], steps
        assert held == ("new", "new")
        return
    assert run["methods_sent"] == [named_method(method) for method in STARTUP_METHODS[:3]], run
    assert run["gate"]["completed"] is False and run["readback"] is None, run
    if case == "refused":
        # The refusal is cached and the file untouched. The adapter's reading
        # either recovers to the cached failure, an error, or starts after it and
        # is answered with no account: both are refusals, and nothing else is.
        assert not denied and len(posts) == 1 and set(after) <= {OLD_CHECK}, steps
        assert (set(run["faults"]), errors) in (
            (STOPPED | {NO_RESULT_FAULT}, [UNAUTHORIZED]), (STOPPED | {NO_ACCOUNT_FAULT}, []),
        ), (run["faults"], errors)
        assert credential.read_bytes() == seeded
    elif case in ("unauthorized", "bounded"):
        # Refreshes keep succeeding and checks keep failing, each recovery
        # starting from the old or the refreshed token, until a reading gives up
        # or the relay's bound refuses a connection.
        assert {post["refresh_token"] for post in posts} <= {"old", "new"}, steps
        assert all(s[2] == 401 for s in after if s[0] == "check"), steps
        assert set(run["faults"]) == STOPPED | {NO_RESULT_FAULT} | (
            {DENIAL_FAULT} if denied else set()), run["faults"]
        assert errors in ([UNAUTHORIZED], [DISCOVERY_FAILED]), errors
        assert held == ("new", "new")
        if case == "bounded":
            # The fixed opening fills the bound, and the first discovery still
            # owes its check with the refreshed token: that connection is refused,
            # whatever the other callers do.
            assert after == [] and accepted == policy.connections, steps
            assert denied == {"denied:connection_bound"}, run["relay"]
    elif case == "stranger":
        # The binding was sealed for another login, and the store holds this one:
        # the clean recovery completes, and our identity check refuses the account
        # the reading names, which is recorded as judged (M8-N5-account-identity.md).
        assert not denied and len(posts) == 1 and errors == [], (steps, errors)
        assert after and set(after) == {("check", "new", 200)}, steps
        assert set(run["faults"]) == STOPPED | {IDENTITY_FAULT}, run["faults"]
        assert run["gate"] == {"completed": False, "plan": None, "account": FIXTURE}
        assert held == ("new", "new")
    elif case == "changed":
        # Fail-closed by intent: the account check refuses before any check with
        # the other user's tokens, which stay persisted. A reading that instead
        # accepted the other user would be the pre-existing continuity gap the
        # design records, and must fail this test rather than pass it.
        assert not denied and len(posts) == 1 and after == [], steps
        assert set(run["faults"]) == STOPPED | {NO_RESULT_FAULT} and errors == [ACCOUNT_CHANGED]
        assert held == ("other", "other")
    else:
        assert not denied and len(posts) == 1, run["relay"]
        assert after and set(after) == {("check", "new", 200)} and errors == [], (steps, errors)
        assert set(run["faults"]) == STOPPED | {UNSEALED_BACKEND_FAULT}, run["faults"]
        assert held == ("new", "new")


def test_no_evidence_file_contains_key_material():
    directory = os.environ.get("M8_EVIDENCE_DIRECTORY")
    if not directory:
        if os.environ.get("M8_BRIDGE_REQUIRED"):
            pytest.fail("the required N4 bridge lane has no evidence directory")
        pytest.skip("N4 bridge evidence is written only by the provisioned Linux lane")
    files = sorted(Path(directory).glob("n4-*.json"))
    if os.environ.get("M8_BRIDGE_REQUIRED"):
        # The root lane's inherited-custody proof runs earlier in the same
        # foundation lane and writes into the same evidence directory, so its
        # file is present too and is scanned with the bridge's own.
        assert [path.name for path in files] == [
            "n4-bridge.json", "n4-inherited-maintenance.json",
            "n4-lane-login.json", "n4-lane-startup.json", "n4-lane-trust.json",
            "n4-pinned-client.json",
        ]
    accounts = sorted(Path(directory).glob("n5-account-*.json"))
    if os.environ.get("M8_BRIDGE_REQUIRED"):
        assert [path.name for path in accounts] == sorted(
            f"n5-account-{case}.json" for case in native_account.CASES)
    tokens = native_account.fixture_tokens()
    for path in files + accounts:
        text = path.read_text()
        assert "-----BEGIN" not in text and "PRIVATE KEY" not in text, path.name
        assert not any(token in text for token in tokens), path.name
