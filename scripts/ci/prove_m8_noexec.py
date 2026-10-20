"""Disposable hosted CI, fake-only AppArmor no-further-exec feasibility.

This is not LinuxLauncher composition, Claude startup, a native profile or an
availability decision. The broad file/mmap/socket permissions deliberately expose
what execution denial does NOT constrain. Fixed benign processes only, not a
replacement hostile-output pump. No credentials or vendor executable are used.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

ROOT = Path("/opt/constructicon-m8-noexec")
PREFIX = "constructicon-m8-noexec-"
LABEL = PREFIX + "payload (enforce)"
POLICIES = Path("/sys/kernel/security/apparmor/profiles")
OPERATIONS = ("direct", "shell", "self", "fd", "execveat")
ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"}
TIMEOUT_S = 15


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run(argv: list[str], data: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """One fixed benign process group; timeout/error kills and joins its group.

    The fixture synchronously joins its one child before a successful exit.
    This is a standalone feasibility driver, not hostile descendant containment.
    """
    with subprocess.Popen(
        argv, stdin=subprocess.DEVNULL if data is None else subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV,
        close_fds=True, start_new_session=True,
    ) as child:
        try:
            stdout, stderr = child.communicate(data, timeout=TIMEOUT_S)
        except BaseException:
            with suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.communicate(timeout=5)
            raise
        require(len(stdout) <= 4096 and len(stderr) <= 4096, "fixture output bound exceeded")
        return subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)


def exact(result: subprocess.CompletedProcess[bytes], code: int, output: bytes) -> None:
    require(result.returncode == code, "fixture exit mismatch")
    require(result.stdout == output, "fixture affirmative evidence mismatch")
    require(result.stderr == b"", "fixture stderr was not empty")


def expected_transcript() -> bytes:
    rows = [f"before:{LABEL}", "exchange:pong"]
    rows += [f"{operation}:13" for operation in OPERATIONS]
    rows += [f"child-label:{LABEL}", "child-errno:13", "child-joined:1",
             "same-process-file:read-write", "same-process-socket:read-write", f"after:{LABEL}"]
    return ("\n".join(rows) + "\n").encode()


def validate_profiles(text: str, *, present: bool) -> None:
    observed = {line for line in text.splitlines() if line.startswith(PREFIX)}
    expected = {PREFIX + name + " (enforce)" for name in ("launch", "payload", "missing")}
    require(observed == (expected if present else set()), "profile presence/enforcement mismatch")


def checked(argv: list[str]) -> None:
    result = run(argv)
    exact(result, 0, b"")


def prove() -> dict[str, object]:
    require(sys.platform == "linux", "physical proof requires Linux")
    require(os.geteuid() == 0 and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted",
            "provisioning requires the disposable hosted CI runner")
    import pwd

    service = pwd.getpwnam("m8-service")
    require(service.pw_uid != 0 and service.pw_gid != 0, "probe service must be unprivileged")
    require(Path("/sys/module/apparmor/parameters/enabled").read_text().strip() == "Y",
            "AppArmor is not enabled")
    validate_profiles(POLICIES.read_text(), present=False)
    source = Path(__file__).resolve().parent
    # mkdir is exclusive. No cleanup runs unless this call created our directory.
    ROOT.mkdir(mode=0o755)
    policy = ROOT / "policy"
    load_attempted = False
    try:
        ROOT.chmod(0o755)
        require(ROOT.stat().st_uid == 0 and ROOT.stat().st_mode & 0o022 == 0,
                "new fixture directory ownership/mode mismatch")
        policy.write_bytes((source / "constructicon-m8-noexec.apparmor").read_bytes())
        policy.chmod(0o444)
        fixture = ROOT / "fixture.c"
        fixture.write_bytes((source / "m8_noexec_fixture.c").read_bytes())
        fixture.chmod(0o444)
        for name, defines in (("launch", ["-DLAUNCHER"]), ("payload", [])):
            checked(["/usr/bin/cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                     *defines, str(fixture), "-o", str(ROOT / name)])
            (ROOT / name).chmod(0o555)
        shutil.copyfile(ROOT / "launch", ROOT / "missing-launch")
        (ROOT / "missing-launch").chmod(0o555)
        store = ROOT / "fake-store"
        store.write_bytes(b"a")
        os.chown(store, service.pw_uid, service.pw_gid)
        store.chmod(0o600)
        prefix = ["/usr/bin/sudo", "-n", "-u", "m8-service", "--"]
        # Positive execution controls precede loading any profile. All targets
        # and both FD routes must actually execute, not merely exist.
        for operation in OPERATIONS:
            exact(run([*prefix, str(ROOT / "payload"), operation]), 0,
                  f"control-label:unconfined\nattempt:{operation}\n".encode())
        load_attempted = True
        checked(["/usr/sbin/apparmor_parser", "--add", "--skip-cache", str(policy)])
        validate_profiles(POLICIES.read_text(), present=True)
        exact(run([*prefix, str(ROOT / "missing-launch")]), 77, b"initial-exec-refused:13\n")
        exact(run([*prefix, str(ROOT / "launch")], b"ping\n"), 0, expected_transcript())
        require(store.read_bytes() == b"b", "same-process write was not observed externally")
        validate_profiles(POLICIES.read_text(), present=True)
        report = {
            "schema_version": 1, "scope": "standalone_fake_no_further_exec_only",
            "production_available": False, "claude_qualified": False,
            "profile_enforced": True, "initial_launch_and_exchange": True,
            "unconfined_execution_controls": list(OPERATIONS),
            "denied_execution": [*OPERATIONS, "fork-child"],
            "missing_transition_refused": True, "child_joined": True,
            "same_process_file_and_socket_io_remain": True,
            "policy_sha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
            "fixture_source_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "fixture_binary_sha256": hashlib.sha256((ROOT / "payload").read_bytes()).hexdigest(),
        }
    finally:
        # No policy is unloaded before every fixed probe call has joined.
        # A partially successful parser load must also be accounted for.
        if load_attempted:
            loaded = [line for line in POLICIES.read_text().splitlines() if line.startswith(PREFIX)]
            if loaded:
                checked(["/usr/sbin/apparmor_parser", "--remove", "--skip-cache", str(policy)])
            validate_profiles(POLICIES.read_text(), present=False)
        # Exact exclusive directory owned by this invocation, never caller input.
        shutil.rmtree(ROOT)
    report["cleanup_complete"] = True
    return report


def main() -> int:
    def interrupted(signum: int, _frame: object) -> None:
        # Finish owned cleanup even if cancellation is delivered a second time.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise InterruptedError("standalone proof interrupted")

    previous = {number: signal.signal(number, interrupted)
                for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        try:
            require(len(sys.argv) == 1, "proof accepts no arguments")
            report = prove()
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            print(json.dumps({"scope": "standalone_fake_no_further_exec_only", "passed": False}))
            return 1
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    print(json.dumps({**report, "passed": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
