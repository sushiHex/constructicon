"""Fake Hyper-V only, including the real Windows PowerShell argv boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import m8_vm_address as discovery

PRIVATE_MARKER = "private-marker-should-never-be-published"


def _source(**changes: object) -> bytes:
    fields: dict[str, object] = {
        "name": discovery.VM_NAME,
        "state": "Running",
        "addresses": ["192.168.44.2"],
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

    # Patch the module binding, not os.name globally (which changes pathlib).
    class Windows:
        name = "nt"

    monkeypatch.setattr(discovery, "os", Windows)
    monkeypatch.setattr(discovery.subprocess, "run", run)
    return calls


def _main_report(capsys: pytest.CaptureFixture[str], expected_exit: int) -> dict[str, str]:
    assert discovery.main([]) == expected_exit
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.encode()) <= discovery.MAX_REPORT_BYTES
    assert PRIVATE_MARKER not in captured.out
    report = json.loads(captured.out)
    assert isinstance(report, dict)
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in report.items())
    if expected_exit:
        assert set(report) == {"status", "reason"}
        assert report["status"] == "refused"
    else:
        assert set(report) == {"status", "vm", "state", "address"}
        assert report == {
            "status": "ok", "vm": "constructicon-m8", "state": "Running",
            "address": "192.168.44.2",
        }
    return report


def test_acceptance_uses_only_fixed_argv_and_closed_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _fake_process(monkeypatch)
    _main_report(capsys, 0)
    assert calls == [(
        [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
         "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", discovery.QUERY],
        {"shell": False, "stdin": subprocess.DEVNULL, "capture_output": True,
         "timeout": 75, "check": False},
    )]


@pytest.mark.parametrize("addresses", [
    ["192.168.44.2", "192.168.44.2"],
    ["::1", "fe80::1234", "fd00::1234", "192.168.44.2"],
    ["0.0.0.0", "127.0.0.1", "169.254.2.3", "224.0.0.1", "255.255.255.255",
     "8.8.8.8", "192.168.44.2"],
])
def test_filter_then_deduplicate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], addresses: list[str],
) -> None:
    _fake_process(monkeypatch, stdout=_source(addresses=addresses))
    _main_report(capsys, 0)


@pytest.mark.parametrize("address", ["10.2.3.4", "172.16.0.1", "172.31.255.254"])
def test_all_rfc1918_ranges_are_accepted(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    _fake_process(monkeypatch, stdout=_source(addresses=[address]))
    assert discovery.discover() == {
        "status": "ok", "vm": "constructicon-m8", "state": "Running", "address": address,
    }


@pytest.mark.parametrize(("changes", "reason"), [
    ({"name": PRIVATE_MARKER}, "vm_identity"),
    ({"state": "Off"}, "vm_state"),
    ({"state": "Paused"}, "vm_state"),
    ({"state": None}, "vm_state"),
    ({"addresses": []}, "no_suitable_address"),
    ({"addresses": ["172.15.255.255", "172.32.0.1"]}, "no_suitable_address"),
    ({"addresses": ["127.0.0.1", "169.254.1.1", "::ffff:192.168.44.2"]},
     "no_suitable_address"),
    ({"addresses": ["192.168.44.2", "10.0.0.2"]}, "ambiguous_address"),
    ({"addresses": ["192.168.44.2", PRIVATE_MARKER]}, "malformed_source"),
    ({"addresses": [None]}, "malformed_source"),
    ({"addresses": "192.168.44.2"}, "malformed_source"),
    ({"addresses": ["192.168.44.2"] * 65}, "malformed_source"),
    ({"addresses": ["x" * 65]}, "malformed_source"),
    ({"addresses": [" 192.168.44.2"]}, "malformed_source"),
    ({"addresses": ["192.168.044.2"]}, "malformed_source"),
    ({"extra": PRIVATE_MARKER}, "malformed_source"),
])
def test_source_refusals_are_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    changes: dict[str, object], reason: str,
) -> None:
    _fake_process(monkeypatch, stdout=_source(**changes))
    assert _main_report(capsys, 1)["reason"] == reason


@pytest.mark.parametrize("source", [
    b"", b"null", b"[]", b"{}", b"\xff", b"not json", b'{"name":',
    b'{"name":"constructicon-m8","name":"constructicon-m8",'
    b'"state":"Running","addresses":["192.168.44.2"]}',
    b"[" * 1500 + b"]" * 1500,
    _source().replace(b'"name": "constructicon-m8", ', b""),
])
def test_malformed_bytes_never_escape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], source: bytes,
) -> None:
    _fake_process(monkeypatch, stdout=source)
    assert _main_report(capsys, 1)["reason"] == "malformed_source"


def test_post_capture_source_bound_binds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source()
    at_bound = source + b" " * (discovery.MAX_SOURCE_BYTES - len(source))
    _fake_process(monkeypatch, stdout=at_bound)
    _main_report(capsys, 0)
    _fake_process(monkeypatch, stdout=at_bound + b" ")
    assert _main_report(capsys, 1)["reason"] == "source_limit"


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"returncode": 1, "stderr": PRIVATE_MARKER.encode()}, "query_failed"),
    ({"stderr": PRIVATE_MARKER.encode()}, "query_stderr"),
    ({"stderr": b"\n"}, "query_stderr"),
    ({"error": FileNotFoundError(PRIVATE_MARKER)}, "query_unavailable"),
    ({"error": PermissionError(PRIVATE_MARKER)}, "query_unavailable"),
    ({"error": subprocess.TimeoutExpired(PRIVATE_MARKER, 75,
                                         output=PRIVATE_MARKER, stderr=PRIVATE_MARKER)},
     "query_timeout"),
])
def test_process_faults_refuse_without_retry_or_private_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    kwargs: dict[str, object], reason: str,
) -> None:
    calls = _fake_process(monkeypatch, **kwargs)  # type: ignore[arg-type]
    assert _main_report(capsys, 1)["reason"] == reason
    assert len(calls) == 1


def test_unsupported_platform_never_starts_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _fake_process(monkeypatch)

    class OtherPlatform:
        name = "posix"

    monkeypatch.setattr(discovery, "os", OtherPlatform)
    assert _main_report(capsys, 1)["reason"] == "unsupported_platform"
    assert calls == []


def test_caller_cannot_supply_a_vm_or_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _fake_process(monkeypatch)
    assert discovery.main([PRIVATE_MARKER]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "refused", "reason": "unexpected_arguments",
    }
    assert calls == []


def test_isolated_script_rejects_arguments_without_loading_repo() -> None:
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(Path(discovery.__file__)), PRIVATE_MARKER],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False,
    )
    assert completed.returncode == 1
    assert completed.stderr == b""
    assert json.loads(completed.stdout) == {"status": "refused", "reason": "unexpected_arguments"}


@pytest.mark.skipif(os.name != "nt", reason="actual Windows PowerShell process boundary")
@pytest.mark.parametrize(("state", "addresses", "expected"), [
    ("Running", ["fe80::1234", "192.168.44.2", "192.168.44.2"], "ok"),
    ("Off", ["192.168.44.2"], "vm_state"),
    ("Running", [], "no_suitable_address"),
    ("Running", ["192.168.44.2", "10.0.0.2"], "ambiguous_address"),
])
def test_actual_windows_argv_boundary_with_fake_hyperv(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    state: str, addresses: list[str], expected: str,
) -> None:
    # Only the Hyper-V cmdlets are substituted. The production query, executable,
    # argv construction and subprocess boundary really execute on Windows.
    fake = """$script:waitFinished = $false
