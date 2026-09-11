"""A scoped byte conversation, never process or execution authority."""

from __future__ import annotations

from typing import Protocol


class ProcessIO(Protocol):
    """One reader and writer; the owning launcher bounds and ends the scope.

    Reads return available bytes promptly, not necessarily a complete message.
    Only actual EOF returns empty bytes. Writes spend a cumulative input budget
    before delivery and cannot be retried automatically after interruption.
    No operation remains valid after the conversation scope ends.
    """

    async def write(self, data: bytes) -> None: ...

    async def read(self, maximum: int = 8192) -> bytes: ...

    async def close_stdin(self) -> None: ...
