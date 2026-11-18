"""The requester's reply for one finished change-review advice READ; offline, read only.

Run by the window's run owner after the window ends. It writes nothing: the
reply goes to stdout for the run owner to send to the requester privately.
Public records carry its digests and lengths only, never the advice.

The reply is bound to the window's own private records, never to a path or
digest a caller chooses. The record is a direct child of the custody work
directory, named by the window's nonce (``m9_read_window.run_window``). The
captures are found from that record's challenge bytes, the same way the native
boundary placed them (``m9_native_read.py:75-79``). Every directory read must
pass the custody's own ``private_directory`` check. The prepared packet is
trusted as the run owner's own, and it must be exactly what
``change_review_input.prepare`` writes. The advice is delivered only when the
read was accepted and the window ended clean:

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
the route recorded them; this module computes none of them. Every scalar is
checked by type as well as value, so ``False`` is never a return code ``0``.
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

from scripts.ops.m9_owner_approval import private_directory
from scripts.ops.m9_read_closure import _evidence, _wire
from scripts.ops.m9_read_command import ADVICE, SUMMARY_LIMIT

SCHEMA_VERSION = 1
RECORD_LIMIT = 4096
PACKET_LIMIT = 65536
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_PATH = re.compile(r"[^\x00-\x1f\x7f\\]{1,4096}\Z")
RECORD = "REPLY_RECORD_UNPROVED"
EVIDENCE = "REPLY_EVIDENCE_MISMATCH"
PACKET = "REPLY_PACKET_MISMATCH"
ADVICE_INVALID = "REPLY_ADVICE_INVALID"
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
# change_review_input.prepare's record, and the sources it checks.
_PACKET = {
    "schema_version", "controller", "checked_source_files", "change", "summary_sha256",
    "offline_pins", "offline_pins_are_provisional", "execution_authorized",
}
_SOURCES = {
    "examples/change_review.py", "src/constructicon/api/change_review_advice.py",
    "src/constructicon/core/control.py", "src/constructicon/core/identity.py",
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


def _same(left: object, right: object) -> bool:
    """Equal JSON values of the same types, so ``False`` never equals ``0``."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_same(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(map(_same, left, right))
    return left == right


def _int(value: object) -> bool:
    return type(value) is int


def _hex(pattern: re.Pattern[str], value: object) -> bool:
    return type(value) is str and pattern.match(value) is not None


def _object(raw: bytes, code: str) -> dict[str, Any]:
    """One JSON object: UTF-8, unique keys, finite numbers, bounded depth."""

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(pairs)
        _need(len(result) == len(pairs), code)
        return result

    def finite(_: str) -> None:
        raise ReplyRefused(code)

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=finite)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ReplyRefused(code) from error
    _need(type(value) is dict, code)
    return value


def _exact(value: object, names: set[str]) -> bool:
    return type(value) is dict and set(value) == names


def _packet(packet: bytes, summary: bytes, instruction: bytes) -> tuple[dict, Any]:
    """The prepared packet's change and the values the route derives from it."""
    from constructicon.api import change_review_advice as route
    from constructicon.core.errors import ContractViolation

    record = _object(packet, PACKET)
    change = record.get("change")
    sources = record.get("checked_source_files")
    _need(
        _exact(record, _PACKET) and _same(record["schema_version"], 1)
        and _hex(_OID, record["controller"])
        and _exact(sources, _SOURCES) and all(_hex(_SHA, sources[name]) for name in _SOURCES)
        and _exact(change, {"before", "after", "path"})
        and _hex(_OID, change["before"]) and _hex(_OID, change["after"])
        and _hex(_PATH, change["path"]) and not change["path"].startswith("/")
        and ".." not in change["path"].split("/")
        and _same(record["summary_sha256"], hashlib.sha256(summary).hexdigest())
        and record["offline_pins_are_provisional"] is True
        and record["execution_authorized"] is False, PACKET,
    )
    try:
        bound = route.bound_values(route.ChangeSummaryV2.model_validate_json(summary))
    except (ValueError, RecursionError, ContractViolation) as error:
        # ContractViolation: a closed summary whose instruction exceeds its bound.
        raise ReplyRefused(PACKET) from error
    pins = json.loads(json.dumps(bound.projection()))
    _need(bound.instruction.encode("utf-8") == instruction
          and _same(record["offline_pins"], pins), PACKET)
    return record, bound


