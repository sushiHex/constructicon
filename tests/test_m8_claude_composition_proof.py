"""Portable scope/refusal checks; kernel evidence belongs to the hosted lane."""

from __future__ import annotations

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
    assert step.count("scripts/ci/prove_m8_claude_missing.py") == 1
    assert "M8_CLAUDE_COMPOSITION_REQUIRED=1" in step
    assert step.count("</dev/null") == 3
    assert "${{ runner.temp }}/m8-claude-fixture.json" in workflow
    assert "${{ env.M8_EVIDENCE }}/n6-*.json" in workflow
