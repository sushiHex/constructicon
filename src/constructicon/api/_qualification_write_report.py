"""Allowlisted WRITE evidence derived only after the control host has joined."""

from __future__ import annotations

import math
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import ValidationError

from constructicon.api._qualification_write_graph import (
    CHECKER_GRANTS,
    CHECKER_SCOPE,
    EXECUTOR,
    GATE,
    OBSERVATION_TIMEOUT_S,
    SMOKE_CHECKER_SCOPE,
    SMOKE_WRITER_SCOPE,
    WORKSPACE,
    WRITER_SCOPE,
    smoke_graph,
    write_graph,
)
from constructicon.api.detail import DEFAULT_DETAIL_BYTES
from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.envelope import GitRef
from constructicon.core.gates import MergeEvaluation
from constructicon.core.identity import Digest, canonical_json, digest, parse_json_value
from constructicon.core.manifest import SELF_BINDING, CapabilityLease
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.qualification_write import (
    CallbackObservation,
    CaptureQualificationReport,
    SmokeQualificationReport,
    WriteObservation,
    WriteQualificationPins,
    WriteQualificationReport,
    WriteQualificationRequest,
    WriteReportCheck,
    WriteReportInstalledIdentities,
    WriteReportIssue,
    WriteReportLimits,
    WriteReportObligation,
    WriteReportTelemetry,
)
from constructicon.core.run import RunStatus
from constructicon.core.workspace import acquisition_id_for, lease_id_for
from constructicon.substrate.executors.codex_host import MAX_EVIDENCE_BYTES, WRITE_GRANTS
from constructicon.substrate.executors.codex_protocol import (
    MAX_TOOL_CALLS,
    NUMBER_CHARS,
    TOOL_OUTPUT_BYTES,
    TOOL_PROGRAM_BYTES,
)

if TYPE_CHECKING:
    from constructicon.api._qualification_write_assembly import (
        ContainedWriteResources,
        WriteAssembly,
    )
    from constructicon.api.system import Constructicon

Issue = WriteReportIssue
_Report = TypeVar("_Report", bound=CaptureQualificationReport)


def write_report_definition() -> Digest:
    """Bind the complete report contract and projection, including helpers."""

    contract = Path(__file__).resolve().parents[1] / "core" / "qualification_write.py"
    return digest(
        "qualification-write-report-definition",
        1,
        {
            "contract": contract.read_bytes().hex(),
            "projection": Path(__file__).read_bytes().hex(),
        },
    )


def _finish(model: type[_Report], data: dict[str, Any], issues: set[Issue]) -> _Report:
    """One whole-public-surface bound, never a truncated successful projection."""
    data["issues"] = tuple(issue for issue in Issue if issue in issues)
    data["verdict"] = "incomplete" if issues else "passed"
    if issues and issues <= {
        Issue.GATE_FAILED,
        Issue.TARGET_DRIFT,
        Issue.RUN_NOT_SUCCEEDED,
        Issue.ATTEMPT_NOT_COMPLETED,
    }:
        data["verdict"] = "not-qualified"
    if data["verdict"] == "incomplete":
        data["details_complete"] = False
    try:
        report = model.model_validate(data)
    except ValidationError:
        issues.add(Issue.TELEMETRY_INVALID)
        # Invalid untrusted identities/numbers cannot escape even on refusal.
        keep = {
            key: value
            for key, value in data.items()
            if key
            in {
                "run_id",
                "authorization_identity",
                "report_definition",
                "observation",
                "obligation_count",
                "check_count",
            }
        }
        for key in ("obligation_count", "check_count"):
            value = keep.get(key)
            keep[key] = value if type(value) is int and 0 <= value < 10**NUMBER_CHARS else None
        keep.update(
            verdict="incomplete",
            details_complete=False,
            issues=tuple(issue for issue in Issue if issue in issues),
        )
        report = model.model_validate(keep)
    if len(report.model_dump_json().encode("utf-8")) <= DEFAULT_DETAIL_BYTES:
        return report
    issues.add(Issue.REPORT_OVERFLOW)
    # Preserve counts, not a prefix of facts with an apparent pass.
    data = {
        key: value
        for key, value in report.model_dump().items()
        if key
        in {
            "schema_version",
            "run_id",
            "authorization_identity",
            "report_definition",
            "observation",
            "obligation_count",
            "check_count",
        }
    }
    data.update(
        verdict="incomplete",
        details_complete=False,
        issues=tuple(issue for issue in Issue if issue in issues),
    )
    return model.model_validate(data)


