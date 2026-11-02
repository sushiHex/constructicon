"""Hosted fake-only proof of the proposed Claude host runtime closure.

The test substitutes a compiled fake peer for the archive member and current
working-tree blobs for a fetched-main commit. It therefore proves runtime
composition, not the private-host source authority, vendor, or installation.
The workflow owns the fixed root copy, profile load, and exact cleanup.
"""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest
from scripts import claude_host_artifacts as host

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest
from constructicon.substrate.executors.claude_native import (
    CLAUDE_PROFILE,
    MANAGED_MCP,
    ClaudeNativeRecipe,
)
from tests.substrate.test_claude_native_containment import fake_mount
from tests.substrate.test_contained_workspace import context

SOURCE = Path(__file__).resolve().parents[2]
COMMIT = "a" * 40  # Test-only stand-in; prove_sources is substituted below.
WORKSPACE = Path("/var/lib/constructicon-m8-claude-host-proof")
INSTALLED = Path("/var/lib/constructicon-m8-claude")
POLICY = Path("/etc/apparmor.d/constructicon-m8-claude")
ENVIRONMENT = "M8_CLAUDE_HOST_PROOF_REQUIRED"


def _required() -> None:
    if not os.environ.get(ENVIRONMENT):
        pytest.skip("dedicated hosted Claude host proof not requested")
    assert sys.platform == "linux" and os.geteuid() != 0
    assert WORKSPACE.is_dir() and not WORKSPACE.is_symlink()


