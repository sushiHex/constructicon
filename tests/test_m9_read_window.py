"""Exercise the whole supervisor through one bounded fake boundary."""

import json
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from scripts.ops import m9_read_window
from scripts.ops.claude_read_commands import sha
from scripts.ops.claude_read_session import json_bytes
from scripts.ops.m9_owner_approval import StandingApproval, issue
from scripts.ops.m9_read_window import (
    CloseProof,
    Qualification,
    TerminalProof,
    WindowLimits,
    run_window,
)

from tests.test_m9_owner_approval import view

WINDOW = "a" * 64
RECEIPT = "c" * 64
ACCEPTED = "d" * 64
LIMITS = WindowLimits(
    window=100, qualify=4, placement=5, dispatch=6, proof=7, close=8, withdraw=9, park=10
)


def standing(work, not_after, max_runs=3):
    """A record loaded from its file in the custody directory, as the CLI loads it."""
    raw = issue(view(), not_after=not_after, max_runs=max_runs)
    path = work / ("standing-approval-" + sha(raw)[:16] + ".json")
    if not path.exists():
        path.write_bytes(raw)
    return StandingApproval.load(path, sha(raw), work)


class Crash(BaseException):
    """A process death: nothing in the window may handle it."""


class Fake:
    def __init__(self, work, fault=None):
        self.work = work
        self.fault = fault
        self.ops = []
        self.tick = 0.0
        self.wall = datetime(2026, 11, 5, tzinfo=UTC)
        self.owner_expiry = self.wall + timedelta(seconds=50)
        self.candidate_expiry = self.wall + timedelta(seconds=60)
        self.qualification_cutoff = 100.0
        self.max_runs = 3
        self.selected = view()
        self.packet = view()
        self.disposition = "terminal"
        self.native_calls = 0

    @property
    def approval(self):
        return standing(self.work, self.owner_expiry, self.max_runs)

    def event(self, name, cutoff):
        assert self.tick < cutoff
        self.ops.append((name, cutoff))

    @property
    def names(self):
        return [name for name, _ in self.ops]

    def selected_pins(self):
        return self.selected

    def qualify(self, cutoff):
        self.event("qualify", cutoff)
        if self.fault == "qualification lost":
            raise TimeoutError
        return Qualification(
            WINDOW,
            json_bytes(self.packet),
            b"exact-bytes",
            self.candidate_expiry,
            self.qualification_cutoff,
            "change-review-advice",
        )

    def park_requested(self, cutoff):
        self.event("park-requested", cutoff)
        return self.fault == "park before claim" or (
            self.fault == "park after claim" and "readback" in self.names
        ) or (
            self.fault == "park during final live check" and self.names.count("check-live") == 3
        )

    def check_live(self, qualification, cutoff):
        self.event("check-live", cutoff)
        return self.fault != "preclaim drift" and (
            self.fault != "live drift" or self.names.count("check-live") < 3
        )

    def place(self, qualification, decision, cutoff):
        self.event("place", cutoff)
        self.decision = decision
        assert decision.decision_sha256 == self.approval.decision(self.expected_slot)
        assert decision.expires_at == self.owner_expiry
        assert (self.work / ("selection-" + decision.decision_sha256)).is_file()
        assert (self.work / ("claim-" + qualification.window_sha256)).is_file()
        assert not (self.work / ("dispatch-" + qualification.window_sha256)).exists()
        if self.fault == "crash after claim":
            raise Crash
        if self.fault == "place lost":
            raise TimeoutError

    expected_slot = 1

    def readback(self, qualification, cutoff):
        self.event("readback", cutoff)
        if self.fault == "owner expired":
            self.wall = self.owner_expiry
        if self.fault == "candidate expired":
            self.wall = self.candidate_expiry
        if self.fault == "placement budget elapsed":
            self.tick = cutoff
        return b"other bytes" if self.fault == "readback drift" else qualification.candidate

    def dispatch(self, qualification, cutoff):
        self.event("dispatch", cutoff)
        assert (self.work / ("dispatch-" + qualification.window_sha256)).is_file()
        self.native_calls += 1
        if self.fault == "response lost":
            raise TimeoutError
        if self.fault == "reentrant":
            second = Fake(self.work)
            with pytest.raises(FileExistsError):
                second.run()
            assert not second.ops

    def prove_remote(self, qualification, challenge_sha256, cutoff):
        self.event("prove-remote", cutoff)
        assert challenge_sha256 == self.decision.challenge_sha256
        if self.fault == "failed join":
            raise TimeoutError
        if self.fault == "no proof":
            return None
        if self.fault == "late proof":
            self.tick = cutoff
        if self.fault == "old proof":
            challenge_sha256 = "e" * 64
        return TerminalProof(challenge_sha256, self.disposition, RECEIPT)

    def close(self, qualification, cutoff):
        self.event("close", cutoff)
        accepted = (
            ACCEPTED if self.disposition == "terminal" and "prove-remote" in self.names
            and self.fault != "not accepted" else None
        )
        return CloseProof("" if self.fault == "close unproved" else RECEIPT, accepted)

    def withdraw(self, qualification, cutoff):
        self.event("withdraw", cutoff)
        assert (qualification is None) == (self.fault == "qualification lost")
        if self.fault == "withdraw lost":
            raise TimeoutError
        return RECEIPT

    def park(self, cutoff):
        self.event("park", cutoff)
        if self.fault == "park response lost":
            raise TimeoutError

    def check_park(self, cutoff):
        self.event("check-park", cutoff)
        return "" if self.fault == "park unproved" else RECEIPT

    def run(self, limits=LIMITS):
        return run_window(
            self.work,
            self,
            limits,
            self.approval,
            monotonic=lambda: self.tick,
            utc=lambda: self.wall,
        )


