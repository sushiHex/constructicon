"""Closed schema-5 Claude phase evidence checker; no login or dispatch authority.

Positive phase validation and observer-refusal diagnosis are separate CLI actions.
The selected plan for observe/reload remains a reviewed-command input, not an
attestation found in those phase records. Historical schemas are not upgraded.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from constructicon.core.identity import Digest, digest
from constructicon.substrate.executors import claude_lane
from constructicon.substrate.executors.claude_host import (
    checked_startup_evidence,
    validate_startup_evidence,
)
from constructicon.substrate.executors.claude_lane import LaneConfiguration
from constructicon.substrate.executors.claude_maintenance_mode import (
    ClaudeMaintenanceRefusalCode,
)
from constructicon.substrate.executors.claude_maintenance_session import (
    ClaudeMaintenanceSessionPhase,
)
from constructicon.substrate.executors.claude_protocol import (
    ClaudeInitializeVerdict,
    ClaudeModeMismatchReason,
    ClaudePlan,
)
from constructicon.substrate.executors.claude_startup import (
    ClaudeSettingsMismatchReason,
    ClaudeStartupVerdict,
)
from constructicon.substrate.executors.codex_host import _evidence
from constructicon.substrate.executors.egress import identity_digests

CHECKER_SCHEMA = 5
_RECORD_FIELDS = frozenset({
    "schema_version", "subscription_qualified", "production_available", "facts",
    "runtime_digest", "vendor_digest", "launch_policy_sha256", "launch_config_sha256",
    "launch_revision", "egress", "completed",
})
_FACT_FIELDS = frozenset({
    "phase", "lifecycle", "login", "mode", "relay_closed", "custody_current",
    "credential_closed", "process_clean",
})
_LOGIN_FIELDS = frozenset({
    "lifecycle", "input_write_attempted", "stdin_closed", "stdout_eof", "stdout_bytes",
})
_MODE_FIELDS = frozenset({
    "phase", "mode_verdict", "mode_mismatch_reason", "classified_responses", "lifecycle",
    "request_writes", "ui_records", "stdin_closed", "eof", "refusal_code",
})
_REASONS = frozenset(reason.value for reason in ClaudeModeMismatchReason)
_VERDICTS = frozenset(verdict.value for verdict in ClaudeInitializeVerdict)
_REFUSALS = frozenset(code.value for code in ClaudeMaintenanceRefusalCode)


class _Refused(Exception):
    """Static refusal, without an evidence value or locator."""


def _require(value: bool) -> None:
    if not value:
        raise _Refused()


def _arguments(phase, evidence, configuration, selected_plan) -> None:
    _require(type(phase) is ClaudeMaintenanceSessionPhase
             and type(configuration) is LaneConfiguration
             and isinstance(evidence, Path) and evidence.is_absolute()
             and ".." not in evidence.parts
             and claude_lane.EVIDENCE_SCHEMA == CHECKER_SCHEMA)
    _require(selected_plan is None if phase is ClaudeMaintenanceSessionPhase.LOGIN
             else type(selected_plan) is ClaudePlan)


def _checked_record(phase, evidence, configuration, selected_plan):
    """Reuse the bounded reader, closed envelope and installed-input checks."""
    _arguments(phase, evidence, configuration, selected_plan)
    _require(phase is not ClaudeMaintenanceSessionPhase.QUALIFY)
    record = _evidence(evidence)
    _require(set(record) == _RECORD_FIELDS)
    facts = record.get("facts")
    _require(type(facts) is dict and set(facts) == _FACT_FIELDS)
    _require(type(record["schema_version"]) is int
             and record["schema_version"] == CHECKER_SCHEMA
             and record["completed"] is True
             and record["subscription_qualified"] is False
             and record["production_available"] is False
             and facts["phase"] == phase.value
             and facts["relay_closed"] is True
             and facts["custody_current"] is True
             and facts["credential_closed"] is True)
    policy = configuration.egress[phase.value]
    expected = {
        "runtime_digest": str(configuration.runtime_digest),
        "vendor_digest": str(configuration.vendor_digest),
        "launch_policy_sha256": configuration.launch_policy_sha256,
        "launch_config_sha256": configuration.configuration_sha256,
        "launch_revision": str(configuration.launcher(phase).revision),
        "egress": {name: str(value) for name, value in identity_digests(policy).items()},
    }
    _require(all(record[name] == value for name, value in expected.items()))
    return record, facts


def _mode(facts, phase):
    mode = facts["mode"]
    _require(type(mode) is dict and set(mode) == _MODE_FIELDS
             and facts["login"] is None and facts["process_clean"] is None)
    _require(mode["phase"] == phase.value
             and type(mode["request_writes"]) is int
             and 0 <= mode["request_writes"] <= (
                 2 if phase is ClaudeMaintenanceSessionPhase.OBSERVE else 1
             )
             and type(mode["classified_responses"]) is int
             and 0 <= mode["classified_responses"] <= mode["request_writes"]
             and (mode["mode_verdict"] is None
                  or (type(mode["mode_verdict"]) is str
                      and mode["mode_verdict"] in _VERDICTS))
             and ((mode["classified_responses"] > 0)
                  == (mode["mode_verdict"] is not None))
             and ((mode["mode_verdict"] == "mode-mismatch")
                  == (mode["mode_mismatch_reason"] is not None))
             and (mode["mode_mismatch_reason"] is None
                  or (type(mode["mode_mismatch_reason"]) is str
                      and mode["mode_mismatch_reason"] in _REASONS
                      and mode["mode_verdict"] == "mode-mismatch"))
             and type(mode["ui_records"]) is int and 0 <= mode["ui_records"] <= 8
             and type(mode["stdin_closed"]) is bool and type(mode["eof"]) is bool
             and (mode["refusal_code"] is None
                  or (type(mode["refusal_code"]) is str
                      and mode["refusal_code"] in _REFUSALS)))
    return mode


def validate_phase_evidence(
    phase: ClaudeMaintenanceSessionPhase, evidence: Path,
    configuration: LaneConfiguration, selected_plan: ClaudePlan | None,
) -> Digest:
    """Return only the digest for the existing positive phase requirements."""
    _arguments(phase, evidence, configuration, selected_plan)
    if phase is ClaudeMaintenanceSessionPhase.QUALIFY:
        observed_plan, revision = validate_startup_evidence(evidence, configuration)
        _require(observed_plan is selected_plan)
        return revision
    record, facts = _checked_record(phase, evidence, configuration, selected_plan)
    _require(facts["lifecycle"] == "joined-clean")
    if phase is ClaudeMaintenanceSessionPhase.LOGIN:
        login = facts["login"]
        _require(type(login) is dict and set(login) == _LOGIN_FIELDS
                 and facts["mode"] is None and facts["process_clean"] is True)
        _require(login["lifecycle"] == "completed"
                 and login["input_write_attempted"] is True
                 and login["stdin_closed"] is True and login["stdout_eof"] is True
                 and type(login["stdout_bytes"]) is int
                 and 0 <= login["stdout_bytes"] <= 256 * 1024)
    else:
        mode = _mode(facts, phase)
        _require(mode["mode_verdict"] == "mode-match"
                 and mode["request_writes"] >= 1
                 and mode["mode_mismatch_reason"] is None
                 and mode["refusal_code"] is None
                 and mode["classified_responses"] == mode["request_writes"]
                 and mode["lifecycle"] == "observed"
                 and mode["stdin_closed"] is True and mode["eof"] is True)
    return digest(claude_lane.EVIDENCE_DOMAIN, 1, record)


@dataclass(frozen=True, slots=True)
class RefusedModeDiagnostic:
    mode_verdict: ClaudeInitializeVerdict | None
    reason: ClaudeModeMismatchReason | None
    refusal_code: ClaudeMaintenanceRefusalCode | None
    classified_responses: int
    request_writes: int
    ui_records: int
    evidence_digest: Digest


@dataclass(frozen=True, slots=True)
class RefusedQualificationDiagnostic:
    settings_verdict: ClaudeStartupVerdict | None
    reason: ClaudeSettingsMismatchReason | None
    process_clean: bool
    evidence_digest: Digest


def diagnose_refused_qualification(
    evidence: Path, configuration: LaneConfiguration, selected_plan: ClaudePlan,
) -> RefusedQualificationDiagnostic:
    """Expose only a checked finite refusal, never a positive phase receipt."""
    try:
        _arguments(ClaudeMaintenanceSessionPhase.QUALIFY, evidence, configuration, selected_plan)
        record, revision = checked_startup_evidence(evidence, configuration)
        facts = record["facts"]
        qualification = facts["qualification"]
        _require(facts["lifecycle"] == "refused"
                 and qualification["lifecycle"] == "refused"
                 and qualification["selected_plan"] == (
                     "pro" if selected_plan is ClaudePlan.PRO else "max"
                 ))
        verdict = qualification["settings_verdict"]
        reason = qualification["settings_mismatch_reason"]
        return RefusedQualificationDiagnostic(
            None if verdict is None else ClaudeStartupVerdict(verdict),
            None if reason is None else ClaudeSettingsMismatchReason(reason),
            facts["process_clean"], revision,
        )
    except Exception:
        pass
    raise _Refused()


def diagnose_refused_mode(
    phase: ClaudeMaintenanceSessionPhase, evidence: Path,
    configuration: LaneConfiguration, selected_plan: ClaudePlan,
) -> RefusedModeDiagnostic:
    """Report bounded observer refusal, never phase approval or a positive marker.

    The mode reason describes only the last classified response. Refusal code,
    when present, names the first observer guard that actually stopped work.
    """
    try:
        _require(phase in (ClaudeMaintenanceSessionPhase.OBSERVE,
                           ClaudeMaintenanceSessionPhase.RELOAD))
        record, facts = _checked_record(phase, evidence, configuration, selected_plan)
        mode = _mode(facts, phase)
        _require(facts["lifecycle"] == "refused"
                 and mode["lifecycle"] == "refused")
        verdict = mode["mode_verdict"]
        reason = mode["mode_mismatch_reason"]
        code = mode["refusal_code"]
        return RefusedModeDiagnostic(
            None if verdict is None else ClaudeInitializeVerdict(verdict),
            None if reason is None else ClaudeModeMismatchReason(reason),
            None if code is None else ClaudeMaintenanceRefusalCode(code),
            mode["classified_responses"], mode["request_writes"], mode["ui_records"],
            digest(claude_lane.EVIDENCE_DOMAIN, 1, record),
        )
    except Exception:
        pass
    raise _Refused()  # Outside the catch: no retained private exception context.


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise _Refused()


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(add_help=False, allow_abbrev=False)
    parser.add_argument("--phase", choices=("login", "observe", "reload", "qualify"),
                        required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--selected-plan", choices=("pro", "max"))
    parser.add_argument("--diagnose-refusal", action="store_true")
    try:
        options = parser.parse_args(argv)
        phase = ClaudeMaintenanceSessionPhase(options.phase)
        plan = {"pro": ClaudePlan.PRO, "max": ClaudePlan.MAX}.get(options.selected_plan)
        configuration = claude_lane.read_configuration(
            options.config, expected_sha256=options.config_sha256,
        )
        if options.diagnose_refusal:
            if phase is ClaudeMaintenanceSessionPhase.QUALIFY:
                startup = diagnose_refused_qualification(options.evidence, configuration, plan)
                print(json.dumps({
                    "settings_verdict": (None if startup.settings_verdict is None
                                         else startup.settings_verdict.value),
                    "reason": None if startup.reason is None else startup.reason.value,
                    "process_clean": startup.process_clean,
                    "evidence_digest": str(startup.evidence_digest),
                }, sort_keys=True, separators=(",", ":")))
                return 0
            diagnostic = diagnose_refused_mode(phase, options.evidence, configuration, plan)
            print(json.dumps({
                "mode_verdict": (None if diagnostic.mode_verdict is None
                                 else diagnostic.mode_verdict.value),
                "reason": None if diagnostic.reason is None else diagnostic.reason.value,
                "refusal_code": (None if diagnostic.refusal_code is None
                                 else diagnostic.refusal_code.value),
                "classified_responses": diagnostic.classified_responses,
                "request_writes": diagnostic.request_writes,
                "ui_records": diagnostic.ui_records,
                "evidence_digest": str(diagnostic.evidence_digest),
            }, sort_keys=True, separators=(",", ":")))
        else:
            print(validate_phase_evidence(phase, options.evidence, configuration, plan))
    except Exception:
        print("Claude phase evidence refused", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
