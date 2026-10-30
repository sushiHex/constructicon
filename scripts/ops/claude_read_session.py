"""One explicit Claude READ operator phase; no scheduler, retry or VM action."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

# The local operator entry is site-enabled (-I -B), independent of an older
# editable installation. Guest commands retain their reviewed -I -S -B entry.
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from scripts.ops import claude_read_commands as commands  # noqa: E402 (isolated entry bootstrap)

SSH = "C:/Program Files/Git/usr/bin/ssh.exe" if os.name == "nt" else "/usr/bin/ssh"
SCP = "C:/Program Files/Git/usr/bin/scp.exe" if os.name == "nt" else "/usr/bin/scp"


def retain(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def json_bytes(value):
    return (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")


def capture(name, captures, argv, timeout, max_stdout=4096, *, run=None):
    """Retain actual completion and bounded streams, including nonzero/timeout.

    Bounds are checked after capture; they are not process or disk-write caps.
    An exception cannot turn a partial prefix into a successful receipt.
    """
    commands.require(
        re.fullmatch(r"[a-z0-9-]+", name) and captures.is_dir() and not captures.is_symlink()
    )
    completed, timed_out, code = False, False, None
    with (
        (captures / (name + ".stdout")).open("xb") as stdout,
        (captures / (name + ".stderr")).open("xb") as stderr,
        (captures / (name + ".status.json")).open("xb") as status,
    ):
        try:
            child = (subprocess.run if run is None else run)(
                argv,
                cwd=captures.parent,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                shell=False,
                check=False,
            )
            completed, code = True, child.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            result = {"completed": completed, "returncode": code, "timed_out": timed_out}
            status.write(json_bytes(result))
            for stream in (stdout, stderr, status):
                stream.flush()
                os.fsync(stream.fileno())
    out = commands.bounded(captures / (name + ".stdout"), max_stdout, empty=True)
    err = commands.bounded(captures / (name + ".stderr"), 4096, empty=True)
    return result, out, err


def _target(target, alias):
    commands.require(
        type(target) is str and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}@[0-9.]{7,15}", target)
    )
    commands.require(
        type(alias) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}", alias)
    )


def ssh_options(alias):
    return [
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "HostKeyAlias=" + alias,
        "-o",
        "ConnectTimeout=15",
        "-o",
        "LogLevel=ERROR",
    ]


def _copy_path(path):
    value = path.resolve(strict=True).as_posix()
    if os.name == "nt":
        commands.require(re.fullmatch(r"[A-Za-z]:/[^\r\n:]*", value))
        return "/" + value[0].lower() + value[2:]
    return value


def transport_commands(package, manifest, bindings, target, alias, phase):
    """The same exact argv in production and the credential-free process double."""
    name = commands.remote_name(bindings, phase, manifest)
    return staging_commands(package, manifest, name, target, alias)


def staging_commands(package, manifest, name, target, alias):
    """Existing fixed four-file transport; callers bind the compiled script."""
    _target(target, alias)
    commands.require(
        commands.SHA.fullmatch(manifest) and re.fullmatch(r"[a-z][a-z0-9-]{0,127}", name)
    )
    ssh = [SSH, "-T", *ssh_options(alias), target]
    code = (
        'import os,pathlib,stat,sys;h=pathlib.Path(os.environ["HOME"]);u=os.geteuid();'
        "ok=u!=0 and h==h.resolve(strict=True) and h.stat().st_uid==u and "
        "all(stat.S_ISDIR(s.st_mode) and s.st_uid in (0,u) and not s.st_mode&0o022 "
        "for p in (h,*h.parents) for s in (p.lstat(),));"
        f"ok=ok and not os.path.lexists(h/{name!r});sys.exit(0 if ok else 1)"
    )
    preflight = shlex.join(["/usr/bin/python3", "-I", "-S", "-B", "-c", code])
    mkdir = (
        f'umask 077;test ! -e "$HOME/{name}" && test ! -L "$HOME/{name}" && '
        f'/usr/bin/mkdir -m 0700 "$HOME/{name}"'
    )
    copy = [
        SCP,
        "-q",
        *ssh_options(alias),
        *(
            _copy_path(package / leaf)
            for leaf in ("MANIFEST.sha256", "phase.sh", "bindings.json", "SOURCE-PINS.json")
        ),
        f"{target}:{name}/",
    ]
    execute = (
        f'cd "$HOME/{name}" && '
        f'test "$(/usr/bin/sha256sum MANIFEST.sha256 | /usr/bin/cut -d " " -f 1)" = {manifest} && '
        "/usr/bin/sha256sum --check --strict --quiet MANIFEST.sha256 "
        "&& /bin/bash phase.sh < /dev/null"
    )
    return [*ssh, preflight], [*ssh, mkdir], copy, [*ssh, execute]


def grant_checked(path, expected, manifest, revision, pins, bindings, target, alias):
    raw = commands.bounded(path, 8192)
    commands.require(commands.sha(raw) == expected)
    record = commands.parsed(raw)
    fields = {
        "schema_version",
        "phase",
        "package_manifest",
        "operator_revision",
        "controller_commit",
        "bindings_sha256",
        "boot",
        "target_sha256",
        "checks",
    }
    commands.require(
        type(record) is dict
        and set(record) == fields
        and type(record["schema_version"]) is int
        and record["schema_version"] == 1
    )
    commands.require(
        record["phase"] == pins["phase"]
        and record["package_manifest"] == manifest
        and record["operator_revision"] == revision
        and record["controller_commit"] == bindings.controller_commit
        and record["bindings_sha256"] == pins["bindings_sha256"]
        and record["boot"] == bindings.values["EXPECTED_BOOT"]
        and record["target_sha256"] == commands.sha((target + "\0" + alias).encode())
    )
    checks = record["checks"]
    commands.require(
        type(checks) is dict
        and set(checks) == commands.COMMON_CHECKS | commands.PHASES[pins["phase"]].checks
        and all(value is True for value in checks.values())
    )


def one_phase(
    package,
    manifest,
    operator_revision,
    evidence,
    grant,
    captures,
    target,
    alias,
    grant_sha256=None,
    *,
    run=None,
):
    """Delegate exactly one reviewed phase. Native nonzero grants no successor."""
    _target(target, alias)
    pins, bindings = commands.validated_package(package, manifest, operator_revision, evidence)
    phase = pins["phase"]
    # A caller supplies the independently reviewed digest; reading a file is not approval.
    commands.require(type(grant_sha256) is str and commands.SHA.fullmatch(grant_sha256))
    grant_checked(grant, grant_sha256, manifest, operator_revision, pins, bindings, target, alias)
    context = commands.context_bytes(manifest, pins, bindings)
    retain(captures / (phase + "-context.json"), context)
    sequence = transport_commands(package, manifest, bindings, target, alias, phase)
    for suffix, argv in zip(("preflight", "mkdir", "copy"), sequence[:3], strict=True):
        status, out, err = capture(phase + "-" + suffix, captures, argv, 120, run=run)
        commands.require(commands.completed_zero(status) and out == err == b"")
    if phase == "activate":
        # Preserve duty before possible activation, including interruption prefixes.
        retain(evidence / "activation-may-have-completed.json", context)
    status, out, err = capture(
        phase + "-native", captures, sequence[3], 600 if phase == "read" else 1800, run=run
    )
    retain(evidence / (phase + "-context.json"), context)
    retain(evidence / (phase + ".status.json"), json_bytes(status))
    retain(evidence / (phase + ".stdout"), out)
    retain(evidence / (phase + ".stderr"), err)
    return status


def readback_argv(bindings, phase, part, manifest, target, alias):
    """Declare the exact fixed transport argv before crossing its boundary."""
    _target(target, alias)
    path, limit, service, _ = commands.readback_spec(bindings, phase, part, manifest)
    guard = (
        'test "$(/usr/bin/cat /proc/sys/kernel/random/boot_id)" = '
        + shlex.quote(bindings.values["EXPECTED_BOOT"])
        + " && "
    )
    return [
        SSH, "-T", *ssh_options(alias), target,
        guard + commands.protected_read_command(path, limit, service),
    ]


def readback(package, manifest, operator_revision, evidence, part, captures, target, alias,
             *, run=None):
    """Read one fixed finite metadata output under the actual request context."""
    _target(target, alias)
    pins, bindings = commands.validated_package(package, manifest, operator_revision, evidence)
    phase = pins["phase"]
    context = commands.context_bytes(manifest, pins, bindings)
    commands.require(commands.bounded(captures / (phase + "-context.json"), 2048) == context)
    status = commands.parsed(commands.bounded(captures / (phase + "-native.status.json"), 256))
    commands.require(
        type(status) is dict
        and set(status) == {"completed", "returncode", "timed_out"}
        and status["completed"] is True
        and type(status["returncode"]) is int
        and status["returncode"] in (0, 1)
        and status["timed_out"] is False
    )
    _, limit, _, slot = commands.readback_spec(bindings, phase, part, manifest)
    argv = readback_argv(bindings, phase, part, manifest, target, alias)
    name = phase + "-readback-" + part
    result, raw, err = capture(name, captures, argv, 45, limit, run=run)
    commands.require(commands.completed_zero(result) and err == b"")
    retain(evidence / slot, raw)
    retain(evidence / (name + ".status.json"), json_bytes(result))
    retain(evidence / (name + ".stderr"), err)
    retain(
        evidence / (name + "-context.json"),
        json_bytes(
            {"request": commands.parsed(context), "part": part, "sha256": commands.sha(raw)}
        ),
    )
    return result


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("action", choices=(
        "describe", "prepare-bindings", "prepare-late", "prepare-cleanup",
        "prepare-owner-approval",
        "compile", "check", "transport", "readback",
    ))
    parser.add_argument("--phase", choices=tuple(commands.PHASES))
    parser.add_argument("--operator-revision")
    for name in (
        "bindings", "evidence", "out", "package", "grant", "captures", "installation",
        "owner-approval",
    ):
        parser.add_argument("--" + name, type=Path)
    for name in (
        "manifest", "grant-sha256", "target", "alias", "part", "namespace", "boot",
        "owner-approval-sha256", "controller", "owner-decision",
    ):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    if args.action == "describe":
        result = {
            "operator_revision": commands.operator_revision(),
            "preparation": {
                "installation_fields": list(commands.INSTALLATION_FIELDS),
                "installation_schema_version": 1,
                "installation_pin_fields": sorted(commands.PIN_KEYS),
                "operator_home": "/home/OPERATOR",
                "actor": "trusted transport actor",
                "boot": "explicit measured UUID; omitted remains UNREVIEWED",
                "namespace": "1-30 lowercase letters/digits/hyphens, beginning with a letter",
                "late_phases": {name: list(keys) for name, keys in commands.LATE_PHASES.items()},
                "evidence_slots": {
                    "qualify-check": ["checker.stdout", "qualification.json"],
                    "inventory": ["inventory.json"],
                    "publish": ["published-sealed.json"],
                    "mint": ["authorization-candidate.json"],
                    "candidate-pins": ["candidate-pins.json", "owner-approval.json"],
                },
                "owner_approval": (
                    "existing evidence/owner-approval.json plus independently approved SHA256"
                ),
                "owner_approval_preparation": (
                    "prepare-owner-approval --controller COMMIT --owner-decision URL --out FILE "
                    "--operator-revision REV; file/hash is not permission"
                ),
                "cleanup_package": "evidence/cleanup-package",
                "output": "fresh exclusive bindings file; no grant or owner authority is created",
            },
            "phases": {
                name: {
                    "checks": sorted(commands.COMMON_CHECKS | phase.checks),
                    "readbacks": sorted(phase.outputs),
                }
                for name, phase in commands.PHASES.items()
            },
        }
    elif args.action == "prepare-owner-approval":
        commands.require(args.operator_revision == commands.operator_revision())
        commands.require(args.out is not None)
        raw = json_bytes(commands.prepare_owner_approval(args.controller, args.owner_decision))
        retain(args.out, raw)
        result = {"owner_approval_sha256": commands.sha(raw)}
    elif args.action in ("prepare-bindings", "prepare-late", "prepare-cleanup"):
        commands.require(args.operator_revision == commands.operator_revision())
        if args.action == "prepare-bindings":
            commands.require(all(value is not None for value in (
                args.installation, args.namespace, args.out,
            )))
            bindings = commands.prepare_bindings(
                commands.parsed(commands.bounded(args.installation, 16384)),
                args.namespace, args.boot,
            )
        else:
            commands.require(args.bindings is not None and args.evidence is not None)
            bindings = commands.Bindings.from_file(args.bindings)
            if args.action == "prepare-late":
                commands.require(args.phase is not None and args.out is not None)
                bindings = commands.prepare_late(
                    bindings, args.phase, args.evidence, args.owner_approval,
                    args.owner_approval_sha256,
                )
        if args.action == "prepare-cleanup":
            result = {
                "phase": "withdraw-after",
                "package_manifest": commands.build_package(
                    "withdraw-after", args.bindings, args.evidence,
                    args.evidence / "cleanup-package", args.operator_revision,
                ),
            }
        else:
            raw = json_bytes(bindings.as_dict())
            retain(args.out, raw)
            result = {"bindings_sha256": commands.sha(raw)}
    elif args.action == "compile":
        commands.require(
            all(
                value is not None
                for value in (
                    args.phase,
                    args.bindings,
                    args.evidence,
                    args.out,
                    args.operator_revision,
                )
            )
        )
        result = {
            "phase": args.phase,
            "package_manifest": commands.build_package(
                args.phase, args.bindings, args.evidence, args.out, args.operator_revision
            ),
        }
    else:
        commands.require(
            all(
                value is not None
                for value in (args.package, args.manifest, args.evidence, args.operator_revision)
            )
        )
        if args.action == "check":
            pins, bindings = commands.validated_package(
                args.package, args.manifest, args.operator_revision, args.evidence
            )
            commands.check_phase_receipt(bindings, pins["phase"], args.evidence)
            result = {"phase": pins["phase"], "checked": True}
        else:
            commands.require(
                all(value is not None for value in (args.captures, args.target, args.alias))
            )
            if args.action == "transport":
                commands.require(args.grant is not None and args.grant_sha256 is not None)
                result = one_phase(
                    args.package,
                    args.manifest,
                    args.operator_revision,
                    args.evidence,
                    args.grant,
                    args.captures,
                    args.target,
                    args.alias,
                    args.grant_sha256,
                )
            else:
                commands.require(args.part is not None)
                result = readback(
                    args.package,
                    args.manifest,
                    args.operator_revision,
                    args.evidence,
                    args.part,
                    args.captures,
                    args.target,
                    args.alias,
                )
    sys.stdout.buffer.write(json_bytes(result))
    if args.action == "transport" and not commands.completed_zero(result):
        code = result.get("returncode")
        return code if type(code) is int and 0 < code <= 255 else 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("Claude READ operator step refused", file=sys.stderr)
        raise SystemExit(1) from None
