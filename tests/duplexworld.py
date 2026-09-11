"""A genuine scripted byte-channel double, not simulated Linux ownership."""

import asyncio
import hashlib

from constructicon.core.errors import ContractViolation


class ScriptedIO:
    def __init__(self):
        self.challenge = b"scripted-challenge"
        self.history = self.challenge + b"\n"
        self.pending = bytearray(self.history)
        self.answer = bytearray()
        self.closed = False
        self.active = True
        self.changed = asyncio.Event()
        self.reading = False

    def require_active(self):
        if not self.active:
            raise ContractViolation("scripted conversation closed")

    async def write(self, data):
        self.require_active()
        if self.closed or not isinstance(data, bytes) or len(self.answer) + len(data) > 1024 * 1024:
            raise ContractViolation("scripted input refused")
        self.answer.extend(data)
        if data and self.answer.endswith(b"\n"):
            assert self.answer == hashlib.sha256(self.challenge).hexdigest().encode() + b"\n"
            self.pending.extend(b"confirmed\n")
            self.history += b"confirmed\n"
            self.changed.set()

    async def read(self, maximum=8192):
        self.require_active()
        if type(maximum) is not int or not 1 <= maximum <= 8192 or self.reading:
            raise ContractViolation("scripted read refused")
        self.reading = True
        try:
            while not self.pending and not self.closed:
                self.changed.clear()
                await self.changed.wait()
                self.require_active()
            value = bytes(self.pending[:maximum])
            del self.pending[:maximum]
            return value
        finally:
            self.reading = False

    async def close_stdin(self):
        self.require_active()
        self.closed = True
        self.changed.set()

    def invalidate(self):
        self.active = False
        self.changed.set()