function Wait-VM {
    param($Name, $For, $Timeout, $ErrorAction)
    if ($Name -cne 'constructicon-m8' -or $For -cne 'IPAddress' -or
        $Timeout -ne 60 -or $ErrorAction -cne 'Stop') { throw 'Wrong wait arguments' }
    $script:waitFinished = $true
    'This wait output must be suppressed'
}
function Get-VM {
    param($Name, $ErrorAction)
    if (-not $script:waitFinished) { throw 'Query before readiness wait' }
    if ($Name -cne 'constructicon-m8' -or $ErrorAction -cne 'Stop') { throw 'Wrong VM query' }
    [pscustomobject]@{Name='constructicon-m8'; State='STATE'}
}
function Get-VMNetworkAdapter {
    param($VM, $ErrorAction)
    if ($VM.Name -cne 'constructicon-m8' -or $ErrorAction -cne 'Stop') { throw 'Wrong VM object' }
    [pscustomobject]@{IPAddresses=@(ADDRESSES)}
}
""".replace("STATE", state).replace("ADDRESSES", ",".join(f"'{a}'" for a in addresses))
    real_run = subprocess.run
    calls = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert argv == discovery.powershell_argv()
        calls.append(argv)
        return real_run([*argv[:-1], fake + argv[-1]], **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(discovery.subprocess, "run", run)
    report = _main_report(capsys, 0 if expected == "ok" else 1)
    assert (report["status"] if expected == "ok" else report["reason"]) == expected
    assert len(calls) == 1


@pytest.mark.skipif(os.name != "nt", reason="actual Windows PowerShell process boundary")
def test_actual_wait_failure_stops_before_vm_query(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = """function Wait-VM {
    param($Name, $For, $Timeout, $ErrorAction)
    throw 'private wait failure'
}
function Get-VM { [Console]::Out.WriteLine('QUERY-MUST-NOT-RUN'); exit 0 }
function Get-VMNetworkAdapter { [Console]::Out.WriteLine('QUERY-MUST-NOT-RUN'); exit 0 }
"""
    real_run = subprocess.run
    observed = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert argv == discovery.powershell_argv()
        completed = real_run([*argv[:-1], fake + argv[-1]], **kwargs)
        observed.append(completed)
        return completed

    monkeypatch.setattr(discovery.subprocess, "run", run)
    assert discovery.discover() == {"status": "refused", "reason": "query_failed"}
    assert len(observed) == 1
    assert observed[0].returncode != 0
    assert observed[0].stdout == b""
    assert b"private wait failure" in observed[0].stderr


@pytest.mark.skipif(os.name != "nt", reason="actual Windows PowerShell process boundary")
@pytest.mark.parametrize("vm_count", [0, 2])
def test_actual_missing_or_multiple_vms_stop_before_adapter_query(
    monkeypatch: pytest.MonkeyPatch, vm_count: int,
) -> None:
    fake = """function Wait-VM { param($Name, $For, $Timeout, $ErrorAction) }
function Get-VM {
    param($Name, $ErrorAction)
    for ($i=0; $i -lt VM_COUNT; $i++) {
        [pscustomobject]@{Name='constructicon-m8'; State='Running'}
    }
}
function Get-VMNetworkAdapter { [Console]::Out.WriteLine('QUERY-MUST-NOT-RUN'); exit 0 }
""".replace("VM_COUNT", str(vm_count))
    real_run = subprocess.run
    observed = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        completed = real_run([*argv[:-1], fake + argv[-1]], **kwargs)
        observed.append(completed)
        return completed

    monkeypatch.setattr(discovery.subprocess, "run", run)
    assert discovery.discover() == {"status": "refused", "reason": "query_failed"}
    assert len(observed) == 1
    assert observed[0].returncode != 0
    assert observed[0].stdout == b""
    assert b"Unexpected VM cardinality" in observed[0].stderr
