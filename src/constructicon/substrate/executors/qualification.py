"""Reading the owner's qualification authorization (M8 N5 Stage 1).

The authorization is operator configuration, so its only source is a file the
owner wrote as root: ``0640 root:<service group>``, single-linked, under a
chain of root-owned directories nobody else can write, every one opened
without following a symlink. The unprivileged runtime reads it through its
group and can neither write, replace nor redirect it. There is no other
reader here: CI's fixture authorizations are built by tests, never parsed.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from pydantic import ValidationError

from constructicon.core.errors import ContractViolation
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors import operator_store

MAX_AUTHORIZATION_BYTES = 8192
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_UNAVAILABLE = "the qualification authorization is unavailable"


def read_authorization(path: Path) -> QualificationAuthorization:
    """The owner's authorization, or a refusal that discloses nothing about why."""

    if sys.platform != "linux" or not path.is_absolute() or ".." in path.parts:
        raise ContractViolation(_UNAVAILABLE)
    try:
        # Every ancestor: root-owned, unwritable by group and others, no symlink.
        directory = operator_store._open_trusted_directory(path.parent)
        try:
            fd = os.open(
                path.name,
                os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC | _O_NONBLOCK,
                dir_fd=directory,
            )
        finally:
            os.close(directory)
        try:
            info = os.fstat(fd)
            if (
                info.st_nlink != 1
                or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) != 0o640
            ):
                raise ContractViolation(_UNAVAILABLE)
            raw = os.read(fd, MAX_AUTHORIZATION_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > MAX_AUTHORIZATION_BYTES:
            raise ContractViolation(_UNAVAILABLE)
        return QualificationAuthorization.model_validate_json(raw)
    except (ContractViolation, OSError, ValidationError, ValueError) as exc:
        raise ContractViolation(_UNAVAILABLE) from exc
