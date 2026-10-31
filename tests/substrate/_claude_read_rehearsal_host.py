"""Disposable hosted provisioning for the actual generated Claude READ chain.

Only the vendor archive and private drift observer are test doubles. The
artifact helpers, locked controller closure, D2 probe, store and READ commands
are real. Fixture git commits explicitly pin the fake archive; they make no
claim about reviewed main or the private host. Run only after other foundation
consumers have finished, as root with RUNNER_ENVIRONMENT=github-hosted.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]
ROOT = Path("/var/lib/constructicon-m8-claude-read-rehearsal")
HOME = Path("/home/runner")
WORK = HOME / "m8-claude-read-rehearsal-host"
D2 = WORK / "d2"
CONTROLLER = WORK / "controller"
LAUNCH = WORK / "launch"
INSTALLED = Path("/var/lib/constructicon-m8-claude")
CONTROLLER_ROOT = Path("/opt/constructicon-m8-controller")
QUALIFICATION_ROOT = Path("/opt/constructicon-m8-qualification")
OPT = Path("/opt")
STORES = Path("/var/lib/constructicon-m8-claude-stores")
CHECKERS = Path("/opt/constructicon-m8-claude-read-checker")
CHECKER = CHECKERS / "check_claude_phase.py"
DRIFT = Path("/usr/local/bin/m8-host-drift")
CLAUDE_POLICY = Path("/etc/apparmor.d/constructicon-m8-claude")
D2_POLICY = Path("/etc/apparmor.d/constructicon-m8-bwrap")
CAPTURE = HOME / "m8-claude-first-read-rehearsal"
RUN = Path("/var/lib/m8-cr-run")
AUTH = Path("/var/lib/m8-cr-auth")
ACQ = Path("/var/lib/m8-cr-acq")
SESSION_PATHS = (CAPTURE, RUN, AUTH, ACQ, *(
    path.with_name(path.name + "-" + case)
    for case in ("accept", "abort") for path in (CAPTURE, RUN, AUTH, ACQ)
))
ENV = {"PATH": "/usr/bin:/bin", "HOME": str(HOME), "LANG": "C.UTF-8",
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_GRAFT_FILE": "/nonexistent"}


def require(ok: object, message: str) -> None:
    if not ok:
        raise ValueError(message)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnostic(raw: bytes, limit: int = 4096) -> str:
    text = raw[:limit].decode("utf-8", errors="replace")
    return text + (f" [truncated; {len(raw)} bytes total]" if len(raw) > limit else "")


def command(argv: list[str], *, user: str | None = None, data: bytes = b"",
            cwd: Path = Path("/"), timeout: int = 120,
            operation: str = "fixed provisioning command") -> bytes:
    requested = list(argv)
    if user:
        argv = ["/usr/bin/sudo", "-n", "-u", user, "/usr/bin/env", "-i",
                *(key + "=" + value for key, value in ENV.items()), *argv]
    result = subprocess.run(argv, input=data, capture_output=True, check=False,
                            timeout=timeout, cwd=cwd, env=ENV)
    if result.returncode != 0 or result.stderr:
        raise ValueError(
            f"fixture command failed: operation={operation!r} user={user or 'root'!r} "
            f"cwd={str(cwd)!r} returncode={result.returncode} "
            f"argv={diagnostic(json.dumps(requested).encode())}\n"
            f"stdout ({len(result.stdout)} bytes): {diagnostic(result.stdout)}\n"
            f"stderr ({len(result.stderr)} bytes): {diagnostic(result.stderr)}"
        )
    return result.stdout


def write(path: Path, raw: bytes, mode: int = 0o444, owner: str = "root") -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    command(["/usr/bin/chown", owner + ":" + owner, str(path)])
    path.chmod(mode)


def directory(path: Path, owner: str = "root", mode: int = 0o755) -> None:
    require(not os.path.lexists(path), "fixture destination is not fresh")
    command(["/usr/bin/install", "-d", "-o", owner, "-g", owner,
             "-m", oct(mode)[2:], str(path)])


def profiles() -> bytes:
    return Path("/sys/kernel/security/apparmor/profiles").read_bytes()


def install_tree(source: Path, destination: Path) -> None:
    require(not os.path.lexists(destination), "fixture install destination exists")
    command(["/usr/bin/cp", "-a", "--", str(source), str(destination)])
    command(["/usr/bin/chown", "-R", "root:root", str(destination)])


def helper(workspace: Path, commit: str, operation: str, *, claude: bool = False,
           config: str | None = None, listing: bool = True) -> dict:
    name = "claude_host_artifacts.py" if claude else "m8_host_artifacts.py"
    argv = ["/usr/bin/python3", "-I", str(workspace / name), operation,
            commit, str(workspace)]
    if config is not None:
        argv += ["--launch-config-sha256", config]
    return json.loads(command(argv, user="runner", data=profiles() if listing else b"",
                              operation=f"{operation} workspace={workspace}"))


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def protect_opt() -> None:
    """The hosted image makes /opt 0777; satisfy the unchanged root-custody law.

    This changes only the disposable runner after other foundation consumers
    finish. Save the exact original mode before tightening, and restore it only
    after every rehearsal installation beneath /opt has been removed.
    """
    info = OPT.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == info.st_gid == 0
            and OPT.resolve(strict=True) == OPT, "hosted /opt custody refused")
    original = stat.S_IMODE(info.st_mode)
    identity = {"original_mode": original, "device": info.st_dev, "inode": info.st_ino,
                "uid": info.st_uid, "gid": info.st_gid}
    write(ROOT / "opt-custody.json", json.dumps(identity, sort_keys=True).encode())
    _sync_directory(ROOT)
    OPT.chmod(0o755)
    after = OPT.lstat()
    require(stat.S_IMODE(after.st_mode) == 0o755
            and (after.st_dev, after.st_ino, after.st_uid, after.st_gid)
            == (info.st_dev, info.st_ino, 0, 0), "hosted /opt hardening failed")
    print(json.dumps({"operation": "hosted-opt-custody", "before_mode": oct(original),
                      "after_mode": oct(stat.S_IMODE(after.st_mode)),
                      "root_owned": True, "same_directory": True}, sort_keys=True), flush=True)


def fixture_repository(archive: Path, member: bytes) -> str:
    """A fresh, explicitly synthetic first-parent source with only vendor pins replaced."""
    tree = WORK / "fixture-source"
    changes: dict[str, dict[str, str]] = {}
    directory(tree, "runner", 0o700)
    names = ["scripts/ci/m8_host_artifacts.py", "scripts/ci/qualify_m8_runner.py",
             "scripts/ci/constructicon-m8-bwrap.apparmor", "scripts/claude_host_artifacts.py",
             "scripts/constructicon-m8-claude.apparmor", "scripts/check_claude_phase.py", "uv.lock"]
    names += [path.relative_to(SOURCE).as_posix()
              for path in sorted((SOURCE / "src/constructicon").rglob("*"))
              if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"]
    for name in names:
        target = tree / name
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = (SOURCE / name).read_bytes()
        if name == "scripts/claude_host_artifacts.py":
            from scripts import claude_host_artifacts as host
            for key, old, new in (
                ("ARCHIVE_SHA256", repr(host.ARCHIVE_SHA256),
                 repr(hashlib.sha256(archive.read_bytes()).hexdigest())),
                ("MEMBER_SHA256", repr(host.MEMBER_SHA256),
                 repr(hashlib.sha256(member).hexdigest())),
                ("MEMBER_SIZE", str(host.MEMBER_SIZE), str(len(member))),
            ):
                old = old.replace("'", '"')
                new = new.replace("'", '"')
                before = (key + " = " + old).encode()
                require(raw.count(before) == 1, "fixture pin substitution is ambiguous")
                raw = raw.replace(before, (key + " = " + new).encode())
                changes[key] = {"original": old, "fixture": new}
        target.write_bytes(raw)
        target.chmod(0o644)
    write(ROOT / "synthetic-inputs.json", json.dumps(changes, sort_keys=True).encode())
    command(["/usr/bin/chown", "-R", "runner:runner", str(tree)])
    command(["/usr/bin/git", "init", "-q", "-b", "main"], user="runner", cwd=tree)
    command(["/usr/bin/git", "add", "--all"], user="runner", cwd=tree)
    command(["/usr/bin/git", "-c", "user.name=Rehearsal Fixture", "-c",
             "user.email=fixture@example.invalid", "commit", "-q", "-m",
             "Synthetic fake-only READ host inputs"], user="runner", cwd=tree)
    commit = command(["/usr/bin/git", "rev-parse", "HEAD"],
                     user="runner", cwd=tree).decode().strip()
    for workspace in (D2, CONTROLLER, LAUNCH):
        directory(workspace, "runner", 0o700)
        command(["/usr/bin/git", "clone", "-q", "--bare", str(tree),
                 str(workspace / "source.git")], user="runner")
        name = "claude_host_artifacts.py" if workspace == LAUNCH else "m8_host_artifacts.py"
        source = ("scripts/claude_host_artifacts.py" if workspace == LAUNCH
                  else "scripts/ci/m8_host_artifacts.py")
        write(workspace / name, (tree / source).read_bytes(), 0o600, "runner")
    return commit


def provision_d2(commit: str) -> None:
    from scripts.ci import m8_host_artifacts as artifacts
    directory(D2 / "staging", "runner", 0o700)
    for target, (source, mode) in artifacts.FILES.items():
        raw = (SOURCE / source).read_bytes() if source else Path("/usr/bin/bwrap").read_bytes()
        write(D2 / "staging" / Path(target).name, raw, mode, "runner")
    require(helper(D2, commit, "judge")["ready"] is True, "D2 judge refused")
    directory(QUALIFICATION_ROOT)
    for target, (_, mode) in artifacts.FILES.items():
        command(["/usr/bin/install", "-o", "root", "-g", "root", "-m", oct(mode)[2:],
                 str(D2 / "staging" / Path(target).name), "/" + target])
    command(["/usr/sbin/apparmor_parser", "--add", "--skip-cache", str(D2_POLICY)])
    (D2 / "staging").rename(D2 / "staging-retired")
    write(D2 / "profiles-verify", profiles(), 0o600, "runner")
    verified = helper(D2, commit, "verify")
    require(verified["installed"] is True, "D2 verification refused")
    write(D2 / "verify.json", (json.dumps(verified) + "\n").encode(), 0o600, "runner")
    command(["/usr/sbin/useradd", "--create-home", "--shell", "/bin/sh", "m8-probe"])
    raw = command(["/usr/bin/python3", str(QUALIFICATION_ROOT / "probe.py"),
                   "--commit", commit, "--image", "local-hyperv/ubuntu-24.04.5"], user="m8-probe")
    require(json.loads(raw)["qualified"] is True, "D2 probe did not qualify")
    write(D2 / "qualification.json", raw, 0o600, "runner")


def provision_controller(commit: str) -> None:
    from scripts.ci import acquire_m8_controller_wheels as wheels
    from scripts.ci import m8_host_artifacts as artifacts
    wheels.acquire(CONTROLLER / "wheels", wheels.selected_wheels(
        (SOURCE / "uv.lock").read_bytes(), artifacts.host_glibc()))
    command(["/usr/bin/chown", "-R", "runner:runner", str(CONTROLLER / "wheels")])
    require(helper(CONTROLLER, commit, "stage-controller", listing=False)["staged"] is True,
            "controller stage refused")
    require(helper(CONTROLLER, commit, "judge-controller", listing=False)["ready"] is True,
            "controller judge refused")
    install_tree(CONTROLLER / "staging/controller", CONTROLLER_ROOT)
    (CONTROLLER / "staging").rename(CONTROLLER / "staging-retired")
    require(helper(CONTROLLER, commit, "verify-controller", listing=False)["installed"] is True,
            "controller verification refused")
    checked = json.loads(command(["/usr/bin/python3", "-I", "-S", "-B", "-c",
                                 artifacts.controller_check(),
                                 "constructicon.api.claude_qualification",
                                 "constructicon.substrate.executors.claude_lane"],
                                user="m8-service"))
    require(checked["passed"] is True and checked["outside"] == [],
            "controller import closure refused")


def retire_prior_fake() -> None:
    """The earlier foundation fixture is finished; refuse any unfamiliar install."""
    if not os.path.lexists(INSTALLED):
        return
    require(INSTALLED.is_dir() and not INSTALLED.is_symlink()
            and INSTALLED.stat().st_uid == 0, "prior fixture custody differs")
    record = json.loads((INSTALLED / "fixture.json").read_bytes())
    require(record["scope"] == "fake_native_composition_fixture"
            and record["production_available"] is False and record["claude_qualified"] is False,
            "prior installation is not the disposable fake fixture")
    command(["/usr/sbin/apparmor_parser", "--remove", "--skip-cache", str(CLAUDE_POLICY)])
    CLAUDE_POLICY.unlink()
    shutil.rmtree(INSTALLED)


def provision_launch(commit: str, archive: Path) -> dict:
    from scripts import claude_host_artifacts as host
    shutil.copyfile(archive, LAUNCH / host.ARCHIVE)
    command(["/usr/bin/chown", "runner:runner", str(LAUNCH / host.ARCHIVE)])
    destinations = [["platform.claude.com", 443, "8.8.8.8"],
                    ["api.anthropic.com", 443, "1.1.1.1"]]
    selection = {"schema_version": 1, "model": "fixture-ready", "effort": "low",
                 "egress": {phase: {"destinations": destinations[:1] if phase == "login"
                                    else destinations, "connections": 16}
                            for phase in ("login", "observe", "reload")}}
    write(LAUNCH / host.SELECTION, json.dumps(selection).encode(), 0o600, "runner")
    staged = helper(LAUNCH, commit, "stage", claude=True, listing=False)
    require(staged["staged"] is True, "Claude stage refused")
    pin = staged["launch_config_sha256"]
    require(helper(LAUNCH, commit, "judge", claude=True, config=pin)["ready"] is True,
            "Claude judge refused")
    install_tree(LAUNCH / "staging/constructicon-m8-claude", INSTALLED)
    command(["/usr/bin/install", "-o", "root", "-g", "root", "-m", "0444",
             str(LAUNCH / "staging/constructicon-m8-claude.apparmor"), str(CLAUDE_POLICY)])
    command(["/usr/sbin/apparmor_parser", "--add", "--skip-cache", str(CLAUDE_POLICY)])
    (LAUNCH / "staging").rename(LAUNCH / "staging-retired")
    require(helper(LAUNCH, commit, "verify", claude=True, config=pin)["installed"] is True,
            "Claude installed verification refused")
    return staged


DRIFT_CODE = '''#!/usr/bin/python3
"""Test-scoped platform observer; not the private historical drift tool."""
import hashlib,json,os,pathlib,stat,subprocess
base=pathlib.Path("/var/lib/constructicon-m8-claude-read-rehearsal/drift-baseline.json")
record=json.loads(base.read_bytes())
assert pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()==record["boot"]
for name, expected in record["files"].items():
 p=pathlib.Path(name); s=p.lstat()
 assert [s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink]==expected[:4]
 assert hashlib.sha256(p.read_bytes()).hexdigest()==expected[4]
for name,expected in record["directories"].items():
 p=pathlib.Path(name);s=p.lstat()
 assert stat.S_ISDIR(s.st_mode) and [s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode)]==expected
 assert sorted(x.name for x in p.iterdir())==record["entries"][name]
for name,expected in record["links"].items():
 assert os.readlink(name)==expected
result=subprocess.run(["/usr/bin/sudo","-n","/usr/bin/cat","/sys/kernel/security/apparmor/profiles"],stdin=subprocess.DEVNULL,capture_output=True,check=True)
assert result.stderr==b""
current=sorted(x for x in result.stdout.decode().splitlines() if x.startswith("constructicon-m8-"))
assert current==record["profiles"]
print("rehearsal immutable platform checked")
'''


def provision_drift() -> None:
    immutable = [INSTALLED, CONTROLLER_ROOT, QUALIFICATION_ROOT, CHECKERS]
    record: dict = {"boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                    "files": {}, "directories": {}, "entries": {}, "links": {},
                    "profiles": sorted(x for x in profiles().decode().splitlines()
                                       if x.startswith("constructicon-m8-"))}
    for path in [*(p for root in immutable for p in (root, *root.rglob("*"))),
                 CLAUDE_POLICY, D2_POLICY]:
        info = path.lstat()
        if path.is_symlink():
            record["links"][str(path)] = os.readlink(path)
        elif path.is_dir():
            record["directories"][str(path)] = [info.st_uid, info.st_gid,
                                                 stat.S_IMODE(info.st_mode)]
            record["entries"][str(path)] = sorted(p.name for p in path.iterdir())
        else:
            record["files"][str(path)] = [info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode),
                                         info.st_nlink,
                                         hashlib.sha256(path.read_bytes()).hexdigest()]
    write(ROOT / "drift-baseline.json", json.dumps(record, sort_keys=True).encode())
    write(DRIFT, DRIFT_CODE.encode(), 0o555)
    require(command([str(DRIFT)], user="runner") == b"rehearsal immutable platform checked\n",
            "fixture drift observer refused its baseline")
    # Exercise the refusing path against a real changed immutable file, then
    # restore precisely the original mode. Store/session mutations are omitted
    # from the baseline so the actual operator phases can publish normally.
    try:
        CHECKER.chmod(0o440)
        refused = subprocess.run(
            ["/usr/bin/sudo", "-n", "-u", "runner", str(DRIFT)],
            input=b"", capture_output=True, check=False, timeout=120, env=ENV,
        )
        require(refused.returncode != 0 and refused.stdout == b""
                and b"AssertionError" in refused.stderr,
                "fixture observer did not refuse changed immutable custody")
    finally:
        CHECKER.chmod(0o444)
    require(command([str(DRIFT)], user="runner") == b"rehearsal immutable platform checked\n",
            "fixture observer did not recover after exact mode restoration")


def provision() -> None:
    import pwd

    try:
        pwd.getpwnam("m8-probe")
    except KeyError:
        pass
    else:
        raise ValueError("fixture probe account is not fresh")
    for path in (ROOT, WORK, CONTROLLER_ROOT, QUALIFICATION_ROOT, STORES, CHECKERS,
                 DRIFT, D2_POLICY, *SESSION_PATHS):
        require(not os.path.lexists(path), "rehearsal requires fresh fixed destinations")
    require(not list(HOME.glob("read-rehearsal-*-*")), "remote package destinations exist")
    retire_prior_fake()
    directory(ROOT)
    # Created first so cleanup can identify exactly this invocation's custody.
    write(ROOT / "owned.json", b'{"schema_version":1,"scope":"fake-read-rehearsal"}\n')
    protect_opt()
    directory(WORK, "runner", 0o700)
    peer = ROOT / "fake-claude"
    command(["/usr/bin/cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
             str(SOURCE / "scripts/ci/m8_claude_peer.c"), "-o", str(peer)])
    payload = peer.read_bytes()
    archive = ROOT / "claude.tgz"
    with tarfile.open(archive, "w:gz") as package:
        member = tarfile.TarInfo("package/claude")
        member.size, member.mode = len(payload), 0o555
        package.addfile(member, io.BytesIO(payload))
    commit = fixture_repository(archive, payload)
    provision_d2(commit)
    provision_controller(commit)
    staged = provision_launch(commit, archive)
    directory(CHECKERS, mode=0o555)
    write(CHECKER, (SOURCE / "scripts/check_claude_phase.py").read_bytes())
    directory(STORES, mode=0o750)
    from constructicon.substrate.executors import operator_store
    service = pwd.getpwnam("m8-service")
    os.chown(STORES, 0, service.pw_gid)
    operator_store.provision_offline(STORES, "claude-subscription",
                                     service=(service.pw_uid, service.pw_gid))
    credential = (STORES / operator_store._bundle_token("claude-subscription")
                  / "store" / operator_store.CREDENTIAL_FILE)
    write(credential, b"synthetic retained fixture bytes\n", 0o600, "m8-service")
    # Parents are deliberately left absent: the generated parents phase creates them.
    provision_drift()
    from scripts.ops import claude_read_commands as commands
    record = {"schema_version": 2, "controller_commit": commit, "namespace": "read-rehearsal",
              "controller_workspace": str(CONTROLLER), "launch_workspace": str(LAUNCH),
              "mode": "subscription", "values": {
                  **{key: "UNREVIEWED" for key in commands.LATE},
                  "EXPECTED_BOOT": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                  "R": str(CAPTURE), "RUN": str(RUN), "AUTH": str(AUTH), "ACQ": str(ACQ),
                  "QUAL": str(RUN / "qualify.json"), "ACTOR": "static:rehearsal",
                  "READ_KEY": "rehearsal-read-once",
                  "AUTHORIZATION_ID": "rehearsal-read-authorization"},
              "pins": {"launch_commit": commit,
                       "configuration_sha256": staged["launch_config_sha256"],
                       "controller_helper_sha256": file_sha(CONTROLLER / "m8_host_artifacts.py"),
                       "launch_helper_sha256": file_sha(LAUNCH / "claude_host_artifacts.py"),
                       "checker_path": str(CHECKER), "checker_sha256": file_sha(CHECKER),
                       "checker_size": CHECKER.stat().st_size, "drift_sha256": file_sha(DRIFT),
                       "drift_stdout": "rehearsal immutable platform checked\n",
                       "d2_commit": commit, "d2_workspace": str(D2)}}
    bindings = commands.Bindings.from_dict(record)
    commands.values_checked(bindings.expanded(), "d2-preserve")
    write(ROOT / "bindings.json", (json.dumps(record, sort_keys=True) + "\n").encode())
    print(json.dumps({"provisioned": True, "bindings": str(ROOT / "bindings.json")}))


def cleanup() -> None:
    if not ROOT.exists():
        return
    require(ROOT.resolve() == ROOT and ROOT.stat().st_uid == 0
            and json.loads((ROOT / "owned.json").read_bytes()) == {
                "schema_version": 1, "scope": "fake-read-rehearsal"}, "cleanup custody refused")
    for policy in (CLAUDE_POLICY, D2_POLICY):
        if policy.exists():
            require(policy.is_file() and not policy.is_symlink() and policy.stat().st_uid == 0,
                    "cleanup policy custody refused")
            command(["/usr/sbin/apparmor_parser", "--remove", "--skip-cache", str(policy)])
            policy.unlink()
    for path in (INSTALLED, CONTROLLER_ROOT, QUALIFICATION_ROOT, STORES, CHECKERS,
                 WORK, *SESSION_PATHS, *HOME.glob("read-rehearsal-*-*")):
        if os.path.lexists(path):
            require(path.is_dir() and not path.is_symlink() and path.resolve() == path,
                    "cleanup directory custody refused")
            shutil.rmtree(path)
    if DRIFT.exists():
        require(DRIFT.is_file() and not DRIFT.is_symlink() and DRIFT.stat().st_uid == 0,
                "cleanup observer custody refused")
        DRIFT.unlink()
    import pwd

    try:
        probe = pwd.getpwnam("m8-probe")
    except KeyError:
        pass
    else:
        probe_home = Path("/home/m8-probe")
        require(probe.pw_dir == str(probe_home) and probe_home.resolve() == probe_home
                and probe_home.is_dir() and probe_home.stat().st_uid == probe.pw_uid,
                "cleanup probe account custody refused")
        command(["/usr/sbin/userdel", "m8-probe"])
        shutil.rmtree(probe_home)
    custody = ROOT / "opt-custody.json"
    if custody.exists():
        recorded = json.loads(custody.read_bytes())
        original = recorded.get("original_mode")
        info = OPT.lstat()
        require(set(recorded) == {"original_mode", "device", "inode", "uid", "gid"}
                and all(type(value) is int and value >= 0 for value in recorded.values())
                and 0 <= original <= 0o7777 and stat.S_ISDIR(info.st_mode)
                and recorded["uid"] == recorded["gid"] == 0
                and (info.st_dev, info.st_ino, info.st_uid, info.st_gid)
                == (recorded["device"], recorded["inode"], recorded["uid"], recorded["gid"])
                and OPT.resolve(strict=True) == OPT
                and stat.S_IMODE(info.st_mode) in (0o755, original),
                "cleanup hosted /opt custody refused")
        OPT.chmod(original)
        after = OPT.lstat()
        require(stat.S_IMODE(after.st_mode) == original
                and (after.st_dev, after.st_ino, after.st_uid, after.st_gid)
                == (recorded["device"], recorded["inode"], 0, 0),
                "cleanup hosted /opt restoration failed")
    shutil.rmtree(ROOT)


def main() -> None:
    require(sys.platform == "linux" and os.geteuid() == 0
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted",
            "rehearsal provisioning requires the disposable hosted Linux root")
    require(sys.argv[1:] in (["provision"], ["cleanup"]), "expected provision or cleanup")
    if sys.argv[1] == "provision":
        provision()
    else:
        cleanup()


if __name__ == "__main__":
    main()
