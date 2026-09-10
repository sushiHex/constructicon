"""A real control-plane process paused across capture's durable boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sys
from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.core.control import RunSubmission
from constructicon.core.errors import ContractViolation
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

    def record_at_seam(lease, row):
        nonlocal row_seen
        record(lease, row)
        row_seen = row

    def pause():
        assert row_seen is not None
        print(json.dumps({"phase": phase, "lease": row_seen.model_dump(mode="json")}), flush=True)
        os.kill(os.getpid(), signal.SIGSTOP)

    publish = provider.closure.publish

    def publish_at_seam(*args):
        if phase == "before_publication":
            pause()  # After the last local control check; no physical guard held.
            try:
                publish(*args)
            except ContractViolation:
                print(json.dumps({"result": "refused"}), flush=True)
            else:
                print(json.dumps({"result": "published"}), flush=True)
            os.kill(os.getpid(), signal.SIGSTOP)
            raise AssertionError("the already-reconciled owner resumed twice")
        publish(*args)
        if phase == "after_publication":
            pause()
            raise AssertionError("a killed publisher resumed")

    completion = journal.record_completion

    def completion_at_seam(*args):
        completion(*args)
        if phase == "after_checkpoint":
            pause()
            raise AssertionError("a killed checkpoint owner resumed")

    journal.record_capability_lease = record_at_seam
    journal.record_completion = completion_at_seam
    provider.closure.publish = publish_at_seam
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
