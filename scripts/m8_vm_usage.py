"""One read-only usage observation of the fixed M8 VM; never start, stop or connect to it.

Run directly with isolated Python: ``python -I -S -B scripts/m8_vm_usage.py``.
Exit 0 prints ``idle-observed``. At the instant of the query the VM was Off, its
operational status was exactly ``Ok`` (no disk merge or import in progress), it
had zero uptime and zero checkpoints, and no local ``vmconnect`` process existed.
Exit 1 prints ``in-use`` for any other well-formed observation: Running, Saved,
Paused, another operational status, a nonzero uptime, a checkpoint or a local
vmconnect. Exit 2 prints ``unknown`` with a closed reason when the query failed,
timed out or returned anything not exactly the expected record. Process
enumeration errors stop the query; they are never read as zero. Raw query
output, exception text and paths are never printed.

``idle-observed`` proves no running guest and no local console at that instant.
It does not observe a remote VMConnect or Hyper-V Manager session on another
machine. It does NOT prove exclusive custody, the absence of another
administrator's intent, or authorization; those are separate (see
docs/plans/handoffs/M8-vm-custody.md). The source byte limit is checked after
subprocess capture, not as a streaming memory bound. One query, one 60 second
timeout, no retries. The child is a fixed, trusted, read-only Windows PowerShell
query.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

VM_NAME = "constructicon-m8"
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
TIMEOUT_SECONDS = 60
MAX_SOURCE_BYTES = 16_384
MAX_REPORT_BYTES = 256
MAX_COUNT = 1_000_000
MAX_UPTIME_SECONDS = 10**10
FIELDS = {"name", "state", "operational", "uptime_seconds", "checkpoints", "vmconnect"}
MAX_OPERATIONAL = 2
OPERATIONAL_PATTERN = re.compile(r"[A-Za-z]{1,24}")
STATE_PATTERN = re.compile(r"[A-Za-z]{1,32}")
QUERY = """$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$vms = @(Get-VM -Name 'constructicon-m8' -ErrorAction Stop)
if ($vms.Count -ne 1) { throw 'Unexpected VM cardinality' }
$vm = $vms[0]
$checkpoints = @(Get-VMCheckpoint -VM $vm).Count
$processes = @(Get-Process -ErrorAction Stop)
$vmconnect = @($processes | Where-Object { $_.ProcessName -eq 'vmconnect' }).Count
$uptime = [int64][math]::Floor($vm.Uptime.TotalSeconds)
$operational = @([string[]]$vm.OperationalStatus)
$result = [pscustomobject]@{name=$vm.Name; state=[string]$vm.State;
  operational=$operational; uptime_seconds=$uptime; checkpoints=[int]$checkpoints;
  vmconnect=[int]$vmconnect}
$result | ConvertTo-Json -Compress -Depth 3
"""


def powershell_argv() -> list[str]:
    return [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", QUERY]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _unknown(reason: str) -> dict[str, object]:
    return {"schema_version": 1, "vm": VM_NAME, "verdict": "unknown", "reason": reason}


def _count(value: object, limit: int) -> bool:
    # bool is an int subclass; a JSON true/false is never a count.
    return type(value) is int and 0 <= value <= limit


def _parse(source: bytes) -> dict[str, object]:
    try:
        value = json.loads(source.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        return _unknown("malformed_source")
    if not isinstance(value, dict) or set(value) != FIELDS:
        return _unknown("malformed_source")
    state = value["state"]
    operational = value["operational"]
    uptime = value["uptime_seconds"]
    checkpoints = value["checkpoints"]
    vmconnect = value["vmconnect"]
    if (
        not isinstance(value["name"], str)
        or not isinstance(state, str)
        or STATE_PATTERN.fullmatch(state) is None
        or not isinstance(operational, list)
        or not 0 < len(operational) <= MAX_OPERATIONAL
        or not all(isinstance(item, str) and OPERATIONAL_PATTERN.fullmatch(item)
                   for item in operational)
        or not _count(uptime, MAX_UPTIME_SECONDS)
        or not _count(checkpoints, MAX_COUNT)
        or not _count(vmconnect, MAX_COUNT)
    ):
        return _unknown("malformed_source")
    if value["name"] != VM_NAME:
        return _unknown("vm_identity")
    # A disk merge or import runs while Off; only an exactly Ok status is idle.
    idle = (state == "Off" and operational == ["Ok"] and uptime == 0 and checkpoints == 0
            and vmconnect == 0)
    return {
        "schema_version": 1,
        "vm": VM_NAME,
        "verdict": "idle-observed" if idle else "in-use",
        "state": state,
        "operational": operational,
        "uptime_seconds": uptime,
        "checkpoints": checkpoints,
        "vmconnect": vmconnect,
    }


def observe() -> dict[str, object]:
    if os.name != "nt":
        return _unknown("unsupported_platform")
    try:
        completed = subprocess.run(
            powershell_argv(),
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _unknown("timeout")
    except OSError:
        return _unknown("query_unavailable")
    if completed.returncode != 0:
        return _unknown("query_failed")
    if completed.stderr:
        return _unknown("query_stderr")
    if len(completed.stdout) > MAX_SOURCE_BYTES:
        return _unknown("source_limit")
    return _parse(completed.stdout)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    report = _unknown("unexpected_arguments") if arguments else observe()
    rendered = json.dumps(report, separators=(",", ":"), ensure_ascii=True)
    # Every public field is fixed vocabulary, a validated state word or a bounded integer.
    assert len(rendered.encode("ascii")) + 1 <= MAX_REPORT_BYTES
    print(rendered)
    verdict = report["verdict"]
    return 0 if verdict == "idle-observed" else 1 if verdict == "in-use" else 2


if __name__ == "__main__":
    raise SystemExit(main())
