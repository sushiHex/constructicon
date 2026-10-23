"""Run the real portable workflow selector against committed Git evidence."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from scripts.ci import m8_ci_scope as scope

from tests.test_m8_ci_scope import _commit, _run_git, _write_manifest
from tests.test_m8_ci_scope import git_repository as git_repository
from tests.test_m8_operator_commands import _bash

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/verify.yml"


def _job(name: str) -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    return re.split(r"\n  [\w-]+:\n", workflow.split(f"\n  {name}:\n", 1)[1], maxsplit=1)[0]


def _run_classifier(repository: Path, base: str, head: str, tmp_path: Path,
                    *, event: str = "pull_request"):
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    command = textwrap.dedent(_job("classify").split("        run: |\n", 1)[1])
    # Git Bash has no python3 alias; substitute only the interpreter spelling.
    command = 'python3() { "$TEST_PYTHON" "$@"; }\n' + command
    completed = subprocess.run(
        [str(_bash()), "-c", command], cwd=repository, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False, timeout=30,
        env={**os.environ, "EVENT": event, "BASE_SHA": base, "HEAD_SHA": head,
             "TEST_PYTHON": Path(sys.executable).as_posix(),
             "RUNNER_TEMP": runtime.as_posix(), "GITHUB_OUTPUT": output.as_posix(),
             "GITHUB_STEP_SUMMARY": summary.as_posix()},
    )
    emitted = output.read_text(encoding="utf-8") if output.exists() else ""
    return completed, emitted


@pytest.fixture
def classifier_repository(git_repository: tuple[Path, str]) -> tuple[Path, str]:
    repository, _ = git_repository
    script = repository / "scripts/ci/m8_ci_scope.py"
    script.parent.mkdir(parents=True)
    script.write_bytes((ROOT / "scripts/ci/m8_ci_scope.py").read_bytes())
    return repository, _commit(repository, "trusted base classifier")


def test_portable_scope_has_only_read_permission_and_credential_free_checkout() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "\npermissions:\n  contents: read\n" in workflow
    assert "pull_request_target" not in workflow
    checkouts = re.findall(r"^      - uses: actions/checkout@[^\n]+\n((?:        .+\n)+)",
                           workflow, re.M)
    assert len(checkouts) == 5
    assert all("          persist-credentials: false\n" in checkout for checkout in checkouts)
    classify = _job("classify")
    assert "          fetch-depth: 0\n" in classify
    assert 'git show "$BASE_SHA:scripts/ci/m8_ci_scope.py"' in classify
    assert 'python3 "$RUNNER_TEMP/m8-ci-scope.py" classify' in classify
    assert "python3 scripts/ci/m8_ci_scope.py classify" not in classify
    assert "          ref: ${{ github.event.pull_request.head.sha || github.sha }}" in classify
    assert "          ref:" not in _job("docs")


def test_scope_conditions_select_docs_or_all_existing_code_jobs() -> None:
    assert "    needs: classify\n" in _job("docs")
    assert "    if: needs.classify.outputs.scope == 'docs'\n" in _job("docs")
    assert "      - run: python3 scripts/ci/m8_ci_scope.py docs\n" in _job("docs")
    for job in ("windows-discovery", "verify", "mutations"):
        assert "    needs: classify\n" in _job(job)
        assert "    if: needs.classify.outputs.scope == 'full'\n" in _job(job)
    assert "      - run: uv run verify\n" in _job("verify")
    assert _job("mutations").count("          - check_") == 17
    assert "      fail-fast: false\n" in _job("mutations")


@pytest.mark.parametrize("path,expected", [
    ("README.md", "docs"), ("CLAUDE.md", "docs"),
    ("docs/ARCHITECTURE.md", "docs"), ("source.py", "full"),
    ("docs/plans/handoffs/M8-implementation-record.md", "docs"),
    ("docs/plans/handoffs/M8-N6-host-session.md", "full"),
    ("docs/unknown.md", "full"),
    (".github/workflows/verify.yml", "full"), ("unknown.md", "full"),
])
def test_workflow_selector_uses_committed_base_policy(
    classifier_repository: tuple[Path, str], tmp_path: Path, path: str, expected: str,
) -> None:
    repository, base = classifier_repository
    changed = repository / path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("changed\n", encoding="utf-8")
    head = _commit(repository, "candidate")
    completed, emitted = _run_classifier(repository, base, head, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert emitted == f"scope={expected}\n"
    selected = {
        name for name in ("docs", "windows-discovery", "verify", "mutations")
        if f"scope == '{expected}'" in _job(name)
    }
    assert selected == ({"docs"} if expected == "docs"
                        else {"windows-discovery", "verify", "mutations"})


def test_mixed_change_and_pr_classifier_self_exemption_still_require_full(
    classifier_repository: tuple[Path, str], tmp_path: Path,
) -> None:
    repository, base = classifier_repository
    (repository / "README.md").write_text("candidate prose\n", encoding="utf-8")
    (repository / "scripts/ci/m8_ci_scope.py").write_text('print("docs")\n', encoding="utf-8")
    head = _commit(repository, "candidate tries to exempt itself")
    completed, emitted = _run_classifier(repository, base, head, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert emitted == "scope=full\n"


def test_main_push_always_selects_full_even_for_docs(
    classifier_repository: tuple[Path, str], tmp_path: Path,
) -> None:
    repository, base = classifier_repository
    (repository / "README.md").write_text("changed\n", encoding="utf-8")
    head = _commit(repository, "prose push")
    completed, emitted = _run_classifier(repository, base, head, tmp_path, event="push")
    assert completed.returncode == 0, completed.stderr
    assert emitted == "scope=full\n"


def test_docs_command_checks_merge_tree_when_base_deleted_a_link_target(
    classifier_repository: tuple[Path, str], tmp_path: Path,
) -> None:
    repository, _ = classifier_repository
    (repository / "docs/guide.md").write_text("target\n", encoding="utf-8")
    (repository / "docs/plans").mkdir()
    (repository / "docs/plans/README.md").write_text("plans\n", encoding="utf-8")
    _write_manifest(repository)
    _commit(repository, "shared link target")
    _run_git(repository, "checkout", "-b", "feature")
    (repository / "README.md").write_text("[guide](docs/guide.md)\n", encoding="utf-8")
    head = _commit(repository, "prose links to existing target")
    scope.verify_docs(repository)
    _run_git(repository, "checkout", "main")
    (repository / "docs/guide.md").unlink()
    base = _commit(repository, "base deletes target")
    completed, emitted = _run_classifier(repository, base, head, tmp_path)
    assert completed.returncode == 0 and emitted == "scope=docs\n"
    _run_git(repository, "merge", "--no-commit", "--no-ff", head)
    command = _job("docs").split("      - run: ", 1)[1].strip()
    command = 'python3() { "$TEST_PYTHON" "$@"; }\n' + command
    checked = subprocess.run(
        [str(_bash()), "-c", command], cwd=repository, stdin=subprocess.DEVNULL,
        env={**os.environ, "TEST_PYTHON": Path(sys.executable).as_posix()},
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert checked.returncode != 0
    assert "missing relative link target" in checked.stderr


def test_base_without_classifier_selects_full(
    git_repository: tuple[Path, str], tmp_path: Path,
) -> None:
    repository, base = git_repository
    (repository / "README.md").write_text("changed\n", encoding="utf-8")
    head = _commit(repository, "introducing change")
    completed, emitted = _run_classifier(repository, base, head, tmp_path)
    assert completed.returncode == 0
    assert emitted == "scope=full\n"


def test_missing_git_head_refuses_classification_without_docs_output(
    classifier_repository: tuple[Path, str], tmp_path: Path,
) -> None:
    repository, base = classifier_repository
    completed, emitted = _run_classifier(repository, base, "f" * 40, tmp_path)
    assert completed.returncode != 0 and emitted == ""


def test_unknown_classifier_output_never_selects_docs(
    classifier_repository: tuple[Path, str], tmp_path: Path,
) -> None:
    repository, _ = classifier_repository
    (repository / "scripts/ci/m8_ci_scope.py").write_text('print("unknown")\n', encoding="utf-8")
    base = _commit(repository, "unknown base output")
    completed, emitted = _run_classifier(repository, base, base, tmp_path)
    assert completed.returncode != 0 and emitted == ""
