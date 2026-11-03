"""Owned identity for the Pi fixture's single local destination."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from constructicon.core.errors import ContractViolation


class PiPeerRoute:
    """One acquired leaf. Revocation is terminal, even before readiness."""

    def __init__(self, directory: Path) -> None:
        self._path = directory / "pi.sock"
        self._identity: tuple[int, int] | None = None
        self._fd: int | None = None
        self._closed = False

    @staticmethod
    def _identity_of(info: os.stat_result) -> tuple[int, int]:
        if sys.platform != "linux":
            raise ContractViolation("Pi peer sockets require Linux")
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise ContractViolation("Pi peer leaf is not an owned socket")
        return info.st_dev, info.st_ino

    def ready(self, reported: tuple[int, int]) -> None:
        if sys.platform != "linux" or self._closed or self._fd is not None:
            raise ContractViolation("Pi peer route cannot become ready")
        try:
            fd = os.open(self._path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError as exc:
            raise ContractViolation("Pi peer socket unavailable") from exc
        try:
            if self._identity_of(os.fstat(fd)) != reported:
                raise ContractViolation("Pi peer readiness does not identify its acquired socket")
        except BaseException:
            os.close(fd)
            raise
        self._identity, self._fd = reported, fd

    def require_current(self) -> tuple[Path, tuple[int, int]]:
        if self._closed or self._identity is None:
            raise ContractViolation("Pi peer route is not current")
        try:
            current = self._identity_of(self._path.lstat())
        except OSError as exc:
            raise ContractViolation("Pi peer socket unavailable") from exc
        if current != self._identity:
            raise ContractViolation("Pi peer route is not current")
        return self._path, self._identity

    def revoke(self) -> None:
        self._closed = True
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                # A bind mount shares the acquired inode. Deny new connects
                # there even if a worker spawn was already in flight. This
                # magic link identifies the original leaf even after unlink.
                os.chmod(f"/proc/self/fd/{fd}", 0)
            finally:
                os.close(fd)
