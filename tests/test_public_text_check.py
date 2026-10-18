"""The public-text check: complete coverage or failure, never echoing a match."""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import re
import signal
import threading
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path

import pytest
from scripts.ci import check_public_text as check

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "public-text.yml"
SECRET = "Example-Operator"
PATTERNS = f"{SECRET}\n 10\\.9\\.8\\.\\d+ \n\n"
LEAK = f"/home/{SECRET.lower()}/m8-launch"


class Response(io.BytesIO):
    """A response body with headers, as ``urlopen`` returns."""

    def __init__(self, body: bytes, link: str = "") -> None:
        super().__init__(body)
        self.headers = {"Link": link} if link else {}


# The repository and an empty activity listing, unless a test routes its own.
DEFAULT_ROUTES = {"": {"default_branch": "main"}, "activity": {"linked": [[]]}}


class FakeAPI:
    """Routes ``/repos/owner/repo/<path>`` to canned JSON pages or raw bytes.

    ``{"linked": [page, ...]}`` is a listing paged by ``Link`` cursors, as the
    activity listing is; an exception instance is raised, as a failed request.
    """

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes, self.seen = {**DEFAULT_ROUTES, **routes}, []

    def __call__(self, request, timeout):
        assert request.get_header("Authorization") == "Bearer token"
        located = re.fullmatch(r"https://api\.github\.com/(?:repos/owner/repo|repositories/1)/?(.*)",
                               request.full_url)
        assert located is not None, request.full_url
        path = located.group(1)
        self.seen.append(path)
        base, _, query = path.partition("?")
        number = re.search(r"(?:^|&)page=(\d+)", query)
        page = int(number.group(1)) if number else None
        value = self.routes.get(base)
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            value = value()
        if value is None and base.startswith("commits/") and "commits/*" in self.routes:
            value = self.routes["commits/*"]
        if value is None and page:
            value = []
        if isinstance(value, dict) and "linked" in value:
            cursor = re.search(r"(?:^|&)after=(\d+)", query)
            index = int(cursor.group(1)) if cursor else 0
            pages = value["linked"]
            link = ""
            if index + 1 < len(pages):
                origin = value.get("origin", "https://api.github.com/repositories/1/activity")
                link = f'<{origin}?per_page=100&after={index + 1}>; rel="next"'
            elif index and not value.get("linkless"):  # a later page links back
                link = '<https://api.github.com/repositories/1/activity?before=0>; rel="prev"'
            body = json.dumps(pages[index]).encode()
            return io.BytesIO(body) if value.get("headerless") else Response(body, link)
        if isinstance(value, dict) and "pages" in value:  # a paged object such as a commit
            value = value["pages"][page - 1] if page <= len(value["pages"]) else {"files": []}
        if isinstance(value, bytes):
            return io.BytesIO(value)
        if page is not None and isinstance(value, list) and value and isinstance(value[0], list):
            value = value[page - 1] if page <= len(value) else []
        assert value is not None, f"unexpected request {path}"
        return Response(json.dumps(value).encode())


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
    assert (status, out) == (0, "::notice::public text check made 4 API requests\n")


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


