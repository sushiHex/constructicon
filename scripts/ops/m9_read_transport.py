"""Compose the fixed M9 guest claim with the existing checked phase transport."""

from __future__ import annotations

import base64
import math
import re
import shlex
import time
from dataclasses import astuple
from pathlib import Path

from scripts.ops import claude_read_session as session
from scripts.ops.claude_read_commands import parsed, sha
from scripts.ops.m9_read_closure import ClosurePins, accept_result
from scripts.ops.m9_read_command import BOOT, SERVICE_STATE, SHA, read_argv
from scripts.ops.m9_read_window import TerminalProof

_GUEST = Path(__file__).with_name("m9_read_command.py")
_CLOSURE = Path(__file__).with_name("m9_read_closure.py")
_EXEC = "&& /bin/bash phase.sh < /dev/null"


class StagedRead:
    """One guest directory, shared by dispatch and independent proof.

    The caller selects the actual candidate and authenticates the owner; this
    object stages no authorization and never constitutes a release to run.
    """

    def __init__(
        self,
        package: Path,
        target: str,
        alias: str,
        boot: str,
        claim: str,
        candidate: bytes,
        authorization: str,
        admit_until: int,
        closure: ClosurePins | None = None,
    ) -> None:
        session._target(target, alias)
        if BOOT.fullmatch(boot) is None or SHA.fullmatch(claim) is None:
            raise ValueError("M9_READ_BAD_BOOT_OR_CLAIM")
        if type(candidate) is not bytes or not 0 < len(candidate) <= 8192:
            raise ValueError("M9_READ_BAD_CANDIDATE_BYTES")
        candidate_sha = sha(candidate)
        read_argv(candidate_sha, authorization, admit_until)
        self.candidate = candidate
        self.boot, self.claim = boot, claim
        self._staged = False
        self._issued = False
        self._placement_issued = False
        self._readback_checked = False
        self._discard_issued = False
        self._observed = False
        self._terminal = False
        self._closure = closure
        source = _GUEST.read_bytes().replace(b"\r\n", b"\n")
        closure_branch = ""
        closure_source_sha = None
        if closure is not None:
            selected = parsed(candidate)
            attempt = selected.get("attempt_record") if type(selected) is dict else None
            if (
                closure.trial != "m9-live-1"
                or type(selected) is not dict
                or selected.get("authorization_id") != closure.authorization_id
                or type(attempt) is not str
                or re.fullmatch(
                    re.escape(SERVICE_STATE) + r"/[a-zA-Z0-9_-][a-zA-Z0-9_.-]*", attempt
                ) is None
            ):
                raise ValueError("M9_READ_CLOSURE_BAD_PINS")
            closure_source = _CLOSURE.read_bytes().replace(b"\r\n", b"\n")
            closure_source_sha = sha(closure_source)
            if source.count(b'CLOSURE_SOURCE = b""') != 1:
                raise ValueError("M9_READ_GUEST_SOURCE_BOUND")
            source = source.replace(
                b'CLOSURE_SOURCE = b""',
                b'CLOSURE_SOURCE = base64.b64decode(b"' + base64.b64encode(closure_source) + b'")',
                1,
            )
            args = shlex.join([attempt, *astuple(closure)])
            closure_branch = f" projection) set -- projection --closure-pins {args};;\n"
        if b"\r" in source or b"\nM9_GUEST\n" in source or not source.endswith(b"\n"):
            raise ValueError("M9_READ_GUEST_SOURCE_BOUND")
        # The authorization leaf and candidate are data, not executable input.
        script = (
            (
                "#!/bin/bash\n"
                'test "$#" = 1 || exit 2\n'
                'case "$1" in\n'
                f" dispatch) set -- dispatch --candidate-sha {candidate_sha}"
                f" --authorization {authorization} --admit-until {admit_until};;\n"
                f" place) set -- place --candidate-sha {candidate_sha}"
                f" --authorization {authorization} --admit-until {admit_until}"
                f" --candidate-hex {candidate.hex()};;\n"
                ' readback|discard) set -- "$1"'
                f" --candidate-sha {candidate_sha} --authorization {authorization};;\n"
                ' prove|original) set -- "$1";;\n'
                + closure_branch
                + " *) exit 2;;\n"
                "esac\n"
                f"/usr/bin/python3 -I -S -B - \"$@\" --boot {boot} --claim {claim} <<'M9_GUEST'\n"
            ).encode("ascii")
            + source
            + b"M9_GUEST\n"
        )
        contents = {
            "phase.sh": script,
            "bindings.json": session.json_bytes(
                {
                    "boot": boot,
                    "claim": claim,
                    "candidate_sha": candidate_sha,
                    "authorization": authorization,
                    "admit_until": admit_until,
                }
            ),
            "SOURCE-PINS.json": session.json_bytes({"guest_sha256": sha(source),
                                                    "closure_sha256": closure_source_sha}),
        }
        manifest = "".join(f"{sha(contents[name])}  {name}\n" for name in sorted(contents)).encode(
            "ascii"
        )
        package.mkdir(mode=0o700)
        for name, raw in {**contents, "MANIFEST.sha256": manifest}.items():
            session.retain(package / name, raw)
        self.operations = session.staging_commands(
            package, sha(manifest), "m9-read-" + sha(manifest)[:24], target, alias
        )
        if not self.operations[3][-1].endswith(_EXEC):
            raise ValueError("M9_READ_TRANSPORT_SHAPE_CHANGED")

    @staticmethod
    def _capture(name, captures, argv, cutoff, run, limit=4096):
        seconds = math.floor(cutoff - time.monotonic())
        if seconds <= 0:
            raise TimeoutError("M9_READ_PHASE_DEADLINE")
        return session.capture(name, captures, argv, seconds, limit, run=run)

    def stage(self, captures: Path, cutoff: float, *, run=None) -> None:
        if self._staged:
            raise ValueError("M9_READ_ALREADY_STAGED")
        for i, argv in enumerate(self.operations[:3]):
            status, out, err = self._capture(f"read-stage-{i}", captures, argv, cutoff, run)
            if status != {"completed": True, "returncode": 0, "timed_out": False} or out or err:
                raise ValueError("M9_READ_STAGE_UNPROVED")
        self._staged = True

    def _action(self, action, captures, cutoff, run):
        if not self._staged:
            raise ValueError("M9_READ_NOT_STAGED")
        argv = self.operations[3]
        tail = argv[-1].removesuffix(_EXEC) + f"&& /bin/bash phase.sh {action} < /dev/null"
        return self._capture(
            f"read-{action}",
            captures,
            [*argv[:-1], tail],
            cutoff,
            run,
            {"readback": 8192, "original": 16384}.get(action, 4096),
        )

    def _receipt(self, action, state, captures, cutoff, run):
        status, raw, err = self._action(action, captures, cutoff, run)
        if (
            status != {"completed": True, "returncode": 0, "timed_out": False}
            or err
            or parsed(raw) != {"state": state, "boot": self.boot, "claim": self.claim}
        ):
            raise ValueError("M9_READ_" + action.upper() + "_UNPROVED")
        return sha(raw)

    def place(self, captures: Path, cutoff: float, *, run=None) -> None:
        if self._placement_issued or self._discard_issued:
            raise ValueError("M9_READ_PLACEMENT_ALREADY_CLAIMED")
        self._placement_issued = True
        self._receipt("place", "placed", captures, cutoff, run)

    def readback(self, captures: Path, cutoff: float, *, run=None) -> bytes:
        status, raw, err = self._action("readback", captures, cutoff, run)
        if (
            status != {"completed": True, "returncode": 0, "timed_out": False}
            or err
            or raw != self.candidate
        ):
            raise ValueError("M9_READ_READBACK_UNPROVED")
        self._readback_checked = True
        return raw

    def discard(self, captures: Path, cutoff: float, *, run=None) -> str:
        if self._discard_issued:
            raise ValueError("M9_READ_DISCARD_ALREADY_CLAIMED")
        self._discard_issued = True
        return self._receipt("discard", "discarded", captures, cutoff, run)

    def dispatch(self, captures: Path, cutoff: float, *, run=None) -> None:
        if self._issued or self._observed:
            raise ValueError("M9_READ_ALREADY_ISSUED_OR_FENCED")
        if not self._readback_checked or self._discard_issued:
            raise ValueError("M9_READ_REQUIRES_CHECKED_PLACEMENT")
        self._issued = True
        # Even zero here is only a response. The independent proof is mandatory.
        status, _, err = self._action("dispatch", captures, cutoff, run)
        if status["timed_out"]:
            raise TimeoutError("M9_READ_DISPATCH_RESPONSE_LOST")
        if status != {"completed": True, "returncode": 0, "timed_out": False} or err:
            raise ValueError("M9_READ_DISPATCH_RESPONSE_UNPROVED")

    def prove(self, captures: Path, cutoff: float, *, run=None) -> TerminalProof | None:
        if self._observed:
            raise ValueError("M9_READ_PROOF_ALREADY_REQUESTED")
        self._observed = True
        status, raw, err = self._action("prove", captures, cutoff, run)
        if status != {"completed": True, "returncode": 0, "timed_out": False} or err:
            return None
        record = parsed(raw)
        for state, disposition in (("joined", "terminal"), ("fenced", "fenced")):
            if record == {"state": state, "boot": self.boot, "claim": self.claim}:
                self._terminal = disposition == "terminal"
                return TerminalProof(self.claim, disposition, sha(raw))
        return None

    def original(self, captures: Path, cutoff: float, *, run=None) -> tuple[bytes, bytes]:
        if not self._terminal or self._discard_issued:
            raise ValueError("M9_READ_REQUIRES_TERMINAL_PROOF")
        status, raw, err = self._action("original", captures, cutoff, run)
        record = parsed(raw)
        if (
            status != {"completed": True, "returncode": 0, "timed_out": False}
            or err
            or type(record) is not dict
            or set(record) != {"boot", "claim", "returncode", "stdout", "stderr"}
            or record["boot"] != self.boot
            or record["claim"] != self.claim
            or type(record["returncode"]) is not int
            or record["returncode"] != 0
            or not all(type(record[name]) is str for name in ("stdout", "stderr"))
        ):
            raise ValueError("M9_READ_ORIGINAL_UNPROVED")
        try:
            out = base64.b64decode(record["stdout"], validate=True)
            error = base64.b64decode(record["stderr"], validate=True)
        except ValueError as exc:
            raise ValueError("M9_READ_ORIGINAL_UNPROVED") from exc
        if max(len(out), len(error)) > 4096:
            raise ValueError("M9_READ_ORIGINAL_UNPROVED")
        return out, error

    def accept(self, captures: Path, cutoff: float, *, run=None) -> str:
        if self._closure is None:
            raise ValueError("M9_READ_CLOSURE_BAD_PINS")
        stdout, stderr = self.original(captures, cutoff, run=run)
        status, raw, err = self._action("projection", captures, cutoff, run)
        if status != {"completed": True, "returncode": 0, "timed_out": False} or err:
            raise ValueError("M9_READ_CLOSURE_UNPROVED")
        return accept_result(self._closure, raw, stdout, stderr, 0)
