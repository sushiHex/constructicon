"""Root-only hosted missing-target phase, restoring policy in every exit path."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.ci.build_m8_claude_fixture import POLICY, ROOT, checked, require


def prove() -> int:
    require(len(sys.argv) == 1, "missing-target proof accepts no arguments")
    require(sys.platform == "linux" and os.geteuid() == 0
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted",
            "missing-target proof requires the disposable hosted CI runner")
    pins = json.loads((ROOT / "fixture.json").read_text())
    policy_bytes = POLICY.read_bytes()
    require(hashlib.sha256(policy_bytes).hexdigest() == pins["policy_sha256"],
            "the fixture policy changed")
    native_start = b"profile constructicon-m8-claude-native flags="
    native = ROOT / "native-profile"
    require(native.read_bytes() == b"abi <abi/4.0>,\n\n" + native_start
            + policy_bytes.split(native_start, 1)[1], "the native profile changed")
    profiles = Path("/sys/kernel/security/apparmor/profiles")
    native_line = "constructicon-m8-claude-native (enforce)"
    require(native_line in profiles.read_text().splitlines(), "native profile was not loaded")
    checkout = Path(__file__).resolve().parents[2]
    try:
        checked(["/usr/sbin/apparmor_parser", "--remove", "--skip-cache", str(native)])
        require(not any(line.startswith("constructicon-m8-claude-native ")
                        for line in profiles.read_text().splitlines()),
                "native transition target was not absent")
        result = subprocess.run(
            ["/usr/bin/sudo", "-n", "-u", "m8-service", "--", "/usr/bin/env", "-i",
             "HOME=/home/m8-service", "PATH=/usr/bin:/bin", "LANG=C.UTF-8",
             "M8_CONTAINMENT_REQUIRED=1", "M8_LINUX_ROOT=/var/lib/constructicon-m8-launch",
             "M8_CLAUDE_COMPOSITION_REQUIRED=1", "M8_CLAUDE_MISSING_PROFILE_REQUIRED=1",
             str(checkout / ".venv/bin/python"), "-m", "pytest",
             "tests/substrate/test_claude_native_containment.py::"
             "test_missing_native_profile_refuses_before_conversation",
             "-v", "--tb=short", "-p", "no:cacheprovider"],
            stdin=subprocess.DEVNULL, check=False, timeout=60, cwd=checkout,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
    finally:
        # Replace restores the reviewed bytes even after a partial remove.
        checked(["/usr/sbin/apparmor_parser", "--replace", "--skip-cache", str(native)])
        require(native_line in profiles.read_text().splitlines(), "native profile was not restored")
    return result.returncode


def main() -> int:
    def interrupted(_signum: int, _frame: object) -> None:
        # Repeated cancellation cannot interrupt the owned policy restoration.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise InterruptedError("missing-target proof interrupted")

    previous = {number: signal.signal(number, interrupted)
                for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        return prove()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


if __name__ == "__main__":
    raise SystemExit(main())