def merge_commit(sha: str, message: str, date: str | None = None) -> dict:
    dated = {"date": date} if date else {}
    return {"sha": sha, "commit": {"message": message,
                                   "author": {"name": "a", "email": "a@x", **dated},
                                   "committer": {"name": "c", "email": "c@x", **dated}}}


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
        "commits/dddddddddddddddd": {"files": []},
        "commits/cccccccccccccccc": {"files": [
            {"filename": "notes.md", "status": "added", "patch": f"+{LEAK}"}]},
        "comments": [{"id": 70, "body": LEAK, "updated_at": "2026-10-15T00:00:00Z"},
                     {"id": 71, "body": f"on a commit {LEAK}",
                      "updated_at": "2026-10-16T01:00:00Z"}],
        "issues": [{"number": 3, "title": "t", "body": "b"},
                   {"number": 7, "title": "t", "body": "b", "pull_request": {}}],
        "pulls/7/reviews": [{"id": 900, "body": f"see {LEAK}"}],
        "issues/7/timeline": [{"event": "labeled"}, {
            "event": "review_dismissed", "dismissed_review": {"dismissal_message": LEAK}}],
        "issues/comments": [{"id": 51, "body": "ok"}],
        "pulls/comments": [{"id": 61, "body": "ok", "path": "a.py",
                            "diff_hunk": "@@ 10.9.8.4"}],
        **clean_pull_routes(),
        # The pull request carries a branch commit, fetched once per sweep, and
        # an old-dated commit, still fetched: its date says nothing of its push.
        "pulls/7": pull(commits=2),
        "pulls/7/commits": [merge_commit("dddddddddddddddd", "old", "2026-01-01T00:00:00Z"),
                            merge_commit("cccccccccccccccc", "topic work")],
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
    assert sum(path.startswith("commits/dddddddddddddddd") for path in api.seen) == 1


def test_manual_backfill_skips_the_cursor_and_reports_its_request_count(
        tmp_path, monkeypatch, capsys):
    status, out, api = run(tmp_path, monkeypatch, capsys,
                           ["sweep", "--since", "2026-09-01T00:00:00+09:00"])
    assert status == 0
    assert not any(path.startswith("actions/") for path in api.seen)
    assert "issues?state=all&since=2026-08-31T15:00:00Z&per_page=100&page=1" in api.seen
    assert f"made {len(api.seen)} API requests" in out
    assert "PUBLIC_TEXT_SWEPT_THROUGH candidate" not in out
    for args in (["sweep", "--since", "yesterday"], ["sweep", "--since"],
                 ["sweep", "extra"], ["event"]):
        assert run(tmp_path, monkeypatch, capsys, args)[0] == 1, args


def test_cursor_starts_at_the_last_successful_sweep_and_never_skips():
    def runs(*entries):
        return check.GitHub("owner/repo", "token", FakeAPI({
            "actions/workflows/public-text.yml/runs": {"workflow_runs": [
                {"event": event, "run_started_at": started} for event, started in entries]}}))

    github = runs(("schedule", "2026-10-16T01:00:00Z"),
                  ("workflow_dispatch", "2026-10-16T02:00:00Z"),
                  ("issue_comment", "2026-10-16T05:00:00Z"))
    # A five-hour gap since the last scheduled sweep is scanned in full, with an
    # overlap; no other run, dispatched or event-triggered, advances the cursor.
    assert check.cursor(github) == datetime(2026, 10, 16, 0, 30, tzinfo=UTC)
    # An earlier manual backfill does not move it back; a later one moves it on.
    assert check.cursor(github, "2026-10-16T09:00:00+09:00") == datetime(
        2026, 10, 16, 0, 30, tzinfo=UTC)
    assert check.cursor(github, "2026-10-16T04:00:00Z") == datetime(
        2026, 10, 16, 3, 30, tzinfo=UTC)
    # Without either there is no window: never one measured back from now.
    assert check.cursor(runs(), "2026-10-01T00:00:00Z") == datetime(
        2026, 9, 30, 23, 30, tzinfo=UTC)
    for anchor in ("", "  "):
        with pytest.raises(check.Incomplete):
            check.cursor(runs(), anchor)


