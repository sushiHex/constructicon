"""Connect one verified qualification to the checked M9 READ guest phase.

Use ``prepare-input --help`` for offline successor input preparation. Compile
that input separately, then use ``--preflight`` to check the selected package.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Match the operator phase tools' isolated local entry.
if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts.ops.claude_read_commands import bounded, parsed, sha
from scripts.ops.claude_read_session import json_bytes
from scripts.ops.m9_owner_approval import StandingApproval, private_directory
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
    def __init__(self, host, work: Path, *, run=None):
        self.host, self.work, self.run = host, work, run
        self._qualified = None
        self._read = None
        self._captures = None
        self._placement_requested = False
        self._joined = False

    def selected_pins(self):
        return self.host.selected_pins()

    def qualify(self, cutoff):
        self._qualified = self.host.qualify(cutoff)
        return self._qualified.qualification

    def _current(self, qualification):
        if self._qualified is None or qualification is not self._qualified.qualification:
            raise ValueError("M9_READ_QUALIFICATION_CHANGED")
        return self._qualified

    def park_requested(self, cutoff):
        return os.path.lexists(self.work / "PARK-NOW")

    def check_live(self, qualification, cutoff):
        return self.host.check_live(self._current(qualification), cutoff)

    def place(self, qualification, decision, cutoff):
        bound = self._current(qualification)
        if decision is None or self._read is not None:
            raise ValueError("M9_READ_AUTHORIZATION_NOT_SELECTED")
        # The guest's integer admission deadline rounds down, never up.
        admit_until = math.floor(
            min(
                decision.expires_at.timestamp(),
                qualification.candidate_expires_at.timestamp(),
            )
        )
        claim = decision.challenge_sha256
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


def run_native_read(work, host, approval, limits, *, run=None):
    return run_window(work, NativeReadBoundary(host, work, run=run), limits, approval)


def preflight(work, host, approval, reserve_seconds, *, host_values=None,
              host_values_sha256=None):
    """Check selected local bytes and record validity without claiming a window.

    The constructor already checked the package and literal helper contracts.
    This does not execute a private writer/compiler or verify fresh host facts.
    """
    if type(reserve_seconds) is not int or reserve_seconds <= 0:
        raise ValueError("preflight-reserve-seconds")
    now = datetime.now(UTC)
    try:
        end = now + timedelta(seconds=reserve_seconds)
    except OverflowError:
        raise ValueError("preflight-reserve-seconds") from None
    input_digest = None
    if host_values is not None:
        try:
            raw = bounded(host_values, 65536)
        except (OSError, ValueError):
            raise ValueError("preflight-host-values-unreadable") from None
        if sha(raw) != host_values_sha256:
            raise ValueError("preflight-host-values-digest")
        # Producer: claude_read_session.json_bytes emits sorted JSON plus one
        # LF as bytes. Never repair a text writer's CRLF output before checking.
        try:
            value = parsed(raw)
            canonical = json_bytes(value)
        except (ValueError, RecursionError):
            raise ValueError("preflight-host-values-json") from None
        if (type(value) is not dict or b"\r" in raw or raw != canonical):
            raise ValueError("preflight-host-values-canonical")
        for key in ("previous_boot", "previous_generation"):
            # Compare only these known predecessor facts with the immutable
            # constructor-validated snapshot, not a second host-values schema.
            if key not in value or json_bytes(value[key]) != json_bytes(host._selected[key]):
                raise ValueError("preflight-host-values-" + key)
        input_digest = sha(raw)
    selected = host.selected_pins()
    for when in (now, end):
        if refusal := approval.admit(selected, work, when):
            raise ValueError(refusal)
    return {
        "status": "preflight-checked", "selection_sha256": host._selection_sha,
        "approval_sha256": approval.sha256, "host_values_sha256": input_digest,
        "reserve_seconds": reserve_seconds, "checked_until": end.isoformat(),
        "contract_coverage": host.contract_coverage,
        "qualification_performed": False, "private_writer_or_compiler_executed": False,
        "fresh_host_facts_verified": False,
    }


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments[:1] == ["prepare-input"]:
        from scripts.ops.m9_read_preparation import main as prepare_main

        return prepare_main(arguments[1:])
    from scripts.ops.m9_qualification_boundary import QualificationBoundary

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--approval-sha256", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--preflight", action="store_true",
                        help="check selected local inputs only; no window or host process")
    parser.add_argument("--reserve-seconds", type=int)
    parser.add_argument("--host-values", type=Path)
    parser.add_argument("--host-values-sha256")
    args = parser.parse_args(argv)
    if args.preflight:
        if args.reserve_seconds is None:
            parser.error("--preflight requires --reserve-seconds")
        if (args.host_values is None) != (args.host_values_sha256 is None):
            parser.error("--host-values and --host-values-sha256 must be selected together")
    elif any(value is not None for value in (
        args.reserve_seconds, args.host_values, args.host_values_sha256,
    )):
        parser.error("local preparation options require --preflight")
    if os.name != "nt" and not args.preflight:
        parser.error("the selected Hyper-V host requires Windows")
    try:
        private_directory(args.work)
        approval = StandingApproval.load(args.approval, args.approval_sha256, args.work)
        host = QualificationBoundary(
            args.selection,
            args.selection_sha256,
            args.work / ("qualification-" + args.selection_sha256),
            target=args.target,
            alias=args.alias,
        )
        if args.preflight:
            checked = preflight(
                args.work, host, approval, args.reserve_seconds,
                host_values=args.host_values, host_values_sha256=args.host_values_sha256,
            )
            sys.stdout.buffer.write(json_bytes(checked))
            return 0
        result = run_native_read(args.work, host, approval, LIMITS)
    except (OSError, ValueError) as exc:
        # Only closed local/standing-approval refusals are echoed, never values.
        prefixes = ("approval-", "preflight-") if args.preflight else ("approval-",)
        named = str(exc).startswith(prefixes) and str(exc).isascii() and len(str(exc)) < 64
        parser.exit(2, f"M9 window refused: {str(exc) if named else type(exc).__name__}\n")
    print(json_bytes({**asdict(result), "record": str(result.record)}).decode("utf-8"), end="")
    return 0 if result.accepted_read_sha256 and not result.custody_retained else 1


if __name__ == "__main__":
    raise SystemExit(main())
