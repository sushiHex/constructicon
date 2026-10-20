"""Scripted Pi lifecycle: portable instrument check plus literal Linux death.

Only the provisioned Linux cases establish physical recovery. The portable
instrument check proves its pause depends on observed real-file READ bytes.
"""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import pytest

from constructicon.core.executor import TaskSpec
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunStatus
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors.pi_read import PI_LIMITS, PiReadConversation
from constructicon.substrate.git.acquisition import AcquisitionClosure, AcquisitionPaths
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.gitworld import seed_authority
from tests.piworld import PeerIO
from tests.substrate import _pi_recovery_owner as recovery_owner
from tests.substrate._evidence_secrecy import assert_clean_evidence
from tests.substrate._pi_recovery_owner import EVIDENCE_NAMES, FIXTURE_TEXT, PHASES, ObservedIO
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence


async def test_active_pause_follows_actual_read_before_prompt_write_returns(tmp_path):
    text = "literal recovery READ é"
    (tmp_path / "fixture.txt").write_text(text, encoding="utf-8")
    peer = PeerIO(tmp_path)
    observed = []

    class Paused(Exception):
        pass

    def pause():
        assert io.read_result.is_set()
        assert not peer.closed  # The still-pending prompt prevented half-close.
        observed.append("read-before-write-return")
        raise Paused

    io = ObservedIO(peer, expected=text, dispatch=lambda: observed.append("dispatch"),
                    pause=pause)
    conversation = PiReadConversation(TaskSpec(instruction="Analyze fixture.txt"),
                                      input_limit=PI_LIMITS.input_bytes)
    with pytest.raises(Paused):
        await conversation(io)
    assert observed == ["dispatch", "read-before-write-return"]
    assert len(peer.writes) == 2 and not peer.closed


@pytest.mark.parametrize("current, permitted", [
    (("old", "R"), False), (("old", "S"), False), (("old", "T"), False),
    (("old", "Z"), True), (("old", "X"), True), (("old", "x"), True),
    (("new", "R"), True), (None, True),
])
def test_quiescence_distinguishes_live_old_process_from_exit_or_pid_reuse(
    monkeypatch, current, permitted,
):
    monkeypatch.setattr(recovery_owner, "process_status", lambda pid: current)
    previous = {"processes": {123: "old"}}
    if permitted:
        result = recovery_owner.assert_previous_quiescent(previous)
        assert set(result) == {"123"}
        assert result["123"] in {"absent", "reused", "Z", "X", "x"}
    else:
        with pytest.raises(AssertionError, match="preceded old-process quiescence"):
            recovery_owner.assert_previous_quiescent(previous)


@pytest.fixture(scope="module", autouse=True)
def recovery_evidence_census():
    yield
    location = os.environ.get("M8_EVIDENCE_DIRECTORY")
    required = bool(os.environ.get("M8_CONTAINMENT_REQUIRED"))
    if sys.platform == "linux" and (location or required):
        assert_clean_evidence(Path(location) if location else None,
                              "duplex-pi-recovery-*.json", EVIDENCE_NAMES, (),
                              required=required)


@pytest.mark.parametrize("damage", [None, "missing", "extra"])
def test_recovery_evidence_family_has_an_exact_census(tmp_path, damage):
    for name in EVIDENCE_NAMES:
        (tmp_path / name).write_text('{"proof":"scripted peer only"}', encoding="utf-8")
    if damage == "missing":
        (tmp_path / EVIDENCE_NAMES[0]).unlink()
    elif damage == "extra":
        (tmp_path / "duplex-pi-recovery-unexpected.json").write_text("{}", encoding="utf-8")
    if damage:
        with pytest.raises(AssertionError):
            assert_clean_evidence(tmp_path, "duplex-pi-recovery-*.json", EVIDENCE_NAMES, ())
    else:
        assert_clean_evidence(tmp_path, "duplex-pi-recovery-*.json", EVIDENCE_NAMES, ())


async def owner(root, phase):
    return await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.substrate._pi_recovery_owner", str(root), phase,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, limit=1048576,
    )


async def stop(process):
    if process is None:
        return
    if process.returncode is None:
        process.kill()
    await asyncio.wait_for(process.communicate(), 5)