def suspended(work, fake):
    return fake.approval.suspension(work).exists()


def test_accepts_exact_candidate_and_closes_one_window(tmp_path):
    fake = Fake(tmp_path, "reentrant")
    result = fake.run()
    # No owner step: the standing approval's slot is spent without one.
    assert fake.names == [
        "qualify",
        "park-requested",
        "check-live",
        "park-requested",
        "check-live",
        "park-requested",
        "place",
        "readback",
        "park-requested",
        "check-live",
        "park-requested",
        "dispatch",
        "prove-remote",
        "close",
        "withdraw",
        "park",
        "check-park",
    ]
    assert (result.reason, result.dispatch, result.cleanup) == ("read-settled", "terminal", "clean")
    assert result.accepted_read_sha256 == ACCEPTED and result.approval_suspended is False
    assert fake.native_calls == 1
    assert result.custody_retained is False
    assert not (tmp_path / "active").exists()
    assert not suspended(tmp_path, fake)
    assert (result.record / "remote-proof.json").is_file()
    challenge = json.loads((result.record / "challenge.json").read_bytes())
    assert challenge["schema_version"] == 2
    assert challenge["approval_sha256"] == fake.approval.sha256
    assert "approval_not_after" not in challenge and "exposure" not in challenge
    recorded = json.loads((result.record / "result.json").read_bytes())
    assert (recorded["approval_slot"], recorded["approval_suspended"]) == (1, False)


@pytest.mark.parametrize(("change", "code"), [
    ("m9", "approval-consumer"),
    ("alias", "approval-host_key_alias"),
    ("grants", "approval-grants"),
    ("expired", "approval-expired"),
    ("suspended", "approval-suspended"),
    ("revoked", "approval-revoked"),
    ("exhausted", "approval-exhausted"),
])
def test_check_point_a_refuses_before_any_boundary_call(tmp_path, change, code):
    fake = Fake(tmp_path)
    if change == "m9":
        fake.selected = {**view(), "consumer": "m9", "pins": {}}
    elif change == "alias":
        fake.selected = view(alias="another-host")
    elif change == "grants":
        fake.selected = view(pins={"grants": {"timeout_s": 600}})
    elif change == "expired":
        fake.wall = fake.owner_expiry
    elif change == "suspended":
        fake.approval.suspension(tmp_path).write_bytes(b"an earlier window")
    elif change == "revoked":
        fake.approval.revocation(tmp_path).write_bytes(b"")
    else:
        for slot in range(1, fake.max_runs + 1):
            (tmp_path / ("selection-" + fake.approval.decision(slot))).write_bytes(b"spent")
    assert fake.approval.path.exists()  # the record itself lives in the custody directory
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError, match=f"^{code}$"):
        fake.run()
    assert fake.ops == [] and fake.native_calls == 0
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize(("change", "code"), [
    ("grants", "approval-grants"),
    ("component", "approval-component"),
    ("instruction", "approval-instruction_max_bytes"),
    ("alias", "approval-host_key_alias"),
])
def test_check_point_b_refuses_actual_pins_by_name_and_suspends(tmp_path, change, code):
    fake = Fake(tmp_path)
    if change == "grants":
        fake.packet = view(pins={"grants": {**view()["pins"]["grants"], "effort": "high"}})
    elif change == "component":
        fake.packet = view(pins={"component": "sha256:" + "e" * 64})
    elif change == "instruction":
        text = "x" * 8193
        fake.packet = view(pins={"instruction": text, "instruction_bytes": len(text)})
    else:
        fake.packet = view(alias="another-host")
    result = fake.run()
    assert (result.reason, result.dispatch, result.cleanup) == (code, "not-issued", "clean")
    assert fake.names == ["qualify", "withdraw", "park", "check-park"]
    assert not list(tmp_path.glob("selection-*")) and not list(tmp_path.glob("claim-*"))
    assert not list(result.record.glob("challenge*"))
    assert result.approval_suspended and suspended(tmp_path, fake)
    with pytest.raises(ValueError, match=r"^approval-suspended$"):
        Fake(tmp_path).run()


