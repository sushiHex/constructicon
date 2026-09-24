"""N3c refresh, cleanup and store persistence on the provisioned Linux lane.

Credential-free, as ``m8-service`` over the N3a CI fixture. The persistence
proof runs through the real N3b relay and leaf, not the egressless N3a launch.
Under the N4 layout the zone reaches the store only as its one bound file, so
what one acquisition plants in its vendor home must survive into neither the
next acquisition's launch arguments, its home, nor the zone's reach. Every
denial is paired with a same-run positive control, and the probe must first
prove it ran. The required lane fails, never skips, when its fixture is absent.
"""

from __future__ import annotations

import asyncio
import errno
import json
import os
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors import operator_store
from constructicon.substrate.executors.egress import EgressRelay
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests.substrate.test_egress import controlled_loopback as controlled_loopback
from tests.substrate.test_egress import refuse_resolution
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence
from tests.substrate.test_native_egress_containment import (
    TlsPeer,
    plan_for,
    policy_for,
    unix_listener,
)
from tests.substrate.test_native_egress_containment import pki as pki
from tests.substrate.test_native_egress_containment import short_root as short_root
from tests.substrate.test_operator_store_containment import (
    CONFIGURATION,
    CREDENTIAL,
    KEY,
    collect,
    hold,
    native_mount,
    normalized,
)
from tests.substrate.test_operator_store_containment import binding as binding

REFRESHED = b"refreshed harmless fixture\n"

REFRESH = r"""
import json, os
from pathlib import Path
home = Path('/tmp/home/.codex')
credential = home / 'auth.json'
# The pinned store's own save pattern: truncate and rewrite the same inode.
with open(credential, 'r+b') as stream:
    stream.truncate(0)
    stream.write(REFRESHED)
    stream.flush()
    os.fsync(stream.fileno())
# A rename-over replacement cannot reach the bound file at all.
staged = home / 'auth.json.pending'
staged.write_bytes(b'replacement\n')
try:
    os.replace(staged, credential)
    replace_errno = 0
except OSError as exc:
    replace_errno = exc.errno
print(json.dumps({
    'rewritten': credential.read_bytes() == REFRESHED,
    'replace_errno': replace_errno,
}), flush=True)
""".replace("REFRESHED", repr(REFRESHED))

HELPER = r"""#!/usr/bin/python3 -I
import errno, json, os, socket, ssl, sys
plan = json.loads(sys.stdin.read())
print('helper ran', flush=True)
context = ssl.create_default_context(cadata=plan['ca'])

def errno_of(action):
    try:
        action()
    except OSError as exc:
        return exc.errno
    return 0

def unix(path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
    finally:
        sock.close()

def https(host, port):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect('/vendor-egress.sock')
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
        return 'refused'
    tls = context.wrap_socket(sock, server_hostname=host)
    tls.sendall(f'GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'.encode())
    data = b''
    try:
        while chunk := tls.recv(8192):
            data += chunk
    except OSError:
        pass
    tls.close()
    return data.partition(b'\r\n\r\n')[2].decode('latin-1')

def write(path):
    with open(path, 'w') as stream:
        stream.write('escaped')

facts = {
    'workspace_entries': sorted(os.listdir('/workspace')) if os.path.isdir('/workspace') else [],
    'workspace_write': errno_of(lambda: write('/workspace/n3c-probe')),
    'root_write': errno_of(lambda: write('/n3c-probe')),
    'anchor': errno_of(lambda: open(plan['anchor'], 'rb').close()),
    'lock': errno_of(lambda: open(plan['lock'], 'rb').close()),
    'tcp': errno_of(lambda: socket.create_connection(('192.0.2.1', 443), timeout=5)),
    'host_socket': errno_of(lambda: unix(plan['unmounted'])),
    'decoy': https(plan['decoy'], plan['decoy_port']),
    'allowed': https(plan['allowed'], plan['allowed_port']),
}
private = []
for fd in os.listdir('/proc/self/fd'):
    try:
        target = os.readlink(f'/proc/self/fd/{fd}')
    except OSError:
        continue
    if 'retained.lock' in target or 'anchor.json' in target or '/guards/' in target:
        private.append(fd)
facts['private_fds'] = private
print(json.dumps(facts), flush=True)
"""

