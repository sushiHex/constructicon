"""Disposable controllers for the literal N2 WRITE worker-death proof.

The native byte peer is scripted.  The public WRITE provider and handle,
contained callback worker, workspace, capture, SQLite recovery and successor
are real.  Consequently this helper proves worker-supervisor/workspace-guard
custody only; it makes no native-supervisor/store-lock claim.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from contextlib import suppress
from dataclasses import fields
from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.control import RunSubmission
from constructicon.core.grants import Posture
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.core.run import RunStatus
from constructicon.core.workspace import acquisition_id_for
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.runtime.walker import DEFAULT_HEARTBEAT_INTERVAL_S, DEFAULT_LEASE_TTL_S
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.executors.operator_store import BindingStore
from constructicon.substrate.git.acquisition import AcquisitionPaths
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.captureworld import register_capture
from tests.substrate._gate_owner import installed_launcher
from tests.substrate.test_codex_adapter import FINISHED, descriptor_of
from tests.substrate.test_codex_write import WRITE_GRANTS, write_native, write_provider
from tests.substrate.test_codex_write_capture import PhysicalWorkerLauncher
from tests.substrate.test_operator_store_containment import KEY as STORE_KEY
from tests.substrate.test_provider_placement import descendants

ACTIVE_PROGRAM = """
import os, signal, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = os.fork()
if child == 0:
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path('session-child').write_text(str(os.getpid()))
    time.sleep(100)
    os._exit(0)
Path('worker-ready').write_text(str(os.getpid()))
while not Path('session-child').exists():
    time.sleep(.001)