def _revoke_by_file(approval, how):
    if how == "deleted":
        approval.path.unlink()
    else:  # replaced: a different, still canonical record at the same name
        approval.path.write_bytes(issue(view(), not_after=approval.not_after, max_runs=1))


class _Loaded(Fake):
    """A fake whose window runs one record loaded once, as the CLI loads it.

    The base fixture reloads (and so rewrites) its record per access, which would
    mask a deleted file; this one never rewrites it.
    """

    def __init__(self, work, revoke=None):
        super().__init__(work)
        self.loaded = standing(work, self.owner_expiry, self.max_runs)
        self.revoke = revoke

    @property
    def approval(self):
        return self.loaded

    def qualify(self, cutoff):
        qualified = super().qualify(cutoff)
        if self.revoke is not None:
            _revoke_by_file(self.loaded, self.revoke)
        return qualified


@pytest.mark.parametrize("how", ["deleted", "replaced"])
def test_a_record_removed_after_load_refuses_at_check_point_a(tmp_path, how):
    fake = _Loaded(tmp_path)
    _revoke_by_file(fake.loaded, how)
    with pytest.raises(ValueError, match=r"^approval-revoked$"):
        fake.run()
    assert fake.ops == [] and fake.native_calls == 0
    assert not list(tmp_path.glob("selection-*")) and not (tmp_path / "active").exists()


@pytest.mark.parametrize("how", ["deleted", "replaced"])
def test_a_record_removed_during_qualification_refuses_at_check_point_b(tmp_path, how):
    fake = _Loaded(tmp_path, revoke=how)
    result = fake.run()
    outcome = (result.reason, result.dispatch, result.cleanup)
    assert outcome == ("approval-revoked", "not-issued", "clean")
    # No claim, placement or dispatch; the existing cleanup path runs.
    assert fake.names == ["qualify", "withdraw", "park", "check-park"]
    assert fake.native_calls == 0
    assert not list(tmp_path.glob("selection-*")) and not list(tmp_path.glob("claim-*"))
    assert result.approval_suspended and fake.loaded.suspension(tmp_path).exists()


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("preclaim drift", "live-drift"),
        ("park before claim", "park-requested"),
        ("qualification lost", "qualification-unproved"),
    ],
)
def test_unselected_window_withdraws_without_a_claim(tmp_path, fault, reason):
    fake = Fake(tmp_path, fault)
    result = fake.run()
    assert (result.reason, result.dispatch, result.cleanup) == (reason, "not-issued", "clean")
    assert fake.names[-3:] == ["withdraw", "park", "check-park"]
    assert "place" not in fake.names
    assert fake.native_calls == 0
    assert not list(tmp_path.glob("claim-*")) and not list(tmp_path.glob("selection-*"))
    # Not accepted and clean: the next window refuses until a new record is issued.
    assert result.approval_suspended and suspended(tmp_path, fake)


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("owner expired", "expired"),
        ("candidate expired", "expired"),
        ("placement budget elapsed", "deadline"),
        ("live drift", "live-drift"),
        ("readback drift", "readback-mismatch"),
        ("place lost", "placement-unproved"),
        ("park after claim", "park-requested"),
    ],
)
def test_refusal_after_claim_closes_without_dispatch(tmp_path, fault, reason):
    fake = Fake(tmp_path, fault)
    if fault == "candidate expired":
        fake.owner_expiry += timedelta(minutes=1)
    result = fake.run()
    assert (result.reason, result.dispatch, result.cleanup) == (reason, "not-issued", "clean")
    assert fake.names[-4:] == ["close", "withdraw", "park", "check-park"]
    assert fake.native_calls == 0
    assert (tmp_path / ("claim-" + WINDOW)).is_file()
    assert not (tmp_path / ("dispatch-" + WINDOW)).exists()
    # The slot was spent at the claim and is never refunded.
    assert (tmp_path / ("selection-" + fake.approval.decision(1))).is_file()
    assert fake.approval.free_slot(tmp_path) == 2
    assert result.approval_suspended and suspended(tmp_path, fake)