NATIVE = r"""
import json, subprocess, sys
from pathlib import Path
plan = json.loads(sys.stdin.readline())
home = Path('/tmp/home/.codex')
if plan['mode'] == 'plant':
    try:
        (home / 'config.toml').write_text('model_provider = "decoy"\n')
        config_errno = 0
    except OSError as exc:
        config_errno = exc.errno
    (home / 'hooks.json').write_text('{"startup": ["/tmp/home/.codex/helper"]}\n')
    (home / 'helper').write_text(plan['helper'])
    (home / 'helper').chmod(0o700)
    print(json.dumps({'planted': (home / 'helper').is_file(),
                      'config_errno': config_errno}), flush=True)
else:
    survivors = sorted(name for name in ('hooks.json', 'helper') if (home / name).exists())
    config = (home / 'config.toml').read_bytes()
    helper = plan.pop('helper')
    ran = subprocess.run(['/usr/bin/python3', '-I', '-c', helper], input=json.dumps(plan),
                         capture_output=True, text=True, timeout=60)
    lines = ran.stdout.splitlines()
    print(json.dumps({'returncode': ran.returncode, 'lines': lines[:1],
                      'survivors': survivors, 'config': config.decode(),
                      'home_entries': sorted(p.name for p in home.iterdir()),
                      'facts': json.loads(lines[-1]) if len(lines) > 1 else None}), flush=True)
"""


async def launch(launcher, binding, root: Path, plan: dict, policy):
    """One contained native exchange inside its own relay, one fixed acquisition."""
    held = await hold(binding)
    paths = AcquisitionPaths(root, acquisition_id_for("n3c-persistence", 1))
    output = bytearray()
    relay = EgressRelay(policy, paths.payload, asyncio.get_running_loop().time() + 60,
                        lambda: None)

    async def conversation(io):
        await io.write((json.dumps(plan) + "\n").encode())
        while chunk := await io.read():
            output.extend(chunk)

    try:
        async with acquisition_guard(paths) as guard, relay as leaf:
            with native_mount(binding, held, egress=leaf) as mount:
                result = await launcher.exchange(
                    ("/usr/bin/python3", "-I", "-c", NATIVE), workspace=None,
                    posture=Posture.READ, guard_fds=(guard, held.lock_fd), timeout_s=60,
                    conversation=conversation, native_store=mount,
                )
        terminal = binding.check_held(held)
    finally:
        binding.close_held(held)
    assert result.returncode == result.payload_returncode == 0, result
    assert terminal.binding_digest == binding.sealed.operator_binding_digest
    return json.loads(bytes(output).strip().splitlines()[-1]), relay


async def test_refresh_rewrites_in_place_keeps_every_check_and_close_keeps_the_bytes(
    binding, launcher, tmp_path,
):
    held = await hold(binding)
    store = held.store_path
    credential = store / "auth.json"
    inode = credential.stat().st_ino
    checks: list[object] = []
    paths = AcquisitionPaths(tmp_path, acquisition_id_for("n3c-refresh", 1))
    try:
        async with acquisition_guard(paths) as guard:
            def post_probe():
                checks.append(binding.check_held(held))
                return checks[-1]

            with native_mount(binding, held, before_spawn=post_probe) as mount:
                result = await launcher.exchange(
                    ("/usr/bin/python3", "-I", "-c", REFRESH), workspace=None,
                    posture=Posture.READ, guard_fds=(guard, held.lock_fd), timeout_s=10,
                    conversation=collect, native_store=mount,
                )
            assert result.returncode == result.payload_returncode == 0, result
            facts = json.loads(result.stdout)
            assert facts == {"rewritten": True, "replace_errno": errno.EBUSY}, facts
            checks.append(binding.check_held(held))
        expected = binding.sealed.operator_binding_digest
        assert [check.binding_digest for check in checks] == [expected, expected]
        assert credential.stat().st_ino == inode, "the in-place save replaced the inode"
        binding.close_held(held)
        # Cleanup leaves persistent vendor state alone: bytes, not existence.
        assert credential.read_bytes() == REFRESHED
        assert sorted(os.listdir(store)) == ["auth.json"], "the zone reached the store directory"
        write_evidence("n3c-refresh.json", {
            "schema_version": 1, "credential_free_fixture": True,
            "vendor_conformance_qualified": False,
            "in_place_rewrite_kept_inode": True, "rename_over_the_bind_refused": True,
            "post_probe_and_terminal_checks_accepted": True,
            "store_bytes_preserved_after_close": True,
        })
    finally:
        binding.close_held(held)
        credential.write_bytes(CREDENTIAL)


