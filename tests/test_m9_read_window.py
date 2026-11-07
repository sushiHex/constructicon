"""Exercise the whole supervisor through one bounded fake boundary."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from scripts.ops import m9_read_window
from scripts.ops.m9_read_window import (
    CloseProof,
    OwnerDecision,
    Qualification,
    TerminalProof,
    WindowLimits,
    run_window,
)

WINDOW = "a" * 64
DECISION = "b" * 64
RECEIPT = "c" * 64
LIMITS = WindowLimits(
    window=100, qualify=4, placement=5, dispatch=6, proof=7, close=8, withdraw=9, park=10
)


class Fake:
    def __init__(self, work, fault=None):
        self.work = work
        self.fault = fault
        self.ops = []
        self.tick = 0.0
        self.wall = datetime(2026, 11, 5, tzinfo=UTC)
        self.selected = self.wall
        self.owner_expiry = self.wall + timedelta(seconds=50)
        self.candidate_expiry = self.wall + timedelta(seconds=60)
        self.qualification_cutoff = 100.0
        self.decision_sha = DECISION
        self.disposition = "terminal"
        self.native_calls = 0

    def event(self, name, cutoff):
        assert self.tick < cutoff
        self.ops.append((name, cutoff))

    @property
    def names(self):
        return [name for name, _ in self.ops]

    def qualify(self, cutoff):
        self.event("qualify", cutoff)
        if self.fault == "qualification lost":
            raise TimeoutError
        return Qualification(
            WINDOW,
            b"checked-packet",
            b"exact-bytes",
            self.candidate_expiry,
            self.qualification_cutoff,
        )

    def park_requested(self, cutoff):
        self.event("park-requested", cutoff)
        return self.fault == "park before claim" or (
            self.fault == "park after claim" and "readback" in self.names
        ) or (
            self.fault == "park during final live check" and self.names.count("check-live") == 3
        )

    def await_owner(self, challenge, cutoff):
        self.event("await-owner", cutoff)
        self.challenge = challenge
        self.challenge_sha = sha256(challenge).hexdigest()
        if self.fault == "no selection":
            return None
        if self.fault == "pin wait elapsed":
            self.tick = cutoff
        return b"opaque owner evidence"

    def check_owner_decision(self, challenge, transport, cutoff):
        self.event("authenticate", cutoff)
        assert challenge == self.challenge
        assert transport == b"opaque owner evidence"
        if self.fault == "invalid manual decision":
            return None
        return OwnerDecision(
            "d" * 64 if self.fault == "wrong boot" else self.challenge_sha,
            self.decision_sha,
            self.selected - timedelta(seconds=self.fault == "stale selection"),
            self.owner_expiry,
        )

    def check_live(self, qualification, cutoff):
        self.event("check-live", cutoff)
        return self.fault != "preclaim drift" and (
            self.fault != "live drift" or self.names.count("check-live") < 3
        )

    def place(self, qualification, cutoff):
        self.event("place", cutoff)
        assert (self.work / ("selection-" + self.decision_sha)).is_file()
        assert (self.work / ("claim-" + qualification.window_sha256)).is_file()
        assert not (self.work / ("dispatch-" + qualification.window_sha256)).exists()
        if self.fault == "place lost":
            raise TimeoutError

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
        assert challenge_sha256 == self.challenge_sha
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
        return CloseProof("" if self.fault == "close unproved" else RECEIPT)

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
            monotonic=lambda: self.tick,
            utc=lambda: self.wall,
        )


def test_accepts_exact_candidate_and_closes_one_window(tmp_path):
    fake = Fake(tmp_path, "reentrant")
    result = fake.run()
    assert fake.names == [
        "qualify",
        "park-requested",
        "await-owner",
        "authenticate",
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
    assert fake.native_calls == 1
    assert result.custody_retained is False
    assert not (tmp_path / "active").exists()
    assert (result.record / "remote-proof.json").is_file()


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("no selection", "no-selection"),
        ("invalid manual decision", "invalid-selection"),
        ("wrong boot", "invalid-selection"),
        ("stale selection", "invalid-selection"),
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
    assert not list(tmp_path.glob("claim-*"))


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


def test_park_requested_during_final_live_check_prevents_dispatch(tmp_path):
    fake = Fake(tmp_path, "park during final live check")
    result = fake.run()
    assert (result.reason, result.dispatch, result.cleanup) == (
        "park-requested", "not-issued", "clean",
    )
    assert fake.native_calls == 0 and (tmp_path / ("dispatch-" + WINDOW)).is_file()


def test_wait_reserves_every_stage_and_caps_pin_hold(tmp_path):
    first = Fake(tmp_path, "pin wait elapsed")
    assert first.run().reason == "deadline"
    assert first.ops[2] == ("await-owner", 55.0)
    assert "authenticate" not in first.names
    second = Fake(tmp_path, "no selection")
    second.qualification_cutoff = 1200
    assert second.run().cleanup == "clean"
    assert second.ops[2] == ("await-owner", 55.0)
    wider = Fake(tmp_path, "no selection")
    wider.qualification_cutoff = 1200
    assert wider.run(replace(LIMITS, window=1200)).cleanup == "clean"
    assert wider.ops[2] == ("await-owner", 900.0)
    third = Fake(tmp_path)
    third.qualification_cutoff = 45.0
    assert third.run().reason == "budget"
    assert "await-owner" not in third.names


@pytest.mark.parametrize("new_decision", [False, True])
def test_replayed_selection_or_physical_qualification_refuses_placement(tmp_path, new_decision):
    assert Fake(tmp_path).run().cleanup == "clean"
    second = Fake(tmp_path)
    if new_decision:
        second.decision_sha = "e" * 64
    assert second.run().reason == "replayed-selection"
    assert second.native_calls == 0
    assert "place" not in second.names


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


def test_independent_off_ok_can_prove_a_lost_park_response(tmp_path):
    fake = Fake(tmp_path, "park response lost")
    assert fake.run().cleanup == "clean"
    assert fake.names[-2:] == ["park", "check-park"]


@pytest.mark.parametrize(
    ("marker", "reason", "placed"),
    [
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
