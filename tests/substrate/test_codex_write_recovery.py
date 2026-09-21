"""Literal Linux controller death while a real N2 WRITE worker is active."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path

import pytest

from constructicon.core.address import GitSha
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunStatus
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.git.acquisition import AcquisitionClosure, AcquisitionPaths
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.gitworld import seed_authority
from tests.runtime.test_async_workspace import until
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence
from tests.substrate.test_operator_store_containment import binding as binding
from tests.substrate.test_provider_placement import birth


async def _owner(root: Path, phase: str):
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.substrate._codex_write_recovery_owner",
        str(root),
        phase,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,
    )


async def _kill(process) -> None:
    if process.returncode is None:
        process.kill()
    await asyncio.wait_for(process.communicate(), 5)


@pytest.mark.skipif(sys.platform != "linux", reason="literal worker owner death requires Linux")
async def test_controller_death_retains_the_worker_guard_until_successor_recovery(
    launcher, binding, tmp_path,
):
    """A scripted native does not weaken the real callback worker's custody proof."""

    import fcntl

    del launcher, binding  # Fixture admission: both provisioned boundaries are required.
    seed_authority(tmp_path)
    original = await _owner(tmp_path, "original")
    successor = None
    supervisor = None
    supervisor_started = None
    try:
        assert original.stdout is not None and original.stderr is not None
        raw = await asyncio.wait_for(original.stdout.readline(), 35)
        assert raw, (await original.stderr.read()).decode()
        observed = json.loads(raw)
        row = CapabilityLease.model_validate(observed["workspace_lease"])
        supervisor = observed["supervisor"]
        resident = {int(pid): started for pid, started in observed["resident"].items()}
        supervisor_started = resident[supervisor]
        assert observed["worker_active"] and observed["launch_checked"]
        assert observed["worker_calls"] == 1 and observed["callback_responses"] == 0

        journal = SqliteJournal(tmp_path / "control.sqlite")
        assert journal.checkpoint(row.run_id, row.path) is None
        old = AcquisitionPaths(
            tmp_path / "owned",
            acquisition_id_for(row.lease_id, row.acquisition_epoch),
        )
        closure = AcquisitionClosure(GitAuthority(
            tmp_path / "authority.git", tmp_path / "legacy",
        ))
        assert not closure.is_closed(old)
        assert (old.payload / "workspace" / "worker-ready").is_file()
        assert (old.payload / "workspace" / "session-child").is_file()

        original.kill()
        async with asyncio.timeout(5):
            while original.returncode is None:
                await asyncio.sleep(0.01)
        await until(lambda: journal.run_state(row.run_id).liveness == "lost")
        successor = await _owner(tmp_path, "recover")

        # Reconciliation revokes first, then waits for the inherited workspace
        # OFD. The stopped real supervisor makes both facts independently visible.
        async with asyncio.timeout(10):
            while not closure.is_closed(old):
                await asyncio.sleep(0.01)
        assert old.payload.exists()
        assert successor.returncode is None
        assert journal.run_state(row.run_id).status is RunStatus.RUNNING
        assert journal.checkpoint(row.run_id, row.path) is None
        with old.guard.open("rb") as guard, pytest.raises(BlockingIOError):
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        os.kill(supervisor, signal.SIGCONT)
        supervisor = None
        assert successor.stdout is not None and successor.stderr is not None
        stdout, stderr = await asyncio.wait_for(successor.communicate(), 50)
        assert successor.returncode == 0, stderr.decode()
        recovered = json.loads(stdout)

        async with asyncio.timeout(10):
            while any(birth(pid) == started for pid, started in resident.items()):
                await asyncio.sleep(0.01)
        assert closure.is_closed(old) and not old.payload.exists()
        assert recovered["run_id"] == row.run_id
        assert recovered["worker_calls"] == recovered["callback_responses"] == 1
        assert recovered["handle_closed"] and recovered["worker_inactive"]
        assert recovered["launch_checked"] and recovered["terminal_checked"]

        rows = journal.capability_leases(row.run_id)
        old_rows = [item for item in rows if item.acquisition_epoch == row.acquisition_epoch]
        assert {item.binding_id for item in old_rows} == {"workspace", "executor"}
        assert all(
            item.state == "closed" and item.disposition == "discarded"
            for item in old_rows
        )
        assert max(item.acquisition_epoch for item in rows) == row.acquisition_epoch + 1
        assert all(item.state == "closed" for item in rows)
        assert journal.run_state(row.run_id).status is RunStatus.SUCCEEDED

        candidate = GitSha(recovered["candidate"])
        authority = GitAuthority(tmp_path / "authority.git", tmp_path / "legacy")
        assert authority._run("show", f"{candidate}:recovered.txt").stdout == (
            "fresh successor callback"
        )
        assert authority._run(
            "cat-file", "-e", f"{candidate}:worker-ready", check=False,
        ).returncode != 0
        assert authority.resolve_ref("refs/heads/main") != candidate
        write_evidence("codex-write-recovery.json", {
            "schema_version": 1,
            "run_id": str(row.run_id),
            "old_acquisition": old.acquisition_id,
            "observed_pids": sorted(resident),
            "controller_died": original.returncode is not None,
            "closure_preceded_guard_release": True,
            "guard_exclusion_observed": True,
            "old_processes_reaped": True,
            "old_payload_discarded": True,
            "fresh_epoch": row.acquisition_epoch + 1,
            "fresh_callback_completed_once": True,
            "candidate": str(candidate),
            "checkpoint_completed": True,
        })
    finally:
        if supervisor is not None:
            with suppress(ProcessLookupError):
                os.kill(supervisor, signal.SIGCONT)
        await _kill(original)
        if successor is not None:
            await _kill(successor)
        if supervisor is not None and supervisor_started is not None:
            async with asyncio.timeout(10):
                while birth(supervisor) == supervisor_started:
                    await asyncio.sleep(0.01)