async def test_home_content_widens_neither_the_next_launch_nor_the_zone(
    binding, launcher, pki, short_root, monkeypatch, controlled_loopback,
):
    # The peers are controlled loopback servers, admitted only through N3b's
    # `_routable` seam (`controlled_loopback`), exactly as N3b's own lane does.
    recorded: list[tuple[str, ...]] = []
    original = LinuxLauncher.argv

    def recording(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        recorded.append(tuple(value))
        return value

    monkeypatch.setattr(LinuxLauncher, "argv", recording)
    resolved = refuse_resolution(monkeypatch)
    store = Path(binding.root) / operator_store._bundle_token(KEY) / "store"
    before = sorted(os.listdir(store))
    peers: list[TlsPeer] = []
    unmounted = None
    try:
        allowed, decoy = TlsPeer(pki.server("allowed")), TlsPeer(pki.server("decoy"))
        peers += [allowed, decoy]
        unmounted = unix_listener(str(short_root / "host.sock"))
        policy = policy_for(allowed.port)
        planted, first_relay = await launch(
            launcher, binding, short_root, {"mode": "plant", "helper": HELPER}, policy,
        )
        plan = plan_for(
            pki, allowed, mode="probe", decoy_port=decoy.port, helper=HELPER,
            unmounted=str(short_root / "host.sock"),
            anchor=str(store.parent / "anchor.json"), lock=str(store.parent / "retained.lock"),
        )
        probed, relay = await launch(launcher, binding, short_root, plan, policy)
    finally:
        for peer in peers:
            peer.close()
        if unmounted is not None:
            unmounted.close()

    denied_writes = {errno.EROFS, errno.EACCES, errno.EPERM}
    assert planted["planted"] is True and planted["config_errno"] in denied_writes, planted
    # Each exchange also runs its mount-free probe through argv; compare the launches.
    native = [normalized(argv) for argv in recorded if "CODEX_HOME" in argv]
    assert len(native) == 2 and native[0] == native[1], "home content changed the launch"
    assert probed["survivors"] == [], "planted home content survived the acquisition"
    assert probed["config"] == CONFIGURATION.decode(), "the sealed configuration changed"
    assert probed["home_entries"] == ["auth.json", "config.toml"], probed
    assert sorted(os.listdir(store)) == before == ["auth.json"], "the zone reached the store"
    assert resolved == [("control.invalid", 443)], "the relay resolved a name"
    assert probed["returncode"] == 0 and probed["lines"] == ["helper ran"], probed
    facts = probed["facts"]
    assert facts["workspace_entries"] == []
    assert facts["workspace_write"] in denied_writes and facts["root_write"] in denied_writes
    assert facts["anchor"] == errno.ENOENT and facts["lock"] == errno.ENOENT
    assert facts["tcp"] == errno.ENETUNREACH
    assert facts["host_socket"] == errno.ENOENT
    assert facts["decoy"] == "refused"
    assert facts["allowed"] == "harmless-peer", "the same-run relay control failed"
    assert facts["private_fds"] == []
    assert dict(first_relay.observed) == {}
    observed = {key: value for key, value in relay.observed.items() if key != "reset"}
    assert observed == {"accepted": 1, "denied:destination": 1}
    assert len(allowed.connections) == 1 and allowed.connections[0].handshake
    assert decoy.connections == []
    write_evidence("n3c-persistence.json", {
        "schema_version": 1, "credential_free_fixture": True,
        "vendor_conformance_qualified": False,
        "second_launch_arguments_identical": True, "planted_home_content_absent": True,
        "sealed_configuration_unchanged": True, "store_directory_unchanged": True,
        "probe_ran": True,
        "helper_denials": {key: facts[key] for key in (
            "workspace_write", "root_write", "anchor", "lock", "tcp", "host_socket",
        )},
        "decoy_refused_by_relay": True, "allowed_peer_same_run_control": True,
        "observed": observed,
    })


async def test_the_service_holds_the_lock_but_cannot_withdraw(binding, monkeypatch):
    active = Path(binding.root) / operator_store._bundle_token(KEY) / "active.json"
    before = active.read_bytes()
    acquired: list[bool] = []
    flock = operator_store._flock

    def recording(fd):
        acquired.append(flock(fd))
        return acquired[-1]

    monkeypatch.setattr(operator_store, "_flock", recording)
    with (
        pytest.raises(ContractViolation, match="maintenance is unavailable"),
        operator_store.maintain_offline(binding.root, KEY, wait_s=5),
    ):
        pytest.fail("the service exposed the store through maintenance")
    assert acquired and acquired[-1] is True, "the refusal was not the bundle write"
    assert active.read_bytes() == before
    assert not [name for name in os.listdir(active.parent) if name.startswith(".pending-")]
    held = await hold(binding)
    try:
        assert binding.check_held(held).binding_digest == binding.sealed.operator_binding_digest
    finally:
        binding.close_held(held)
    write_evidence("n3c-service-maintenance.json", {
        "schema_version": 1, "service_took_the_lock": True,
        "withdrawal_refused_for_the_service": True, "selection_bytes_preserved": True,
    })
