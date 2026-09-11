"""Disposable controller for the existing supervisor's owner-death proof."""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from constructicon.core.identity import Digest
from tests.provider_placement import PlacementLauncher
from tests.substrate.test_provider_placement import observe

PROBE = '''
import json, os, signal, time
read_fd, write_fd = os.pipe()
if os.fork() == 0:
    os.close(read_fd)
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.write(write_fd, b"R")
    time.sleep(100)
else:
    os.close(write_fd)
    assert os.read(read_fd, 1) == b"R"
    print(json.dumps({"descendant_ready": True}), flush=True)
    time.sleep(100)
'''


async def main():
    from types import SimpleNamespace
    root = Path(os.environ["M8_PLACEMENT_ROOT"])
    policy = Path("/etc/apparmor.d/constructicon-m8-launch")
    endpoint = Path(sys.argv[1])
    observed = endpoint.stat()
    launcher = PlacementLauncher(
        runtime_root=root,
        expected_runtime=Digest(json.loads(root.with_suffix(".json").read_text())["runtime_digest"]),
        bubblewrap=Path(os.environ["M8_LINUX_ROOT"]) / "bwrap", policy=policy,
        expected_policy_sha256=hashlib.sha256(policy.read_bytes()).hexdigest(),
        endpoint=endpoint, endpoint_identity=(observed.st_dev, observed.st_ino),
    )

    async def ready(wire, _observations):
        assert "placement" in await wire.read()
        assert (await wire.read())["descendant_ready"]
        print("ready", flush=True)
        await wire.read()

    await observe(launcher, SimpleNamespace(deadline=float(sys.argv[3]), model="gpt-5.5"),
                  Path(sys.argv[2]),
                  probe=PROBE, query=ready)


if __name__ == "__main__":
    asyncio.run(main())
