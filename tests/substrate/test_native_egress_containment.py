"""N3b physical egress proofs on the provisioned Linux lane; no credentials.

The native client is inline harmless Python that speaks CONNECT to the one
socket leaf. A throwaway CA and certificates are made with ``openssl`` in a
temporary directory for this run only; no private key is ever archived. The
peers are TLS servers on host loopback. These cases drive ``EgressRelay`` and
``launcher.exchange`` directly, as N3a's containment test does; the handle path
is covered by the portable suite. Every test uses a short acquisition root, since
a pytest ``tmp_path`` would exceed the socket path budget. The required lane
asserts its own preconditions: a missing ``openssl`` or an in-zone ``ssl`` that
cannot import is a failure there, never a skip.
"""

from __future__ import annotations

import asyncio
import errno
import json
import os
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path

import pytest

from constructicon.core.grants import Posture
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors import egress
from constructicon.substrate.executors.egress import (
    CHUNK_BYTES,
    EgressDestination,
    EgressPolicy,
    EgressRelay,
    identity_digests,
)
from constructicon.substrate.executors.linux import NativeStoreMount
from constructicon.substrate.git.acquisition import (
    AcquisitionClosure,
    AcquisitionPaths,
    acquisition_guard,
    dispose_acquisition,
)
from constructicon.substrate.git.authority import GitAuthority
from tests.gitworld import seed_authority
from tests.substrate.test_egress import (
    CONTROLLED,
    HeldPeer,
    controlled,
    refuse_resolution,
    until,
)
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence
from tests.substrate.test_operator_store_containment import binding as binding
from tests.substrate.test_operator_store_containment import hold

ALLOWED = "allowed.invalid"
DECOY = "decoy.invalid"

