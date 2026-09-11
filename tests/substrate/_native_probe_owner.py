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
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.contained import ContainedWorkspaceProvider
from tests.containedworld import RecordedExecutorProvider
from tests.native_codex_probe import run_probe
from tests.substrate.test_contained_workspace import context, stale_row
from tests.substrate.test_linux_containment import launcher
from tests.substrate.test_native_codex_mediation import WORKER, argv_for, catalog_for, fake_provider


async def main():
    root, epoch, model = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    # Use the same fixture factories and real boundary as the in-process lane.
    workspaces = ContainedWorkspaceProvider(
        GitAuthority(root / "authority.git", root / "legacy"), root=root / "owned",
        target_ref="refs/heads/main", provider_id="test-workspace", posture=Posture.WRITE,
        launcher=launcher.__wrapped__(),
    )
    executor = RecordedExecutorProvider(workspaces.launcher, workspaces, WORKER)
    await executor.qualify()
    contexts = [context(epoch=epoch, posture=Posture.WRITE, binding=binding)
                for binding in ("workspace", "executor")]
    workspace = await workspaces.acquire(contexts[0])
    acquired = await executor.acquire(contexts[1])
    home = root / f"home-{epoch}"
    config = home / ".codex"
    config.mkdir(parents=True)
    env = {"HOME": str(home), "CODEX_HOME": str(config),
           "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    binary = Path(os.environ["M8_CODEX_BINARY"])
    catalog = config / "catalog.json"
    catalog.write_bytes(catalog_for(Path(os.environ["M8_CODEX_CATALOG"]).read_bytes(),
                                    restricted=True))
    native_pid = None
    create = asyncio.create_subprocess_exec

    async def observe(*argv, **kwargs):
        nonlocal native_pid
        process = await create(*argv, **kwargs)
        if argv[0] == str(binary):
            native_pid = process.pid
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
        result = await acquired.resource.execute(
            TaskSpec(instruction=source), workspace=workspace.resource,
            grants=contexts[1].binding.effective_grants,
        )
        assert result.status == "success", result
        return json.dumps(result.output)

    async def report_active():
        async with asyncio.timeout(15):
            while not heartbeat.exists():
                await asyncio.sleep(.01)
        assert acquired.resource.active is not None and native_pid is not None
        print(json.dumps({"phase": "active", "native_pid": native_pid,
                          "leases": [stale_row(handle, ctx).lease.model_dump(mode="json")
                                     for handle, ctx in zip((workspace, acquired), contexts,
                                                            strict=True)]}), flush=True)

    try:
        await workspace.materialize()
        await acquired.materialize()
        async with fake_provider("contained_python", {"program": program}, model=model) as exchange:
            endpoint, requests, failures = exchange
            argv = argv_for((binary, env), root, endpoint, images=False, model=model,
                            catalog=catalog)
            async with asyncio.TaskGroup() as group:
                if epoch == 1:
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
