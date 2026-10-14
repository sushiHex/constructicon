"""A real process death leaves only durable command and fake physical worlds."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.control import ADMIN_SCOPE, AuthenticatedActor, CapabilityAcquisitionPair
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock

CRASH_EXIT_CODE = 42
RUN = RunId("run-disposal-fixture")


async def run(directory: Path, seam: str) -> None:
    clock = FakeClock()
    if seam == "recover":
        clock.advance(3600)
    journal = SqliteJournal(directory / "journal.db", now_fn=clock.now)
    system = Constructicon(journal=journal)

    async def forbidden_worker(*args, **kwargs):
        with sqlite3.connect(directory / "fake-physical.db") as physical:
            physical.execute("UPDATE physical_resources SET provider_calls = provider_calls + 1")
        raise AssertionError("administrative disposal must not enter workers or physical providers")

    system._run_prepared = forbidden_worker
    host = RunHost(system, journal=journal, now_fn=clock.now)
    with sqlite3.connect(directory / "journal.db") as connection:
        host._deferred.update(
            RunId(row[0]) for row in connection.execute("SELECT run_id FROM runs")
        )

    def die(name: str) -> None:
        if (seam == "after_domain_comparison"
                and name == "runs_dispose_capabilities.after_plan"):
            worker = journal.claim_run(RUN, owner_id="comparison-superseder", ttl_s=30)
            journal.release_run(worker)
        if name == f"runs_dispose_capabilities.{seam}":
            os._exit(CRASH_EXIT_CODE)

    control = ControlPlane(system=system, store=journal, run_host=host,
                           owner_id=f"process-{os.getpid()}", fault_probe=die)
    await host.startup()
    with sqlite3.connect(directory / "fake-physical.db") as physical:
        pairs = tuple(CapabilityAcquisitionPair(lease_id=row[0], acquisition_epoch=row[1])
                      for row in physical.execute("SELECT lease_id, epoch FROM physical_resources"))
    actor = AuthenticatedActor(actor_id="static:process-disposer", auth_method="static",
                               scopes=frozenset({ADMIN_SCOPE}))
    response = await control.runs_dispose_capabilities(
        actor, run_id=RUN, pairs=pairs, reason="private process-restart reason",
        idempotency_key="durable-process-disposal",
    )
    print(response.model_dump_json())
    await control.shutdown()


if __name__ == "__main__":
    asyncio.run(run(Path(sys.argv[1]), sys.argv[2]))
