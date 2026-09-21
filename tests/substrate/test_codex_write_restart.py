"""N2 WRITE abandonment/reconstruction across the durable checkpoint boundary.

The byte peer is scripted, but the callback worker and contained capture are
the real provisioned Linux boundary.  This test intentionally uses host
abandonment followed by a fresh ``ControlPlane`` rather than claiming a
controller process death.  The literal process-death companion remains the
native recovery lane.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import fields

import pytest

from constructicon.api.control import ControlPlane
from constructicon.core.control import RunSubmission
from constructicon.core.run import RunStatus
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.gateworld import ControlledGate, ControlledGateProvider
from tests.substrate.test_codex_adapter import FINISHED
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_write import write_native, write_provider
from tests.substrate.test_codex_write_capture import (
    PhysicalWorkerLauncher,
    write_graph,
    write_system,
)
from tests.substrate.test_contained_capture import write_provider as capture_provider
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher

LINUX = pytest.mark.skipif(
    sys.platform != "linux",
    reason="actual contained capture requires the provisioned Linux launcher",
)


async def _until(predicate) -> None:
    async with asyncio.timeout(60):
        while not predicate():
            await asyncio.sleep(0.01)


def _worker_launcher(launcher: LinuxLauncher, native):
    return PhysicalWorkerLauncher(
        **{item.name: getattr(launcher, item.name) for item in fields(LinuxLauncher)},
        native=native,
        result=FINISHED,
    )


@pytest.mark.parametrize("phase", ("before_checkpoint", "after_checkpoint"))
@LINUX
async def test_write_abandonment_reconstruction_replays_only_the_uncheckpointed_stage(
    launcher, provider, portable_binding, tmp_path, monkeypatch, phase,
):
    """A fresh host replays callback/capture only when their node lacks a checkpoint.

    The sole hook is a cancellation point either before ``capture`` invokes
    the contained Git path, or at the existing blocking downstream gate after
    the writer's durable checkpoint.  It neither manufactures a failed run
    nor supplies a canned candidate.
    """

    program = "from pathlib import Path; Path('callback.txt').write_text('recovered')"
    journal = SqliteJournal(tmp_path / "restart.sqlite")
    workspace = capture_provider(provider, launcher)
    gate_a = ControlledGateProvider()
    native_a = write_native(program=program)
    worker_a = _worker_launcher(launcher, native_a)
    executor_a = write_provider(
        worker_a, binding=portable_binding[1:3], root=tmp_path / "executor",
    )
    system_a = write_system(journal, workspace, executor_a, gate_a)

    paused = asyncio.Event()
    pause_once = True
    capture_calls: list[str] = []
    original_capture = workspace.capture
    candidates = []
    original_verify = ControlledGate.verify

    async def capture_at_boundary(view, message):
        nonlocal pause_once
        capture_calls.append(message)
        if phase == "before_checkpoint" and pause_once:
            pause_once = False
            paused.set()
            await asyncio.Event().wait()
        return await original_capture(view, message)

    async def record_candidate(self, candidate):
        candidates.append(candidate)
        return await original_verify(self, candidate)

    monkeypatch.setattr(workspace, "capture", capture_at_boundary)
    monkeypatch.setattr(ControlledGate, "verify", record_candidate)

    first = ControlPlane(system=system_a, store=journal)
    second: ControlPlane | None = None
    try:
        await first.startup()
        graph = await write_graph(first)
        submitted = await first.runs_start(
            RUN_ACTOR,
            proposal=graph,
            inputs={"goal": {"message": "write across reconstruction"}},
            idempotency_key=f"write-{phase}",
        )
        assert isinstance(submitted, RunSubmission), submitted
        if phase == "before_checkpoint":
            await _until(paused.is_set)
        else:
            await _until(lambda: bool(gate_a.handles) and gate_a.handles[0].started.is_set())

        writer_lease = next(
            row for row in journal.capability_leases(submitted.run_id)
            if row.binding_id == "workspace"
        )
        checkpoint = journal.checkpoint(submitted.run_id, writer_lease.path)
        assert (checkpoint is not None) is (phase == "after_checkpoint")
        assert journal.run_state(submitted.run_id).status is RunStatus.RUNNING
        assert len(worker_a.worker_calls) == 1
        assert len(native_a.callback_responses) == 1
        assert capture_calls == ["write across reconstruction"]

        # This is the lawful abandonment hook: it cancels only process-local
        # host work, leaves no user cancellation intent, and releases its lease.
        await first.shutdown()
        state = journal.run_state(submitted.run_id)
        assert state.status is RunStatus.RUNNING and not state.cancel_requested

        native_b = write_native(program=program)
        worker_b = _worker_launcher(launcher, native_b)
        executor_b = write_provider(
            worker_b, binding=portable_binding[1:3], root=tmp_path / "executor",
        )
        gate_b = ControlledGateProvider()
        system_b = write_system(journal, workspace, executor_b, gate_b)
        second = ControlPlane(system=system_b, store=journal)
        await second.startup()

        # The controlled downstream gate proves the reconstructed walker has
        # crossed the capture checkpoint.  It does not stand in for capture.
        await _until(lambda: bool(gate_b.handles) and gate_b.handles[0].started.is_set())
        gate_b.handles[0].allowed.set()
        await _until(lambda: journal.run_state(submitted.run_id).status in {
            RunStatus.SUCCEEDED, RunStatus.FAILED,
        })
        assert journal.run_state(submitted.run_id).status is RunStatus.SUCCEEDED, (
            journal.events(submitted.run_id)
        )

        replayed = phase == "before_checkpoint"
        stored = journal.checkpoint(submitted.run_id, writer_lease.path)
        assert stored is not None
        candidate = stored.outputs["candidate"].payload["commit"]
        assert len(worker_b.worker_calls) == (1 if replayed else 0)
        assert len(worker_b.commands) == (1 if replayed else 0)
        assert len(native_b.callback_responses) == (1 if replayed else 0)
        assert len(capture_calls) == (2 if replayed else 1)
        assert [str(item) for item in candidates] == [candidate] * (2 if not replayed else 1)
        assert len(gate_a.handles) == (1 if not replayed else 0)
        assert len(gate_b.handles) == 1  # A fresh downstream gate is permitted.
        assert all(handle.closed for handle in executor_a.handles)
        assert all(handle.closed for handle in executor_b.handles)
        assert not list(workspace.root.glob("payloads/*"))
    finally:
        if second is not None:
            await second.shutdown()
        await first.shutdown()
