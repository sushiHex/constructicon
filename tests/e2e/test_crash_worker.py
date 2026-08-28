"""The acceptance lane: a real worker process dies via ``os._exit`` at a named
probe; a fresh process reclaims the run from durable state alone (M2 §4).

The fake external world lives in a second SQLite file (``fake-external.db``),
so the parent asserts *exactly which uncheckpointed work replayed* against a
store the dead worker could not have cleaned up.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from constructicon.core.address import RunId
from constructicon.core.envelope import utc_now
from constructicon.core.run import RunStatus
from constructicon.substrate.external.fake import FakeExternalLedger
from tests.e2e.crash_worker import CRASH_EXIT_CODE

REPO_ROOT = Path(__file__).resolve().parents[2]

# (probe, executor_calls_after_recovery, expected_effect_event)
# calls == 2 -> triage's uncheckpointed work replayed; == 1 -> restored.
ACCEPTANCE_MATRIX = [
    ("completion.after_checkpoint_insert", 2, "EffectCommitted"),
    ("completion.after_commit", 1, "EffectCommitted"),
    ("effect.before_receipt_txn", 1, "EffectReconciled"),
    ("effect.after_commit", 1, "EffectDeduplicated"),
]


def spawn_crashing_worker(probe: str, run_id: str, tmp_path: Path) -> None:
    env = dict(os.environ)
    env.update(
        CONSTRUCTICON_JOURNAL_DB=str(tmp_path / "journal.db"),
        CONSTRUCTICON_EXTERNAL_DB=str(tmp_path / "fake-external.db"),
        CONSTRUCTICON_CRASH_PROBE=probe,
        CONSTRUCTICON_RUN_ID=run_id,
    )
    proc = subprocess.run(
        [sys.executable, "-m", "tests.e2e.crash_worker"],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == CRASH_EXIT_CODE, (proc.returncode, proc.stderr)


@pytest.mark.parametrize(("probe", "executor_calls", "effect_event"), ACCEPTANCE_MATRIX)
async def test_a_fresh_process_recovers_from_durable_state_alone(
    tmp_path: Path, probe: str, executor_calls: int, effect_event: str
) -> None:
    run_id = f"run-{probe.replace('.', '-')}"
    spawn_crashing_worker(probe, run_id, tmp_path)

    # the dead worker's lease is real wall-clock; recover on a clock an hour
    # ahead instead of sleeping past the TTL
    from tests.e2e.crash_worker import build_worker_system

    system, journal = build_worker_system(
        tmp_path / "journal.db",
        tmp_path / "fake-external.db",
        owner_id="recovery-worker",
    )
    journal._now = lambda: utc_now() + timedelta(hours=1)

    state = system.run_state(RunId(run_id))
    assert state is not None and state.status is RunStatus.RUNNING
    assert state.liveness == "lost"  # durably RUNNING; the lease looks expired

    result = await system._resume_direct(RunId(run_id))
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["summary"] == {"text": "summary of fix the flaky retry loop"}
    assert result.outputs["announced"] == {"reference": "announce/1"}

    # the independently durable outside world holds the whole truth
    ledger = FakeExternalLedger(tmp_path / "fake-external.db")
    assert ledger.announce_count() == 1  # never a second external transition
    assert len(ledger.executor_calls()) == executor_calls
    kinds = [event.kind for event in journal.events(RunId(run_id), limit=200)]
    assert "RunReclaimed" in kinds
    assert effect_event in kinds