def _synthetic_archive() -> Path:
    """Compile only the existing fake C peer; never read or run vendor bytes."""
    peer = WORKSPACE / "fake-claude"
    result = subprocess.run(
        ["/usr/bin/cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
         str(SOURCE / "scripts/ci/m8_claude_peer.c"), "-o", str(peer)],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=30,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    assert result.returncode == 0, "fixed fake-peer compilation failed"
    archive = WORKSPACE / host.ARCHIVE
    with tarfile.open(archive, "w:gz") as package:
        payload = peer.read_bytes()
        member = tarfile.TarInfo(host.MEMBER)
        member.size = len(payload)
        member.mode = 0o555
        package.addfile(member, io.BytesIO(payload))
    return archive


def _test_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    archive = WORKSPACE / host.ARCHIVE
    with tarfile.open(archive, "r:gz") as package:
        member = package.getmember(host.MEMBER)
        stream = package.extractfile(member)
        assert stream is not None
        payload = stream.read()
    monkeypatch.setattr(host, "ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    monkeypatch.setattr(host, "MEMBER_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(host, "MEMBER_SIZE", len(payload))

    def current_blobs(commit: str, workspace: Path) -> dict[str, bytes]:
        assert commit == COMMIT and workspace == WORKSPACE
        return {name: (SOURCE / name).read_bytes() for name in host.SOURCE_BLOBS}

    monkeypatch.setattr(host, "prove_sources", current_blobs)


def _selection() -> bytes:
    return (json.dumps({
        "schema_version": 1, "model": "fixture-only", "effort": "low",
        "egress": {
            "login": {"destinations": [["platform.claude.com", 443, "8.8.8.8"]],
                      "connections": 1},
            "observe": {"destinations": [["platform.claude.com", 443, "8.8.8.8"],
                                         ["api.anthropic.com", 443, "1.1.1.1"]],
                        "connections": 2},
            "reload": {"destinations": [["platform.claude.com", 443, "8.8.8.8"],
                                        ["api.anthropic.com", 443, "1.1.1.1"]],
                       "connections": 2},
        },
    }, sort_keys=True) + "\n").encode()


def _profile_snapshot(name: str) -> str:
    with (WORKSPACE / name).open("rb") as source:
        raw = source.read(1 << 20)
        assert not source.read(1)
    assert raw
    return raw.decode("utf-8")


def test_stage_and_judge_synthetic_host_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _required()
    assert not INSTALLED.exists() and not INSTALLED.is_symlink()
    assert not POLICY.exists() and not POLICY.is_symlink()
    assert not (WORKSPACE / host.STAGING).exists()
    (WORKSPACE / host.REPOSITORY).mkdir(mode=0o700)
    (WORKSPACE / host.SELECTION).write_bytes(_selection())
    _synthetic_archive()
    _test_pins(monkeypatch)
    staged = host.stage(COMMIT, WORKSPACE)
    assert staged["staged"] is True
    config_sha256 = staged["launch_config_sha256"]
    profiles = _profile_snapshot("profiles-before")
    assert host.judge(COMMIT, WORKSPACE, expected_sha256="0" * 64,
                      profile_list=profiles) == {"ready": False}
    judged = host.judge(COMMIT, WORKSPACE, expected_sha256=config_sha256,
                        profile_list=profiles)
    assert judged["ready"] is True
    assert judged["runtime_digest"] == staged["runtime_digest"]
    assert judged["vendor_digest"] == staged["vendor_digest"]
    assert judged["policy_sha256"] == staged["policy_sha256"]
    # Test-only handoff for the fixed stock-tool copy and independent verify.
    (WORKSPACE / "proof-pins.json").write_text(json.dumps(staged, sort_keys=True) + "\n")


@pytest.mark.asyncio
async def test_verified_install_launches_joined_fake_peer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _required()
    _test_pins(monkeypatch)
    assert not (WORKSPACE / host.STAGING).exists()
    assert (WORKSPACE / "staging-retired").is_dir()
    staged = json.loads((WORKSPACE / "proof-pins.json").read_text())
    profiles = _profile_snapshot("profiles-after")
    verified = host.verify(
        COMMIT, WORKSPACE, expected_sha256=staged["launch_config_sha256"],
        profile_list=profiles,
    )
    assert verified["installed"] is True
    assert verified["runtime_digest"] == staged["runtime_digest"]
    assert verified["vendor_digest"] == staged["vendor_digest"]
    assert verified["policy_sha256"] == staged["policy_sha256"]
    # Import only after the hosted prerequisite: this branch can run portable
    # tests before the independently reviewed lane consumer is merged.
    from constructicon.substrate.executors.claude_lane import read_configuration
    from constructicon.substrate.executors.claude_maintenance_session import (
        ClaudeMaintenanceSessionPhase,
    )
    configuration = read_configuration(
        INSTALLED / "launch-config.json",
        expected_sha256=staged["launch_config_sha256"],
    )
    assert configuration.launch_root == INSTALLED
    assert configuration.runtime_digest == Digest(staged["runtime_digest"])
    assert configuration.vendor_digest == Digest(staged["vendor_digest"])
    assert configuration.launch_policy == POLICY
    assert configuration.launch_policy_sha256 == staged["policy_sha256"]
    launcher = configuration.launcher(ClaudeMaintenanceSessionPhase.OBSERVE)
    assert launcher.claude_recipe is ClaudeNativeRecipe.STREAM_JSON
    vendor = launcher.claude
    assert vendor is not None
    assert vendor.tree == INSTALLED / "vendor"
    assert vendor.expected_tree == Digest(staged["vendor_digest"])
    output = bytearray()
    admitted = False

    async def conversation(io: object) -> None:
        nonlocal admitted
        admitted = True
        policy = ClaudeNativeRecipe.STREAM_JSON.policy
        await io.write(b"ping\n" + json.dumps(policy, sort_keys=True).encode()
                       + b"\n" + MANAGED_MCP)
        await io.close_stdin()
        while chunk := await io.read():
            output.extend(chunk)

    with fake_mount(tmp_path) as (mount, credential, received, failures, peer):
        peer.start()
        result = await launcher.exchange(
            launcher.claude.command,
            workspace=None, posture=Posture.READ,
            guard_fds=(mount.lock_fd,), conversation=conversation,
            timeout_s=20, native_store=mount,
        )
        peer.join(timeout=5)
        assert not peer.is_alive() and failures == []
        assert received == [b"bridge-ping\n"]
        assert admitted and result.returncode == result.payload_returncode == 0
        assert result.stderr == b"" and bytes(output) == result.stdout
        assert b"policy-content:exact\n" in result.stdout
        assert b"mcp-content:exact\n" in result.stdout
        assert b"policy-canonical:linked-0600-reopened\n" in result.stdout
        assert b"mcp-canonical:linked-0600-reopened\n" in result.stdout
        assert b"policy-canonical-path:exact\n" in result.stdout
        assert b"mcp-canonical-path:exact\n" in result.stdout
        assert f"final-label:{CLAUDE_PROFILE}\n".encode() in result.stdout
        assert f"git:{errno.EACCES}\n".encode() in result.stdout
        assert credential.read_bytes() == b"fake-refreshed\n"
    await _write_population(configuration)
    # The installed artifact and proof scope are physical; the archive member
    # remains synthetic and says nothing about vendor authentication.


async def _write_population(configuration, missing=None):
    """Real resource assembly, acquire, populate, Git checkout and discard.

    Only fixture admission/control is test-owned; no launcher/process/populate
    result is substituted. The installed archive contains the synthetic peer.
    """
    from constructicon.api import _qualification_write_assembly as assembly
    from constructicon.substrate.executors.linux import LinuxLauncher, LinuxLaunchProfile
    from constructicon.substrate.journal.sqlite import SqliteJournal

    suffix = missing or "accepted"
    fixture = WORKSPACE / ("write-fixture-" + suffix)
    assembly.prepare_fixture(fixture)
    launcher = LinuxLauncher(
        runtime_root=configuration.launch_root / "runtime",
        expected_runtime=configuration.runtime_digest,
        bubblewrap=configuration.launch_root / "bwrap", policy=configuration.launch_policy,
        expected_policy_sha256=configuration.launch_policy_sha256,
        launch_profile=LinuxLaunchProfile.CLAUDE_BOOTSTRAP,
    )
    if missing:
        original = (SOURCE / "scripts/constructicon-m8-claude.apparmor").read_bytes()
        rule = b"  allow ix /usr/bin/git,\n"
        components = original.split(b"profile constructicon-m8-claude-")
        for index, component in enumerate(components):
            if component.startswith(missing.encode() + b" "):
                components[index] = component.replace(rule, b"")
        expected = b"profile constructicon-m8-claude-".join(components)
        assert POLICY.read_bytes() == expected and expected != original
        launcher = replace(launcher, expected_policy_sha256=hashlib.sha256(expected).hexdigest())
    assert launcher.effective_profile is LinuxLaunchProfile.CLAUDE_BOOTSTRAP
    journal = SqliteJournal(WORKSPACE / ("write-" + suffix + ".sqlite"))
    resources = await assembly.assemble_contained_write(fixture, journal, launcher)
    workspace = resources.workspace
    ctx = context(posture=Posture.WRITE, run_id="claude-git-" + suffix)
    ctx = replace(ctx, binding=replace(ctx.binding, revision=str(workspace.revision),
                                      capability_id=assembly.WORKSPACE_CAPABILITY),
                  check_control=lambda: None)
    acquired = await workspace.acquire(ctx)
    try:
        if missing:
            with pytest.raises(ContractViolation, match="contained staging initialization failed"):
                await acquired.materialize()
            assert not acquired.resource.ready
        else:
            await acquired.materialize()
            assert acquired.resource.ready
            async with acquired.resource.use() as guard:
                result = await launcher.run(
                    ("/usr/bin/python3", "-I", "-c", "import subprocess;"
                     "subprocess.run(['/usr/bin/git','rev-parse','--verify','HEAD'],check=True)"),
                    workspace=Path(acquired.resource.path), posture=Posture.WRITE,
                    guard_fds=(guard,), timeout_s=20,
                )
            assert result.returncode == result.payload_returncode == 0, result
            assert result.stdout.strip().decode() == resources.fixture.base_commit
            assert sorted(p.name for p in Path(acquired.resource.path).iterdir()) == [".git"]
    finally:
        closed = await workspace.close(acquired, "discard")
        assert closed.disposition == "discarded" and not Path(acquired.resource.path).exists()
    assert resources.authority.resolve_ref(assembly.TARGET) == resources.fixture.base_commit


async def test_missing_git_rule_refuses_real_write_population():
    _required()
    from constructicon.substrate.executors.claude_lane import read_configuration

    missing = os.environ["M8_CLAUDE_GIT_RULE_MISSING"]
    assert missing in ("launch", "bootstrap")
    pins = json.loads((WORKSPACE / "proof-pins.json").read_text())
    configuration = read_configuration(INSTALLED / "launch-config.json",
                                       expected_sha256=pins["launch_config_sha256"])
    await _write_population(configuration, missing)
