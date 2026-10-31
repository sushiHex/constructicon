"""Credential-free positive and refusal checks for the repo-owned CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from scripts import check_claude_phase as checker

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.substrate.executors import claude_lane
from constructicon.substrate.executors.claude_maintenance_mode import (
    ClaudeMaintenanceRefusalCode,
)
from constructicon.substrate.executors.claude_maintenance_session import (
    ClaudeMaintenanceSessionPhase,
)
from constructicon.substrate.executors.claude_native_events import ClaudeSystemRecordCategory
from constructicon.substrate.executors.claude_protocol import ClaudeAuthMode
from tests.substrate.test_claude_lane import configuration, facts

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_claude_phase.py"


def sample(tmp_path: Path, phase: ClaudeMaintenanceSessionPhase) -> tuple[Path, Path, object]:
    config = configuration(tmp_path)
    loaded = claude_lane.read_configuration(
        config, expected_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
    )
    selection = (None if phase is ClaudeMaintenanceSessionPhase.LOGIN
                 else ClaudeAuthMode.SUBSCRIPTION)
    launcher = loaded.launcher(phase)
    observed = facts(phase)
    if observed.mode_observation is not None:
        observed = replace(observed, mode_observation=replace(
            observed.mode_observation, classified_responses=1,
        ))
    record = claude_lane._record(
        observed, launcher, loaded.egress["observe" if phase is
                                  ClaudeMaintenanceSessionPhase.QUALIFY else phase.value],
        loaded, mode=selection,
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
                lifecycle="refused", stdin_closed=False, eof=False, refusal_code=code,
                rejected_system_category="other" if code == "ui-record" else None)
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
    extra = () if phase is ClaudeMaintenanceSessionPhase.LOGIN else ("--mode", "subscription")
    result = cli(config, evidence, phase.value, *extra)
    assert result.returncode == 0 and result.stderr == b""
    assert result.stdout.splitlines() == [str(digest(
        claude_lane.EVIDENCE_DOMAIN, 1, json.loads(evidence.read_text()),
    )).encode()]
    assert checker.validate_phase_evidence(
        phase, evidence, loaded, None if phase is ClaudeMaintenanceSessionPhase.LOGIN
        else ClaudeAuthMode.SUBSCRIPTION,
    )


@pytest.mark.parametrize("code", ["partial-record", None])
def test_refusal_cli_is_bounded_diagnostic_never_positive(tmp_path: Path, code):
    config, evidence, loaded = refused(tmp_path, code)
    result = cli(config, evidence, "observe", "--mode", "subscription",
                 "--diagnose-refusal")
    assert result.returncode == 0 and result.stderr == b""
    diagnostic = json.loads(result.stdout)
    assert set(diagnostic) == {"mode_verdict", "reason", "refusal_code", "classified_responses",
                               "request_writes", "ui_records", "evidence_digest",
                               "token_source_category", "api_key_source_category",
                               "rejected_system_category"}
    assert diagnostic["mode_verdict"] == "mode-mismatch"
    assert diagnostic["reason"] == "ambiguous-api" and diagnostic["refusal_code"] == code
    assert diagnostic["classified_responses"] == diagnostic["request_writes"] == 1
    assert diagnostic["ui_records"] == 0
    assert diagnostic["rejected_system_category"] is None
    assert diagnostic["evidence_digest"] == str(digest(
        claude_lane.EVIDENCE_DOMAIN, 1, json.loads(evidence.read_text()),
    ))
    observed = checker.diagnose_refused_mode(
        ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION,
    )
    assert (None if observed.refusal_code is None else observed.refusal_code.value) == code
    positive = cli(config, evidence, "observe", "--mode", "subscription")
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
                refusal_code=code,
                token_source_category=("absent" if verdict == "mode-match" else None),
                api_key_source_category=("absent" if verdict == "mode-match" else None))
    evidence.write_text(json.dumps(record), encoding="utf-8")
    diagnostic = checker.diagnose_refused_mode(
        ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION,
    )
    assert (None if diagnostic.mode_verdict is None else diagnostic.mode_verdict.value) == verdict
    assert diagnostic.reason is None
    assert (None if diagnostic.refusal_code is None else diagnostic.refusal_code.value) == code
    assert diagnostic.classified_responses == classified
    assert diagnostic.request_writes == writes
    result = cli(config, evidence, "observe", "--mode", "subscription",
                 "--diagnose-refusal")
    assert result.returncode == 0 and result.stderr == b""
    published = json.loads(result.stdout)
    assert published["mode_verdict"] == verdict
    assert published["reason"] is None and published["refusal_code"] == code
    positive = cli(config, evidence, "observe", "--mode", "subscription")
    assert positive.returncode == 1 and positive.stdout == b""


@pytest.mark.parametrize(
    ("verdict", "reason", "classified"),
    [(None, None, 1), ("mode-match", "ambiguous-api", 1),
     ("mode-mismatch", None, 1),
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
    result = cli(config, evidence, "observe", "--mode", "subscription",
                 "--diagnose-refusal")
    assert result.returncode == 1 and result.stdout == b""


@pytest.mark.parametrize("code", list(ClaudeMaintenanceRefusalCode))
def test_each_refusal_code_is_closed_and_never_a_positive_receipt(tmp_path: Path, code):
    _, evidence, loaded = refused(tmp_path, code.value)
    observed = checker.diagnose_refused_mode(
        ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION,
    )
    assert observed.refusal_code is code
    with pytest.raises(checker._Refused):
        checker.validate_phase_evidence(
            ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION,
        )


def test_diagnostic_switch_cannot_approve_positive(tmp_path: Path):
    config, evidence, _ = sample(tmp_path, ClaudeMaintenanceSessionPhase.OBSERVE)
    result = cli(config, evidence, "observe", "--mode", "subscription",
                 "--diagnose-refusal")
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr.splitlines() == [b"Claude phase evidence refused"]


def test_positive_mode_with_refusal_code_cannot_publish(tmp_path: Path):
    config, evidence, _ = sample(tmp_path, ClaudeMaintenanceSessionPhase.OBSERVE)
    record = json.loads(evidence.read_text())
    record["facts"]["mode"]["refusal_code"] = "partial-record"
    evidence.write_text(json.dumps(record), encoding="utf-8")
    result = cli(config, evidence, "observe", "--mode", "subscription")
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
    result = cli(config, evidence, "observe", "--mode", "subscription",
                 "--diagnose-refusal")
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr.splitlines() == [b"Claude phase evidence refused"]
    assert b"private-sentinel" not in result.stderr


def test_cli_rejects_missing_or_wrong_mode(tmp_path: Path):
    config, evidence, _ = sample(tmp_path, ClaudeMaintenanceSessionPhase.OBSERVE)
    for extra in ((), ("--selected-plan", "pro"), ("--mode", "pro"),
                  ("--mode", "subscription"), ("--mode", "subscription", "--other")):
        result = cli(config, evidence, "observe", *extra)
        if extra == ("--mode", "subscription"):
            # Observe has no plan attestation in the record; the reviewed command owns it.
            assert result.returncode == 0
        else:
            assert result.returncode == 1 and result.stdout == b""


def refused_qualification(tmp_path, reason="effort-mismatch", process_clean=True):
    config, evidence, loaded = sample(tmp_path, ClaudeMaintenanceSessionPhase.QUALIFY)
    record = json.loads(evidence.read_bytes())
    record["facts"].update(lifecycle="refused", process_clean=process_clean)
    record["facts"]["qualification"].update(
        lifecycle="refused", settings_verdict="configuration-mismatch",
        settings_mismatch_reason=reason, hooks_verdict=None,
        request_writes=2, stdin_closed=False, eof=False,
    )
    evidence.write_text(json.dumps(record), encoding="utf-8")
    return config, evidence, loaded


@pytest.mark.parametrize("reason", list(checker.ClaudeSettingsMismatchReason))
@pytest.mark.parametrize("process_clean", [True, False])
def test_refused_qualification_cli_is_finite_and_never_positive(tmp_path, reason, process_clean):
    config, evidence, loaded = refused_qualification(tmp_path, reason.value, process_clean)
    result = cli(config, evidence, "qualify", "--mode", "subscription", "--diagnose-refusal")
    assert result.returncode == 0 and result.stderr == b""
    assert json.loads(result.stdout) == {
        "settings_verdict": "configuration-mismatch", "reason": reason.value,
        "initialize_verdict": "mode-match", "mode_mismatch_reason": None,
        "token_source_category": "absent", "api_key_source_category": "absent",
        "process_clean": process_clean,
        "evidence_digest": str(digest(claude_lane.EVIDENCE_DOMAIN, 1,
                                      json.loads(evidence.read_bytes()))),
    }
    with pytest.raises(ContractViolation):
        checker.validate_phase_evidence(
            ClaudeMaintenanceSessionPhase.QUALIFY, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION,
        )
    positive = cli(config, evidence, "qualify", "--mode", "subscription")
    assert positive.returncode == 1 and positive.stdout == b""


@pytest.mark.parametrize("damage", [
    "schema3", "missing-reason", "unknown-reason", "null-reason", "reason-with-match",
    "unknown-verdict", "no-cleanup", "no-custody", "credential-open", "process-unknown",
    "bad-source-revision", "bad-identity", "bad-count", "missing-initialize", "wrong-plan",
    "extra", "positive",
])
def test_qualification_diagnostic_requires_closed_current_consistent_evidence(tmp_path, damage):
    config, evidence, _ = refused_qualification(tmp_path)
    record = json.loads(evidence.read_bytes())
    facts = record["facts"]
    qualification = facts["qualification"]
    if damage == "schema3":
        record["schema_version"] = 3
    elif damage == "missing-reason":
        del qualification["settings_mismatch_reason"]
    elif damage == "unknown-reason":
        qualification["settings_mismatch_reason"] = "private-sentinel"
    elif damage == "null-reason":
        qualification["settings_mismatch_reason"] = None
    elif damage == "reason-with-match":
        qualification["settings_verdict"] = "match"
    elif damage == "unknown-verdict":
        qualification["settings_verdict"] = "private-sentinel"
    elif damage == "no-cleanup":
        facts["relay_closed"] = False
    elif damage == "no-custody":
        facts["custody_current"] = False
    elif damage == "credential-open":
        facts["credential_closed"] = False
    elif damage == "process-unknown":
        facts["process_clean"] = None
    elif damage == "bad-source-revision":
        record["qualification_revision"] = "private-sentinel"
    elif damage == "bad-identity":
        record["runtime_digest"] = "private-sentinel"
    elif damage == "bad-count":
        qualification["request_writes"] = 0
    elif damage == "missing-initialize":
        qualification["initialize_verdict"] = None
    elif damage == "wrong-plan":
        qualification["mode"] = "pro"
    elif damage == "extra":
        qualification["private-sentinel"] = "secret"
    else:
        facts["lifecycle"] = "joined-clean"
        qualification["lifecycle"] = "qualified"
    evidence.write_text(json.dumps(record), encoding="utf-8")
    result = cli(config, evidence, "qualify", "--mode", "subscription", "--diagnose-refusal")
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr.splitlines() == [b"Claude phase evidence refused"]
    assert b"private-sentinel" not in result.stderr


def test_qualification_diagnostic_keeps_unobserved_settings_absent(tmp_path):
    config, evidence, _ = refused_qualification(tmp_path)
    record = json.loads(evidence.read_bytes())
    record["facts"]["qualification"].update(
        initialize_verdict=None, settings_verdict=None, settings_mismatch_reason=None,
        mode_mismatch_reason=None, token_source_category=None, api_key_source_category=None,
        request_writes=1,
    )
    evidence.write_text(json.dumps(record), encoding="utf-8")
    result = cli(config, evidence, "qualify", "--mode", "subscription", "--diagnose-refusal")
    assert result.returncode == 0 and result.stderr == b""
    diagnostic = json.loads(result.stdout)
    assert diagnostic["settings_verdict"] is diagnostic["reason"] is None



@pytest.mark.parametrize("schema", [3, 4, 5, 6])
def test_historical_qualification_is_preserved_without_invented_reason(tmp_path, schema):
    config, evidence, _ = refused_qualification(tmp_path)
    record = json.loads(evidence.read_bytes())
    record["schema_version"] = schema
    for name in ("mode_mismatch_reason", "token_source_category", "api_key_source_category"):
        del record["facts"]["qualification"][name]
    if schema == 3:
        del record["facts"]["qualification"]["settings_mismatch_reason"]
    else:
        record["facts"]["qualification"]["settings_mismatch_reason"] = "effective-settings"
    legacy = json.dumps(record, separators=(",", ":")).encode()
    evidence.write_bytes(legacy)
    for extra in ((), ("--diagnose-refusal",)):
        result = cli(config, evidence, "qualify", "--mode", "subscription", *extra)
        assert result.returncode == 1 and result.stdout == b""
        assert result.stderr.splitlines() == [b"Claude phase evidence refused"]
        assert evidence.read_bytes() == legacy


def test_qualification_initialize_refusal_has_exact_closed_reason_and_source_categories(tmp_path):
    config, evidence, loaded = sample(tmp_path, ClaudeMaintenanceSessionPhase.QUALIFY)
    record = json.loads(evidence.read_bytes())
    record["facts"]["lifecycle"] = "refused"
    record["facts"]["qualification"].update(
        lifecycle="refused", initialize_verdict="mode-mismatch",
        mode_mismatch_reason="credential-source-present",
        token_source_category="none", api_key_source_category="unknown",
        settings_verdict=None, settings_mismatch_reason=None, hooks_verdict=None,
        request_writes=1, stdin_closed=False, eof=False,
    )
    evidence.write_text(json.dumps(record), encoding="utf-8")
    result = cli(config, evidence, "qualify", "--mode", "subscription", "--diagnose-refusal")
    assert result.returncode == 0 and result.stderr == b""
    published = json.loads(result.stdout)
    assert published == {
        "initialize_verdict": "mode-mismatch", "mode_mismatch_reason": "credential-source-present",
        "token_source_category": "none", "api_key_source_category": "unknown",
        "settings_verdict": None, "reason": None, "process_clean": True,
        "evidence_digest": str(digest(claude_lane.EVIDENCE_DOMAIN, 1, record)),
    }
    observed = checker.diagnose_refused_qualification(evidence, loaded, ClaudeAuthMode.SUBSCRIPTION)
    assert observed.mode_mismatch_reason.value == "credential-source-present"
    assert observed.token_source_category.value == "none"
    with pytest.raises(ContractViolation):
        checker.validate_phase_evidence(
            ClaudeMaintenanceSessionPhase.QUALIFY, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION,
        )


@pytest.mark.parametrize("phase", ["observe", "qualify"])
@pytest.mark.parametrize("field,value", [
    ("token_source_category", None), ("api_key_source_category", None),
    ("token_source_category", "private-source-sentinel"), ("api_key_source_category", True),
    ("token_source_category", "login-managed-key"), ("api_key_source_category", "none"),
    ("token_source_category", "null"),
])
def test_strict_current_diagnostics_reject_unknown_cross_key_or_incoherent_tags(
    tmp_path, phase, field, value,
):
    selected = ClaudeMaintenanceSessionPhase(phase)
    config, evidence, loaded = sample(tmp_path, selected)
    record = json.loads(evidence.read_bytes())
    branch = record["facts"]["mode" if phase == "observe" else "qualification"]
    branch[field] = value
    evidence.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises((checker._Refused, ContractViolation)):
        checker.validate_phase_evidence(selected, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION)
    result = cli(config, evidence, phase, "--mode", "subscription")
    assert result.returncode == 1 and result.stdout == b""
    assert b"private-source-sentinel" not in result.stderr


def test_historical_mode_schema5_is_not_silently_upgraded(tmp_path):
    _config, evidence, loaded = sample(tmp_path, ClaudeMaintenanceSessionPhase.OBSERVE)
    record = json.loads(evidence.read_bytes())
    record["schema_version"] = 5
    for name in ("token_source_category", "api_key_source_category"):
        del record["facts"]["mode"][name]
    raw = json.dumps(record, separators=(",", ":")).encode()
    evidence.write_bytes(raw)
    with pytest.raises(checker._Refused):
        checker.validate_phase_evidence(
            ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION,
        )
    assert evidence.read_bytes() == raw


@pytest.mark.parametrize("category", list(ClaudeSystemRecordCategory))
def test_rejected_system_category_survives_strict_mode_checker_and_cli(tmp_path, category):
    config, evidence, loaded = refused(tmp_path, "ui-record")
    record = json.loads(evidence.read_bytes())
    record["facts"]["mode"]["rejected_system_category"] = category.value
    evidence.write_text(json.dumps(record), encoding="utf-8")
    diagnostic = checker.diagnose_refused_mode(
        ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION,
    )
    assert diagnostic.rejected_system_category is category
    result = cli(config, evidence, "observe", "--mode", "subscription", "--diagnose-refusal")
    assert result.returncode == 0 and result.stderr == b""
    public = json.loads(result.stdout)
    assert public["rejected_system_category"] == category.value
    assert public["refusal_code"] == "ui-record"
    assert public["request_writes"] == public["classified_responses"] == 1
    assert public["ui_records"] == 0 and len(result.stdout) < 1024
    assert "private" not in result.stdout.decode()
    with pytest.raises(checker._Refused):
        checker.validate_phase_evidence(
            ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION,
        )


@pytest.mark.parametrize("damage", ["missing", "unknown", "bool", "dict", "list", "null",
                                    "wrong-code", "positive"])
def test_rejected_category_requires_closed_current_same_fault_evidence(tmp_path, damage):
    config, evidence, loaded = refused(tmp_path, "ui-record")
    record = json.loads(evidence.read_bytes())
    mode = record["facts"]["mode"]
    if damage == "missing":
        del mode["rejected_system_category"]
    elif damage == "wrong-code":
        mode["refusal_code"] = "read-error"
    elif damage == "positive":
        record["facts"]["lifecycle"] = "joined-clean"
        mode.update(lifecycle="observed", mode_verdict="mode-match", mode_mismatch_reason=None,
                    refusal_code=None, stdin_closed=True, eof=True)
    else:
        mode["rejected_system_category"] = {
            "unknown": "private-subtype", "bool": True, "dict": {"private-key": "private-value"},
            "list": ["private-value"], "null": None,
        }[damage]
    evidence.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(checker._Refused):
        checker.diagnose_refused_mode(
            ClaudeMaintenanceSessionPhase.OBSERVE, evidence, loaded, ClaudeAuthMode.SUBSCRIPTION,
        )
    for extra in ((), ("--diagnose-refusal",)):
        result = cli(config, evidence, "observe", "--mode", "subscription", *extra)
        assert result.returncode == 1 and result.stdout == b""
        assert result.stderr.splitlines() == [b"Claude phase evidence refused"]


@pytest.mark.parametrize("phase", list(ClaudeMaintenanceSessionPhase))
def test_schema6_is_preserved_and_refused_without_inventing_system_category(tmp_path, phase):
    config, evidence, _ = sample(tmp_path, phase)
    record = json.loads(evidence.read_bytes())
    record["schema_version"] = 6
    if record["facts"]["mode"] is not None:
        del record["facts"]["mode"]["rejected_system_category"]
    raw = json.dumps(record, separators=(",", ":")).encode()
    evidence.write_bytes(raw)
    selection = () if phase is ClaudeMaintenanceSessionPhase.LOGIN else ("--mode", "subscription")
    for extra in ((), ("--diagnose-refusal",)):
        result = cli(config, evidence, phase.value, *selection, *extra)
        assert result.returncode == 1 and result.stdout == b""
        assert result.stderr.splitlines() == [b"Claude phase evidence refused"]
    assert evidence.read_bytes() == raw