def test_a_failure_still_reports_what_was_already_found(tmp_path, monkeypatch, capsys):
    routes = {"actions/workflows/public-text.yml/runs": {"workflow_runs": []},
              "branches": [{"name": f"wip-{SECRET}"}], "commits": {"not": "a listing"}}
    monkeypatch.setenv("PUBLIC_TEXT_SWEPT_THROUGH", "2026-10-16T00:00:00Z")
    status, out, _ = run(tmp_path, monkeypatch, capsys, ["sweep"], routes)
    assert status == 1 and "incomplete" in out and "branch name" in out


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
    for name in ("issues:", "issue_comment:", "pull_request_target:", "schedule:"):
        assert name in triggers
    # Hourly: one window's requests must fit GITHUB_TOKEN's hourly budget.
    assert re.findall(r'cron: "(.*)"', triggers) == ["17 * * * *"]
    steps = workflow.split("steps:", 1)[1]
    assert "ref: ${{ github.event.repository.default_branch }}" in steps
    assert "persist-credentials: false" in steps and "head" not in steps
    assert "PUBLIC_TEXT_PATTERNS: ${{ secrets.PUBLIC_TEXT_PATTERNS }}" in steps
    permissions = workflow.split("\npermissions:", 1)[1].split("\njobs:", 1)[0]
    assert "write" not in permissions and "actions: read" in permissions


