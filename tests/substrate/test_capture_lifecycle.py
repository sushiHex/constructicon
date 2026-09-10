"""Native capture follows the public run/lease lifecycle, including simulation."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import pytest

from constructicon.api.control import ControlPlane
from constructicon.core.control import RunSubmission
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunStatus
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.git.acquisition import AcquisitionPaths
from constructicon.substrate.git.authority import candidate_ref_for
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.captureworld import capture_system, register_capture
from tests.containedworld import RecordedExecutorProvider
from tests.gitworld import seed_authority
from tests.substrate.test_contained_capture import write_provider
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher

PROGRAM = """
import sys
open('from-recorded.txt', 'w').write(sys.stdin.read())
print('{"type":"result","output":{"proposed":true}}')
"""


async def terminal(journal, run_id):
    async with asyncio.timeout(25):
        while journal.run_state(run_id).status not in (RunStatus.SUCCEEDED, RunStatus.FAILED):
            await asyncio.sleep(0.01)
    state = journal.run_state(run_id)
    assert state.status is RunStatus.SUCCEEDED, (state, journal.events(run_id))


@pytest.mark.parametrize(
    "phase",
    [
        "during_import",
        "before_publication",
        "after_publication",
        "after_checkpoint",
    ],
)
async def test_dead_owner_and_reconciled_late_publisher_cannot_leave_an_old_candidate(
    launcher,
    tmp_path,
    phase,
):
    from tests.substrate._capture_owner import assemble

    seed_authority(tmp_path)
    owner = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.substrate._capture_owner",
        str(tmp_path),
        phase,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        line = await asyncio.wait_for(owner.stdout.readline(), 25)
        assert line, (await owner.stderr.read()).decode()
        event = json.loads(line)
        assert event["phase"] == phase
        row = CapabilityLease.model_validate(event["lease"])
        acquisition = acquisition_id_for(row.lease_id, row.acquisition_epoch)
        old = AcquisitionPaths(tmp_path / "owned", acquisition)
        reference = candidate_ref_for(row.run_id, acquisition)
        if phase != "before_publication":
            owner.kill()
            await owner.wait()
        system, journal, provider = assemble(tmp_path, "successor-capture-owner")
        old_candidate = provider.closure.candidate(reference)
        assert (old_candidate is None) == (phase in {"during_import", "before_publication"})
        async with asyncio.timeout(5):
            while journal.run_state(row.run_id).liveness != "lost":
                await asyncio.sleep(0.01)
        control = ControlPlane(system=system, store=journal)
        await control.startup()
        try:
            if phase == "during_import":
                import fcntl

                async with asyncio.timeout(5):
                    while not provider.closure.is_closed(old):
                        await asyncio.sleep(0.01)
                try:
                    assert list(old.payload.glob("quarantine-*"))
                    with old.guard.open("rb") as guard, pytest.raises(BlockingIOError):
                        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.kill(event["child_pid"], signal.SIGCONT)
            await terminal(journal, row.run_id)
            assert provider.closure.is_closed(old) and not old.payload.exists()
            assert provider.closure.candidate(reference) == (
                old_candidate if phase == "after_checkpoint" else None
            )
            rows = journal.capability_leases(row.run_id)
            assert all(item.state == "closed" for item in rows)
            if phase != "after_checkpoint":
                assert max(item.acquisition_epoch for item in rows) > row.acquisition_epoch
            if phase == "before_publication":
                # The successor has finished, not merely begun, discard. Let the
                # old host attempt its real Git transaction, then kill that host.
                os.kill(owner.pid, signal.SIGCONT)
                observed = json.loads(await asyncio.wait_for(owner.stdout.readline(), 5))
                owner.kill()
                await owner.wait()
                assert observed == {"result": "refused"}
                assert provider.closure.candidate(reference) is None
                assert not old.payload.exists()
        finally:
            await control.shutdown()
    finally:
        if owner.returncode is None:
            owner.kill()
        await owner.wait()


async def test_recorded_proposal_captures_then_counterfactual_discards(
    provider, launcher, tmp_path
):
    provider = write_provider(provider, launcher)
    executor = RecordedExecutorProvider(launcher, provider, PROGRAM)
    await executor.qualify()
    journal = SqliteJournal(tmp_path / "control.sqlite")
    system = capture_system(journal, provider, executor=executor)
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        graph = await register_capture(control, executor=True)
        submission = await control.runs_start(
            RUN_ACTOR,
            proposal=graph,
            inputs={"goal": {"message": "isolated proposal"}},
            idempotency_key="start",
        )
        assert isinstance(submission, RunSubmission), submission
        await terminal(journal, submission.run_id)
        source_rows = journal.capability_leases(submission.run_id)
        assert len(source_rows) == 2 and all(row.state == "closed" for row in source_rows)
        workspace = next(row for row in source_rows if row.binding_id == "workspace")
        oid = (
            journal.checkpoint(submission.run_id, workspace.path)
            .outputs["candidate"]
            .payload["commit"]
        )
        source_ref = candidate_ref_for(
            workspace.run_id,
            acquisition_id_for(workspace.lease_id, workspace.acquisition_epoch),
        )
        assert provider.closure.candidate(source_ref) == oid
        assert (
            provider.authority._run("show", f"{oid}:from-recorded.txt").stdout
            == "isolated proposal"
        )
        assert all(handle.closed and handle.active is None for handle in executor.handles)
        simulated = await control.runs_counterfactual(
            RUN_ACTOR,
            source_run_id=submission.run_id,
            overrides={},
            idempotency_key="simulate",
        )
        assert isinstance(simulated, RunSubmission), simulated
        await terminal(journal, simulated.run_id)
        rows = journal.capability_leases(simulated.run_id)
        assert len(rows) == 2 and all(row.state == "closed" for row in rows)
        for row in rows:
            acquisition = acquisition_id_for(row.lease_id, row.acquisition_epoch)
            assert provider.closure.is_closed(AcquisitionPaths(provider.root, acquisition))
            assert not (provider.root / "payloads" / acquisition).exists()
            assert provider.closure.candidate(candidate_ref_for(row.run_id, acquisition)) is None
        assert provider.closure.candidate(source_ref) == oid  # Simulation never discards source.
        assert provider.authority.resolve_ref("refs/heads/main") != oid
        assert not list(Path(provider.root, "payloads").iterdir())
    finally:
        await control.shutdown()
