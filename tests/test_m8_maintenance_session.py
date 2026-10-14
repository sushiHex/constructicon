"""Execute the maintenance successor's guards with credential-free boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

import pytest
from scripts.ci import m8_host_artifacts

from constructicon.core.address import ScopePath
from constructicon.core.identity import digest
from constructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN
from constructicon.substrate.executors.egress import MAX_SOCKET_PATH_BYTES, SOCKET_NAME
from constructicon.substrate.git.acquisition import AcquisitionPaths
from tests.core.test_maintenance_authorization import GRAPH, authorization
from tests.test_m8_n5_g6_session import SEAL, _run
from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import PYTHON_PROGRAM, _bash, _run_isolated

DOCUMENT = HANDOFFS / "M8-maintenance-session.md"


def _blocks(heading: str) -> list[str]:
    return [block.strip() for block in _fences(_section(_text(DOCUMENT), heading))]


def _program(heading: str) -> str:
    found = PYTHON_PROGRAM.findall("\n".join(_blocks(heading)))
    assert found
    return found[-1]


def _python(program: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", program, *args], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=30, check=False)


def test_all_blocks_parse_with_real_common_and_named_delegates():
    operator = _text(HANDOFFS / "M8-N4-operator-commands.md")
    common = "\n".join(_fences(operator.split("## Setup", 1)[1].split("\n### ", 1)[0]))
    delegated = []
    for filename, heading in (
        ("M8-N4-operator-commands.md", "S1. Prepare"),
        ("M8-N4-operator-commands.md", "S4. Qualification"),
        ("M8-N4-operator-commands.md", "S6a. Maintenance-lock positive control"),
        ("M8-N5-host-session.md", "H2. S0 at `C`"),
        ("M8-N5-explicit-refresh.md", "Operator procedure after separately authorized deployment"),
    ):
        delegated.extend(_fences(_section(_text(HANDOFFS / filename), heading)))
    text = _text(DOCUMENT)
    # PowerShell has a distinct native surface; only bash fences enter bash -n.
    bash = re.findall(r"```bash\n(.*?)```", text, re.S)
    for block in [*bash, *delegated]:
        ran = subprocess.run([_bash(), "-n"], input=common + "\n" + block,
                             capture_output=True, text=True, timeout=30, check=False)
        assert ran.returncode == 0, ran.stderr


@pytest.mark.parametrize(("controller", "base", "bundle_hash", "bundle", "passes"), [
    ("a" * 40, "b" * 40, "c" * 64, "/private/reviewed.bundle", True),
    ("UNMERGED", "b" * 40, "c" * 64, "/private/reviewed.bundle", False),
    ("a" * 39, "b" * 40, "c" * 64, "/private/reviewed.bundle", False),
    ("a" * 40, "UNPINNED", "c" * 64, "/private/reviewed.bundle", False),
    ("a" * 40, "b" * 40, "UNPINNED", "/private/reviewed.bundle", False),
    ("a" * 40, "b" * 40, "c" * 64, "/home/m8-service/UNPREPARED.bundle", False),
])
def test_pin_guard_accepts_concrete_pins_and_refuses_placeholders_before_transport(
    controller: str, base: str, bundle_hash: str, bundle: str, passes: bool,
):
    guard = _blocks("P0: pins, custody and reviewed composition")[0]
    guard = guard[guard.index('[[ "$C"'):]
    result = _run('C="$PIN_C"; BASE="$PIN_BASE"; BUNDLE_SHA256="$PIN_HASH"; BUNDLE="$PIN_BUNDLE"\n'
                  + guard + "\necho transport-permitted", PIN_C=controller, PIN_BASE=base,
                  PIN_HASH=bundle_hash, PIN_BUNDLE=bundle)
    assert (result.returncode == 0) is passes
    assert result.stdout == ("transport-permitted\n" if passes else "")


@pytest.mark.parametrize(("pins", "state", "checkpoints", "passes"), [
    (True, "Off", 0, True), (False, "Off", 0, False),
    (True, "Running", 0, False), (True, "Off", 1, False),
])
def test_native_start_guard_requires_prepared_pins_off_and_zero_checkpoints(
    pins: bool, state: str, checkpoints: int, passes: bool,
):
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if executable is None:
        pytest.skip("PowerShell is required for this native VM-command syntax proof")
    found = re.search(r"```powershell\n(.*?)```", _text(DOCUMENT), re.S)
    assert found is not None
    block = found[1]
    if pins:
        block = block.replace("'UNMERGED'", "'" + "a" * 40 + "'")
        block = block.replace("$maintenanceBase = 'UNPINNED'",
                              "$maintenanceBase = '" + "b" * 40 + "'")
        block = block.replace("$maintenanceBundleSha256 = 'UNPINNED'",
                              "$maintenanceBundleSha256 = '" + "c" * 64 + "'")
    script = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "function Get-VM { [pscustomobject]@{ State = '" + state + "' } }",
        "function Get-VMSnapshot { " + ("[pscustomobject]@{}" if checkpoints else "") + " }",
        "function Start-VM { 'fake-start-observed' }", block,
    ])
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-Command", script],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=30, check=False)
    assert (result.returncode == 0) is passes, result.stderr
    assert result.stdout.strip() == ("fake-start-observed" if passes else "")


@pytest.mark.parametrize("failure", ["none", "anchor", "qualification", "seal", "plan", "occupied"])
def test_already_off_capture_requires_specific_anchor_and_historical_evidence(
    tmp_path: Path, failure: str,
):
    capture = _blocks("P1: already Off, one fresh start and historical continuity")[-1]
    path = tmp_path / "maintenance-g9-account.seal"
    if failure == "occupied":
        path.write_text("preserved\n", encoding="utf-8")
    result = _run("\n".join([
        "set -Eeuo pipefail; umask 077; W=historical",
        'binding_check() { test "$*" = "historical/g8.sealed.json reboot-anchor -"; '
        'test "$FAILURE" != anchor; }',
        'load_final_qualification() { test "$FAILURE" != qualification; Q=q; SEAL="$FAKE_SEAL"; }',
        'check_sealed() { test "$*" = "historical/g8.sealed.json q"; test "$FAILURE" != seal; }',
        capture, "echo captured",
    ]), HOME=tmp_path.as_posix(), FAILURE=failure,
        FAKE_SEAL="plus/private" if failure == "plan" else SEAL)
    assert (result.returncode == 0) is (failure == "none"), result.stderr
    assert result.stdout == ("captured\n" if failure == "none" else "")
    if failure == "none":
        assert path.read_text(encoding="utf-8") == SEAL + "\n"
    elif failure == "occupied":
        assert path.read_text(encoding="utf-8") == "preserved\n"
    else:
        assert not path.exists()
    assert 'accepted -' not in capture


@pytest.mark.parametrize("failure", [
    "none", "missing-profiles", "missing-verify", "missing-qualification",
    "symlink", "occupied", "archive-link", "corrupt-copy",
])
def test_d2_preservation_copies_fixed_records_before_lr2_without_overwrite(
    tmp_path: Path, failure: str,
):
    world = tmp_path / "m8-host"
    world.mkdir()
    names = ("profiles-verify", "verify.json", "qualification.json")
    for name in names:
        (world / name).write_bytes(("historical-" + name).encode())
    missing = {
        "missing-profiles": "profiles-verify", "missing-verify": "verify.json",
        "missing-qualification": "qualification.json",
    }
    if failure in missing:
        (world / missing[failure]).unlink()
    archive = tmp_path / "maintenance-g9-d2-prior"
    if failure == "occupied":
        archive.mkdir()
        (archive / "verify.json").write_bytes(b"preserved-archive")
    if os.name != "nt" and failure == "symlink":
        linked = tmp_path / "linked-record.json"
        linked.write_bytes((world / "verify.json").read_bytes())
        (world / "verify.json").unlink()
        (world / "verify.json").symlink_to(linked)
    if os.name != "nt" and failure == "archive-link":
        archive.symlink_to(tmp_path / "absent-archive", target_is_directory=True)
    block, = _blocks("P2: D2 fresh-boot physical qualification and normal LR")
    # Git Bash cannot prove Linux chmod or native Windows symlink creation.
    # Substitute only mkdir's mode and the link predicate, retaining real
    # source files, copies, cmp, archive guards and fail-fast shell execution.
    block = block.replace("/usr/bin/mkdir -m 0700 --", "/usr/bin/mkdir --")
    if os.name == "nt" and failure in {"symlink", "archive-link"}:
        target = (world / "verify.json") if failure == "symlink" else archive
        block = block.replace("test -L", "is_link")
        link_boundary = (
            'is_link() { test "$(cygpath -m "$1")" = '
            '"$(cygpath -m "$SIMULATED_LINK")"; }'
        )
    else:
        target = tmp_path / "unused-link"
        link_boundary = ""
    if failure == "corrupt-copy":
        block = block.replace("/usr/bin/cp -p --no-clobber --", "corrupt_copy")
    before = {path: (path.read_bytes(), path.lstat().st_ino, path.lstat().st_mode)
              for path in world.iterdir()}
    archive_before = (
        {path: path.read_bytes() for path in archive.glob("*")} if archive.exists() else {}
    )
    result = _run("\n".join([
        link_boundary,
        'corrupt_copy() { /usr/bin/cp -- "$1" "$2"; printf corrupted > "$2"; }',
        block, "echo LR2-permitted",
    ]), HOME=tmp_path.as_posix(), SIMULATED_LINK=target.as_posix())
    assert (result.returncode == 0) is (failure == "none"), result.stderr
    assert {path: (path.read_bytes(), path.lstat().st_ino, path.lstat().st_mode)
            for path in world.iterdir()} == before
    if failure == "none":
        assert result.stdout.splitlines() == ["d2-prior-records-preserved", "LR2-permitted"]
        assert {path.name: path.read_bytes() for path in archive.iterdir()} == {
            path.name: facts[0] for path, facts in before.items()
        }
    else:
        assert "LR2-permitted" not in result.stdout
        assert "d2-prior-records-preserved" not in result.stdout
        if failure in {"missing-profiles", "missing-verify", "missing-qualification", "symlink"}:
            assert not archive.exists()
    assert {path: path.read_bytes() for path in archive_before} == archive_before


@pytest.mark.parametrize("record", ["s4", "s6a"])
@pytest.mark.parametrize("floor", [8, True, 8.0, 7, 9, None])
def test_both_strict_floors_bind_before_publication(tmp_path: Path, record: str, floor: object):
    for name in ("s4", "s6a"):
        custody = {"kind": "maintenance", "generation_floor": floor if name == record else 8}
        if floor is None and name == record:
            custody.pop("generation_floor")
        (tmp_path / (name + "-qualification.json")).write_text(
            json.dumps({"custody": custody}), encoding="utf-8",
        )
    block, = _blocks("P4: checked maintenance floor 8, publish and activate g9")
    program = block[:block.index('"${ROOT_STORE[@]}" publish')]
    result = _run("\n".join([
        'set -Eeuo pipefail; W="$WORLD"; SERVICE=(service)',
        'load_final_qualification() { :; }',
        'service() { test "$1" = /usr/bin/python3; shift; "$TEST_PY" "$@"; }',
        program, "echo publication-permitted",
    ]), WORLD=tmp_path.as_posix(), TEST_PY=sys.executable)
    passes = type(floor) is int and floor == 8
    assert (result.returncode == 0) is passes, result.stderr
    assert result.stdout == ("publication-permitted\n" if passes else "")
    assert '--generation 9' in block
    assert 'binding_check "$W_PRIOR/g8.sealed.json" stale-generation "$W/g9.sealed.json"' in block


@pytest.mark.parametrize(("failure", "refresh"), [
    ("none", "measured"), ("none", "unmeasured"),
    *[(failure, "measured") for failure in (
        "qualification", "active-run", "active", "policy", "denial-status", "denial",
        "wrongplan-status", "wrongplan", "stale", "digest", "refresh-checker",
        "refresh-checker-status", "refresh-checker-digest",
    )],
    ("none", "unexpected"),
])
def test_all_h7_controls_run_even_with_measured_refresh(
    tmp_path: Path, failure: str, refresh: str,
):
    record = {"refresh": refresh, "completed": True}
    (tmp_path / "h7-g9-active.json").write_text(json.dumps(record), encoding="utf-8")
    active_digest = str(digest(EVIDENCE_DOMAIN, 1, record))
    if failure == "digest":
        active_digest = "sha256:" + "0" * 64
    block, = _blocks("P5: every H7 control, even when refresh is measured")
    result = _run("\n".join([
        'set -Eeuo pipefail; R=store; K=key; L=launch; W="$WORLD"; W_PRIOR=prior',
        "SERVICE=(service); LANE=(lane)",
        'check() { test "$FAILURE" != "$1"; }',
        'load_final_qualification() { check qualification; SEAL=pro/private; }',
        'service() { if test "$1" = /usr/bin/python3; then',
        'case "$6" in *"p = json.loads"*) echo policy; check policy; return ;; esac',
        'shift 4; "$TEST_PY" "$@"; return; fi',
        'test "$1 $2" = "lane startup"; case "$*" in',
        '*h7-g9-s6b-denial.json*) echo denial-run; '
        'test "$FAILURE" = denial-status && return 0; return 1 ;;',
        '*h7-g9-s6c-plan-refusal.json*) echo wrongplan-run; '
        'test "$FAILURE" = wrongplan-status && return 2; return 1 ;;',
        '*h7-g9-active.json*) echo active-run; check active-run ;;',
        '*) return 3 ;; esac; }',
        'check_evidence() { if test "$1" = active; then check active || return 1; '
        'echo "$ACTIVE_DIGEST"; elif test "$1" = refresh; then '
        'test "$FAILURE" = refresh-checker-status && return 2; '
        'test "$FAILURE" = refresh-checker && return 1; test "$REFRESH" = measured || return 1; '
        'if test "$FAILURE" = refresh-checker-digest; then echo different-digest; '
        'else echo "$ACTIVE_DIGEST"; fi; '
        'else check "$1"; fi; }',
        'binding_check() { test "$*" = '
        '"prior/g8.sealed.json stale-generation $W/g9.sealed.json"; '
        'check stale; echo g8-stale; }',
        block, "echo H8-review-permitted",
    ]), FAILURE=failure, REFRESH=refresh, WORLD=tmp_path.as_posix(),
        TEST_PY=Path(sys.executable).as_posix(), ACTIVE_DIGEST=active_digest)
    passes = failure == "none" and refresh in {"measured", "unmeasured"}
    assert (result.returncode == 0) is passes, result.stderr
    if passes:
        assert result.stdout.splitlines() == ["active-run", "refresh-" + refresh,
                                             "policy", "denial-run", "wrongplan-run", "g8-stale",
                                             "H8-review-permitted"]
    else:
        assert "g8-stale" not in result.stdout
        assert "H8-review-permitted" not in result.stdout
        if failure in {"digest", "refresh-checker", "refresh-checker-status",
                       "refresh-checker-digest"}:
            assert "refresh-unmeasured" not in result.stdout
    assert "--request-refresh" not in block


@pytest.mark.parametrize("case", [
    "measured", "unmeasured", "unexpected", "missing", "bool", "mismatch",
    "malformed", "duplicate", "oversized",
])
def test_refresh_selector_requires_explicit_verdict_in_the_exact_bounded_record(
    tmp_path: Path, case: str,
):
    record = {"refresh": case if case in {"measured", "unmeasured", "unexpected"}
              else "unmeasured", "completed": True}
    if case == "missing":
        record.pop("refresh")
    elif case == "bool":
        record["refresh"] = False
    elif case == "oversized":
        record["padding"] = "x" * 1048576
    raw = json.dumps(record)
    if case == "malformed":
        raw = "not-json"
    elif case == "duplicate":
        raw = '{"refresh":"measured","refresh":"unmeasured","completed":true}'
    path = tmp_path / "active.json"
    path.write_text(raw, encoding="utf-8")
    expected = str(digest(EVIDENCE_DOMAIN, 1, record))
    if case == "mismatch":
        expected = "sha256:" + "0" * 64
    block, = _blocks("P5: every H7 control, even when refresh is measured")
    program = PYTHON_PROGRAM.findall(block)[0]
    result = _python(program, str(path), expected)
    passes = case in {"measured", "unmeasured"}
    assert (result.returncode == 0) is passes, result.stderr
    assert result.stdout == (case + "\n" if passes else "")


def test_cli_flags_exist_and_native_state_path_is_bounded():
    text = _text(DOCUMENT)
    for command in ("prepare", "preflight", "run", "inspect"):
        matches = re.findall(rf'"\$\{{ENTRY\[@\]\}}" {command} (.*?)< /dev/null', text, re.S)
        assert matches
        offered = _run_isolated("constructicon.api.maintenance_entry", command, "--help")
        assert offered.returncode == 0, offered.stderr
        for flag in re.findall(r"--[a-z][a-z-]+", "\n".join(matches)):
            assert flag in offered.stdout, (command, flag)
    declarations = _blocks("P7: installed entry, fresh closure and reviewed application source")[0]
    state = re.search(r"^S=(.*)$", declarations, re.M)
    assert state is not None
    socket = AcquisitionPaths(
        PurePosixPath(state[1]) / "acquisitions", "acq-" + "0" * 32,
    ).payload / SOCKET_NAME
    assert len(os.fsencode(socket)) <= MAX_SOCKET_PATH_BYTES
    assert '--qualification "$W/s6a-qualification.json"' in declarations


def test_fresh_authority_is_outside_the_exact_launch_entry_inventory():
    declarations = _blocks("P7: installed entry, fresh closure and reviewed application source")[0]
    authority = re.search(r"^A=(.*)$", declarations, re.M)
    assert authority is not None
    path = PurePosixPath(authority[1])
    launch = PurePosixPath("/" + m8_host_artifacts.LAUNCH)
    assert path.parent.parent == PurePosixPath("/var/lib")
    assert not path.is_relative_to(launch)
    for qualification in (None, {"dev": 1, "ino": 2}):
        entries = m8_host_artifacts.launch_entries(qualification, installed=True)
        assert entries == set(m8_host_artifacts.LAUNCH_ENTRIES) | (
            {m8_host_artifacts.QUALIFICATION} if qualification is not None else set()
        )
        assert path.parent.name not in entries
    install, = _blocks("P9: install exact reviewed preview as fresh root authority")
    assert "_open_trusted_directory(Path(sys.argv[3]).parent.parent)" in install
    assert '\"$S/preflight.json\" \"$PREVIEW_SHA256\" \"$A\"' in install


def _preview(tmp_path: Path, **changes: object) -> Path:
    app = "/private/application"
    a = authorization(
        authorization_id="fixed", actor_id="operator:maintenance-1",
        idempotency_key="maintenance-1",
        scope=ScopePath(segments=("constructicon-plan-manifest-maintenance", "writer")),
        capability_id="codex-operator", journal=app + "/maintenance.sqlite",
        attempt_record=app + "/maintenance-attempt.json",
        not_after=datetime.now(UTC) + timedelta(hours=1),
        workspace={"capability_id": "maintenance-workspace", "revision": GRAPH},
        gate={"capability_id": "maintenance-gate", "revision": GRAPH},
    )
    value = {**a.model_dump(mode="json"), **changes}
    path = tmp_path / "preview.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_preflight_review_accepts_real_wire_shape_and_omits_private_locators(tmp_path: Path):
    preview = _preview(tmp_path)
    result = _python(_program("P8: genuine-provider preflight and exact private preview"),
                     str(preview), "/private/application", "fixed", "operator:maintenance-1",
                     "maintenance-1", "a" * 40)
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record["run_id"].startswith("run-") and record["preview_sha256"]
    assert "/private/" not in result.stdout
    assert "journal" not in record and "attempt_record" not in record


@pytest.mark.parametrize(
    "damage", ["none", "base", "bundle", "retained", "missing-source", "empty"],
)
def test_prepare_requires_matching_bounded_positive_source_pin(tmp_path: Path, damage: str):
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
    elif damage == "missing-source":
        values["sources"] = {}
    elif damage == "retained":
        retained.write_text("{}", encoding="utf-8")
    prepared = tmp_path / "source-prepared.json"
    prepared.write_text("" if damage == "empty" else json.dumps(values), encoding="utf-8")
    result = _python(_program("P7: installed entry, fresh closure and reviewed application source"),
                     str(prepared), str(tmp_path), "a" * 40, "b" * 64)
    assert (result.returncode == 0) is (damage == "none"), result.stderr
    if damage != "none":
        assert result.stdout == ""
    else:
        assert json.loads(result.stdout)["source_prepared"] is True


@pytest.mark.parametrize("changes", [
    {"purpose": "qualification-write"}, {"max_epoch": True}, {"journal": "/other"},
    {"attempt_record": "/other"}, {"capability_id": "other"}, {"binding": "other"},
    {"not_after": "2000-01-01T00:00:00Z"}, {"actor_id": "other"},
])
def test_preflight_review_refuses_contradictory_or_expired_pins(tmp_path: Path, changes: dict):
    result = _python(_program("P8: genuine-provider preflight and exact private preview"),
                     str(_preview(tmp_path, **changes)), "/private/application", "fixed",
                     "operator:maintenance-1", "maintenance-1", "a" * 40)
    assert result.returncode != 0 and result.stdout == ""


@pytest.mark.parametrize(("outcome", "status", "passes"), [
    ("accepted", 0, True), ("rejected", 0, True), ("refused", 1, True),
    ("accepted", 1, False), ("rejected", 1, False), ("refused", 0, False),
    ("foreign", 0, False), ("empty", 0, False), ("extra", 0, False), ("bool", 0, False),
])
def test_retained_outcome_requires_affirmative_identity_and_exit_shape(
    tmp_path: Path, outcome: str, status: int, passes: bool,
):
    preview = _preview(tmp_path)
    from constructicon.core.maintenance import MaintenanceAttemptAuthorization
    a = MaintenanceAttemptAuthorization.model_validate_json(preview.read_bytes())
    record = {"accepted": outcome == "accepted", "run_id": str(a.run_id)}
    if outcome == "refused":
        record = {"accepted": False, "error": "maintenance command refused or incomplete"}
    elif outcome == "foreign":
        record["run_id"] = "run-" + "0" * 32
    elif outcome == "extra":
        record["private"] = "DO-NOT-PUBLISH"
    elif outcome == "bool":
        record["accepted"] = 1
    report = tmp_path / "report.json"
    report.write_text("" if outcome == "empty" else json.dumps(record), encoding="utf-8")
    program = _program("P10: one application run, retain verdict and park")
    # Substitute only the root-file reader, retaining the real closed contract.
    program = program.replace(
        "from constructicon.substrate.executors.maintenance import read_maintenance_authorization",
        "from constructicon.core.maintenance import MaintenanceAttemptAuthorization\n"
        "def read_maintenance_authorization(path):\n"
        "    return MaintenanceAttemptAuthorization.model_validate_json(path.read_bytes())",
    )
    result = _python(program, str(report), str(preview), str(status))
    assert (result.returncode == 0) is passes, result.stderr
    if passes:
        observed = json.loads(result.stdout)
        assert observed["accepted"] is (outcome == "accepted")
        assert observed["run_id"] == str(a.run_id)
    else:
        assert result.stdout == ""
    assert "DO-NOT-PUBLISH" not in result.stdout


@pytest.mark.parametrize("phase", ["install", "run"])
@pytest.mark.parametrize("damage", ["none", "changed-preview", "unreviewed", "occupied", "root"])
def test_approved_digest_and_fresh_paths_stop_before_install_or_dispatch(
    tmp_path: Path, phase: str, damage: str,
):
    state = tmp_path / "state"
    state.mkdir()
    preview = state / "preflight.json"
    preview.write_bytes(_preview(tmp_path).read_bytes())
    reviewed = hashlib.sha256(preview.read_bytes()).hexdigest()
    launch = tmp_path / "launch"
    launch.mkdir()
    parent = launch / "maintenance"
    authority = parent / "application-1.json"
    if phase == "run":
        parent.mkdir()
        authority.write_bytes(preview.read_bytes())
    if damage == "changed-preview":
        preview.write_bytes(preview.read_bytes() + b"\n")
    elif damage == "occupied":
        if phase == "install":
            parent.mkdir()
        else:
            (state / "application-run.json").write_bytes(b"preserved")
    elif damage == "root":
        if phase == "install":
            launch = tmp_path / "untrusted-missing-root"
            authority = launch / "maintenance" / "application-1.json"
        else:
            authority.write_bytes(b"{}")
    heading = ("P9: install exact reviewed preview as fresh root authority" if phase == "install"
               else "P10: one application run, retain verdict and park")
    block = _blocks(heading)[0]
    if damage != "unreviewed":
        block = block.replace("PREVIEW_SHA256=UNREVIEWED", "PREVIEW_SHA256=" + reviewed)
    # Substitute only physical root custody/reader and isolated installed-Python
    # bootstrap. Actual digest, shell path guards and operation ordering execute.
    # This is no POSIX owner/mode or credential-host proof.
    block = block.replace(
        "os.close(_open_trusted_directory(Path(sys.argv[3]).parent.parent))",
        "assert Path(sys.argv[3]).parent.parent.is_dir() "
        "and not Path(sys.argv[3]).parent.parent.is_symlink()",
    )
    block = block.replace(
        "from constructicon.substrate.executors.maintenance import read_maintenance_authorization",
        "from constructicon.core.maintenance import MaintenanceAttemptAuthorization\n"
        "def read_maintenance_authorization(path):\n"
        "    return MaintenanceAttemptAuthorization.model_validate_json(path.read_bytes())",
    )
    if phase == "run":
        # The verified outcome program is tested independently above. Stop the
        # fake run after an affirmative launch marker to observe dispatch count.
        block = block[:block.index('"${SERVICE[@]}" /usr/bin/python3',
                                  block.index('then RUN_EXIT=0; else RUN_EXIT=$?; fi'))]
    result = _run("\n".join([
        'set -Eeuo pipefail; S="$STATE"; A="$AUTHORITY"; L="$LAUNCH"; APP=application',
        'SERVICE=(service); ENTRY=(entry); HOST=()',
        'service() { local command="$1"; shift; case "$command" in',
        '/usr/bin/python3) shift 3; "$TEST_PY" "$@" ;;',
        '/usr/bin/test) command /usr/bin/test "$@" ;;',
        'entry) echo run >> "$TEST_LOG"; echo fake-run ;;',
        '*) return 97 ;; esac; }',
        'save_sealed() { (set -C; /usr/bin/cat > "$1"); }',
        'sudo() { test "$1" = -n; shift; case "$1" in',
        '/usr/bin/test) shift; command /usr/bin/test "$@" ;;',
        '/usr/bin/install) echo install >> "$TEST_LOG"; if test "$2" = -d; then',
        'command /bin/mkdir "${@: -1}"; else command /usr/bin/cp "${@: -2:1}" "${@: -1}"; fi ;;',
        '*) return 98 ;; esac; }', block, 'echo phase-completed',
    ]), STATE=state.as_posix(), AUTHORITY=authority.as_posix(), LAUNCH=launch.as_posix(),
        TEST_PY=Path(sys.executable).as_posix(), TEST_LOG=(tmp_path / "operations").as_posix())
    assert (result.returncode == 0) is (damage == "none"), result.stderr
    log = tmp_path / "operations"
    operations = log.read_text().splitlines() if log.exists() else []
    if damage == "none":
        assert operations == (["install", "install"] if phase == "install" else ["run"])
        if phase == "install":
            assert authority.read_bytes() == preview.read_bytes()
    else:
        assert operations == []
        assert "phase-completed" not in result.stdout


def test_single_attempt_and_controller_routes_keep_existing_authority_limits():
    text = _text(DOCUMENT)
    assert text.count('"${ENTRY[@]}" run --root') == 1
    assert "R19\nmust pass on **both routes**" in text
    assert "No R6 or drift repair" in text
    assert "No second attempt" in text
    transport = _blocks("P0: pins, custody and reviewed composition")[1]
    assert "StrictHostKeyChecking=yes" in transport and "BatchMode=yes" in transport
    assert "sha256sum --check --strict" in transport
    commands = re.findall(r"(?:ssh|scp) .*?(?=\n(?:ssh|scp)|\Z)", transport, re.S)
    assert all("< /dev/null" in command for command in commands)
