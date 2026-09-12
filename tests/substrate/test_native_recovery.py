"""Physical native recovery through real SQLite, re-import and RunHost."""

import asyncio
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from constructicon.api.control import ControlPlane
from constructicon.core.control import RunSubmission
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunStatus
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.git.acquisition import AcquisitionPaths
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.gitworld import seed_authority
from tests.native_lifecycle import assemble, register_native
from tests.native_startup import MODELS
from tests.runtime.test_async_workspace import until
from tests.substrate._native_recovery_owner import physical_snapshot
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence
from tests.substrate.test_provider_placement import placement_image as placement_image

PHASES = ("before_materialization", "during_materialization", "during_active",
          "before_checkpoint", "after_checkpoint")


@pytest.fixture
def native_root(launcher, placement_image):
    # Keep the acquisition-derived AF_UNIX locator below Linux's pathname bound.
    # This root belongs to this test only and outlives both real interpreters.
    with tempfile.TemporaryDirectory(prefix="m8n-") as directory:
        root = Path(directory)
        seed_authority(root)
        yield root


async def owner(root, model, phase):
    return await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.substrate._native_recovery_owner", str(root), model, phase,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=1024 * 1024,
    )


async def kill(process):
    if process.returncode is None:
        process.kill()
    await asyncio.wait_for(process.communicate(), 5)


async def assert_reaped(snapshot):
    async with asyncio.timeout(5):
        while any(Path(f"/proc/{pid}").exists() for pid in snapshot["processes"]):
            await asyncio.sleep(0.01)
    for home in snapshot["native_homes"]:
        assert not Path(f"/proc/{home['pid']}/root/tmp/home").exists()


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("phase", PHASES)
async def test_native_owner_death_recovers_from_sqlite(native_root, model, phase):
    original = await owner(native_root, model, phase)
    successor = None
    evidence = {"phase": phase, "model": model}
    try:
        raw = await asyncio.wait_for(original.stdout.readline(), 25)
        assert raw, (await original.stderr.read()).decode()
        evidence["before_death"] = observed = json.loads(raw)
        # Read the row independently, before allowing a successor to recover it.
        journal = SqliteJournal(native_root / "control.sqlite")
        rows = journal.capability_leases(observed["run_id"])
        row = next(row for row in rows if row.binding_id == "native")
        assert row == CapabilityLease.model_validate(observed["lease"])
        paths = AcquisitionPaths(native_root / "n", acquisition_id_for(row.lease_id,
                                                                       row.acquisition_epoch))
        authority = GitAuthority(native_root / "authority.git", native_root / "legacy")
        from constructicon.substrate.git.acquisition import AcquisitionClosure

        closure = AcquisitionClosure(authority)
        assert not closure.is_closed(paths)
        assert paths.payload.exists() is (phase != "before_materialization")
        checkpoint = journal.checkpoint(row.run_id, row.path)
        assert (checkpoint is not None) is (phase == "after_checkpoint")
        if phase == "during_active":
            assert observed["native_homes"] and observed["session_children"]
            assert (paths.payload / "provider.sock").is_socket()
        await kill(original)
        await assert_reaped(observed)
        evidence["old_processes_reaped_before_recovery"] = True
        assert not closure.is_closed(paths), "process death is not journal reconciliation"
        await until(lambda: journal.run_state(row.run_id).liveness == "lost")
        successor = await owner(native_root, model, "recover")
        stdout, stderr = await asyncio.wait_for(successor.communicate(), 35)
        assert successor.returncode == 0, stderr.decode()
        evidence["successor"] = recovered = json.loads(stdout)
        assert recovered["run_id"] == row.run_id
        assert closure.is_closed(paths) and not paths.payload.exists()
        retained = phase == "after_checkpoint"
        assert recovered["acquired"] == (0 if retained else 1)
        assert len(recovered["completed"]) == (0 if retained else 1)
        after = journal.capability_leases(row.run_id)
        assert after and all(item.state == "closed" for item in after)
        native_rows = [item for item in after if item.binding_id == "native"]
        assert len(native_rows) == (1 if retained else 2)
        assert max(item.acquisition_epoch for item in native_rows) == (
            row.acquisition_epoch if retained else row.acquisition_epoch + 1
        )
        assert journal.run_state(row.run_id).status is RunStatus.SUCCEEDED
        if retained:
            assert journal.checkpoint(row.run_id, row.path) == checkpoint
        else:
            fresh = recovered["completed"][0]
            assert fresh["acquisition"] != paths.acquisition_id
            old_thread = observed.get("observed_before_death", {}).get("protocol", {}).get("thread")
            if old_thread is not None:
                assert fresh["thread_id"] != old_thread
        evidence["leases_after"] = [item.model_dump(mode="json") for item in after]
    finally:
        await kill(original)
        if successor is not None:
            await kill(successor)
        write_evidence(f"codex-recovery-{model}-{phase}.json", evidence)


@pytest.mark.parametrize("stop", ["cancel", "ownership"])
async def test_native_cancellation_and_revocation(native_root, launcher, placement_image, stop):
    system, journal, provider = assemble(native_root, launcher=launcher, image=placement_image)
    ready = asyncio.Event()
    observed = {}

    async def pause(phase, handle):
        if phase == "during_active":
            observed.update(physical_snapshot())
            observed["handle"] = handle
            ready.set()
            await asyncio.Event().wait()

    provider.hook = pause
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        graph = await register_native(control)
        submitted = await control.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"goal": {"message": "native fixture"}},
            idempotency_key="native-revocation",
        )
        assert isinstance(submitted, RunSubmission), submitted
        await asyncio.wait_for(ready.wait(), 20)
        assert observed["native_homes"] and observed["session_children"]
        handle = observed["handle"]
        state = journal.run_state(submitted.run_id)
        await until(lambda: journal.run_state(submitted.run_id).lease_expires_at
                    != state.lease_expires_at)
        if stop == "cancel":
            await control.runs_cancel(RUN_ACTOR, run_id=submitted.run_id,
                                      idempotency_key="cancel-native")
            await until(lambda: journal.run_state(submitted.run_id).status is RunStatus.CANCELLED)
        else:
            state = journal.run_state(submitted.run_id)
            journal._now = lambda: state.lease_expires_at + timedelta(seconds=1)
            lease = journal.claim_run(submitted.run_id, owner_id="new-owner", ttl_s=30)
            assert lease.epoch > handle.context.run_lease.epoch
        await assert_reaped(observed)
        await control.shutdown()
        assert provider.closure.is_closed(handle.paths) and not handle.paths.payload.exists()
        assert not provider.completed
        assert journal.checkpoint(submitted.run_id, handle.context.path) is None
        from constructicon.core.errors import ContractViolation

        with pytest.raises(ContractViolation, match="not open"):
            handle.require_open()
        write_evidence(f"codex-recovery-{stop}.json", {
            "processes": observed["processes"], "native_homes": observed["native_homes"],
            "session_children": observed["session_children"], "old_processes_reaped": True,
            "closed": True, "completed": provider.completed,
        })
    finally:
        await control.shutdown()
