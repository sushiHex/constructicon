"""Acceptance-lane crash worker for the git authority (M3): dies via
``os._exit`` at a named probe mid-merge; a fresh process must recover the
install from durable git + journal state alone."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from constructicon.core.address import RunId
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.gitworld import GOOD_FIX, build_git_system, build_graph

CRASH_EXIT_CODE = 42
GOAL_INPUT = {"goal": {"title": "add double()", "content": GOOD_FIX}}


def main() -> None:
    world_dir = Path(os.environ["CONSTRUCTICON_GIT_WORLD"])
    probe = os.environ["CONSTRUCTICON_CRASH_PROBE"]
    run_id = RunId(os.environ["CONSTRUCTICON_RUN_ID"])
    journal = SqliteJournal(world_dir / "journal.db")
    system, _ = build_git_system(world_dir, journal, owner_id=f"git-crash-{os.getpid()}")

    def die(name: str) -> None:
        if name == probe:
            os._exit(CRASH_EXIT_CODE)  # real, immediate process death

    journal.fault_probe = die
    result = asyncio.run(system.start(build_graph(), GOAL_INPUT, run_id=run_id))
    print(result.status.value)


if __name__ == "__main__":
    main()
