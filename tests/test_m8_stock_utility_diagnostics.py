"""Historical P2 diagnostics on Ubuntu; portable controls are explicitly synthetic."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package

from tests import test_m8_maintenance_session as historical
from tests.git_bash import git_bash
from tests.substrate._evidence_secrecy import assert_clean_evidence
from tests.substrate.test_native_codex_mediation import write_evidence

HANDOFFS = Path(__file__).resolve().parents[1] / "docs/plans/handoffs"
MARKER = b"d2-prior-records-preserved\n"
WARNING = (b"/usr/bin/cp: warning: behavior of -n is non-portable and may change in future; "
           b"use --update=none instead\n")
EVIDENCE = "n3c-stock-utility-cp.json"


def transport_program():
    document = (HANDOFFS / "M8-maintenance-q12-continuation.md").read_bytes().decode()
    body, = [body for kind, body in package.fences(
        package.section(document, "Q6: transport T5")) if kind == "python"]
    return body


def preservation_program():
    document = (HANDOFFS / "M8-maintenance-session.md").read_bytes().decode()
    body, = [body for kind, body in package.fences(package.section(
        document, "P2: D2 fresh-boot physical qualification and normal LR")) if kind == "bash"]
    return body


def prior_files(tmp_path):
    source = tmp_path / "m8-host"
    source.mkdir()
    names = ("profiles-verify", "verify.json", "qualification.json")
    before = {name: f"synthetic prior record: {name}\n".encode() for name in names}
    for name, raw in before.items():
        (source / name).write_bytes(raw)
    return source, before


def through_transport(tmp_path, argv, *, home=None):
    checker = tmp_path / "transport.py"
    checker.write_bytes(transport_program().encode())
    expected = tmp_path / "expected.json"
    expected.write_bytes(json.dumps({
        "alternatives": [[MARKER.decode().rstrip("\n")]], "record": None,
    }).encode())
    next_step = tmp_path / "next-step"
    command = shlex.join([
        Path(sys.executable).as_posix(), "-I", "-S", "-B", checker.as_posix(),
        (tmp_path / "capture").as_posix(), expected.as_posix(), "--", *argv,
    ]) + " && printf entered > " + shlex.quote(next_step.as_posix())
    result = subprocess.run(
        [git_bash(), "-c", command], stdin=subprocess.DEVNULL,
        capture_output=True, timeout=30, check=False,
        env={**os.environ, "LC_ALL": "C", **({"HOME": str(home)} if home else {})},
    )
    status = json.loads((tmp_path / "capture.status.json").read_bytes())
    return (result, (tmp_path / "capture.stdout").read_bytes(),
            (tmp_path / "capture.stderr").read_bytes(), status, next_step.exists())


@pytest.mark.parametrize("warning", [False, True])
def test_preservation_success_with_three_synthetic_warnings_cannot_continue(tmp_path, warning):
    source, before = prior_files(tmp_path)
    # Substitute only cp's option/diagnostic boundary. Copies, cmp and original
    # archive guards remain real. This is not an observed coreutils warning.
    copy = "copy_boundary() { /usr/bin/cp -p -- \"$@\"; "
    copy += ("printf %s " + shlex.quote(WARNING.decode()) + " >&2; ") if warning else ""
    copy += "}\n"
    body = preservation_program()
    assert body.count("/usr/bin/cp -p --no-clobber --") == 1
    script = tmp_path / "p2.sh"
    script.write_bytes((copy + body.replace(
        "/usr/bin/cp -p --no-clobber --", "copy_boundary")).encode())
    result, out, err, status, continued = through_transport(
        tmp_path, [git_bash(), script.as_posix()], home=tmp_path)
    assert (out, err, status) == (MARKER, WARNING * 3 if warning else b"", {"returncode": 0})
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    archive = tmp_path / "maintenance-g9-d2-prior"
    assert {p.name: p.read_bytes() for p in archive.iterdir()} == before
    assert (result.returncode, result.stdout, result.stderr) == (
        (0, b"transport-step-checked 0\n", b"") if not warning
        else (1, b"transport-step-refused\n", b""))
    assert continued is (not warning)


def test_historical_copy_test_does_not_observe_success_stderr(tmp_path, monkeypatch):
    original = historical._run
    observed = []

    def run(script, **environment):
        # Reproduce the test omission independently of this platform's cp version.
        result = original("printf 'synthetic utility warning\\n' >&2\n" + script, **environment)
        observed.append(result)
        return result

    monkeypatch.setattr(historical, "_run", run)
    historical.test_d2_preservation_copies_fixed_records_before_lr2_without_overwrite(
        tmp_path, "none")
    result, = observed
    assert (result.returncode, result.stdout) == (
        0, MARKER.decode() + "LR2-permitted\n")
    assert result.stderr in {
        "synthetic utility warning\n", "synthetic utility warning\n" + WARNING.decode() * 3,
    }


def require_stock_utility_lane():
    assert sys.platform == "linux", "required stock-utility probe needs Linux"
    release = platform.freedesktop_os_release()
    assert (release["ID"], release["VERSION_ID"]) == ("ubuntu", "24.04")
    assert os.getuid() != 0, "stock utilities need only an unprivileged scratch directory"
    directory = os.environ.get("M8_EVIDENCE_DIRECTORY")
    assert directory and Path(directory).is_dir(), "required stock-utility evidence is missing"
    return Path(directory)


def test_ubuntu_stock_cp_preserves_bytes_but_fails_clean_diagnostics(tmp_path):
    if os.environ.get("M8_STOCK_UTILITIES_REQUIRED") != "1":
        pytest.skip("actual Ubuntu 24.04 stock-utility observation requires its dedicated lane")
    directory = require_stock_utility_lane()
    source, before = prior_files(tmp_path)
    script = tmp_path / "p2.sh"
    # Exact frozen body; only HOME selects disposable inputs.
    producer = preservation_program().encode()
    script.write_bytes(producer)
    version = subprocess.run(["/usr/bin/cp", "--version"], stdin=subprocess.DEVNULL,
        capture_output=True, timeout=30, check=False, env={**os.environ, "LC_ALL": "C"})
    assert version.returncode == 0 and version.stderr == b""
    version_line = version.stdout.splitlines()[0].decode("ascii")
    assert re.fullmatch(r"cp \(GNU coreutils\) [0-9]+(?:\.[0-9]+)+", version_line)
    result, stdout, stderr, status, continued = through_transport(
        tmp_path, ["/bin/bash", script.as_posix()], home=tmp_path)
    archive = tmp_path / "maintenance-g9-d2-prior"
    source_unchanged = {p.name: p.read_bytes() for p in source.iterdir()} == before
    archive_matches = archive.is_dir() and {
        p.name: p.read_bytes() for p in archive.iterdir()} == before
    assert not (directory / EVIDENCE).exists(), "do not replace a previous observation"
    write_evidence(EVIDENCE, {
        "scope": "disposable-ubuntu-stock-utility-observation", "cp_version": version_line,
        "producer_sha256": hashlib.sha256(producer).hexdigest(),
        "producer": {"returncode": status["returncode"], "stdout": stdout.decode(),
                     "stderr": stderr.decode()},
        "transport": {"returncode": result.returncode, "stdout": result.stdout.decode(),
                      "stderr": result.stderr.decode()},
        "source_unchanged": source_unchanged, "archive_matches": archive_matches,
        "next_command_entered": continued,
    })
    assert_clean_evidence(directory, "n3c-stock-*.json", (EVIDENCE,), (), required=True)
    assert source_unchanged and archive_matches
    assert (stdout, stderr, status) == (MARKER, WARNING * 3, {"returncode": 0})
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"transport-step-refused\n", b"")
    assert not continued


def test_required_stock_utility_lane_cannot_silently_skip(monkeypatch, tmp_path):
    monkeypatch.setenv("M8_STOCK_UTILITIES_REQUIRED", "1")
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(AssertionError, match=r"requires|needs Linux"):
        test_ubuntu_stock_cp_preserves_bytes_but_fails_clean_diagnostics(tmp_path)


@pytest.mark.parametrize("damage", ["none", "missing", "injected"])
def test_stock_utility_observation_has_an_exact_retained_census(tmp_path, monkeypatch, damage):
    monkeypatch.setenv("M8_EVIDENCE_DIRECTORY", str(tmp_path))
    if damage != "missing":
        write_evidence(EVIDENCE, {"synthetic_retention_probe": True})
    if damage == "injected":
        (tmp_path / "n3c-stock-injected.json").write_text("{}")
    if damage == "none":
        assert_clean_evidence(tmp_path, "n3c-stock-*.json", (EVIDENCE,), (), required=True)
    else:
        with pytest.raises(AssertionError):
            assert_clean_evidence(tmp_path, "n3c-stock-*.json", (EVIDENCE,), (), required=True)
