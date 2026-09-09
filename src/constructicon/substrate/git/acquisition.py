"""The external revocation fact and physical guard for M8 acquisitions.

The journal remains the inventory and disposition authority. Git revokes an
acquisition permanently; a retained flock inode serializes its physical work.
Neither a directory's absence nor an old process's local phase means closed.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import stat
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from constructicon.core.errors import ContractViolation
from constructicon.substrate.git.authority import GitAuthority, GitAuthorityDamaged


@dataclass(frozen=True)
class AcquisitionPaths:
    """Locators derived from a complete durable acquisition id, never task data."""

    root: Path
    acquisition_id: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"acq-[0-9a-f]{32}", self.acquisition_id) is None:
            raise ContractViolation("invalid acquisition identity")
        if not self.root.is_absolute():
            raise ContractViolation("acquisition root must be absolute")

    @property
    def payload(self) -> Path:
        return self.root / "payloads" / self.acquisition_id

    @property
    def guard(self) -> Path:
        return self.root / "guards" / self.acquisition_id

    @property
    def closure_ref(self) -> str:
        return f"refs/constructicon/acquisition-closed/{self.acquisition_id}"


class AcquisitionClosure:
    """A literal, immutable empty-blob ref, independent of any merge subject."""

    def __init__(self, authority: GitAuthority) -> None:
        self.authority = authority
        algorithm = authority.environment.object_format
        if algorithm not in {"sha1", "sha256"}:
            raise ContractViolation("unsupported Git object format for acquisition closure")
        self.sentinel = hashlib.new(algorithm, b"blob 0\0").hexdigest()

    def is_closed(self, paths: AcquisitionPaths) -> bool:
        symbolic = self.authority._run("symbolic-ref", "--quiet", paths.closure_ref, check=False)
        if symbolic.returncode != 1:
            raise GitAuthorityDamaged("acquisition closure must be a literal object ref")
        result = self.authority._run(
            "rev-parse", "--verify", "--quiet", paths.closure_ref, check=False,
        )
        if result.returncode == 1:
            return False
        if result.returncode != 0 or result.stdout.strip() != self.sentinel:
            raise GitAuthorityDamaged("acquisition closure contradicts the empty-blob sentinel")
        return True

    def require_open(self, paths: AcquisitionPaths) -> None:
        if self.is_closed(paths):
            raise ContractViolation("acquisition is permanently closed")

    def commit(self, paths: AcquisitionPaths) -> None:
        # This is called only for started handles or authoritative durable rows.
        actual = self.authority._run("hash-object", "-w", "--stdin", input_text="").stdout.strip()
        if actual != self.sentinel:
            raise GitAuthorityDamaged("Git produced a different empty-blob sentinel")
        for _ in range(8):
            exists = self.is_closed(paths)
            operation = "verify" if exists else "create"
            result = self.authority._ref_transaction([
                "option no-deref",
                f"{operation} {paths.closure_ref} {self.sentinel}",
            ])
            if result.returncode == 0:
                if not self.is_closed(paths):
                    raise GitAuthorityDamaged("committed acquisition closure disappeared")
                return
        raise ContractViolation("acquisition closure transaction did not converge")


@asynccontextmanager
async def acquisition_guard(paths: AcquisitionPaths) -> AsyncIterator[int]:
    """An async wait on one stable inode; closing our fd never unlocks copies.

    The launcher inherits this open file description. Do not call LOCK_UN:
    it would unlock the supervisor's copy too, including after owner death.
    The retained guard is outside every payload mount and is never removed.
    """

    if sys.platform != "linux":
        raise ContractViolation("physical acquisition guards require Linux")
    import fcntl

    paths.guard.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(paths.guard, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ContractViolation("acquisition guard is not an owned, single-link regular file")
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.01)
        yield fd
    finally:
        os.close(fd)


async def dispose_acquisition(closure: AcquisitionClosure, paths: AcquisitionPaths) -> bool:
    """Revoke before waiting, then remove only quiescent acquisition payloads."""

    closure.commit(paths)
    async with acquisition_guard(paths):
        if not paths.payload.exists() and not paths.payload.is_symlink():
            return False
        if paths.payload.is_symlink():
            raise ContractViolation("acquisition payload root was replaced by a symlink")
        # Linux's fd-based rmtree never follows payload-authored symlinks.
        if not shutil.rmtree.avoids_symlink_attacks:
            raise ContractViolation("symlink-safe acquisition disposal is unavailable")
        shutil.rmtree(paths.payload)
        return True
