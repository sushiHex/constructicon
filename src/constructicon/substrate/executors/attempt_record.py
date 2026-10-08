"""The one attempt record of a read authorization (M8 N5 Stage 3, decision S3-1).

One file accounts for the authorization's one attempt and outlives a journal
reset. It moves through three phases, each written whole and made durable
(the file and its directory are fsynced) before anything depends on it:
- **acquired.** It is created exclusively at `acquire`, so a second
  acquisition, before or after a journal reset, finds it and refuses. This
  phase alone proves nothing was dispatched.
- **intent.** It is written immediately before `turn/start` reaches the native
  client. From here, a death means "possibly dispatched".
- **outcome.** Exactly one of "completed", "not dispatched" or "possibly
  dispatched", with bounded facts and no text.

It is one record per authorization, not an executor ledger (ADR 0018:331-332),
which the owner set aside for this one artifact. Deleting it is outside the
threat model: the runtime is not an adversary of its own budget (ADR
0021:157-158).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from constructicon.core.errors import ContractViolation

Dispatch = Literal["completed", "not dispatched", "possibly dispatched"]
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class AttemptRecord:
    """The record at one path, from its exclusive reservation on."""

    def __init__(self, path: Path, identity: Mapping[str, Any]) -> None:
        self.path = path
        self._identity = dict(identity)

    @classmethod
    def reserve(cls, path: Path, identity: Mapping[str, Any]) -> AttemptRecord:
        """Create the record, or refuse: the authorization's one attempt is spent."""
        record = cls(path, identity)
        try:
            record._write(path, {"phase": "acquired"})
        except FileExistsError as exc:
            raise ContractViolation("the authorization's one attempt is spent") from exc
        return record

    def intend(self) -> str | None:
        """Record the intent to dispatch; a refusal, never a raise, if it cannot."""
        try:
            self._replace({"phase": "intent"})
        except OSError as exc:
            return f"the attempt record could not record intent: {exc.strerror}"
        return None

    def complete(self, dispatch: Dispatch, facts: Mapping[str, Any]) -> None:
        self._replace({"phase": "outcome", "dispatch": dispatch, "facts": dict(facts)})

    def _replace(self, content: Mapping[str, Any]) -> None:
        following = self.path.with_name(self.path.name + ".next")
        self._write(following, content)
        os.replace(following, self.path)
        self._sync_directory()

    def _write(self, path: Path, content: Mapping[str, Any]) -> None:
        body = {**self._identity, **content, "at": datetime.now(UTC).isoformat()}
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_CLOEXEC | _O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, (json.dumps(body, sort_keys=True) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        self._sync_directory()

    def _sync_directory(self) -> None:
        if os.name != "posix":
            return  # directory fsync exists only on POSIX; the host is Linux
        fd = os.open(self.path.parent, os.O_RDONLY | _O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