def _window(result: bytes, challenge: bytes | None, nonce: str) -> dict[str, Any]:
    """The finished window's result, and its challenge when it reached one.

    A window that ends before check point (b) saves its result but never its
    challenge (``m9_read_window.py:290-306``); that is a finished window too.
    """
    window = _object(result, RECORD)
    _need(
        _hex(_NONCE, nonce) and _exact(window, _RESULT) and _same(window["schema_version"], 2)
        and all(type(window[name]) is str
                for name in ("reason", "dispatch", "dispatch_transport", "cleanup"))
        and all(type(window[name]) is bool for name in (
            "custody_release_eligible", "marker_uncertain", "approval_suspended"))
        and (window["accepted_read_sha256"] is None
             or _hex(_SHA, window["accepted_read_sha256"]))
        # No slot is spent before the claim (m9_read_window.py:261).
        and _hex(_SHA, window["approval_sha256"])
        and (window["approval_slot"] is None or _int(window["approval_slot"])), RECORD,
    )
    if challenge is None:
        return window
    claim = _object(challenge, RECORD)
    _need(
        _exact(claim, _CHALLENGE) and _same(claim["schema_version"], 2)
        and _same(claim["nonce"], nonce) and _same(claim["consumer"], ADVICE.id)
        and _same(claim["procedure"], ADVICE.procedure)
        and _same(claim["approval_sha256"], window["approval_sha256"]), RECORD,
    )
    return window


def _disposition(window: dict[str, Any], nonce: str, active: bytes | None,
                 suspension: bytes | None) -> bool:
    """Whether the window ended accepted and clean, with its markers consistent."""
    mine = nonce.encode("ascii")
    return (
        window["reason"] == "read-settled" and window["dispatch"] == "terminal"
        and window["cleanup"] == "clean" and window["custody_release_eligible"] is True
        and window["marker_uncertain"] is False and window["approval_suspended"] is False
        and window["accepted_read_sha256"] is not None
        and active != mine and suspension != mine
    )


