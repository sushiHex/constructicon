"""GitAuthority plumbing: the staging boundary, the exact merge, the one
install transaction, and marker-based reconciliation (M3 §2)."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

import pytest

from constructicon.core.address import GitSha
from constructicon.core.envelope import GitRef
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.substrate.git.authority import (
    GitAuthority,
    GitAuthorityDamaged,
    MergeConflict,
    PreparedMerge,
)
from tests.gitworld import BROKEN_FIX, GOOD_FIX, push_to_main, seed_authority

KEY = digest("idempotency", 1, {"test": "install"})


@pytest.fixture
def authority(tmp_path: Path) -> GitAuthority:
    repo = seed_authority(tmp_path)
    return GitAuthority(repo, tmp_path / "workspaces")


def make_candidate(
    authority: GitAuthority, tmp_path: Path, content: str = GOOD_FIX, tag: str = "a"
) -> GitSha:
    workspace = authority.acquire_write(
        acquisition_id=f"acq-{tag}",
        target_ref="refs/heads/main",
        candidate_ref=f"refs/candidates/run-test/acq-{tag}",
    )
    Path(workspace.path, "calc.py").write_text(content)
    return workspace.commit_all(f"candidate {tag}")


def test_agent_git_commands_cannot_touch_authority_refs(
    authority: GitAuthority, tmp_path: Path
) -> None:
    """Blocker 1's test: zero protected-ref authority in an agent workspace."""
    before = authority.resolve_ref("refs/heads/main")
    workspace = authority.acquire_write(
        acquisition_id="acq-hostile",
        target_ref="refs/heads/main",
        candidate_ref="refs/candidates/run-test/acq-hostile",
    )
    Path(workspace.path, "calc.py").write_text(BROKEN_FIX)
    candidate = workspace.commit_all("hostile")

    def agent_git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=workspace.path, capture_output=True, text=True,
            check=False, timeout=30,
        )

    # moving refs inside the staging repository is allowed — and irrelevant
    assert agent_git("update-ref", "refs/heads/main", candidate).returncode == 0
    assert agent_git("branch", "-f", "sneaky", candidate).returncode == 0
    # pushing into the authority is physically refused (deny-all pre-receive)
    push = agent_git("push", authority.repository_id, f"{candidate}:refs/heads/main")
    assert push.returncode != 0
    assert "refused" in (push.stderr + push.stdout)
    assert authority.resolve_ref("refs/heads/main") == before  # byte-identical


def test_prepare_merge_is_exact_and_deterministic(
    authority: GitAuthority, tmp_path: Path
) -> None:
    candidate = make_candidate(authority, tmp_path)
    first = authority.prepare_merge(candidate, "refs/heads/main")
    second = authority.prepare_merge(candidate, "refs/heads/main")
    assert isinstance(first, PreparedMerge) and isinstance(second, PreparedMerge)
    assert first.subject == second.subject  # pinned identity: same sha
    subject = first.subject
    assert authority.tree_of(subject.merge_commit) == subject.tested_tree
    assert authority.parents_of(subject.merge_commit) == (
        subject.expected_base,
        subject.candidate,
    )


def test_conflict_is_data_never_an_exception(
    authority: GitAuthority, tmp_path: Path
) -> None:
    candidate = make_candidate(authority, tmp_path, content=GOOD_FIX)
    push_to_main(
        authority._repo, {"calc.py": "def add(a, b):\n    return b + a\n"}, "collide"
    )
    prepared = authority.prepare_merge(candidate, "refs/heads/main")
    assert isinstance(prepared, MergeConflict)
    assert prepared.detail


def test_install_is_one_transaction_with_a_marker(
    authority: GitAuthority, tmp_path: Path
) -> None:
    candidate = make_candidate(authority, tmp_path)
    prepared = authority.prepare_merge(candidate, "refs/heads/main")
    assert isinstance(prepared, PreparedMerge)
    subject = prepared.subject

    assert authority.reconcile_install(subject, KEY) is None  # nothing yet
    outcome = authority.install(subject, KEY)
    assert outcome.installed
    assert authority.resolve_ref("refs/heads/main") == subject.merge_commit
    assert authority.read_ref(authority.marker_ref(KEY)) == subject.merge_commit
    assert authority.reconcile_install(subject, KEY) is True
    # idempotent re-install: the marker proves it already happened
    assert authority.install(subject, KEY).installed


def test_marker_survives_a_forced_move_of_the_target(
    authority: GitAuthority, tmp_path: Path
) -> None:
    candidate = make_candidate(authority, tmp_path)
    prepared = authority.prepare_merge(candidate, "refs/heads/main")
    assert isinstance(prepared, PreparedMerge)
    subject = prepared.subject
    authority.install(subject, KEY)
    push_to_main(authority._repo, {"calc.py": SEED_LIKE}, "supersede")
    # the target moved on, but the durable proof of install stands
    assert authority.reconcile_install(subject, KEY) is True


SEED_LIKE = "def add(a: int, b: int) -> int:\n    return int(a + b)\n"


def test_marker_mismatch_is_damage(authority: GitAuthority, tmp_path: Path) -> None:
    candidate = make_candidate(authority, tmp_path)
    prepared = authority.prepare_merge(candidate, "refs/heads/main")
    assert isinstance(prepared, PreparedMerge)
    subject = prepared.subject
    authority._run("update-ref", authority.marker_ref(KEY), subject.candidate)
    with pytest.raises(GitAuthorityDamaged, match="marker"):
        authority.reconcile_install(subject, KEY)


