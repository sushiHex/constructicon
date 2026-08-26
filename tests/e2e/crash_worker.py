"""The acceptance-lane crash worker (M2 §4).

Run as ``python -m tests.e2e.crash_worker`` with the environment naming the
databases, the run, and the probe. At the named probe the process dies via
``os._exit`` — no exception handlers, no ``finally``, no connection cleanup —
so a fresh process must recover from durable state alone. Exit code 42 marks
the deliberate death; a run that finishes without dying prints its status.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.external.fake import FakeExternalLedger
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import (
    ANNOUNCED,
    BRIEF,
    ISSUE,
    SUMMARY,
    TRIAGE_SCRIPT,
    announce_impl,
    atomic,
    pipeline_graph,
    summarize_impl,
    triage_impl,
)

CRASH_EXIT_CODE = 42
INPUTS = {"issue": {"title": "retry loop is flaky"}}


def build_worker_system(
    journal_db: Path, external_db: Path, *, owner_id: str
) -> tuple[Constructicon, SqliteJournal]:
    ledger = FakeExternalLedger(external_db)
    journal = SqliteJournal(journal_db)
    executor = FakeExecutor(dict(TRIAGE_SCRIPT), ledger=ledger)
    system = Constructicon(
        journal=journal,
        capabilities={"fake-executor": executor},
        catalog={
            "fake-executor": CapabilityDescriptor(
                capability_id="fake-executor",
                kind="executor",
                revision="1",
                executor_profile=executor.profile,
            )
        },
        effects={"announce": FakeAnnounceEffect(ledger=ledger)},
        owner_id=owner_id,
    )
    for definition, impl in (
        atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl),
        atomic("test/announce", (BRIEF,), (ANNOUNCED,), announce_impl),
        atomic("test/summarize", (BRIEF,), (SUMMARY,), summarize_impl),
    ):
        version = system.register(definition, impl)  # write-once: idempotent
        system.promote_initial(component=definition.name, version=version)
    return system, journal


def main() -> None:
    journal_db = Path(os.environ["CONSTRUCTICON_JOURNAL_DB"])
    external_db = Path(os.environ["CONSTRUCTICON_EXTERNAL_DB"])
    probe = os.environ["CONSTRUCTICON_CRASH_PROBE"]
    run_id = RunId(os.environ["CONSTRUCTICON_RUN_ID"])
    system, journal = build_worker_system(
        journal_db, external_db, owner_id=f"crash-worker-{os.getpid()}"
    )

    def die(name: str) -> None:
        if name == probe:
            os._exit(CRASH_EXIT_CODE)  # real, immediate process death

    journal.fault_probe = die
    result = asyncio.run(system.start(pipeline_graph(), INPUTS, run_id=run_id))
    print(result.status.value)


if __name__ == "__main__":
    main()