def test_park_requested_during_final_live_check_prevents_dispatch(tmp_path):
    fake = Fake(tmp_path, "park during final live check")
    result = fake.run()
    assert (result.reason, result.dispatch, result.cleanup) == (
        "park-requested", "not-issued", "clean",
    )
    assert fake.native_calls == 0 and (tmp_path / ("dispatch-" + WINDOW)).is_file()


def test_pins_hold_only_for_the_route_reserve(tmp_path):
    # No pin wait: the first stage after check point (b) is bounded by the
    # window cutoff less the route reserve (45 of LIMITS), however wide.
    first = Fake(tmp_path)
    assert first.run().cleanup == "clean"
    assert first.ops[1] == ("park-requested", 55.0)
    wider = Fake(tmp_path / "wider")
    (tmp_path / "wider").mkdir(mode=0o700)
    wider.qualification_cutoff = 1200
    assert wider.run(replace(LIMITS, window=1200)).cleanup == "clean"
    assert wider.ops[1] == ("park-requested", 1155.0)
    third = Fake(tmp_path / "third")
    (tmp_path / "third").mkdir(mode=0o700)
    third.qualification_cutoff = 45.0
    result = third.run()
    assert result.reason == "budget"
    assert third.names == ["qualify", "withdraw", "park", "check-park"]


def test_replayed_physical_qualification_spends_a_new_slot_and_suspends(tmp_path):
    assert Fake(tmp_path).run().approval_suspended is False
    second = Fake(tmp_path)
    second.expected_slot = 2
    result = second.run()
    assert result.reason == "replayed-selection"
    assert second.native_calls == 0
    assert "place" not in second.names
    # Slot 2 is spent although nothing was placed; slots are never refunded.
    spent = {second.approval.decision(slot) for slot in (1, 2)}
    assert {path.name.removeprefix("selection-") for path in tmp_path.glob("selection-*")} == spent
    assert second.approval.free_slot(tmp_path) == 3
    with pytest.raises(ValueError, match=r"^approval-suspended$"):
        Fake(tmp_path).run()


def test_every_slot_spent_by_accepted_runs_leaves_the_record_exhausted(tmp_path):
    for slot in (1, 2, 3):
        fake = Fake(tmp_path)
        fake.expected_slot = slot
        fake.packet = view(pins={"instruction": f"run {slot}\n", "instruction_bytes": 6})
        result = fake.run()
        assert (result.reason, result.accepted_read_sha256) == ("read-settled", ACCEPTED)
        (tmp_path / ("claim-" + WINDOW)).unlink()  # a fresh physical window each time
        (tmp_path / ("dispatch-" + WINDOW)).unlink()
    with pytest.raises(ValueError, match=r"^approval-exhausted$"):
        Fake(tmp_path).run()


def test_a_settled_but_unaccepted_read_suspends_the_approval(tmp_path):
    fake = Fake(tmp_path, "not accepted")
    result = fake.run()
    assert (result.reason, result.dispatch, result.cleanup) == ("read-settled", "terminal", "clean")
    assert result.accepted_read_sha256 is None and not result.custody_retained
    assert result.approval_suspended and suspended(tmp_path, fake)
    assert json.loads((result.record / "result.json").read_bytes())["approval_suspended"] is True
    with pytest.raises(ValueError, match=r"^approval-suspended$"):
        Fake(tmp_path).run()