def test_every_event_run_executes_and_python_receives_the_runner_signals():
    """#221: no concurrency group cancels a pending event run, and ``exec``
    makes Python the step's entry process, which the runner signals."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    code = "\n".join(line for line in workflow.splitlines() if not line.lstrip().startswith("#"))
    assert "concurrency" not in code and "queue" not in code
    run_step = workflow.split("run: |", 1)[1]
    assert run_step.count("exec python3 -I -S -B scripts/ci/check_public_text.py ") == 2
    assert run_step.count("python3") == 2


# --- #216: branch commits by ref update, and tags --------------------------------

SINCE = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
P, X, Y, Q = ("1" * 40, "2" * 40, "3" * 40, "4" * 40)
ZERO = "0" * 40


def update(ref: str, before: str, after: str, at: str = "2026-10-16T02:00:00Z",
           kind: str = "push") -> dict:
    return {"id": 1, "ref": ref, "before": before, "after": after, "timestamp": at,
            "activity_type": kind}


def leaky_commit(sha: str) -> dict:
    """An old-dated commit whose own diff carries the leak."""
    return {f"commits/{sha}": {"files": [
        {"filename": "notes.md", "status": "added", "patch": f"+{LEAK}"}]}}


def comparison(*shas: str, total: int | None = None) -> dict:
    return {"total_commits": len(shas) if total is None else total,
            "commits": [merge_commit(sha, "old", "2026-01-01T00:00:00Z") for sha in shas]}


def swept(routes: dict, since=SINCE, now=NOW):
    api = FakeAPI(routes)
    try:
        found = check.findings(check.sweep(check.GitHub("owner/repo", "token", api), since, now),
                               check.patterns(PATTERNS))
    except check.Incomplete as error:  # an assertion, so a mutant's refusal counts as a kill
        pytest.fail(f"the sweep was incomplete: {error}")
    return found, api


def test_an_old_dated_commit_pushed_after_the_cursor_is_scanned():
    """The acceptance of #216: the date-filtered listing misses the commit; its
    push, recorded after the cursor, does not."""
    found, api = swept({
        "branches": [{"name": "topic"}],
        "commits": [],  # dated before the cursor, so the dated listing is empty
        "activity": {"linked": [[
            update("refs/heads/topic", P, X),
            # Before the cursor: an earlier sweep covered it, so it is not compared.
            update("refs/heads/topic", Q, P, at="2026-10-15T20:00:00Z"),
        ]]},
        f"compare/{P}...{X}": comparison(X),
        **leaky_commit(X),
    })
    assert found == [("branch file", X[:12])]
    assert "activity?per_page=100&time_period=day" in api.seen
    assert f"compare/{P}...{X}?per_page=100&page=1" in api.seen
    assert not any(path.startswith(f"compare/{Q}") for path in api.seen)


def test_activity_cursor_pages_are_followed_and_the_period_widens_with_the_window():
    found, api = swept({
        "activity": {"linked": [[update("refs/heads/a", Q, P)],
                                [update("refs/heads/b", P, X)]]},
        f"compare/{Q}...{P}": comparison(),
        f"compare/{P}...{X}": comparison(X),
        **leaky_commit(X),
    }, now=SINCE + timedelta(days=3))
    assert found == [("branch file", X[:12])]
    assert "activity?per_page=100&time_period=week" in api.seen
    assert "activity?per_page=100&after=1" in api.seen
    _, api = swept({}, now=SINCE + timedelta(days=8))
    assert "activity?per_page=100" in api.seen


def test_new_and_deleted_branches_and_the_default_branch_creation_are_covered():
    deleted = f"wip-{SECRET}"
    found, api = swept({
        "activity": {"linked": [[
            update("refs/heads/new", ZERO, X, kind="branch_creation"),
            update("refs/heads/main", ZERO, Y, kind="branch_creation"),
            update(f"refs/heads/{deleted}", P, ZERO, kind="branch_deletion"),
        ]]},
        f"compare/main...{X}": comparison(X),
        "commits": [merge_commit(Y, f"first {LEAK}")],
        **leaky_commit(X),
        f"commits/{Y}": {"files": []},
    })
    assert found == [("branch file", X[:12]), ("branch commit", Y[:12]),
                     ("branch name", hashlib.sha256(deleted.encode()).hexdigest()[:12])]
    # A new branch is compared with the default branch; the default branch's own
    # creation lists its whole history; a deletion is compared with nothing.
    assert f"commits?sha={Y}&per_page=100&page=1" in api.seen
    assert not any(path.startswith(f"compare/{P}") for path in api.seen)


def test_comparison_pages_are_followed_and_their_declared_count_met():
    clean = [merge_commit(f"{n:040x}", "clean") for n in range(100)]
    found, api = swept({
        "activity": {"linked": [[update("refs/heads/topic", P, X)]]},
        f"compare/{P}...{X}": {"pages": [
            {"total_commits": 101, "commits": clean},
            {"total_commits": 101, "commits": [merge_commit(X, "late")]}]},
        "commits/*": {"files": []},
        **leaky_commit(X),
    })
    assert found == [("branch file", X[:12])]
    assert f"compare/{P}...{X}?per_page=100&page=2" in api.seen


def test_a_commit_already_scanned_this_sweep_is_not_fetched_again():
    found, api = swept({
        "branches": [{"name": "topic"}],
        "commits": [merge_commit(X, "new")],
        "activity": {"linked": [[update("refs/heads/topic", P, X)]]},
        f"compare/{P}...{X}": comparison(X),
        **leaky_commit(X),
    })
    assert found == [("branch file", X[:12])]
    assert sum(path.startswith(f"commits/{X}") for path in api.seen) == 1


@pytest.mark.parametrize("failure", [
    "unknown previous head", "short comparison", "endless comparison", "malformed head",
    "endless activity", "link outside the API", "page without headers",
    "later page without links", "full page without next", "no default branch", "no timestamp",
])
def test_every_ref_update_failure_fails_closed(tmp_path, monkeypatch, capsys, failure):
    pushed = {"activity": {"linked": [[update("refs/heads/topic", P, X)]]}}
    routes = {
        "unknown previous head": {**pushed, f"compare/{P}...{X}": urllib.error.HTTPError(
            "https://api.github.com/", 404, "Not Found", Message(), None)},
        "short comparison": {**pushed, f"compare/{P}...{X}": comparison(X, total=2)},
        "endless comparison": {**pushed, f"compare/{P}...{X}": {"pages": [
            comparison(*[X] * 100, total=100 * check.MAX_PAGES)] * check.MAX_PAGES}},
        # Comparable if accepted: only the refusal itself fails it.
        "malformed head": {"activity": {"linked": [[update("refs/heads/topic", P, "head")]]},
                           f"compare/{P}...head": comparison()},
        "endless activity": {"activity": {"linked": [[]] * (check.MAX_PAGES + 1)}},
        "link outside the API": {"activity": {"linked": [[], []],
                                              "origin": "https://example.invalid/activity"}},
        "page without headers": {"activity": {"linked": [[]], "headerless": True}},
        "later page without links": {"activity": {"linked": [[], []], "linkless": True}},
        # GitHub omits ``next`` from a full last page too: refused, as noise.
        "full page without next": {"activity": {"linked": [
            [update("refs/heads/old", P, X, at="2026-10-15T00:00:00Z")] * 100]}},
        "no default branch": {"": {}},
        "no timestamp": {"activity": {"linked": [[{"ref": "refs/heads/topic", "before": P,
                                                    "after": X}]]}},
    }[failure]
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         ["sweep", "--since", "2026-10-16T00:00:00Z"],
                         {**routes, "commits/*": {"files": []}})
    # The refusal's own class: a fake's assertion over an unexpected request is not it.
    expected = {"unknown previous head": "HTTPError", "no timestamp": "KeyError"}
    assert status == 1, failure
    assert f"public text check incomplete ({expected.get(failure, 'Incomplete')})" in out


def test_a_failing_surface_does_not_hide_the_rest(tmp_path, monkeypatch, capsys):
    """An obstruction that recurs every sweep (here an unreachable previous
    head) still fails the run, but every other surface is scanned each time."""
    routes = {"activity": {"linked": [[update("refs/heads/topic", P, X)]]},
              f"compare/{P}...{X}": urllib.error.HTTPError(
                  "https://api.github.com/", 404, "Not Found", Message(), None),
              "comments": [{"id": 71, "body": LEAK, "updated_at": "2026-10-16T01:00:00Z"}]}
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         ["sweep", "--since", "2026-10-16T00:00:00Z"], routes)
    assert status == 1
    assert "::error::commit comment 71 matches a private pattern" in out
    assert "public text check incomplete (HTTPError)" in out


def test_every_tag_is_scanned_in_full():
    """Tags have no update record: each sweep reads every tag's name, every
    annotated tag's message, and each commit a tag reaches off the default branch."""
    leaky_tag = f"rel-{SECRET}"
    tag_object = "5" * 40
    found, api = swept({
        "tags": [{"name": "v1"}, {"name": leaky_tag}, {"name": "signed"}, {"name": "renamed"}],
        "git/ref/tags/v1": {"object": {"type": "commit", "sha": X}},
        f"git/ref/tags/{leaky_tag}": {"object": {"type": "commit", "sha": Y}},
        "git/ref/tags/signed": {"object": {"type": "tag", "sha": tag_object}},
        f"git/tags/{tag_object}": {"tag": "signed", "message": f"release {LEAK}",
                                   "tagger": {"name": "t"},
                                   "object": {"type": "commit", "sha": Q}},
        # An annotated tag's own name need not be its ref's.
        "git/ref/tags/renamed": {"object": {"type": "tag", "sha": "7" * 40}},
        f"git/tags/{'7' * 40}": {"tag": f"internal-{SECRET}", "message": "clean",
                                 "object": {"type": "commit", "sha": Q}},
        f"compare/main...{X}": comparison(X),
        f"compare/main...{Y}": comparison(),
        f"compare/main...{Q}": comparison(),
        **leaky_commit(X),
    })

    def digest(name: str) -> str:
        return hashlib.sha256(name.encode()).hexdigest()[:12]

    assert found == [("existing tag", digest("v1")), ("tag file", X[:12]),
                     ("existing tag", digest(leaky_tag)), ("tag name", digest(leaky_tag)),
                     ("existing tag", digest("signed")), ("tag message", digest("signed")),
                     ("existing tag", digest("renamed")), ("tag message", digest("renamed"))]
    assert "tags?per_page=100&page=1" in api.seen