def _base(run_id: RunId, observation: WriteObservation) -> tuple[dict[str, Any], set[Issue]]:
    issues: set[Issue] = set()
    if observation == "timeout":
        issues.add(Issue.OBSERVATION_TIMEOUT)
    elif observation == "error":
        issues.add(Issue.OBSERVATION_ERROR)
    return {
        "run_id": run_id,
        "observation": observation,
        "details_complete": True,
        "report_definition": write_report_definition(),
    }, issues


def _capture_facts(
    system: Constructicon,
    resources: ContainedWriteResources,
    pins: WriteQualificationPins,
    run_id: RunId,
    observation: WriteObservation,
    *,
    authorization: QualificationAuthorization | None,
) -> tuple[dict[str, Any], set[Issue], list[CapabilityLease]]:
    """The real two consumers share exactly one capture/checkpoint/attestation law."""
    data, issues = _base(run_id, observation)
    rows: list[CapabilityLease] = []
    writer_scope = WRITER_SCOPE if authorization is not None else SMOKE_WRITER_SCOPE
    checker_scope = CHECKER_SCOPE if authorization is not None else SMOKE_CHECKER_SCOPE
    expected = {(writer_scope, WORKSPACE): "workspace", (checker_scope, GATE): "gate"}
    if authorization is not None:
        expected[(writer_scope, EXECUTOR)] = "executor"
    try:
        state = system.run_state(run_id)
        if state is None:
            issues.add(Issue.RUN_MISSING)
        else:
            data["run_status"] = state.status
            if state.status != RunStatus.SUCCEEDED:
                issues.add(Issue.RUN_NOT_SUCCEEDED)
        data.update(
            fixture_identity=pins.fixture.identity,
            base_commit=pins.fixture.base_commit,
            workspace_revision=pins.workspace.revision,
            gate_revision=pins.gate.revision,
        )
        if (
            resources.fixture != pins.fixture
            or pins.report_definition != data["report_definition"]
            or resources.workspace.revision != str(pins.workspace.revision)
            or resources.gate.revision != str(pins.gate.revision)
            or resources.gate.check_set_hash != pins.gate.revision
        ):
            issues.add(Issue.ASSEMBLY_MISMATCH)
        target_unchanged = (
            resources.authority.read_ref(pins.fixture.target_ref) == pins.fixture.base_commit
        )
        data["target_unchanged"] = target_unchanged
        if not target_unchanged:
            issues.add(Issue.TARGET_DRIFT)
        manifest = system.manifest_for_run(run_id)
        data["manifest_hash"] = manifest.manifest_hash
        graph = (
            write_graph(authorization.capability_id, pins)
            if authorization is not None
            else smoke_graph(pins)
        )
        request = WriteQualificationRequest(
            authorization_id=(
                authorization.authorization_id if authorization else "credential-free-smoke"
            ),
            fixture_identity=pins.fixture.identity,
            base_commit=pins.fixture.base_commit,
        )
        if canonical_json(manifest.source_graph) != canonical_json(graph) or canonical_json(
            system.inputs_for_run(run_id)
        ) != canonical_json({"request": request}):
            issues.add(Issue.AUTHORIZATION_MISMATCH)
        bindings = [
            binding for binding in manifest.capability_bindings if binding.binding != SELF_BINDING
        ]
        actual_keys = [(binding.scope, binding.binding) for binding in bindings]
        if len(actual_keys) != len(expected) or set(actual_keys) != set(expected):
            issues.add(Issue.OBLIGATION_MISMATCH)
        for binding in bindings:
            role = expected.get((binding.scope, binding.binding))
            pin = pins.workspace if role == "workspace" else pins.gate if role == "gate" else None
            revision = (
                authorization.revision
                if role == "executor" and authorization
                else str(pin.revision)
                if pin
                else None
            )
            capability = (
                authorization.capability_id
                if role == "executor" and authorization
                else pin.capability_id
                if pin
                else None
            )
            grants = CHECKER_GRANTS if role == "gate" else WRITE_GRANTS
            if (
                binding.revision != revision
                or binding.capability_id != capability
                or canonical_json(binding.effective_grants) != canonical_json(grants)
            ):
                issues.add(Issue.OBLIGATION_MISMATCH)
        rows = resources.journal.capability_leases(run_id)
        data["obligation_count"] = len(rows)
        obligations = []
        seen: set[str] = set()
        acquired: set[tuple[str, int]] = set()
        for row in rows:
            role = expected.get((row.path.scope, row.binding_id), "unexpected")
            logical = lease_id_for(run_id, row.path, row.binding_id)
            if (
                role == "unexpected"
                or row.run_id != run_id
                or row.path.iterations
                or row.lease_id != logical
                or row.acquisition_epoch <= 0
            ):
                issues.add(Issue.OBLIGATION_MISMATCH)
            key = (row.lease_id, row.acquisition_epoch)
            if key in acquired:
                issues.add(Issue.OBLIGATION_MISMATCH)
            acquired.add(key)
            seen.add(role)
            if row.state != "closed" or row.disposition is None:
                issues.add(Issue.OBLIGATIONS_UNSETTLED)
            obligations.append(
                WriteReportObligation(
                    role=role,
                    lease_id=row.lease_id,
                    acquisition_id=acquisition_id_for(logical, row.acquisition_epoch),
                    epoch=row.acquisition_epoch,
                    state=row.state,
                    disposition=row.disposition,
                )
            )
        data["obligations"] = tuple(obligations)
        if seen != set(expected.values()):
            issues.add(Issue.OBLIGATIONS_MISSING)
        for role in expected.values():
            role_rows = [
                row for row in rows if expected.get((row.path.scope, row.binding_id)) == role
            ]
            if (
                role_rows
                and max(role_rows, key=lambda row: row.acquisition_epoch).disposition != "released"
            ):
                issues.add(Issue.OBLIGATIONS_UNSETTLED)
        if authorization is not None:
            for role in ("executor", "workspace"):
                writer_rows = [
                    row for row in rows if expected.get((row.path.scope, row.binding_id)) == role
                ]
                if len(writer_rows) != 1 or writer_rows[0].acquisition_epoch != 1:
                    issues.add(Issue.OBLIGATION_MISMATCH)
        # Full materialization validates the entire retained input-hash/version chain.
        try:
            materialized = system.materialize_run(run_id)
        except Exception:
            issues.add(Issue.CHECKPOINT_CHAIN)
            return data, issues, rows
        data["checkpoint_chain_validated"] = True
        candidate = GitRef.model_validate(materialized["candidate"])
        evaluation = MergeEvaluation.model_validate(materialized["evaluation"])
        writer = resources.journal.checkpoint(run_id, ExecutionPath(scope=writer_scope))
        checker = resources.journal.checkpoint(run_id, ExecutionPath(scope=checker_scope))
        if (
            writer is None
            or checker is None
            or canonical_json(writer.outputs["candidate"].payload) != canonical_json(candidate)
            or canonical_json(checker.outputs["evaluation"].payload) != canonical_json(evaluation)
        ):
            issues.add(Issue.CHECKPOINT_CHAIN)
        data.update(
            candidate=candidate.commit, candidate_tree=resources.authority.tree_of(candidate.commit)
        )
        if (
            candidate.repository != resources.authority.repository_id
            or candidate.paths
            or candidate.diff_against != pins.fixture.base_commit
        ):
            issues.add(Issue.CANDIDATE_MISMATCH)
        if evaluation.attestation_id is None or evaluation.subject is None:
            issues.add(Issue.ATTESTATION_MISSING)
            return data, issues, rows
        attestation = resources.journal.load_attestation(evaluation.attestation_id)
        if attestation is None:
            issues.add(Issue.ATTESTATION_MISSING)
            return data, issues, rows
        data.update(
            attestation_id=attestation.attestation_id,
            gate_subject_identity=digest(
                "qualification-write-gate-subject", 1, attestation.subject
            ),
            check_set_hash=attestation.check_set_hash,
            check_count=len(attestation.checks),
            checks=tuple(
                WriteReportCheck(
                    identity=digest("qualification-check-name", 1, check.name), status=check.status
                )
                for check in attestation.checks
            ),
        )
        subject = evaluation.subject
        if (
            attestation.attestation_id != evaluation.attestation_id
            or attestation.action != "merge"
            or attestation.created_by_run != run_id
            or attestation.manifest_hash != manifest.manifest_hash
            or canonical_json(attestation.subject) != canonical_json(subject)
            or canonical_json(attestation.checks) != canonical_json(evaluation.checks)
            or attestation.check_set_hash != resources.gate.check_set_hash
            or subject.repository != resources.authority.repository_id
            or subject.target_ref != pins.fixture.target_ref
            or subject.candidate != candidate.commit
            or subject.expected_base != pins.fixture.base_commit
            or subject.tested_tree != data["candidate_tree"]
            or resources.authority.tree_of(subject.merge_commit) != subject.tested_tree
            or resources.authority.parents_of(subject.merge_commit)
            != (pins.fixture.base_commit, candidate.commit)
            or tuple(check.name for check in attestation.checks)
            != tuple(spec.name for spec in resources.gate.checks)
        ):
            issues.add(Issue.ATTESTATION_MISMATCH)
        if not evaluation.ok or not attestation.ok:
            issues.add(Issue.GATE_FAILED)
    except Exception:
        issues.add(Issue.EVIDENCE_UNAVAILABLE)
    return data, issues, rows


