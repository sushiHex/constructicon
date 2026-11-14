"""The rehearsal CLI in fresh processes: one attempt, its packet, replay and resume.

Each step is a separate interpreter running ``python -m tests.e2e.maintenance_rehearsal``.
Fakes and limits are those of tests/maintenance_task_world (scripted native
peer, fake operator store, portable launcher); not physical containment.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from tests.e2e.maintenance_rehearsal import AUTHORIZATION_ID, DEATH_EXIT

ROOT = Path(__file__).parents[2]


@pytest.fixture
def home_state():
    # Capture's real POSIX custody refuses world-writable ancestry such as /tmp;
    # a short home path also keeps Windows under its full-tree checkout path limit.
    with tempfile.TemporaryDirectory(prefix="mr-", dir=Path.home()) as temp:
        parent = Path(temp).resolve()
        parent.chmod(0o700)
        yield parent


def rehearse(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tests.e2e.maintenance_rehearsal", *arguments], cwd=ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", timeout=600, check=False,
    )


def attempt(state: Path, *flags: str) -> tuple[int, dict]:
    process = rehearse("run", "--state", str(state), *flags)
    return process.returncode, json.loads(process.stdout.splitlines()[-1]) if (
        process.stdout.strip()) else {"stderr": process.stderr}


def packet(state: Path, out: Path) -> tuple[int, dict, str]:
    process = rehearse("report", "--state", str(state), "--out", str(out))
    assert process.stderr == "", process.stderr
    return process.returncode, json.loads(process.stdout), process.stdout


def files(root: Path) -> dict[str, bytes]:
    """Every byte under the state root: store, attempt, result, authority refs and hooks."""
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).digest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def assert_private_safe(text: str, state: Path) -> None:
    assert len(text.encode()) <= 8192
    for marker in (str(state), state.as_posix(), state.parent.name, Path.home().name,
                   "authority.git", "Traceback"):
        assert marker not in text


def test_contribution_packet_replay_and_unwritten_original(home_state):
    state = home_state / "state"
    code, first = attempt(state, "--change", "--key", "one")
    assert code == 0, first
    assert first["accepted"] is True
    assert first["this_process"] == {"turn_start": 1, "task_workers": 1}
    record = (state / "maintenance-attempt.json").read_bytes()
    before = files(state)
    assert "authority.git/hooks/pre-receive" in before
    code, contribution, text = packet(state, home_state / "packet-1")
    assert code == 0, contribution
    assert files(state) == before, "the report wrote under the original root"
    assert_private_safe(text, state)
    assert contribution["complete"] is True and contribution["run_id"] == first["run_id"]
    assert contribution["status"] == "succeeded"
    assert contribution["outcome"] == "succeeded-with-acceptance-record"
    assert contribution["refusal"] is None
    result = contribution["result"]
    assert result["observation"] == "historical-acceptance-observed"
    assert set(result) == {"observation", "candidate_commit", "input_sha256", "render_sha256"}
    assert contribution["diagnostic"]["command"] == "accepted"
    assert contribution["diagnostic"]["attempt"]["dispatch"] == "completed"
    # The installed diagnostic names only the checks its frozen readers know; the
    # inventory check is "unknown" there until the report schema step.
    assert contribution["diagnostic"]["journal"]["checks"] == [
        {"name": "unknown", "status": "passed"},
        {"name": "plan-manifest-trusted-vectors", "status": "passed"}]
    assert contribution["attestation"]["observation"] == "recorded"
    assert contribution["attestation"]["ok"] is True
    assert contribution["attestation"]["created_by_this_run"] is True
    leases = contribution["leases"]
    assert leases["summary"] == "recorded-closed"
    assert leases["meaning"] == "journal-recorded-states-not-physical-quiescence"
    assert sorted((item["node"], item["binding"]) for item in leases["items"]) == [
        ("checker", "gate"), ("writer", "executor"), ("writer", "workspace")]
    target = contribution["target"]
    assert target["observation"] == "observed-at-base"
    assert target["meaning"] == "current-ref-read-not-proof-of-cleanup"
    metering = contribution["metering"]
    assert metering["projection"] == "run-result-v3-metering"
    assert metering["estimate"] is None and metering["confirmed_charge"] is None
    assert metering["estimate_coverage"] == metering["confirmed_charge_coverage"] == "unknown"
    # Same key, same state, fresh process: replay, no second dispatch.
    code, replay = attempt(state, "--change", "--key", "one")
    assert code == 0 and replay["accepted"] is True and replay["run_id"] == first["run_id"]
    assert replay["this_process"] == {"turn_start": 0, "task_workers": 0}
    assert (state / "maintenance-attempt.json").read_bytes() == record
    code, replayed, _ = packet(state, home_state / "packet-2")
    assert code == 0
    for section in ("result", "leases", "attestation", "metering", "capability_accounting"):
        assert replayed[section] == contribution[section], section
    # Another key in this state is refused before any world is assembled.
    code, refused = attempt(state, "--change", "--key", "two")
    assert code == 1 and refused == {"accepted": False,
                                     "error": "maintenance command refused or incomplete"}


def test_noop_packet_names_the_producer_mapped_refusal(home_state):
    state = home_state / "state"
    code, first = attempt(state, "--noop", "--key", "noop")
    assert code == 2 and first["accepted"] is False
    assert first["this_process"] == {"turn_start": 1, "task_workers": 1}
    before = files(state)
    code, noop, text = packet(state, home_state / "packet")
    assert code == 0, noop
    assert files(state) == before
    assert_private_safe(text, state)
    assert noop["status"] == "failed" and noop["outcome"] == "refused"
    assert noop["refusal"] == {"node": "writer", "cause": "capture-unchanged",
                               "source": "diagnostic-producer-mapped-node-failure"}
    assert noop["diagnostic"]["command"] == "normal-nonacceptance"
    assert noop["result"] == {"observation": "missing"}
    assert noop["attestation"] == {"observation": "missing"}
    assert noop["leases"]["summary"] == "recorded-closed" and len(noop["leases"]["items"]) == 2
    assert noop["target"]["observation"] == "observed-at-base"


def test_process_death_after_writer_checkpoint_resumes_without_second_writer(home_state):
    state = home_state / "state"
    process = rehearse("run", "--state", str(state), "--change", "--key", "one",
                       "--die-after-writer-checkpoint")
    assert process.returncode == DEATH_EXIT, process.stderr
    assert not (state / "application-run.json").exists()
    assert not (state / "maintenance-result.json").exists()
    record = (state / "maintenance-attempt.json").read_bytes()
    assert json.loads(record)["phase"] == "outcome"
    assert json.loads(record)["authorization_id"] == AUTHORIZATION_ID
    code, dead, text = packet(state, home_state / "packet-dead")
    assert code == 0, dead
    assert_private_safe(text, state)
    assert dead["status"] == "running" and dead["outcome"] == "incomplete"
    assert dead["diagnostic"]["command"] == "missing"
    nodes = dead["diagnostic"]["journal"]["nodes"]
    assert nodes["writer"]["checkpoint"] == "validated"
    assert nodes["checker"]["checkpoint"] == "missing"
    # Recorded truthfully: the dead process's leases were never closed.
    assert dead["leases"]["summary"] == "recorded-not-all-closed"
    code, resumed = attempt(state, "--change", "--key", "one")
    assert code == 0 and resumed["accepted"] is True, resumed
    assert resumed["this_process"] == {"turn_start": 0, "task_workers": 0}
    assert (state / "maintenance-attempt.json").read_bytes() == record
    code, final, _ = packet(state, home_state / "packet-final")
    assert code == 0 and final["outcome"] == "succeeded-with-acceptance-record"
    assert final["leases"]["summary"] == "recorded-closed"
    epochs = {(item["node"], item["binding"]): item["acquisition_epoch"]
              for item in final["leases"]["items"]}
    assert epochs[("writer", "executor")] == 1 and len(epochs) == 3
