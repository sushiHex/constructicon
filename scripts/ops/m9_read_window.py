"""One supervisor for a same-boot M9 Codex READ. No native fallback or resume.

The adapter owns real authentication and checked remote observations. In
particular, receiving bytes from the owner transport is not authentication,
and losing the dispatch response is not evidence that the guest stopped.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, TypeVar

from scripts.ops.claude_read_session import json_bytes, retain

SCHEMA_VERSION = 1
MAX_PIN_WAIT = 15 * 60
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_T = TypeVar("_T")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _utc(value: datetime) -> bool:
    return type(value) is datetime and value.utcoffset() == timedelta(0)


@dataclass(frozen=True)
class WindowLimits:
    """Reviewed outer transport limits, in seconds; each includes local checking."""

    window: float
    qualify: float
    placement: float
    dispatch: float
    proof: float
    close: float
    withdraw: float
    park: float

    def __post_init__(self) -> None:
        if any(
            type(value := getattr(self, field.name)) not in (int, float)
            or not math.isfinite(value)
            or value <= 0
            for field in fields(self)
        ):
            raise ValueError("window limits must be finite and positive")
        if not math.isfinite(sum(getattr(self, field.name) for field in fields(self))):
            raise ValueError("total window limit must be finite")
        if self.window <= self.withdraw + self.park:
            raise ValueError("window must leave time for qualification and cleanup")


@dataclass(frozen=True)
class Qualification:
    # Stable physical identity across retries: target, boot, generation and qualification.
    window_sha256: str
    # Exact checked packet binding install, runtime, provider, task, authority and paths.
    pins: bytes
    candidate: bytes
    candidate_expires_at: datetime
    cutoff: float


@dataclass(frozen=True)
class OwnerDecision:
    """Produced only by the independent owner authentication callback."""

    challenge_sha256: str
    decision_sha256: str
    selected_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class TerminalProof:
    """Checked independent projection of the original attempt or a proved guest fence."""

    challenge_sha256: str
    disposition: Literal["terminal", "fenced"]
    evidence_sha256: str


@dataclass(frozen=True)
class WindowResult:
    record: Path
    reason: str
    dispatch: Literal["not-issued", "unknown", "terminal", "fenced"]
    cleanup: Literal["clean", "unknown"]
    custody_retained: bool


class ReadBoundary(Protocol):
    """Each call must enforce its absolute monotonic deadline, including transport.

    All calls are single shot. Qualification and checking cannot issue READ.
    Cleanup accepts an absent qualification so the adapter can affirmatively
    unwind a partially completed qualification. Each cleanup digest names a
    checked receipt. Park verification is independent of the park request.
    """

    def qualify(self, cutoff: float) -> Qualification: ...
    def park_requested(self, cutoff: float) -> bool: ...
    def await_owner(self, challenge: bytes, cutoff: float) -> bytes | None: ...
    def authenticate_owner(
        self, challenge: bytes, transport: bytes, cutoff: float
    ) -> OwnerDecision | None: ...
    def check_live(self, qualification: Qualification, cutoff: float) -> bool: ...
    def place(self, qualification: Qualification, cutoff: float) -> None: ...
    def readback(self, qualification: Qualification, cutoff: float) -> bytes: ...
    def dispatch(self, qualification: Qualification, cutoff: float) -> None: ...
    def prove_remote(
        self, qualification: Qualification, challenge_sha256: str, cutoff: float
    ) -> TerminalProof | None: ...
    def close(self, qualification: Qualification, cutoff: float) -> str: ...
    def withdraw(self, qualification: Qualification | None, cutoff: float) -> str: ...
    def park(self, cutoff: float) -> None: ...
    def check_park(self, cutoff: float) -> str: ...


class _Stop(Exception):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise _Stop(reason)


def _retain(path: Path, payload: bytes) -> None:
    retain(path, payload)
    if os.name == "posix":
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def run_window(
    work: Path,
    boundary: ReadBoundary,
    limits: WindowLimits,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    utc: Callable[[], datetime] = _now_utc,
) -> WindowResult:
    """Run one window using the stable, private custody directory for this target.

    A caller must affirm protected ancestors (and a restrictive Windows ACL)
    and reuse this directory for that target. A retained
    active marker prevents another run until custody is resolved externally.
    """
    if not work.is_absolute() or not work.is_dir() or work != work.resolve(strict=True):
        raise ValueError("a canonical private custody directory is required")
    if os.name == "posix" and (work.stat().st_uid != os.geteuid() or work.stat().st_mode & 0o077):
        raise ValueError("a private custody directory is required")
    nonce = uuid.uuid4().hex
    active = work / "active"
    _retain(active, nonce.encode("ascii"))
    record = work / nonce
    record.mkdir(mode=0o700)

    def save(name: str, value: object) -> None:
        _retain(record / (name + ".json"), json_bytes(value))

    def call(deadline: float, action: Callable[..., _T], *args: object) -> _T:
        _require(monotonic() < deadline, "deadline")
        value = action(*args, deadline)
        _require(monotonic() < deadline, "deadline")
        return value

    started = monotonic()
    cutoff = started + limits.window
    qualify_cutoff = min(started + limits.qualify, cutoff - limits.withdraw - limits.park)
    cleanup_reserve = limits.close + limits.withdraw + limits.park
    route_reserve = limits.placement + limits.dispatch + limits.proof + cleanup_reserve
    qualified = None
    placed = False
    marker_uncertain = False
    dispatched: Literal["not-issued", "unknown", "terminal", "fenced"] = "not-issued"
    dispatch_transport = "not-called"
    reason = "qualification-unproved"
    try:
        qualified = call(qualify_cutoff, boundary.qualify)
        now = utc()
        _require(
            _digest(qualified.window_sha256)
            and type(qualified.pins) is bytes
            and bool(qualified.pins)
            and type(qualified.candidate) is bytes
            and bool(qualified.candidate)
            and _utc(qualified.candidate_expires_at)
            and _utc(now)
            and type(qualified.cutoff) in (int, float)
            and math.isfinite(qualified.cutoff),
            reason,
        )
        cutoff = min(cutoff, qualified.cutoff)
        pin_cutoff = min(monotonic() + MAX_PIN_WAIT, cutoff - route_reserve)
        _require(now < qualified.candidate_expires_at, "expired")
        _require(monotonic() < pin_cutoff, "budget")
        challenge = json_bytes(
            {
                "schema_version": SCHEMA_VERSION,
                "nonce": nonce,
                "window_sha256": qualified.window_sha256,
                "pins_sha256": _sha(qualified.pins),
                "candidate_sha256": _sha(qualified.candidate),
                "candidate_expires_at": qualified.candidate_expires_at.isoformat(),
                "procedure": "m9-codex-read",
                "model": "gpt-6.1-sol",
                "effort": "low",
                "epochs": 1,
                "native_user_turns": 1,
                "executor_seconds": 120,
                "exposure": "subscription; backend requests unknown; no enforced monetary ceiling",
            }
        )
        challenge_sha = _sha(challenge)
        _retain(record / "challenge.json", challenge)
        reason = "park-check-unproved"
        _require(call(pin_cutoff, boundary.park_requested) is False, "park-requested")
        reason = "owner-selection-unproved"
        transport = call(pin_cutoff, boundary.await_owner, challenge)
        _require(transport is not None, "no-selection")
        decision = call(pin_cutoff, boundary.authenticate_owner, challenge, transport)
        _require(
            type(decision) is OwnerDecision
            and decision.challenge_sha256 == challenge_sha
            and _digest(decision.decision_sha256)
            and _utc(decision.selected_at)
            and _utc(decision.expires_at)
            and now <= decision.selected_at < decision.expires_at,
            "invalid-selection",
        )

        chosen_expiry = min(decision.expires_at, qualified.candidate_expires_at)
        current = utc()
        _require(_utc(current), "expired")
        admission_end = monotonic() + (chosen_expiry - current).total_seconds()

        def check_admission() -> None:
            current = utc()
            _require(
                _utc(current)
                and decision.selected_at <= current < chosen_expiry
                and monotonic() < admission_end,
                "expired",
            )

        reason = "claim-unproved"
        _require(call(pin_cutoff, boundary.check_live, qualified) is True, "live-drift")
        _require(call(pin_cutoff, boundary.park_requested) is False, "park-requested")
        check_admission()
        _require(monotonic() < pin_cutoff, "budget")
        claim = json_bytes(
            {
                "challenge_sha256": challenge_sha,
                "decision_sha256": decision.decision_sha256,
                "expires_at": decision.expires_at.isoformat(),
            }
        )
        marker_uncertain = True
        try:
            _retain(work / ("selection-" + decision.decision_sha256), claim)
            _retain(work / ("claim-" + qualified.window_sha256), claim)
        except FileExistsError as exc:
            marker_uncertain = False
            raise _Stop("replayed-selection") from exc
        save("claim", {"window_sha256": qualified.window_sha256})
        marker_uncertain = False

        reason = "placement-unproved"
        placement_cutoff = min(
            monotonic() + limits.placement,
            cutoff - limits.dispatch - limits.proof - cleanup_reserve,
        )
        _require(call(placement_cutoff, boundary.check_live, qualified) is True, "live-drift")
        _require(call(placement_cutoff, boundary.park_requested) is False, "park-requested")
        check_admission()
        placed = True  # A failed response may follow the effect.
        call(placement_cutoff, boundary.place, qualified)
        readback = call(placement_cutoff, boundary.readback, qualified)
        _require(type(readback) is bytes and readback == qualified.candidate, "readback-mismatch")
        _require(call(placement_cutoff, boundary.park_requested) is False, "park-requested")
        _require(call(placement_cutoff, boundary.check_live, qualified) is True, "live-drift")
        check_admission()
        _require(monotonic() < placement_cutoff, "budget")
        reason = "dispatch-intent-unproved"
        marker_uncertain = True
        _retain(work / ("dispatch-" + qualified.window_sha256), claim)
        marker_uncertain = False
        check_admission()
        _require(monotonic() < placement_cutoff, "budget")
        dispatch_cutoff = min(
            monotonic() + limits.dispatch,
            cutoff - limits.proof - cleanup_reserve,
        )
        _require(monotonic() < dispatch_cutoff, "budget")
        dispatched = "unknown"
        reason = "remote-unproved"
        # Never repeat a call whose response may have been lost.
        dispatch_transport = "raised"
        with suppress(Exception):
            boundary.dispatch(qualified, dispatch_cutoff)
            dispatch_transport = "returned"
        proof_cutoff = min(monotonic() + limits.proof, cutoff - cleanup_reserve)
        proof = call(proof_cutoff, boundary.prove_remote, qualified, challenge_sha)
        _require(
            type(proof) is TerminalProof
            and proof.challenge_sha256 == challenge_sha
            and proof.disposition in ("terminal", "fenced")
            and _digest(proof.evidence_sha256),
            reason,
        )
        save("remote-proof", {"disposition": proof.disposition, "sha256": proof.evidence_sha256})
        dispatched = proof.disposition
        reason = "read-settled"
    except _Stop as exc:
        reason = str(exc) if dispatched == "not-issued" else "remote-unproved"
    except Exception:
        # The stage tells what is missing without retaining transport diagnostics or credentials.
        pass

    def cleanup_receipt(
        name: str, deadline: float, action: Callable[..., str], *args: object
    ) -> bool:
        try:
            receipt = call(deadline, action, *args)
            _require(_digest(receipt), name + "-unproved")
            save(name, {"sha256": receipt})
        except Exception:
            return False
        return True

    cleaned = False
    if dispatched != "unknown":
        closed = not placed or cleanup_receipt(
            "close",
            min(monotonic() + limits.close, cutoff - limits.withdraw - limits.park),
            boundary.close,
            qualified,
        )
        if closed:
            withdrawn = cleanup_receipt(
                "withdraw",
                min(monotonic() + limits.withdraw, cutoff - limits.park),
                boundary.withdraw,
                qualified,
            )
            park_cutoff = min(monotonic() + limits.park, cutoff)
            # Even a lost park response may be proved by the independent observation.
            with suppress(Exception):
                call(park_cutoff, boundary.park)
            parked = cleanup_receipt("park", park_cutoff, boundary.check_park)
            cleaned = withdrawn and parked
    custody_retained = not cleaned or marker_uncertain
    result = WindowResult(
        record,
        reason,
        dispatched,
        "clean" if cleaned else "unknown",
        custody_retained,
    )
    save(
        "result",
        {
            "schema_version": SCHEMA_VERSION,
            "reason": result.reason,
            "dispatch": result.dispatch,
            "dispatch_transport": dispatch_transport,
            "cleanup": result.cleanup,
            "custody_release_eligible": not custody_retained,
            "marker_uncertain": marker_uncertain,
        },
    )
    if not custody_retained:
        active.unlink()
    return result
