"""Real journal/control/walker host used by the three allocation death seams."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sys
from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.component import CapabilityRequirement
from constructicon.core.control import (
    PromotionCommandResult,
    RegistrationCommandResult,
    RunSubmission,
)
from constructicon.core.grants import Posture
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import Digest, digest
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.contained import ContainedWorkspaceProvider
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import LOCAL_ADMIN, RUN_ACTOR
from tests.conftest import ISSUE, SUMMARY, atomic


async def read_workspace(ctx, inputs):
    workspace = ctx.capability("workspace")
    return {"summary": {"source": Path(workspace.path, "calc.py").read_text()}}


def assemble(root, owner):
    runtime = Path(os.environ["M8_LINUX_ROOT"])
    policy = Path("/etc/apparmor.d/constructicon-m8-launch")
    pinned = json.loads((runtime / "runtime.json").read_text())["runtime_digest"]
    launcher = LinuxLauncher(
        runtime_root=runtime / "runtime",
        expected_runtime=Digest(pinned),
        bubblewrap=runtime / "bwrap", policy=policy,
        expected_policy_sha256=hashlib.sha256(policy.read_bytes()).hexdigest(),
    )
    journal = SqliteJournal(root / "control.sqlite")
    authority = GitAuthority(root / "authority.git", root / "legacy")
    provider = ContainedWorkspaceProvider(
        authority, root=root / "owned", target_ref="refs/heads/main", provider_id="snapshot",
        posture=Posture.READ, launcher=launcher,
    )
    system = Constructicon(
        journal=journal, capabilities={"snapshot": provider},
        catalog={"snapshot": CapabilityDescriptor(
            capability_id="snapshot", kind="workspace.snapshot", leased=True,
            revision=str(digest("test-snapshot-revision", 1, launcher.revision)),
            requires_posture=Posture.READ,
        )},
        owner_id=owner, lease_ttl_s=.3, heartbeat_interval_s=.05,
    )
    return system, journal, provider


def pause(phase, row):
    print(json.dumps({"phase": phase, "lease": row.model_dump(mode="json")}), flush=True)
    os.kill(os.getpid(), signal.SIGSTOP)
    raise AssertionError("a killed controller resumed")


async def register_read(control):
    # This process runs as __main__; the durable PythonRef must instead name
    # the importable module that the successor can resolve independently.
    from tests.substrate._lease_owner import read_workspace as implementation

    definition, _ = atomic("test/leased-read", (ISSUE,), (SUMMARY,), implementation)
    definition = definition.model_copy(update={"capability_requirements": (
        CapabilityRequirement(alias="workspace", kind="workspace.snapshot"),
    )})
    registered = await control.registry_register(
        LOCAL_ADMIN, definition=definition, idempotency_key="register-read",
    )
    assert isinstance(registered, RegistrationCommandResult), registered
    promoted = await control.registry_promote_initial(
        LOCAL_ADMIN, component=definition.name, version=registered.version,
        idempotency_key="promote-read",
    )
    assert isinstance(promoted, PromotionCommandResult), promoted
    return Graph(name="leased-read", inputs=(ISSUE,), outputs=(SUMMARY,), nodes=(
        GraphNode(id="worker", body=Ref(
            component=definition.name, bind={"workspace": "snapshot"},
        )),
    ))


async def main():
    root, phase = Path(sys.argv[1]), sys.argv[2]
    system, journal, provider = assemble(root, "doomed-controller")
    record = journal.record_capability_lease
    row_seen = None

    def record_at_seam(lease, row):
        nonlocal row_seen
        row_seen = row
        if phase == "before_record":
            pause(phase, row)
        record(lease, row)
        if phase == "after_record":
            pause(phase, row)

    async def populate_at_seam(workspace, guard):
        assert row_seen is not None
        pause(phase, row_seen)

    journal.record_capability_lease = record_at_seam
    if phase == "during_materialization":
        provider.populate = populate_at_seam
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    graph = await register_read(control)
    submission = await control.runs_start(
        RUN_ACTOR, proposal=graph, inputs={"issue": {"title": "physical lease"}},
        idempotency_key="start-read",
    )
    assert isinstance(submission, RunSubmission), submission
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
