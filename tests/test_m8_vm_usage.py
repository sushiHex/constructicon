"""Fake subprocess runner only; no PowerShell, Hyper-V or VM is ever contacted."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import m8_vm_usage as usage

PRIVATE_MARKER = "private-marker-should-never-be-published"


def _source(**changes: object) -> bytes:
    fields: dict[str, object] = {
        "name": usage.VM_NAME,
        "state": "Off",
        "uptime_seconds": 0,
        "checkpoints": 0,
        "vmconnect": 0,
    }
    fields.update(changes)
    return json.dumps(fields).encode()


def _fake_process(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: bytes | None = None,
    stderr: bytes = b"",
    returncode: int = 0,
    error: Exception | None = None,
) -> list[tuple[list[str], dict[str, object]]]:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((argv, kwargs))
        if error is not None:
            raise error
        return subprocess.CompletedProcess(
            argv, returncode, _source() if stdout is None else stdout, stderr,
        )

    class Windows:
        name = "nt"

    # Patch the module bindings, not os.name globally (which changes pathlib).
    monkeypatch.setattr(usage, "os", Windows)
    monkeypatch.setattr(usage.subprocess, "run", run)
    return calls


def _main_report(
    capsys: pytest.CaptureFixture[str], expected_exit: int,
) -> dict[str, object]:
    assert usage.main([]) == expected_exit
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.encode()) <= usage.MAX_REPORT_BYTES
    assert PRIVATE_MARKER not in captured.out
    report = json.loads(captured.out)
    assert report["schema_version"] == 1
    assert report["vm"] == "constructicon-m8"
    if expected_exit == 2:
        assert set(report) == {"schema_version", "vm", "verdict", "reason"}
        assert report["verdict"] == "unknown"
    else:
        assert set(report) == {
            "schema_version", "vm", "verdict", "state", "uptime_seconds",
            "checkpoints", "vmconnect",
        }
    return report


def test_idle_path_and_exact_invocation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _fake_process(monkeypatch)
    assert _main_report(capsys, 0) == {
        "schema_version": 1, "vm": "constructicon-m8", "verdict": "idle-observed",
        "state": "Off", "uptime_seconds": 0, "checkpoints": 0, "vmconnect": 0,
    }
    assert calls == [(
        [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
         "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", usage.QUERY],
        {"shell": False, "stdin": subprocess.DEVNULL, "capture_output": True,
         "timeout": 60, "check": False},
    )]


def test_query_is_read_only_and_names_every_dimension() -> None:
    for fragment in (
        "Get-VM -Name 'constructicon-m8'",
        "@(Get-VMCheckpoint -VM $vm).Count",
        "@(Get-Process -Name vmconnect -ErrorAction SilentlyContinue).Count",
    ):
        assert fragment in usage.QUERY
    for forbidden in ("Start-", "Stop-", "Set-", "Remove-", "Restore-", "Checkpoint-", "Connect"):
        assert forbidden not in usage.QUERY


@pytest.mark.parametrize("changes", [
    {"state": "Running"},
    {"state": "Saved"},
    {"state": "Paused"},
    {"state": "Starting"},
    {"uptime_seconds": 1},
    {"checkpoints": 1},
    {"vmconnect": 1},
    {"state": "Running", "uptime_seconds": 3600, "checkpoints": 2, "vmconnect": 1},
])
def test_each_in_use_dimension_is_in_use(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    changes: dict[str, object],
) -> None:
    _fake_process(monkeypatch, stdout=_source(**changes))
    report = _main_report(capsys, 1)
    assert report["verdict"] == "in-use"
    for key, value in changes.items():
        assert report[key] == value


@pytest.mark.parametrize(("changes", "reason"), [
    ({"name": PRIVATE_MARKER}, "vm_identity"),
    ({"name": "Constructicon-M8"}, "vm_identity"),
    ({"name": None}, "malformed_source"),
    ({"state": None}, "malformed_source"),
    ({"state": ""}, "malformed_source"),
    ({"state": "Off\n"}, "malformed_source"),
    ({"state": PRIVATE_MARKER}, "malformed_source"),
    ({"state": "x" * 33}, "malformed_source"),
    ({"state": 0}, "malformed_source"),
    ({"uptime_seconds": -1}, "malformed_source"),
    ({"uptime_seconds": 0.0}, "malformed_source"),
    ({"uptime_seconds": "0"}, "malformed_source"),
    ({"uptime_seconds": None}, "malformed_source"),
    ({"uptime_seconds": usage.MAX_UPTIME_SECONDS + 1}, "malformed_source"),
    ({"checkpoints": -1}, "malformed_source"),
    ({"checkpoints": 0.0}, "malformed_source"),
    ({"checkpoints": usage.MAX_COUNT + 1}, "malformed_source"),
    ({"vmconnect": -1}, "malformed_source"),
    ({"vmconnect": "0"}, "malformed_source"),
    ({"vmconnect": usage.MAX_COUNT + 1}, "malformed_source"),
    ({"extra": PRIVATE_MARKER}, "malformed_source"),
])
def test_source_refusals_are_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    changes: dict[str, object], reason: str,
) -> None:
    _fake_process(monkeypatch, stdout=_source(**changes))
    assert _main_report(capsys, 2)["reason"] == reason


@pytest.mark.parametrize("field", ["uptime_seconds", "checkpoints", "vmconnect"])
@pytest.mark.parametrize("flag", [True, False])
def test_bool_is_never_a_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    field: str, flag: bool,
) -> None:
    # False == 0 in Python: it must not read as an idle zero.
    _fake_process(monkeypatch, stdout=_source(**{field: flag}))
    assert _main_report(capsys, 2)["reason"] == "malformed_source"


@pytest.mark.parametrize("field", sorted(usage.FIELDS))
def test_missing_field_is_malformed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], field: str,
) -> None:
    fields = json.loads(_source())
    del fields[field]
    _fake_process(monkeypatch, stdout=json.dumps(fields).encode())
    assert _main_report(capsys, 2)["reason"] == "malformed_source"


@pytest.mark.parametrize("source", [
    b"", b"null", b"[]", b"{}", b"\xff", b"not json", b'{"name":',
    b'{"name":"constructicon-m8","name":"constructicon-m8","state":"Off",'
    b'"uptime_seconds":0,"checkpoints":0,"vmconnect":0}',
    b'{"name":"constructicon-m8","state":"Off","uptime_seconds":0,'
    b'"checkpoints":0,"checkpoints":1,"vmconnect":0}',
    b"[" * 1500 + b"]" * 1500,
])
def test_malformed_bytes_never_escape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], source: bytes,
) -> None:
    _fake_process(monkeypatch, stdout=source)
    assert _main_report(capsys, 2)["reason"] == "malformed_source"


def test_source_byte_bound_binds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source()
    at_bound = source + b" " * (usage.MAX_SOURCE_BYTES - len(source))
    _fake_process(monkeypatch, stdout=at_bound)
    _main_report(capsys, 0)
    _fake_process(monkeypatch, stdout=at_bound + b" ")
    assert _main_report(capsys, 2)["reason"] == "source_limit"


def test_widest_accepted_record_fits_the_output_bound(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_process(monkeypatch, stdout=_source(
        state="x" * 32, uptime_seconds=usage.MAX_UPTIME_SECONDS,
        checkpoints=usage.MAX_COUNT, vmconnect=usage.MAX_COUNT,
    ))
    _main_report(capsys, 1)


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"returncode": 1, "stderr": PRIVATE_MARKER.encode()}, "query_failed"),
    ({"returncode": 1, "stdout": _source()}, "query_failed"),
    ({"stderr": PRIVATE_MARKER.encode()}, "query_stderr"),
    ({"stderr": b"\n"}, "query_stderr"),
    ({"error": FileNotFoundError(PRIVATE_MARKER)}, "query_unavailable"),
    ({"error": PermissionError(PRIVATE_MARKER)}, "query_unavailable"),
    ({"error": subprocess.TimeoutExpired(PRIVATE_MARKER, 60,
                                         output=PRIVATE_MARKER, stderr=PRIVATE_MARKER)},
     "timeout"),
])
def test_process_faults_are_unknown_without_retry_or_private_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    kwargs: dict[str, object], reason: str,
) -> None:
    calls = _fake_process(monkeypatch, **kwargs)  # type: ignore[arg-type]
    assert _main_report(capsys, 2)["reason"] == reason
    assert len(calls) == 1


def test_unsupported_platform_never_starts_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _fake_process(monkeypatch)

    class OtherPlatform:
        name = "posix"

    monkeypatch.setattr(usage, "os", OtherPlatform)
    assert _main_report(capsys, 2)["reason"] == "unsupported_platform"
    assert calls == []


def test_caller_cannot_supply_a_vm_or_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _fake_process(monkeypatch)
    assert usage.main([PRIVATE_MARKER]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1, "vm": "constructicon-m8", "verdict": "unknown",
        "reason": "unexpected_arguments",
    }
    assert calls == []


FAKE_HYPERV = """function Get-VM {
    param($Name, $ErrorAction)
    if ($Name -cne 'constructicon-m8' -or $ErrorAction -cne 'Stop') { throw 'Wrong VM query' }
    for ($i=0; $i -lt VMS; $i++) {
        [pscustomobject]@{Name='constructicon-m8'; State='STATE';
          Uptime=[timespan]::FromSeconds(UPTIME)}
    }
}
function Get-VMCheckpoint {
    param($VM)
    if ($VM.Name -cne 'constructicon-m8') { throw 'Wrong VM object' }
    for ($i=0; $i -lt CHECKPOINTS; $i++) { [pscustomobject]@{Name="checkpoint$i"} }
}
function Get-Process {
    param($Name, $ErrorAction)
    if ($Name -cne 'vmconnect' -or $ErrorAction -cne 'SilentlyContinue') {
        throw 'Wrong process query'
    }
    for ($i=0; $i -lt CONSOLES; $i++) { [pscustomobject]@{Name='vmconnect'} }
}
"""


def _actual_powershell(
    monkeypatch: pytest.MonkeyPatch, *, vms: int = 1, state: str = "Off",
    uptime: float = 0, checkpoints: int = 0, consoles: int = 0,
) -> list[subprocess.CompletedProcess[bytes]]:
    # Only the Hyper-V and process cmdlets are substituted; the production query,
    # executable, argv construction and subprocess boundary really execute.
    fake = (FAKE_HYPERV.replace("VMS", str(vms)).replace("STATE", state)
            .replace("UPTIME", repr(uptime)).replace("CHECKPOINTS", str(checkpoints))
            .replace("CONSOLES", str(consoles)))
    real_run = subprocess.run
    observed: list[subprocess.CompletedProcess[bytes]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert argv == usage.powershell_argv()
        command = [*argv[:-1], fake + argv[-1]]
        completed = real_run(command, **kwargs)  # type: ignore[call-overload]
        observed.append(completed)
        return completed

    monkeypatch.setattr(usage.subprocess, "run", run)
    return observed


ACTUAL = pytest.mark.skipif(os.name != "nt", reason="actual Windows PowerShell process boundary")


@ACTUAL
@pytest.mark.parametrize(("dimensions", "verdict"), [
    ({}, "idle-observed"),
    ({"state": "Running", "uptime": 125.9}, "in-use"),
    ({"checkpoints": 2}, "in-use"),
    ({"consoles": 1}, "in-use"),
    ({"state": "Saved"}, "in-use"),
])
def test_actual_windows_query_with_fake_hyperv(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    dimensions: dict[str, object], verdict: str,
) -> None:
    observed = _actual_powershell(monkeypatch, **dimensions)  # type: ignore[arg-type]
    report = _main_report(capsys, 0 if verdict == "idle-observed" else 1)
    assert report["verdict"] == verdict and len(observed) == 1
    assert report["uptime_seconds"] == int(dimensions.get("uptime", 0))  # floored seconds
    assert report["checkpoints"] == dimensions.get("checkpoints", 0)
    assert report["vmconnect"] == dimensions.get("consoles", 0)


@ACTUAL
@pytest.mark.parametrize("vms", [0, 2])
def test_actual_missing_or_multiple_vms_are_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], vms: int,
) -> None:
    observed = _actual_powershell(monkeypatch, vms=vms)
    assert _main_report(capsys, 2)["reason"] == "query_failed"
    assert observed[0].stdout == b"" and b"Unexpected VM cardinality" in observed[0].stderr


def test_isolated_script_rejects_arguments_without_loading_repo() -> None:
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(Path(usage.__file__)), PRIVATE_MARKER],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False,
    )
    assert completed.returncode == 2
    assert completed.stderr == b""
    assert json.loads(completed.stdout) == {
        "schema_version": 1, "vm": "constructicon-m8", "verdict": "unknown",
        "reason": "unexpected_arguments",
    }