def deliver(
    *, nonce: str, result: bytes, challenge: bytes | None, packet: bytes, summary: bytes,
    instruction: bytes, active: bytes | None = None, suspension: bytes | None = None,
    close: bytes | None = None, original: bytes | None = None,
    original_status: bytes | None = None, projection: bytes | None = None,
    projection_status: bytes | None = None,
) -> dict[str, Any]:
    """The reply over already-read bytes. Pure: no I/O, no clock."""
    from constructicon.api import change_review_advice as route
    from constructicon.core.control import RunResultPreviewV3

    window = _window(result, challenge, nonce)
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
    # An accepted read always passed check point (b), which saved the challenge.
    _need(challenge is not None, RECORD)
    _need(close is not None and original is not None and projection is not None
          and original_status is not None and projection_status is not None, EVIDENCE)
    _need(_same(_object(close, EVIDENCE).get("accepted_read_sha256"), accepted)
          and _same(_object(original_status, EVIDENCE), _COMPLETED)
          and _same(_object(projection_status, EVIDENCE), _COMPLETED)
          and len(original) <= ADVICE.original_limit
          and len(projection) <= ADVICE.projection_limit, EVIDENCE)
    envelope = _object(original, EVIDENCE)
    _need(_exact(envelope, _ORIGINAL)
          and _same(envelope["claim"], hashlib.sha256(challenge).hexdigest())
          and _same(envelope["returncode"], 0) and type(envelope["stdout"]) is str
          and type(envelope["stderr"]) is str, EVIDENCE)
    try:
        stdout = base64.b64decode(envelope["stdout"], validate=True)
        stderr = base64.b64decode(envelope["stderr"], validate=True)
    except ValueError as error:
        raise ReplyRefused(EVIDENCE) from error
    _need(stderr == b"" and len(stdout) <= ADVICE.log_limit
          and _evidence(projection, stdout, stderr, 0) == accepted, EVIDENCE)

    printed = _object(stdout, ADVICE_INVALID)
    _need(_exact(printed, _PRINTED) and printed["replayed"] is False
          and stdout == _wire(printed), ADVICE_INVALID)
    try:
        advice = route.ModelAdvicePayload.model_validate(printed["advice"])
        run = RunResultPreviewV3.model_validate_json(json.dumps(printed["result"]))
    except (ValueError, RecursionError) as error:
        raise ReplyRefused(ADVICE_INVALID) from error
    _need(
        _same(printed["run_id"], str(bound.run_id)) and str(run.run_id) == bound.run_id
        and _same(printed["instruction_digest"], str(bound.instruction_digest))
        and str(advice.instruction_digest) == str(bound.instruction_digest)
        and run.status.value == "succeeded"
        and advice.reply_bytes == len(advice.advice.encode("utf-8")), ADVICE_INVALID,
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


def _private(path: Path, code: str) -> None:
    try:
        private_directory(path)
    except (OSError, ValueError) as error:
        raise ReplyRefused(code) from error


def _read(path: Path, limit: int, code: str) -> bytes:
    """One regular file, not a link, at most ``limit`` bytes."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        _need(not path.is_symlink(), code)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            _need(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), code)
            raw = stream.read(limit + 1)
    except OSError as error:
        raise ReplyRefused(code) from error
    _need(len(raw) <= limit, code)
    return raw


def _optional(path: Path, limit: int, code: str) -> bytes | None:
    return _read(path, limit, code) if os.path.lexists(path) else None


def collect(work: Path, window_record: Path, packet_dir: Path) -> dict[str, Any]:
    """Read one finished window's own records and return its reply."""
    _need(window_record.parent == work and _hex(_NONCE, window_record.name), RECORD)
    _private(work, RECORD)
    _private(window_record, RECORD)
    _private(packet_dir, PACKET)
    # The result first: every finished window saved it, and only a deliverable
    # one is read further, into its challenge's captures.
    result = _read(window_record / "result.json", RECORD_LIMIT, RECORD)
    challenge = _optional(window_record / "challenge.json", RECORD_LIMIT, RECORD)
    window = _window(result, challenge, window_record.name)
    active = _optional(work / "active", RECORD_LIMIT, RECORD)
    suspension = _optional(work / ("suspended-" + window["approval_sha256"]), RECORD_LIMIT,
                           RECORD)
    evidence: dict[str, bytes | None] = {}
    if challenge is not None and _disposition(window, window_record.name, active, suspension):
        native = work / ("native-" + hashlib.sha256(challenge).hexdigest())
        _private(native, EVIDENCE)
        _private(native / "captures", EVIDENCE)
        for key, name, limit in (
            ("original", "read-original.stdout", ADVICE.original_limit),
            ("original_status", "read-original.status.json", RECORD_LIMIT),
            ("projection", "read-projection.stdout", ADVICE.projection_limit),
            ("projection_status", "read-projection.status.json", RECORD_LIMIT),
        ):
            evidence[key] = _optional(native / "captures" / name, limit, EVIDENCE)
        evidence["close"] = _optional(window_record / "close.json", RECORD_LIMIT, RECORD)
    return deliver(
        nonce=window_record.name, result=result, challenge=challenge,
        packet=_read(packet_dir / "packet.json", PACKET_LIMIT, PACKET),
        summary=_read(packet_dir / "summary.json", SUMMARY_LIMIT, PACKET),
        instruction=_read(packet_dir / "instruction.txt", SUMMARY_LIMIT, PACKET),
        active=active, suspension=suspension, **evidence,
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