def derive_smoke_report(
    system: Constructicon,
    resources: ContainedWriteResources,
    pins: WriteQualificationPins,
    run_id: RunId,
    observation: WriteObservation,
) -> SmokeQualificationReport:
    data, issues, _ = _capture_facts(
        system, resources, pins, run_id, observation, authorization=None
    )
    return _finish(SmokeQualificationReport, data, issues)


def _attempt(path: Path) -> dict[str, Any]:
    """Bound the actual artifact before parsing; never follow a link or block on a FIFO."""
    if stat.S_ISLNK(path.lstat().st_mode):
        raise ValueError("attempt link")
    fd = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0),
    )
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_EVIDENCE_BYTES:
            raise ValueError("attempt shape")
        raw = os.read(fd, MAX_EVIDENCE_BYTES + 1)
        if len(raw) != info.st_size:
            raise ValueError("attempt size")
        value = parse_json_value(raw.decode("utf-8"))
    finally:
        os.close(fd)
    if not isinstance(value, dict):
        raise ValueError("attempt object")
    return value


def _turn_facts(
    assembly: WriteAssembly,
    authorization: QualificationAuthorization,
    rows: list[CapabilityLease],
    data: dict[str, Any],
    issues: set[Issue],
) -> None:
    try:
        record = _attempt(Path(authorization.attempt_record or ""))
    except FileNotFoundError:
        issues.add(Issue.ATTEMPT_MISSING)
        return
    except Exception:
        issues.add(Issue.ATTEMPT_INVALID)
        return
    try:
        data["attempt_identity"] = digest("qualification-write-attempt", 1, record)
        required = {"authorization_id", "run_id", "epoch", "acquisition_id", "phase", "at"}
        phase = record.get("phase")
        callback_keys = {"callbacks"} if "callbacks" in record else set()
        if phase not in ("acquired", "intent", "outcome") or set(record) != (
            required | {"dispatch", "facts"} if phase == "outcome" else required
        ) | callback_keys:
            raise ValueError("attempt shape")
        callbacks = (
            CallbackObservation.model_validate(record["callbacks"])
            if callback_keys else None
        )
        callback_telemetry = {
            "callbacks": callbacks,
            "callbacks_final_snapshot": phase == "outcome" if callbacks is not None else None,
        }
        data["telemetry"] = WriteReportTelemetry.model_validate(callback_telemetry)
        instant = datetime.fromisoformat(record["at"])
        if instant.tzinfo is None:
            raise ValueError("attempt time")
        executor_rows = [
            row
            for row in rows
            if row.path == ExecutionPath(scope=WRITER_SCOPE) and row.binding_id == EXECUTOR
        ]
        logical = lease_id_for(authorization.run_id, ExecutionPath(scope=WRITER_SCOPE), EXECUTOR)
        epoch = record["epoch"]
        if (
            type(epoch) is not int
            or epoch != 1
            or len(executor_rows) != 1
            or executor_rows[0].acquisition_epoch != epoch
            or executor_rows[0].lease_id != logical
            or record["authorization_id"] != authorization.authorization_id
            or record["run_id"] != authorization.run_id
            or record["acquisition_id"] != acquisition_id_for(logical, epoch)
        ):
            issues.add(Issue.ATTEMPT_MISMATCH)
        if type(epoch) is int and 0 <= epoch < 10**NUMBER_CHARS:
            data.update(
                attempt_epoch=epoch,
                writer_lease_id=logical,
                writer_acquisition_id=acquisition_id_for(logical, epoch),
            )
        if phase != "outcome":
            data["turn_dispatch"] = (
                "acquired-only" if phase == "acquired" else "possibly dispatched"
            )
            issues.add(Issue.ATTEMPT_NOT_COMPLETED)
            return
        data.update(turn_dispatch=record["dispatch"], turn_status=record["facts"]["status"])
        facts = record["facts"]
        if set(facts) != {
            "status",
            "refusal",
            "answer_bytes",
            "usage",
            "served_model",
            "readbacks",
            "relay",
            "process",
            "identities",
        }:
            raise ValueError("attempt facts")
        if callbacks is not None and (
            record["dispatch"] == "completed" or facts["status"] == "success"
        ) and not callbacks.responses_complete:
            issues.add(Issue.ATTEMPT_INVALID)
        identity = assembly.executor.identity
        if facts["identities"] != {
            "adapter_revision": str(identity.adapter_revision),
            "capability_revision": identity.revision,
            "operator_binding_digest": str(authorization.operator_binding_digest),
            "qualification": str(identity.store.subscription_mode_adapter_revision),
        }:
            issues.add(Issue.ATTEMPT_MISMATCH)
        process = facts["process"]
        relay = facts["relay"]
        if not isinstance(relay, dict) or set(relay) != {"destinations", "denied"}:
            raise ValueError("attempt relay")
        for counts in relay.values():
            if not isinstance(counts, dict) or any(
                type(count) is not int or not 0 <= count < 10**NUMBER_CHARS
                for count in counts.values()
            ):
                raise ValueError("attempt relay counts")
        if any(relay["denied"].values()) or facts["refusal"] is not None:
            issues.add(Issue.ATTEMPT_NOT_COMPLETED)
        if (
            record["dispatch"] != "completed"
            or facts["status"] != "success"
            or not isinstance(process, dict)
            or type(process.get("returncode")) is not int
            or process["returncode"] != 0
            or type(process.get("payload_returncode")) is not int
            or process["payload_returncode"] != 0
            or process.get("timed_out") is not False
            or process.get("bound_exceeded") is not False
        ):
            issues.add(Issue.ATTEMPT_NOT_COMPLETED)
        if process is not None and (
            set(process)
            != {
                "returncode",
                "payload_returncode",
                "timed_out",
                "bound_exceeded",
                "elapsed_s",
                "stderr_bytes",
            }
            or type(process["stderr_bytes"]) is not int
            or not 0 <= process["stderr_bytes"] <= assembly.executor.launcher.limits.stderr_bytes
            or type(process["elapsed_s"]) not in (int, float)
            or not math.isfinite(process["elapsed_s"])
            or process["elapsed_s"] < 0
        ):
            issues.add(Issue.ATTEMPT_INVALID)
        usage = facts["usage"]
        if usage != "unknown" and (
            not isinstance(usage, dict) or set(usage) != {"input_tokens", "output_tokens"}
        ):
            raise ValueError("attempt usage")
        readbacks = facts["readbacks"]
        telemetry: dict[str, Any] = {
            **callback_telemetry,
            "requested_model": authorization.grants.model_selection.model
            if authorization.grants
            else None,
            "effort": authorization.grants.effort if authorization.grants else None,
            "served_model": None if facts["served_model"] == "unknown" else facts["served_model"],
            "input_tokens": None if usage == "unknown" else usage["input_tokens"],
            "output_tokens": None if usage == "unknown" else usage["output_tokens"],
        }
        if readbacks is not None:
            if not isinstance(readbacks, dict):
                raise ValueError("attempt readbacks")
            names = {
                "has_credits",
                "unlimited",
                "balance_zero",
                "spend_control_reached",
                "rate_limit_reached",
                "primary_used_percent",
                "secondary_used_percent",
            }
            if any(
                key not in {f"{phase}.{name}" for phase in ("before", "after") for name in names}
                for key in readbacks
            ):
                raise ValueError("attempt readback vocabulary")
            for phase in ("before", "after"):
                telemetry[phase] = {
                    name: readbacks[f"{phase}.{name}"]
                    for name in names
                    if f"{phase}.{name}" in readbacks
                } or None
        data["telemetry"] = WriteReportTelemetry.model_validate(telemetry)
    except Exception:
        issues.add(Issue.ATTEMPT_INVALID)


