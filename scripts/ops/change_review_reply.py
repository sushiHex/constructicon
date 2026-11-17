"""The requester's reply for one finished change-review advice READ; offline, read only.

Run by the window's run owner after the window ends. It writes nothing: the
reply goes to stdout for the run owner to send to the requester privately.
Public records carry its digests and lengths only, never the advice.

The reply is bound to the window's own private records, never to a path or
digest a caller chooses. The record is a direct child of the custody work
directory, named by the window's nonce (``m9_read_window.run_window``). The
captures are found from that record's challenge bytes, the same way the native
boundary placed them (``m9_native_read.py:75-79``). The advice is delivered
only when the read was accepted and the window ended clean:

- ``result.json`` is terminal and clean, its custody is release-eligible and
  its approval is not suspended, and neither the active nor the suspension
  marker still holds this window's nonce;
- ``close.json`` names the same accepted read;
- the retained original and projection reproduce that accepted SHA through
  the closure's own ``_evidence``;
- the original is the entry's own printer output, and its run and instruction
  are the ones the prepared packet derives.

Any other finished window gives ``not-delivered`` with its result record
verbatim. Metering, served model, estimate and charge are copied exactly as
the route recorded them; this module computes none of them.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts.ops.m9_read_closure import _evidence, _wire
from scripts.ops.m9_read_command import ADVICE, SUMMARY_LIMIT

SCHEMA_VERSION = 1
RECORD_LIMIT = 4096
PACKET_LIMIT = 65536
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
# The window result's exact members (m9_read_window.py, ``save("result", ...)``).
_RESULT = {
    "schema_version", "reason", "dispatch", "dispatch_transport", "cleanup",
    "accepted_read_sha256", "custody_release_eligible", "marker_uncertain",
    "approval_sha256", "approval_slot", "approval_suspended",
}
_CHALLENGE = {
    "schema_version", "nonce", "window_sha256", "pins_sha256", "candidate_sha256",
    "candidate_expires_at", "consumer", "procedure", "approval_sha256",
}
_ORIGINAL = {"boot", "claim", "returncode", "stdout", "stderr"}
_PRINTED = {"run_id", "replayed", "instruction_digest", "advice", "result"}
_COMPLETED = {"completed": True, "returncode": 0, "timed_out": False}


class ReplyRefused(ValueError):
    """A closed, named reason; it never carries a path or a payload."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise ReplyRefused(code)


def _object(raw: bytes, code: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(pairs)
        _need(len(result) == len(pairs), code)
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, ValueError) as error:
        raise ReplyRefused(code) from error
    _need(type(value) is dict, code)
    return value


def _exact(value: object, names: set[str]) -> bool:
    return type(value) is dict and set(value) == names


def _packet(packet: bytes, summary: bytes, instruction: bytes) -> tuple[dict, Any]:
    """The prepared packet's change and the values the route derives from it."""
    from constructicon.api import change_review_advice as route

    code = "REPLY_PACKET_MISMATCH"
    record = _object(packet, code)
    _need(
        record.get("schema_version") == 1 and record.get("execution_authorized") is False
        and record.get("summary_sha256") == hashlib.sha256(summary).hexdigest()
        and _exact(record.get("change"), {"before", "after", "path"}), code,
    )
    try:
        bound = route.bound_values(route.ChangeSummaryV1.model_validate_json(summary))
    except ValueError as error:
        raise ReplyRefused(code) from error
    _need(bound.instruction.encode("utf-8") == instruction, code)
    return record, bound


def _disposition(result: dict[str, Any], nonce: str, active: bytes | None,
                 suspension: bytes | None) -> bool:
    """Whether the window ended accepted and clean, with its markers consistent."""
    return (
        result["reason"] == "read-settled" and result["dispatch"] == "terminal"
        and result["cleanup"] == "clean" and result["custody_release_eligible"] is True
        and result["marker_uncertain"] is False and result["approval_suspended"] is False
        and type(result["accepted_read_sha256"]) is str
        and _SHA.match(result["accepted_read_sha256"]) is not None
        and active != nonce.encode("ascii") and suspension != nonce.encode("ascii")
    )


