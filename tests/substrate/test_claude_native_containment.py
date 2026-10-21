"""Mandatory hosted fake-peer proofs; no vendor/account qualification is earned."""

from __future__ import annotations

import errno
import json
import os
import socket
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from constructicon.core.grants import Posture
from constructicon.core.identity import Digest, digest
from constructicon.substrate.executors.claude_native import (
    CLAUDE_PROFILE,
    ClaudeNativeStoreMount,
    ClaudeNativeVendor,
)
from constructicon.substrate.executors.egress import EgressSocket
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessExchangeError
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence

ROOT = Path("/var/lib/constructicon-m8-claude")
POLICY = Path("/etc/apparmor.d/constructicon-m8-claude")
OPERATIONS = ("direct", "shell", "self", "fd", "execveat")
GENERIC_LABEL = "constructicon-m8-launch//&constructicon-m8-workload (enforce)"


@pytest.fixture
def claude_launcher(launcher) -> LinuxLauncher:
    if sys.platform != "linux" or not os.environ.get("M8_CLAUDE_COMPOSITION_REQUIRED"):
        pytest.skip("Claude native physical composition requires its hosted fake fixture")
    assert ROOT.is_dir(), "the required fake composition fixture is missing"
    pins = json.loads((ROOT / "fixture.json").read_text())
    return replace(
        launcher, runtime_root=ROOT / "runtime",
        expected_runtime=Digest(pins["runtime_digest"]), bubblewrap=ROOT / "bwrap",
        policy=POLICY, expected_policy_sha256=pins["policy_sha256"],
        claude=ClaudeNativeVendor(tree=ROOT / "fake-vendor", model="fixture-only", effort="low",
                                  expected_tree=Digest(pins["vendor_digest"])),
    )


