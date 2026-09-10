"""Real journal authority, responsive cancellation, and literal owner death."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import sys
import threading
from contextlib import closing, suppress
from pathlib import Path

import pytest

from constructicon.api.control import ControlPlane
from constructicon.core.control import (
    PromotionCommandResult,
    RegistrationCommandResult,
    RunSubmission,
)
from constructicon.core.graph import Connection, GraphNode, Ref
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunStatus
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.effects.git import MergeVerifiedEffect
from constructicon.substrate.git.acquisition import AcquisitionPaths
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import LOCAL_ADMIN, RUN_ACTOR
from tests.conftest import atomic
from tests.gateworld import register_gate
from tests.gitworld import EVALUATION, MERGED, merge_impl
from tests.runtime.test_async_gates import gate_system, until
from tests.substrate._gate_owner import assemble
from tests.substrate.test_contained_gates import candidate, unqualified
from tests.substrate.test_contained_gates import qualify as qualify_gate
from tests.substrate.test_contained_gates import started as started_gate
from tests.substrate.test_linux_containment import launcher as launcher


def workload_pids(tag):
    result = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            with suppress(FileNotFoundError, ProcessLookupError, PermissionError):
                command = (entry / "cmdline").read_bytes().split(b"\0")
                if command[:2] == [b"/usr/bin/python3", b"/workspace/check.py"] and (
                    tag.encode() in command
                ):
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


async def test_contained_gate_attestation_installs_through_the_public_effect_path(
    launcher, tmp_path,
):
    journal = SqliteJournal(tmp_path / "control.sqlite")
    runner = await qualify_gate(unqualified(tmp_path, launcher, journal=journal))
    sha = candidate(runner)
    expected = runner.authority.prepare_merge(sha, runner.target_ref).subject
    effect = MergeVerifiedEffect(journal=journal, authority=runner.authority)
    system = gate_system(journal, runner, effects={"merge_verified": effect})
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        graph = await register_gate(control)
        definition, _ = atomic("test/gated-merge", (EVALUATION,), (MERGED,), merge_impl)
        registered = await control.registry_register(
            LOCAL_ADMIN, definition=definition, idempotency_key="register-merge",
        )
        assert isinstance(registered, RegistrationCommandResult), registered
        promoted = await control.registry_promote_initial(
            LOCAL_ADMIN, component=definition.name, version=registered.version,
            idempotency_key="promote-merge",
        )
        assert isinstance(promoted, PromotionCommandResult), promoted
        graph = graph.model_copy(update={
            "outputs": (MERGED,),
            "nodes": (*graph.nodes, GraphNode(id="merge", body=Ref(component=definition.name))),
            "connections": (Connection(src="check", dst="merge"),),
        })
        submitted = await control.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"candidate": {"commit": sha}},
            idempotency_key="contained-merge",
        )
        assert isinstance(submitted, RunSubmission), submitted
        await succeeded(journal, submitted.run_id)
        assert runner.authority.resolve_ref(runner.target_ref) == expected.merge_commit
        assert durable_counts(tmp_path, submitted.run_id) == (1, 2)
        assert any(event.kind == "EffectCommitted" for event in journal.events(submitted.run_id))
    finally:
        await control.shutdown()


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


async def test_repeated_cancellation_joins_snapshot_cleanup(launcher, tmp_path, monkeypatch):
    import shutil

    from constructicon.substrate.gates.runner import CheckSpec

    runner = await qualify_gate(unqualified(tmp_path, launcher, (
        CheckSpec("slow", ("/usr/bin/python3", "/workspace/check.py", tmp_path.name), 30),
    )))
    sha = candidate(runner, {"check.py": "import os,time\nos.fork()\ntime.sleep(90)\n"})
    acquired = await started_gate(runner)
    entered, released = threading.Event(), threading.Event()
    original = shutil.rmtree

    def remove(path, *args, **kwargs):
        if path == acquired.resource.paths.payload:
            entered.set()
            assert released.wait(5)
        return original(path, *args, **kwargs)

    monkeypatch.setattr("constructicon.substrate.gates.contained.shutil.rmtree", remove)
    running = asyncio.create_task(acquired.resource.verify(sha))
    try:
        pids = await wait_workload(tmp_path.name)
        running.cancel()
        await until(entered.is_set)
        running.cancel()
        await asyncio.sleep(0)
        running.cancel()
        await asyncio.sleep(0)
        assert not running.done()
        assert acquired.resource.paths.payload.exists()
    finally:
        released.set()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    assert not runner._journal.drafts and not acquired.resource.paths.payload.exists()
    assert not workload_pids(tmp_path.name)
    assert all(not Path(f"/proc/{pid}").exists() for pid in pids)
    await runner.close(acquired, "discard")
