"""The model's side of one maintenance attempt, kept as text on the private host.

One file beside the attempt record holds what the attempt record may not: each
callback program handed to the worker, in order, and the message its turn completed
with. It is written in the one format a recorded turn replays from
(``tests/model_seat.py``, ``Turn``, record version 1), so a failed live attempt
becomes an offline case without a second format:

    {"version": 1, "calls": [{"program": str, "seen": {"sha256", "bytes"} | null}],
     "completed": bool, "reply": str | null}

``seen`` is the digest and length of the output the model was handed for that
call, and null when nothing came back; only the last call may lack one. Output
text is not kept: a replay regenerates it and compares digests. ``completed``
says the turn's terminal record arrived, and ``reply`` is that turn's output
text; a turn that never completed has none.

The file is replaced whole and made durable at every step, so a death leaves the
exact prefix that was exchanged, in order. It is model-authored text and may
quote anything the worker could read in the workspace. It therefore never enters
the journal, the attempt record, a diagnostic or a report. Its only protection is
the custody the attempt record already has: the private maintenance root, mode
0600.

Retention never fails the attempt it describes. Anything that cannot be kept
exactly (a write failure, a bound, an existing file, a step out of order) clears
``intact`` and stops further writes; nothing is truncated to fit.
"""

from __future__ import annotations

import errno
import json
import os
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from constructicon.core.attempt_content import ContentDigest
from constructicon.substrate.executors.codex_protocol import (
    MAX_TOOL_CALLS,
    RECORD_BYTES,
    TOOL_PROGRAM_BYTES,
)

VERSION = 1
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def turn_path(attempt_record: Path) -> Path:
    """The turn's file for one attempt record: its sibling, under the same custody."""
    return attempt_record.with_name(attempt_record.stem + ".turn.json")


class TurnRecord:
    """The turn at one path, from its exclusive creation on."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.intact = True
        self._calls: list[dict[str, Any]] = []
        self._completed = False
        self._reply: str | None = None

    @classmethod
    def reserve(cls, path: Path) -> TurnRecord:
        """Create the empty turn. An existing file is left alone and nothing is kept."""
        record = cls(path)
        record._publish(os.link)
        return record

    def program(self, text: str) -> None:
        """One program the model sent, before anything runs it."""
        if (
            self._completed or len(self._calls) >= MAX_TOOL_CALLS
            or (self._calls and self._calls[-1]["seen"] is None)
            or _oversized(text, TOOL_PROGRAM_BYTES)
        ):
            self.intact = False
        if self.intact:
            self._calls.append({"program": text, "seen": None})
            self._replace()

    def seen(self, index: int, output: ContentDigest | None) -> None:
        """The output the model was handed for call ``index``, by digest."""
        if output is None or self._completed or not (
            0 <= index == len(self._calls) - 1 and self._calls[index]["seen"] is None
        ):
            self.intact = False
        if self.intact:
            assert output is not None
            self._calls[index]["seen"] = {"sha256": output.sha256, "bytes": output.bytes}
            self._replace()

    def complete(self, reply: str | None) -> None:
        """The turn's terminal record arrived, with this output text or none.

        The ceiling can only catch a caller's error. A reply is one JSON string in
        one inbound record, and the framer keeps every record under
        ``RECORD_BYTES`` (``codex_protocol.py``, ``RecordStream.feed``; the text is
        read by ``_message_text`` for ``observe_turn``). A JSON string never
        encodes to fewer bytes than its UTF-8 text.
        """
        if reply is not None and _oversized(reply, RECORD_BYTES):
            self.intact = False
        if self.intact and not (self._completed and reply == self._reply):
            self._completed, self._reply = True, reply
            self._replace()

    def _replace(self) -> None:
        self._publish(os.replace)

    def _publish(self, place: Callable[[Path, Path], None]) -> None:
        """Write the whole turn beside its path, then put it there in one step.

        ``os.link`` places the first copy and refuses an existing file;
        ``os.replace`` places each later one. Either way the path only ever names
        a complete document. The sibling is removed again unless a rename took it;
        a death or a failed removal can leave it, holding the same text under the
        same custody, and nothing reads it.
        """
        following = self.path.with_name(self.path.name + ".next")
        created = False
        try:
            body = json.dumps(
                {"version": VERSION, "calls": self._calls, "completed": self._completed,
                 "reply": self._reply},
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_CLOEXEC | _O_NOFOLLOW
            fd = os.open(following, flags, 0o600)
            created = True
            try:
                pending = memoryview(body)
                while pending:
                    written = os.write(fd, pending)
                    if written <= 0:
                        raise OSError(errno.EIO, "the turn record made no progress")
                    pending = pending[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            place(following, self.path)
            _sync_directory(self.path.parent)
        except (OSError, ValueError):
            self.intact = False
        if created and (place is os.link or not self.intact):
            with suppress(OSError):
                os.unlink(following)


def _oversized(text: str, ceiling: int) -> bool:
    # Four bytes is the most one code point encodes to, so most text never encodes here.
    return len(text) > ceiling or (
        len(text) * 4 > ceiling and len(text.encode("utf-8", errors="surrogatepass")) > ceiling
    )


def _sync_directory(directory: Path) -> None:
    if os.name != "posix":
        return  # directory fsync exists only on POSIX; the host is Linux
    fd = os.open(directory, os.O_RDONLY | _O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
