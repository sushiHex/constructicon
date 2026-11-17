"""One supervisor for a same-boot Codex READ by a reviewed consumer (M9 or
change-review advice). No native fallback or resume.

Each window spends one slot of the owner's standing approval (ADR 0026),
checked before any process and again against the actual pins. No human step
runs inside the window. The adapter checks the permit's scope and expiry, and
losing the dispatch response is not evidence that the guest stopped.
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
from typing import TYPE_CHECKING, Literal, Protocol, TypeVar

from scripts.ops.claude_read_session import json_bytes, retain
from scripts.ops.m9_read_command import CONSUMERS, M9

if TYPE_CHECKING:
    from scripts.ops.m9_owner_approval import StandingApproval

# 2: the challenge restates no card literals and names the standing approval;
# the result names the approval, its spent slot and whether it is suspended.
SCHEMA_VERSION = 2
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
    # The reviewed consumer descriptor's closed id (m9_read_command.CONSUMERS).
    consumer: str = M9.id


@dataclass(frozen=True)
class OwnerDecision:
    """The slot this window spent of the owner's standing approval.

    ``decision_sha256`` is H(approval digest, slot); ``expires_at`` is the
    approval's ``not_after``.
    """

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
class CloseProof:
    cleanup_sha256: str
    accepted_read_sha256: str | None = None


@dataclass(frozen=True)
class WindowResult:
    record: Path
    reason: str
    dispatch: Literal["not-issued", "unknown", "terminal", "fenced"]
    cleanup: Literal["clean", "unknown"]
    custody_retained: bool
    accepted_read_sha256: str | None
    # The standing approval stays suspended unless this window ended accepted and clean.
    approval_suspended: bool = True


class ReadBoundary(Protocol):
    """Each call must enforce its absolute monotonic deadline, including transport.

    All calls are single shot. ``selected_pins`` runs no process. Qualification
    and checking cannot issue READ. Cleanup accepts an absent qualification so
    the adapter can affirmatively unwind a partially completed qualification.
    Each cleanup digest names a checked receipt. Park verification is
    independent of the park request.
    """

    def selected_pins(self) -> dict[str, object]: ...
    def qualify(self, cutoff: float) -> Qualification: ...
    def park_requested(self, cutoff: float) -> bool: ...
    def check_live(self, qualification: Qualification, cutoff: float) -> bool: ...
    def place(
        self, qualification: Qualification, decision: OwnerDecision, cutoff: float
    ) -> None: ...
    def readback(self, qualification: Qualification, cutoff: float) -> bytes: ...
    def dispatch(self, qualification: Qualification, cutoff: float) -> None: ...
    def prove_remote(
        self, qualification: Qualification, challenge_sha256: str, cutoff: float
    ) -> TerminalProof | None: ...
    def close(self, qualification: Qualification, cutoff: float) -> CloseProof: ...
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


def _claim_slot(
    work: Path, approval: StandingApproval, claim_for: Callable[[int, str], bytes],
) -> tuple[int, str, bytes] | None:
    """Spend the lowest unspent slot by exclusive create; never refunded.

    Two claimers cannot take one slot: the loser's create raises and it moves
    on. A crash after the create leaves the slot spent.
    """
    for slot in range(1, approval.max_runs + 1):
        decision = approval.decision(slot)
        claim = claim_for(slot, decision)
        try:
            _retain(work / ("selection-" + decision), claim)
        except FileExistsError:
            continue
        return slot, decision, claim
    return None


def run_window(
    work: Path,
    boundary: ReadBoundary,
    limits: WindowLimits,
    approval: StandingApproval,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    utc: Callable[[], datetime] = _now_utc,
) -> WindowResult:
    """Run one window using the stable, private custody directory for this target.

    A caller must affirm protected ancestors (and a restrictive Windows ACL)
    and reuse this directory for that target. A retained
    active marker prevents another run until custody is resolved externally.
    A refusal at approval check point (a) raises ``ValueError`` with its
    closed ``approval-*`` code before any process, and retains nothing.
    """
    if not work.is_absolute() or not work.is_dir() or work != work.resolve(strict=True):
        raise ValueError("a canonical private custody directory is required")
    if os.name == "posix" and (work.stat().st_uid != os.geteuid() or work.stat().st_mode & 0o077):
        raise ValueError("a private custody directory is required")
    nonce = uuid.uuid4().hex
    active = work / "active"
    _retain(active, nonce.encode("ascii"))
    # Check point (a): the record against what the selection fixes, before
    # any process. Admission writes the suspension marker exclusively; only an
    # accepted and clean end removes it, so a crash leaves the approval suspended.
    try:
        refusal = approval.admit(boundary.selected_pins(), work, utc())
        if refusal is None:
            try:
                _retain(approval.suspension(work), nonce.encode("ascii"))
            except FileExistsError:
                refusal = "approval-suspended"
    except BaseException:
        active.unlink()
        raise
    if refusal is not None:
        active.unlink()
        raise ValueError(refusal)
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
    spent_slot: int | None = None
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
            and math.isfinite(qualified.cutoff)
            and type(qualified.consumer) is str
            and qualified.consumer in CONSUMERS,
            reason,
        )
        consumer = CONSUMERS[qualified.consumer]
        cutoff = min(cutoff, qualified.cutoff)
        # No human waits inside a window: the pins hold only for the route.
        pin_cutoff = cutoff - route_reserve
        _require(now < qualified.candidate_expires_at, "expired")
        _require(monotonic() < pin_cutoff, "budget")
        # Check point (b): exact equality against the actual pins bytes.
        reason = "approval-unproved"
        refusal = approval.confirm(qualified.consumer, qualified.pins, work, now, nonce)
        _require(refusal is None, refusal or reason)
        challenge = json_bytes(
            {
                "schema_version": SCHEMA_VERSION,
                "nonce": nonce,
                "window_sha256": qualified.window_sha256,
                "pins_sha256": _sha(qualified.pins),
                "candidate_sha256": _sha(qualified.candidate),
                "candidate_expires_at": qualified.candidate_expires_at.isoformat(),
                "consumer": consumer.id,
                "procedure": consumer.procedure,
                "approval_sha256": approval.sha256,
            }
        )
        challenge_sha = _sha(challenge)
        _retain(record / "challenge.json", challenge)
        reason = "park-check-unproved"
        _require(call(pin_cutoff, boundary.park_requested) is False, "park-requested")

        selected_at = now
        chosen_expiry = min(approval.not_after, qualified.candidate_expires_at)
        admission_end = monotonic() + (chosen_expiry - selected_at).total_seconds()

        def check_admission() -> None:
            current = utc()
            _require(
                _utc(current)
                and selected_at <= current < chosen_expiry
                and monotonic() < admission_end,
                "expired",
            )

        reason = "claim-unproved"
        _require(call(pin_cutoff, boundary.check_live, qualified) is True, "live-drift")
        _require(call(pin_cutoff, boundary.park_requested) is False, "park-requested")
        check_admission()
        _require(monotonic() < pin_cutoff, "budget")

        def claim_for(slot: int, decision_sha256: str) -> bytes:
            return json_bytes(
                {
                    "approval_kind": "standing",
                    "approval_sha256": approval.sha256,
                    "slot": slot,
                    "challenge_sha256": challenge_sha,
                    "decision_sha256": decision_sha256,
                    "checked_at": selected_at.isoformat(),
                    "expires_at": approval.not_after.isoformat(),
                }
            )

        marker_uncertain = True
        claimed = _claim_slot(work, approval, claim_for)
        if claimed is None:
            marker_uncertain = False
            raise _Stop("approval-exhausted")
        spent_slot, decision_sha, claim = claimed
        try:
            _retain(work / ("claim-" + qualified.window_sha256), claim)
        except FileExistsError as exc:
            marker_uncertain = False
            raise _Stop("replayed-selection") from exc
        save("claim", {"window_sha256": qualified.window_sha256, "slot": spent_slot})
        marker_uncertain = False
        decision = OwnerDecision(challenge_sha, decision_sha, selected_at, approval.not_after)

        reason = "placement-unproved"
        placement_cutoff = min(
            monotonic() + limits.placement,
            cutoff - limits.dispatch - limits.proof - cleanup_reserve,
        )
        _require(call(placement_cutoff, boundary.check_live, qualified) is True, "live-drift")
        _require(call(placement_cutoff, boundary.park_requested) is False, "park-requested")
        check_admission()
        placed = True  # A failed response may follow the effect.
        call(placement_cutoff, boundary.place, qualified, decision)
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
        _require(call(placement_cutoff, boundary.park_requested) is False, "park-requested")
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
    accepted_read = None
    if dispatched != "unknown":
        closed = not placed
        if placed:
            try:
                close = call(
                    min(monotonic() + limits.close, cutoff - limits.withdraw - limits.park),
                    boundary.close,
                    qualified,
                )
                _require(type(close) is CloseProof and _digest(close.cleanup_sha256), "close")
                accepted_read = close.accepted_read_sha256
                _require(
                    accepted_read is None or (dispatched == "terminal" and _digest(accepted_read)),
                    "close",
                )
                save(
                    "close", {"sha256": close.cleanup_sha256, "accepted_read_sha256": accepted_read}
                )
                closed = True
            except Exception:
                accepted_read = None
        if not closed:
            reason = "close-unproved"
        elif not cleanup_receipt(
            "withdraw",
            min(monotonic() + limits.withdraw, cutoff - limits.park),
            boundary.withdraw,
            qualified,
        ):
            # A lost withdrawal response can leave that remote write in flight.
            # Do not race it by parking the guest from this window.
            reason = "withdraw-unproved"
        else:
            park_cutoff = min(monotonic() + limits.park, cutoff)
            # Even a lost park response may be proved by the independent observation.
            with suppress(Exception):
                call(park_cutoff, boundary.park)
            cleaned = cleanup_receipt("park", park_cutoff, boundary.check_park)
            if not cleaned:
                reason = "park-unproved"
    custody_retained = not cleaned or marker_uncertain
    # Suspension persists after any window that is not accepted and clean;
    # a failed removal keeps the approval suspended, never the reverse.
    suspended = True
    if accepted_read is not None and not custody_retained:
        with suppress(OSError):
            approval.suspension(work).unlink()
            suspended = False
    result = WindowResult(
        record,
        reason,
        dispatched,
        "clean" if cleaned else "unknown",
        custody_retained,
        accepted_read,
        suspended,
    )
    save(
        "result",
        {
            "schema_version": SCHEMA_VERSION,
            "reason": result.reason,
            "dispatch": result.dispatch,
            "dispatch_transport": dispatch_transport,
            "cleanup": result.cleanup,
            "accepted_read_sha256": result.accepted_read_sha256,
            "custody_release_eligible": not custody_retained,
            "marker_uncertain": marker_uncertain,
            "approval_sha256": approval.sha256,
            "approval_slot": spent_slot,
            "approval_suspended": suspended,
        },
    )
    if not custody_retained:
        active.unlink()
    return result