@contextmanager
def fake_mount(tmp_path):
    """Real locked fake file and one bounded socket peer, no transport substitute.

    The echo peer proves bridge composition only. Existing sealed-relay tests
    separately prove destination admission; this peer is never called a relay.
    """
    import fcntl

    credential = tmp_path / ".credentials.json"
    credential.write_bytes(b"fake-initial\n")
    credential.chmod(0o600)
    lock = tmp_path / "retained.lock"
    lock_fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    credential_fd = os.open(credential, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    identity = credential.stat().st_dev, credential.stat().st_ino
    received: list[bytes] = []
    failures: list[BaseException] = []
    thread = None
    try:
        # Keep the AF_UNIX name independent of pytest's potentially long paths.
        with tempfile.TemporaryDirectory(prefix="m8-claude-") as directory:
            socket_path = Path(directory) / "peer.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(socket_path))
                listener.listen(1)
                listener.settimeout(15)
                info = socket_path.stat()
                leaf = EgressSocket(socket_path, (info.st_dev, info.st_ino))

                def serve():
                    try:
                        connection, _ = listener.accept()
                        with connection:
                            connection.settimeout(5)
                            value = bytearray()
                            while part := connection.recv(64):
                                value.extend(part)
                                assert len(value) <= 64
                            received.append(bytes(value))
                            assert bytes(value) == b"bridge-ping\n"
                            connection.sendall(b"bridge-pong\n")
                            connection.shutdown(socket.SHUT_WR)
                    except BaseException as exc:
                        failures.append(exc)

                thread = threading.Thread(target=serve, daemon=True)

                def check():
                    assert (credential.stat().st_dev, credential.stat().st_ino) == identity
                    opened = os.fstat(credential_fd)
                    assert (opened.st_dev, opened.st_ino) == identity
                    return BindingCheck(digest("fake-claude-binding", 1, "fixed"))

                mount = ClaudeNativeStoreMount(lock_fd, credential_fd, check, leaf)
                yield mount, credential, received, failures, thread
    finally:
        try:
            if thread is not None and thread.ident is not None:
                thread.join(timeout=20)
                assert not thread.is_alive(), "the fake bridge peer was not joined"
        finally:
            os.close(credential_fd)
            os.close(lock_fd)


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_same_namespace_execution_controls_really_execute(
    claude_launcher, launcher, operation,
):
    launch = replace(launcher, runtime_root=claude_launcher.runtime_root,
                     expected_runtime=claude_launcher.expected_runtime)
    guard = os.memfd_create("fake-claude-control", os.MFD_CLOEXEC)
    try:
        result = await launch.run(
            ("/opt/claude/claude", "--control", operation), workspace=None,
            posture=Posture.READ, guard_fds=(guard,), timeout_s=15,
        )
    finally:
        os.close(guard)
    assert result.returncode == result.payload_returncode == 0, result
    assert result.stdout == f"control-label:{GENERIC_LABEL}\nattempt:{operation}\n".encode()
    assert result.stderr == b""


async def test_same_namespace_parent_child_ptrace_control_really_attaches(
    claude_launcher, launcher,
):
    launch = replace(launcher, runtime_root=claude_launcher.runtime_root,
                     expected_runtime=claude_launcher.expected_runtime)
    guard = os.memfd_create("fake-claude-ptrace-control", os.MFD_CLOEXEC)
    try:
        result = await launch.run(
            ("/opt/claude/claude", "--ptrace-control"), workspace=None,
            posture=Posture.READ, guard_fds=(guard,), timeout_s=15,
        )
    finally:
        os.close(guard)
    assert result.returncode == result.payload_returncode == 0, result
    assert result.stdout == b"child-ptrace:0\n" and result.stderr == b""


async def test_final_transition_noexec_bootstrap_protection_and_fake_persistence(
    claude_launcher, tmp_path,
):
    output = bytearray()
    admitted = []

    async def conversation(io):
        # The launcher admits this callback only after its trusted PID 1's
        # private observation of the exact final label and no_new_privs.
        admitted.append(True)
        await io.write(b"ping\n")
        await io.close_stdin()
        while chunk := await io.read():
            output.extend(chunk)

    with fake_mount(tmp_path) as (mount, credential, received, failures, peer):
        peer.start()
        result = await claude_launcher.exchange(
            claude_launcher.claude.command, workspace=None, posture=Posture.READ,
            guard_fds=(mount.lock_fd,), conversation=conversation, timeout_s=20,
            native_store=mount,
        )
        peer.join(timeout=5)
        assert not peer.is_alive(), "accepting bridge peer did not finish"
        assert failures == [] and received == [b"bridge-ping\n"]
        assert admitted == [True]
        assert result.returncode == result.payload_returncode == 0, result
        assert result.stderr == b"" and bytes(output) == result.stdout
        lines = bytes(output).decode().splitlines()
        facts = dict(line.split(":", 1) for line in lines)
        assert len(facts) == len(lines), "duplicated physical observations"
        # dumpable/Yama checks can return EPERM before AppArmor's EACCES.
        # The same-parent own-child positive control above and exact own-child
        # EACCES below separately prove the native ptrace restriction.
        for name in ("parent-ptrace", "forwarder-ptrace"):
            assert facts[name] in {str(errno.EACCES), str(errno.EPERM)}
        expected = {
            "native-label": CLAUDE_PROFILE, "child-label": CLAUDE_PROFILE,
            "final-label": CLAUDE_PROFILE,
            **{operation: str(errno.EACCES) for operation in OPERATIONS},
            "child-exec": str(errno.EACCES), "child-joined": "1",
            "child-ptrace": str(errno.EACCES),
            "parent-ptrace": facts["parent-ptrace"], "parent-stop": str(errno.EACCES),
            "forwarder-ptrace": facts["forwarder-ptrace"], "forwarder-stop": str(errno.EACCES),
            "workspace-entries": "0", "private-fds": "0",
            "credential-initial": "fake-initial",
            "credential-rename": str(errno.EBUSY),
            "credential-fallback": "written-synced-chmod",
            "policy-write": str(errno.EROFS), "direct-network": str(errno.ENETUNREACH),
            "bridge-exchange": "pong",
        }
        assert facts == expected
        assert credential.read_bytes() == b"fake-refreshed\n"
        assert credential.stat().st_mode & 0o777 == 0o600
        assert sorted(path.name for path in tmp_path.iterdir()) == [
            ".credentials.json", "retained.lock",
        ]
        reloaded = bytearray()

        async def reload(io):
            await io.write(b"reload\n")
            await io.close_stdin()
            while chunk := await io.read():
                reloaded.extend(chunk)

        later = await claude_launcher.exchange(
            claude_launcher.claude.command, workspace=None, posture=Posture.READ,
            guard_fds=(mount.lock_fd,), conversation=reload, timeout_s=15,
            native_store=mount,
        )
        assert later.returncode == later.payload_returncode == 0, later
        assert later.stderr == b""
        assert bytes(reloaded) == later.stdout == (
            f"reload-label:{CLAUDE_PROFILE}\ncredential-reload:fake-refreshed\n".encode()
        )
        write_evidence("n6-claude-native-composition.json", {
            "schema_version": 1, "scope": "fake_physical_native_boundary_only",
            "production_available": False, "claude_qualified": False,
            "launch_revision": str(claude_launcher.revision),
            "trusted_final_transition_gated_conversation": True,
            "fake_peer_report": facts, "fake_credential_persisted": True,
            "later_native_process_reloaded_fake_credential": True,
            "forbidden_sibling_not_persisted": True, "bridge_peer_joined": True,
            "full_read_transaction_proven": False,
        })


async def test_missing_native_profile_refuses_before_conversation(claude_launcher, tmp_path):
    if not os.environ.get("M8_CLAUDE_MISSING_PROFILE_REQUIRED"):
        pytest.skip("explicit root-orchestrated missing-profile phase required")
    admitted = []

    async def conversation(_io):
        admitted.append(True)

    with fake_mount(tmp_path) as (mount, credential, _received, failures, _peer):
        with pytest.raises(ProcessExchangeError) as refused:
            await claude_launcher.exchange(
                claude_launcher.claude.command, workspace=None, posture=Posture.READ,
                guard_fds=(mount.lock_fd,), conversation=conversation, timeout_s=10,
                native_store=mount,
            )
        result = refused.value.result
        assert admitted == [] and failures == []
        assert result.returncode != 0 and result.payload_returncode != 0
        assert b"constructicon egress bridge refused: exec" in result.stderr
        assert credential.read_bytes() == b"fake-initial\n"
