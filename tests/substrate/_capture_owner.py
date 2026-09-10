"""A real control-plane process paused across capture's durable boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sys
import threading
from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.core.control import RunSubmission
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.captureworld import capture_system, register_capture


def assemble(root, owner):
    runtime = Path(os.environ["M8_LINUX_ROOT"])
    policy = Path("/etc/apparmor.d/constructicon-m8-launch")
    pinned = json.loads((runtime / "runtime.json").read_text())["runtime_digest"]
    launcher = LinuxLauncher(
        runtime_root=runtime / "runtime",
        expected_runtime=Digest(pinned),
        bubblewrap=runtime / "bwrap",
        policy=policy,
        expected_policy_sha256=hashlib.sha256(policy.read_bytes()).hexdigest(),
    )
    journal = SqliteJournal(root / "control.sqlite")
    authority = GitAuthority(root / "authority.git", root / "legacy")
    provider = ContainedWriteWorkspaceProvider(
        authority,
        root=root / "owned",
        target_ref="refs/heads/main",
        provider_id="capture",
        posture=Posture.WRITE,
        launcher=launcher,
    )
    return capture_system(journal, provider, owner=owner, lease_ttl_s=0.4), journal, provider


async def main():
    root, phase = Path(sys.argv[1]), sys.argv[2]
    system, journal, provider = assemble(root, "doomed-capture-owner")
    row_seen = None
    record = journal.record_capability_lease
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()

    def record_at_seam(lease, row):
        nonlocal row_seen
        record(lease, row)
        row_seen = row

    def pause(**evidence):
        assert row_seen is not None
        resumed = threading.Event()

        def at_loop_boundary():
            # All journal transactions here are synchronous on the event loop.
            # Stop between callbacks, never freeze its heartbeat inside SQLite
            # merely because this publication seam runs in a Git worker thread.
            print(
                json.dumps({"phase": phase, "lease": row_seen.model_dump(mode="json"), **evidence}),
                flush=True,
            )
            os.kill(os.getpid(), signal.SIGSTOP)
            resumed.set()

        if threading.get_ident() == loop_thread:
            at_loop_boundary()
        else:
            loop.call_soon_threadsafe(at_loop_boundary)
            resumed.wait()

    spawn = asyncio.create_subprocess_exec

    async def spawn_at_seam(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        if (
            phase == "during_import"
            and "index-pack" in args
            and Path(kwargs["cwd"]).name.startswith("quarantine-")
        ):
            # Freeze the actual trusted child, then its Python owner. Killing
            # only the owner must not let recovery bypass the child's guard.
            os.kill(process.pid, signal.SIGSTOP)
            pause(child_pid=process.pid)
            raise AssertionError("a killed importer owner resumed")
        return process

    publish = provider.closure.publish

    def publish_at_seam(*args):
        publish(*args)
        if phase == "after_publication":
            pause()
            raise AssertionError("a killed publisher resumed")

    transaction = provider.authority._ref_transaction

    def transaction_at_seam(commands):
        if phase == "before_publication" and any("refs/candidates/" in c for c in commands):
            # After both the local control check AND the literal open-marker
            # read. Only Git's atomic absence assertion can fence this writer.
            pause()
            result = transaction(commands)
            outcome = "refused" if result.returncode else "published"
            print(json.dumps({"result": outcome}), flush=True)
            os.kill(os.getpid(), signal.SIGSTOP)
            raise AssertionError("the already-reconciled owner resumed twice")
        return transaction(commands)

    completion = journal.record_completion

    def completion_at_seam(*args):
        completion(*args)
        if phase == "after_checkpoint":
            pause()
            raise AssertionError("a killed checkpoint owner resumed")

    journal.record_capability_lease = record_at_seam
    journal.record_completion = completion_at_seam
    provider.closure.publish = publish_at_seam
    provider.authority._ref_transaction = transaction_at_seam
    asyncio.create_subprocess_exec = spawn_at_seam
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    graph = await register_capture(control)
    submission = await control.runs_start(
        RUN_ACTOR,
        proposal=graph,
        inputs={"goal": {"message": "capture"}},
        idempotency_key="start",
    )
    assert isinstance(submission, RunSubmission), submission
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
