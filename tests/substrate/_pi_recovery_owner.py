"""Literal-controller-death instrument; only SQLite owns recovery inventory.

The scripted peer, adapter and Linux launch recipe are unchanged. The active
seam pauses the controller after an actual READ result while prompt delivery
has not returned, so the peer cannot yet receive the conversation's half-close.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import fields
from pathlib import Path

from constructicon.core.process import ProcessIO

PHASES = (
    "before_materialization", "during_materialization", "during_active",
    "before_checkpoint", "after_checkpoint",
)
FIXTURE_TEXT = "literal recovery READ é"
EVIDENCE_NAMES = tuple(f"duplex-pi-recovery-{phase}.json" for phase in PHASES)


def process_status(pid: int) -> tuple[str, str] | None:
    """Start time plus kernel state; installation PID is never authority."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[19], fields[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def birth(pid: int) -> str | None:
    observed = process_status(pid)
    return None if observed is None else observed[0]


def descendants(pid: int) -> dict[int, str]:
    observed: dict[int, str] = {}
    pending = [pid]
    while pending:
        parent = pending.pop()
        try:
            children = Path(f"/proc/{parent}/task/{parent}/children").read_text().split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        for raw in children:
            child = int(raw)
            started = birth(child)
            if started is not None:
                observed[child] = started
                pending.append(child)
    return observed


def assert_previous_quiescent(previous: dict) -> dict[str, str]:
    observations = {}
    for pid, started in previous["processes"].items():
        current = process_status(int(pid))
        if current is None:
            observations[str(pid)] = "absent"
        elif current[0] != started:
            observations[str(pid)] = "reused"
        else:
            # A zombie/dead process has exited and cannot execute or retain
            # acquisition FDs. Its /proc entry can await unrelated PID1 reaping.
            assert current[1] in {"Z", "X", "x"}, (
                "fresh Pi dispatch preceded old-process quiescence"
            )
            observations[str(pid)] = current[1]
    return observations


class ObservedIO:
    """Transparent byte instrument; never synthesizes a protocol result."""

    def __init__(self, io: ProcessIO, *, expected: str, dispatch: Callable[[], None],
                 pause: Callable[[], None] | None = None) -> None:
        self.io, self.expected = io, expected
        self.dispatch, self.pause = dispatch, pause
        self.pending = bytearray()
        self.read_result = asyncio.Event()
        self.eof = False

    async def write(self, data: bytes) -> None:
        prompt = json.loads(data)["type"] == "prompt"
        if prompt:
            self.dispatch()
        await self.io.write(data)
        if prompt and self.pause is not None:
            await self.read_result.wait()
            self.pause()
            raise AssertionError("a doomed prompt write unexpectedly resumed")

    async def read(self, maximum: int = 8192) -> bytes:
        chunk = await self.io.read(maximum)
        self.eof = not chunk
        self.pending.extend(chunk)
        assert len(self.pending) <= 1048576
        while b"\n" in self.pending:
            raw, _, rest = self.pending.partition(b"\n")
            self.pending[:] = rest
            item = json.loads(raw)
            if (item.get("type") == "message_end"
                    and item.get("message", {}).get("role") == "toolResult"):
                message = item["message"]
                assert message["toolName"] == "read" and message["isError"] is False
                assert message["content"] == [{"type": "text", "text": self.expected}]
                self.read_result.set()
        return chunk

    async def close_stdin(self) -> None:
        await self.io.close_stdin()


