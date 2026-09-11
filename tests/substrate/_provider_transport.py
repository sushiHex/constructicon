"""Bounded test IPC, shared by the host peer and immutable byte bridge.

Stdlib only: this exact file is copied into the test image. No provider,
process ownership, routing, or authentication decisions belong here.
"""

import array
import asyncio
import os
import socket
from dataclasses import dataclass

CONNECTIONS = 2
HEADERS = 256 * 1024
BODY = 1024 * 1024
TOTAL = 4 * 1024 * 1024
CHUNK = 8192
CASE_SECONDS = 20
HANDLER_SECONDS = 10
ENDPOINT = "/opt/native-startup/provider.sock"


@dataclass
class Budget:
    connections: int = 0
    total: int = 0

    def admit(self):
        self.connections += 1
        if self.connections > CONNECTIONS:
            raise ValueError("connection bound")

    def charge(self, count):
        self.total += count
        if self.total > TOTAL:
            raise ValueError("aggregate byte bound")


async def receive(sock, count=CHUNK):
    """SCM_RIGHTS must be closed, not silently discarded by a stream wrapper."""
    loop = asyncio.get_running_loop()
    if not hasattr(sock, "recvmsg") or sock.family != socket.AF_UNIX:
        return await loop.sock_recv(sock, min(CHUNK, count))
    while True:
        try:
            data, ancillary, flags, _ = sock.recvmsg(min(CHUNK, count), socket.CMSG_SPACE(1024))
        except BlockingIOError:
            ready = loop.create_future()
            loop.add_reader(sock.fileno(), lambda r=ready: not r.done() and r.set_result(None))
            try:
                await ready
            finally:
                loop.remove_reader(sock.fileno())
            continue
        for level, kind, raw in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                fds = array.array("i")
                fds.frombytes(raw[:len(raw) - len(raw) % fds.itemsize])
                for fd in fds:
                    os.close(fd)
        if ancillary or flags & socket.MSG_CTRUNC:
            raise ValueError("ancillary transfer refused")
        return data


async def read(sock, budget, count=CHUNK):
    raw = await receive(sock, min(count, TOTAL - budget.total + 1))
    budget.charge(len(raw))
    return raw


async def write(sock, budget, raw):
    budget.charge(len(raw))
    await asyncio.get_running_loop().sock_sendall(sock, raw)


async def forward(left, right, budget, *, observe=None):
    """Each byte counts once at the bridge; EOF does not discard the other half."""
    async def copy(source, destination):
        while raw := await read(source, budget):
            if observe is not None:
                observe("request" if source is left else "response", raw)
            await asyncio.get_running_loop().sock_sendall(destination, raw)
        if observe is not None:
            observe("request_eof" if source is left else "response_eof", b"")
        destination.shutdown(socket.SHUT_WR)

    async with asyncio.TaskGroup() as group:
        group.create_task(copy(left, right))
        group.create_task(copy(right, left))
