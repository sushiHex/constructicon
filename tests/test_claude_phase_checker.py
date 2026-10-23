"""Credential-free positive and refusal checks for the repo-owned CLI."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from constructicon.core.identity import digest
from constructicon.substrate.executors import claude_lane
from constructicon.substrate.executors.claude_maintenance_mode import (
    ClaudeMaintenanceRefusalCode,
)
from constructicon.substrate.executors.claude_maintenance_session import (
    ClaudeMaintenanceSessionPhase,
)
from constructicon.substrate.executors.claude_protocol import ClaudePlan
from tests.substrate.test_claude_lane import configuration, facts

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_claude_phase.py"
SPEC = importlib.util.spec_from_file_location("check_claude_phase", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def sample(tmp_path: Path, phase: ClaudeMaintenanceSessionPhase) -> tuple[Path, Path, object]:
    config = configuration(tmp_path)
    loaded = claude_lane.read_configuration(
        config, expected_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
    )
    selection = None if phase is ClaudeMaintenanceSessionPhase.LOGIN else ClaudePlan.MAX
    launcher = loaded.launcher(phase)
    observed = facts(phase)
    if observed.mode_observation is not None:
        observed = replace(observed, mode_observation=replace(
            observed.mode_observation, classified_responses=1,
        ))
    record = claude_lane._record(
        observed, launcher, loaded.egress["observe" if phase is
                                  ClaudeMaintenanceSessionPhase.QUALIFY else phase.value],
        loaded, selected_plan=selection,
    )
    record["completed"] = True
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
    return config, evidence, loaded


def refused(tmp_path: Path, code: str | None = "partial-record") -> tuple[Path, Path, object]:
    config, evidence, loaded = sample(tmp_path, ClaudeMaintenanceSessionPhase.OBSERVE)
    record = json.loads(evidence.read_text(encoding="utf-8"))
    record["facts"]["lifecycle"] = "refused"
    mode = record["facts"]["mode"]
    mode.update(mode_verdict="mode-mismatch", mode_mismatch_reason="ambiguous-api",
                classified_responses=1, request_writes=1, ui_records=0,
                lifecycle="refused", stdin_closed=False, eof=False, refusal_code=code)
    evidence.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
    return config, evidence, loaded


def cli(
    config: Path, evidence: Path, phase: str, *extra: str,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", "-B", str(SCRIPT), "--phase", phase,
         "--evidence", str(evidence), "--config", str(config),
         "--config-sha256", hashlib.sha256(config.read_bytes()).hexdigest(), *extra],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=30,
    )


@pytest.mark.parametrize("phase", list(ClaudeMaintenanceSessionPhase))
def test_real_subprocess_positive_cli_only_prints_digest(tmp_path: Path, phase):
    config, evidence, loaded = sample(tmp_path, phase)
    extra = () if phase is ClaudeMaintenanceSessionPhase.LOGIN else ("--selected-plan", "max")
    result = cli(config, evidence, phase.value, *extra)
    assert result.returncode == 0 and result.stderr == b""
    assert result.stdout.splitlines() == [str(digest(
        claude_lane.EVIDENCE_DOMAIN, 1, json.loads(evidence.read_text()),
    )).encode()]
    assert checker.validate_phase_evidence(
        phase, evidence, loaded, None if phase is ClaudeMaintenanceSessionPhase.LOGIN
        else ClaudePlan.MAX,
    )


@pytest.mark.parametrize("code", ["partial-record", None])
def test_refusal_cli_is_bounded_diagnostic_never_positive(tmp_path: Path, code):
    config, evidence, loaded = refused(tmp_path, code)
    result = cli(config, evidence, "observe", "--selected-plan", "max",
                 "--diagnose-refusal")
    assert result.returncode == 0 and result.stderr == b""
    diagnostic = json.loads(result.stdout)
    assert set(diagnostic) == {"mode_verdict", "reason", "refusal_code", "classified_responses",
                               "request_writes", "ui_records", "evidence_digest"}
    assert diagnostic["mode_verdict"] == "mode-mismatch"
    assert diagnostic["reason"] == "ambiguous-api" and diagnostic["refusal_code"] == code
    assert diagnostic["classified_responses"] == diagnostic["request_writes"] == 1
    assert diagnostic["ui_records"] == 0
    assert diagnostic["evidence_digest"] == str(digest(
        claude_lane.EVIDENCE_DOMAIN, 1, json.loads(evidence.read_text()),
    ))
    observed = checker.diagnose_refused_mode(
        ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudePlan.MAX,
    )
    assert (None if observed.refusal_code is None else observed.refusal_code.value) == code
    positive = cli(config, evidence, "observe", "--selected-plan", "max")
    assert positive.returncode == 1 and positive.stdout == b""


@pytest.mark.parametrize(
    ("verdict", "reason", "classified", "writes", "code"),
    [
        (None, None, 0, 1, "read-error"),
        ("mode-match", None, 1, 1, "partial-record"),
        (None, None, 0, 0, None),
    ],
)
def test_generic_observer_refusal_before_or_after_classification(
    tmp_path: Path, verdict, reason, classified, writes, code,
):
    config, evidence, loaded = refused(tmp_path)
    record = json.loads(evidence.read_text(encoding="utf-8"))
    mode = record["facts"]["mode"]
    mode.update(mode_verdict=verdict, mode_mismatch_reason=reason,
                classified_responses=classified, request_writes=writes,
                refusal_code=code)
    evidence.write_text(json.dumps(record), encoding="utf-8")
    diagnostic = checker.diagnose_refused_mode(
        ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudePlan.MAX,
    )
    assert (None if diagnostic.mode_verdict is None else diagnostic.mode_verdict.value) == verdict
    assert diagnostic.reason is None
    assert (None if diagnostic.refusal_code is None else diagnostic.refusal_code.value) == code
    assert diagnostic.classified_responses == classified
    assert diagnostic.request_writes == writes
    result = cli(config, evidence, "observe", "--selected-plan", "max",
                 "--diagnose-refusal")
    assert result.returncode == 0 and result.stderr == b""
    published = json.loads(result.stdout)
    assert published["mode_verdict"] == verdict
    assert published["reason"] is None and published["refusal_code"] == code
    positive = cli(config, evidence, "observe", "--selected-plan", "max")
    assert positive.returncode == 1 and positive.stdout == b""


@pytest.mark.parametrize(
    ("verdict", "reason", "classified"),
    [(None, None, 1), ("mode-match", "ambiguous-api", 1),
     ("private-sentinel", None, 1)],
)
def test_generic_diagnostic_rejects_inconsistent_classification(
    tmp_path: Path, verdict, reason, classified,
):
    config, evidence, _ = refused(tmp_path)
    record = json.loads(evidence.read_text(encoding="utf-8"))
    record["facts"]["mode"].update(
        mode_verdict=verdict, mode_mismatch_reason=reason,
        classified_responses=classified,
    )
    evidence.write_text(json.dumps(record), encoding="utf-8")
    result = cli(config, evidence, "observe", "--selected-plan", "max",
                 "--diagnose-refusal")
    assert result.returncode == 1 and result.stdout == b""


@pytest.mark.parametrize("code", list(ClaudeMaintenanceRefusalCode))
def test_each_refusal_code_is_closed_and_never_a_positive_receipt(tmp_path: Path, code):
    _, evidence, loaded = refused(tmp_path, code.value)
    observed = checker.diagnose_refused_mode(
        ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudePlan.MAX,
    )
    assert observed.refusal_code is code
    with pytest.raises(checker._Refused):
        checker.validate_phase_evidence(
            ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudePlan.MAX,
        )


def test_diagnostic_switch_cannot_approve_positive(tmp_path: Path):
    config, evidence, _ = sample(tmp_path, ClaudeMaintenanceSessionPhase.OBSERVE)
    result = cli(config, evidence, "observe", "--selected-plan", "max",
                 "--diagnose-refusal")
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr.splitlines() == [b"Claude phase evidence refused"]


def test_positive_mode_with_refusal_code_cannot_publish(tmp_path: Path):
    config, evidence, _ = sample(tmp_path, ClaudeMaintenanceSessionPhase.OBSERVE)
    record = json.loads(evidence.read_text())
    record["facts"]["mode"]["refusal_code"] = "partial-record"
    evidence.write_text(json.dumps(record), encoding="utf-8")
    result = cli(config, evidence, "observe", "--selected-plan", "max")
    assert result.returncode == 1 and result.stdout == b""


@pytest.mark.parametrize("damage", ["schema2", "missing-code", "unknown-code", "extra",
                                    "bad-count", "bad-identity"])
def test_refusal_rejects_old_or_unbounded_or_wrong_identity(tmp_path: Path, damage: str):
    config, evidence, _ = refused(tmp_path)
    record = json.loads(evidence.read_text())
    mode = record["facts"]["mode"]
    if damage == "schema2":
        record["schema_version"] = 2
    elif damage == "missing-code":
        del mode["refusal_code"]
    elif damage == "unknown-code":
        mode["refusal_code"] = "private-sentinel"
    elif damage == "extra":
        mode["private-sentinel"] = "secret"
    elif damage == "bad-count":
        mode["classified_responses"] = 3
    else:
        record["launch_revision"] = "private-sentinel"
    evidence.write_text(json.dumps(record), encoding="utf-8")
    result = cli(config, evidence, "observe", "--selected-plan", "max",
                 "--diagnose-refusal")
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr.splitlines() == [b"Claude phase evidence refused"]
    assert b"private-sentinel" not in result.stderr


def test_cli_rejects_missing_or_wrong_selected_plan(tmp_path: Path):
    config, evidence, _ = sample(tmp_path, ClaudeMaintenanceSessionPhase.OBSERVE)
    for extra in ((), ("--selected-plan", "pro"), ("--selected-plan", "max", "--other")):
        result = cli(config, evidence, "observe", *extra)
        if extra == ("--selected-plan", "pro"):
            # Observe has no plan attestation in the record; the reviewed command owns it.
            assert result.returncode == 0
        else:
            assert result.returncode == 1 and result.stdout == b""