@pytest.mark.parametrize("phase", PHASES)
async def test_pi_owner_death_recovers_only_from_sqlite(launcher, tmp_path, phase):
    """Actual old children and guard custody; no vendor, store or model call."""
    seed_authority(tmp_path, {"fixture.txt": FIXTURE_TEXT})
    authority = GitAuthority(tmp_path / "authority.git", tmp_path / "legacy")
    head = authority.read_ref("refs/heads/main")
    closure = AcquisitionClosure(authority)
    journal = SqliteJournal(tmp_path / "control.sqlite")
    original = await owner(tmp_path, phase)
    successor = None
    evidence = {"phase": phase, "proof": "scripted peer; no Pi/provider qualification"}
    try:
        raw = await asyncio.wait_for(original.stdout.readline(), 25)
        assert raw, "original controller exited before affirming the selected seam"
        evidence["before_death"] = observed = json.loads(raw)
        assert observed["phase"] == phase and observed["controller"] == original.pid
        row = CapabilityLease.model_validate(observed["lease"])
        rows = journal.capability_leases(row.run_id)
        assert row in rows
        assert [item.model_dump(mode="json") for item in rows] == observed["rows"]
        paths = AcquisitionPaths(tmp_path / "executor", acquisition_id_for(
            row.lease_id, row.acquisition_epoch,
        ))
        assert not closure.is_closed(paths)
        checkpoint = journal.checkpoint(row.run_id, row.path)
        retained = phase == "after_checkpoint"
        assert (checkpoint is not None) is retained
        if phase == "before_materialization":
            assert not observed["entered"] and not paths.guard.exists()
        elif phase == "during_materialization":
            assert observed["entered"] and not observed["ready"]
        else:
            assert observed["entered"] and observed["ready"] and observed["executed"]
        if phase == "during_active":
            assert observed["read_observed"] and observed["processes"]
            assert observed["dispatches"] == 1
            import fcntl

            assert {item.binding_id for item in rows} == {"executor", "workspace"}
            held = []
            for item in rows:
                area = "executor" if item.binding_id == "executor" else "workspace"
                owned = AcquisitionPaths(tmp_path / area, acquisition_id_for(
                    item.lease_id, item.acquisition_epoch,
                ))
                fd = os.open(owned.guard, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    with pytest.raises(BlockingIOError):
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held.append(item.binding_id)
                finally:
                    os.close(fd)
            evidence["active_guards_held"] = sorted(held)
        if phase in {"before_checkpoint", "after_checkpoint"}:
            assert observed["dispatches"] == 1
        # This metadata is an assertion instrument, not provider recovery input.
        # The successor obtains its actual stale inventory from SQLite/RunHost.
        (tmp_path / "prior.json").write_text(json.dumps(observed), encoding="utf-8")
        original.kill()  # Kill the controller only, never its supervisor/group.
        await asyncio.wait_for(original.wait(), 5)
        assert original.returncode == -signal.SIGKILL
        evidence["controller_death_observed"] = True
        # Do not pre-reap descendants or wait for liveness loss here. Successor
        # reconciliation owns quiescence before any fresh request can dispatch.
        successor = await owner(tmp_path, "recover")
        stdout, stderr = await asyncio.wait_for(successor.communicate(), 35)
        assert successor.returncode == 0, stderr.decode("utf-8", errors="replace")
        evidence["successor"] = recovered = json.loads(stdout)
        assert recovered["run_id"] == str(row.run_id)
        assert recovered["identity"] == observed["identity"]
        assert recovered["workspace_head"] == str(head)
        assert recovered["acquired"] == (0 if retained else 1)
        assert len(recovered["dispatches"]) == (0 if retained else 1)
        assert recovered["eof"] is (None if retained else True)
        assert recovered["old_quiescent_before_dispatch"] is (None if retained else True)
        quiescence = recovered["quiescence_observations"]
        assert set(quiescence["after_join"]) == set(observed["processes"])
        if not retained:
            assert set(quiescence["before_acquire"]) == set(observed["processes"])
            assert set(quiescence["before_dispatch"]) == set(observed["processes"])
        assert row.resource_ref in recovered["reconciled"]
        if not retained:
            assert recovered["dispatches"][0] != paths.acquisition_id
        after = journal.capability_leases(row.run_id)
        assert after and all(item.state == "closed" for item in after)
        disposition = "released" if retained else "discarded"
        for previous in rows:
            closed = next(item for item in after if item.lease_id == previous.lease_id
                          and item.acquisition_epoch == previous.acquisition_epoch)
            assert closed.disposition == disposition
            area = "executor" if previous.binding_id == "executor" else "workspace"
            old_paths = AcquisitionPaths(tmp_path / area, acquisition_id_for(
                previous.lease_id, previous.acquisition_epoch,
            ))
            assert closure.is_closed(old_paths) and not old_paths.payload.exists()
        current = journal.checkpoint(row.run_id, row.path)
        assert current is not None
        assert current.outputs["summary"].payload == "Read: " + FIXTURE_TEXT
        if retained:
            assert current == checkpoint
        assert journal.run_state(row.run_id).status is RunStatus.SUCCEEDED
        assert not journal.cancel_requested(row.run_id)
        assert authority.read_ref("refs/heads/main") == head
        evidence["leases_after"] = [item.model_dump(mode="json") for item in after]
        evidence["checkpoint_retained_without_redispatch"] = retained
        evidence["status"] = "success"
    finally:
        await stop(original)
        await stop(successor)
        write_evidence(f"duplex-pi-recovery-{phase}.json", evidence)
