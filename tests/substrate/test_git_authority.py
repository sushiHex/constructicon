"""GitAuthority plumbing: the staging boundary, the exact merge, the one
install transaction, and marker-based reconciliation (M3 §2)."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
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
    # Root and Windows ACLs can bypass or reinterpret POSIX write bits.
    geteuid = getattr(os, "geteuid", lambda: 1)
    if os.name != "nt" and geteuid() != 0:
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


def test_discarding_an_already_removed_tree_is_never_a_caller_fault(
    authority: GitAuthority,
    tmp_path: Path,
) -> None:
    """Cleanup is best-effort by contract: a discard reports, it never raises.

    A crash-and-retry, a second discard, or a tree another process still holds
    open must all leave the caller with a plain answer rather than an
    exception it has no way to act on.
    """

    base = authority.resolve_ref("refs/heads/main")
    snapshot = authority.read_snapshot(base)
    authority.discard_snapshot(snapshot)
    assert not Path(snapshot.path).exists()
    authority.discard_snapshot(snapshot)  # idempotent, not an error

    authority.acquire_write(
        acquisition_id="acq-discard",
        target_ref="refs/heads/main",
        candidate_ref="refs/candidates/run-test/acq-discard",
    )
    assert authority.discard_staging("acq-discard") is True
    assert authority.discard_staging("acq-discard") is False


def _commit_files(
    authority: GitAuthority, tag: str, files: dict[str, str], *, executable: str | None = None
) -> GitSha:
    workspace = authority.acquire_write(
        acquisition_id=f"acq-{tag}",
        target_ref="refs/heads/main",
        candidate_ref=f"refs/candidates/run-test/acq-{tag}",
    )
    for name, content in files.items():
        Path(workspace.path, name).write_text(content, newline="\n")
    if executable is not None:
        os.chmod(Path(workspace.path, executable), 0o755)
    return workspace.commit_all(f"candidate {tag}")


def _snapshot_dirs(authority: GitAuthority, tmp_path: Path) -> list[str]:
    root = tmp_path / "workspaces" / "snapshots"
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


@pytest.mark.parametrize(
    ("files", "attributes"),
    [
        pytest.param({"test_bad.py": "def test_x():\n    assert False\n"},
                     "test_bad.py export-ignore\n", id="export-ignore"),
        pytest.param({"stamp.txt": "$Format:%H$\n"},
                     "stamp.txt export-subst\n", id="export-subst"),
        pytest.param({"crlf.txt": "a\nb\n"},
                     "crlf.txt text eol=crlf\n", id="eol-conversion"),
    ],
)
def test_snapshot_refuses_exports_that_differ_from_the_git_tree(
    authority: GitAuthority, tmp_path: Path, files: dict[str, str], attributes: str
) -> None:
    candidate = _commit_files(authority, "attr", {**files, ".gitattributes": attributes})
    with pytest.raises(ContractViolation, match="differs from the exact Git tree"):
        authority.read_snapshot(candidate)
    assert _snapshot_dirs(authority, tmp_path) == []  # refused export is removed


def test_snapshot_accepts_ordinary_candidate_with_attributes_and_modes(
    authority: GitAuthority, tmp_path: Path
) -> None:
    candidate = _commit_files(
        authority,
        "ok",
        {
            "run.sh": "#!/bin/sh\n", "run.cmd": "echo candidate\n", "doc.txt": "x\n",
            ".gitattributes": "*.txt text eol=lf\n",
        },
        executable="run.sh",
    )
    snapshot = authority.read_snapshot(candidate)
    try:
        assert Path(snapshot.path, "doc.txt").read_text() == "x\n"
        assert Path(snapshot.path, "run.sh").exists()
        assert Path(snapshot.path, "run.cmd").read_text() == "echo candidate\n"
        if os.name != "nt":
            assert os.stat(Path(snapshot.path, "run.sh")).st_mode & 0o111
    finally:
        authority.discard_snapshot(snapshot)
    assert _snapshot_dirs(authority, tmp_path) == []


def test_snapshot_archive_is_disk_backed_even_with_a_relative_workspace_root(
    authority, tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    relative = GitAuthority(authority.repository_id, Path("relative-workspaces"))
    original = subprocess.run
    archives = []

    def observe(command, **kwargs):
        result = original(command, **kwargs)
        if "archive" in command:
            outputs = [arg.removeprefix("--output=") for arg in command
                       if arg.startswith("--output=")]
            assert len(outputs) == 1, "archive has no affirmative disk-output destination"
            archive = Path(outputs[0])
            assert archive.is_absolute() and archive.is_file()
            assert archive.stat().st_size > 0
            assert result.stdout == b"", "tar bytes crossed the subprocess output boundary"
            archives.append(archive)
        return result

    monkeypatch.setattr(subprocess, "run", observe)
    snapshot = relative.read_snapshot(relative.resolve_ref("refs/heads/main"))
    try:
        expected = relative._run("show", f"{snapshot.commit}:calc.py").stdout
        assert Path(snapshot.path, "calc.py").read_text() == expected
        assert len(archives) == 1 and not any(path.exists() for path in archives)
        assert not Path(snapshot.path).is_absolute()
    finally:
        relative.discard_snapshot(snapshot)


@pytest.mark.parametrize("failure", ["archive", "extract", "readonly"])
def test_snapshot_cleans_its_disk_archive_and_tree_on_failure(
    authority, tmp_path, monkeypatch, failure,
):
    from constructicon.substrate.git import authority as module

    original = subprocess.run
    if failure == "archive":
        def fail(command, **kwargs):
            if "archive" in command:
                output, = (arg.removeprefix("--output=") for arg in command
                           if arg.startswith("--output="))
                Path(output).write_bytes(b"partial archive")
                raise subprocess.CalledProcessError(1, command)
            return original(command, **kwargs)
        monkeypatch.setattr(subprocess, "run", fail)
    elif failure == "extract":
        def fail_extract(self, path, **kwargs):
            Path(path, "partial").write_bytes(b"partial extraction")
            raise tarfile.ReadError("partial extraction")
        monkeypatch.setattr(tarfile.TarFile, "extractall", fail_extract)
    else:
        set_bits = module._set_write_bits
        def fail_readonly(root, *, writable):
            if not writable:
                raise OSError("readonly setup failed")
            set_bits(root, writable=writable)
        monkeypatch.setattr(module, "_set_write_bits", fail_readonly)
    with pytest.raises((subprocess.CalledProcessError, tarfile.ReadError, OSError)):
        authority.read_snapshot(authority.resolve_ref("refs/heads/main"))
    assert _snapshot_dirs(authority, tmp_path) == []


def test_exact_extraction_never_removes_a_preexisting_destination(authority, tmp_path):
    dest, archive = tmp_path / "existing", tmp_path / "owned.tar"
    dest.mkdir()
    (dest / "sentinel").write_bytes(b"not this extraction's tree")
    archive.write_bytes(b"unused")
    with pytest.raises(FileExistsError):
        authority.extract_exact(b"", archive, dest)
    assert (dest / "sentinel").read_bytes() == b"not this extraction's tree"
    assert not archive.exists()


def test_exact_extraction_refuses_escaping_tar_members_and_cleans_up(authority, tmp_path):
    archive, dest = tmp_path / "unsafe.tar", tmp_path / "snapshot"
    with tarfile.open(archive, "w") as output:
        output.addfile(tarfile.TarInfo("../escaped"))
    with pytest.raises(tarfile.FilterError):
        authority.extract_exact(b"", archive, dest)
    assert not archive.exists() and not dest.exists() and not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("entry", ["executable", "symlink", "blob-mismatch", "gitlink"])
def test_exact_extraction_preserves_blob_type_and_mode_laws(authority, tmp_path, entry):
    archive, dest = tmp_path / "tree.tar", tmp_path / "snapshot"
    if entry == "symlink" and os.name == "nt":
        probe = tmp_path / "symlink-probe"
        try:
            probe.symlink_to("target")
        except OSError as exc:
            if exc.winerror == 1314:
                pytest.skip("Windows account cannot create symbolic links")
            raise
        probe.unlink()
    raw = b"target" if entry == "symlink" else b"blob contents\n"
    oid = hashlib.new(authority.environment.object_format,
                      f"blob {len(raw)}\0".encode() + raw).hexdigest()
    mode = {"executable": "100755", "symlink": "120000", "gitlink": "160000"}.get(
        entry, "100644",
    )
    inventory = f"{mode} {'commit' if entry == 'gitlink' else 'blob'} {oid}\tfile\0".encode()
    with tarfile.open(archive, "w") as output:
        member = tarfile.TarInfo("file")
        member.mode = 0o755 if entry == "executable" else 0o644
        if entry == "symlink":
            member.type, member.linkname = tarfile.SYMTYPE, "target"
        else:
            payload = b"wrong contents" if entry == "blob-mismatch" else raw
            member.size = len(payload)
        output.addfile(member, None if entry == "symlink" else io.BytesIO(payload))
    if entry in {"blob-mismatch", "gitlink"}:
        with pytest.raises(ContractViolation, match=r"exact Git tree|unsupported Git entry"):
            authority.extract_exact(inventory, archive, dest)
        assert not dest.exists()
    else:
        authority.extract_exact(inventory, archive, dest)
        if entry == "symlink":
            assert (dest / "file").is_symlink() and os.readlink(dest / "file") == "target"
        else:
            assert (dest / "file").read_bytes() == raw
            if os.name != "nt":
                assert (dest / "file").stat().st_mode & 0o111
    assert not archive.exists()
