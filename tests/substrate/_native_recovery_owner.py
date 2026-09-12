"""Two real interpreters; only SQLite gives the successor its recovery inventory."""

import asyncio
import hashlib
import json
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.core.control import RunSubmission
from constructicon.core.run import RunStatus
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.native_lifecycle import WORKER, assemble, register_native
from tests.substrate.test_provider_placement import descendants


def physical_snapshot():
    processes = descendants(os.getpid())
    native_homes, session_children = [], []
    for pid in processes:
        with suppress(FileNotFoundError, ProcessLookupError):
            args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            if b"app-server" in args and args[0] == b"codex":
                config = Path(f"/proc/{pid}/root/tmp/home/.codex/config.toml")
                native_homes.append({"pid": pid, "config_sha256": hashlib.sha256(
                    config.read_bytes(),
                ).hexdigest()})
            if WORKER.encode() in args and os.getsid(pid) == pid:
                session_children.append(pid)
    return {"processes": processes, "native_homes": native_homes,
            "session_children": session_children}


async def main(root, model, phase):
    successor = phase == "recover"
    system, journal, provider = assemble(root, model, "successor" if successor else "original")

    def pause(selected, handle):
        rows = journal.capability_leases(handle.context.run_lease.run_id)
        row = next(row for row in rows if row.binding_id == "native")
        evidence = {"phase": selected, "run_id": str(row.run_id),
                    "lease": row.model_dump(mode="json"), **physical_snapshot()}
        if hasattr(handle, "observation"):
            evidence["observed_before_death"] = handle.observation
        print(json.dumps(evidence), flush=True)
        os.kill(os.getpid(), signal.SIGSTOP)
        raise AssertionError("doomed controller unexpectedly resumed")

    async def at(selected, handle):
        if selected == phase:
            pause(selected, handle)

    provider.hook = at
    if phase == "before_materialization":
        original = journal.record_capability_lease

        def record(lease, row):
            original(lease, row)
            if row.binding_id == "native":
                pause(phase, provider.handles[-1])

        journal.record_capability_lease = record
    if phase == "after_checkpoint":
        original_complete = journal.record_completion

        def complete(*args):
            original_complete(*args)
            pause(phase, provider.handles[-1])

        journal.record_completion = complete
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        if successor:
            # RunHost already owns recovery. No supplied lease rows, manual
            # reconciliation, synthetic resume, or native session id participates.
            runs = journal.run_records(limit=2)
            assert len(runs) == 1
            run_id = runs[0].run_id
            async with asyncio.timeout(30):
                terminal = (RunStatus.SUCCEEDED, RunStatus.FAILED)
                while journal.run_state(run_id).status not in terminal:
                    await asyncio.sleep(0.01)
            state = journal.run_state(run_id)
            assert state.status is RunStatus.SUCCEEDED, journal.events(run_id)
            print(json.dumps({"run_id": str(run_id), "completed": provider.completed,
                              "observations": [handle.observation for handle in provider.handles
                                               if hasattr(handle, "observation")],
                              "acquired": len(provider.handles)}),
                  flush=True)
        else:
            graph = await register_native(control)
            submitted = await control.runs_start(
                RUN_ACTOR, proposal=graph, inputs={"goal": {"message": "native fixture"}},
                idempotency_key="start-native-lifecycle",
            )
            assert isinstance(submitted, RunSubmission), submitted
            await asyncio.Event().wait()
    finally:
        await control.shutdown()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