def test_base_moved_is_a_truthful_rejection(
    authority: GitAuthority, tmp_path: Path
) -> None:
    candidate = make_candidate(authority, tmp_path)
    prepared = authority.prepare_merge(candidate, "refs/heads/main")
    assert isinstance(prepared, PreparedMerge)
    subject = prepared.subject
    moved = push_to_main(authority._repo, {"extra.py": "X = 1\n"}, "base moves")
    outcome = authority.install(subject, KEY)
    assert not outcome.installed
    assert outcome.found_base == moved
    assert authority.read_ref(authority.marker_ref(KEY)) is None  # neither ref landed


def test_same_subject_race_yields_one_install_both_committed(
    authority: GitAuthority, tmp_path: Path
) -> None:
    candidate = make_candidate(authority, tmp_path)
    prepared = authority.prepare_merge(candidate, "refs/heads/main")
    assert isinstance(prepared, PreparedMerge)
    subject = prepared.subject
    results: list[bool] = []
    barrier = threading.Barrier(2)

    def race() -> None:
        barrier.wait()
        results.append(authority.install(subject, KEY).installed)

    threads = [threading.Thread(target=race) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [True, True]  # one physical install, both observe committed
    assert authority.resolve_ref("refs/heads/main") == subject.merge_commit


def test_competing_subjects_one_committed_one_rejected(
    authority: GitAuthority, tmp_path: Path
) -> None:
    first = make_candidate(authority, tmp_path, tag="one")
    second = make_candidate(authority, tmp_path, content=SEED_LIKE, tag="two")
    prepared_one = authority.prepare_merge(first, "refs/heads/main")
    prepared_two = authority.prepare_merge(second, "refs/heads/main")
    assert isinstance(prepared_one, PreparedMerge)
    assert isinstance(prepared_two, PreparedMerge)
    key_two = digest("idempotency", 1, {"test": "install-two"})

    assert authority.install(prepared_one.subject, KEY).installed
    outcome = authority.install(prepared_two.subject, key_two)
    assert not outcome.installed  # its expected base is gone
    assert outcome.found_base == prepared_one.subject.merge_commit


def test_snapshot_is_physically_read_only_and_content_verified(
    authority: GitAuthority, tmp_path: Path
) -> None:
    base = authority.resolve_ref("refs/heads/main")
    snapshot = authority.read_snapshot(base)
    calc = Path(snapshot.path, "calc.py")
    mode = os.stat(calc).st_mode
    assert mode & 0o222 == 0  # write bits gone on files
    assert os.stat(snapshot.path).st_mode & 0o222 == 0  # and directories
    if os.geteuid() != 0:  # root bypasses permission bits; CI runs unprivileged
        with pytest.raises(PermissionError):
            calc.write_text("mutate")
        with pytest.raises(PermissionError):
            Path(snapshot.path, "new.py").write_text("create")
    before = authority.content_digest(snapshot.path)
    assert before == authority.content_digest(snapshot.path)  # stable
    authority.discard_snapshot(snapshot)
    assert not Path(snapshot.path).exists()


def test_candidate_ref_cleanup_is_cas_checked(
    authority: GitAuthority, tmp_path: Path
) -> None:
    candidate = make_candidate(authority, tmp_path)
    ref = "refs/candidates/run-test/acq-a"
    other = authority.resolve_ref("refs/heads/main")  # a real, different commit
    assert authority.read_ref(ref) == candidate
    assert not authority.delete_ref_cas(ref, other)  # moved -> refuse, report
    assert authority.read_ref(ref) == candidate
    assert authority.delete_ref_cas(ref, candidate)
    assert authority.read_ref(ref) is None


def test_reset_to_threads_a_prior_candidate_as_the_new_parent(
    authority: GitAuthority,
    tmp_path: Path,
) -> None:
    first = make_candidate(authority, tmp_path, content=BROKEN_FIX, tag="first")
    workspace = authority.acquire_write(
        acquisition_id="acq-second",
        target_ref="refs/heads/main",
        candidate_ref="refs/candidates/run-test/acq-second",
    )
    # reset is exact: tracked and untracked staging state are discarded
    Path(workspace.path, "untracked.tmp").write_text("remove me")
    workspace.reset_to(
        GitRef(
            repository=authority.repository_id,
            commit=first,
            diff_against=workspace.base,
        )
    )
    assert not Path(workspace.path, "untracked.tmp").exists()
    Path(workspace.path, "calc.py").write_text(GOOD_FIX)
    second = workspace.commit_all("second repair")
    assert authority.parents_of(second) == (first,)


def test_reset_to_refuses_cross_repository_missing_and_post_import_targets(
    authority: GitAuthority,
    tmp_path: Path,
) -> None:
    candidate = make_candidate(authority, tmp_path, tag="source")
    workspace = authority.acquire_write(
        acquisition_id="acq-reset-errors",
        target_ref="refs/heads/main",
        candidate_ref="refs/candidates/run-test/acq-reset-errors",
    )
    with pytest.raises(ContractViolation, match="does not match authority"):
        workspace.reset_to(
            GitRef(repository="elsewhere", commit=candidate)
        )
    with pytest.raises(ContractViolation):
        workspace.reset_to(
            GitRef(
                repository=authority.repository_id,
                commit=GitSha("0" * 40),
            )
        )

    Path(workspace.path, "calc.py").write_text(GOOD_FIX)
    workspace.commit_all("already imported")
    with pytest.raises(ContractViolation, match="before commit_all"):
        workspace.reset_to(
            GitRef(repository=authority.repository_id, commit=candidate)
        )
