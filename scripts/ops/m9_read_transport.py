"""Compose the fixed M9 guest claim with the existing checked phase transport."""

from __future__ import annotations

import math
import time
from pathlib import Path

from scripts.ops import claude_read_session as session
from scripts.ops.claude_read_commands import parsed, sha
from scripts.ops.m9_read_command import BOOT, SHA, read_argv
from scripts.ops.m9_read_window import TerminalProof

_GUEST = Path(__file__).with_name("m9_read_command.py")
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
        candidate_sha: str,
        authorization: str,
        admit_until: int,
    ) -> None:
        session._target(target, alias)
        if BOOT.fullmatch(boot) is None or SHA.fullmatch(claim) is None:
            raise ValueError("M9_READ_BAD_BOOT_OR_CLAIM")
        read_argv(candidate_sha, authorization, admit_until)
        self.boot, self.claim = boot, claim
        self._staged = False
        self._issued = False
        self._observed = False
        source = _GUEST.read_bytes().replace(b"\r\n", b"\n")
        if b"\r" in source or b"\nM9_GUEST\n" in source or not source.endswith(b"\n"):
            raise ValueError("M9_READ_GUEST_SOURCE_BOUND")
        # Only these two exact actions exist on the selected package. The
        # authorization leaf and candidate are data, not executable input.
        script = (
            (
                "#!/bin/bash\n"
                'test "$#" = 1 || exit 2\n'
                'case "$1" in\n'
                f" dispatch) set -- dispatch --candidate-sha {candidate_sha}"
                f" --authorization {authorization} --admit-until {admit_until};;\n"
                " prove) set -- prove;;\n"
                " *) exit 2;;\n"
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
            "SOURCE-PINS.json": session.json_bytes({"guest_sha256": sha(source)}),
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
    def _capture(name, captures, argv, cutoff, run):
        seconds = math.floor(cutoff - time.monotonic())
        if seconds <= 0:
            raise TimeoutError("M9_READ_PHASE_DEADLINE")
        return session.capture(name, captures, argv, seconds, 4096, run=run)

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
        return self._capture(f"read-{action}", captures, [*argv[:-1], tail], cutoff, run)

    def dispatch(self, captures: Path, cutoff: float, *, run=None) -> None:
        if self._issued or self._observed:
            raise ValueError("M9_READ_ALREADY_ISSUED_OR_FENCED")
        self._issued = True
        # Even zero here is only a response. The independent proof is mandatory.
        self._action("dispatch", captures, cutoff, run)

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
                return TerminalProof(self.claim, disposition, sha(raw))
        return None
