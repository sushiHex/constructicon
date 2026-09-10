"""Real journal authority, responsive cancellation, and literal owner death."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import sys
from contextlib import closing, suppress
from pathlib import Path

import pytest

from constructicon.api.control import ControlPlane
from constructicon.core.control import RunSubmission
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunStatus
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.git.acquisition import AcquisitionPaths
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.gateworld import register_gate
from tests.runtime.test_async_gates import until
from tests.substrate._gate_owner import assemble
from tests.substrate.test_contained_gates import candidate, unqualified
from tests.substrate.test_linux_containment import launcher as launcher


def workload_pids(tag):
    result = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            with suppress(FileNotFoundError, ProcessLookupError, PermissionError):
                command = (entry / "cmdline").read_bytes().split(b"\0")
                if b"/workspace/check.py" in command and tag.encode() in command:
                    result.append(int(entry.name))
    return result


async def wait_workload(tag):
    async with asyncio.timeout(20):
        while not (found := workload_pids(tag)):
            await asyncio.sleep(0.01)
    return found


def durable_counts(root, run_id):
    with closing(sqlite3.connect(root / "control.sqlite")) as connection:
        attestations = connection.execute(
            "SELECT COUNT(*) FROM attestations "
            "WHERE json_extract(attestation_json, '$.created_by_run') = ?", (run_id,),
        ).fetchone()[0]
        checkpoints = connection.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE run_id = ?", (run_id,),
        ).fetchone()[0]
    return attestations, checkpoints


async def succeeded(journal, run_id):
    async with asyncio.timeout(30):
        while journal.run_state(run_id).status not in (RunStatus.FAILED, RunStatus.SUCCEEDED):
            await asyncio.sleep(0.01)
    assert journal.run_state(run_id).status is RunStatus.SUCCEEDED, journal.events(run_id)


@pytest.mark.parametrize("phase", ["before_verify", "during_check"])
async def test_process_death_closes_old_gate_before_successor_attests(launcher, tmp_path, phase):
    initial = unqualified(tmp_path)
    sha = candidate(initial, {"check.py": "import time\ntime.sleep(2)\nprint('checked')\n"})
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.substrate._gate_owner", str(tmp_path), sha, phase,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    pids = []
    try:
        line = await asyncio.wait_for(child.stdout.readline(), 25)
        assert line, (await child.stderr.read()).decode()
        record = json.loads(line)
        row = CapabilityLease.model_validate(record["lease"])
        old = AcquisitionPaths(tmp_path / "gates", acquisition_id_for(row.lease_id,
                                                                     row.acquisition_epoch))
        if phase == "during_check":
            pids = await wait_workload(tmp_path.name)
        child.kill()
        await child.wait()
        system, journal, runner = await assemble(tmp_path, "successor-gate-owner")
        assert durable_counts(tmp_path, row.run_id) == (0, 0)
        async with asyncio.timeout(5):
            while journal.run_state(row.run_id).liveness != "lost":
                await asyncio.sleep(0.01)
        control = ControlPlane(system=system, store=journal)
        await control.startup()
        try:
            await succeeded(journal, row.run_id)
            assert runner.closure.is_closed(old) and not old.payload.exists()
            assert all(not Path(f"/proc/{pid}").exists() for pid in pids)
            rows = journal.capability_leases(row.run_id)
            assert all(item.state == "closed" for item in rows)
            assert max(item.acquisition_epoch for item in rows) > row.acquisition_epoch
            assert durable_counts(tmp_path, row.run_id) == (1, 1)
        finally:
            await control.shutdown()
    finally:
        if child.returncode is None:
            child.kill()
        await child.wait()


@pytest.mark.parametrize("stop", ["cancel", "shutdown", "ownership"])
async def test_running_gate_heartbeats_and_quiesces_without_authority(launcher, tmp_path, stop):
    initial = unqualified(tmp_path)
    sha = candidate(initial, {"check.py": "import os,time\nos.fork()\ntime.sleep(90)\n"})
    system, journal, runner = await assemble(tmp_path, "responsive-gate-owner")
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    pids = []
    try:
        graph = await register_gate(control)
        submitted = await control.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"candidate": {"commit": sha}},
            idempotency_key="native-run",
        )
        assert isinstance(submitted, RunSubmission), submitted
        pids = await wait_workload(tmp_path.name)
        original = journal.run_state(submitted.run_id)
        # An actual heartbeat, not a sleep-duration inference, must advance expiry.
        await until(lambda: journal.run_state(submitted.run_id).lease_expires_at
                    != original.lease_expires_at)
        assert workload_pids(tmp_path.name)
        if stop == "cancel":
            await control.runs_cancel(RUN_ACTOR, run_id=submitted.run_id, idempotency_key="cancel")
            await until(lambda: journal.run_state(submitted.run_id).status is RunStatus.CANCELLED)
        elif stop == "shutdown":
            await control.shutdown()
        else:
            # Expire the old owner then claim through the journal's own epoch law.
            from datetime import timedelta

            state = journal.run_state(submitted.run_id)
            journal._now = lambda: state.lease_expires_at + timedelta(seconds=1)
            successor = journal.claim_run(submitted.run_id, owner_id="stolen", ttl_s=30)
            assert successor.epoch > 1
            await until(lambda: not workload_pids(tmp_path.name))
            await control.shutdown()
        assert not workload_pids(tmp_path.name)
        assert all(not Path(f"/proc/{pid}").exists() for pid in pids)
        assert not list(runner.root.glob("payloads/*/snapshot"))
        assert durable_counts(tmp_path, submitted.run_id) == (0, 0)
    finally:
        await control.shutdown()
        for pid in pids:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
