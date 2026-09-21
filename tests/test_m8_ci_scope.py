"""Portable proofs for M8 CI selection; these are not containment evidence."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from scripts.ci import m8_ci_scope as scope


def _entry(
    path: str,
    *,
    status: str = "M",
    old_mode: str = scope.REGULAR_MODE,
    new_mode: str = scope.REGULAR_MODE,
) -> scope.DiffEntry:
    old_oid = "1" * 40
    new_oid = "2" * 40
    if status == "A":
        old_mode, old_oid = scope.ABSENT_MODE, scope.ZERO_OID
    elif status == "D":
        new_mode, new_oid = scope.ABSENT_MODE, scope.ZERO_OID
    return scope.DiffEntry(old_mode, new_mode, old_oid, new_oid, status, path)


@pytest.mark.parametrize(
    "entries",
    [
        (_entry("README.md"),),
        (_entry("AGENTS.md", status="D"),),
        (_entry("CONTRIBUTING.md", status="A"),),
        (_entry("docs/new.md", status="A"),),
        (_entry("docs/deep/archive.md", status="D"),),
        (_entry("docs/plans/MANIFEST.sha256"),),
        (_entry("docs/old.md", status="D"), _entry("docs/new.md", status="A")),
    ],
)
def test_only_plain_allowlisted_prose_changes_select_docs(
    entries: tuple[scope.DiffEntry, ...],
) -> None:
    assert scope.classify_changes(entries) == "docs"


@pytest.mark.parametrize(
    "entry",
    [
        _entry("CLAUDE.md"),
        _entry(".github/pull_request_template.md"),
        _entry("notes/example.md"),
        _entry("src/constructicon/core/run.py"),
        _entry("docs/image.png"),
        _entry("../docs/escape.md"),
        _entry("docs\\windows.md"),
        _entry("docs/tool.md", new_mode="100755"),
        _entry("docs/link.md", status="A", new_mode="120000"),
        _entry("docs/submodule.md", status="A", new_mode="160000"),
        _entry("docs/conflict.md", status="U"),
        _entry("docs/type.md", status="T"),
        _entry("docs/renamed.md", status="R"),
    ],
)
def test_unknown_path_mode_or_status_selects_full(entry: scope.DiffEntry) -> None:
    assert scope.classify_changes((entry,)) == "full"


def test_one_unknown_entry_makes_the_whole_change_full() -> None:
    entries = (_entry("docs/guide.md"), _entry("tests/test_behavior.py"))
    assert scope.classify_changes(entries) == "full"


def test_no_changes_selects_full() -> None:
    assert scope.classify_changes(()) == "full"


def test_raw_diff_parser_preserves_unusual_but_valid_path_bytes() -> None:
    raw = (
        b":100644 100644 "
        + b"1" * 40
        + b" "
        + b"2" * 40
        + b" M\0docs/name with newline\nand tab\t.md\0"
    )
    assert scope.parse_raw_diff(raw) == (_entry("docs/name with newline\nand tab\t.md"),)


@pytest.mark.parametrize(
    "raw",
    [
        b":100644 100644 111 222 M\0docs/a.md\0",
        b":100644 100644 " + b"1" * 40 + b" " + b"2" * 40 + b" M\0",
        b":100644 100644 " + b"1" * 40 + b" " + b"2" * 40 + b" M\0docs/a.md",
        b":100644 100644 " + b"1" * 40 + b" " + b"2" * 40 + b" M\0\xff\0",
    ],
)
def test_incomplete_or_malformed_raw_diff_is_an_error(raw: bytes) -> None:
    with pytest.raises(scope.ScopeError):
        scope.parse_raw_diff(raw)


def _run_git(repository: Path, *arguments: str, input_bytes: bytes | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        input=input_bytes,
        capture_output=True,
        check=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
    )
    return completed.stdout.decode().strip()


def _commit(repository: Path, message: str) -> str:
    _run_git(repository, "add", "-A")
    _run_git(repository, "commit", "-m", message)
    return _run_git(repository, "rev-parse", "HEAD")


@pytest.fixture
def git_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _run_git(repository, "init", "--initial-branch=main")
    _run_git(repository, "config", "user.name", "CI Test")
    _run_git(repository, "config", "user.email", "ci@example.invalid")
    (repository / "docs").mkdir()
    (repository / "docs/guide.md").write_text("guide\n", encoding="utf-8")
    (repository / "README.md").write_text("readme\n", encoding="utf-8")
    (repository / "source.py").write_text("value = 1\n", encoding="utf-8")
    return repository, _commit(repository, "base")


def test_repository_classifier_uses_the_committed_docs_diff(
    git_repository: tuple[Path, str],
) -> None:
    repository, base = git_repository
    (repository / "docs/guide.md").write_text("changed\n", encoding="utf-8")
    head = _commit(repository, "docs")
    assert scope.classify_repository(repository, base, head) == "docs"


def test_repository_classifier_treats_a_docs_rename_as_delete_plus_add(
    git_repository: tuple[Path, str],
) -> None:
    repository, base = git_repository
    _run_git(repository, "mv", "docs/guide.md", "docs/moved.md")
    head = _commit(repository, "rename docs")
    assert scope.classify_repository(repository, base, head) == "docs"


def test_repository_classifier_allows_a_regular_docs_deletion(
    git_repository: tuple[Path, str],
) -> None:
    repository, base = git_repository
    (repository / "docs/guide.md").unlink()
    head = _commit(repository, "delete docs")
    assert scope.classify_repository(repository, base, head) == "docs"


def test_repository_classifier_selects_full_for_code(
    git_repository: tuple[Path, str],
) -> None:
    repository, base = git_repository
    (repository / "source.py").write_text("value = 2\n", encoding="utf-8")
    head = _commit(repository, "code")
    assert scope.classify_repository(repository, base, head) == "full"


def test_repository_classifier_selects_full_for_an_executable_doc(
    git_repository: tuple[Path, str],
) -> None:
    repository, base = git_repository
    _run_git(repository, "update-index", "--chmod=+x", "docs/guide.md")
    _run_git(repository, "commit", "-m", "executable docs")
    head = _run_git(repository, "rev-parse", "HEAD")
    assert scope.classify_repository(repository, base, head) == "full"


def test_repository_classifier_selects_full_for_a_symlink_record(
    git_repository: tuple[Path, str],
) -> None:
    repository, base = git_repository
    blob = _run_git(repository, "hash-object", "-w", "--stdin", input_bytes=b"guide.md")
    _run_git(repository, "update-index", "--add", "--cacheinfo", f"120000,{blob},docs/link.md")
    _run_git(repository, "commit", "-m", "symlink docs")
    head = _run_git(repository, "rev-parse", "HEAD")
    assert scope.classify_repository(repository, base, head) == "full"


def test_repository_classifier_uses_merge_base_not_base_branch_only_changes(
    git_repository: tuple[Path, str],
) -> None:
    repository, common = git_repository
    _run_git(repository, "checkout", "-b", "feature")
    (repository / "docs/guide.md").write_text("feature docs\n", encoding="utf-8")
    head = _commit(repository, "feature docs")
    _run_git(repository, "checkout", "main")
    (repository / "source.py").write_text("base branch code\n", encoding="utf-8")
    base = _commit(repository, "base code")
    assert common != base
    assert scope.classify_repository(repository, base, head) == "docs"


def test_repository_classifier_refuses_bad_or_missing_commit_evidence(
    git_repository: tuple[Path, str],
) -> None:
    repository, base = git_repository
    with pytest.raises(scope.ScopeError, match="40-hex"):
        scope.classify_repository(repository, "HEAD", base)
    with pytest.raises(scope.ScopeError, match="failed"):
        scope.classify_repository(repository, "f" * 40, base)


def test_repository_classifier_selects_full_for_an_empty_diff(
    git_repository: tuple[Path, str],
) -> None:
    repository, base = git_repository
    assert scope.classify_repository(repository, base, base) == "full"


def _write_manifest(repository: Path) -> Path:
    plans = repository / "docs/plans"
    documents = sorted(plans.rglob("*.md"))
    manifest = plans / "MANIFEST.sha256"
    manifest.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"{path.relative_to(plans).as_posix()}\n"
            for path in documents
        ),
        encoding="utf-8",
    )
    return manifest


@pytest.fixture
def docs_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "docs-repository"
    (repository / "docs/plans/archive").mkdir(parents=True)
    (repository / "README.md").write_text(
        "[guide](docs/guide.md#section) [external](https://example.invalid)\n",
        encoding="utf-8",
    )
    (repository / "docs/guide.md").write_text(
        "[archive](plans/archive/) [self](#section)\n",
        encoding="utf-8",
    )
    (repository / "docs/plans/README.md").write_text("[archive](archive/item.md)\n")
    (repository / "docs/plans/archive/item.md").write_text("retained\n")
    _write_manifest(repository)
    return repository


def test_docs_validation_accepts_complete_archive_and_relative_links(
    docs_repository: Path,
) -> None:
    scope.verify_docs(docs_repository)


def test_docs_validation_accepts_the_actual_repository() -> None:
    scope.verify_docs(Path(__file__).parents[1])


def test_docs_validation_refuses_a_missing_relative_target(docs_repository: Path) -> None:
    (docs_repository / "README.md").write_text("[missing](docs/missing.md)\n")
    with pytest.raises(scope.ScopeError, match="missing relative link"):
        scope.verify_docs(docs_repository)


def test_docs_validation_refuses_a_manifest_digest_mismatch(docs_repository: Path) -> None:
    (docs_repository / "docs/plans/archive/item.md").write_text("changed\n")
    with pytest.raises(scope.ScopeError, match="digest mismatch"):
        scope.verify_docs(docs_repository)


def test_docs_validation_refuses_a_missing_manifest_entry(docs_repository: Path) -> None:
    (docs_repository / "docs/plans/new.md").write_text("new\n")
    with pytest.raises(scope.ScopeError, match="incomplete plan manifest"):
        scope.verify_docs(docs_repository)


def test_docs_validation_refuses_a_duplicate_manifest_entry(docs_repository: Path) -> None:
    manifest = docs_repository / "docs/plans/MANIFEST.sha256"
    first = manifest.read_text(encoding="utf-8").splitlines()[0]
    manifest.write_text(manifest.read_text(encoding="utf-8") + first + "\n", encoding="utf-8")
    with pytest.raises(scope.ScopeError, match="duplicate"):
        scope.verify_docs(docs_repository)


def test_docs_validation_refuses_an_extra_manifest_path(docs_repository: Path) -> None:
    manifest = docs_repository / "docs/plans/MANIFEST.sha256"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + f"{'0' * 64}  absent.md\n",
        encoding="utf-8",
    )
    with pytest.raises(scope.ScopeError, match="incomplete plan manifest"):
        scope.verify_docs(docs_repository)


@pytest.mark.parametrize(
    ("scope_name", "classification", "docs", "proofs", "allowed"),
    [
        ("full", "success", "skipped", "success", True),
        ("docs", "success", "success", "skipped", True),
        ("docs", "success", "failure", "skipped", False),
        ("docs", "success", "cancelled", "skipped", False),
        ("docs", "success", "success", "success", False),
        ("full", "success", "skipped", "failure", False),
        ("full", "success", "skipped", "cancelled", False),
        ("full", "success", "success", "success", False),
        ("full", "failure", "skipped", "success", False),
        ("full", "cancelled", "skipped", "success", False),
        ("full", "", "skipped", "success", False),
        ("unknown", "success", "skipped", "success", False),
        ("", "success", "skipped", "success", False),
        ("docs", "success", "success", "", False),
        ("docs", "success", "unknown", "skipped", False),
    ],
)
def test_gate_accepts_only_complete_expected_job_shapes(
    scope_name: str,
    classification: str,
    docs: str,
    proofs: str,
    allowed: bool,
) -> None:
    assert scope.gate_allows(scope_name, classification, docs, proofs) is allowed


def test_cli_classify_prints_only_the_scope(
    git_repository: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    repository, base = git_repository
    (repository / "docs/guide.md").write_text("changed\n", encoding="utf-8")
    head = _commit(repository, "docs")
    result = scope.main(
        ["classify", "--base", base, "--head", head, "--repository", str(repository)]
    )
    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "docs\n"
    assert captured.err == ""


def test_cli_classification_error_never_prints_docs(
    git_repository: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    repository, base = git_repository
    result = scope.main(
        ["classify", "--base", "f" * 40, "--head", base, "--repository", str(repository)]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "Git evidence command failed" in captured.err
