"""Immutable, bounded Git packs cross from containment into trusted metadata.

Git validates objects and their closure; Python checks only the pack framing
and resource bounds. No stage path, configuration, refspec, or object-store
locator is accepted here. Quarantines stay outside every payload mount.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

from constructicon.core.address import GitSha
from constructicon.core.errors import ContractViolation
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.git.authority import GitAuthority, _remove_tree
from constructicon.substrate.git.process import GitProcess


@dataclass(frozen=True)
class PackLimits:
    objects: int = 100_000
    expanded_bytes: int = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        values = (self.objects, self.expanded_bytes)
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("Git pack limits must be positive integers")


def commit_oid(raw: bytes, algorithm: str) -> GitSha:
    size = hashlib.new(algorithm).digest_size * 2
    if re.fullmatch(rb"[0-9a-f]{" + str(size).encode() + rb"}\n?", raw) is None:
        raise ContractViolation("capture did not name one exact commit OID")
    return GitSha(raw.decode("ascii").removesuffix("\n"))


async def import_pack(
    authority: GitAuthority, git: GitProcess, *, acquisition_root: Path,
    candidate: GitSha, pack: bytes, limits: PackLimits, guard: int | None,
) -> None:
    """Verify in a fresh owned quarantine, then import those exact immutable bytes.

    Publication is deliberately separate: only the acquisition's external
    closure transaction can give these already-verified objects a candidate ref.
    """

    if type(pack) is not bytes:
        raise ContractViolation("Git handoff requires immutable bytes")
    algorithm = authority.environment.object_format
    candidate = commit_oid(str(candidate).encode(), algorithm)
    hash_bytes = hashlib.new(algorithm).digest_size
    if not 12 + hash_bytes <= len(pack) <= git.limits.artifact_bytes:
        raise ContractViolation("Git pack is truncated or exceeds the artifact bound")
    magic, version, count = struct.unpack("!4sII", pack[:12])
    if magic != b"PACK" or version not in (2, 3) or not 0 < count <= limits.objects:
        raise ContractViolation("Git pack framing or object count is invalid")
    checksum = hashlib.new(algorithm, pack[:-hash_bytes]).digest()
    if checksum != pack[-hash_bytes:]:
        raise ContractViolation("Git pack checksum differs from its immutable bytes")
    quarantine = Path(tempfile.mkdtemp(prefix="quarantine-", dir=acquisition_root))
    try:
        await git.run(
            "init", "--bare", "--template=", f"--object-format={algorithm}",
            cwd=quarantine, guard=guard,
        )
        indexed = await git.run(
            "index-pack", "--stdin", "--strict", "--threads=1",
            f"--max-input-size={git.limits.artifact_bytes}",
            cwd=quarantine, stdin=pack, guard=guard,
        )
        if indexed != b"pack\t" + checksum.hex().encode() + b"\n":
            raise ContractViolation("Git did not consume the exact self-contained pack")
        kind = await git.run("cat-file", "-t", candidate, cwd=quarantine, guard=guard)
        if kind != b"commit\n":
            raise ContractViolation("candidate OID is not a commit in the verified pack")
        await git.run(
            "fsck", "--strict", "--full", "--no-reflogs", "--no-dangling", candidate,
            cwd=quarantine, guard=guard,
        )
        sizes = await git.run(
            "cat-file", "--batch-all-objects", "--batch-check=%(objectsize)",
            cwd=quarantine, guard=guard,
        )
        rows = sizes.splitlines()
        if len(rows) != count or any(not row.isdigit() for row in rows):
            raise ContractViolation("Git pack object inventory contradicts its framing")
        if sum(int(row) for row in rows) > limits.expanded_bytes:
            raise ContractViolation("Git pack exceeds the expanded-object bound")
        await git.run(
            "index-pack", "--stdin", "--strict", "--threads=1",
            f"--max-input-size={git.limits.artifact_bytes}",
            cwd=authority.repository_id, stdin=pack, guard=guard,
        )
    finally:
        await finish_owned(asyncio.create_task(asyncio.to_thread(_remove_tree, quarantine)))