CLIENT = r"""
import errno, json, os, socket, stat, sys
plan = json.loads(sys.stdin.readline())
try:
    import ssl
except ImportError:
    print(json.dumps({'ssl': False}), flush=True)
    raise SystemExit(0)
context = ssl.create_default_context(cadata=plan['ca'])

def relay():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect('/vendor-egress.sock')
    return sock

def connect(host, port):
    sock = relay()
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

def https(host, port, path, server_hostname=None):
    sock = connect(host, port)
    if sock is None:
        return {'connect': 'refused'}
    try:
        tls = context.wrap_socket(sock, server_hostname=server_hostname or host)
    except OSError:
        sock.close()
        return {'connect': 'ok', 'tls': 'refused'}
    tls.sendall(f'GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'.encode())
    data = b''
    try:
        while chunk := tls.recv(8192):
            data += chunk
    except OSError:
        pass
    tls.close()
    head, _, body = data.partition(b'\r\n\r\n')
    lines = head.decode('latin-1').split('\r\n')
    location = [line.split(': ', 1)[1] for line in lines if line.startswith('Location: ')]
    return {'connect': 'ok', 'tls': 'ok', 'status': lines[0].split(' ')[1] if head else None,
            'location': location[0] if location else None, 'body': body.decode('latin-1')}

def with_ech(record):
    hello = record[9:]
    offset = 34
    offset += 1 + hello[offset]
    offset += 2 + int.from_bytes(hello[offset:offset + 2], 'big')
    offset += 1 + hello[offset]
    size = int.from_bytes(hello[offset:offset + 2], 'big')
    extensions = hello[offset + 2:offset + 2 + size] + b'\xfe\x0d\x00\x04\x00\x01\x02\x03'
    hello = hello[:offset] + len(extensions).to_bytes(2, 'big') + extensions
    body = b'\x01' + len(hello).to_bytes(3, 'big') + hello
    return record[:3] + len(body).to_bytes(2, 'big') + body

def ech(port):
    sock = connect(plan['allowed'], port)
    if sock is None:
        return 'no-connect'
    outgoing = ssl.MemoryBIO()
    tls = context.wrap_bio(ssl.MemoryBIO(), outgoing, server_hostname=plan['allowed'])
    try:
        tls.do_handshake()
    except ssl.SSLWantReadError:
        pass
    try:
        sock.sendall(with_ech(outgoing.read()))
        answer = sock.recv(1)
    except OSError:
        answer = b''
    sock.close()
    return 'refused' if answer == b'' else 'answered'

def errno_of(action):
    try:
        action()
    except socket.gaierror:
        return 'gaierror'
    except OSError as exc:
        return exc.errno
    return 0

def unix(path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
    finally:
        sock.close()

def sockets():
    found = []
    for top, directories, files in os.walk('/'):
        if top == '/':
            directories[:] = [name for name in directories if name != 'proc']
        for name in directories + files:
            path = os.path.join(top, name)
            try:
                if stat.S_ISSOCK(os.lstat(path).st_mode):
                    found.append(path)
            except OSError:
                pass
    return sorted(found)

results = {'ssl': True}
if plan['mode'] == 'walk':
    results['sockets'] = sockets()
elif plan['mode'] == 'flood':
    # One genuine hello for the relay to judge, then raw bytes for as long as
    # the path accepts them; the peer never completes TLS and never reads.
    sock = connect(plan['allowed'], plan['allowed_port'])
    outgoing = ssl.MemoryBIO()
    tls = context.wrap_bio(ssl.MemoryBIO(), outgoing, server_hostname=plan['allowed'])
    try:
        tls.do_handshake()
    except ssl.SSLWantReadError:
        pass
    sock.sendall(outgoing.read())
    print('streaming', flush=True)
    try:
        while True:
            sock.sendall(b'x' * 65536)
    except OSError as exc:
        results['stream_ended'] = type(exc).__name__
elif plan['mode'] == 'stream':
    sock = connect(plan['allowed'], plan['allowed_port'])
    tls = context.wrap_socket(sock, server_hostname=plan['allowed'])
    tls.sendall(b'GET /stream HTTP/1.1\r\nHost: allowed.invalid\r\n\r\n')
    tls.sendall(b'x' * 1024)
    print('streaming', flush=True)
    try:
        while True:
            tls.sendall(b'x' * 1024)
    except OSError as exc:
        results['stream_ended'] = type(exc).__name__
else:
    allowed, decoy = plan['allowed_port'], plan['decoy_port']
    results['accepted'] = https(plan['allowed'], allowed, '/')
    redirect = https(plan['allowed'], allowed, '/redirect')
    results['redirect'] = redirect
    target = (redirect.get('location') or '').removeprefix('https://').rstrip('/')
    host, _, port = target.rpartition(':')
    results['redirect_followed'] = https(host, int(port), '/') if host else None
    results['decoy'] = https(plan['decoy'], decoy, '/')
    results['ip_literal'] = https('127.0.0.1', allowed, '/')
    results['sni_mismatch'] = https(plan['allowed'], allowed, '/', server_hostname=plan['decoy'])
    results['ech'] = ech(allowed)
    results['tcp'] = errno_of(lambda: socket.create_connection(('192.0.2.1', 443), timeout=5))
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    results['udp_dns'] = errno_of(lambda: udp.sendto(b'x', ('192.0.2.1', 53)))
    results['loopback'] = errno_of(
        lambda: socket.create_connection(('127.0.0.1', allowed), timeout=5))
    results['dns'] = errno_of(lambda: socket.getaddrinfo(plan['allowed'], 443))
    results['abstract'] = errno_of(lambda: unix(plan['abstract']))
    results['unmounted'] = errno_of(lambda: unix(plan['unmounted']))
    results['sockets'] = sockets()
print(json.dumps(results), flush=True)
"""

WORKER = r"""
import json, os, socket, stat
info = os.lstat('/vendor-egress.sock')
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    sock.connect('/vendor-egress.sock')
    code = 0
except OSError as exc:
    code = exc.errno
print(json.dumps({'regular': stat.S_ISREG(info.st_mode), 'size': info.st_size,
                  'mode': stat.S_IMODE(info.st_mode), 'connect_errno': code}))
"""


def required() -> bool:
    return bool(os.environ.get("M8_EGRESS_REQUIRED"))


