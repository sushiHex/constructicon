"""Host-side calibration of the hand-written stored-reply candidate (CI evidence only).

Base and candidate each run in a separate fresh ``-I`` interpreter. The gate's
authority is the stdlib oracle; this battery only shows that the fixture keeps
the observed behavior, and the control shows the battery can see a change.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from constructicon.core.maintenance import CHANNEL_TARGET_PATH

ROOT = Path(__file__).resolve().parents[3]
BATTERY = ROOT / "tests/channel_reply_battery.py"
FIXTURE = ROOT / "tests/fixtures/channel_stored_reply/in_process_candidate.py.txt"
SCENARIOS = {
    "absent", "no_reply", "valid_detach", "ack_cycle", "answered_ack", "reply_id_input",
    "forged_pointer", "torn", "history_and_bad_request", "proof_and_missing_port",
    "consistent_missing_port", "torn_and_conflicting_ack",
}


def battery(source: Path) -> dict[str, list[dict[str, object]]]:
    result = subprocess.run(
        (sys.executable, "-I", str(BATTERY), str(ROOT / "src"), str(source)),
        cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    report = json.loads(result.stdout)
    assert set(report["report"]) == SCENARIOS
    return report["report"]


@pytest.fixture(scope="module")
def base_report():
    return battery(ROOT / CHANNEL_TARGET_PATH)


def test_fixture_candidate_matches_base_on_every_fault(base_report):
    candidate = battery(FIXTURE)
    for name in sorted(SCENARIOS):
        assert candidate[name] == base_report[name], name


def test_battery_observes_the_faults_it_claims(base_report):
    def single(name, index=0):
        return base_report[name][index]

    assert single("absent")["result"] is None
    assert single("absent", 1)["error"] == "ContractViolation"
    assert single("no_reply")["result"] is None
    detached = base_report["valid_detach"]
    assert detached[0]["result"] == detached[1]["result"] and detached[0]["result"] is not None
    first, replay, conflict = base_report["ack_cycle"]
    assert first["result"] == replay["result"] and first["ack_seq"] == replay["ack_seq"] == 1
    assert conflict["error"] == "ChannelAckConflict"
    assert single("reply_id_input")["error"] == "JournalDamaged"
    assert single("forged_pointer")["error"] == "JournalDamaged"
    torn_read, torn_ack = base_report["torn"]
    assert "without its request acknowledgement" in torn_read["text"]
    # The ack path checks the torn reply before any claim: no acknowledgement lands.
    assert torn_ack["error"] == "JournalDamaged" and torn_ack["ack_seq"] == 0
    assert "history is damaged" in single("history_and_bad_request")["text"]
    assert "contradicts its independent intent proof" in single("proof_and_missing_port")["text"]
    loser = single("torn_and_conflicting_ack")
    assert loser["error"] == "JournalDamaged" and loser["error"] != "ChannelAckConflict"
    # Limit, written down: neither port-damage case reaches the port guard. The
    # proof check, or the message model's own validator, refuses first, so the
    # guard's fault text is proved by the oracle's tree equality, not here.
    assert single("consistent_missing_port")["error"] == "ValidationError"
    assert all("pins no reply port" not in outcome.get("text", "")
               for outcomes in base_report.values() for outcome in outcomes)
    for name, outcomes in base_report.items():
        for index, outcome in enumerate(outcomes):
            # Every retained-index lookup runs under the one nonreentrant lock,
            # entered once per public call (the detach step makes two calls).
            calls = 2 if (name, index) == ("valid_detach", 1) else 1
            assert outcome["lock_held_after"] == 0, name
            assert outcome["lock_entries"] == calls, name
            assert outcome["lookup_depths"], name
            assert all(depth == 1 for depth in outcome["lookup_depths"]), name


def test_battery_distinguishes_a_changed_behavior(base_report, tmp_path):
    """Control: a candidate that skips the torn-reply proof in reply_for is seen."""
    source = FIXTURE.read_bytes().replace(b"\r\n", b"\n")
    old = b"            return _detached_message(self._complete_reply(request, stored))\n"
    assert source.count(old) == 1
    path = tmp_path / "changed.py"
    path.write_bytes(source.replace(old, b"            return _detached_message(stored)\n"))
    observed = battery(path)
    assert observed["torn"] != base_report["torn"]
    assert observed["torn"][0]["result"] is not None
