"""Benign runner prerequisites only, never a production availability decision.

No provisioning, policy writes, network calls, repository imports, or credentials.
Run on Linux as the intended non-root account; unsupported hosts fail explicitly.
The separate workflow owns provisioning on its disposable GitHub-hosted VM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

BWRAP = "/opt/constructicon-m8-qualification/bwrap"
PACKAGE = "0.9.0-1ubuntu0.1"
BWRAP_SHA256 = "52231e1caf55bcbc667b269f49c63599a6f7db4767ae6a039580d0ff853db712"
POLICY = Path("/etc/apparmor.d/constructicon-m8-bwrap")
POLICY_SHA256 = "9375aeda9db21f862c5456d0734c4fdc3f21769f23bbc2b6abd1503fc3b4590b"
CHILD_PROFILE = "constructicon-m8-bwrap//&constructicon-m8-payload (enforce)"
RESTRICTION = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
NAMESPACES = ("user", "mnt", "pid", "ipc", "uts", "net")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    # Only fixed benign programs are run. This is not M8's hostile-output pump.
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"},
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def artifact_digest(path: Path, expected: str) -> str:
    metadata = path.stat()
    require(
        metadata.st_uid == 0 and metadata.st_mode & 0o6022 == 0,
        f"artifact is not root-owned, read-only to others, and non-set-ID: {path}",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    require(digest == expected, f"reviewed artifact drift: {path}")
    return digest


def permission_refusal(returncode: int, stderr: str) -> str | None:
    # Explicit userns denial is EACCES; global restrictions may instead strip
    # capabilities, stopping the unprofiled launcher at loopback setup (EPERM).
    # Never count a different operation's failure as the expected refusal.
    stages = {
        "bwrap: Creating new namespace failed: Permission denied": "namespace_creation",
        "bwrap: Creating new namespace failed: Operation not permitted": "namespace_creation",
        "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted": "loopback_setup",
    }
    return stages.get(stderr.strip()) if returncode == 1 else None


def sandbox_argv(workspace: Path, script: str) -> list[str]:
    # This minimal diagnostic root borrows system userspace read-only. It is NOT
    # PR B's content-pinned runtime or final launcher; no untrusted input runs.
    return [
        BWRAP,
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-net",
        "--new-session",
        "--die-with-parent",
        "--cap-drop",
        "ALL",
        "--uid",
        str(os.getuid()),
        "--gid",
        str(os.getgid()),
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        BWRAP,
        "/bwrap",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--ro-bind",
        str(workspace),
        "/workspace",
        "--chdir",
        "/workspace",
        "--",
        "/usr/bin/python3",
        "-I",
        "-c",
        script,
    ]


CHILD = r"""
import json, os, pathlib, subprocess
p = pathlib.Path
state = {
    "uid": os.getuid(), "gid": os.getgid(),
    "namespaces": {n: os.readlink("/proc/self/ns/" + n)
                   for n in ("user", "mnt", "pid", "ipc", "uts", "net")},
    "apparmor": p("/proc/self/attr/current").read_text().strip(),
    "uid_map": p("/proc/self/uid_map").read_text().strip(),
    "gid_map": p("/proc/self/gid_map").read_text().strip(),
    "status": [line for line in p("/proc/self/status").read_text().splitlines()
               if line.startswith(("NoNewPrivs:", "CapEff:"))],
    "net_dev": p("/proc/net/dev").read_text(),
    "host_home_visible": p("/home/m8-probe").exists(),
    "sys_visible": p("/sys").exists(),
}
try:
    p("/workspace/sentinel").write_text("changed")
    state["write_errno"] = None
except OSError as e:
    state["write_errno"] = e.errno
