"""Attack the public projection after a genuine completed credential-free run."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from constructicon.api import _qualification_write_report as projection
from constructicon.api import qualification
from constructicon.api.detail import DEFAULT_DETAIL_BYTES
from constructicon.core.address import RunId
from constructicon.core.identity import digest
from constructicon.core.qualification_write import (
    SmokeQualificationReport,
    WriteQualificationReport,
    WriteReportIssue,
    WriteReportTelemetry,
)
from constructicon.substrate.executors import codex_protocol
from constructicon.substrate.executors.codex_host import MAX_EVIDENCE_BYTES
from tests.api.test_qualification_write_lifecycle import portable_binding as portable_binding
from tests.api.test_qualification_write_lifecycle import (
    portable_launcher,
    sealed_assembly,
)
from tests.api.test_qualification_write_lifecycle import (
    portable_write_boundary as portable_write_boundary,
)


@pytest.fixture
async def completed(tmp_path, portable_binding, portable_write_boundary, monkeypatch):
    assembly, authorization = await sealed_assembly(
        tmp_path,
        portable_launcher(),
        portable_binding[1:],
    )
    observed = []
    original = projection.derive_write_report

    def capture(system, assembly, authorization, observation):
        observed.append(system)
        return original(system, assembly, authorization, observation)

    monkeypatch.setattr(projection, "derive_write_report", capture)
    report = await qualification.qualify_write(assembly=assembly, authorization=authorization)
    assert report.verdict == "passed", report
    monkeypatch.setattr(projection, "derive_write_report", original)
    assert len(observed) == 1
    return observed[0], assembly, authorization, report


def project(completed, observation="terminal"):
    system, assembly, authorization, _ = completed
    return projection.derive_write_report(system, assembly, authorization, observation)


def assert_bounded(report):
    encoded = report.model_dump_json()
    assert len(encoded.encode("utf-8")) <= DEFAULT_DETAIL_BYTES
    document = json.loads(encoded)

    def walk(value):
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str):
            # Every published string is an enum, protocol-name, Git object,
            # derived identity, or domain-separated digest; never arbitrary text.
            assert len(value) <= 71
            assert value.isascii()
        elif type(value) is int:
            assert len(repr(value)) <= codex_protocol.NUMBER_CHARS
        elif isinstance(value, float):
            assert math.isfinite(value)

    walk(document)


async def test_report_accepting_path_uses_full_materialization(completed, monkeypatch):
    system, assembly, auth, first = completed
    called = []
    original = system.materialize_run

    def materialize(run_id):
        called.append(run_id)
        return original(run_id)

    monkeypatch.setattr(system, "materialize_run", materialize)
    report = project(completed)
    assert report == first
    assert called == [auth.run_id]
    assert report.checkpoint_chain_validated is True
    assert report.obligation_count == 3
    assert {row.role for row in report.obligations} == {"executor", "workspace", "gate"}
    assert all(
        row.state == "closed" and row.disposition == "released" for row in report.obligations
    )
    assert report.turn_dispatch == "completed" and report.turn_status == "success"
    assert report.schema_version == 2
    assert report.target_unchanged is True and report.check_count == 1
    assert report.telemetry.callbacks is not None
    assert report.telemetry.callbacks.admitted_started == 1
    assert report.telemetry.callbacks.admitted_completed == 1
    assert report.telemetry.callbacks.worker_results == ("success",)
    assert report.telemetry.callbacks_final_snapshot is True
    assert report.telemetry.backend_request_count is None
    assert report.telemetry.vendor_retry_count is None
    assert report.limits.stdout_bytes == assembly.executor.launcher.limits.stdout_bytes
    assert_bounded(report)


@pytest.mark.parametrize("fault", ["absent", "active", "discarded", "epoch", "run", "lease"])
async def test_report_requires_actual_complete_obligations(completed, monkeypatch, fault):
    journal = completed[1].resources.journal
    rows = journal.capability_leases(completed[2].run_id)
    changes = {
        "active": {"state": "active", "disposition": None},
        "discarded": {"disposition": "discarded"},
        "epoch": {"acquisition_epoch": 0},
        "run": {"run_id": RunId("run-" + "f" * 32)},
        "lease": {"lease_id": "lease-" + "f" * 32},
    }
    # Workspace does not duplicate the executor attempt's identity guard.
    changed = (
        []
        if fault == "absent"
        else [
            row.model_copy(update=changes[fault]) if row.binding_id == "workspace" else row
            for row in rows
        ]
    )
    monkeypatch.setattr(journal, "capability_leases", lambda run_id: changed)
    report = project(completed)
    assert report.verdict != "passed"
    assert report.issues
    if fault == "absent":
        assert WriteReportIssue.OBLIGATIONS_MISSING in report.issues
    assert_bounded(report)


@pytest.mark.parametrize("field", ["authorization_id", "run_id", "epoch", "acquisition_id"])
async def test_report_attempt_must_match_derived_durable_acquisition(completed, field):
    path = Path(completed[2].attempt_record)
    record = json.loads(path.read_text())
    record[field] = 2 if field == "epoch" else "foreign"
    path.write_text(json.dumps(record))
    report = project(completed)
    assert report.verdict != "passed"
    assert WriteReportIssue.ATTEMPT_MISMATCH in report.issues
    assert_bounded(report)


@pytest.mark.parametrize("fault", ["missing", "oversized", "duplicate", "nonfinite", "intent"])
async def test_report_actual_attempt_reader_fails_closed(completed, fault):
    path = Path(completed[2].attempt_record)
    if fault == "missing":
        path.unlink()
    elif fault == "oversized":
        path.write_bytes(b" " * (MAX_EVIDENCE_BYTES + 1))
    elif fault == "duplicate":
        path.write_text('{"phase":"outcome","phase":"acquired"}')
    elif fault == "nonfinite":
        path.write_text('{"phase":NaN}')
    else:
        record = json.loads(path.read_text())
        record.update(phase="intent")
        del record["facts"], record["dispatch"]
        path.write_text(json.dumps(record))
    report = project(completed)
    assert report.verdict != "passed"
    assert_bounded(report)


@pytest.mark.parametrize("field", ["created_by_run", "manifest_hash", "check_set_hash", "subject"])
async def test_report_real_attestation_must_match_capture_chain(completed, monkeypatch, field):
    journal = completed[1].resources.journal
    original = journal.load_attestation
    attestation = original(completed[3].attestation_id)
    changes = {
        "created_by_run": RunId("run-" + "f" * 32),
        "manifest_hash": digest("foreign", 1, "manifest"),
        "check_set_hash": digest("foreign", 1, "checks"),
        "subject": attestation.subject.model_copy(update={"candidate": "f" * 40}),
    }
    changed = attestation.model_copy(update={field: changes[field]})
    monkeypatch.setattr(journal, "load_attestation", lambda identity: changed)
    report = project(completed)
    assert report.verdict != "passed"
    assert WriteReportIssue.ATTESTATION_MISMATCH in report.issues
    assert_bounded(report)


async def test_report_checkpoint_failure_is_not_a_candidate_certificate(completed, monkeypatch):
    def damaged(run_id):
        raise ValueError("PRIVATE raw callback /account/credential/path")

    monkeypatch.setattr(completed[0], "materialize_run", damaged)
    report = project(completed)
    assert report.verdict == "incomplete"
    assert not report.checkpoint_chain_validated
    assert WriteReportIssue.CHECKPOINT_CHAIN in report.issues
    assert "PRIVATE" not in report.model_dump_json()
    assert_bounded(report)


async def test_report_never_certifies_partial_run(completed, monkeypatch):
    system = completed[0]
    state = system.run_state(completed[2].run_id)
    monkeypatch.setattr(
        system, "run_state", lambda run_id: state.model_copy(update={"status": "running"})
    )
    report = project(completed)
    assert report.verdict != "passed"
    assert WriteReportIssue.RUN_NOT_SUCCEEDED in report.issues


@pytest.mark.parametrize(
    "state,disposition,passed",
    [
        ("closed", "discarded", True),
        ("active", None, False),
        ("lost", None, False),
    ],
)
async def test_report_recovered_gate_requires_every_prior_row_settled(
    completed,
    monkeypatch,
    state,
    disposition,
    passed,
):
    journal = completed[1].resources.journal
    rows = journal.capability_leases(completed[2].run_id)
    gate = next(row for row in rows if row.binding_id == "gate")
    actual = [row for row in rows if row.binding_id != "gate"] + [
        gate.model_copy(update={"state": state, "disposition": disposition}),
        gate.model_copy(update={"acquisition_epoch": 2}),
    ]
    monkeypatch.setattr(journal, "capability_leases", lambda run_id: actual)
    report = project(completed)
    assert (report.verdict == "passed") is passed
    assert report.obligation_count == 4
    if not passed:
        assert WriteReportIssue.OBLIGATIONS_UNSETTLED in report.issues
    assert_bounded(report)


async def test_report_latest_gate_cannot_be_discarded(completed, monkeypatch):
    journal = completed[1].resources.journal
    rows = journal.capability_leases(completed[2].run_id)
    gate = next(row for row in rows if row.binding_id == "gate")
    actual = [*rows, gate.model_copy(update={"acquisition_epoch": 2, "disposition": "discarded"})]
    monkeypatch.setattr(journal, "capability_leases", lambda run_id: actual)
    report = project(completed)
    assert report.verdict != "passed"
    assert WriteReportIssue.OBLIGATIONS_UNSETTLED in report.issues


async def test_report_missing_attestation_is_not_an_empty_fault_pass(completed, monkeypatch):
    monkeypatch.setattr(completed[1].resources.journal, "load_attestation", lambda identity: None)
    report = project(completed)
    assert report.verdict == "incomplete"
    assert report.check_count is None
    assert WriteReportIssue.ATTESTATION_MISSING in report.issues


async def test_report_target_is_read_from_actual_authority(completed):
    authority = completed[1].resources.authority
    authority._run("update-ref", completed[1].pins.fixture.target_ref, completed[3].candidate)
    report = project(completed)
    assert report.verdict == "not-qualified"
    assert report.target_unchanged is False
    assert WriteReportIssue.TARGET_DRIFT in report.issues


async def test_report_whole_bound_binds_without_invented_row_cap(completed, monkeypatch):
    journal = completed[1].resources.journal
    rows = journal.capability_leases(completed[2].run_id)
    gate = next(row for row in rows if row.binding_id == "gate")
    actual = [
        *rows,
        *(gate.model_copy(update={"acquisition_epoch": epoch}) for epoch in range(2, 502)),
    ]
    monkeypatch.setattr(journal, "capability_leases", lambda run_id: actual)
    report = project(completed)
    assert report.verdict == "incomplete"
    assert report.obligation_count == 503
    assert report.obligations == ()
    assert report.check_count == 1 and report.checks == ()
    assert report.details_complete is False
    assert WriteReportIssue.REPORT_OVERFLOW in report.issues
    assert_bounded(report)


@pytest.mark.parametrize(
    "field,value",
    [
        pytest.param("served_model", "PRIVATE:/account/" * 10000, id="private-model-overflow"),
        pytest.param("input_tokens", 10**codex_protocol.NUMBER_CHARS, id="input-number-overflow"),
        pytest.param("output_tokens", -1, id="negative-output-count"),
    ],
)
async def test_report_every_telemetry_field_obeys_protocol_bounds(completed, field, value):
    path = Path(completed[2].attempt_record)
    record = json.loads(path.read_text())
    if field == "served_model":
        record["facts"][field] = value
    else:
        record["facts"]["usage"] = {"input_tokens": 1, "output_tokens": 1, field: value}
    path.write_text(json.dumps(record))
    report = project(completed)
    assert report.verdict != "passed"
    assert "PRIVATE" not in report.model_dump_json()
    assert_bounded(report)


async def test_report_configured_limit_is_not_fabricated_default(
    tmp_path, portable_binding, portable_write_boundary,
):
    launcher = portable_launcher()
    configured = replace(launcher.limits, stdout_bytes=1234567)
    assert configured.stdout_bytes != launcher.limits.stdout_bytes
    # Inject the replacement before sealing the provider and authorization:
    # LinuxLauncher is frozen, and the observed run must use the changed bound.
    launcher = replace(launcher, limits=configured)
    assembly, authorization = await sealed_assembly(tmp_path, launcher, portable_binding[1:])
    report = await qualification.qualify_write(assembly=assembly, authorization=authorization)
    assert report.verdict == "passed", report.model_dump_json()
    assert report.limits.stdout_bytes == launcher.limits.stdout_bytes == 1234567
    assert_bounded(report)


def test_public_contract_names_and_counts_match_protocol():
    valid = WriteReportTelemetry(
        requested_model="a" * codex_protocol.NAMEABLE_METHOD,
        input_tokens=10**codex_protocol.NUMBER_CHARS - 1,
    )
    assert valid.requested_model and valid.input_tokens
    for values in (
        {"requested_model": "a" * (codex_protocol.NAMEABLE_METHOD + 1)},
        {"requested_model": "private:/account"},
        {"input_tokens": 10**codex_protocol.NUMBER_CHARS},
        {"callback_count": 1},
    ):
        with pytest.raises(ValidationError):
            WriteReportTelemetry.model_validate(values)


async def test_callback_provenance_and_legacy_absence_stay_distinct(completed, monkeypatch):
    assembly, authorization = completed[1:3]
    retained = json.loads(Path(authorization.attempt_record).read_text())
    legacy = {key: value for key, value in retained.items() if key != "callbacks"}
    monkeypatch.setattr(projection, "_attempt", lambda path: legacy)
    report = project(completed)
    assert report.schema_version == 2 and report.verdict == "passed"
    assert report.telemetry.callbacks is None and report.telemetry.callbacks_final_snapshot is None
    progress = {key: value for key, value in retained.items() if key not in {"facts", "dispatch"}}
    progress["phase"] = "intent"
    monkeypatch.setattr(projection, "_attempt", lambda path: progress)
    report = project(completed)
    assert report.verdict != "passed" and report.telemetry.callbacks_final_snapshot is False
    assert report.telemetry.callbacks.admitted_started == 1
    assert report.telemetry.callbacks.worker_results == ("success",)
    assert report.turn_dispatch == "possibly dispatched"
    assert assembly.executor.identity


def test_write_schema_two_and_smoke_schema_one_are_strict_disjoint_consumers():
    common = {"verdict": "incomplete", "observation": "error", "issues": (),
              "details_complete": False, "run_id": "run-" + "0" * 32,
              "report_definition": digest("report", 1, "test")}
    smoke = SmokeQualificationReport.model_validate(common)
    write = WriteQualificationReport.model_validate({
        **common, "authorization_identity": digest("auth", 1, "test"),
    })
    assert smoke.schema_version == 1 and write.schema_version == 2
    with pytest.raises(ValidationError):
        SmokeQualificationReport.model_validate({**common, "schema_version": 2})
    with pytest.raises(ValidationError):
        WriteQualificationReport.model_validate({**write.model_dump(), "schema_version": 1})


@pytest.mark.parametrize("value", [0, 1, "false", "true"])
def test_callback_finalization_is_exact_boolean_not_coerced(value):
    with pytest.raises(ValidationError):
        WriteReportTelemetry.model_validate({"callbacks_final_snapshot": value, "callbacks": {
            "schema_version": 1, "admitted_started": 0,
            "admitted_completed": 0, "worker_results": [],
        }})


@pytest.mark.parametrize("values", [
    {"callbacks_final_snapshot": False},
    {"callbacks": {"schema_version": 1, "admitted_started": 0,
                   "admitted_completed": 0, "worker_results": []}},
])
def test_callback_snapshot_and_its_provenance_cannot_be_separated(values):
    with pytest.raises(ValidationError):
        WriteReportTelemetry.model_validate(values)


async def test_successful_attempt_refuses_unfinished_callback_observations(completed, monkeypatch):
    record = json.loads(Path(completed[2].attempt_record).read_text())
    for worker in (None, "success", "nonzero"):
        record["callbacks"] = {"schema_version": 1, "admitted_started": 1,
                               "admitted_completed": 0, "worker_results": [worker]}
        monkeypatch.setattr(projection, "_attempt", lambda path: record)
        report = project(completed)
        assert report.verdict != "passed", f"contradictory successful callback snapshot: {worker}"
        assert WriteReportIssue.ATTEMPT_INVALID in report.issues


async def test_passed_contract_refuses_unfinished_or_partial_callback_observations(completed):
    document = completed[3].model_dump(mode="json")
    for worker in (None, "success", "nonzero"):
        document["telemetry"]["callbacks"] = {
            "schema_version": 1, "admitted_started": 1,
            "admitted_completed": 0, "worker_results": [worker],
        }
        with pytest.raises(ValidationError):
            WriteQualificationReport.model_validate(document)
    document["telemetry"]["callbacks"] = {
        "schema_version": 1, "admitted_started": 0,
        "admitted_completed": 0, "worker_results": [],
    }
    document["telemetry"]["callbacks_final_snapshot"] = False
    with pytest.raises(ValidationError):
        WriteQualificationReport.model_validate(document)


async def test_callback_crossfact_law_permits_zero_legacy_and_failed_prefix(completed, monkeypatch):
    record = json.loads(Path(completed[2].attempt_record).read_text())
    record["callbacks"] = {"schema_version": 1, "admitted_started": 0,
                           "admitted_completed": 0, "worker_results": []}
    monkeypatch.setattr(projection, "_attempt", lambda path: record)
    zero = project(completed)
    assert zero.verdict == "passed" and zero.telemetry.callbacks_final_snapshot is True
    assert zero.telemetry.callbacks.admitted_started == 0
    assert WriteQualificationReport.model_validate(zero.model_dump()) == zero
    del record["callbacks"]
    legacy = project(completed)
    assert legacy.verdict == "passed" and legacy.telemetry.callbacks is None
    assert WriteQualificationReport.model_validate(legacy.model_dump()) == legacy
    record["callbacks"] = {"schema_version": 1, "admitted_started": 1,
                           "admitted_completed": 0, "worker_results": ["nonzero"]}
    record["dispatch"] = "possibly dispatched"
    record["facts"]["status"] = "failure"
    failed = project(completed)
    assert failed.verdict == "not-qualified"
    assert WriteReportIssue.ATTEMPT_INVALID not in failed.issues
    assert failed.telemetry.callbacks_final_snapshot is True
    assert failed.telemetry.callbacks.worker_results == ("nonzero",)
    assert WriteQualificationReport.model_validate(failed.model_dump()) == failed


def test_report_definition_covers_whole_contract_and_projection():
    source = Path(projection.__file__)
    contract = source.parents[1] / "core" / "qualification_write.py"
    assert projection.write_report_definition() == digest(
        "qualification-write-report-definition",
        1,
        {"contract": contract.read_bytes().hex(), "projection": source.read_bytes().hex()},
    )


def test_missing_observations_and_invalid_count_fallback_stay_unknown():
    data, issues = projection._base(RunId("run-" + "0" * 32), "error")
    data["obligation_count"] = 10**codex_protocol.NUMBER_CHARS
    report = projection._finish(SmokeQualificationReport, data, issues)
    assert report.obligation_count is None and report.check_count is None
    assert report.verdict == "incomplete" and not report.details_complete
    assert_bounded(report)


async def test_passing_schema_cannot_drop_one_expected_role(completed):
    document = completed[3].model_dump()
    document["obligations"] = ()
    document["obligation_count"] = 0
    with pytest.raises(ValidationError):
        WriteQualificationReport.model_validate(document)
    # Smoke shares capture fields, but does not invent any turn or executor.
    smoke = {
        key: value
        for key, value in document.items()
        if key in SmokeQualificationReport.model_fields
    }
    with pytest.raises(ValidationError):
        SmokeQualificationReport.model_validate(smoke)