def missing(status=404):
    return urllib.error.HTTPError("https://api.github.com/", status, "missing", Message(), None)


def test_all_history_backfill_has_no_date_filter_and_pins_branch_heads(
        tmp_path, monkeypatch, capsys):
    """Old-dated reachable history is read even if activity no longer lists it."""
    class Started(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(check, "datetime", Started)
    routes = {"branches": [{"name": "topic", "commit": {"sha": X}}],
              "commits": [merge_commit(P, "old", "2000-01-01T00:00:00Z")],
              f"commits/{P}": {"files": []}}
    status, out, api = run(tmp_path, monkeypatch, capsys,
                           ["sweep", "--since", "2026-10-16T00:00:00Z", "--all-history"],
                           routes)
    assert status == 0 and "PUBLIC_TEXT_SWEPT_THROUGH candidate" in out
    assert "candidate 2026-10-16T03:00:00Z" in out
    assert f"commits?sha={X}&per_page=100&page=1" in api.seen
    assert all("since=" not in path for path in api.seen if path.startswith("commits?"))
    assert f"commits/{P}?per_page=100&page=1" in api.seen
    assert not any(path.startswith("actions/") for path in api.seen)
    routes[f"commits/{P}"] = leaky_commit(P)[f"commits/{P}"]
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         ["sweep", "--since", "2026-10-16T00:00:00Z", "--all-history"], routes)
    assert status == 1 and f"branch file {P[:12]} matches" in out
    assert "PUBLIC_TEXT_SWEPT_THROUGH candidate" not in out


