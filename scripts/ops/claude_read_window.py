"""One explicit release at a time for the fixed Claude READ procedure.

This entry composes the canonical compiler, transport and receipt checker. It
does not boot a VM, grant authority, retry a claimed phase or resume a stopped
window. Its private directory retains uncertain dispatch and cleanup duties.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from scripts.ops import claude_read_commands as commands  # noqa: E402
from scripts.ops import claude_read_session as session  # noqa: E402


class ExternalBoundary:
    """Consume only the whole argv of declared, single-use SSH/SCP operations.

    An injected executor is an explicit alternative, never a fallback. Both
    modes retain affirmative dispositions without publishing private argv.
    """

    def __init__(self, operations, captures, external=None):
        self.operations = {tuple(argv): (name, timeout) for name, argv, timeout in operations}
        commands.require(len(self.operations) == len(operations))
        self.external = external
        self.captures = captures
        self.seen = set()
        self.ledger = captures / "external-dispositions.jsonl"
        with self.ledger.open("xb"):
            pass
        if external is None:
            commands.require(not any(
                key.startswith("CLAUDE_READ_WINDOW_FIXTURE") for key in os.environ
            ))

    def _record(self, argv, disposition, code=None):
        with self.ledger.open("ab") as stream:
            stream.write(session.json_bytes({
                "operation": self.operations[argv][0],
                "argv_sha256": commands.sha(session.json_bytes(list(argv))),
                "disposition": disposition,
                "returncode": code,
            }))
            stream.flush()
            os.fsync(stream.fileno())

    def __call__(self, argv, **kwargs):
        argv = tuple(argv)
        commands.require(argv in self.operations and argv not in self.seen)
        name, timeout = self.operations[argv]
        commands.require(
            set(kwargs) == {"stdin", "shell", "check", "cwd", "timeout", "stdout", "stderr"}
            and kwargs["cwd"] == self.captures.parent
            and type(kwargs["timeout"]) is int and kwargs["timeout"] == timeout
            and
            kwargs.get("stdin") == subprocess.DEVNULL
            and kwargs.get("shell") is False and kwargs.get("check") is False
        )
        for part in ("stdout", "stderr"):
            stream = kwargs[part]
            commands.require(Path(stream.name) == self.captures / (name + "." + part)
                             and stream.mode == "xb" and not stream.closed)
        self.seen.add(argv)
        mode = "native" if self.external is None else "substituted"
        self._record(argv, mode + "-issued")
        try:
            child = (subprocess.run if self.external is None else self.external)(argv, **kwargs)
            commands.require(
                isinstance(child, subprocess.CompletedProcess) and type(child.returncode) is int
            )
        except BaseException:
            self._record(argv, mode + "-uncertain")
            raise
        self._record(argv, mode + "-completed", child.returncode)
        return child

    def complete(self):
        commands.require(self.seen == set(self.operations))
        return {"declared": len(self.operations), "observed": len(self.seen),
                "mode": "native" if self.external is None else "substituted"}


class ReadWindow:
    """Private fixed-phase claims; checked evidence, rather than exit zero, releases progress."""

    def __init__(self, work, config):
        self.work = work
        self.config = config
        self.evidence = Path(config["evidence"])
        self.revision = config["operator_revision"]
        self.target, self.alias = config["target"], config["alias"]

    @classmethod
    def create(cls, bindings_path, evidence, work, operator_revision, target, alias,
               owner_approval_sha256=None):
        commands.require(operator_revision == commands.operator_revision())
        session._target(target, alias)
        commands.require(evidence.is_dir() and not evidence.is_symlink())
        commands.require(owner_approval_sha256 is None or (
            type(owner_approval_sha256) is str and commands.SHA.fullmatch(owner_approval_sha256)
        ))
        raw = commands.bounded(bindings_path, 16384)
        commands.Bindings.from_dict(commands.parsed(raw))
        work.mkdir(mode=0o700)
        config = {
            "schema_version": 1, "operator_revision": operator_revision,
            "bindings_sha256": commands.sha(raw), "evidence": str(evidence.resolve()),
            "target": target, "alias": alias,
            "owner_approval_sha256": owner_approval_sha256,
        }
        session.retain(work / "initial-bindings.json", raw)
        session.retain(work / "window.json", session.json_bytes(config))
        return cls(work.resolve(), config)

    @classmethod
    def load(cls, work):
        commands.require(work.is_dir() and not work.is_symlink())
        config = commands.parsed(commands.bounded(work / "window.json", 4096))
        commands.require(type(config) is dict and set(config) == {
            "schema_version", "operator_revision", "bindings_sha256", "evidence",
            "target", "alias", "owner_approval_sha256",
        })
        commands.require(type(config["schema_version"]) is int and config["schema_version"] == 1)
        commands.require(config["operator_revision"] == commands.operator_revision())
        session._target(config["target"], config["alias"])
        commands.require(config["owner_approval_sha256"] is None or (
            type(config["owner_approval_sha256"]) is str
            and commands.SHA.fullmatch(config["owner_approval_sha256"])
        ))
        window = cls(work.resolve(), config)
        commands.require(window.evidence.is_dir() and not window.evidence.is_symlink())
        raw = commands.bounded(work / "initial-bindings.json", 16384)
        commands.require(commands.sha(raw) == config["bindings_sha256"])
        commands.Bindings.from_dict(commands.parsed(raw))
        return window

    def _package(self, phase):
        return (self.evidence / "cleanup-package" if phase == "withdraw-after"
                else self.work / phase / "package")

    def _next_bindings(self, bindings, phase):
        if phase in commands.LATE_PHASES:
            extra = ({} if phase != "candidate-pins" else {
                "owner_approval": self.evidence / "owner-approval.json",
                "owner_approval_sha256": self.config["owner_approval_sha256"],
            })
            bindings = commands.prepare_late(bindings, phase, self.evidence, **extra)
        return session.json_bytes(bindings.as_dict())

    def _prefix(self):
        bindings_path = self.work / "initial-bindings.json"
        for phase in commands.PHASES:
            checked_path = self.work / phase / "checked.json"
            if not checked_path.exists():
                later = tuple(commands.PHASES)[tuple(commands.PHASES).index(phase) + 1:]
                commands.require(not any(
                    (self.work / name / marker).exists()
                    for name in later for marker in ("claim.json", "checked.json")
                ))
                return phase, bindings_path
            checked = commands.parsed(commands.bounded(checked_path, 1024))
            commands.require(type(checked) is dict and set(checked) == {
                "phase", "manifest", "next_bindings_sha256",
            } and checked["phase"] == phase)
            pins, bindings = commands.package_checked(
                self._package(phase), checked["manifest"], self.revision,
            )
            commands.require(pins["phase"] == phase)
            if phase != "withdraw-after":
                commands.require(commands.bounded(self._package(phase) / "bindings.json", 16384)
                                 == commands.bounded(bindings_path, 16384))
            commands.check_phase_receipt(bindings, phase, self.evidence)
            bindings_path = self.work / phase / "next-bindings.json"
            raw = commands.bounded(bindings_path, 16384)
            commands.require(raw == self._next_bindings(bindings, phase)
                             and commands.sha(raw) == checked["next_bindings_sha256"])
        raise commands.Refused("window is complete")

    def prepare_next(self, *, cleanup=False):
        commands.require(self.revision == commands.operator_revision())
        if cleanup:
            commands.require((self.work / "activate" / "claim.json").is_file())
            phase, bindings_path = "withdraw-after", None
        else:
            # A separately completed cleanup ends the window, including aborts.
            commands.require(not (self.work / "withdraw-after" / "checked.json").exists())
            phase, bindings_path = self._prefix()
        directory = self.work / phase
        commands.require(not (directory / "claim.json").exists())
        directory.mkdir(mode=0o700, exist_ok=True)
        package = self._package(phase)
        if phase == "activate":
            cleanup_package = self.evidence / "cleanup-package"
            if not cleanup_package.exists():
                commands.build_package("withdraw-after", bindings_path, self.evidence,
                                       cleanup_package, self.revision)
            # The canonical activation compiler checks the retained cleanup package.
        if package.exists():
            manifest = commands.sha(commands.bounded(package / "MANIFEST.sha256", 1024))
            pins, _ = commands.validated_package(package, manifest, self.revision, self.evidence)
            commands.require(pins["phase"] == phase)
            if phase != "withdraw-after":
                commands.require(commands.bounded(package / "bindings.json", 16384)
                                 == commands.bounded(bindings_path, 16384))
        else:
            commands.require(bindings_path is not None)
            manifest = commands.build_package(phase, bindings_path, self.evidence,
                                              package, self.revision)
        return {
            "phase": phase, "package": str(package), "manifest": manifest,
            "checks": sorted(commands.COMMON_CHECKS | commands.PHASES[phase].checks),
        }

    def advance(self, grant, grant_sha256, *, cleanup=False, external=None):
        request = self.prepare_next(cleanup=cleanup)
        phase, manifest = request["phase"], request["manifest"]
        package, directory = Path(request["package"]), self.work / phase
        pins, bindings = commands.validated_package(package, manifest, self.revision, self.evidence)
        # Verify an independently supplied release before spending the phase claim.
        session.grant_checked(grant, grant_sha256, manifest, self.revision, pins, bindings,
                              self.target, self.alias)
        captures = directory / "captures"
        captures.mkdir(mode=0o700)
        sequence = session.transport_commands(package, manifest, bindings,
                                              self.target, self.alias, phase)
        operations = [(phase + "-" + name, argv, timeout) for name, argv, timeout in zip(
            ("preflight", "mkdir", "copy", "native"), sequence,
            (120, 120, 120, 600 if phase == "read" else 1800), strict=True,
        )]
        operations += [(phase + "-readback-" + part, session.readback_argv(
            bindings, phase, part, manifest, self.target, self.alias,
        ), 45) for part in commands.PHASES[phase].outputs]
        boundary = ExternalBoundary(operations, captures, external)
        session.retain(directory / "claim.json", session.json_bytes({
            "phase": phase, "manifest": manifest, "grant_sha256": grant_sha256,
            "dispatch": "uncertain_until_checked",
        }))
        status = session.one_phase(package, manifest, self.revision, self.evidence,
                                   grant, captures, self.target, self.alias, grant_sha256,
                                   run=boundary)
        if (status["completed"] is True and type(status["returncode"]) is int
                and status["returncode"] in (0, 1) and status["timed_out"] is False):
            for part in commands.PHASES[phase].outputs:
                session.readback(package, manifest, self.revision, self.evidence, part,
                                 captures, self.target, self.alias, run=boundary)
        commands.require(commands.completed_zero(status))
        observed = boundary.complete()
        commands.check_phase_receipt(bindings, phase, self.evidence)
        raw = self._next_bindings(bindings, phase)
        session.retain(directory / "next-bindings.json", raw)
        session.retain(directory / "checked.json", session.json_bytes({
            "phase": phase, "manifest": manifest, "next_bindings_sha256": commands.sha(raw),
        }))
        return {"phase": phase, "checked": True, "external": observed,
                "cleanup_required": phase != "withdraw-after" and
                (self.work / "activate" / "claim.json").exists()}


def main(argv=None, *, external=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("describe", allow_abbrev=False)
    create = actions.add_parser("create", allow_abbrev=False)
    for name in ("bindings", "evidence", "work"):
        create.add_argument("--" + name, type=Path, required=True)
    for name in ("operator-revision", "target", "alias"):
        create.add_argument("--" + name, required=True)
    create.add_argument("--owner-approval-sha256")
    for action in ("prepare", "advance"):
        sub = actions.add_parser(action, allow_abbrev=False)
        sub.add_argument("--work", type=Path, required=True)
        sub.add_argument("--cleanup", action="store_true")
        if action == "advance":
            sub.add_argument("--grant", type=Path, required=True)
            sub.add_argument("--grant-sha256", required=True)
    args = parser.parse_args(argv)
    if args.action == "describe":
        result = {"operator_revision": commands.operator_revision(),
                  "phases": list(commands.PHASES), "release": "one independent phase grant",
                  "retry": False, "vm_management": False,
                  "mutating_inventory_phases": ["pre-reload-inventory", "inventory"]}
    elif args.action == "create":
        ReadWindow.create(args.bindings, args.evidence, args.work, args.operator_revision,
                          args.target, args.alias, args.owner_approval_sha256)
        result = {"created": True}
    else:
        window = ReadWindow.load(args.work)
        result = (window.prepare_next(cleanup=args.cleanup) if args.action == "prepare"
                  else window.advance(args.grant, args.grant_sha256,
                                      cleanup=args.cleanup, external=external))
    sys.stdout.buffer.write(session.json_bytes(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("Claude READ window refused; retain claims and discharge any cleanup duty",
              file=sys.stderr)
        raise SystemExit(1) from None
