"""Portable scope/refusal checks; kernel evidence belongs to the hosted lane."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from scripts.ci import build_m8_claude_fixture as fixture
from scripts.ci import prove_m8_claude_missing as missing

from constructicon.substrate.executors.claude_native import CLAUDE_PROFILE


def test_native_exec_stack_retains_both_existing_components_without_fallback():
    root = Path(__file__).resolve().parents[1]
    policy = (root / "scripts/ci/constructicon-m8-claude.apparmor").read_text()
    target = ("constructicon-m8-claude-launch//&constructicon-m8-claude-bootstrap"
              "//&constructicon-m8-claude-native")
    assert policy.count(f"allow px /opt/claude/claude -> {target},") == 2
    assert "allow ix /usr/bin/python3{,.12}," in policy
    assert "allow ix /**" not in policy
    native = policy.split("profile constructicon-m8-claude-native flags=", 1)[1]
    assert "deny x /**," in native
    assert "deny ptrace (read, trace)," in native
    assert "allow ptrace (readby)," in native
    assert "allow signal (receive)," in native
    assert f"allow signal (send) peer={CLAUDE_PROFILE.removesuffix(' (enforce)')}," in native
    assert not any(fallback in policy for fallback in ("pux", "pix", " ux "))
    assert CLAUDE_PROFILE == (
        "constructicon-m8-claude-bootstrap//&constructicon-m8-claude-launch"
        "//&constructicon-m8-claude-native (enforce)"
    )


@pytest.mark.parametrize("operation", [fixture.build, missing.prove])
def test_provisioning_and_profile_mutation_refuse_unsupported_hosts(monkeypatch, operation):
    monkeypatch.setattr(sys, "argv", ["proof"])
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ValueError, match="requires the disposable hosted CI runner"):
        operation()


def test_physical_proof_has_one_mandatory_hosted_route_and_retained_evidence():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/m8-containment.yml").read_text()
    step = workflow.split(
        "- name: Prove the fake Claude native final transition and bounded layout", 1,
    )[1].split("- name:", 1)[0]
    assert "if: matrix.lane == 'foundation'" in step
    assert step.count("scripts/ci/build_m8_claude_fixture.py") == 1
    assert step.count("tests/substrate/test_claude_native_containment.py") == 1
    assert step.count("tests/substrate/test_claude_native_read.py") == 1
    assert step.count("scripts/ci/prove_m8_claude_missing.py") == 1
    assert "M8_CLAUDE_COMPOSITION_REQUIRED=1" in step
    assert step.count("</dev/null") == 3
    assert "${{ runner.temp }}/m8-claude-fixture.json" in workflow
    assert "${{ env.M8_EVIDENCE }}/n6-*.json" in workflow


def test_builder_preserves_executable_control_copies(monkeypatch, tmp_path):
    """Run actual copying/freezing; substitute host provisioning primitives only."""
    root = tmp_path / "fixture"
    base = tmp_path / "base"
    policy = tmp_path / "policy"
    original_stat, original_lstat = Path.stat, Path.lstat
    original_chmod, original_read = Path.chmod, Path.read_text
    original_copy = fixture.shutil.copyfile
    modes = {}

    def chmod(path, mode, *args, **kwargs):
        modes[path] = mode
        original_chmod(path, mode, *args, **kwargs)

    def metadata(path, original, *args, **kwargs):
        observed = original(path, *args, **kwargs)
        values = list(observed)
        values[4] = 0  # Hosted provisioning runs as root.
        if path == base / "runtime":
            # Root can populate a copied read-only directory. Let the actual
            # unprivileged copy remain writable while reporting its host mode.
            values[0] = (values[0] & ~0o7777) | 0o555
        elif os.name == "nt" and path in modes:
            # Windows chmod does not implement Linux executable permission bits.
            values[0] = (values[0] & ~0o7777) | modes[path]
        return os.stat_result(values)

    monkeypatch.setattr(Path, "chmod", chmod)
    monkeypatch.setattr(Path, "stat", lambda path, *a, **kw:
                        metadata(path, original_stat, *a, **kw))
    monkeypatch.setattr(Path, "lstat", lambda path, *a, **kw:
                        metadata(path, original_lstat, *a, **kw))
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **kw:
                        "" if path == Path("/sys/kernel/security/apparmor/profiles")
                        else original_read(path, *a, **kw))
    base.mkdir()
    (base / "runtime").mkdir()
    (base / "bwrap").write_bytes(b"fixed bubblewrap substitute")
    shell = tmp_path / "shell-source"
    shell.write_bytes(b"fixed shell substitute")
    shell.chmod(0o555)

    def copy(source, destination, **kwargs):
        return original_copy(shell if str(source) == "/bin/sh" else source,
                             destination, **kwargs)

    def checked(argv):
        if argv[0] == "/usr/bin/cc":
            Path(argv[-1]).write_bytes(b"compiled fixed peer substitute")
        else:
            assert argv[:3] == ["/usr/sbin/apparmor_parser", "--add", "--skip-cache"]

    monkeypatch.setattr(fixture, "ROOT", root)
    monkeypatch.setattr(fixture, "BASE", base)
    monkeypatch.setattr(fixture, "POLICY", policy)
    monkeypatch.setattr(fixture.shutil, "copyfile", copy)
    monkeypatch.setattr(fixture, "checked", checked)
    monkeypatch.setattr(sys, "argv", ["proof"])
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    report = fixture.build()
    for name in ("opt/claude/claude", "bin/sh"):
        assert (root / "runtime" / name).stat().st_mode & 0o777 == 0o555
    assert (root / "runtime/opt/claude/claude").read_bytes() == (
        root / "fake-vendor/claude"
    ).read_bytes()
    assert (root / "runtime/bin/sh").read_bytes() == shell.read_bytes()
    assert report["scope"] == "fake_native_composition_fixture"