def deliver(
    *, nonce: str, result: bytes, challenge: bytes, packet: bytes, summary: bytes,
    instruction: bytes, active: bytes | None = None, suspension: bytes | None = None,
    close: bytes | None = None, original: bytes | None = None,
    original_status: bytes | None = None, projection: bytes | None = None,
    projection_status: bytes | None = None,
) -> dict[str, Any]:
    """The reply over already-read bytes. Pure: no I/O, no clock."""
    from constructicon.api import change_review_advice as route
    from constructicon.core.control import RunResultPreviewV3

    code = "REPLY_RECORD_UNPROVED"
    window = _object(result, code)
    claim = _object(challenge, code)
    _need(
        _NONCE.match(nonce) is not None and _exact(window, _RESULT)
        and window["schema_version"] == 2 and _exact(claim, _CHALLENGE)
        and claim["schema_version"] == 2 and claim["nonce"] == nonce
        and claim["consumer"] == ADVICE.id and claim["procedure"] == ADVICE.procedure
        and claim["approval_sha256"] == window["approval_sha256"], code,
    )
    change, bound = _packet(packet, summary, instruction)
    reply: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "change": change["change"],
        "summary_sha256": change["summary_sha256"],
        "instruction_digest": str(bound.instruction_digest),
        "window": nonce,
    }
    if not _disposition(window, nonce, active, suspension):
        return {**reply, "status": "not-delivered", "result": window}

    accepted = window["accepted_read_sha256"]
    code = "REPLY_EVIDENCE_MISMATCH"
    _need(close is not None and original is not None and projection is not None
          and original_status is not None and projection_status is not None, code)
    _need(_object(close, code).get("accepted_read_sha256") == accepted
          and _object(original_status, code) == _COMPLETED
          and _object(projection_status, code) == _COMPLETED
          and len(original) <= ADVICE.original_limit
          and len(projection) <= ADVICE.projection_limit, code)
    envelope = _object(original, code)
    _need(_exact(envelope, _ORIGINAL) and envelope["claim"] == hashlib.sha256(challenge).hexdigest()
          and envelope["returncode"] == 0 and type(envelope["stdout"]) is str
          and type(envelope["stderr"]) is str, code)
    try:
        stdout = base64.b64decode(envelope["stdout"], validate=True)
        stderr = base64.b64decode(envelope["stderr"], validate=True)
    except ValueError as error:
        raise ReplyRefused(code) from error
    _need(stderr == b"" and len(stdout) <= ADVICE.log_limit
          and _evidence(projection, stdout, stderr, 0) == accepted, code)

    code = "REPLY_ADVICE_INVALID"
    printed = _object(stdout, code)
    _need(_exact(printed, _PRINTED) and printed["replayed"] is False
          and stdout == _wire(printed), code)
    try:
        advice = route.ModelAdvicePayload.model_validate(printed["advice"])
        run = RunResultPreviewV3.model_validate_json(json.dumps(printed["result"]))
    except ValueError as error:
        raise ReplyRefused(code) from error
    _need(
        printed["run_id"] == bound.run_id and str(run.run_id) == bound.run_id
        and printed["instruction_digest"] == str(bound.instruction_digest)
        and str(advice.instruction_digest) == str(bound.instruction_digest)
        and run.status.value == "succeeded"
        and advice.reply_bytes == len(advice.advice.encode("utf-8")), code,
    )
    return {
        **reply,
        "status": "delivered",
        "run_id": printed["run_id"],
        "accepted_read_sha256": accepted,
        "approval_sha256": window["approval_sha256"],
        "approval_slot": window["approval_slot"],
        "advice": printed["advice"],
        "metering": printed["result"]["metering"],
    }


def _read(path: Path, limit: int, code: str = "REPLY_RECORD_UNPROVED") -> bytes:
    """One regular file, not a link, at most ``limit`` bytes."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        _need(not path.is_symlink(), code)
        fd = os.open(path, flags)
    except OSError as error:
        raise ReplyRefused(code) from error
    with os.fdopen(fd, "rb") as stream:
        _need(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), code)
        raw = stream.read(limit + 1)
    _need(len(raw) <= limit, code)
    return raw


def _optional(path: Path, limit: int, code: str = "REPLY_RECORD_UNPROVED") -> bytes | None:
    return _read(path, limit, code) if os.path.lexists(path) else None


def _private_dir(path: Path, code: str) -> None:
    try:
        mode = os.lstat(path).st_mode
    except OSError as error:
        raise ReplyRefused(code) from error
    _need(stat.S_ISDIR(mode) and (os.name != "posix" or mode & 0o077 == 0), code)


def collect(work: Path, window_record: Path, packet_dir: Path) -> dict[str, Any]:
    """Read one finished window's own records and return its reply."""
    code = "REPLY_RECORD_UNPROVED"
    _need(work.is_absolute() and window_record.is_absolute() and packet_dir.is_absolute()
          and window_record.parent == work and _NONCE.match(window_record.name) is not None,
          code)
    _private_dir(work, code)
    _private_dir(window_record, code)
    challenge = _read(window_record / "challenge.json", RECORD_LIMIT)
    result = _read(window_record / "result.json", RECORD_LIMIT)
    packet = "REPLY_PACKET_MISMATCH"
    _private_dir(packet_dir, packet)
    approval = _object(result, code).get("approval_sha256")
    _need(type(approval) is str and _SHA.match(approval) is not None, code)
    captures = work / ("native-" + hashlib.sha256(challenge).hexdigest()) / "captures"
    evidence = "REPLY_EVIDENCE_MISMATCH"
    present = os.path.lexists(captures)
    if present:
        _private_dir(captures.parent, evidence)
        _private_dir(captures, evidence)

    def capture(name: str, limit: int) -> bytes | None:
        return _optional(captures / name, limit, evidence) if present else None

    return deliver(
        nonce=window_record.name, result=result, challenge=challenge,
        packet=_read(packet_dir / "packet.json", PACKET_LIMIT, packet),
        summary=_read(packet_dir / "summary.json", SUMMARY_LIMIT, packet),
        instruction=_read(packet_dir / "instruction.txt", SUMMARY_LIMIT, packet),
        active=_optional(work / "active", RECORD_LIMIT),
        suspension=_optional(work / ("suspended-" + approval), RECORD_LIMIT),
        close=_optional(window_record / "close.json", RECORD_LIMIT),
        original=capture("read-original.stdout", ADVICE.original_limit),
        original_status=capture("read-original.status.json", RECORD_LIMIT),
        projection=capture("read-projection.stdout", ADVICE.projection_limit),
        projection_status=capture("read-projection.status.json", RECORD_LIMIT),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    options = parser.parse_args(argv)
    try:
        reply = collect(options.work, options.record, options.packet)
    except ReplyRefused as error:
        # The code only: a message could carry a private path.
        print(json.dumps({"status": "refused", "reason": error.code}))
        return 1
    sys.stdout.buffer.write(_wire(reply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
