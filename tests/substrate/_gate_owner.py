"""Literal process-death fixture over the public async gate path."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.core.control import RunSubmission
from constructicon.core.identity import Digest
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.gates.contained import BoundContainedGate, ContainedGateRunner
from constructicon.substrate.gates.runner import CheckSpec
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.gateworld import register_gate
from tests.runtime.test_async_gates import gate_system


def installed_launcher():
    root = Path(os.environ["M8_LINUX_ROOT"])
    policy = Path("/etc/apparmor.d/constructicon-m8-launch")
    return LinuxLauncher(
        runtime_root=root / "runtime",
        expected_runtime=Digest(json.loads((root / "runtime.json").read_text())["runtime_digest"]),
        bubblewrap=root / "bwrap", policy=policy,
        expected_policy_sha256=hashlib.sha256(policy.read_bytes()).hexdigest(),
    )


async def assemble(root, owner):
    journal = SqliteJournal(root / "control.sqlite")
    runner = await ContainedGateRunner.create(
        journal=journal, authority=GitAuthority(root / "authority.git", root / "legacy"),
        root=root / "gates", target_ref="refs/heads/main", provider_id="lifecycle-gates",
        launcher=installed_launcher(), checks=(CheckSpec(
            "repository-check", ("/usr/bin/python3", "/workspace/check.py", str(root.name)), 30,
        ),),
    )
    return gate_system(journal, runner, owner=owner, lease_ttl_s=2), journal, runner


async def main(root, candidate, phase):
    system, journal, runner = await assemble(root, "original-gate-owner")

    def report(handle):
        rows = journal.capability_leases(handle.context.run_lease.run_id)
        row = next(row for row in rows
                   if row.resource_ref and handle.paths.acquisition_id in row.resource_ref)
        print(json.dumps({"phase": phase, "lease": row.model_dump(mode="json")}), flush=True)

    if phase == "before_verify":
        original = BoundContainedGate.materialize

        async def pause(handle):
            await original(handle)
            report(handle)
            await asyncio.Event().wait()

        BoundContainedGate.materialize = pause
    else:
        original_snapshot = runner._snapshot

        async def snapshot(handle, *args):
            result = await original_snapshot(handle, *args)
            report(handle)
            return result

        runner._snapshot = snapshot
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    graph = await register_gate(control)
    submission = await control.runs_start(
        RUN_ACTOR, proposal=graph, inputs={"candidate": {"commit": candidate}},
        idempotency_key="start-native-gate",
    )
    assert isinstance(submission, RunSubmission), submission
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
