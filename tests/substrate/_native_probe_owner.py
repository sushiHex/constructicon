"""Disposable native probe owner; no production adapter or credential authority.

The parent kills this interpreter, then reconciles serialized fixture lease
rows with the existing providers. This is not a RunHost/journal recovery proof.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from constructicon.core.executor import TaskSpec
from constructicon.core.grants import Posture
from constructicon.core.manifest import CapabilityLease
from constructicon.core.workspace import StaleAcquisition
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.contained import ContainedWorkspaceProvider
from tests.containedworld import RecordedExecutorProvider
from tests.native_codex_probe import run_probe
from tests.substrate.test_contained_workspace import context, stale_row
from tests.substrate.test_linux_containment import launcher
from tests.substrate.test_native_codex_mediation import (
    WORKER,
    argv_for,
    fake_provider,
    install_catalog,
    process_state,
)


async def wait_for_heartbeat(heartbeat):
    async with asyncio.timeout(15):
        while not heartbeat.exists() or not heartbeat.read_bytes():
            await asyncio.sleep(.01)


async def main():
    root, mode, model = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    rows = ([StaleAcquisition(lease=CapabilityLease.model_validate(row), disposition="discard")
             for row in json.loads(sys.stdin.read())] if mode == "reconcile" else [])
    epoch = max(row.lease.acquisition_epoch for row in rows) + 1 if rows else int(mode)
    # Use the same fixture factories and real boundary as the in-process lane.
    workspaces = ContainedWorkspaceProvider(
        GitAuthority(root / "authority.git", root / "legacy"), root=root / "owned",
        target_ref="refs/heads/main", provider_id="test-workspace", posture=Posture.WRITE,
        launcher=launcher.__wrapped__(),
    )
    executor = RecordedExecutorProvider(workspaces.launcher, workspaces, WORKER)
    contexts = [context(epoch=epoch, posture=Posture.WRITE, binding=binding)
                for binding in ("workspace", "executor")]
    if mode == "reconcile":
        await executor.reconcile(contexts[1], (rows[1],))
        await workspaces.reconcile(contexts[0], (rows[0],))
        print(json.dumps({"phase": "reconciled"}), flush=True)
        return
    await executor.qualify()
    workspace = await workspaces.acquire(contexts[0])
    acquired = await executor.acquire(contexts[1])
    # Enroll both inert handles before materialization can create or block on
    # persistent resources. The parent retains these rows even without a PID.
    print(json.dumps({"phase": "acquired",
                      "leases": [stale_row(handle, ctx).lease.model_dump(mode="json")
                                 for handle, ctx in zip((workspace, acquired), contexts,
                                                        strict=True)]}), flush=True)
    if sys.argv[4] == "during-materialization":
        async def stalled_population(_workspace, _guard):
            (root / "materialization-entered").write_text("entered")
            await asyncio.Event().wait()
        workspaces.populate = stalled_population
    home = root / f"home-{epoch}"
    config = home / ".codex"
    config.mkdir(parents=True)
    env = {"HOME": str(home), "CODEX_HOME": str(config),
           "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    binary = Path(os.environ["M8_CODEX_BINARY"])
    catalog = install_catalog((binary, env), restricted=True)
    native_pid = None
    create = asyncio.create_subprocess_exec

    async def observe(*argv, **kwargs):
        nonlocal native_pid
        process = await create(*argv, **kwargs)
        if argv[0] == str(binary):
            native_pid = process.pid
            state = process_state(native_pid)
            assert state is not None and state[0] != "Z"
            # Report before any tool/heartbeat await, including a failed turn.
            print(json.dumps({"phase": "native-started", "native_pid": native_pid,
                              "native_start": state[1]}), flush=True)
        return process

    asyncio.create_subprocess_exec = observe
    heartbeat = Path(workspace.resource.path) / "worker-live"
    program = (
        "import time\n"
        "with open('/workspace/worker-live', 'ab', buffering=0) as beat:\n"
        "    while True:\n"
        "        beat.write(b'.'); time.sleep(.02)\n"
    ) if epoch == 1 else "print('{\"type\":\"result\",\"output\":{\"fresh\":true}}')"

    async def worker(source):
        if sys.argv[4] == "before-worker":
            await asyncio.Event().wait()  # Regression: no heartbeat ever arrives.
        result = await acquired.resource.execute(
            TaskSpec(instruction=source), workspace=workspace.resource,
            grants=contexts[1].binding.effective_grants,
        )
        assert result.status == "success", result
        return json.dumps(result.output)

    async def report_active():
        await wait_for_heartbeat(heartbeat)
        assert acquired.resource.active is not None and native_pid is not None
        print(json.dumps({"phase": "active"}), flush=True)

    try:
        await workspace.materialize()
        await acquired.materialize()
        async with fake_provider("contained_python", {"program": program}, model=model) as exchange:
            endpoint, requests, failures = exchange
            argv = argv_for((binary, env), root, endpoint, images=False, model=model,
                            catalog=catalog)
            async with asyncio.TaskGroup() as group:
                if epoch == 1 and sys.argv[4] == "active":
                    group.create_task(report_active())
                result = await run_probe(argv, cwd=root, env=env, worker=worker, model=model)
            assert not failures and len(requests) == 2
            assert result["calls"] == ["call_probe"]
    finally:
        await executor.close(acquired, "discard")
        await workspaces.close(workspace, "discard")
    assert epoch == 2  # The first owner must be killed, not finish cooperatively.
    print(json.dumps({"phase": "completed", "native_pid": native_pid,
                      "executor_closed": workspaces.closure.is_closed(acquired.resource.paths),
                      "workspace_closed": workspaces.closure.is_closed(workspace.resource.paths),
                      "workspace_removed": not workspace.resource.paths.payload.exists()}),
          flush=True)


if __name__ == "__main__":
    asyncio.run(main())