nested = subprocess.run(
    ["/bwrap", "--unshare-user", "--ro-bind", "/", "/", "/bin/true"],
    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5,
)
state["nested_returncode"] = nested.returncode
state["nested_stderr"] = nested.stderr[:2048]
print(json.dumps(state, sort_keys=True))
"""


def validate_child(child: dict, host: dict, uid: int, gid: int) -> None:
    require(child["uid"] == uid and child["gid"] == gid, "service UID/GID mapping changed")
    # Pinned bwrap's --dev setup maps the service ID through UID/GID 0 in
    # an intermediate user namespace. Column two is that parent, NOT host root.
    require(
        child["uid_map"].split() == [str(uid), "0", "1"]
        and child["gid_map"].split() == [str(gid), "0", "1"],
        "service identity mapping is not exactly one UID/GID",
    )
    require(
        all(child["namespaces"][n] != host[n] for n in NAMESPACES),
        "required namespace remained shared",
    )
    require(child["write_errno"] == 30, "workspace write was not denied by a read-only mount")
    require(
        not child["host_home_visible"] and not child["sys_visible"], "host home or sysfs is visible"
    )
    require(
        "NoNewPrivs:\t1" in child["status"] and "CapEff:\t0000000000000000" in child["status"],
        "no-new-privileges or dropped capabilities missing",
    )
    require(
        child["apparmor"] == CHILD_PROFILE,
        "exact enforcing child AppArmor attachment is absent",
    )
    require(
        permission_refusal(child["nested_returncode"], child["nested_stderr"])
        == "namespace_creation",
        "nested bubblewrap did not produce the expected permission refusal",
    )
    interfaces = [line.split(":", 1)[0].strip() for line in child["net_dev"].splitlines()[2:]]
    require(interfaces == ["lo"], "sandbox has a non-loopback network interface")


def qualify(evidence: dict) -> None:
    require(sys.platform == "linux", "Linux prerequisites were not exercised on this host")
    uid, gid = os.getuid(), os.getgid()
    evidence["service"] = {"uid": uid, "gid": gid, "groups": os.getgroups()}
    require(uid != 0 and gid != 0, "qualification must not run as root")
    require(
        run(["/usr/bin/sudo", "-n", "/usr/bin/true"]).returncode != 0,
        "service user has passwordless sudo",
    )
    evidence["os_release"] = platform.freedesktop_os_release()
    require(
        evidence["os_release"].get("ID") == "ubuntu"
        and evidence["os_release"].get("VERSION_ID") == "24.04",
        "expected Ubuntu 24.04",
    )
    evidence["apparmor_enabled"] = read(Path("/sys/module/apparmor/parameters/enabled"))
    require(evidence["apparmor_enabled"] == "Y", "AppArmor is not enabled")
    evidence["userns_restriction"] = read(RESTRICTION)
    require(
        evidence["userns_restriction"] == "1", "global user-namespace restriction is not enabled"
    )
    package = run(["/usr/bin/dpkg-query", "-W", "-f=${Version}", "bubblewrap"])
    evidence["bubblewrap_package"] = package.stdout
    require(package.returncode == 0 and package.stdout == PACKAGE, "bubblewrap package drift")
    evidence["bubblewrap_sha256"] = artifact_digest(Path(BWRAP), BWRAP_SHA256)
    evidence["policy_sha256"] = artifact_digest(POLICY, POLICY_SHA256)
    evidence["apparmor_abi_sha256"] = hashlib.sha256(
        Path("/etc/apparmor.d/abi/4.0").read_bytes()
    ).hexdigest()
    evidence["host_namespaces"] = {n: os.readlink("/proc/self/ns/" + n) for n in NAMESPACES}
    with TemporaryDirectory(prefix="m8-qualification-") as directory:
        workspace = Path(directory)
        (workspace / "sentinel").write_text("unchanged", encoding="utf-8")
        result = run(sandbox_argv(workspace, CHILD))
        evidence["outer_returncode"] = result.returncode
        evidence["outer_stderr"] = result.stderr[:2048]
        require(result.returncode == 0, "outer namespace probe failed before qualification")
        child = json.loads(result.stdout)
        evidence["child"] = child
        validate_child(child, evidence["host_namespaces"], uid, gid)
        require(read(workspace / "sentinel") == "unchanged", "host sentinel changed")
        # Same executable and dependencies, but no private-path attachment.
        # Do not unload a host policy just to test its absence.
        unprofiled = workspace / "unprofiled-bwrap"
        shutil.copyfile(BWRAP, unprofiled)
        unprofiled.chmod(0o755)
        argv = sandbox_argv(workspace, "print('unexpected launch')")
        argv[0] = str(unprofiled)
        denied = run(argv)
        evidence["unprofiled_returncode"] = denied.returncode
        evidence["unprofiled_stderr"] = denied.stderr[:2048]
        evidence["unprofiled_refusal_stage"] = permission_refusal(denied.returncode, denied.stderr)
        require(
            evidence["unprofiled_refusal_stage"] is not None,
            "unprofiled launch did not produce the expected permission refusal",
        )
    require(read(RESTRICTION) == "1", "global restriction changed during probe")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    evidence = {
        "schema_version": 1,
        "scope": "runner_prerequisites_only",
        "production_available": False,
        "commit": args.commit[:64],
        "image": args.image[:128],
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "qualified": False,
    }
    try:
        qualify(evidence)
        evidence["qualified"] = True
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        evidence["failure"] = f"{type(exc).__name__}: {exc}"[:2048]
    print(json.dumps(evidence, sort_keys=True, indent=2))
    return 0 if evidence["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
