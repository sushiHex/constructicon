"""Fixed-endpoint byte transport, a descendant of the existing owner.

No reaper, retry, URL parser, or provider protocol. Its exit is deliberately
not a separate supervisor observation. This file runs only in a test image.
"""

import asyncio
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _provider_transport import (
    ENDPOINT,
    HANDLER_SECONDS,
    Budget,
    forward,
)


async def bridge(listener, ready_fd, deadline, fault):
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
            os.write(ready_fd, b"R")
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
                        def seam(event, _raw):
                            if event == fault:
                                os._exit(7)

                        await forward(client, peer, budget, observe=seam)
                peer.close()
                peer = None
        finally:
            if peer is not None:
                peer.close()


def main():
    listener_fd, ready_fd = map(int, sys.argv[1:3])
    with socket.socket(fileno=listener_fd) as listener:
        listener.setblocking(False)
        asyncio.run(bridge(listener, ready_fd, float(sys.argv[3]), sys.argv[4]))


if __name__ == "__main__":
    main()