def test_a_crash_after_the_claim_spends_the_slot_and_leaves_the_approval_suspended(tmp_path):
    fake = Fake(tmp_path, "crash after claim")
    with pytest.raises(Crash):
        fake.run()
    assert (tmp_path / ("selection-" + fake.approval.decision(1))).is_file()
    assert fake.approval.free_slot(tmp_path) == 2
    assert (tmp_path / "active").is_file() and suspended(tmp_path, fake)
    # Even once custody is resolved externally, the approval stays suspended.
    (tmp_path / "active").unlink()
    with pytest.raises(ValueError, match=r"^approval-suspended$"):
        Fake(tmp_path).run()


@pytest.mark.parametrize("max_runs", [1, 2])
def test_two_concurrent_claimers_cannot_take_one_slot(tmp_path, max_runs):
    approval = standing(tmp_path, datetime(2026, 11, 6, tzinfo=UTC), max_runs)
    barrier = threading.Barrier(2)
    results = []

    def claim_for(slot, decision):
        if slot == 1:
            barrier.wait(timeout=10)  # both reach the exclusive create together
        return json_bytes({"slot": slot, "decision": decision, "by": threading.get_ident()})

    def claimer():
        results.append(m9_read_window._claim_slot(tmp_path, approval, claim_for))

    threads = [threading.Thread(target=claimer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    won = [result for result in results if result is not None]
    assert len(results) == 2 and len(won) == min(max_runs, 2)
    assert len({slot for slot, _, _ in won}) == len(won)
    for slot, decision, claim in won:
        assert decision == approval.decision(slot)
        assert (tmp_path / ("selection-" + decision)).read_bytes() == claim


@pytest.mark.parametrize("disposition", ["terminal", "fenced"])
def test_lost_response_closes_only_with_independent_proof(tmp_path, disposition):
    fake = Fake(tmp_path, "response lost")
    fake.disposition = disposition
    result = fake.run()
    assert (result.dispatch, result.cleanup) == (disposition, "clean")
    retained = json.loads((result.record / "result.json").read_bytes())
    assert retained["dispatch_transport"] == "raised"
    assert fake.native_calls == 1
    assert fake.names[-5:] == ["prove-remote", "close", "withdraw", "park", "check-park"]


@pytest.mark.parametrize("fault", ["failed join", "no proof", "old proof", "late proof"])
def test_unproved_remote_attempt_retains_custody_and_blocks_restart(tmp_path, fault):
    fake = Fake(tmp_path, fault)
    result = fake.run()
    assert result.reason == "remote-unproved"
    assert (result.dispatch, result.cleanup) == ("unknown", "unknown")
    assert fake.names[-1] == "prove-remote"
    assert fake.native_calls == 1
    assert (tmp_path / "active").is_file()
    assert not (result.record / "remote-proof.json").exists()
    with pytest.raises(FileExistsError):
        Fake(tmp_path).run()


@pytest.mark.parametrize(
    ("fault", "tail"),
    [
        ("close unproved", ["close"]),
        ("withdraw lost", ["withdraw"]),
        ("park unproved", ["park", "check-park"]),
    ],
)
def test_cleanup_does_not_infer_clean_custody(tmp_path, fault, tail):
    fake = Fake(tmp_path, fault)
    result = fake.run()
    assert (result.dispatch, result.cleanup) == ("terminal", "unknown")
    assert fake.names[-len(tail) :] == tail
    assert (tmp_path / "active").is_file()
    assert result.approval_suspended and suspended(tmp_path, fake)


def test_independent_off_ok_can_prove_a_lost_park_response(tmp_path):
    fake = Fake(tmp_path, "park response lost")
    assert fake.run().cleanup == "clean"
    assert fake.names[-2:] == ["park", "check-park"]


@pytest.mark.parametrize(
    ("marker", "reason", "placed"),
    [
        ("selection-", "claim-unproved", False),
        ("claim-", "claim-unproved", False),
        ("dispatch-", "dispatch-intent-unproved", True),
    ],
)
def test_uncertain_marker_commit_preserves_custody(tmp_path, monkeypatch, marker, reason, placed):
    actual = m9_read_window.retain

    def lost_commit(path, raw):
        actual(path, raw)
        if path.name.startswith(marker):
            raise OSError("lost local commit response")

    monkeypatch.setattr(m9_read_window, "retain", lost_commit)
    fake = Fake(tmp_path)
    result = fake.run()
    assert result.reason == reason
    assert ("place" in fake.names) == placed
    assert fake.native_calls == 0
    assert result.cleanup == "clean"
    assert result.custody_retained is True
    assert (tmp_path / "active").is_file()
    with pytest.raises(FileExistsError):
        Fake(tmp_path).run()
