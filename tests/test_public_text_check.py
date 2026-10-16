"""The public-text check: complete coverage or failure, never echoing a match."""

from __future__ import annotations

import hashlib
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
        value = self.routes.get(base)
        if value is None and base.startswith("commits/") and "commits/*" in self.routes:
            value = self.routes["commits/*"]
        if value is None and page:
            value = []
        if isinstance(value, dict) and "pages" in value:  # a paged object such as a commit
            value = value["pages"][page - 1] if page <= len(value["pages"]) else {"files": []}
        if isinstance(value, bytes):
            return io.BytesIO(value)
        if page is not None and isinstance(value, list) and value and isinstance(value[0], list):
            value = value[page - 1] if page <= len(value) else []
        assert value is not None, f"unexpected request {path}"
        return io.BytesIO(json.dumps(value).encode())


def pull(number: int = 7, **fields) -> dict:
    return {"number": number, "title": "t", "body": "b", "commits": 0,
            "head": {"ref": "feature", "sha": "abc"}, **fields}


def clean_pull_routes(number: int = 7, **extra) -> dict:
    return {f"pulls/{number}/commits": [], **extra}


def one_commit_pull(files: list[dict], **extra) -> dict:
    """Routes for a PR whose single commit changes ``files``."""
    commit = {"sha": "c1", "commit": {"message": "m", "author": {"name": "a", "email": "a@x"},
                                      "committer": {"name": "c", "email": "c@x"}}}
    return clean_pull_routes(**{"pulls/7/commits": [commit],
                                "commits/c1": {"files": files, "parents": [{"sha": "p1"}]},
                                **extra})


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
    payload = {"pull_request": pull(title=LEAK if where == "title" else "t", commits=1,
                                    head={"ref": LEAK if where == "branch" else "f", "sha": "abc"})}
    commit = {"sha": "c1", "commit": {
        "message": LEAK if where == "commit message" else "m",
        "author": {"name": SECRET if where == "commit author" else "a", "email": "a@x"},
        "committer": {"name": "c", "email": "c@x"}}}
    files = [{"filename": f"docs/{SECRET}.md" if where == "filename" else "docs/a.md",
              "previous_filename": f"old/{SECRET}" if where == "previous filename" else "",
              "status": "modified",
              "patch": LEAK if where == "patch" else ("+x" if where != "file contents" else None)}]
    routes = clean_pull_routes(**{"pulls/7/commits": [commit],
                                  "commits/c1": {"files": files, "parents": [{"sha": "p1"}]},
                                  "contents/docs/a.md": LEAK.encode()})
    status, out, api = run(tmp_path, monkeypatch, capsys, event_args(tmp_path, payload), routes)
    assert status == 1 and " 7 matches" in out
    if where == "file contents":
        assert "contents/docs/a.md?ref=c1" in api.seen


def test_text_added_then_removed_inside_a_pull_request_is_found(tmp_path, monkeypatch, capsys):
    """The PR's final diff is clean; its first commit's diff is not."""
    commits = [{"sha": sha, "commit": {"message": "m", "author": {}, "committer": {}}}
               for sha in ("c1", "c2")]
    routes = clean_pull_routes(**{
        "pulls/7/commits": commits,
        "commits/c1": {"files": [{"filename": "a.md", "status": "added", "patch": f"+{LEAK}"}]},
        "commits/c2": {"files": [{"filename": "a.md", "status": "modified",
                                  "patch": f"-{LEAK}\n+clean"}]},
    })
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"pull_request": pull(commits=2)}), routes)
    assert status == 1 and "pull request file 7 matches" in out


def test_a_clean_pull_request_with_a_large_text_file_passes(tmp_path, monkeypatch, capsys):
    files = [{"filename": "big.txt", "status": "added", "patch": None},
             {"filename": "gone.txt", "status": "removed", "patch": None}]
    routes = one_commit_pull(files, **{"contents/big.txt": b"clean text\n",
                                       "contents/gone.txt": b"also clean\n"})
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"pull_request": pull(commits=1)}), routes)
    assert (status, out) == (0, "")


def test_a_large_modification_is_read_on_both_sides(tmp_path, monkeypatch, capsys):
    """Text deleted from a patchless file is still public in the parent."""
    files = [{"filename": "big.md", "status": "modified", "patch": None}]
    seen_refs = []

    class Sided(FakeAPI):
        def __call__(self, request, timeout):
            if "contents/big.md" in request.full_url:
                ref = request.full_url.rsplit("ref=", 1)[1]
                seen_refs.append(ref)
                return io.BytesIO((LEAK if ref == "p1" else "clean now").encode())
            return super().__call__(request, timeout)

    monkeypatch.setenv("PUBLIC_TEXT_PATTERNS", PATTERNS)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    api = Sided(one_commit_pull(files))
    status = check.main(["check", *event_args(tmp_path, {"pull_request": pull(commits=1)})],
                        opener=api)
    assert status == 1 and "pull request file 7 matches" in capsys.readouterr().out
    assert seen_refs == ["c1", "p1"]


