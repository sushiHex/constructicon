"""Portable assertion tests for the CI probe; these do not prove Linux containment."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from scripts.ci import qualify_m8_runner as probe

HOST = {name: f"{name}:[1]" for name in probe.NAMESPACES}
CHILD = {
    "uid": 1001,
    "gid": 1001,
    "uid_map": "1001 0 1",
    "gid_map": "1001 0 1",
    "namespaces": {name: f"{name}:[2]" for name in probe.NAMESPACES},
    "write_errno": 30,
    "host_home_visible": False,
    "sys_visible": False,
    "status": ["NoNewPrivs:\t1", "CapEff:\t0000000000000000"],
    "apparmor": "constructicon-m8-bwrap//&constructicon-m8-payload (enforce)",
    "nested_returncode": 1,
    "nested_stderr": "bwrap: Creating new namespace failed: Operation not permitted",
    "net_dev": "Inter-| Receive\n face |bytes\n    lo: 0 0 0 0\n",
}


def test_complete_diagnostic_is_accepted() -> None:
    probe.validate_child(CHILD, HOST, 1001, 1001)


@pytest.mark.parametrize("namespace", probe.NAMESPACES)
def test_every_namespace_must_be_distinct(namespace: str) -> None:
    child = copy.deepcopy(CHILD)
    child["namespaces"][namespace] = HOST[namespace]
    with pytest.raises(ValueError, match="namespace remained shared"):
        probe.validate_child(child, HOST, 1001, 1001)


@pytest.mark.parametrize(
    ("key", "value", "fault"),
    [
        ("uid", 0, "UID/GID"),
        ("gid", 0, "UID/GID"),
        ("uid_map", "1001 1001 1", "exactly one UID/GID"),
        ("gid_map", "1001 1001 2", "exactly one UID/GID"),
        ("write_errno", None, "read-only mount"),
        ("write_errno", 13, "read-only mount"),
        ("host_home_visible", True, "host home or sysfs"),
        ("sys_visible", True, "host home or sysfs"),
        ("status", ["NoNewPrivs:\t0", "CapEff:\t0000000000000000"], "privileges"),
        ("status", ["NoNewPrivs:\t1", "CapEff:\t0000000000000001"], "capabilities"),
        ("apparmor", "unconfined", "AppArmor attachment"),
        ("apparmor", "constructicon-m8-bwrap (enforce)", "AppArmor attachment"),
        ("apparmor", "constructicon-m8-payload (enforce)", "AppArmor attachment"),
        ("apparmor", "bwrap//&unpriv_bwrap (enforce)", "AppArmor attachment"),
        (
            "apparmor",
            "constructicon-m8-bwrap//&constructicon-m8-payload (complain)",
            "AppArmor attachment",
        ),
        ("nested_returncode", 0, "permission refusal"),
        ("nested_stderr", "bwrap: unknown option", "permission refusal"),
        ("net_dev", "header\nheader\n lo: 0\n eth0: 0\n", "non-loopback"),
    ],
)
def test_each_observed_boundary_is_required(key: str, value: object, fault: str) -> None:
    child = {**CHILD, key: value}
    with pytest.raises(ValueError, match=fault):
        probe.validate_child(child, HOST, 1001, 1001)


def test_unsupported_host_is_explicit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ValueError, match="not exercised"):
        probe.qualify({})


@pytest.mark.parametrize(
    ("returncode", "message", "expected"),
    [
        (1, "bwrap: Creating new namespace failed: Permission denied\n", True),
        (1, "bwrap: Creating new namespace failed: Operation not permitted\n", True),
        (0, "bwrap: Creating new namespace failed: Permission denied\n", False),
        (2, "bwrap: Creating new namespace failed: Permission denied\n", False),
        (1, "bwrap: execvp /usr/bin/python3: Permission denied\n", False),
        (1, "bwrap: mount: Operation not permitted\n", False),
        (1, "bwrap: unknown option\n", False),
    ],
)
def test_namespace_refusal_names_the_operation(
    returncode: int, message: str, expected: bool
) -> None:
    assert probe.namespace_refused(returncode, message) is expected


@pytest.mark.parametrize(
    ("uid", "mode", "data", "fault"),
    [
        (0, 0o100555, b"reviewed", None),
        (1001, 0o100555, b"reviewed", "root-owned"),
        (0, 0o100575, b"reviewed", "read-only to others"),
        (0, 0o100557, b"reviewed", "read-only to others"),
        (0, 0o104555, b"reviewed", "non-set-ID"),
        (0, 0o102555, b"reviewed", "non-set-ID"),
        (0, 0o100555, b"unreviewed", "artifact drift"),
    ],
)
def test_artifacts_require_ownership_mode_and_reviewed_bytes(
    uid: int, mode: int, data: bytes, fault: str | None
) -> None:
    artifact = Mock(spec=Path)
    artifact.stat.return_value = SimpleNamespace(st_uid=uid, st_mode=mode)
    artifact.read_bytes.return_value = data
    expected = hashlib.sha256(b"reviewed").hexdigest()
    if fault is None:
        assert probe.artifact_digest(artifact, expected) == expected
    else:
        with pytest.raises(ValueError, match=fault):
            probe.artifact_digest(artifact, expected)


def test_policy_pin_and_private_attachment_match_reviewed_file() -> None:
    policy = Path(__file__).parents[1] / "scripts/ci/constructicon-m8-bwrap.apparmor"
    # Git stores text as LF; a Windows checkout may materialize CRLF.
    data = policy.read_text(encoding="utf-8").encode()
    assert hashlib.sha256(data).hexdigest() == probe.POLICY_SHA256
    text = data.decode()
    assert f"profile constructicon-m8-bwrap {probe.BWRAP} " in text
    assert "allow px /** -> constructicon-m8-bwrap//&constructicon-m8-payload," in text
    assert "allow ix /**," in text
    assert "deny capability," in text and "deny userns," in text
    rules = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    assert "include" not in rules
    assert "unconfined" not in rules


def test_root_is_never_a_qualification_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(probe.os, "getuid", lambda: 0, raising=False)
    monkeypatch.setattr(probe.os, "getgid", lambda: 0, raising=False)
    monkeypatch.setattr(probe.os, "getgroups", lambda: [0], raising=False)

    def unexpected_command(argv: list[str]) -> None:
        pytest.fail("root refusal must precede any subprocess")

    monkeypatch.setattr(probe, "run", unexpected_command)
    with pytest.raises(ValueError, match="must not run as root"):
        probe.qualify({})


@pytest.mark.parametrize(
    ("broken", "fault"),
    [
        ("sudo", "passwordless sudo"),
        ("distribution", "expected Ubuntu"),
        ("apparmor", "AppArmor is not enabled"),
        ("restriction", "restriction is not enabled"),
        ("package", "package drift"),
    ],
)
def test_host_refusals_precede_namespace_launch(
    broken: str, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(probe.os, "getuid", lambda: 1001, raising=False)
    monkeypatch.setattr(probe.os, "getgid", lambda: 1001, raising=False)
    monkeypatch.setattr(probe.os, "getgroups", lambda: [1001], raising=False)
    monkeypatch.setattr(
        probe.platform,
        "freedesktop_os_release",
        lambda: {"ID": "other" if broken == "distribution" else "ubuntu", "VERSION_ID": "24.04"},
    )

    def reading(path: Path) -> str:
        if path == probe.RESTRICTION:
            return "0" if broken == "restriction" else "1"
        return "N" if broken == "apparmor" else "Y"

    def running(argv: list[str]) -> subprocess.CompletedProcess[str]:
        if argv[0] == "/usr/bin/sudo":
            return subprocess.CompletedProcess(argv, int(broken != "sudo"), "", "")
        assert argv[0] == "/usr/bin/dpkg-query", "must not launch a namespace"
        return subprocess.CompletedProcess(
            argv, 0, "other" if broken == "package" else probe.PACKAGE
        )

    def path_for(value: str) -> Path:
        if value == probe.BWRAP:
            raise ValueError("crossed the host-prerequisite boundary")
        return Path(value)

    monkeypatch.setattr(probe, "read", reading)
    monkeypatch.setattr(probe, "run", running)
    monkeypatch.setattr(probe, "Path", path_for)
    with pytest.raises(ValueError, match=fault):
        probe.qualify({})


@pytest.mark.parametrize("failure", [False, True])
def test_report_cannot_claim_production_availability(
    failure: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["probe", "--commit", "a" * 40, "--image", "unit-only"])

    def qualifying(evidence: dict) -> None:
        if failure:
            raise ValueError("qualification deliberately refused")

    monkeypatch.setattr(probe, "qualify", qualifying)
    assert probe.main() == int(failure)
    report = json.loads(capsys.readouterr().out)
    assert report["scope"] == "runner_prerequisites_only"
    assert report["qualified"] is not failure
    assert report["production_available"] is False
    assert ("failure" in report) == failure


def test_workflow_is_exact_head_read_only_and_credential_free() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github/workflows/m8-runner-qualification.yml"
    ).read_text()
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert "EVIDENCE_COMMIT: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "contents: read" in workflow
    assert "sudo -u m8-probe env -i" in workflow
    assert "bubblewrap=" + probe.PACKAGE in workflow
    assert "retention-days: 7" in workflow
    assert "if-no-files-found: error" in workflow
    assert 'test "$RUNNER_ENVIRONMENT" = github-hosted' in workflow
    assert f"sudo install -m 0555 /usr/bin/bwrap {probe.BWRAP}" in workflow
    assert "apparmor_parser --add --skip-cache /etc/apparmor.d/constructicon-m8-bwrap" in workflow
    for target, install in (
        ("/opt/constructicon-m8-qualification", "sudo install -d"),
        ("/etc/apparmor.d/constructicon-m8-bwrap", "sudo install -m 0444 scripts/ci/constructicon"),
    ):
        assert workflow.index(f"test ! -e {target}") < workflow.index(install)
        assert workflow.index(f"test ! -L {target}") < workflow.index(install)
    for prohibited in (
        "pull_request_target",
        "secrets.",
        "continue-on-error",
        "sysctl -w",
        "--replace",
        "--remove",
        "--Complain",
    ):
        assert prohibited not in workflow
