"""Fake-only execution of the new continuation's stop and publication guards."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.address import ScopePath
from constructicon.core.envelope import utc_now
from constructicon.core.maintenance import (
    MaintenanceAttemptAuthorization,
    MaintenanceCapabilityPin,
    PlanManifestRequest,
)
from constructicon.substrate.executors.codex_host import WRITE_GRANTS
from tests.test_m8_maintenance_continuation import _portable
from tests.test_m8_n5_g6_session import _run
from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import PYTHON_PROGRAM, _bash

DOCUMENT = HANDOFFS / "M8-maintenance-private-continuation.md"


def _blocks(heading):
    return _fences(_section(_text(DOCUMENT), heading))


def _pin_guard(**assignments):
    guard = _blocks("C0: prepare literal pins and the new reviewed composition")[0]
    for name, value in assignments.items():
        guard, count = re.subn(r"(?m)^" + name + r"=.*$", name + "=" + value, guard)
        assert count == 1, "pin fixture must replace exactly one literal assignment"
    return guard


def _valid_fixture_pins():
    return {"C": "a" * 40, "BASE": "a" * 40, "BUNDLE_SHA256": "0" * 64,
            "BUNDLE_SIZE": "1", "BUNDLE": "/prepared.bundle"}


def _preflight_program():
    program, = PYTHON_PROGRAM.findall(_blocks(
        "C8: retain preflight and display its closed failure stage")[0])
    if os.name == "nt":
        # Only POSIX owner/mode semantics differ; real regular/link/bound reads run.
        program = program.replace("info.st_uid == os.getuid()", "info.st_uid == 0")
        program = program.replace("info.st_mode & 0o077 == 0", "True")
    return program


def _authorization(root):
    pin = "sha256:" + "0" * 64
    return MaintenanceAttemptAuthorization(authorization_id="reviewed", actor_id="operator:test",
        idempotency_key="maintenance-2", scope=ScopePath(
            segments=("constructicon-plan-manifest-maintenance", "writer")), binding="executor",
        source_graph_hash=pin, capability_id="codex-operator", revision=pin,
        operator_binding_digest=pin, journal=root.as_posix() + "/maintenance.sqlite", max_epoch=1,
        not_after=utc_now() + timedelta(hours=1), grants=WRITE_GRANTS,
        attempt_record=root.as_posix() + "/maintenance-attempt.json",
        request=PlanManifestRequest(repository=str(root / "authority.git"),
            target_ref="refs/heads/maintenance", base_commit="a" * 40,
            target_sha256="0" * 64, check_set_hash=pin), application_revision=pin,
        workspace=MaintenanceCapabilityPin(capability_id="maintenance-workspace", revision=pin),
        gate=MaintenanceCapabilityPin(capability_id="maintenance-gate", revision=pin))


def _classify(path, root, monkeypatch, capsys, cli="1", saver="0"):
    with monkeypatch.context() as patch:
        patch.setattr(sys, "argv", ["check", str(path), root.as_posix(),
                                   "reviewed", "operator:test",
                                   "maintenance-2", "a" * 40, cli, saver])
        patch.setattr(sys, "path", list(sys.path))
        status = 0
        try:
            exec(compile(_preflight_program(), "<reviewed-preflight-check>", "exec"), {})
        except SystemExit as exit:
            status = exit.code
    captured = capsys.readouterr()
    assert captured.err == ""
    return status, json.loads(captured.out), captured.out


def test_new_bash_blocks_parse_and_unprepared_pins_stop_before_actions():
    document = _text(DOCUMENT)
    for block in re.findall(r"```bash\n(.*?)```", document, re.S):
        parsed = subprocess.run([_bash(), "-n"], input=block, capture_output=True,
                                text=True, timeout=30, check=False)
        assert parsed.returncode == 0 and parsed.stdout == "" and parsed.stderr == ""
    guard = _pin_guard(C="UNPREPARED")
    stopped = _run(guard + "\necho forbidden-host-action")
    assert stopped.returncode == 1 and stopped.stdout == ""
    assert "merged controller and reviewed source pins required; stop" in stopped.stderr
    assert "W=/home/m8-service/m8-maint-q9" in document
    assert "W_PRIOR=/home/m8-service/m8-maint-q9" in document
    assert "W=/home/m8-service/m8-maint-q10" in document
    assert "m8-maint-a2" in document and "m8-m2" in document


def test_actual_prepared_pin_guard_accepts_without_host_actions():
    guard = _blocks("C0: prepare literal pins and the new reviewed composition")[0]
    checked = _run(guard + "\necho reviewed-pins-checked")
    assert checked.returncode == 0 and checked.stderr == ""
    assert checked.stdout == "reviewed-pins-checked\n"


@pytest.mark.parametrize("failure", ("base", "oversized"))
def test_pin_guard_stops_even_without_errexit(failure):
    pins = _valid_fixture_pins()
    pins["BASE" if failure == "base" else "BUNDLE_SIZE"] = (
        "b" * 40 if failure == "base" else "67108865")
    guard = _pin_guard(**pins)
    stopped = _run("set +e\n" + guard + "\necho forbidden-host-action")
    assert stopped.returncode == 1 and stopped.stdout == ""


@pytest.mark.parametrize("name", ("C", "BASE", "BUNDLE_SHA256", "BUNDLE_SIZE"))
def test_explicit_unprepared_pin_fixtures_stop_before_actions(name):
    pins = _valid_fixture_pins()
    pins[name] = "UNPREPARED"
    stopped = _run(_pin_guard(**pins) + "\necho forbidden-host-action")
    assert stopped.returncode == 1 and stopped.stdout == ""
    assert "merged controller and reviewed source pins required; stop" in stopped.stderr


@pytest.mark.parametrize("stage", ("source", "assembly", "preview", "unknown"))
def test_preflight_refusal_emits_only_closed_stage_and_preserves_preview(
    tmp_path, monkeypatch, capsys, stage,
):
    path = tmp_path / "preflight.json"
    raw = json.dumps({"accepted": False, "error": "maintenance command refused or incomplete",
                      "stage": stage}).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    status, result, out = _classify(path, tmp_path, monkeypatch, capsys)
    assert status == 1 and result == {"preflight": False, "stage": stage}
    assert path.read_bytes() == raw and len(out.encode()) <= 64


@pytest.mark.parametrize("damage", ("numeric-false", "private-error", "extra", "stage",
                                   "legacy", "duplicate", "malformed", "empty", "oversized",
                                   "cli-status", "saver-status", "missing", "hardlink"))
def test_preflight_invalid_or_incomplete_capture_stops_without_payload(
    tmp_path, monkeypatch, capsys, damage,
):
    path = tmp_path / "preflight.json"
    record = {"accepted": False, "error": "maintenance command refused or incomplete",
              "stage": "source"}
    cli, saver = "1", "0"
    if damage == "numeric-false":
        record["accepted"] = 0
    elif damage == "private-error":
        record["error"] = "PRIVATE:/credential/path:SUBPROCESS-TEXT"
    elif damage == "extra":
        record["private"] = "PRIVATE:/credential/path:SUBPROCESS-TEXT"
    elif damage == "stage":
        record["stage"] = "PRIVATE:/credential/path:SUBPROCESS-TEXT"
    elif damage == "legacy":
        del record["stage"]
    elif damage == "cli-status":
        cli = "2"
    elif damage == "saver-status":
        saver = "1"
    raw = json.dumps(record).encode()
    raw = {"duplicate": b'{"accepted":false,"accepted":false}', "malformed": b"\xff",
           "empty": b"", "oversized": b"PRIVATE" * 1366}.get(damage, raw)
    path.write_bytes(raw)
    path.chmod(0o600)
    if damage == "missing":
        path.unlink()
    elif damage == "hardlink":
        os.link(path, tmp_path / "alias")
    status, result, out = _classify(path, tmp_path, monkeypatch, capsys, cli, saver)
    assert status == 1 and result == {"preflight": False, "stage": "unknown"}
    assert "PRIVATE" not in out and len(out.encode()) <= 64
    if path.exists():
        assert path.read_bytes() == raw


def test_preflight_success_keeps_original_pin_whitelist_and_private_locators(
    tmp_path, monkeypatch, capsys,
):
    path = tmp_path / "preflight.json"
    raw = _authorization(tmp_path).model_dump_json().encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    status, result, out = _classify(path, tmp_path, monkeypatch, capsys, "0", "0")
    assert status == 0 and result["preview_sha256"] == hashlib.sha256(raw).hexdigest()
    assert set(result) == {"preview_sha256", "run_id", "authorization_id", "base",
                          "source_graph_hash", "application_revision", "revision",
                          "operator_binding_digest", "workspace", "gate", "not_after", "grants"}
    assert str(tmp_path) not in out and path.read_bytes() == raw


@pytest.mark.parametrize(("cli", "saver"), ((0, 0), (1, 0), (0, 1), (1, 1)))
def test_preflight_pipeline_records_both_statuses_before_any_command(tmp_path, cli, saver):
    block = _blocks("C8: retain preflight and display its closed failure stage")[0]
    capture = block.split('"${SERVICE[@]}" /usr/bin/python3', 1)[0]
    prefix = '\n'.join((
        "set -Eeuo pipefail; umask 077; SERVICE=(); ENTRY=(entry); HOST=()",
        "APP=fake; ID=i; ACTOR=a; KEY=k",
        'S="$TEST_OUT"',
        'entry() { printf "retained-private-preview\\n"; return "$CLI_STATUS"; }',
        'save_sealed() { /usr/bin/cat >"$1"; return "$SAVER_STATUS"; }',
    ))
    ran = _run(prefix + "\n" + capture + '\nprintf "%s %s\\n" "${P8_STATUS[0]}" "${P8_STATUS[1]}"',
               TEST_OUT=tmp_path.as_posix(), CLI_STATUS=str(cli), SAVER_STATUS=str(saver))
    assert ran.returncode == 0 and ran.stderr == "" and ran.stdout == f"{cli} {saver}\n"
    assert (tmp_path / "preflight.json").read_bytes() == b"retained-private-preview\n"


def test_kept_launch_profile_read_failure_stops_before_verifier(tmp_path):
    block = _blocks("C2: preserve current D2 records and verify the kept launch")[1]
    prefix = '\n'.join((
        "set +e; C=" + "a" * 40,
        'W="$TEST_OUT"',
        'sudo() { return 1; }',
    ))
    ran = _run(prefix + "\n" + block + "\necho forbidden-controller-step",
               TEST_OUT=tmp_path.as_posix())
    assert ran.returncode == 1 and ran.stdout == ""
    assert not (tmp_path / "verify.json").exists()


@pytest.mark.parametrize("floor", (9, 8, True, 9.0, None))
def test_generation_ten_publication_requires_both_strict_floor_nine_records(tmp_path, floor):
    for name in ("s4-qualification.json", "s6a-qualification.json"):
        (tmp_path / name).write_text(json.dumps({
            "custody": {"kind": "maintenance", "generation_floor": floor},
        }), encoding="utf-8")
    block = _blocks("C4: checked floor 9, publish and activate g10")[0]
    block = block.replace("/usr/bin/python3", '"$TEST_PY"')
    prefix = '\n'.join((
        "set -Eeuo pipefail; SERVICE=(); ROOT_STORE=(store); R=r; K=k",
        'W="$TEST_OUT"; W_PRIOR=historical-q9',
        'load_final_qualification() { Q=qualified; }',
        'store() { printf "%s\\n" "$*" >>"$TEST_OUT/store-calls"; printf "{}\\n"; }',
        'save_sealed() { /usr/bin/cat >"$1"; }',
        'check_sealed() { return 0; }',
        'binding_check() { return 0; }',
    ))
    ran = _run(prefix + "\n" + block, TEST_OUT=tmp_path.as_posix(),
               TEST_PY=Path(sys.executable).as_posix())
    calls = tmp_path / "store-calls"
    if type(floor) is int and floor == 9:
        assert ran.returncode == 0 and ran.stderr == ""
        assert len(calls.read_text().splitlines()) == 2
        assert all("--generation 10" in call for call in calls.read_text().splitlines())
    else:
        assert ran.returncode != 0 and not calls.exists()
        assert not (tmp_path / "g10.sealed.json").exists()


def test_every_h7_control_matches_existing_law_with_only_literal_generation_changes():
    original, = _fences(_section(_text(HANDOFFS / "M8-maintenance-session.md"),
        "P5: every H7 control, even when refresh is measured"))
    current, = _blocks("C5: complete H7 and explicit checked refresh selection")
    assert current == original.replace("g9", "g10").replace("g8", "g9")


def test_application_delegates_command_fences_with_explicit_current_generation_prerequisite():
    section = _section(_text(DOCUMENT),
        "C9/C10: exact reviewed authority, one attempt and park")
    assert "P9/P10 command fences verbatim" in section
    assert "repeat HS H2, load_final_qualification, g10 accepted/check_sealed" in section
    assert "recorded boot/custody check and unchanged approved literal preview digest" in section
    assert "historical g9 prerequisite is not delegated" in section


@pytest.mark.parametrize("failure", ("none", "anchor", "qualification", "seal", "plan"))
def test_retained_capture_is_compared_only_after_current_g9_historical_checks(tmp_path, failure):
    path = tmp_path / "maintenance-g9-account.seal"
    raw = b"pro/private-fake-identity\n"
    path.write_bytes(raw)
    path.chmod(0o600)
    blocks = _blocks("C1: one fresh boot, historical g9 and the retained capture")
    block, = blocks
    program, = PYTHON_PROGRAM.findall(block)
    block = block.replace(program, _portable(program)).replace("/usr/bin/python3", '"$TEST_PY"')
    prefix = '\n'.join((
        "set -Eeuo pipefail; W=historical-q9",
        'binding_check() { test "$*" = "historical-q9/g9.sealed.json reboot-anchor -"; '
        'test "$FAILURE" != anchor; }',
        'load_final_qualification() { test "$FAILURE" != qualification; Q=q; '
        'SEAL="$FAKE_SEAL"; }',
        'check_sealed() { test "$*" = "historical-q9/g9.sealed.json q"; '
        'test "$FAILURE" != seal; }',
    ))
    ran = _run(prefix + "\n" + block, HOME=tmp_path.as_posix(), FAILURE=failure,
               TEST_PY=Path(sys.executable).as_posix(),
               FAKE_SEAL="plus/private-fake-identity" if failure == "plan"
               else "pro/private-fake-identity")
    assert path.read_bytes() == raw
    if failure == "none":
        assert ran.returncode == 0 and ran.stderr == ""
        assert ran.stdout == "historical-g9-account-capture-revalidated\n"
    else:
        assert ran.returncode != 0 and ran.stdout == ""


@pytest.mark.parametrize("change", ("atime", "mode", "mtime"))
def test_archive_reads_allow_atime_change_but_refuse_custody_or_content_metadata_change(
    tmp_path, monkeypatch, capsys, change,
):
    source, archive = tmp_path / "m8-host", tmp_path / "new-archive"
    source.mkdir()
    for name in ("profiles-verify", "verify.json", "qualification.json"):
        (source / name).write_bytes(b"retained-fake-record")
    program, = PYTHON_PROGRAM.findall(_blocks(
        "C2: preserve current D2 records and verify the kept launch")[0])
    if os.name == "nt":
        program = program.replace("os.O_NOFOLLOW", "0").replace("os.O_NONBLOCK", "0")
    original = Path.lstat
    observed = []

    def lstat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == source / "profiles-verify":
            observed.append(path)
            if len(observed) == 2:
                fields = {field: getattr(info, field) for field in dir(info)
                          if field.startswith("st_")}
                if change == "atime":
                    fields["st_atime_ns"] += 100
                elif change == "mode":
                    fields["st_mode"] ^= 0o020
                else:
                    fields["st_mtime_ns"] += 100
                return SimpleNamespace(**fields)
        return info

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(sys, "argv", ["preserve", str(source), str(archive)])
    if change == "atime":
        exec(compile(program, "<reviewed-archive>", "exec"), {})
        captured = capsys.readouterr()
        assert captured.out == "g9-boot-d2-records-preserved\n" and captured.err == ""
        assert (archive / "profiles-verify").read_bytes() == b"retained-fake-record"
    else:
        with pytest.raises(AssertionError):
            exec(compile(program, "<reviewed-archive>", "exec"), {})
        assert not archive.exists() and capsys.readouterr().out == ""
