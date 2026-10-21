"""Provision a fake-only Claude composition fixture on the disposable CI runner.

The existing curated runtime supplies Python, Git and their link closure. This
adds one reviewed C peer, a shell execution control and empty mount points. No
vendor executable, operator store, account or credential is read or installed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/var/lib/constructicon-m8-claude")
BASE = Path("/var/lib/constructicon-m8-launch")
POLICY = Path("/etc/apparmor.d/constructicon-m8-claude")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def checked(argv: list[str]) -> None:
    result = subprocess.run(
        argv, stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=30,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    require(result.returncode == 0 and result.stdout == result.stderr == b"",
            "fixed fixture provisioning command failed")


def build() -> dict[str, object]:
    require(len(sys.argv) == 1, "fixture provisioning accepts no arguments")
    require(sys.platform == "linux" and os.geteuid() == 0
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted",
            "fixture provisioning requires the disposable hosted CI runner")
    require(not POLICY.exists() and not POLICY.is_symlink(), "fixture policy already exists")
    profiles = Path("/sys/kernel/security/apparmor/profiles").read_text()
    require(not any(line.startswith("constructicon-m8-claude-")
                    for line in profiles.splitlines()), "fixture profiles already exist")
    from constructicon.substrate.executors.linux import runtime_digest, runtime_inventory

    runtime_inventory(BASE / "runtime")
    # Exclusive ownership precedes every write. Partial provisioning stays on
    # this disposable runner and can never publish a successful fixture report.
    ROOT.mkdir(mode=0o755)
    source = Path(__file__).resolve().parent
    policy_bytes = (source / "constructicon-m8-claude.apparmor").read_bytes()
    POLICY.write_bytes(policy_bytes)
    POLICY.chmod(0o444)
    native_start = b"profile constructicon-m8-claude-native flags="
    require(policy_bytes.count(native_start) == 1, "native policy section is ambiguous")
    native = ROOT / "native-profile"
    native.write_bytes(b"abi <abi/4.0>,\n\n" + native_start
                       + policy_bytes.split(native_start, 1)[1])
    native.chmod(0o444)
    shutil.copyfile(BASE / "bwrap", ROOT / "bwrap")
    (ROOT / "bwrap").chmod(0o555)
    runtime = ROOT / "runtime"
    shutil.copytree(BASE / "runtime", runtime, symlinks=True)
    vendor = ROOT / "fake-vendor"
    vendor.mkdir(mode=0o755)
    checked(["/usr/bin/cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
             str(source / "m8_claude_peer.c"), "-o", str(vendor / "claude")])
    (vendor / "claude").chmod(0o555)
    vendor.chmod(0o555)
    (runtime / "opt/claude").mkdir(parents=True)
    shutil.copyfile(vendor / "claude", runtime / "opt/claude/claude")
    (runtime / "bin").mkdir(exist_ok=True)
    shutil.copyfile("/bin/sh", runtime / "bin/sh")
    admin = runtime / "etc/claude-code"
    admin.mkdir(parents=True)
    for name in ("managed-settings.json", "managed-mcp.json"):
        (admin / name).write_bytes(b"")
    for path in [*runtime.rglob("*"), runtime]:
        if not path.is_symlink():
            path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
    checked(["/usr/sbin/apparmor_parser", "--add", "--skip-cache", str(POLICY)])
    report: dict[str, object] = {
        "schema_version": 1, "scope": "fake_native_composition_fixture",
        "production_available": False, "claude_qualified": False,
        "runtime_digest": str(runtime_digest(runtime)),
        "vendor_digest": str(runtime_digest(vendor)),
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "peer_sha256": hashlib.sha256((vendor / "claude").read_bytes()).hexdigest(),
    }
    report_path = ROOT / "fixture.json"
    report_path.write_text(json.dumps(report, sort_keys=True) + "\n")
    report_path.chmod(0o444)
    return report


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
