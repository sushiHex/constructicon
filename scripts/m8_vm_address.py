"""Read the fixed M8 VM's private DHCP address; never start it or connect to it.

Run directly with isolated Python: ``python -I -S -B scripts/m8_vm_address.py``.
The JSON result contains private transport metadata and must stay local. The
source byte limit is checked after subprocess capture, not a streaming memory
bound. The child is a fixed, trusted, read-only Windows PowerShell query. Its
single bounded IP-address wait does not establish SSH readiness or identity.
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys

VM_NAME = "constructicon-m8"
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
TIMEOUT_SECONDS = 75
MAX_SOURCE_BYTES = 16_384
MAX_REPORT_BYTES = 256
PRIVATE_NETWORKS = tuple(
    ipaddress.IPv4Network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
QUERY = """$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Wait-VM -Name 'constructicon-m8' -For IPAddress -Timeout 60 -ErrorAction Stop | Out-Null
$vms = @(Get-VM -Name 'constructicon-m8' -ErrorAction Stop)
if ($vms.Count -ne 1) { throw 'Unexpected VM cardinality' }
$vm = $vms[0]
$addresses = @(Get-VMNetworkAdapter -VM $vm -ErrorAction Stop | ForEach-Object { $_.IPAddresses })
$result = [pscustomobject]@{name=$vm.Name; state=[string]$vm.State; addresses=$addresses}
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


def _refused(reason: str) -> dict[str, str]:
    return {"status": "refused", "reason": reason}


def _parse(source: bytes) -> dict[str, str]:
    try:
        value = json.loads(source.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        return _refused("malformed_source")
    if not isinstance(value, dict) or set(value) != {"name", "state", "addresses"}:
        return _refused("malformed_source")
    if value["name"] != VM_NAME:
        return _refused("vm_identity")
    if value["state"] != "Running":
        return _refused("vm_state")
    addresses = value["addresses"]
    if not isinstance(addresses, list) or len(addresses) > 64:
        return _refused("malformed_source")
    suitable = set()
    for address in addresses:
        if not isinstance(address, str) or len(address) > 64:
            return _refused("malformed_source")
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return _refused("malformed_source")
        # IPv6 and non-RFC1918 addresses cannot be this private DHCP target.
        if isinstance(parsed, ipaddress.IPv4Address) and any(
            parsed in network for network in PRIVATE_NETWORKS
        ):
            suitable.add(str(parsed))
    if not suitable:
        return _refused("no_suitable_address")
    if len(suitable) != 1:
        return _refused("ambiguous_address")
    return {"status": "ok", "vm": VM_NAME, "state": "Running", "address": suitable.pop()}


def discover() -> dict[str, str]:
    if os.name != "nt":
        return _refused("unsupported_platform")
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
        return _refused("query_timeout")
    except OSError:
        return _refused("query_unavailable")
    if completed.returncode != 0:
        return _refused("query_failed")
    if completed.stderr:
        return _refused("query_stderr")
    if len(completed.stdout) > MAX_SOURCE_BYTES:
        return _refused("source_limit")
    return _parse(completed.stdout)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    report = _refused("unexpected_arguments") if arguments else discover()
    rendered = json.dumps(report, separators=(",", ":"), ensure_ascii=True)
    # Every public field is fixed vocabulary or a validated IPv4 address.
    assert len(rendered.encode("ascii")) + 1 <= MAX_REPORT_BYTES
    print(rendered)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
