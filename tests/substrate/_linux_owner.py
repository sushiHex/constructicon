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
    phase = sys.argv[2] if len(sys.argv) > 2 else "running"
    paths = AcquisitionPaths(owned, acquisition_id_for("lease-owner-death", 1))
    paths.payload.mkdir(parents=True)
    policy = Path("/etc/apparmor.d/constructicon-m8-launch")
    launcher = LinuxLauncher(
        runtime_root=root / "runtime",
        expected_runtime=Digest(json.loads((root / "runtime.json").read_text())["runtime_digest"]),
        bubblewrap=root / "bwrap", policy=policy,
        expected_policy_sha256=hashlib.sha256(policy.read_bytes()).hexdigest(),
    )
    if phase in {"setup", "duplex-setup"}:
        spawn = asyncio.create_subprocess_exec
        calls = 0

        async def held_spawn(*args, **kwargs):
            nonlocal calls
            calls += 1
            process = await spawn(*args, **kwargs)
            if calls == 2:
                # A real OS setup child holds the inherited guards, but the
                # controller does not yet own its handle or authorize start.
                print(json.dumps({"reaper": process.pid}), flush=True)
                await asyncio.Event().wait()
            return process

        asyncio.create_subprocess_exec = held_spawn
    source = """
import os, signal, time
if os.fork() == 0:
    os.setsid()
    if os.fork(): os._exit(0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open('/workspace/writer-id', 'w') as identity:
        identity.write(str(os.getpid()))
    with open('/workspace/live', 'w') as stream:
        while True:
            stream.write('x'); stream.flush(); time.sleep(.01)
while not os.path.exists('/workspace/live'): time.sleep(.001)
time.sleep(100)
"""
    duplex = phase.startswith("duplex")
    if duplex:
        source = (
            "import os, sys\nchallenge = os.urandom(16).hex()\n"
            "print(challenge, flush=True)\n"
            "assert sys.stdin.readline().strip() == challenge[::-1]\n"
        ) + source

    async def conversation(io):
        challenge = bytearray()
        while not challenge.endswith(b"\n"):
            data = await io.read()
            assert data
            challenge.extend(data)
        await io.write(bytes(challenge).strip()[::-1] + b"\n")
        await io.read()  # Remain in the exchange while the escaped descendant runs.

    async with acquisition_guard(paths) as guard:
        arguments = {
            "workspace": paths.payload, "posture": Posture.WRITE,
            "guard_fds": (guard,), "timeout_s": 60,
        }
        command = ("/usr/bin/python3", "-I", "-c", source)
        if duplex:
            await launcher.exchange(command, conversation=conversation, **arguments)
        else:
            await launcher.run(command, **arguments)


if __name__ == "__main__":
    asyncio.run(main())
