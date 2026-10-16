"""The public-text check: every user-written field and PR patch, never echoing a match."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
from scripts.ci import check_public_text as check

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "public-text.yml"
SECRET = "Example-Operator"
PATTERNS = f"{SECRET}\n 10\\.9\\.8\\.\\d+ \n\n"


def event(**items: dict) -> dict:
    return {"repository": {"full_name": "owner/repo"}, **items}


def run(tmp_path: Path, monkeypatch, payload: dict, patterns: str | None = PATTERNS,
        capsys=None) -> tuple[int, str]:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    if patterns is None:
        monkeypatch.delenv("PUBLIC_TEXT_PATTERNS", raising=False)
    else:
        monkeypatch.setenv("PUBLIC_TEXT_PATTERNS", patterns)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    status = check.main(["check", str(path)])
    return status, capsys.readouterr().out if capsys else ""


@pytest.mark.parametrize("kind", ("issue", "comment", "review", "pull_request"))
@pytest.mark.parametrize("field", ("title", "body"))
def test_every_user_written_field_is_scanned(tmp_path, monkeypatch, capsys, kind, field):
    url = f"https://github.com/owner/repo/{kind}/1"
    leaked = {"html_url": url, field: f"path /home/{SECRET.lower()}/m8-launch"}
    status, out = run(tmp_path, monkeypatch, event(**{kind: leaked}), capsys=capsys)
    assert status == 1 and url in out
    assert SECRET.lower() not in out.lower() and "m8-launch" not in out
    clean = {"html_url": url, field: "the controller verified installed true"}
    assert run(tmp_path, monkeypatch, event(**{kind: clean}), capsys=capsys)[0] == 0


def test_second_pattern_and_whitespace_lines_are_honoured(tmp_path, monkeypatch, capsys):
    payload = event(comment={"html_url": "u", "body": "address 10.9.8.200 in a listing"})
    assert run(tmp_path, monkeypatch, payload, capsys=capsys)[0] == 1
    assert [p.pattern for p in check.patterns(PATTERNS)] == [SECRET, r"10\.9\.8\.\d+"]


@pytest.mark.parametrize("patterns", (None, "", "  \n\n"))
def test_unset_patterns_fail_instead_of_passing(tmp_path, monkeypatch, capsys, patterns):
    status, out = run(tmp_path, monkeypatch, event(comment={"body": "anything"}), patterns,
                      capsys)
    assert status == 1 and "PatternsNotConfigured" in out


def test_invalid_pattern_reports_only_its_class(tmp_path, monkeypatch, capsys):
    status, out = run(tmp_path, monkeypatch, event(comment={"body": "x"}), "([unclosed",
                      capsys)
    assert status == 1 and "unclosed" not in out


def _opener(pages: list[list[dict]], seen: list[str]):
    def opener(request, timeout):
        seen.append(request.full_url)
        assert request.get_header("Authorization") == "Bearer token"
        page = int(re.search(r"page=(\d+)$", request.full_url).group(1))
        return io.BytesIO(json.dumps(pages[page - 1]).encode())
    return opener


def test_pull_request_patches_are_scanned_across_pages(tmp_path):
    pull = {"number": 7, "html_url": "https://github.com/owner/repo/pull/7", "body": "ok"}
    clean = [{"filename": f"f{n}.py", "patch": "+x = 1"} for n in range(100)]
    leaked = [{"filename": "docs/run.md", "patch": f"+ssh {SECRET}@host"}]
    seen: list[str] = []
    found = check.findings(event(pull_request=pull), check.patterns(PATTERNS), "token",
                           _opener([clean, leaked], seen))
    assert found == [("pull_request file", pull["html_url"])]
    assert len(seen) == 2
    assert seen[0].endswith("/repos/owner/repo/pulls/7/files?per_page=100&page=1")
    assert check.findings(event(pull_request=pull), check.patterns(PATTERNS), "token",
                          _opener([clean[:3]], [])) == []


def test_a_filename_alone_can_leak(tmp_path):
    pull = {"number": 1, "html_url": "u"}
    files = [[{"filename": f"captures/{SECRET}/listing.txt", "patch": None}]]
    assert check.findings(event(pull_request=pull), check.patterns(PATTERNS), "token",
                          _opener(files, [])) == [("pull_request file", "u")]


def test_unbounded_patch_listing_is_a_failure_not_a_partial_pass():
    pull = {"number": 1, "html_url": "u"}
    full = [{"filename": "f.py", "patch": "+x"}] * 100
    with pytest.raises(ValueError, match="too many"):
        check.findings(event(pull_request=pull), check.patterns(PATTERNS), "token",
                       _opener([full] * check.MAX_PATCH_PAGES, []))


def test_workflow_never_checks_out_the_head_and_reads_only_the_secret():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in workflow and "head" not in workflow.split("steps:", 1)[1]
    assert "ref: ${{ github.event.repository.default_branch }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "PUBLIC_TEXT_PATTERNS: ${{ secrets.PUBLIC_TEXT_PATTERNS }}" in workflow
    assert "contents: read" in workflow and "pull-requests: read" in workflow
    assert "write" not in workflow.split("permissions:", 1)[1].split("jobs:", 1)[0]
    for event_name in ("issues:", "issue_comment:", "pull_request_review:",
                       "pull_request_review_comment:"):
        assert event_name in workflow
