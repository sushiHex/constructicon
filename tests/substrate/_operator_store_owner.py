"""One disposable controller for the N3a inherited-lock death proof."""

import asyncio
import sys
from pathlib import Path

from constructicon.core.grants import Posture
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests.substrate.test_linux_containment import launcher
from tests.substrate.test_operator_store_containment import binding, hold, native_mount


async def main():
    store = binding.__wrapped__()
    boundary = launcher.__wrapped__()
    held = await hold(store)
    paths = AcquisitionPaths(Path(sys.argv[1]), acquisition_id_for("n3a-owner-death", 1))

    async def conversation(io):
        line = bytearray()
        while not line.endswith(b"\n"):
            chunk = await io.read()
            assert chunk, "native readiness was never observed"
            line.extend(chunk)
        assert bytes(line) == b"ready\n"
        print("ready", flush=True)
        await io.close_stdin()
        while await io.read():
            pass

    try:
        async with acquisition_guard(paths) as guard:
            with native_mount(store, held) as mount:
                await boundary.exchange(
                    ("/usr/bin/python3", "-I", "-c",
                     "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                     "print('ready', flush=True); time.sleep(30)"),
                    workspace=None, posture=Posture.READ, guard_fds=(guard, held.lock_fd),
                    conversation=conversation, timeout_s=20, native_store=mount,
                )
    finally:
        store.close_held(held)


if __name__ == "__main__":
    asyncio.run(main())
