"""Real Git verifies immutable handoffs; these tests claim no OS containment."""

from __future__ import annotations

import hashlib
import shutil
import struct
from dataclasses import replace

import pytest

from constructicon.core.address import GitSha
from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.pack import PackLimits, commit_oid, import_pack
from constructicon.substrate.git.process import GitProcess
from tests.gitworld import push_to_main, seed_authority

DEFAULT_PACK_LIMITS = PackLimits()


@pytest.fixture
async def handoff(tmp_path):
    source_root, destination_root = tmp_path / "source", tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    source = seed_authority(source_root)
    candidate = push_to_main(source, {"candidate.txt": "a separate candidate\n"}, "candidate")
    destination = GitAuthority(
        seed_authority(destination_root, {"target.txt": "unrelated history\n"}),
        destination_root / "legacy",
    )
    git = GitProcess(shutil.which("git"), ProcessLimits())
    content = await git.run(
        "pack-objects",
        "--stdout",
        "--revs",
        cwd=source,
        stdin=f"{candidate}\n".encode(),
    )
    root = tmp_path / "acquisition"
    root.mkdir()
    return source, destination, git, root, candidate, content


async def receive(handoff, *, content=None, candidate=None, limits=DEFAULT_PACK_LIMITS, git=None):
    _, authority, original_git, root, expected, original_content = handoff
    await import_pack(
        authority,
        git or original_git,
        acquisition_root=root,
        candidate=candidate or expected,
        pack=original_content if content is None else content,
        limits=limits,
        guard=None,
    )


async def test_verified_pack_preserves_exact_commit_history_without_moving_any_ref(handoff):
    source, authority, git, root, candidate, content = handoff
    refs = authority._run("show-ref").stdout
    assert authority._run("cat-file", "-e", candidate, check=False).returncode != 0
    await receive(handoff)
    await receive(handoff)  # Immutable import is an exact retry, not another commit.
    assert authority._run("show-ref").stdout == refs
    for args in (("cat-file", "commit", candidate), ("rev-list", "--objects", candidate)):
        expected = await git.run(*args, cwd=source)
        assert expected == await git.run(*args, cwd=authority.repository_id)
    assert list(root.iterdir()) == []
    assert content.startswith(b"PACK")


@pytest.mark.parametrize(
    "damage", ["truncated", "checksum", "magic", "version", "count", "trailer"]
)
async def test_invalid_pack_framing_never_enters_the_authority(handoff, damage):
    _, authority, _, root, candidate, original = handoff
    raw = bytearray(original)
    if damage == "truncated":
        raw = raw[:10]
    elif damage == "checksum":
        raw[-1] ^= 1
    elif damage == "magic":
        raw[:4] = b"FAKE"
    elif damage == "version":
        raw[4:8] = struct.pack("!I", 99)
    elif damage == "count":
        raw[8:12] = struct.pack("!I", 100_001)
    else:
        raw += b"trailing bytes"
    with pytest.raises(ContractViolation):
        await receive(handoff, content=bytes(raw))
    assert authority._run("cat-file", "-e", candidate, check=False).returncode != 0
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("limit", ["artifact", "objects", "expanded"])
async def test_pack_resource_bounds_are_enforced_before_authority_import(handoff, limit):
    _, authority, git, root, candidate, content = handoff
    selected = PackLimits()
    if limit == "artifact":
        git = replace(git, limits=replace(git.limits, artifact_bytes=len(content) - 1))
    elif limit == "objects":
        selected = PackLimits(objects=1)
    else:
        selected = PackLimits(expanded_bytes=1)
    with pytest.raises(ContractViolation):
        await receive(handoff, limits=selected, git=git)
    assert authority._run("cat-file", "-e", candidate, check=False).returncode != 0
    assert list(root.iterdir()) == []


async def test_correctly_checksummed_broken_objects_are_rejected_by_git(handoff):
    # Keep framing/checksum valid while breaking the first compressed object.
    _, authority, _, root, candidate, content = handoff
    raw = bytearray(content)
    raw[13] ^= 255
    raw[-20:] = hashlib.sha1(raw[:-20]).digest()
    with pytest.raises(ContractViolation, match="trusted Git index-pack failed"):
        await receive(handoff, content=bytes(raw))
    assert authority._run("cat-file", "-e", candidate, check=False).returncode != 0
    assert list(root.iterdir()) == []


async def test_pack_must_carry_the_named_commit_not_an_object_in_the_authority(handoff):
    _, authority, _, root, candidate, _ = handoff
    # The destination has this commit. The fresh quarantine deliberately does not.
    other = authority.resolve_ref("refs/heads/main")
    with pytest.raises(ContractViolation):
        await receive(handoff, candidate=other)
    assert authority._run("cat-file", "-e", candidate, check=False).returncode != 0
    assert list(root.iterdir()) == []


async def test_export_with_omitted_history_is_not_repaired_from_another_object_store(handoff):
    source, authority, git, root, candidate, _ = handoff
    parent = (await git.run("rev-parse", f"{candidate}^", cwd=source)).decode().strip()
    incomplete = await git.run(
        "pack-objects",
        "--stdout",
        "--revs",
        cwd=source,
        stdin=f"{candidate}\n^{parent}\n".encode(),
    )
    with pytest.raises(ContractViolation):
        await receive(handoff, content=incomplete)
    assert authority._run("cat-file", "-e", candidate, check=False).returncode != 0
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("raw", [b"", b"HEAD", b"-h", b"0" * 40 + b"\nnoise", b"A" * 40])
def test_candidate_identity_is_never_a_revision_expression_or_command_stream(raw):
    with pytest.raises(ContractViolation):
        commit_oid(raw, "sha1")


@pytest.mark.parametrize("algorithm,length", [("sha1", 40), ("sha256", 64)])
def test_exact_object_format_defines_the_oid_length(algorithm, length):
    assert commit_oid(b"a" * length + b"\n", algorithm) == GitSha("a" * length)
