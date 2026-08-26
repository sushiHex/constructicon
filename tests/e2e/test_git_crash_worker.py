"""The M3 acceptance lane: a real worker process dies via ``os._exit`` after
the git install transaction but before the SQLite receipt; a fresh process
recovers from the marker ref — exactly one install ever."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from constructicon.core.address import RunId
from constructicon.core.envelope import utc_now
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.e2e.git_crash_worker import CRASH_EXIT_CODE
from tests.gitworld import build_git_system, seed_authority

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_a_fresh_process_recovers_the_install_from_the_marker(
    tmp_path: Path,
) -> None:
    seed_authority(tmp_path)
    run_id = "run-git-crash"
    env = dict(os.environ)
    env.update(
        CONSTRUCTICON_GIT_WORLD=str(tmp_path),
        CONSTRUCTICON_CRASH_PROBE="effect.before_receipt_txn",
        CONSTRUCTICON_RUN_ID=run_id,
    )
    proc = subprocess.run(
        [sys.executable, "-m", "tests.e2e.git_crash_worker"],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == CRASH_EXIT_CODE, (proc.returncode, proc.stderr)

    # recover on a clock an hour ahead instead of sleeping past the TTL
    journal = SqliteJournal(tmp_path / "journal.db")
    journal._now = lambda: utc_now() + timedelta(hours=1)
    system, world = build_git_system(tmp_path, journal, owner_id="recovery-worker")
    authority = world.authority

    state = system.run_state(RunId(run_id))
    assert state is not None and state.status is RunStatus.RUNNING
    assert state.liveness == "lost"

    result = await system.resume(RunId(run_id))
    assert result.status is RunStatus.SUCCEEDED
    merged = result.outputs["merged"]
    assert merged["status"] == "committed"

    installed = authority.resolve_ref("refs/heads/main")
    assert str(installed) == merged["observed"]["merge_commit"]
    # exactly one install ever: the seed commit is the direct first parent
    parents = authority.parents_of(installed)
    assert len(parents) == 2 and authority.parents_of(parents[0]) == ()
    kinds = [event.kind for event in journal.events(RunId(run_id), limit=200)]
    assert "RunReclaimed" in kinds and "EffectReconciled" in kinds
