"""A fresh process resumes a real hard crash in the middle of an M4 loop."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from constructicon.core.address import RunId
from constructicon.core.envelope import utc_now
from constructicon.core.run import RunStatus
from constructicon.substrate.external.fake import FakeExternalLedger
from tests.e2e.loop_crash_worker import CRASH_EXIT_CODE

REPO_ROOT = Path(__file__).resolve().parents[2]


def spawn_crashing_worker(run_id: str, tmp_path: Path) -> None:
    env = dict(os.environ)
    env.update(
        CONSTRUCTICON_JOURNAL_DB=str(tmp_path / "loop-journal.db"),
        CONSTRUCTICON_EXTERNAL_DB=str(tmp_path / "loop-external.db"),
        CONSTRUCTICON_RUN_ID=run_id,
    )
    process = subprocess.run(
        [sys.executable, "-m", "tests.e2e.loop_crash_worker"],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert process.returncode == CRASH_EXIT_CODE, (
        process.returncode,
        process.stdout,
        process.stderr,
    )


async def test_fresh_process_restores_completed_loop_iterations(
    tmp_path: Path,
) -> None:
    run_id = RunId("run-hard-crash-loop")
    spawn_crashing_worker(run_id, tmp_path)

    from tests.loopworld import build_loop_worker_system

    system, journal = build_loop_worker_system(
        tmp_path / "loop-journal.db",
        tmp_path / "loop-external.db",
        owner_id="loop-recovery-worker",
    )
    journal._now = lambda: utc_now() + timedelta(hours=1)

    result = await system._resume_direct(run_id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs == {"state": {"value": 3}}
    ledger = FakeExternalLedger(tmp_path / "loop-external.db")
    calls = ledger.executor_calls()
    assert len(calls) == 3
    kinds = [event.kind for event in journal.events(run_id, limit=300)]
    assert kinds.count("NodeRestored") == 2
    assert kinds.count("LoopIterationRestored") == 2
    assert kinds.count("LoopIterationCompleted") == 2