def test_a_large_removed_file_is_read_at_its_parent(tmp_path, monkeypatch, capsys):
    """Deleted without a patch, the file still lives in the parent commit."""
    files = [{"filename": "old.md", "status": "removed", "patch": None}]
    routes = one_commit_pull(files, **{"contents/old.md": LEAK.encode()})
    status, out, api = run(tmp_path, monkeypatch, capsys,
                           event_args(tmp_path, {"pull_request": pull(commits=1)}), routes)
    assert status == 1 and "pull request file 7 matches" in out
    assert "contents/old.md?ref=p1" in api.seen
    orphan = clean_pull_routes(**{
        "pulls/7/commits": [{"sha": "c1", "commit": {}}],
        "commits/c1": {"files": files, "parents": []}})
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"pull_request": pull(commits=1)}), orphan)
    assert status == 1 and "incomplete (Incomplete)" in out


@pytest.mark.parametrize("files", ["binary", "missing"])
def test_unscannable_commit_files_fail_closed(tmp_path, monkeypatch, capsys, files):
    listing = {
        "binary": [{"filename": "image.png", "status": "added", "patch": None}],
        "missing": None,
    }[files]
    routes = one_commit_pull(listing, **{"contents/image.png": b"\x89PNG\xff\xfe"})
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"pull_request": pull(commits=1)}), routes)
    assert status == 1 and "incomplete (Incomplete)" in out


def test_commit_file_pages_are_followed_and_bounded(tmp_path, monkeypatch, capsys):
    """The commit endpoint pages its files: a leak on page 2 is found, and a
    listing that never ends within the page bound fails closed."""
    full = [{"filename": "a.txt", "status": "added", "patch": "+x"}] * 100
    leaked = [{"filename": "b.txt", "status": "added", "patch": f"+{LEAK}"}]
    commit = {"sha": "c1", "commit": {"message": "m", "author": {}, "committer": {}}}
    paged = clean_pull_routes(**{"pulls/7/commits": [commit],
                                 "commits/c1": {"pages": [{"files": full}, {"files": leaked}]}})
    status, out, api = run(tmp_path, monkeypatch, capsys,
                           event_args(tmp_path, {"pull_request": pull(commits=1)}), paged)
    assert status == 1 and "pull request file 7 matches" in out
    assert "commits/c1?per_page=100&page=2" in api.seen
    endless = clean_pull_routes(**{"pulls/7/commits": [commit], "commits/c1": {
        "pages": [{"files": full}] * check.MAX_PAGES}})
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"pull_request": pull(commits=1)}), endless)
    assert status == 1 and "incomplete (Incomplete)" in out


def test_pull_request_event_without_token_fails_closed(tmp_path, monkeypatch, capsys):
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"pull_request": pull()}), token="")
    assert status == 1 and "incomplete (Incomplete)" in out


def test_listing_bound_binds_at_exactly_its_limit(tmp_path, monkeypatch, capsys):
    page = [{"sha": "c", "commit": {"message": "m", "author": {}, "committer": {}}}] * 100
    for pages, expected in ((check.MAX_PAGES - 1, 0), (check.MAX_PAGES, 1)):
        routes = clean_pull_routes(**{"pulls/7/commits": [page] * pages + [page[:1]],
                                      "commits/*": {"files": []}})
        declared = pull(commits=100 * pages + 1)
        status, _, _ = run(tmp_path, monkeypatch, capsys,
                           event_args(tmp_path, {"pull_request": declared}), routes)
        assert status == expected, pages


def merge_commit(sha: str, message: str) -> dict:
    return {"sha": sha, "commit": {"message": message, "author": {"name": "a", "email": "a@x"},
                                   "committer": {"name": "c", "email": "c@x"}}}


