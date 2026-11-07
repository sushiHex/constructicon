"""Connect one verified qualification to the checked M9 READ guest phase."""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path

# Match the operator phase tools' isolated local entry.
if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts.ops.claude_read_commands import sha
from scripts.ops.claude_read_session import json_bytes
from scripts.ops.m9_owner_approval import ManualApproval, private_directory
from scripts.ops.m9_read_transport import StagedRead
from scripts.ops.m9_read_window import CloseProof, WindowLimits, run_window

LIMITS = WindowLimits(
    window=75 * 60,
    qualify=50 * 60,
    placement=180,
    dispatch=150,
    proof=60,
    close=180,
    withdraw=320,
    park=240,
)


class NativeReadBoundary:
    def __init__(self, host, owner, work: Path, *, run=None):
        self.host, self.owner, self.work, self.run = host, owner, work, run
        self._qualified = None
        self._decision = None
        self._read = None
        self._captures = None
        self._placement_requested = False
        self._joined = False

    def qualify(self, cutoff):
        self._qualified = self.host.qualify(cutoff)
        return self._qualified.qualification

    def _current(self, qualification):
        if self._qualified is None or qualification is not self._qualified.qualification:
            raise ValueError("M9_READ_QUALIFICATION_CHANGED")
        return self._qualified

    def park_requested(self, cutoff):
        return os.path.lexists(self.work / "PARK-NOW")

    def await_owner(self, challenge, cutoff):
        if self._qualified is None:
            raise ValueError("M9_READ_QUALIFICATION_MISSING")
        return self.owner.await_decision(challenge, self._qualified.qualification.pins, cutoff)

    def check_owner_decision(self, challenge, transport, cutoff):
        self._decision = self.owner.verify(challenge, transport, cutoff)
        return self._decision

    def check_live(self, qualification, cutoff):
        return self.host.check_live(self._current(qualification), cutoff)

    def place(self, qualification, cutoff):
        bound = self._current(qualification)
        if self._decision is None or self._read is not None:
            raise ValueError("M9_READ_AUTHORIZATION_NOT_SELECTED")
        # The guest's integer admission deadline rounds down, never up.
        admit_until = math.floor(
            min(
                self._decision.expires_at.timestamp(),
                qualification.candidate_expires_at.timestamp(),
            )
        )
        claim = self._decision.challenge_sha256
        root = self.work / ("native-" + claim)
        root.mkdir(mode=0o700)
        self._captures = root / "captures"
        self._captures.mkdir(mode=0o700)
        self._read = StagedRead(
            root / "package",
            bound.target,
            bound.alias,
            bound.boot,
            claim,
            qualification.candidate,
            bound.authorization,
            admit_until,
            bound.closure,
        )
        self._read.stage(self._captures, cutoff, run=self.run)
        self._placement_requested = True
        self._read.place(self._captures, cutoff, run=self.run)

    def readback(self, qualification, cutoff):
        self._current(qualification)
        return self._read.readback(self._captures, cutoff, run=self.run)

    def dispatch(self, qualification, cutoff):
        self._current(qualification)
        self._read.dispatch(self._captures, cutoff, run=self.run)

    def prove_remote(self, qualification, challenge_sha256, cutoff):
        self._current(qualification)
        if self._read.claim != challenge_sha256:
            raise ValueError("M9_READ_CLAIM_CHANGED")
        proof = self._read.prove(self._captures, cutoff, run=self.run)
        self._joined = proof is not None and proof.disposition == "terminal"
        return proof

    def close(self, qualification, cutoff):
        self._current(qualification)
        if not self._placement_requested:
            # Package staging never executes a privileged guest action.
            return CloseProof(sha(b"M9 authorization placement not requested\n"))
        accepted = None
        if self._joined:
            # A refused or lost projection cannot strand safely removable authority.
            projection_cutoff = time.monotonic() + (cutoff - time.monotonic()) / 2
            with suppress(OSError, ValueError, TimeoutError):
                accepted = self._read.accept(self._captures, projection_cutoff, run=self.run)
        removed = self._read.discard(self._captures, cutoff, run=self.run)
        return CloseProof(removed, accepted)

    def withdraw(self, qualification, cutoff):
        bound = None if qualification is None else self._current(qualification)
        return self.host.withdraw(bound, cutoff)

    def park(self, cutoff):
        self.host.park(cutoff)

    def check_park(self, cutoff):
        return self.host.check_park(cutoff)


def run_native_read(work, host, owner, limits, *, run=None):
    return run_window(work, NativeReadBoundary(host, owner, work, run=run), limits)


def main(argv: list[str] | None = None) -> int:
    from scripts.ops.m9_qualification_boundary import QualificationBoundary

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--alias", required=True)
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("the selected Hyper-V host requires Windows")
    try:
        private_directory(args.work)
        host = QualificationBoundary(
            args.selection,
            args.selection_sha256,
            args.work / ("qualification-" + args.selection_sha256),
            target=args.target,
            alias=args.alias,
        )
        owner = ManualApproval(args.work)
        result = run_native_read(args.work, host, owner, LIMITS)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"M9 window refused: {type(exc).__name__}\n")
    print(json_bytes({**asdict(result), "record": str(result.record)}).decode("utf-8"), end="")
    return 0 if result.accepted_read_sha256 and not result.custody_retained else 1


if __name__ == "__main__":
    raise SystemExit(main())
