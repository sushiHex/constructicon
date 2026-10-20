"""The external revocation fact and physical guard for M8 acquisitions.

The journal remains the inventory and disposition authority. Git revokes an
acquisition permanently; a retained flock inode serializes its physical work.
Neither a directory's absence nor an old process's local phase means closed.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import os
import re
import shutil
import stat
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from constructicon.core.address import GitSha
from constructicon.core.errors import ContractViolation
from constructicon.core.workspace import Disposition
from constructicon.substrate._lifetime import finish_owned
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

    def candidate(self, ref: str) -> GitSha | None:
        """Read a literal candidate, never peel a malformed ref into absence."""

        symbolic = self.authority._run("symbolic-ref", "--quiet", ref, check=False)
        if symbolic.returncode != 1:
            raise GitAuthorityDamaged("candidate must be a literal object ref")
        result = self.authority._run("rev-parse", "--verify", "--quiet", ref, check=False)
        if result.returncode == 1:
            return None
        oid = result.stdout.strip()
        if result.returncode or re.fullmatch(rf"[0-9a-f]{{{len(self.sentinel)}}}", oid) is None:
            raise GitAuthorityDamaged("candidate ref is malformed")
        kind = self.authority._run("cat-file", "-t", oid, check=False)
        if kind.returncode or kind.stdout.strip() != "commit":
            raise GitAuthorityDamaged("candidate ref does not name a commit")
        return GitSha(oid)

    def publish(self, paths: AcquisitionPaths, ref: str, candidate: GitSha) -> None:
        """One external fence: publication cannot occur behind committed closure."""

        for _ in range(8):
            self.require_open(paths)
            current = self.candidate(ref)
            if current is not None and current != candidate:
                raise ContractViolation("candidate ref already pins a different commit")
            operation = "create" if current is None else "verify"
            result = self.authority._ref_transaction([
                "option no-deref",
                f"verify {paths.closure_ref} {'0' * len(self.sentinel)}",
                f"{operation} {ref} {candidate}",
            ])
            if result.returncode == 0:
                return
        raise ContractViolation("candidate publication transaction did not converge")

    def commit(
        self, paths: AcquisitionPaths, *, candidate_ref: str | None = None,
        disposition: Disposition = "discard",
    ) -> None:
        # This is called only for started handles or authoritative durable rows.
        actual = self.authority._run("hash-object", "-w", "--stdin", input_text="").stdout.strip()
        if actual != self.sentinel:
            raise GitAuthorityDamaged("Git produced a different empty-blob sentinel")
        for _ in range(8):
            exists = self.is_closed(paths)
            operation = "verify" if exists else "create"
            commands = [
                "option no-deref",
                f"{operation} {paths.closure_ref} {self.sentinel}",
            ]
            if candidate_ref is not None:
                candidate = self.candidate(candidate_ref)
                if disposition == "discard" and candidate is not None:
                    commands.append(f"delete {candidate_ref} {candidate}")
                else:
                    # Even absence is verified inside the transaction: a publisher
                    # may have won since this read, and closure must retry as a whole.
                    observed = candidate or "0" * len(self.sentinel)
                    commands.append(f"verify {candidate_ref} {observed}")
            result = self.authority._ref_transaction(commands)
            if result.returncode == 0:
                if not self.is_closed(paths):
                    raise GitAuthorityDamaged("committed acquisition closure disappeared")
                return
        raise ContractViolation("acquisition closure transaction did not converge")


@dataclass(frozen=True)
class _AcquisitionNamespace:
    root_fd: int
    guards_fd: int
    payloads_fd: int | None


def _open_child_directory(parent: int, name: str, *, create: bool = False) -> int:
    if sys.platform != "linux":
        raise ContractViolation("physical acquisition directories require Linux")
    if create:
        with suppress(FileExistsError):
            os.mkdir(name, mode=0o700, dir_fd=parent)
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                       dir_fd=parent)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ContractViolation(
                "acquisition namespace must contain real directories",
            ) from error
        raise


@contextmanager
def _acquisition_namespace(paths: AcquisitionPaths) -> Iterator[_AcquisitionNamespace]:
    """Pin no-follow directory descriptions before any awaited physical work.

    These descriptors prevent later pathname replacement from redirecting our
    guard or removal operations. They do not defend arbitrary guard-file changes
    by a malicious same-UID process with general filesystem access.
    """

    if sys.platform != "linux":
        raise ContractViolation("physical acquisition guards require Linux")
    if any(part in (".", "..") for part in paths.root.parts[1:]):
        raise ContractViolation("acquisition namespace requires a canonical root")
    with ExitStack() as owned:
        current = os.open(paths.root.anchor,
                          os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        owned.callback(os.close, current)
        for part in paths.root.parts[1:]:
            current = _open_child_directory(current, part, create=True)
            owned.callback(os.close, current)
        guards = _open_child_directory(current, "guards", create=True)
        owned.callback(os.close, guards)
        try:
            payloads = _open_child_directory(current, "payloads")
        except FileNotFoundError:
            payloads = None
        if payloads is not None:
            owned.callback(os.close, payloads)
        yield _AcquisitionNamespace(current, guards, payloads)


@asynccontextmanager
async def _guard_at_namespace(paths: AcquisitionPaths,
                              namespace: _AcquisitionNamespace) -> AsyncIterator[int]:
    if sys.platform != "linux":
        raise ContractViolation("physical acquisition guards require Linux")
    import fcntl

    fd = os.open(paths.acquisition_id, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
                 0o600, dir_fd=namespace.guards_fd)
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


@asynccontextmanager
async def acquisition_guard(paths: AcquisitionPaths) -> AsyncIterator[int]:
    """Wait on a pinned guard inode; close never unlocks inherited descriptions."""

    with _acquisition_namespace(paths) as namespace:
        async with _guard_at_namespace(paths, namespace) as guard:
            yield guard


def _remove_at_namespace(paths: AcquisitionPaths, namespace: _AcquisitionNamespace) -> bool:
    """Runs only inside the joined worker, with directory custody still retained."""

    with ExitStack() as owned:
        payloads = namespace.payloads_fd
        if payloads is None:
            try:
                payloads = _open_child_directory(namespace.root_fd, "payloads")
            except FileNotFoundError:
                return False
            owned.callback(os.close, payloads)
        try:
            info = os.stat(paths.acquisition_id, dir_fd=payloads, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if not stat.S_ISDIR(info.st_mode):
            raise ContractViolation("acquisition payload root must be a real directory")
        if not shutil.rmtree.avoids_symlink_attacks:
            raise ContractViolation("symlink-safe acquisition disposal is unavailable")
        shutil.rmtree(paths.acquisition_id, dir_fd=payloads)
        return True


async def dispose_acquisition(
    closure: AcquisitionClosure, paths: AcquisitionPaths, *,
    candidate_ref: str | None = None, disposition: Disposition = "discard",
) -> bool:
    """Revoke before waiting, then remove only quiescent acquisition payloads."""

    with _acquisition_namespace(paths) as namespace:
        await finish_owned(asyncio.create_task(asyncio.to_thread(
            closure.commit, paths, candidate_ref=candidate_ref, disposition=disposition,
        )))
        async with _guard_at_namespace(paths, namespace):
            # Cancellation cannot release custody while this worker still has
            # filesystem authority. It only removes the acquisition-relative tree.
            return await finish_owned(asyncio.create_task(asyncio.to_thread(
                _remove_at_namespace, paths, namespace,
            )))
