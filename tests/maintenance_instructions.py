"""The committed maintenance instructions, exactly as a base commit holds them.

Product code reads these from the pinned base in its private authority and pins
their digest in the request (docs/designs/INSTRUCTION_BINDING.md). Tests read the
working copy, which ``.gitattributes`` keeps byte-identical to the blob.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from constructicon.core.maintenance import instruction_path

ROOT = Path(__file__).resolve().parents[1]
PLAN_PURPOSE = "plan-manifest-maintenance"
CHANNEL_PURPOSE = "channel-stored-reply"


def instruction_bytes(purpose: str) -> bytes:
    raw = (ROOT / instruction_path(purpose)).read_bytes()
    assert b"\r" not in raw, "the instruction must be checked out with LF endings"
    return raw


def instruction(purpose: str) -> str:
    return instruction_bytes(purpose).decode("utf-8")


def instruction_sha256(purpose: str) -> str:
    return hashlib.sha256(instruction_bytes(purpose)).hexdigest()


def fast_import_entry(purpose: str) -> bytes:
    """One ``git fast-import`` file command adding this task's instruction to a commit."""
    raw = instruction_bytes(purpose)
    return (f"M 100644 inline {instruction_path(purpose)}\ndata {len(raw)}\n".encode()
            + raw + b"\n")


def pinned(purpose: str) -> dict[str, object]:
    """The request fields of the era that pins this task's committed instruction."""
    return {"schema_version": 2, "instruction_sha256": instruction_sha256(purpose)}


async def commit_instruction(git_executable: str, repository, ref: str, purpose: str) -> str:
    """Move ``ref`` to a parentless copy of its tree that also holds the instruction.

    Synthetic bases hold only their task's files; a base commit must also hold
    the instruction its request pins. A tree that already has it is left alone.
    """
    from constructicon.substrate.executors.linux import ProcessLimits
    from constructicon.substrate.git.process import GitProcess

    git = GitProcess(git_executable, ProcessLimits())

    async def run(*args: str, stdin: bytes = b"") -> bytes:
        return await git.run(*args, cwd=repository, stdin=stdin)

    base = (await run("rev-parse", "--verify", ref)).strip().decode()
    if await run("ls-tree", base, "--", instruction_path(purpose)):
        return base
    top = await run("ls-tree", base)
    assert b"\tmaintenance\n" not in top
    blob = (await run("hash-object", "-w", "--stdin",
                      stdin=instruction_bytes(purpose))).strip().decode()
    directory, name = instruction_path(purpose).split("/")
    sub = (await run("mktree", stdin=f"100644 blob {blob}\t{name}\n".encode())).strip().decode()
    tree = (await run("mktree",
                      stdin=top + f"040000 tree {sub}\t{directory}\n".encode())).strip().decode()
    commit = (await run("commit-tree", tree,
                        stdin=b"base with its task instruction\n")).strip().decode()
    await run("update-ref", ref, commit)
    return commit


WRITE_INSTRUCTION = instruction(PLAN_PURPOSE)
CHANNEL_INSTRUCTION = instruction(CHANNEL_PURPOSE)
# Both tasks open with the same paragraph about the one tool and its limits.
TOOL_PREFIX = WRITE_INSTRUCTION[: WRITE_INSTRUCTION.index("\n\n") + 2]