async def main(root: Path, phase: str) -> None:
    from constructicon.api.control import ControlPlane
    from constructicon.core.control import RunSubmission
    from constructicon.core.run import RunStatus
    from constructicon.core.workspace import acquisition_id_for
    from constructicon.substrate.executors import pi_provider
    from constructicon.substrate.executors.linux import LinuxLauncher
    from constructicon.substrate.executors.pi_read import PI_LIMITS
    from constructicon.substrate.git.acquisition import AcquisitionPaths
    from tests.api.test_control_response_loss import RUN_ACTOR
    from tests.pi_leaseworld import assemble, register_pi
    from tests.substrate._gate_owner import installed_launcher

    assert phase in (*PHASES, "recover")
    recovering = phase == "recover"
    previous = json.loads((root / "prior.json").read_text()) if recovering else None
    handles, dispatches, reconciliations = [], [], []
    holder = {}
    read_observed = False

    def report() -> None:
        handle = handles[-1]
        rows = journal.capability_leases(handle.context.run_lease.run_id)
        row = next(item for item in rows if item.binding_id == "executor")
        assert not workspace.closure.is_closed(handle.paths)
        processes = descendants(os.getpid())
        print(json.dumps({
            "phase": phase, "lease": row.model_dump(mode="json"),
            "rows": [item.model_dump(mode="json") for item in rows],
            "processes": processes, "controller": os.getpid(),
            "process_inventory": "all observed descendants, including transient helpers",
            "process_states": {str(pid): process_status(pid) for pid in processes},
            "entered": handle.entered, "ready": handle.ready,
            "executed": handle.executed, "read_observed": read_observed,
            "dispatches": len(dispatches),
            "identity": executor.identity.revision,
        }), flush=True)
        os.kill(os.getpid(), signal.SIGSTOP)  # Never suspend the supervisor's group.
        raise AssertionError("a doomed Pi controller unexpectedly resumed")

    def assert_old_closed() -> dict[str, str]:
        assert previous is not None
        observed = assert_previous_quiescent(previous)
        for item in previous["rows"]:
            area = "executor" if item["binding_id"] == "executor" else "workspace"
            paths = AcquisitionPaths(root / area, acquisition_id_for(
                item["lease_id"], item["acquisition_epoch"],
            ))
            assert workspace.closure.is_closed(paths)
            assert not paths.payload.exists()
        return observed

    class RecoveryLauncher(LinuxLauncher):
        async def exchange(self, command, **kwargs):
            original = kwargs["conversation"]

            def dispatch():
                if recovering:
                    # Affirm immediately before actual prompt delivery; do not
                    # make a premature reconciliation pass by waiting here.
                    holder["before_dispatch"] = assert_old_closed()
                dispatches.append(handles[-1].paths.acquisition_id)

            def active():
                nonlocal read_observed
                read_observed = True
                report()

            async def conversation(io):
                observed = ObservedIO(
                    io, expected=FIXTURE_TEXT, dispatch=dispatch,
                    pause=active if phase == "during_active" else None,
                )
                await original(observed)
                holder["eof"] = observed.eof

            return await super().exchange(command, **{**kwargs, "conversation": conversation})

    base = installed_launcher()
    launcher = RecoveryLauncher(**{
        item.name: PI_LIMITS if item.name == "limits" else getattr(base, item.name)
        for item in fields(LinuxLauncher)
    })
    system, journal, executor, workspace = await assemble(
        root, launcher, owner="pi-successor" if recovering else "pi-original",
    )

    original_acquire = executor.acquire

    async def acquire(context):
        if recovering:
            # No fresh acquisition may overlap old custody.
            holder["before_acquire"] = assert_old_closed()
        result = await original_acquire(context)
        handles.append(result.resource)
        return result

    executor.acquire = acquire
    original_reconcile = executor.reconcile

    async def reconcile(context, stale):
        result = await original_reconcile(context, stale)
        reconciliations.extend(result.reaped)
        return result

    executor.reconcile = reconcile
    record = journal.record_capability_lease

    def record_at_seam(lease, row):
        record(lease, row)
        if phase == "before_materialization" and row.binding_id == "executor":
            report()

    journal.record_capability_lease = record_at_seam
    original_guard = pi_provider.acquisition_guard

    @asynccontextmanager
    async def guard_at_seam(paths):
        async with original_guard(paths) as fd:
            if phase == "during_materialization":
                assert handles and handles[-1].entered and not handles[-1].ready
                report()
            yield fd

    pi_provider.acquisition_guard = guard_at_seam
    original_execute = pi_provider.PiReadHandle.execute

    async def execute_at_seam(handle, *args, **kwargs):
        outcome = await original_execute(handle, *args, **kwargs)
        assert outcome.status == "success", outcome
        assert outcome.output == "Read: " + FIXTURE_TEXT
        if phase == "before_checkpoint":
            report()
        return outcome

    pi_provider.PiReadHandle.execute = execute_at_seam
    complete = journal.record_completion

    def complete_at_seam(*args, **kwargs):
        complete(*args, **kwargs)
        if phase == "after_checkpoint":
            assert journal.checkpoint(handles[-1].context.run_lease.run_id,
                                      handles[-1].context.path) is not None
            report()

    journal.record_completion = complete_at_seam
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        if not recovering:
            graph = await register_pi(control)
            submitted = await control.runs_start(
                RUN_ACTOR, proposal=graph, inputs={"issue": {"title": "scripted Pi recovery"}},
                idempotency_key="start-pi-recovery",
            )
            assert isinstance(submitted, RunSubmission), submitted
            await asyncio.Event().wait()
        else:
            records = journal.run_records(limit=2)
            assert len(records) == 1
            run_id = records[0].run_id
            async with asyncio.timeout(30):
                while journal.run_state(run_id).status not in {
                    RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED,
                }:
                    await asyncio.sleep(0.01)
            assert journal.run_state(run_id).status is RunStatus.SUCCEEDED, journal.events(run_id)
            await control.shutdown()  # Terminal observation alone does not join lease cleanup.
            holder["after_join"] = assert_old_closed()
            print(json.dumps({
                "run_id": str(run_id), "acquired": len(handles), "dispatches": dispatches,
                "reconciled": reconciliations, "eof": holder.get("eof"),
                "identity": executor.identity.revision,
                "workspace_head": str(workspace.authority.read_ref("refs/heads/main")),
                "old_quiescent_before_dispatch": True if dispatches else None,
                "quiescence_observations": holder,
            }), flush=True)
    finally:
        await control.shutdown()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2]))