@pytest.fixture
def short_root():
    if sys.platform != "linux":
        pytest.skip("N3b physical egress requires the provisioned Linux lane")
    root = Path(tempfile.mkdtemp(prefix="n3b-", dir="/tmp"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _openssl(directory: Path, *arguments: str) -> None:
    subprocess.run(
        ["openssl", *arguments], cwd=directory, check=True, capture_output=True, timeout=60,
    )


class Pki:
    """A throwaway CA and two leaves, generated for this run and never archived."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        (directory / "ca.cnf").write_text(
            "[req]\ndistinguished_name = dn\nprompt = no\nx509_extensions = ca\n"
            "[dn]\nCN = n3b-throwaway-ca\n"
            "[ca]\nbasicConstraints = critical,CA:TRUE\n"
            "keyUsage = critical,keyCertSign,cRLSign\nsubjectKeyIdentifier = hash\n"
        )
        _openssl(directory, "req", "-x509", "-new", "-nodes", "-newkey", "ec",
                 "-pkeyopt", "ec_paramgen_curve:prime256v1", "-keyout", "ca.key",
                 "-out", "ca.pem", "-days", "1", "-config", "ca.cnf")
        for name in ("allowed", "decoy"):
            (directory / f"{name}.cnf").write_text(
                f"[req]\ndistinguished_name = dn\nprompt = no\n[dn]\nCN = {name}.invalid\n"
            )
            (directory / f"{name}.ext").write_text(
                f"subjectAltName = DNS:{name}.invalid\nbasicConstraints = critical,CA:FALSE\n"
                "keyUsage = critical,digitalSignature\nextendedKeyUsage = serverAuth\n"
                "subjectKeyIdentifier = hash\nauthorityKeyIdentifier = keyid\n"
            )
            _openssl(directory, "req", "-new", "-nodes", "-newkey", "ec",
                     "-pkeyopt", "ec_paramgen_curve:prime256v1", "-keyout", f"{name}.key",
                     "-out", f"{name}.csr", "-config", f"{name}.cnf")
            _openssl(directory, "x509", "-req", "-in", f"{name}.csr", "-CA", "ca.pem",
                     "-CAkey", "ca.key", "-CAcreateserial", "-days", "1",
                     "-out", f"{name}.pem", "-extfile", f"{name}.ext")
        self.ca = (directory / "ca.pem").read_text()

    def server(self, name: str) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.directory / f"{name}.pem", self.directory / f"{name}.key")
        return context


@pytest.fixture
def pki(short_root):
    if shutil.which("openssl") is None:
        if required():
            pytest.fail("the required N3b lane has no openssl for its throwaway CA")
        pytest.skip("openssl is required for the throwaway N3b CA")
    with tempfile.TemporaryDirectory(prefix="n3b-pki-") as directory:
        yield Pki(Path(directory))


class PeerConnection:
    def __init__(self) -> None:
        self.bytes = 0
        self.handshake = False
        self.eof = False
        self.eof_at: float | None = None


class TlsPeer:
    """A host TLS server that records connections and bytes; it forwards nothing."""

    def __init__(self, context: ssl.SSLContext) -> None:
        self.context = context
        self.redirect: str | None = None
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.connections: list[PeerConnection] = []
        self.raw: list[socket.socket] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                raw, _ = self.server.accept()
            except OSError:
                return
            record = PeerConnection()
            self.connections.append(record)
            self.raw.append(raw)
            threading.Thread(target=self._session, args=(raw, record), daemon=True).start()

    def _session(self, raw: socket.socket, record: PeerConnection) -> None:
        try:
            with self.context.wrap_socket(raw, server_side=True) as tls:
                record.handshake = True
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = tls.recv(8192)
                    if not chunk:
                        return
                    request += chunk
                record.bytes += len(request)
                path = request.split(b" ")[1]
                if path == b"/redirect":
                    tls.sendall(
                        f"HTTP/1.1 302 Found\r\nLocation: {self.redirect}\r\n"
                        "Content-Length: 0\r\nConnection: close\r\n\r\n".encode()
                    )
                elif path == b"/stream":
                    tls.sendall(b"HTTP/1.1 200 OK\r\n\r\n")
                    while chunk := tls.recv(65536):
                        record.bytes += len(chunk)
                else:
                    tls.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\nConnection: close\r\n\r\n"
                        b"harmless-peer"
                    )
        except (OSError, IndexError):
            pass
        finally:
            record.eof_at = time.monotonic()
            record.eof = True

    def close(self) -> None:
        for sock in (self.server, *self.raw):
            with suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()


@pytest.fixture(autouse=True)
def controlled_peers(monkeypatch):
    """Every peer in this module is a controlled loopback server (see ``controlled``)."""
    monkeypatch.setattr(egress, "_routable", controlled(egress._routable))


def policy_for(port: int) -> EgressPolicy:
    return EgressPolicy((EgressDestination(ALLOWED, port, CONTROLLED),), 16)


def send_queue_to(port: int) -> int:
    """The largest host TCP send queue toward ``127.0.0.1:<port>`` (``/proc/net/tcp``)."""
    largest = 0
    for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        fields = line.split()
        if int(fields[2].split(":")[1], 16) == port:
            largest = max(largest, int(fields[4].split(":")[0], 16))
    return largest


def guard_holders(guard: Path) -> list[str]:
    """Every process of this uid that still has the acquisition guard open.

    A process whose ``/proc`` entry this uid does not own (another uid, or a
    non-dumpable process) is not scanned: a limit, not a finding. The native
    tree and its supervisor run as this uid.
    """
    target = str(guard.resolve())
    holders = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            descriptors = list((entry / "fd").iterdir())
        except FileNotFoundError:
            continue  # the process exited during the scan
        for item in descriptors:
            with suppress(FileNotFoundError):
                if os.readlink(item) == target:
                    holders.append(entry.name)
    return holders


def plan_for(pki: Pki, allowed: TlsPeer, **extra) -> dict:
    return {"ca": pki.ca, "allowed": ALLOWED, "allowed_port": allowed.port,
            "decoy": DECOY, **extra}


def conversation_for(plan: dict, output: bytearray, streaming: asyncio.Event | None = None):
    async def conversation(io):
        await io.write((json.dumps(plan) + "\n").encode())
        while chunk := await io.read():
            output.extend(chunk)
            if streaming is not None and b"streaming\n" in output:
                streaming.set()

    return conversation


async def run_native(launcher, binding, root: Path, lease: str, plan: dict, *,
                     policy: EgressPolicy, seconds: float = 60.0, output=None, streaming=None):
    """One contained native exchange inside its own relay; returns (result, relay)."""
    held = await hold(binding)
    paths = AcquisitionPaths(root, acquisition_id_for(lease, 1))
    output = bytearray() if output is None else output
    relay = EgressRelay(policy, paths.payload, asyncio.get_running_loop().time() + seconds,
                        lambda: None)
    try:
        async with acquisition_guard(paths) as guard, relay as leaf:
            result = await launcher.exchange(
                ("/usr/bin/python3", "-I", "-c", CLIENT), workspace=None,
                posture=Posture.READ, guard_fds=(guard, held.lock_fd), timeout_s=seconds,
                conversation=conversation_for(plan, output, streaming),
                native_store=NativeStoreMount(
                    path=held.store_path, lock_fd=held.lock_fd,
                    before_spawn=lambda: binding.check_held(held), egress=leaf,
                ),
            )
    finally:
        binding.close_held(held)
    return result, relay, output


def facts_of(result, output: bytearray) -> dict:
    assert result.returncode == result.payload_returncode == 0, result
    facts = json.loads(bytes(output).strip().splitlines()[-1])
    assert facts.get("ssl") is True, "ssl cannot import inside the production runtime"
    return facts


@pytest.fixture
def closure(tmp_path):
    root = tmp_path / "authority"
    root.mkdir()
    return AcquisitionClosure(GitAuthority(seed_authority(root), root / "legacy"))


def unix_listener(address: str) -> socket.socket:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(address)
    listener.listen()
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(address)  # the positive control: the host reaches it
    finally:
        probe.close()
    return listener


async def test_the_zone_reaches_only_the_pinned_destination(
    binding, launcher, pki, short_root, monkeypatch,
):
    allowed, decoy = TlsPeer(pki.server("allowed")), TlsPeer(pki.server("decoy"))
    allowed.redirect = f"https://{DECOY}:{decoy.port}/"
    abstract_name = f"\0n3b-{os.getpid()}-{time.monotonic_ns()}"
    abstract = unix_listener(abstract_name)
    unmounted = unix_listener(str(short_root / "host.sock"))
    try:
        # Positive control: the decoy is live and verifies against the same CA.
        control = ssl.create_default_context(cadata=pki.ca)
        with socket.create_connection(("127.0.0.1", decoy.port), timeout=5) as raw, \
                control.wrap_socket(raw, server_hostname=DECOY) as tls:
            tls.sendall(b"GET / HTTP/1.1\r\nHost: decoy.invalid\r\n\r\n")
            tls.recv(64)
        assert await until(lambda: len(decoy.connections) == 1 and decoy.connections[0].eof)
        resolved = refuse_resolution(monkeypatch)
        policy = policy_for(allowed.port)
        plan = plan_for(pki, allowed, mode="probe", decoy_port=decoy.port,
                        abstract=abstract_name, unmounted=str(short_root / "host.sock"))
        result, relay, output = await run_native(
            launcher, binding, short_root, "n3b-egress-proof", plan, policy=policy,
        )
        facts = facts_of(result, output)
    finally:
        for item in (allowed, decoy):
            item.close()
        abstract.close()
        unmounted.close()

    assert facts["accepted"] == {"connect": "ok", "tls": "ok", "status": "200",
                                 "location": None, "body": "harmless-peer"}
    assert facts["redirect"]["status"] == "302"
    assert facts["redirect_followed"] == {"connect": "refused"}
    assert facts["decoy"] == {"connect": "refused"}
    assert facts["ip_literal"] == {"connect": "refused"}
    assert facts["sni_mismatch"] == {"connect": "ok", "tls": "refused"}
    assert facts["ech"] == "refused"
    assert facts["tcp"] == errno.ENETUNREACH and facts["udp_dns"] == errno.ENETUNREACH
    assert facts["loopback"] == errno.ECONNREFUSED
    assert facts["dns"] == "gaierror"
    assert facts["abstract"] == errno.ECONNREFUSED
    assert facts["unmounted"] == errno.ENOENT
    assert facts["sockets"] == ["/vendor-egress.sock"]
    observed = {key: value for key, value in relay.observed.items() if key != "reset"}
    assert observed == {
        "accepted": 2, "denied:destination": 2, "denied:ip_literal": 1,
        "denied:sni": 1, "denied:ech": 1,
    }
    assert relay.closed
    assert len(allowed.connections) == 2 and all(item.handshake for item in allowed.connections)
    assert len(decoy.connections) == 1, "the decoy saw a connection besides the host control"
    assert resolved == [("control.invalid", 443)], "the relay resolved a name"
    write_evidence("n3b-egress.json", {
        "schema_version": 1, "credential_free_fixture": True,
        "vendor_conformance_qualified": False,
        "launch_revision": str(launcher.revision),
        "egress_identity": {key: str(value) for key, value in identity_digests(policy).items()},
        "observed": dict(relay.observed),
        "peers": {
            "allowed": {"connections": len(allowed.connections),
                        "bytes": sum(item.bytes for item in allowed.connections)},
            "decoy": {"connections": len(decoy.connections),
                      "bytes": sum(item.bytes for item in decoy.connections)},
        },
        "positive_controls": {
            "resolver_recorder_live": True, "decoy_reachable_from_host": True,
            "abstract_socket_reachable_from_host": True,
            "unmounted_socket_reachable_from_host": True,
        },
        "zone": {key: facts[key] for key in (
            "tcp", "udp_dns", "loopback", "dns", "abstract", "unmounted", "sockets",
        )},
    })


async def test_the_zone_walk_finds_a_socket_planted_in_the_store(
    binding, launcher, pki, short_root,
):
    """The positive control for the socket walk: the store is a pathname route."""
    allowed = TlsPeer(pki.server("allowed"))
    probe = await hold(binding)
    planted_path = probe.store_path / "planted.sock"
    # The store path is longer than sun_path; bind through a short dirfd path.
    directory = os.open(probe.store_path, os.O_RDONLY | os.O_DIRECTORY)
    binding.close_held(probe)
    try:
        planted = unix_listener(f"/proc/self/fd/{directory}/planted.sock")
    finally:
        os.close(directory)
    try:
        result, _, output = await run_native(
            launcher, binding, short_root, "n3b-walk-control",
            plan_for(pki, allowed, mode="walk"), policy=policy_for(allowed.port),
        )
        facts = facts_of(result, output)
    finally:
        planted.close()
        planted_path.unlink(missing_ok=True)
        allowed.close()
    assert facts["sockets"] == ["/vendor-egress.sock", "/vendor-store/planted.sock"]
    write_evidence("n3b-zone-sockets.json", {
        "schema_version": 1, "planted_store_socket_found": True,
        "sockets": facts["sockets"],
    })


async def test_an_ordinary_worker_sees_an_empty_regular_leaf(launcher, short_root):
    paths = AcquisitionPaths(short_root, acquisition_id_for("n3b-worker-leaf", 1))
    workspace = short_root / "workspace"
    workspace.mkdir()
    async with acquisition_guard(paths) as guard:
        result = await launcher.run(
            ("/usr/bin/python3", "-I", "-c", WORKER), workspace=workspace,
            posture=Posture.READ, guard_fds=(guard,), timeout_s=20,
        )
    assert result.returncode == result.payload_returncode == 0, result
    facts = json.loads(result.stdout)
    # Linux's unix_find_bsd checks write permission on the path before its
    # type, so an 0444 leaf refuses with EACCES before ECONNREFUSED could
    # report that it is not a socket (net/unix/af_unix.c, v6.8).
    assert facts == {"regular": True, "size": 0, "mode": 0o444,
                     "connect_errno": errno.EACCES}
    write_evidence("n3b-worker-leaf.json", {"schema_version": 1, **facts})


async def test_cancel_mid_stream_revokes_the_upstream(binding, launcher, pki, short_root):
    allowed = TlsPeer(pki.server("allowed"))
    streaming = asyncio.Event()
    task = asyncio.create_task(run_native(
        launcher, binding, short_root, "n3b-cancel", plan_for(pki, allowed, mode="stream"),
        policy=policy_for(allowed.port), streaming=streaming,
    ))
    try:
        await asyncio.wait_for(streaming.wait(), 60)
        assert await until(lambda: allowed.connections and allowed.connections[0].bytes > 0)
        assert not allowed.connections[0].eof
        task.cancel()
        outcome = (await asyncio.gather(task, return_exceptions=True))[0]
        joined_at = time.monotonic()
        assert isinstance(outcome, BaseException)
        assert await until(lambda: allowed.connections[0].eof, 2.0), "a stream outlived cancel"
    finally:
        allowed.close()
    write_evidence("n3b-cancel.json", {
        "schema_version": 1, "peer_eof_within_s": round(
            max(0.0, (allowed.connections[0].eof_at or joined_at) - joined_at), 3),
        "bytes_before_cancel": allowed.connections[0].bytes,
    })


async def test_the_deadline_cuts_an_actively_streaming_client(
    binding, launcher, pki, short_root,
):
    allowed = TlsPeer(pki.server("allowed"))
    seconds = 12.0
    loop = asyncio.get_running_loop()

    class Stamped(asyncio.Event):
        at: float | None = None

        def set(self) -> None:
            if self.at is None:
                self.at = loop.time()
            super().set()

    streaming = Stamped()
    started = loop.time()
    try:
        result, relay, _ = await run_native(
            launcher, binding, short_root, "n3b-deadline", plan_for(pki, allowed, mode="stream"),
            policy=policy_for(allowed.port), seconds=seconds, streaming=streaming,
        )
    finally:
        allowed.close()
    deadline = relay._deadline
    # run_native takes the deadline after `started` and before the client can
    # stream through the relay, so it lies within seconds of that interval.
    assert streaming.at is not None
    assert started + seconds <= deadline <= streaming.at + seconds
    connection = allowed.connections[0]
    assert connection.bytes > 0 and connection.eof_at is not None
    tick = time.get_clock_info("monotonic").resolution  # asyncio may fire one tick early
    assert deadline - tick <= connection.eof_at <= deadline + 1.0, (connection.eof_at, deadline)
    assert relay.observed["accepted"] == 1 and relay.observed["denied:deadline"] == 1
    assert result.timed_out
    write_evidence("n3b-deadline.json", {
        "schema_version": 1, "observed": dict(relay.observed),
        "peer_eof_after_deadline_s": round(connection.eof_at - deadline, 3),
    })


async def owner_process(mode: str, root: Path, plan: dict):
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan))
    return await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.substrate._egress_owner", mode, str(root), str(plan_path),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def test_controller_death_ends_streams_and_a_successor_disposes_the_relay(
    binding, launcher, pki, short_root, closure,
):
    allowed = TlsPeer(pki.server("allowed"))
    plan = plan_for(pki, allowed, mode="stream", lease="n3b-owner-death",
                    seconds=60, stall_extra=0)
    paths = AcquisitionPaths(short_root, acquisition_id_for("n3b-owner-death", 1))
    owner = await owner_process("death", short_root, plan)
    successor = None
    try:
        assert owner.stdout is not None
        assert await asyncio.wait_for(owner.stdout.readline(), 60) == b"streaming\n"
        assert await until(lambda: allowed.connections and allowed.connections[0].bytes > 0)
        # The positive control for the holder scan: the live owner's tree holds the guard.
        assert guard_holders(paths.guard), "the guard scan saw no live holder"
        owner.kill()
        stale = paths.payload / "egress.sock"
        assert stat.S_ISSOCK(os.lstat(stale).st_mode), "the dead owner left no stale socket"
        # Started at once: nothing but the guard orders it after quiescence.
        successor = asyncio.create_task(dispose_acquisition(closure, paths))
        disposed = await asyncio.wait_for(successor, 30)
        completed_at = time.monotonic()
        holders = guard_holders(paths.guard)
        assert disposed is True and not paths.payload.exists()
        assert holders == [], f"processes {holders} held the guard after disposal completed"
        assert await until(lambda: owner.returncode is not None, 5.0)
        connection = allowed.connections[0]
        assert connection.eof and connection.eof_at is not None, "a stream outlived its owner"
        assert connection.eof_at <= completed_at, "the successor finished before the peer's EOF"
    finally:
        if successor is not None and not successor.done():
            successor.cancel()
        if owner.returncode is None:
            owner.kill()
        await asyncio.wait_for(owner.communicate(), 10)
        allowed.close()
    write_evidence("n3b-owner-death.json", {
        "schema_version": 1, "controller_killed": True, "peer_eof_after_death": True,
        "stale_socket_disposed_by_successor": True,
        "successor_started_at_kill": True, "guard_holders_after_disposal": holders,
        "peer_eof_before_disposal_completed_s": round(completed_at - connection.eof_at, 3),
    })


async def test_controller_death_discards_the_upstream_queue(
    binding, launcher, pki, short_root, closure,
):
    """No cleanup runs in a killed controller, so only linger set at creation
    can turn the kernel's close into a reset that discards the send queue."""
    peer = HeldPeer()
    plan = plan_for(pki, peer, mode="flood", lease="n3b-death-queue", seconds=60, stall_extra=0)
    paths = AcquisitionPaths(short_root, acquisition_id_for("n3b-death-queue", 1))
    owner = await owner_process("death", short_root, plan)
    try:
        assert owner.stdout is not None
        assert await asyncio.wait_for(owner.stdout.readline(), 60) == b"streaming\n"
        # The bound needs an input where it binds: bytes queued beyond the peer.
        assert await until(lambda: send_queue_to(peer.port) > 0, 10.0), "nothing was queued"
        queued = send_queue_to(peer.port)
        owner.kill()
        async with asyncio.timeout(5):
            while owner.returncode is None:
                await asyncio.sleep(0.01)
        # A graceful close would leave an orphan still holding the queue.
        assert await until(lambda: send_queue_to(peer.port) == 0, 5.0), "the queue outlived death"
        held, total = await asyncio.to_thread(peer.drain)
        assert total <= held, f"{total - held} queued bytes reached the peer after death"
        assert await asyncio.wait_for(dispose_acquisition(closure, paths), 30) is True
    finally:
        if owner.returncode is None:
            owner.kill()
        await asyncio.wait_for(owner.communicate(), 10)
        peer.close()
    write_evidence("n3b-owner-death-queue.json", {
        "schema_version": 1, "queued_at_kill": queued, "peer_held": held,
        "bytes_after_death": max(0, total - held),
    })


async def test_a_stalled_controller_holds_its_guard_until_its_streams_end(
    binding, launcher, pki, short_root, closure,
):
    """The recorded limit, pinned: a stalled owner keeps an upstream open, carries
    no byte during the stall once its queue drained (the settle below) and at
    most one partial pump write after it, and a concurrent successor waits for
    the peer's EOF."""
    allowed = TlsPeer(pki.server("allowed"))
    plan = plan_for(pki, allowed, mode="stream", lease="n3b-stalled-owner",
                    seconds=12, stall_extra=6)
    paths = AcquisitionPaths(short_root, acquisition_id_for("n3b-stalled-owner", 1))
    owner = await owner_process("stall", short_root, plan)
    successor = None
    try:
        assert owner.stdout is not None
        assert await asyncio.wait_for(owner.stdout.readline(), 60) == b"streaming\n"
        stalling = (await asyncio.wait_for(owner.stdout.readline(), 10)).split()
        assert stalling[0] == b"stalling"
        deadline = float(stalling[1])
        await asyncio.sleep(0.5)
        connection = allowed.connections[0]
        settled = connection.bytes
        successor = asyncio.create_task(dispose_acquisition(closure, paths))
        while time.monotonic() < deadline + 3:  # past the reaper's two-second grace
            await asyncio.sleep(0.05)
        assert not successor.done(), "a successor proceeded while the old owner held a stream"
        assert not connection.eof, "the stalled owner's upstream closed before it resumed"
        assert connection.bytes == settled, "a byte reached the peer during the stall"
        report = json.loads(await asyncio.wait_for(owner.stdout.readline(), 60))
        await asyncio.wait_for(successor, 30)
        completed_at = time.monotonic()
        assert connection.eof and connection.eof_at is not None
        assert connection.eof_at <= completed_at, "the successor finished before the peer's EOF"
        # The recorded limit: a partial write that began before the stall may
        # finish after it, so at most one pump chunk of ciphertext (read before
        # the stall) completes at most nine of the client's 1 KiB records.
        assert connection.bytes - settled <= CHUNK_BYTES + 1024, "the relay forwarded after stop"
        assert report["timed_out"] and report["closed"]
        assert not paths.payload.exists()
    finally:
        if successor is not None and not successor.done():
            successor.cancel()
        if owner.returncode is None:
            owner.kill()
        await asyncio.wait_for(owner.communicate(), 30)
        allowed.close()
    write_evidence("n3b-stalled-owner.json", {
        "schema_version": 1, "successor_waited_for_peer_eof": True,
        "bytes_during_stall": 0, "bytes_after_resume": connection.bytes - settled,
        "owner_report": report,
    })


def test_no_evidence_file_contains_key_material():
    directory = os.environ.get("M8_EVIDENCE_DIRECTORY")
    if not directory or sys.platform != "linux":
        if required():
            pytest.fail("the required N3b lane has no evidence directory")
        pytest.skip("N3b evidence is written only by the provisioned Linux lane")
    files = sorted(Path(directory).glob("n3b-*.json"))
    if required():
        assert files, "the required N3b lane wrote no evidence"
    for path in files:
        text = path.read_text()
        assert "-----BEGIN" not in text and "PRIVATE KEY" not in text, path.name
