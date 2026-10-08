"""Reading the owner's qualification authorization (M8 N5 Stage 1).

The authorization is operator configuration, so its only source is a file the
owner wrote as root: ``0640 root:<service group>`` in a root-owned directory
nobody else can write. The unprivileged runtime reads it through its group and
can neither write nor replace it. Anything else, a runtime-owned or writable
file, a link or a symlink, is not an owner's authorization. There is no other
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

MAX_AUTHORIZATION_BYTES = 8192
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_UNAVAILABLE = "the qualification authorization is unavailable"


def read_authorization(path: Path) -> QualificationAuthorization:
    """The owner's authorization, or a refusal that discloses nothing about why."""

    if sys.platform != "linux" or not path.is_absolute() or ".." in path.parts:
        raise ContractViolation(_UNAVAILABLE)
    try:
        directory = os.open(path.parent, os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC)
        try:
            parent = os.fstat(directory)
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
                parent.st_uid != 0
                or stat.S_IMODE(parent.st_mode) & 0o022
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != 0
                or info.st_gid != os.getegid()
                or stat.S_IMODE(info.st_mode) != 0o640
                or info.st_size > MAX_AUTHORIZATION_BYTES
            ):
                raise ContractViolation(_UNAVAILABLE)
            raw = os.read(fd, MAX_AUTHORIZATION_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > MAX_AUTHORIZATION_BYTES:
            raise ContractViolation(_UNAVAILABLE)
        return QualificationAuthorization.model_validate_json(raw)
    except (OSError, ValidationError, ValueError) as exc:
        raise ContractViolation(_UNAVAILABLE) from exc