time.sleep(100)
"""
RECOVERY_PROGRAM = (
    "from pathlib import Path; "
    "Path('recovered.txt').write_text('fresh successor callback'); "
    "print('recovered')"
)


def _binding() -> BindingStore:
    root = Path(os.environ["M8_OPERATOR_STORE_ROOT"])
    sealed = NativeOperatorStoreIdentityV1.model_validate_json(
        (root.parent / "operator-store-fixture.json").read_text(),
    )
    return BindingStore(root, STORE_KEY, sealed)


def _launcher(native, installed: LinuxLauncher) -> PhysicalWorkerLauncher:
    return PhysicalWorkerLauncher(
        **{item.name: getattr(installed, item.name) for item in fields(LinuxLauncher)},
        native=native,
        result=FINISHED,
    )


def assemble(root: Path, owner: str, *, recover: bool):
    journal = SqliteJournal(root / "control.sqlite")
    authority = GitAuthority(root / "authority.git", root / "legacy")
    native = write_native(program=RECOVERY_PROGRAM if recover else ACTIVE_PROGRAM)
    installed = installed_launcher()
    launcher = _launcher(native, installed)
    workspace = ContainedWriteWorkspaceProvider(
        authority,
        root=root / "owned",
        target_ref="refs/heads/main",
        provider_id="codex-write-recovery",
        posture=Posture.WRITE,
        # Capture uses the plain real launcher. Keeping it distinct makes the
        # scripted launcher's recorded ``run`` calls an exact worker count.
        launcher=installed,
    )
    executor = write_provider(
        launcher,
        binding=(_binding(), workspace.closure),
        root=root / "executor",
    )
    # The original's lease is short because the test waits for it to expire after
    # the kill. Nothing waits for the successor's lease, and a short one is a
    # scheduling margin: metering refuses dispatch on an expired lease
    # (_sqlite_metering._require_owner), so a loop stall past the TTL makes the
    # successor abandon its own attempt and reclaim the run at a third epoch (#417).
    ttl_s, heartbeat_s = (
        (DEFAULT_LEASE_TTL_S, DEFAULT_HEARTBEAT_INTERVAL_S) if recover else (0.4, 0.08)
    )
    system = Constructicon(
        journal=journal,
        owner_id=owner,
        lease_ttl_s=ttl_s,
        heartbeat_interval_s=heartbeat_s,
        root_grants=WRITE_GRANTS,
        capabilities={"capture": workspace, "recorded": executor},
        catalog={
            "capture": CapabilityDescriptor(
                capability_id="capture",
                kind="workspace.contained",
                leased=True,
                revision=workspace.revision,
                requires_posture=Posture.WRITE,
            ),
            "recorded": descriptor_of(executor, "recorded"),
        },
    )
    return system, journal, workspace, executor, launcher, native


def _direct_child() -> int:
    children = Path(
        f"/proc/{os.getpid()}/task/{os.getpid()}/children",
    ).read_text().split()
    if len(children) != 1:
        raise AssertionError(f"expected one active worker supervisor, observed {children!r}")
    return int(children[0])


async def _original(root: Path) -> None:
    system, journal, workspace, executor, launcher, native = assemble(
        root, "original-codex-write-owner", recover=False,
    )
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    graph = await register_capture(control, executor=True)
    submitted = await control.runs_start(
        RUN_ACTOR,
        proposal=graph,
        inputs={"goal": {"message": "literal WRITE recovery"}},
        idempotency_key="start-literal-write-recovery",
    )
    if not isinstance(submitted, RunSubmission):
        raise AssertionError(submitted)
    async with asyncio.timeout(30):
        row = None
        marker = None
        session_marker = None
        while (
            marker is None or not marker.exists()
            or session_marker is None or not session_marker.exists()
        ):
            rows = journal.capability_leases(submitted.run_id)
            row = next((item for item in rows if item.binding_id == "workspace"), None)
            if row is not None:
                acquisition = acquisition_id_for(row.lease_id, row.acquisition_epoch)
                worktree = AcquisitionPaths(workspace.root, acquisition).payload / "workspace"
                marker = worktree / "worker-ready"
                session_marker = worktree / "session-child"
            if (
                marker is None or not marker.exists()
                or session_marker is None or not session_marker.exists()
            ):
                await asyncio.sleep(0.01)
    assert row is not None and marker is not None and session_marker is not None
    supervisor = _direct_child()
    resident = descendants(os.getpid())
    assert supervisor in resident and len(resident) >= 3
    os.kill(supervisor, signal.SIGSTOP)
    handle = executor.handles[-1]
    print(json.dumps({
        "run_id": str(submitted.run_id),
        "workspace_lease": row.model_dump(mode="json"),
        "supervisor": supervisor,
        "resident": {str(pid): started for pid, started in resident.items()},
        "worker_active": handle.worker_active is not None,
        "launch_checked": handle.launch_check is not None,
        "callback_responses": len(native.callback_responses),
        "worker_calls": len(launcher.worker_calls),
    }), flush=True)
    await asyncio.Event().wait()


async def _recover(root: Path) -> None:
    system, journal, _, executor, launcher, native = assemble(
        root, "successor-codex-write-owner", recover=True,
    )
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        records = journal.run_records(limit=2)
        assert len(records) == 1
        run_id = records[0].run_id
        # A run still not terminal after the bound fails the assertion below, so
        # the same facts are printed for a timeout as for a failed run.
        with suppress(TimeoutError):
            async with asyncio.timeout(40):
                while journal.run_state(run_id).status not in (
                    RunStatus.SUCCEEDED, RunStatus.FAILED,
                ):
                    await asyncio.sleep(0.01)
        state = journal.run_state(run_id)
        # On failure only: how far the attempts in this process got. More than
        # one handle means the successor reclaimed its own run. ``turn/start``
        # among the peer's methods means the dispatch check had passed; the
        # facts do not name an earlier error that a settlement refusal replaced.
        assert state.status is RunStatus.SUCCEEDED, {
            "status": state.status.value,
            "handles": len(executor.handles),
            "peer_methods": native.methods,
            "callback_responses": len(native.callback_responses),
            "worker_calls": len(launcher.worker_calls),
            "events": journal.events(run_id),
        }
        rows = journal.capability_leases(run_id)
        workspace_row = max(
            (item for item in rows if item.binding_id == "workspace"),
            key=lambda item: item.acquisition_epoch,
        )
        checkpoint = journal.checkpoint(run_id, workspace_row.path)
        assert checkpoint is not None
        handle = executor.handles[-1]
        print(json.dumps({
            "run_id": str(run_id),
            "candidate": checkpoint.outputs["candidate"].payload["commit"],
            "callback_responses": len(native.callback_responses),
            "worker_calls": len(launcher.worker_calls),
            "handle_closed": handle.closed,
            "worker_inactive": handle.worker_active is None,
            "launch_checked": handle.launch_check is not None,
            "terminal_checked": handle.terminal_check is not None,
        }), flush=True)
    finally:
        await control.shutdown()


async def main() -> None:
    root = Path(sys.argv[1])
    if sys.argv[2] == "recover":
        await _recover(root)
    else:
        await _original(root)


if __name__ == "__main__":
    asyncio.run(main())
