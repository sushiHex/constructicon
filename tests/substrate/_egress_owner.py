"""One disposable controller for the N3b owner-death and stalled-owner proofs.

``death``: stream through the relay until the test kills this process.
``stall``: once streaming, block this event loop past the deadline, then resume,
exit the relay and the acquisition guard, and report.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from constructicon.core.grants import Posture
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors import egress
from constructicon.substrate.executors.egress import (
    EgressDestination,
    EgressPolicy,
    EgressRelay,
)
from constructicon.substrate.executors.linux import ProcessExchangeError
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests.substrate.test_egress import CONTROLLED, controlled
from tests.substrate.test_linux_containment import launcher
from tests.substrate.test_native_egress_containment import ALLOWED, CLIENT
from tests.substrate.test_operator_store_containment import binding, hold, native_mount

# The peers are controlled loopback servers, as in the test process.
egress._routable = controlled(egress._routable)


async def main():
    mode, root, plan_path = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    plan = json.loads(plan_path.read_text())
    store = binding.__wrapped__()
    boundary = launcher.__wrapped__()
    held = await hold(store)
    paths = AcquisitionPaths(root, acquisition_id_for(plan["lease"], 1))
    seconds = plan["seconds"]
    deadline = asyncio.get_running_loop().time() + seconds
    policy = EgressPolicy((EgressDestination(ALLOWED, plan["allowed_port"], CONTROLLED),), 4)

    async def conversation(io):
        await io.write((json.dumps(plan) + "\n").encode())
        seen = bytearray()
        while b"streaming\n" not in seen:
            chunk = await io.read()
            if not chunk:
                return
            seen.extend(chunk)
        print("streaming", flush=True)
        if mode == "stall":
            print(f"stalling {deadline}", flush=True)
            time.sleep(seconds + plan["stall_extra"])  # blocks this whole loop
        while await io.read():
            pass

    relay = EgressRelay(policy, paths.payload, deadline, lambda: None)
    try:
        async with acquisition_guard(paths) as guard, relay as leaf:
            with native_mount(store, held, egress=leaf) as mount:
                try:
                    result = await boundary.exchange(
                        ("/usr/bin/python3", "-I", "-c", CLIENT), workspace=None,
                        posture=Posture.READ, guard_fds=(guard, held.lock_fd),
                        timeout_s=seconds, conversation=conversation, native_store=mount,
                    )
                except ProcessExchangeError as exc:
                    result = exc.result
    finally:
        store.close_held(held)
    print(json.dumps({
        "timed_out": result.timed_out, "closed": relay.closed,
        "observed": dict(relay.observed), "guard_released_at": time.monotonic(),
    }), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
