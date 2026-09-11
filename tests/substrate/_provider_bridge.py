"""Fixed-endpoint byte transport, a descendant of the existing owner.

No reaper, retry, URL parser, or provider protocol. Its exit is deliberately
not a separate supervisor observation. This file runs only in a test image.
"""

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _provider_transport import (
    ENDPOINT,
    HANDLER_SECONDS,
    Budget,
    descriptors,
    forward,
)


async def bridge(listener, ready_fd, deadline, fault, entry_fds):
    loop = asyncio.get_running_loop()
    budget = Budget()
    async with asyncio.timeout_at(deadline):
        # This connection is kept for the first request, not spent on a probe.
        peer = socket.socket(socket.AF_UNIX)
        peer.setblocking(False)
        try:
            await loop.sock_connect(peer, ENDPOINT)
            if fault == "before_ready":
                os._exit(7)
            raw = json.dumps(entry_fds).encode()
            if len(raw) > 4096:
                raise ValueError("readiness record bound")
            os.write(ready_fd, raw)
            os.close(ready_fd)
            while True:
                client, _ = await loop.sock_accept(listener)
                client.setblocking(False)
                with client:
                    budget.admit()
                    if peer is None:
                        peer = socket.socket(socket.AF_UNIX)
                        peer.setblocking(False)
                        await loop.sock_connect(peer, ENDPOINT)
                    async with asyncio.timeout_at(min(deadline, loop.time() + HANDLER_SECONDS)):
                        requests_seen = 0

                        def seam(event, _raw):
                            nonlocal requests_seen
                            if event == "request":
                                requests_seen += 1
                            if event == fault and (event != "request" or requests_seen > 1):
                                os._exit(7)

                        await forward(client, peer, budget, observe=seam)
                peer.close()
                peer = None
        finally:
            if peer is not None:
                peer.close()


def main():
    listener_fd, ready_fd = map(int, sys.argv[1:3])
    entry_fds = descriptors()
    if set(entry_fds) != {"0", "1", "2", str(listener_fd), str(ready_fd)}:
        raise ValueError("unexpected bridge descriptor")
    if entry_fds["0"] != "/dev/null" or entry_fds["1"] != "/dev/null":
        raise ValueError("bridge inherited payload stdio")
    with socket.socket(fileno=listener_fd) as listener:
        listener.setblocking(False)
        asyncio.run(bridge(listener, ready_fd, float(sys.argv[3]), sys.argv[4], entry_fds))


if __name__ == "__main__":
    main()