def test_all_history_tags_list_full_history_and_are_unconditional_findings(
        tmp_path, monkeypatch, capsys):
    routes = {"tags": [{"name": "clean-release"}],
              "git/ref/tags/clean-release": {"object": {"type": "commit", "sha": X}},
              "commits": [merge_commit(P, "old")], f"commits/{P}": {"files": []}}
    status, out, api = run(tmp_path, monkeypatch, capsys,
                           ["sweep", "--since", "2026-10-16T00:00:00Z", "--all-history"], routes)
    assert status == 1 and "existing tag " in out and "tag exists" in out
    assert "clean-release" not in out and "matches a private pattern" not in out
    assert f"commits?sha={X}&per_page=100&page=1" in api.seen
    assert not any(path.startswith("compare/") for path in api.seen)
    assert "PUBLIC_TEXT_SWEPT_THROUGH candidate" not in out


def test_missing_force_push_prior_head_is_a_gap_and_later_updates_are_scanned(
        tmp_path, monkeypatch, capsys):
    routes = {"activity": {"linked": [[
        update("refs/heads/topic", P, X, kind="force_push"),
        update("refs/heads/next", X, Y)]]},
        f"compare/{P}...{X}": missing(), f"commits/{P}": missing(),
        f"commits/{X}": {"sha": X, "files": []},
        "commits": [merge_commit(X, "current")],
        f"compare/{X}...{Y}": comparison(Y), **leaky_commit(Y),
        "comments": [{"id": 71, "body": LEAK, "updated_at": "2026-10-16T01:00:00Z"}]}
    status, out, api = run(tmp_path, monkeypatch, capsys,
                           ["sweep", "--since", "2026-10-16T00:00:00Z"], routes)
    assert status == 1 and f":{P[:12]}:{X[:12]}" in out
    assert "coverage not established" in out and "check incomplete" not in out
    assert "traversal-complete; coverage-incomplete" in out
    assert f"branch file {Y[:12]} matches" in out and "commit comment 71 matches" in out
    assert f"commits?sha={X}&per_page=100&page=1" in api.seen
    assert "PUBLIC_TEXT_SWEPT_THROUGH candidate" not in out


