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

import errno
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from constructicon.core.errors import ContractViolation
from constructicon.core.qualification_write import CallbackObservation

Dispatch = Literal["completed", "not dispatched", "possibly dispatched"]
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class AttemptRecord:
    """The record at one path, from its exclusive reservation on."""

    def __init__(self, path: Path, identity: Mapping[str, Any]) -> None:
        self.path = path
        self._identity = dict(identity)
        self.callbacks: CallbackObservation | None = None
        self._callback_failed = False
        self._phase = "acquired"

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
            if self.callbacks is not None:
                self._callback_failed = True
            return f"the attempt record could not record intent: {exc.strerror}"
        self._phase = "intent"
        return None

    def complete(self, dispatch: Dispatch, facts: Mapping[str, Any]) -> None:
        if self._callback_failed:
            return  # Preserve the surviving partial snapshot, even after rename/fsync failure.
        self._replace({"phase": "outcome", "dispatch": dispatch, "facts": dict(facts)})
        self._phase = "outcome"

    def enable_callbacks(self) -> None:
        """Affirm zero without moving the acquired reservation into dispatch intent."""
        if self.callbacks is not None or self._phase != "acquired":
            raise ContractViolation("callback observations require a fresh acquisition")
        self._observe(CallbackObservation(
            schema_version=1, admitted_started=0, admitted_completed=0, worker_results=(),
        ))

    def observe_callbacks(self, observation: CallbackObservation) -> None:
        previous = self.callbacks
        if previous is None or self._phase != "intent" or (
            observation.admitted_started < previous.admitted_started
            or observation.admitted_completed < previous.admitted_completed
            or any(old is not None and old != new for old, new in zip(
                previous.worker_results, observation.worker_results,
                strict=False,
            ))
        ):
            raise ContractViolation("callback observations cannot retract retained facts")
        self._observe(observation)

    def _observe(self, observation: CallbackObservation) -> None:
        if self._callback_failed:
            raise ContractViolation("callback observations could not be retained")
        self.callbacks = observation
        try:
            self._replace({"phase": self._phase})
        except OSError as exc:
            self._callback_failed = True
            raise ContractViolation("callback observations could not be retained") from exc

    def _replace(self, content: Mapping[str, Any]) -> None:
        if self.callbacks is not None:
            content = {**content, "callbacks": self.callbacks.model_dump(mode="json")}
        following = self.path.with_name(self.path.name + ".next")
        self._write(following, content)
        os.replace(following, self.path)
        self._sync_directory()

    def _write(self, path: Path, content: Mapping[str, Any]) -> None:
        body = {**self._identity, **content, "at": datetime.now(UTC).isoformat()}
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_CLOEXEC | _O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            pending = memoryview((json.dumps(body, sort_keys=True) + "\n").encode("utf-8"))
            while pending:
                written = os.write(fd, pending)
                if written <= 0:
                    raise OSError(errno.EIO, "the attempt record made no progress")
                pending = pending[written:]
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