def test_sweep_covers_commits_comments_reviews_and_updated_pull_requests():
    since = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
    routes = {
        "branches": [{"name": "main"}, {"name": "topic/x"}, {"name": f"wip-{SECRET}"}],
        # The same listing answers both branches: shared commits are scanned once.
        "commits": [merge_commit("aaaaaaaaaaaaaaaa", "clean"),
                    merge_commit("bbbbbbbbbbbbbbbb", f"squash: {LEAK} (#9)"),
                    merge_commit("cccccccccccccccc", "topic work")],
        "commits/aaaaaaaaaaaaaaaa": {"files": []},
        "commits/bbbbbbbbbbbbbbbb": {"files": []},
        "commits/cccccccccccccccc": {"files": [
            {"filename": "notes.md", "status": "added", "patch": f"+{LEAK}"}]},
        "comments": [{"id": 70, "body": LEAK, "updated_at": "2026-10-15T00:00:00Z"},
                     {"id": 71, "body": f"on a commit {LEAK}",
                      "updated_at": "2026-10-16T01:00:00Z"}],
        "issues": [{"number": 3, "title": "t", "body": "b"},
                   {"number": 7, "title": "t", "body": "b", "pull_request": {}}],
        "pulls/7": pull(),
        "pulls/7/reviews": [{"id": 900, "body": f"see {LEAK}"}],
        "issues/7/timeline": [{"event": "labeled"}, {
            "event": "review_dismissed", "dismissed_review": {"dismissal_message": LEAK}}],
        "issues/comments": [{"id": 51, "body": "ok"}],
        "pulls/comments": [{"id": 61, "body": "ok", "path": "a.py",
                            "diff_hunk": "@@ 10.9.8.4"}],
        **clean_pull_routes(),
    }
    api = FakeAPI(routes)
    found = check.findings(check.sweep(check.GitHub("owner/repo", "token", api), since),
                           check.patterns(PATTERNS))
    # The old commit comment (70) is outside the window; the rest is covered,
    # including a topic branch's pushed file.
    leaky_branch = hashlib.sha256(f"wip-{SECRET}".encode()).hexdigest()[:12]
    assert found == [("branch commit", "bbbbbbbbbbbb"), ("branch file", "cccccccccccc"),
                     ("branch name", leaky_branch),
                     ("commit comment", "71"), ("review", "900"), ("review dismissal", "7"),
                     ("review comment", "61")]
    assert "issues?state=all&since=2026-10-16T00:00:00Z&per_page=100&page=1" in api.seen
    assert "commits?sha=topic%2Fx&since=2026-10-16T00:00:00Z&per_page=100&page=1" in api.seen
    assert sum(path.startswith("commits/cccccccccccccccc") for path in api.seen) == 1


def test_cursor_starts_at_the_last_successful_sweep_and_never_skips():
    now = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)

    def runs(*entries):
        return FakeAPI({"actions/workflows/public-text.yml/runs": {"workflow_runs": [
            {"event": event, "run_started_at": started} for event, started in entries]}})

    github = check.GitHub("owner/repo", "token", runs(
        ("schedule", "2026-10-16T01:00:00Z"), ("workflow_dispatch", "2026-10-16T02:00:00Z"),
        ("issue_comment", "2026-10-16T05:00:00Z")))
    # A five-hour gap since the last scheduled sweep is scanned in full, with an
    # overlap; no other run, dispatched or event-triggered, advances the cursor.
    assert check.cursor(github, now) == datetime(2026, 10, 16, 0, 30, tzinfo=UTC)
    assert check.cursor(check.GitHub("owner/repo", "token", runs()), now) == (
        now - check.FIRST_WINDOW)


@pytest.mark.parametrize("declared", [251, 0, None])
def test_a_capped_or_unknown_commit_listing_fails_closed(tmp_path, monkeypatch, capsys,
                                                         declared):
    commits = [merge_commit(f"{n:040x}", "clean") for n in range(3)]
    routes = clean_pull_routes(**{"pulls/7/commits": commits, "commits/*": {"files": []}})
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         event_args(tmp_path, {"pull_request": pull(commits=declared)}), routes)
    assert status == 1 and "incomplete (Incomplete)" in out
    accepted = run(tmp_path, monkeypatch, capsys,
                   event_args(tmp_path, {"pull_request": pull(commits=3)}), routes)
    assert accepted[0] == 0


def test_commit_comment_event_is_scanned(tmp_path, monkeypatch, capsys):
    payload = {"comment": {"id": 72, "body": "fine", "path": f"docs/{SECRET}.md"}}
    status, out, _ = run(tmp_path, monkeypatch, capsys, event_args(tmp_path, payload))
    assert status == 1 and "comment 72 matches" in out


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
    assert "workflow_dispatch" not in triggers
    for name in ("issues:", "issue_comment:", "commit_comment:", "pull_request_target:",
                 "schedule:"):
        assert name in triggers
    steps = workflow.split("steps:", 1)[1]
    assert "ref: ${{ github.event.repository.default_branch }}" in steps
    assert "persist-credentials: false" in steps and "head" not in steps
    assert "PUBLIC_TEXT_PATTERNS: ${{ secrets.PUBLIC_TEXT_PATTERNS }}" in steps
    permissions = workflow.split("\npermissions:", 1)[1].split("\nconcurrency:", 1)[0]
    assert "write" not in permissions and "actions: read" in permissions