def test_history_gaps_keep_distinct_activity_identities_and_fallback_failures(
        tmp_path, monkeypatch, capsys):
    first = update("refs/heads/topic", P, X, kind="force_push")
    second = {**first, "id": 2}
    routes = {"activity": {"linked": [[first, second]]},
              f"compare/{P}...{X}": missing(), f"commits/{P}": missing(),
              f"commits/{X}": {"sha": X, "files": []}, "commits": []}
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         ["sweep", "--since", "2026-10-16T00:00:00Z", "--all-history"], routes)
    assert status == 1 and out.count("::error::history gap ") == 2
    assert "traversal-complete; coverage-incomplete" in out
    assert "PUBLIC_TEXT_SWEPT_THROUGH candidate" not in out
    routes["commits"] = missing(403)
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         ["sweep", "--since", "2026-10-16T00:00:00Z", "--all-history"], routes)
    assert status == 1 and "::error::history gap " in out
    assert "public text check incomplete (HTTPError)" in out
    assert "traversal-complete" not in out and "PUBLIC_TEXT_SWEPT_THROUGH candidate" not in out


@pytest.mark.parametrize("cause", ["head missing", "prior readable", "prior forbidden",
                                    "comparison forbidden", "current malformed", "file missing"])
def test_only_a_proven_missing_force_push_prior_head_becomes_a_gap(
        tmp_path, monkeypatch, capsys, cause):
    routes = {"activity": {"linked": [[update("refs/heads/topic", P, X, kind="force_push")]]},
              f"compare/{P}...{X}": missing(),
              f"commits/{X}": {"sha": X, "files": []}, f"commits/{P}": missing()}
    if cause == "head missing":
        routes[f"commits/{X}"] = missing()
    elif cause == "prior readable":
        routes[f"commits/{P}"] = {"sha": P, "files": []}
    elif cause == "prior forbidden":
        routes[f"commits/{P}"] = missing(403)
    elif cause == "comparison forbidden":
        routes[f"compare/{P}...{X}"] = missing(403)
    elif cause == "current malformed":
        routes[f"commits/{X}"] = {"files": []}
    else:
        routes[f"compare/{P}...{X}"] = comparison(X)
        routes[f"commits/{X}"] = missing()
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         ["sweep", "--since", "2026-10-16T00:00:00Z"], routes)
    assert status == 1 and "public text check incomplete" in out
    assert "history gap" not in out and "PUBLIC_TEXT_SWEPT_THROUGH candidate" not in out


@pytest.mark.parametrize("cause", ["bound", "error", "cancel"])
def test_backfill_failure_never_offers_a_cursor_candidate(tmp_path, monkeypatch, capsys, cause):
    routes = {"branches": [{"name": "topic", "commit": {"sha": X}}],
              "commits": {"bound": [[merge_commit(X, "clean")] * 100] * check.MAX_PAGES,
                          "error": missing(403), "cancel": Stop()}[cause],
              f"commits/{X}": {"files": []}}
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         ["sweep", "--since", "2026-10-16T00:00:00Z", "--all-history"], routes)
    assert status == 1 and "check incomplete" in out
    assert "PUBLIC_TEXT_SWEPT_THROUGH candidate" not in out


@pytest.mark.parametrize("target", ["blob", "tree", "too deep", "missing"])
def test_a_tag_that_reaches_no_commit_fails_closed(tmp_path, monkeypatch, capsys, target):
    nested = "6" * 40
    named = {"blob": {"type": "blob", "sha": nested}, "tree": {"type": "tree", "sha": nested},
             "too deep": {"type": "tag", "sha": nested}, "missing": None}[target]
    routes = {"tags": [{"name": "v1"}], "git/ref/tags/v1": {"object": named},
              # A tag naming itself never reaches a commit: bounded, then refused.
              f"git/tags/{nested}": {"message": "m", "object": {"type": "tag", "sha": nested}},
              # Comparable if accepted: only the refusal itself fails it.
              f"compare/main...{nested}": comparison()}
    status, out, _ = run(tmp_path, monkeypatch, capsys,
                         ["sweep", "--since", "2026-10-16T00:00:00Z"], routes)
    assert status == 1 and "public text check incomplete (Incomplete)" in out


# --- #221: a cancelled or timed-out scan still reports ---------------------------

class Stop(BaseException):
    """Not an ``Exception``: as a cancellation ends the scan."""


