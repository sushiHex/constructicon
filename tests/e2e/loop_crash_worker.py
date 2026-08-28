"""Hard-crash worker for M4 frame-stamped loop recovery."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from constructicon.core.address import RunId
from tests.loopworld import INPUTS, build_loop_worker_system, loop_graph

CRASH_EXIT_CODE = 43


def main() -> None:
    journal_db = Path(os.environ["CONSTRUCTICON_JOURNAL_DB"])
    external_db = Path(os.environ["CONSTRUCTICON_EXTERNAL_DB"])
    run_id = RunId(os.environ["CONSTRUCTICON_RUN_ID"])
    system, journal = build_loop_worker_system(
        journal_db,
        external_db,
        owner_id=f"loop-crash-worker-{os.getpid()}",
    )
    completions = 0

    def die_after_second_iteration(name: str) -> None:
        nonlocal completions
        if name != "completion.after_commit":
            return
        completions += 1
        if completions == 2:
            os._exit(CRASH_EXIT_CODE)

    journal.fault_probe = die_after_second_iteration
    result = asyncio.run(system._start_direct(loop_graph(), INPUTS, run_id=run_id))
    print(result.status.value)


if __name__ == "__main__":
    main()
