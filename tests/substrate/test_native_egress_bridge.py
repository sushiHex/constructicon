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
import io
import json
import os
import socket
import ssl
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.identity import Digest
from constructicon.substrate.executors import egress, operator_store
from constructicon.substrate.executors._egress_bridge import PROXY_PORT
from constructicon.substrate.executors.codex_lane import (
    active_custody,
    run_login,
    run_startup,
)
from constructicon.substrate.executors.codex_protocol import ExpectedAccount
from constructicon.substrate.executors.egress import identity_digests
from tests.native_startup import (
    BOOTSTRAP,
    CATALOG,
    MODELS,
    DuplexWire,
    configuration,
    initialize,
)
from tests.substrate.test_egress import until
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

PROXY = f"http://127.0.0.1:{PROXY_PORT}"
ZONE_ENVIRONMENT = {
    "HOME": "/tmp/home", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PWD": "/tmp",
    # The N4 layout names the vendor home explicitly on every native launch.
    "CODEX_HOME": "/tmp/home/.codex",
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


def test_no_evidence_file_contains_key_material():
    directory = os.environ.get("M8_EVIDENCE_DIRECTORY")
    if not directory:
        if os.environ.get("M8_BRIDGE_REQUIRED"):
            pytest.fail("the required N4 bridge lane has no evidence directory")
        pytest.skip("N4 bridge evidence is written only by the provisioned Linux lane")
    files = sorted(Path(directory).glob("n4-*.json"))
    if os.environ.get("M8_BRIDGE_REQUIRED"):
        assert [path.name for path in files] == [
            "n4-bridge.json", "n4-lane-login.json", "n4-lane-startup.json",
            "n4-pinned-client.json",
        ]
    for path in files:
        text = path.read_text()
        assert "-----BEGIN" not in text and "PRIVATE KEY" not in text, path.name


# --- N4 lanes with the pinned binary (M8-N4-state-review.md, L2 and L3) --------

PINNED = "/opt/native-startup/native/bin/codex"
EMPTY_AUTH = b"{}\n"
"""An ``AuthDotJson`` with every field absent: no login, parsed rather than
malformed, so the pinned client reports no account."""


def sealed_configuration(*, plugins: bool) -> str:
    """The production sealed configuration's shape (state review, section 1)."""
    return (
        f'model = "{MODELS[0]}"\nmodel_catalog_json = "{CATALOG}"\n'
        'cli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\n'
        'check_for_update_on_startup = false\nweb_search = "disabled"\n'
        "[analytics]\nenabled = false\n[features]\n"
        + ("" if plugins else "plugins = false\n")
        + "apps = false\nshell_tool = false\nunified_exec = false\n"
        "apply_patch_freeform = false\nview_image = false\nmulti_agent = false\n"
        "code_mode = false\njs_repl = false\n"
    )


def decoy_policy() -> egress.EgressPolicy:
    """A sealed policy naming only a decoy: every vendor CONNECT is a denial."""
    return egress.EgressPolicy((egress.EgressDestination(DECOY, 443, "8.8.8.8"),), 8)


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
    binding, bridge_launcher, short_root, heads, empty_auth,
):
    """L2: zero denials with plugins off, beside a same-step control that counts."""
    runs = {}
    for plugins in (False, True):
        heads.clear()
        async with active_custody(binding) as custody:
            runs[plugins] = await run_startup(
                custody, bridge_launcher, decoy_policy(), binary=PINNED,
                configuration=sealed_configuration(plugins=plugins),
                expected=ExpectedAccount(plan_type="pro", alternatives=("prolite",)),
                lane_dir=short_root / f"lane-{int(plugins)}", deadline_s=30,
                expect_denial=plugins,
            )
        runs[plugins]["heads"] = [head.split(b"\r\n", 1)[0].decode() for head in heads]
    clean, control = runs[False], runs[True]
    assert clean["methods_sent"] == ["'initialize'", "'initialized'", "'account/read'"]
    assert any("no usable account" in fault for fault in clean["faults"]), clean["faults"]
    assert clean["relay"] == {"destinations": {}, "denied": {}}, clean["relay"]
    assert clean["heads"] == [] and clean["readback"] is None
    assert control["relay"]["denied"].get("denied:destination", 0) >= 1, control["relay"]
    assert control["heads"], "the control's plugin sync never reached the relay"
    assert empty_auth.read_bytes() == EMPTY_AUTH
    write_evidence("n4-lane-startup.json", {
        "schema_version": 1, "credential_free_fixture": True, "model_requests": 0,
        "vendor_conformance_qualified": False,
        "clean": {key: clean[key] for key in ("methods_sent", "relay", "heads", "faults")},
        "control": {key: control[key] for key in ("relay", "heads")},
    })


async def test_the_pinned_device_login_reaches_only_the_relay_and_keeps_nothing(
    binding, bridge_launcher, short_root, heads, empty_auth,
):
    """L3: the login's CONNECT is denied, its output is never evidence."""
    out = io.BytesIO()
    async with active_custody(binding) as custody:
        evidence = await run_login(
            custody, bridge_launcher, decoy_policy(), binary=PINNED,
            configuration=sealed_configuration(plugins=False),
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