def test_a_scan_stopped_by_a_base_exception_still_reports_what_it_found(
        tmp_path, monkeypatch, capsys):
    payload = {"issue": {"number": 41, "body": LEAK}, "pull_request": pull()}
    try:
        status, out, _ = run(tmp_path, monkeypatch, capsys, event_args(tmp_path, payload),
                             {"pulls/7/commits": Stop()})
    except Stop:  # an assertion, not an escaped BaseException, so it counts as a failure
        pytest.fail("the stop escaped main unreported")
    assert status == 1
    lines = out.splitlines()
    assert lines[:2] == ["::error::issue 41 matches a private pattern",
                         "::error::public text check incomplete (Stop)"]


@pytest.mark.parametrize("name", ["SIGINT", "SIGTERM"])
def test_the_runner_signals_end_the_scan_as_cancelled_after_its_findings(
        tmp_path, monkeypatch, capsys, name):
    """The runner cancels a step with SIGINT, then SIGTERM: either ends the scan
    as an incomplete run that has printed its findings."""
    number = getattr(signal, name)
    before = signal.getsignal(number)
    installed = []

    def interrupt():
        installed.append(signal.getsignal(number))
        if installed[0] is not before:  # never under pytest's own handler or the default
            signal.raise_signal(number)
        return []

    payload = {"issue": {"number": 41, "body": LEAK}, "pull_request": pull()}
    try:
        status, out, _ = run(tmp_path, monkeypatch, capsys, event_args(tmp_path, payload),
                             {"pulls/7/commits": interrupt})
    except BaseException as error:  # an escape is the failure under test
        pytest.fail(f"{type(error).__name__} escaped main unreported")
    assert len(installed) == 1 and installed[0] is not before, "main installs no handler"
    assert status == 1
    assert out.splitlines()[:2] == ["::error::issue 41 matches a private pattern",
                                    "::error::public text check incomplete (Cancelled)"]
    assert signal.getsignal(number) == before


# --- #229: the token never leaves the API ----------------------------------------

class Recorder(http.server.ThreadingHTTPServer):
    """A local server that answers every request with ``reply`` and records it."""

    def __init__(self, reply) -> None:
        super().__init__(("127.0.0.1", 0), self.Handler)
        self.reply, self.requests = reply, []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.requests.append((self.path, self.headers.get("Authorization")))
            status, headers, body = self.server.reply
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_refused_and_the_token_never_reaches_its_target(
        tmp_path, monkeypatch, capsys, status):
    """A followed redirect would forward ``Authorization`` to the new host."""
    elsewhere = Recorder((200, {}, b"{}"))
    api = Recorder((status, {"Location": f"{elsewhere.url}/stolen"}, b""))
    try:
        monkeypatch.setattr(check, "API", api.url)
        with pytest.raises(check.Incomplete):
            check.GitHub("owner/repo", "secret-229").get("")
        assert api.requests == [("/repos/owner/repo", "Bearer secret-229")]
        assert elsewhere.requests == []
        monkeypatch.setenv("PUBLIC_TEXT_PATTERNS", PATTERNS)
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_TOKEN", "secret-229")
        assert check.main(["check", "sweep", "--since", "2026-10-16T00:00:00Z"]) == 1
        out = capsys.readouterr()
        assert "public text check incomplete (Incomplete)" in out.out
        # The report names the failure, never the token or either address.
        for leaked in ("secret-229", api.url, elsewhere.url, "127.0.0.1"):
            assert leaked not in out.out + out.err
        assert elsewhere.requests == []
    finally:
        for server in (api, elsewhere):
            server.shutdown()
            server.server_close()


def test_a_cancellation_ignores_the_runners_next_signal():
    """The runner follows SIGINT with SIGTERM: once cancelled, the report and
    the handler restoration that follow are not interrupted again."""
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        with pytest.raises(check.Cancelled):
            check._cancel(signal.SIGINT, None)
        assert [signal.getsignal(number) for number in previous] == [signal.SIG_IGN] * 2
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
