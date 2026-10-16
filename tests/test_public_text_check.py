"""The public-text check: complete coverage or failure, never echoing a match."""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.ci import check_public_text as check

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "public-text.yml"
SECRET = "Example-Operator"
PATTERNS = f"{SECRET}\n 10\\.9\\.8\\.\\d+ \n\n"
LEAK = f"/home/{SECRET.lower()}/m8-launch"


class FakeAPI:
    """Routes ``/repos/owner/repo/<path>`` to canned JSON pages or raw bytes."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes, self.seen = routes, []

    def __call__(self, request, timeout):
        assert request.get_header("Authorization") == "Bearer token"
        path = request.full_url.split("/repos/owner/repo/", 1)[1]
        self.seen.append(path)
        base, _, query = path.partition("?")
        number = re.search(r"(?:^|&)page=(\d+)", query)
        page = int(number.group(1)) if number else None
        value = self.routes.get(base, [] if page else None)
        if isinstance(value, bytes):
            return io.BytesIO(value)
        if page is not None and isinstance(value, list) and value and isinstance(value[0], list):
            value = value[page - 1] if page <= len(value) else []
        assert value is not None, f"unexpected request {path}"
        return io.BytesIO(json.dumps(value).encode())


def pull(number: int = 7, **fields) -> dict:
    return {"number": number, "title": "t", "body": "b",
            "head": {"ref": "feature", "sha": "abc"}, **fields}


def clean_pull_routes(number: int = 7, **extra) -> dict:
    return {f"pulls/{number}/commits": [], f"pulls/{number}/files": [], **extra}


def run(tmp_path, monkeypatch, capsys, args, routes=None, patterns=PATTERNS, token="token"):
    if patterns is None:
        monkeypatch.delenv("PUBLIC_TEXT_PATTERNS", raising=False)
    else:
        monkeypatch.setenv("PUBLIC_TEXT_PATTERNS", patterns)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", token)
    api = FakeAPI(routes or {})
    status = check.main(["check", *args], opener=api)
    out = capsys.readouterr().out
    assert SECRET.lower() not in out.lower() and "m8-launch" not in out and "http" not in out
    return status, out, api


def event_args(tmp_path, payload) -> list[str]:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return ["event", str(path)]


@pytest.mark.parametrize(("kind", "fields"), [
    ("issue", ("title", "body")),
    ("comment", ("body", "path", "diff_hunk")),
])
def test_every_user_written_event_field_is_scanned(tmp_path, monkeypatch, capsys, kind, fields):
    for field in fields:
        payload = {kind: {"id": 41, "number": 41, field: LEAK}}
        status, out, _ = run(tmp_path, monkeypatch, capsys, event_args(tmp_path, payload))
        assert status == 1 and f"{kind} 41 matches" in out
        payload = {kind: {"id": 41, "number": 41, field: "installed true, zero differences"}}
        assert run(tmp_path, monkeypatch, capsys, event_args(tmp_path, payload))[0] == 0


@pytest.mark.parametrize("where", ["title", "branch", "commit message", "commit author",
                                   "patch", "filename", "previous filename", "file contents"])
def test_pull_request_event_scans_branch_commits_and_every_file(
    tmp_path, monkeypatch, capsys, where,
):
    payload = {"pull_request": pull(title=LEAK if where == "title" else "t",
                                    head={"ref": LEAK if where == "branch" else "f", "sha": "abc"})}
    commit = {"commit": {"message": LEAK if where == "commit message" else "m",
                         "author": {"name": SECRET if where == "commit author" else "a",
                                    "email": "a@x"},
                         "committer": {"name": "c", "email": "c@x"}}}
    files = [{"filename": f"docs/{SECRET}.md" if where == "filename" else "docs/a.md",
              "previous_filename": f"old/{SECRET}" if where == "previous filename" else "",
              "status": "modified",
              "patch": LEAK if where == "patch" else ("+x" if where != "file contents" else None)}]
    routes = clean_pull_routes(**{"pulls/7/commits": [commit], "pulls/7/files": files,
                                  "contents/docs/a.md": LEAK.encode()})
    status, out, api = run(tmp_path, monkeypatch, capsys, event_args(tmp_path, payload), routes)
    assert status == 1 and " 7 matches" in out
    if where == "file contents":
        assert "contents/docs/a.md?ref=abc" in api.seen


def test_a_clean_pull_request_with_a_large_text_file_passes(tmp_path, monkeypatch, capsys):
    files = [{"filename": "big.txt", "status": "added", "patch": None},
             {"filename": "gone.txt", "status": "removed", "patch": None}]
    routes = clean_pull_routes(**{"pulls/7/files": files, "contents/big.txt": b"clean text\n"})
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"pull_request": pull()}), routes)
    assert (status, out) == (0, "")


def test_unscannable_binary_file_fails_closed(tmp_path, monkeypatch, capsys):
    files = [{"filename": "image.png", "status": "added", "patch": None}]
    routes = clean_pull_routes(**{"pulls/7/files": files, "contents/image.png": b"\x89PNG\xff\xfe"})
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"pull_request": pull()}), routes)
    assert status == 1 and "incomplete (Incomplete)" in out


def test_pull_request_event_without_token_fails_closed(tmp_path, monkeypatch, capsys):
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"pull_request": pull()}), token="")
    assert status == 1 and "incomplete (Incomplete)" in out


def test_listing_bound_binds_at_exactly_its_limit(tmp_path, monkeypatch, capsys):
    page = [{"filename": "a.txt", "status": "modified", "patch": "+x"}] * 100
    for pages, expected in ((check.MAX_PAGES - 1, 0), (check.MAX_PAGES, 1)):
        routes = clean_pull_routes(**{"pulls/7/files": [page] * pages + [page[:1]]})
        status, _, _ = run(tmp_path, monkeypatch, capsys,
                           event_args(tmp_path, {"pull_request": pull()}), routes)
        assert status == expected, pages


def test_sweep_covers_reviews_comments_and_updated_pull_requests(tmp_path, monkeypatch, capsys):
    now = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
    routes = {
        "issues": [{"number": 3, "title": "t", "body": "b"},
                   {"number": 7, "title": "t", "body": "b", "pull_request": {}}],
        "pulls/7": pull(),
        "pulls/7/reviews": [{"id": 900, "body": f"see {LEAK}"}],
        "issues/comments": [{"id": 51, "body": "ok"}],
        "pulls/comments": [{"id": 61, "body": "ok", "path": "a.py",
                            "diff_hunk": "@@ 10.9.8.4"}],
        **clean_pull_routes(),
    }
    api = FakeAPI(routes)
    found = check.findings(check.sweep(check.GitHub("owner/repo", "token", api), 120, now),
                           check.patterns(PATTERNS))
    assert found == [("review", "900"), ("review comment", "61")]
    assert "issues?state=all&since=2026-10-16T00:00:00Z&per_page=100&page=1" in api.seen


@pytest.mark.parametrize("patterns", (None, "", "  \n\n"))
def test_unset_patterns_fail_instead_of_passing(tmp_path, monkeypatch, capsys, patterns):
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"issue": {"number": 1}}), patterns=patterns)
    assert status == 1 and "PatternsNotConfigured" in out


def test_invalid_pattern_and_unknown_mode_report_only_a_class(tmp_path, monkeypatch, capsys):
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"issue": {"number": 1}}), patterns="([unclosed")
    assert status == 1 and "unclosed" not in out
    assert run(tmp_path, monkeypatch, capsys, ["other"])[0] == 1


def test_second_pattern_and_whitespace_lines_are_honoured():
    assert [p.pattern for p in check.patterns(PATTERNS)] == [SECRET, r"10\.9\.8\.\d+"]


def test_workflow_runs_only_default_branch_code_and_reads_only_the_secret():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    triggers = workflow.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    assert "pull_request_review" not in triggers and "\n  pull_request:" not in triggers
    for name in ("issues:", "issue_comment:", "pull_request_target:", "schedule:",
                 "workflow_dispatch:"):
        assert name in triggers
    steps = workflow.split("steps:", 1)[1]
    assert "ref: ${{ github.event.repository.default_branch }}" in steps
    assert "persist-credentials: false" in steps and "head" not in steps
    assert "PUBLIC_TEXT_PATTERNS: ${{ secrets.PUBLIC_TEXT_PATTERNS }}" in steps
    permissions = workflow.split("\npermissions:", 1)[1].split("\nconcurrency:", 1)[0]
    assert "write" not in permissions
