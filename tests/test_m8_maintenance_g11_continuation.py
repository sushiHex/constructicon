"""Exercise g11 script blocks with private fake evidence, never a host/vendor."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.identity import digest
from constructicon.substrate.executors import maintenance
from constructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN
from tests.test_m8_maintenance_continuation import _portable
from tests.test_m8_n5_g6_session import _run
from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import PYTHON_PROGRAM, _bash

DOCUMENT = HANDOFFS / "M8-maintenance-g11-continuation.md"
RUN = "run-" + "a" * 32
AUTH = "maintenance-3-" + "b" * 40
PRIVATE = "PRIVATE:/credential/location:payload"
C0 = "C0: prepare literal pins and the new reviewed composition"
C1 = "C1: one fresh boot, historical g10 and the retained capture"
C2 = "C2: preserve current D2 records and verify the kept launch"
C4 = "C4: checked floor 10, publish and activate g11"
C7 = "C7: fresh closure, source bundle and authority"
C8 = "C8: retain preflight and display its closed failure stage"
C10 = "C10: one application, independent statuses and closed outcome"
C11 = "C11: one same-session installed diagnosis, then preserve and park"


def _blocks(heading):
    return _fences(_section(_text(DOCUMENT), heading))


def _programs(heading):
    return PYTHON_PROGRAM.findall("\n".join(_blocks(heading)))


def _exec(program, argv, monkeypatch, capsys):
    with monkeypatch.context() as patch:
        patch.setattr(sys, "argv", ["check", *map(str, argv)])
        patch.setattr(sys, "path", list(sys.path))
        patch.setattr(maintenance, "read_maintenance_authorization",
                      lambda path: SimpleNamespace(run_id=RUN, authorization_id=AUTH))
        status = 0
        try:
            exec(compile(program, "<reviewed-g11-check>", "exec"), {})
        except SystemExit as stopped:
            status = stopped.code
    output = capsys.readouterr()
    assert output.err == "" and PRIVATE not in output.out
    return status, output.out


def _run_files(tmp_path, record=None, status=None):
    report = tmp_path / "application-run.json"
    report.write_bytes(json.dumps(
        {"accepted": False, "run_id": RUN} if record is None else record).encode())
    status_file = tmp_path / "application-status.json"
    status_file.write_bytes(json.dumps(
        {"application": 0, "saver": 0, "diagnostics": "clean"}
        if status is None else status).encode())
    return report, status_file


def _diagnostic():
    return {
        "schema_version": 1, "complete": True,
        "meaning": "selected-historical-facts-only", "run_id": RUN,
        "journal": {
            "observation": "selected-facts-validated", "status": "failed",
            "command_origin": "validated", "events_checked": 9,
            "nodes": {
                "writer": {"started": "observed", "checkpoint": "missing", "failures": [
                    {"type": "ContractViolation", "cause": "capture-unchanged"}]},
                "checker": {"started": "unrecorded", "checkpoint": "missing", "failures": []},
            },
            "checks": [{"name": "plan-manifest-trusted-vectors", "status": "failed"}],
        },
        "attempt": {
            "observation": "identity-matched", "phase": "outcome", "dispatch": "completed",
            "executor_status": "success", "failure_kind": "unknown",
            "callbacks": {"schema_version": 1, "admitted_started": 2, "admitted_completed": 2,
                          "worker_results": ["success", "success"]},
            "process": {"timed_out": False, "bound_exceeded": False},
        },
        "pending_attempt": "missing", "command": "normal-nonacceptance", "result": "missing",
    }


@pytest.mark.parametrize("damage", ("none", "refusal", "saver", "stderr", "bool", "extra"))
def test_diagnosis_requires_positive_retained_normal_completion(
    tmp_path, monkeypatch, capsys, damage,
):
    report, statuses = _run_files(tmp_path)
    s = json.loads(statuses.read_bytes())
    if damage == "refusal":
        s["application"] = 1
    elif damage == "saver":
        s["saver"] = 1
    elif damage == "stderr":
        s["diagnostics"] = "unexpected"
    elif damage == "bool":
        s["application"] = False
    elif damage == "extra":
        s["private"] = PRIVATE
    statuses.write_bytes(json.dumps(s).encode())
    if damage == "none":
        status, out = _exec(_programs(C11)[0],
                            [statuses, report, tmp_path / "auth", RUN, AUTH],
                            monkeypatch, capsys)
        assert status == 0 and out == "normal-application-completion-checked\n"
    else:
        with pytest.raises(AssertionError):
            _exec(_programs(C11)[0], [statuses, report, tmp_path / "auth", RUN, AUTH],
                  monkeypatch, capsys)
        assert capsys.readouterr().out == ""


@pytest.mark.parametrize("cause", (
    "capture-return", "capture-unchanged", "capture-repository", "capture-paths", "capture-base",
    "capture-mismatch", "unknown",
))
def test_diagnosis_all_closed_capture_categories_preserve_complete_report(
    tmp_path, monkeypatch, capsys, cause,
):
    record = _diagnostic()
    record["journal"]["nodes"]["writer"]["failures"][0]["cause"] = cause
    status, result = _diagnose(tmp_path, monkeypatch, capsys, record)
    assert status == 0 and result == record


@pytest.mark.parametrize("phase", ("missing", "acquired", "intent", "outcome"))
def test_diagnosis_all_attempt_phases_and_missing_journal_are_explicit(
    tmp_path, monkeypatch, capsys, phase,
):
    record = _diagnostic()
    record["journal"] = {"observation": "missing"}
    if phase == "missing":
        record["attempt"] = {"observation": "missing"}
    elif phase != "outcome":
        record["attempt"] = {"observation": "identity-matched", "phase": phase,
                             "dispatch": "unknown", "callbacks": "unrecorded"}
    status, result = _diagnose(tmp_path, monkeypatch, capsys, record)
    assert status == 0 and result == record


def _objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


@pytest.mark.parametrize("index", range(len(list(_objects(_diagnostic())))))
def test_every_nested_diagnosis_object_refuses_private_extra_fields(
    tmp_path, monkeypatch, capsys, index,
):
    record = _diagnostic()
    objects = list(_objects(record))
    objects[index]["private"] = PRIVATE
    status, result = _diagnose(tmp_path, monkeypatch, capsys, record)
    assert status == 1 and result == {
        "schema_version": 1, "complete": False, "stage": "output",
        "error": "diagnostic refused or incomplete",
    }


@pytest.mark.parametrize("damage", (
    "version-bool", "complete-int", "wrong-run", "meaning", "command", "result", "pending",
    "event-bound", "event-bool", "failures-bound", "checks-bound", "callbacks-bound",
    "callback-prefix", "callback-extra", "worker-private", "node-private", "check-private",
    "process-int", "dispatch", "executor-status", "failure-kind", "duplicate", "malformed",
    "empty", "oversized", "status", "saver", "stderr",
))
def test_complete_diagnosis_contract_refuses_damage_without_publishing_input(
    tmp_path, monkeypatch, capsys, damage,
):
    record = _diagnostic()
    a, j = record["attempt"], record["journal"]
    values = {
        "version-bool": (record, "schema_version", True), "complete-int": (record, "complete", 1),
        "wrong-run": (record, "run_id", "run-" + "b" * 32),
        "meaning": (record, "meaning", PRIVATE), "command": (record, "command", PRIVATE),
        "result": (record, "result", PRIVATE), "pending": (record, "pending_attempt", PRIVATE),
        "event-bound": (j, "events_checked", 257), "event-bool": (j, "events_checked", True),
        "failures-bound": (j["nodes"]["writer"], "failures",
                           [{"type": "unknown", "cause": "unknown"}] * 9),
        "checks-bound": (j, "checks", [{"name": "unknown", "status": "passed"}] * 9),
        "callbacks-bound": (a["callbacks"], "admitted_started", 9),
        "callback-prefix": (a["callbacks"], "admitted_completed", 1),
        "worker-private": (a["callbacks"], "worker_results", [PRIVATE, "success"]),
        "node-private": (j["nodes"]["writer"], "started", PRIVATE),
        "check-private": (j["checks"][0], "name", PRIVATE),
        "process-int": (a["process"], "timed_out", 0), "dispatch": (a, "dispatch", PRIVATE),
        "executor-status": (a, "executor_status", PRIVATE),
        "failure-kind": (a, "failure_kind", PRIVATE),
    }
    if damage in values:
        obj, key, value = values[damage]
        obj[key] = value
    elif damage == "callback-extra":
        a["callbacks"]["private"] = PRIVATE
    kwargs = {}
    if damage in {"duplicate", "malformed", "empty", "oversized"}:
        kwargs["raw"] = {"duplicate": b'{"complete":true,"complete":true}',
                         "malformed": b"\xff", "empty": b"",
                         "oversized": b"PRIVATE" * 1366}[damage]
    elif damage in {"status", "saver", "stderr"}:
        kwargs[{"status": "cli", "saver": "saver", "stderr": "diagnostics"}[damage]] = (
            "private" if damage == "stderr" else "1")
    status, result = _diagnose(tmp_path, monkeypatch, capsys, record, **kwargs)
    assert status == 1 and result == {
        "schema_version": 1, "complete": False, "stage": "output",
        "error": "diagnostic refused or incomplete",
    }


@pytest.mark.parametrize("stage", ("capture", "snapshot", "journal", "attempt", "command",
                                   "result", "output"))
def test_valid_closed_diagnosis_refusal_remains_an_explicit_failure(
    tmp_path, monkeypatch, capsys, stage,
):
    record = {"schema_version": 1, "complete": False, "stage": stage,
              "error": "diagnostic refused or incomplete"}
    status, result = _diagnose(tmp_path, monkeypatch, capsys, record, cli="1")
    assert status == 1 and result == record


def test_input_byte_bound_binds_and_maximum_nested_counts_are_accepted(
    tmp_path, monkeypatch, capsys,
):
    record = _diagnostic()
    j, a = record["journal"], record["attempt"]
    j["events_checked"] = 256
    for node in j["nodes"].values():
        node["failures"] = [{"type": "ContractViolation", "cause": "capture-repository"}] * 8
    j["checks"] = [{"name": "plan-manifest-trusted-vectors", "status": "infrastructure_error"}] * 8
    a["callbacks"] = {"schema_version": 1, "admitted_started": 8, "admitted_completed": 8,
                      "worker_results": ["success"] * 8}
    raw = json.dumps(record).encode()
    assert len(raw) < 8192
    status, result = _diagnose(tmp_path, monkeypatch, capsys, record, raw=raw.ljust(8192))
    assert status == 0 and result == record
    status, result = _diagnose(tmp_path, monkeypatch, capsys, record, raw=raw.ljust(8193))
    assert status == 1 and result["complete"] is False


def test_new_paths_and_frozen_blocks_preserve_existing_source_laws():
    doc = _text(DOCUMENT)
    assert "C=UNPREPARED" in doc and "BASE=UNPREPARED" in doc
    assert "q11/a3/m3" in doc and "maintenance-3/application-3.json" in doc
    assert "maintenance-g9-account.seal" in doc and "maintenance-g11-d2-prior" in doc
    assert "HR R19 on both routes" in doc and "no retirement" in doc
    assert "No discovery/SSH retry or port probe" in doc
    assert "fixed PowerShell file verbatim" in doc
    assert hashlib.sha256((Path(__file__).parents[1] / "scripts/m8_vm_address.py")
                          .read_bytes()).hexdigest() in doc
    old = _text(HANDOFFS / "M8-maintenance-private-continuation.md")
    old_h7, = _fences(_section(old, "C5: complete H7 and explicit checked refresh selection"))
    new_h7, = _blocks("C5: complete H7 and explicit checked refresh selection")
    assert new_h7 == old_h7.replace("g10", "g11").replace("g9", "g10")
    assert _blocks(C8)[0] == _fences(_section(
        old, "C8: retain preflight and display its closed failure stage"))[0]
    assert "journal.__path__.append" not in doc


@pytest.mark.parametrize(("dispatch", "status"), (
    ("completed", "success"), ("possibly dispatched", "success"),
))
def test_successful_attempt_output_requires_completed_callback_prefix(
    tmp_path, monkeypatch, capsys, dispatch, status,
):
    record = _diagnostic()
    a = record["attempt"]
    a["dispatch"], a["executor_status"] = dispatch, status
    a["callbacks"]["admitted_completed"] = 1
    code, result = _diagnose(tmp_path, monkeypatch, capsys, record)
    assert code == 1 and result["stage"] == "output"


@pytest.mark.parametrize(("cli", "saver", "diagnostics"), (
    (0, 0, ""), (1, 0, ""), (0, 1, ""), (1, 1, ""), (0, 0, "PRIVATE"),
))
def test_actual_diagnosis_pipeline_keeps_report_statuses_and_private_stderr(
    tmp_path, monkeypatch, capsys, cli, saver, diagnostics,
):
    record = (_diagnostic() if cli == 0 else
              {"schema_version": 1, "complete": False, "stage": "capture",
               "error": "diagnostic refused or incomplete"})
    fixture = tmp_path / "fixture.json"
    fixture.write_bytes(json.dumps(record).encode())
    (tmp_path / "maintenance-g11-c11-package").mkdir()
    block = _blocks(C11)[0]
    capture = block[block.index("DIAG_STDERR="):]
    capture = capture.split('"${SERVICE[@]}" /usr/bin/python3', 1)[0]
    prefix = "\n".join((
        "set -Eeuo pipefail; umask 077; set -C; SERVICE=(); PY=(diagnose)",
        'S="$TEST_OUT"; APP=fake; ID=fake; RUN_ID=fake',
        'diagnose() { /usr/bin/cat "$FIXTURE"; printf "%s" "$PRIVATE_DIAGNOSTICS" >&2; '
        'return "$CLI_STATUS"; }',
        'save_sealed() { /usr/bin/cat >"$1"; return "$SAVER_STATUS"; }',
    ))
    ran = _run(prefix + "\n" + capture
               + '\nprintf "%s %s %s\\n" "${P11_STATUS[0]}" "${P11_STATUS[1]}" '
               '"$DIAG_DIAGNOSTICS"', TEST_OUT=tmp_path.as_posix(), HOME=tmp_path.as_posix(),
               FIXTURE=fixture.as_posix(), CLI_STATUS=str(cli), SAVER_STATUS=str(saver),
               PRIVATE_DIAGNOSTICS=diagnostics)
    assert ran.returncode == 0 and ran.stderr == ""
    category = "unexpected" if diagnostics else "clean"
    assert ran.stdout == f"{cli} {saver} {category}\n"
    report = tmp_path / "diagnostic-report.json"
    assert report.read_bytes() == fixture.read_bytes()
    code, out = _exec(_programs(C11)[1], [report, RUN, cli, saver, category], monkeypatch, capsys)
    result = json.loads(out)
    assert len(out.encode()) <= 8192
    if saver or diagnostics:
        assert code == 1 and result["stage"] == "output"
    else:
        assert code == cli and result == record


def _diagnose(tmp_path, monkeypatch, capsys, record, cli="0", saver="0", diagnostics="clean",
              raw=None):
    path = tmp_path / "diagnostic-report.json"
    path.write_bytes(json.dumps(record).encode() if raw is None else raw)
    before = path.read_bytes()
    status, out = _exec(_programs(C11)[1], [path, RUN, cli, saver, diagnostics],
                        monkeypatch, capsys)
    assert path.read_bytes() == before
    assert len(out.encode()) <= 8192 and out.endswith("\n") and out.count("\n") == 1
    return status, json.loads(out)


def test_every_new_shell_block_parses_with_actual_common():
    common = "\n".join(_fences(
        _text(HANDOFFS / "M8-N4-operator-commands.md")
        .split("## Setup", 1)[1].split("\n### ", 1)[0]))
    for block in _fences(_text(DOCUMENT)):
        ran = subprocess.run([_bash(), "-n"], input=common + "\n" + block,
                             capture_output=True, text=True, timeout=30, check=False)
        assert ran.returncode == 0 and ran.stdout == "" and ran.stderr == ""


@pytest.mark.parametrize("damage", ("draft", "none", "base", "bound", "bundle"))
def test_pin_guard_is_nonexecutable_until_all_literals_are_prepared(damage):
    guard = _blocks(C0)[0]
    if damage != "draft":
        for name, value in {
            "C": "a" * 40, "BASE": "a" * 40, "BUNDLE_SHA256": "b" * 64,
            "BUNDLE_SIZE": "1", "BUNDLE": "/reviewed.bundle",
        }.items():
            guard, count = re.subn(r"(?m)^" + name + r"=.*$", name + "=" + value, guard)
            assert count == 1
    if damage == "base":
        guard = guard.replace("BASE=" + "a" * 40, "BASE=" + "b" * 40)
    elif damage == "bound":
        guard = guard.replace("BUNDLE_SIZE=1", "BUNDLE_SIZE=67108865")
    elif damage == "bundle":
        guard = guard.replace("BUNDLE=/reviewed.bundle",
                              "BUNDLE=/home/m8-service/UNPREPARED.bundle")
    ran = _run("set +e\n" + guard + "\necho transport-permitted")
    assert ran.stdout == ("transport-permitted\n" if damage == "none" else "")
    assert (ran.returncode == 0) is (damage == "none")


@pytest.mark.parametrize("record", ("s4", "s6a"))
@pytest.mark.parametrize("floor", (10, 9, 11, True, 10.0, None))
def test_both_strict_floor_ten_facts_precede_any_publish(tmp_path, record, floor):
    for name in ("s4", "s6a"):
        (tmp_path / (name + "-qualification.json")).write_text(json.dumps({
            "custody": {"kind": "maintenance", "generation_floor": floor if name == record else 10},
        }), encoding="utf-8")
    block = _blocks(C4)[0].replace("/usr/bin/python3", '"$TEST_PY"')
    prefix = "\n".join((
        "set -Eeuo pipefail; SERVICE=(); ROOT_STORE=(store); R=r; K=k",
        'W="$TEST_OUT"; W_PRIOR=historical-q10',
        'load_final_qualification() { Q=qualified; }',
        'store() { printf "%s\\n" "$*" >>"$TEST_OUT/calls"; printf "{}\\n"; }',
        'save_sealed() { /usr/bin/cat >"$1"; }',
        'check_sealed() { return 0; }', 'binding_check() { return 0; }',
    ))
    ran = _run(prefix + "\n" + block, TEST_OUT=tmp_path.as_posix(),
               TEST_PY=Path(sys.executable).as_posix())
    if type(floor) is int and floor == 10:
        assert ran.returncode == 0 and ran.stderr == "" and ran.stdout == "{}\n"
        calls = (tmp_path / "calls").read_text().splitlines()
        assert len(calls) == 2 and all("--generation 11" in call for call in calls)
    else:
        assert ran.returncode != 0 and not (tmp_path / "calls").exists()
        assert not (tmp_path / "g11.sealed.json").exists()


@pytest.mark.parametrize("failure", ("none", "anchor", "qualification", "seal", "plan"))
def test_g10_checks_precede_preserved_g9_capture_comparison(tmp_path, failure):
    raw = b"pro/private-fake-identity\n"
    path = tmp_path / "maintenance-g9-account.seal"
    path.write_bytes(raw)
    path.chmod(0o600)
    block = _blocks(C1)[0]
    program, = PYTHON_PROGRAM.findall(block)
    block = block.replace(program, _portable(program)).replace("/usr/bin/python3", '"$TEST_PY"')
    prefix = "\n".join((
        "set -Eeuo pipefail; W=historical-q10",
        'binding_check() { test "$*" = "historical-q10/g10.sealed.json reboot-anchor -"; '
        'test "$FAILURE" != anchor; }',
        'load_final_qualification() { test "$FAILURE" != qualification; Q=q; SEAL="$FAKE_SEAL"; }',
        'check_sealed() { test "$*" = "historical-q10/g10.sealed.json q"; '
        'test "$FAILURE" != seal; }',
    ))
    ran = _run(prefix + "\n" + block, HOME=tmp_path.as_posix(), FAILURE=failure,
               TEST_PY=Path(sys.executable).as_posix(),
               FAKE_SEAL="plus/private-fake-identity" if failure == "plan"
               else "pro/private-fake-identity")
    assert path.read_bytes() == raw
    assert (ran.returncode == 0) is (failure == "none")
    assert ran.stdout == ("historical-g10-account-capture-revalidated\n"
                          if failure == "none" else "")
    if failure == "none":
        assert ran.stderr == ""


@pytest.mark.parametrize(("cli", "saver"), ((0, 0), (1, 0), (0, 1), (1, 1), (143, 0)))
@pytest.mark.parametrize("stderr", ("", "private"))
def test_actual_run_pipeline_retains_independent_statuses_and_stderr(tmp_path, cli, saver, stderr):
    (tmp_path / "maintenance-g11-c10-package").mkdir()
    block = _blocks(C10)[0]
    capture = block[block.index('"${SERVICE[@]}" /usr/bin/test ! -e'):]
    capture = capture.split('"${SERVICE[@]}" /usr/bin/python3', 1)[0]
    prefix = "\n".join((
        "set -Eeuo pipefail; umask 077; SERVICE=(); ENTRY=(entry); HOST=()",
        'S="$TEST_OUT"; APP=fake; A=authority',
        'entry() { printf "retained-private-output\\n"; '
        'if test "$DIAGNOSTIC" = private; then printf "PRIVATE" >&2; fi; return "$CLI_STATUS"; }',
        'save_sealed() { /usr/bin/cat >"$1"; '
        'case "$1" in */application-run.json) return "$SAVER_STATUS";; *) return 0;; esac; }',
    ))
    ran = _run(prefix + "\n" + capture, TEST_OUT=tmp_path.as_posix(),
               HOME=tmp_path.as_posix(), CLI_STATUS=str(cli), SAVER_STATUS=str(saver),
               DIAGNOSTIC=stderr)
    assert ran.returncode == 0 and ran.stdout == "" and ran.stderr == ""
    assert json.loads((tmp_path / "application-status.json").read_bytes()) == {
        "application": cli, "saver": saver, "diagnostics": "unexpected" if stderr else "clean",
    }
    assert (tmp_path / "application-run.json").read_bytes() == b"retained-private-output\n"


@pytest.mark.parametrize(("accepted", "command", "cli", "exit_code"), (
    (True, "normal-completed", 0, 0), (False, "normal-completed", 0, 0),
    (False, "refused", 1, 1),
))
def test_complete_run_output_distinguishes_normal_false_from_refusal(
    tmp_path, monkeypatch, capsys, accepted, command, cli, exit_code,
):
    record = ({"accepted": accepted, "run_id": RUN} if cli == 0 else
              {"accepted": False, "error": "maintenance command refused or incomplete"})
    report, statuses = _run_files(tmp_path, record, {
        "application": cli, "saver": 0, "diagnostics": "clean",
    })
    original = report.read_bytes(), statuses.read_bytes()
    status, out = _exec(_programs(C10)[1], [report, tmp_path / "auth", statuses, RUN],
                        monkeypatch, capsys)
    assert status == exit_code and len(out.encode()) <= 257 and out.count("\n") == 1
    assert json.loads(out) == {
        "accepted": accepted, "command": command, "run_id": RUN,
        "meaning": "application-accepted" if accepted else "application-not-accepted",
    }
    assert (report.read_bytes(), statuses.read_bytes()) == original


@pytest.mark.parametrize("damage", (
    "saver", "cli", "bool-cli", "stderr", "wrong-run", "numeric-accepted", "report-extra",
    "status-extra", "refusal-zero", "normal-one", "duplicate", "malformed", "empty",
    "oversized", "missing-report", "missing-status", "status-bool", "hardlink",
))
def test_run_uncertainty_never_becomes_normal_completion(tmp_path, monkeypatch, capsys, damage):
    report, statuses = _run_files(tmp_path)
    r, s = json.loads(report.read_bytes()), json.loads(statuses.read_bytes())
    if damage == "saver":
        s["saver"] = 1
    elif damage == "cli":
        s["application"] = 143
    elif damage == "bool-cli":
        s["application"] = False
    elif damage == "stderr":
        s["diagnostics"] = PRIVATE
    elif damage == "wrong-run":
        r["run_id"] = "run-" + "b" * 32
    elif damage == "numeric-accepted":
        r["accepted"] = 0
    elif damage == "report-extra":
        r["private"] = PRIVATE
    elif damage == "status-extra":
        s["private"] = PRIVATE
    elif damage == "refusal-zero":
        r = {"accepted": False, "error": "maintenance command refused or incomplete"}
    elif damage == "normal-one":
        s["application"] = 1
    elif damage == "status-bool":
        s["saver"] = False
    report.write_bytes(json.dumps(r).encode())
    statuses.write_bytes(json.dumps(s).encode())
    if damage in {"duplicate", "malformed", "empty", "oversized"}:
        report.write_bytes({"duplicate": b'{"accepted":false,"accepted":false}',
                            "malformed": b"\xff", "empty": b"",
                            "oversized": b"PRIVATE" * 1366}[damage])
    elif damage == "missing-report":
        report.unlink()
    elif damage == "missing-status":
        statuses.unlink()
    elif damage == "hardlink":
        os.link(report, tmp_path / "alias")
    status, out = _exec(_programs(C10)[1], [report, tmp_path / "auth", statuses, RUN],
                        monkeypatch, capsys)
    assert status == 1 and json.loads(out) == {
        "accepted": False, "command": "unknown", "meaning": "application-outcome-unknown",
    }


@pytest.mark.parametrize(("failure", "refresh"), [
    ("none", "measured"), ("none", "unmeasured"),
    *[(failure, "measured") for failure in (
        "qualification", "active-run", "active", "policy", "denial-status", "denial",
        "wrongplan-status", "wrongplan", "stale", "digest", "refresh-checker",
        "refresh-checker-status", "refresh-checker-digest",
    )],
    ("none", "unexpected"),
])
def test_all_g11_h7_controls_run_even_with_measured_refresh(
    tmp_path: Path, failure: str, refresh: str,
):
    record = {"refresh": refresh, "completed": True}
    (tmp_path / "h7-g11-active.json").write_text(json.dumps(record), encoding="utf-8")
    active_digest = str(digest(EVIDENCE_DOMAIN, 1, record))
    if failure == "digest":
        active_digest = "sha256:" + "0" * 64
    block, = _blocks("C5: complete H7 and explicit checked refresh selection")
    result = _run("\n".join([
        'set -Eeuo pipefail; R=store; K=key; L=launch; W="$WORLD"; W_PRIOR=prior',
        "SERVICE=(service); LANE=(lane)",
        'check() { test "$FAILURE" != "$1"; }',
        'load_final_qualification() { check qualification; SEAL=pro/private; }',
        'service() { if test "$1" = /usr/bin/python3; then',
        'case "$6" in *"p = json.loads"*) echo policy; check policy; return ;; esac',
        'shift 4; "$TEST_PY" "$@"; return; fi',
        'test "$1 $2" = "lane startup"; case "$*" in',
        '*h7-g11-s6b-denial.json*) echo denial-run; '
        'test "$FAILURE" = denial-status && return 0; return 1 ;;',
        '*h7-g11-s6c-plan-refusal.json*) echo wrongplan-run; '
        'test "$FAILURE" = wrongplan-status && return 2; return 1 ;;',
        '*h7-g11-active.json*) echo active-run; check active-run ;;',
        '*) return 3 ;; esac; }',
        'check_evidence() { if test "$1" = active; then check active || return 1; '
        'echo "$ACTIVE_DIGEST"; elif test "$1" = refresh; then '
        'test "$FAILURE" = refresh-checker-status && return 2; '
        'test "$FAILURE" = refresh-checker && return 1; test "$REFRESH" = measured || return 1; '
        'if test "$FAILURE" = refresh-checker-digest; then echo different-digest; '
        'else echo "$ACTIVE_DIGEST"; fi; '
        'else check "$1"; fi; }',
        'binding_check() { test "$*" = '
        '"prior/g10.sealed.json stale-generation $W/g11.sealed.json"; '
        'check stale; echo g10-stale; }',
        block, "echo H8-review-permitted",
    ]), FAILURE=failure, REFRESH=refresh, WORLD=tmp_path.as_posix(),
        TEST_PY=Path(sys.executable).as_posix(), ACTIVE_DIGEST=active_digest)
    passes = failure == "none" and refresh in {"measured", "unmeasured"}
    assert (result.returncode == 0) is passes, result.stderr
    if passes:
        assert result.stdout.splitlines() == ["active-run", "refresh-" + refresh,
                                             "policy", "denial-run", "wrongplan-run", "g10-stale",
                                             "H8-review-permitted"]
    else:
        assert "g10-stale" not in result.stdout
        assert "H8-review-permitted" not in result.stdout
        if failure in {"digest", "refresh-checker", "refresh-checker-status",
                       "refresh-checker-digest"}:
            assert "refresh-unmeasured" not in result.stdout
    assert "--request-refresh" not in block


@pytest.mark.parametrize(("installed", "replacement", "exit_code"), (
    (True, False, "0"), (False, False, "0"), (True, True, "0"),
    (1, False, "0"), (True, False, "1"),
))
def test_kept_launch_requires_exact_flags_and_emits_only_marker(
    tmp_path, monkeypatch, capsys, installed, replacement, exit_code,
):
    path = tmp_path / "verify.json"
    path.write_text(json.dumps({"installed": installed, "replacement": replacement,
                                "private": PRIVATE}), encoding="utf-8")
    program, = PYTHON_PROGRAM.findall(_blocks(C2)[1])
    passes = installed is True and replacement is False and exit_code == "0"
    if passes:
        status, out = _exec(program, [path, exit_code], monkeypatch, capsys)
        assert status == 0 and out == "kept-launch-verified\n"
    else:
        with pytest.raises(AssertionError):
            _exec(program, [path, exit_code], monkeypatch, capsys)
        assert capsys.readouterr().out == ""


@pytest.mark.parametrize("damage", ("none", "occupied", "missing", "linked", "oversized"))
def test_d2_archive_uses_fresh_destination_and_preserves_every_old_source(
    tmp_path, monkeypatch, capsys, damage,
):
    source, archive = tmp_path / "m8-host", tmp_path / "maintenance-g11-d2-prior"
    source.mkdir()
    names = ("profiles-verify", "verify.json", "qualification.json")
    for name in names:
        (source / name).write_bytes(("retained:" + name).encode())
    if damage == "occupied":
        archive.mkdir()
        (archive / "old").write_bytes(b"retained")
    elif damage == "missing":
        (source / names[0]).unlink()
    elif damage == "linked":
        os.link(source / names[0], tmp_path / "alias")
    elif damage == "oversized":
        (source / names[0]).write_bytes(b"x" * 1048577)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    program, = PYTHON_PROGRAM.findall(_blocks(C2)[0])
    if damage == "none":
        status, out = _exec(_portable(program), [source, archive], monkeypatch, capsys)
        assert status == 0 and out == "g10-boot-d2-records-preserved\n"
        assert {p.name: p.read_bytes() for p in archive.iterdir()} == before
    else:
        with pytest.raises((AssertionError, FileNotFoundError)):
            _exec(_portable(program), [source, archive], monkeypatch, capsys)
        assert capsys.readouterr().out == ""
        if damage == "occupied":
            assert (archive / "old").read_bytes() == b"retained"
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


@pytest.mark.parametrize("damage", ("none", "base", "bundle", "retained", "extra", "empty"))
def test_source_preparation_output_requires_complete_matching_pin(
    tmp_path, monkeypatch, capsys, damage,
):
    from constructicon.api._maintenance_source import SOURCE_HASHES, SourcePin

    pin = SourcePin(bundle_sha256="b" * 64, base_commit="a" * 40,
                    target_ref="refs/heads/maintenance", config_sha256="c" * 64,
                    sources=SOURCE_HASHES)
    retained = tmp_path / "source-pin.json"
    retained.write_text(pin.model_dump_json(), encoding="utf-8")
    values = pin.model_dump(mode="json")
    if damage == "base":
        values["base_commit"] = "d" * 40
    elif damage == "bundle":
        values["bundle_sha256"] = "d" * 64
    elif damage == "retained":
        retained.write_text("{}", encoding="utf-8")
    elif damage == "extra":
        values["private"] = PRIVATE
    prepared = tmp_path / "source-prepared.json"
    prepared.write_text("" if damage == "empty" else json.dumps(values), encoding="utf-8")
    if damage == "none":
        status, out = _exec(_programs(C7)[0],
                            [prepared, tmp_path, "a" * 40, "b" * 64], monkeypatch, capsys)
        assert status == 0 and json.loads(out) == {
            "source_prepared": True, "base": "a" * 40, "bundle_sha256": "b" * 64,
        }
        assert out.count("\n") == 1 and len(out.encode()) <= 256
    else:
        with pytest.raises((ValueError, AssertionError)):
            _exec(_programs(C7)[0],
                  [prepared, tmp_path, "a" * 40, "b" * 64], monkeypatch, capsys)
        assert capsys.readouterr().out == ""


@pytest.mark.parametrize("stage", (
    "success", "source", "assembly", "preview", "unknown", "private",
))
def test_actual_preflight_whitelist_and_closed_failure_stages(tmp_path, monkeypatch, capsys, stage):
    from tests.test_m8_maintenance_private_continuation import _authorization

    authorization = _authorization(tmp_path)
    preview = tmp_path / "preflight.json"
    record = (authorization.model_dump(mode="json") if stage == "success" else
              {"accepted": False, "error": "maintenance command refused or incomplete",
               "stage": stage})
    if stage == "private":
        record["stage"] = PRIVATE
        record["private"] = PRIVATE
    preview.write_bytes(json.dumps(record).encode())
    preview.chmod(0o600)
    raw = preview.read_bytes()
    status, out = _exec(_portable(_programs(C8)[0]),
                        [preview, tmp_path.as_posix(), "reviewed", "operator:test",
                         "maintenance-2", "a" * 40, "0" if stage == "success" else "1", "0"],
                        monkeypatch, capsys)
    result = json.loads(out)
    assert preview.read_bytes() == raw
    if stage == "success":
        assert status == 0 and result["preview_sha256"] == hashlib.sha256(raw).hexdigest()
        assert set(result) == {
            "preview_sha256", "run_id", "authorization_id", "base", "source_graph_hash",
            "application_revision", "revision", "operator_binding_digest", "workspace",
            "gate", "not_after", "grants",
        }
        assert str(tmp_path) not in out and len(out.encode()) <= 8192
    else:
        assert status == 1 and result == {
            "preflight": False, "stage": "unknown" if stage == "private" else stage,
        }
        assert len(out.encode()) <= 64