def derive_write_report(
    system: Constructicon,
    assembly: WriteAssembly,
    authorization: QualificationAuthorization,
    observation: WriteObservation,
) -> WriteQualificationReport:
    data, issues, rows = _capture_facts(
        system,
        assembly.resources,
        assembly.pins,
        authorization.run_id,
        observation,
        authorization=authorization,
    )
    data["authorization_identity"] = digest("qualification-authorization", 1, authorization)
    try:
        identity = assembly.executor.identity
        if (
            authorization.stage != "qualification-write"
            or authorization.scope != WRITER_SCOPE
            or authorization.binding != EXECUTOR
            or authorization.write != assembly.pins
            or authorization.revision != identity.revision
            or authorization.operator_binding_digest != identity.store.operator_binding_digest
            or system.manifest_for_run(authorization.run_id).source_graph_hash
            != authorization.source_graph_hash
        ):
            issues.add(Issue.AUTHORIZATION_MISMATCH)
        data["installed"] = WriteReportInstalledIdentities(
            capability_revision=Digest(identity.revision),
            **{
                field: getattr(identity, field)
                for field in WriteReportInstalledIdentities.model_fields
                if field != "capability_revision"
            },
        )
        limits = assembly.executor.launcher.limits
        data["limits"] = WriteReportLimits(
            exchange_s=WRITE_GRANTS.timeout_s,
            capture_s=WRITE_GRANTS.timeout_s,
            gate_s=CHECKER_GRANTS.timeout_s,
            check_s=max(spec.timeout_s for spec in assembly.resources.gate.checks),
            observation_s=OBSERVATION_TIMEOUT_S,
            callback_limit=MAX_TOOL_CALLS,
            program_bytes=TOOL_PROGRAM_BYTES,
            callback_output_bytes=TOOL_OUTPUT_BYTES,
            cumulative_input_bytes=limits.input_bytes,
            artifact_bytes=limits.artifact_bytes,
            stdout_bytes=limits.stdout_bytes,
            record_bytes=limits.record_bytes,
            stderr_bytes=limits.stderr_bytes,
        )
        _turn_facts(assembly, authorization, rows, data, issues)
    except Exception:
        issues.add(Issue.EVIDENCE_UNAVAILABLE)
    return _finish(WriteQualificationReport, data, issues)
