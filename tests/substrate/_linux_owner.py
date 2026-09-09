"""A disposable real Python controller, killed by the Linux acceptance tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from constructicon.core.grants import Posture
from constructicon.core.identity import Digest
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard


async def main():
    root = Path(os.environ["M8_LINUX_ROOT"])
    owned = Path(sys.argv[1])
    paths = AcquisitionPaths(owned, acquisition_id_for("lease-owner-death", 1))
    paths.payload.mkdir(parents=True)
    policy = Path("/etc/apparmor.d/constructicon-m8-launch")
    launcher = LinuxLauncher(
        runtime_root=root / "runtime",
        expected_runtime=Digest(json.loads((root / "runtime.json").read_text())["runtime_digest"]),
        bubblewrap=root / "bwrap", policy=policy,
        expected_policy_sha256=hashlib.sha256(policy.read_bytes()).hexdigest(),
    )
    source = """
import os, signal, time
if os.fork() == 0:
    os.setsid()
    if os.fork(): os._exit(0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open('/workspace/live', 'w') as stream:
        while True:
            stream.write('x'); stream.flush(); time.sleep(.01)
while not os.path.exists('/workspace/live'): time.sleep(.001)
time.sleep(100)
"""
    async with acquisition_guard(paths) as guard:
        await launcher.run(
            ("/usr/bin/python3", "-I", "-c", source), workspace=paths.payload,
            posture=Posture.WRITE, guard_fds=(guard,), timeout_s=60,
        )


if __name__ == "__main__":
    asyncio.run(main())
