"""Manifest refresh uses committed baselines and actual staged Git blobs."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from scripts import regen_plan_manifest as regen


def git(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True, capture_output=True, stdin=subprocess.DEVNULL,
    ).stdout


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def entry(path: str, blob: bytes) -> bytes:
    return f"{digest(blob)}  {path}\n".encode()


def document(repository: Path, path: str, blob: bytes) -> None:
    destination = repository / "docs/plans" / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(blob)
    git(repository, "add", "--", f"docs/plans/{path}")


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Manifest fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    git(tmp_path, "config", "core.autocrlf", "false")
    document(tmp_path, "frozen.md", b"approved bytes\n")
    document(tmp_path, "handoffs/living.md", b"living record\n")
    manifest = tmp_path / "docs/plans/MANIFEST.sha256"
    manifest.write_bytes(entry("frozen.md", b"approved bytes\n") +
                         entry("handoffs/living.md", b"living record\n"))
    git(tmp_path, "add", "--", "docs/plans/MANIFEST.sha256")
    git(tmp_path, "commit", "-qm", "Committed baseline")
    monkeypatch.setattr(regen, "ROOT", tmp_path)
    monkeypatch.setattr(regen, "MANIFEST", manifest)
    return tmp_path


def refuse(repository: Path, named: list[str]) -> None:
    manifest = repository / "docs/plans/MANIFEST.sha256"
    before = manifest.read_bytes()
    assert regen.main(named) == 1
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("manifest_change", ["matching-digest", "omitted-entry", "unchanged"])
def test_refuses_unnamed_staged_drift_against_committed_baseline(
    repository: Path, manifest_change: str,
) -> None:
    document(repository, "frozen.md", b"altered frozen bytes\n")
    manifest = repository / "docs/plans/MANIFEST.sha256"
    if manifest_change == "matching-digest":
        manifest.write_bytes(manifest.read_bytes().replace(
            digest(b"approved bytes\n").encode(), digest(b"altered frozen bytes\n").encode(),
        ))
        git(repository, "add", "--", "docs/plans/MANIFEST.sha256")
    elif manifest_change == "omitted-entry":
        manifest.write_bytes(manifest.read_bytes().split(b"\n", 1)[1])
    refuse(repository, [])


@pytest.mark.parametrize("manual_entry", [False, True])
def test_refuses_unnamed_staged_new_document(repository: Path, manual_entry: bool) -> None:
    document(repository, "handoffs/named.md", b"named new document\n")
    document(repository, "handoffs/omitted.md", b"unnamed new document\n")
    if manual_entry:
        manifest = repository / "docs/plans/MANIFEST.sha256"
        manifest.write_bytes(manifest.read_bytes() +
                             entry("handoffs/omitted.md", b"unnamed new document\n"))
    refuse(repository, ["handoffs/named.md"])


@pytest.mark.parametrize("resolved_manifest", [False, True])
def test_accepts_named_new_and_living_documents_from_staged_bytes(
    repository: Path, resolved_manifest: bool,
) -> None:
    document(repository, "handoffs/living.md", b"staged living record\n")
    document(repository, "handoffs/new file.md", b"staged new document\n")
    (repository / "docs/plans/handoffs/living.md").write_bytes(b"unstaged living record\n")
    (repository / "docs/plans/handoffs/new file.md").write_bytes(b"unstaged new document\n")
    if resolved_manifest:
        manifest = repository / "docs/plans/MANIFEST.sha256"
        manifest.write_bytes(manifest.read_bytes().replace(
            digest(b"living record\n").encode(), b"0" * 64,
        ))
    assert regen.main(["handoffs/living.md", "handoffs/new file.md"]) == 0
    assert (repository / "docs/plans/MANIFEST.sha256").read_bytes() == (
        entry("frozen.md", b"approved bytes\n") +
        entry("handoffs/living.md", b"staged living record\n") +
        entry("handoffs/new file.md", b"staged new document\n")
    )


def test_noop_preserves_manifest_bytes(repository: Path) -> None:
    manifest = repository / "docs/plans/MANIFEST.sha256"
    before = manifest.read_bytes()
    assert regen.main([]) == 0
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("change", ["omitted", "changed-digest", "extra", "deleted"])
def test_refuses_manifest_edits_and_deletions_of_unnamed_paths(
    repository: Path, change: str,
) -> None:
    manifest = repository / "docs/plans/MANIFEST.sha256"
    if change == "omitted":
        manifest.write_bytes(manifest.read_bytes().split(b"\n", 1)[1])
    elif change == "changed-digest":
        manifest.write_bytes(manifest.read_bytes().replace(
            digest(b"approved bytes\n").encode(), b"0" * 64,
        ))
    elif change == "extra":
        manifest.write_bytes(manifest.read_bytes() + b"0" * 64 + b"  absent.md\n")
    else:
        git(repository, "rm", "--", "docs/plans/frozen.md")
        manifest.write_bytes(manifest.read_bytes().split(b"\n", 1)[1])
    refuse(repository, [])


@pytest.mark.parametrize("changed_frozen", [False, True, "omitted"])
def test_refuses_conflicted_manifest_before_refresh(
    repository: Path, changed_frozen: bool | str,
) -> None:
    document(repository, "handoffs/living.md", b"resolved staged record\n")
    manifest = repository / "docs/plans/MANIFEST.sha256"
    original = manifest.read_bytes()
    other = original.replace(digest(b"living record\n").encode(), b"1" * 64)
    if changed_frozen == "omitted":
        other = other.split(b"\n", 1)[1]
    elif changed_frozen:
        other = other.replace(digest(b"approved bytes\n").encode(), b"0" * 64)
    manifest.write_bytes(b"<<<<<<< HEAD\n" + original + b"=======\n" + other +
                         b">>>>>>> other\n")
    refuse(repository, ["handoffs/living.md"])


@pytest.mark.parametrize("marker", ["<<<<<<<", "|||||||", "=======", ">>>>>>>"])
def test_refuses_each_manifest_conflict_marker(repository: Path, marker: str) -> None:
    """One marker with unique valid entries isolates marker refusal from parsing."""
    manifest = repository / "docs/plans/MANIFEST.sha256"
    manifest.write_bytes(marker.encode() + b"\n" + manifest.read_bytes())
    refuse(repository, [])


@pytest.mark.parametrize("named", ["../outside.md", "./frozen.md", "absent.md", "MANIFEST.sha256"])
def test_refuses_invalid_or_unstaged_named_paths(repository: Path, named: str) -> None:
    refuse(repository, [named])


def test_refuses_unresolved_staged_document(repository: Path) -> None:
    git(repository, "checkout", "-qb", "other")
    document(repository, "handoffs/living.md", b"other side\n")
    git(repository, "commit", "-qm", "Other side")
    git(repository, "checkout", "-q", "-")
    document(repository, "handoffs/living.md", b"this side\n")
    git(repository, "commit", "-qm", "This side")
    result = subprocess.run(
        ["git", "-C", str(repository), "merge", "--no-edit", "other"],
        check=False, capture_output=True, stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 1
    assert b"CONFLICT" in result.stdout
    refuse(repository, ["handoffs/living.md"])


def manifest_modify_delete_conflict(repository: Path, deleted_side: str) -> None:
    manifest = repository / "docs/plans/MANIFEST.sha256"

    def change(side: str) -> None:
        if side == deleted_side:
            git(repository, "rm", "--", "docs/plans/MANIFEST.sha256")
        else:
            manifest.write_bytes(manifest.read_bytes() + b"\n")
            git(repository, "add", "--", "docs/plans/MANIFEST.sha256")
        git(repository, "commit", "-qm", f"{side} manifest change")

    git(repository, "checkout", "-qb", "other")
    change("other")
    git(repository, "checkout", "-q", "-")
    change("ours")
    result = subprocess.run(
        ["git", "-C", str(repository), "merge", "--no-edit", "other"],
        check=False, capture_output=True, stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 1
    assert b"CONFLICT (modify/delete)" in result.stdout
    assert manifest.is_file()
    assert not any(marker.encode() in manifest.read_bytes() for marker in regen.MARKERS)
    assert git(repository, "ls-files", "--unmerged", "--", "docs/plans/MANIFEST.sha256")


@pytest.mark.parametrize("deleted_side", ["ours", "other"])
def test_refuses_manifest_index_conflict_without_markers(
    repository: Path, deleted_side: str,
) -> None:
    manifest_modify_delete_conflict(repository, deleted_side)
    refuse(repository, [])


def test_accepts_manifest_after_explicit_index_resolution(repository: Path) -> None:
    manifest_modify_delete_conflict(repository, "other")
    git(repository, "add", "--", "docs/plans/MANIFEST.sha256")
    assert not git(repository, "ls-files", "--unmerged", "--", "docs/plans/MANIFEST.sha256")
    assert regen.main([]) == 0
    assert (repository / "docs/plans/MANIFEST.sha256").read_bytes() == (
        entry("frozen.md", b"approved bytes\n") +
        entry("handoffs/living.md", b"living record\n")
    )


def test_refuses_add_add_manifest_index_conflict_after_working_bytes_resolved(
    repository: Path,
) -> None:
    manifest = repository / "docs/plans/MANIFEST.sha256"
    baseline = manifest.read_bytes()
    git(repository, "rm", "--", "docs/plans/MANIFEST.sha256")
    git(repository, "commit", "-qm", "Common ancestor without manifest")
    git(repository, "checkout", "-qb", "other")
    manifest.write_bytes(baseline + b"other addition\n")
    git(repository, "add", "--", "docs/plans/MANIFEST.sha256")
    git(repository, "commit", "-qm", "Other manifest addition")
    git(repository, "checkout", "-q", "-")
    manifest.write_bytes(baseline + b"\n")
    git(repository, "add", "--", "docs/plans/MANIFEST.sha256")
    git(repository, "commit", "-qm", "Our manifest addition")
    result = subprocess.run(
        ["git", "-C", str(repository), "merge", "--no-edit", "other"],
        check=False, capture_output=True, stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 1
    assert b"CONFLICT (add/add)" in result.stdout
    manifest.write_bytes(baseline)
    assert git(repository, "ls-files", "--unmerged", "--", "docs/plans/MANIFEST.sha256")
    refuse(repository, [])
