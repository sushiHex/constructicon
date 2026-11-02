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

    @property
    def stdout_bytes_received(self) -> int:
        """Instant cumulative captured stdout, including unread buffered bytes.

        This observes the launcher's capture buffer, not bytes still in an OS
        pipe or future producer output. Consuming reads never reduces the count.
        """
        ...

    @property
    def stdout_eof_received(self) -> bool:
        """Whether stdout EOF has been captured, even with unread buffered bytes.

        Once true, it stays true and the captured byte count cannot increase.
        """
        ...

    async def write(self, data: bytes) -> None: ...

    async def read(self, maximum: int = 8192) -> bytes: ...

    async def close_stdin(self) -> None: ...
