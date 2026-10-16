"""Flag public repository text that matches a private pattern; never print the match.

Run by ``.github/workflows/public-text.yml`` from the default branch only:

- ``event PATH`` scans one issue, comment, commit comment or pull-request event
  as it happens;
- ``sweep`` (scheduled) scans everything updated since the last successful
  scheduled sweep, less an overlap: every branch's new commits with their own
  diffs (including squash and merge messages), commit comments, issue and
  pull-request titles and bodies, issue comments, reviews, review dismissals,
  review comments, and pull-request commits with their own diffs.
  It also covers text that no event reaches, such as reviews and anything
  posted with ``GITHUB_TOKEN``. A delayed or dropped schedule widens the next
  window; it never skips one.

Patterns come from the ``PUBLIC_TEXT_PATTERNS`` secret, one case-insensitive
regular expression per line, so private values never enter the repository.
Findings print only a kind and a numeric id: no text, URL, filename or pattern.
Anything that cannot be scanned completely, such as a missing token, a
non-UTF-8 file or an over-long listing, is a failure, never a pass. This is
detection after posting: GitHub keeps edited text in the item's history until
that revision is deleted by hand. Only current text is scanned, never edit
history. Text posted and then edited away with ``GITHUB_TOKEN``, which raises no
event, before the next sweep is therefore missed; such a workflow must run this
check before posting (AGENTS.md "Public text"). Branch commits are listed by
commit date, so a commit dated before the cursor but first pushed after it is
also missed until a ref-update cursor replaces the date filter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

API = "https://api.github.com"
MAX_PAGES = 30
OVERLAP = timedelta(minutes=30)

FIRST_WINDOW = timedelta(days=30)
Item = tuple[str, str, str]  # (kind, numeric id, text)


class Incomplete(ValueError):
    """Something could not be scanned completely: a failure, never a pass."""


class PatternsNotConfigured(Incomplete):
    """The secret is unset or empty."""


def patterns(raw: str) -> list[re.Pattern[str]]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        raise PatternsNotConfigured
    return [re.compile(line, re.IGNORECASE) for line in lines]


class GitHub:
    """Read-only REST access with the workflow token; JSON or raw bytes."""

    def __init__(self, repository: str, token: str, opener: Callable = urllib.request.urlopen):
        if not repository or not token:
            raise Incomplete("repository or token missing")
        self.repository, self.token, self.opener = repository, token, opener

    def get(self, path: str, raw: bool = False) -> object:
        request = urllib.request.Request(f"{API}/repos/{self.repository}/{path}", headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        })
        with self.opener(request, timeout=30) as response:
            body = response.read()
        return body if raw else json.loads(body)

    def pages(self, path: str) -> Iterator[dict]:
        joiner = "&" if "?" in path else "?"
        for page in range(1, MAX_PAGES + 1):
            items = self.get(f"{path}{joiner}per_page=100&page={page}")
            assert isinstance(items, list)
            yield from items
            if len(items) < 100:
                return
        raise Incomplete("listing exceeds the page bound")


def _fields(kind: str, item: dict, *names: str) -> Iterator[Item]:
    ident = str(item.get("number") or item.get("id") or "?")
    text = "\n".join(str(item.get(name) or "") for name in names)
    if text.strip():
        yield kind, ident, text


def _commit_text(commit: dict) -> str:
    detail = commit.get("commit") or {}
    people = [detail.get(role) or {} for role in ("author", "committer")]
    return "\n".join([str(detail.get("message") or "")]
                     + [f"{p.get('name', '')} {p.get('email', '')}" for p in people])


def commit_items(github: GitHub, commit: dict, kind: str, ident: str) -> Iterator[Item]:
    """A commit's message, identities and its own complete diff.

    Each commit's own diff, never a final cumulative one: text added by one
    commit and removed by the next stays public in history. The file list is
    paged (the endpoint returns 30 files by default and at most 3000).
    """
    yield f"{kind} commit", ident, _commit_text(commit)
    sha = str(commit.get("sha", ""))
    for page in range(1, MAX_PAGES + 1):
        detail = github.get(f"commits/{sha}?per_page=100&page={page}")
        assert isinstance(detail, dict)
        files = detail.get("files")
        if not isinstance(files, list):
            raise Incomplete("commit file listing is not complete")
        for changed in files:
            names = f"{changed.get('filename', '')}\n{changed.get('previous_filename', '')}"
            patch = changed.get("patch")
            if patch is None:
                # Large or binary diffs carry no patch: scan the file itself, or
                # fail. A removed file is read at the parent, where it still lives.
                ref = sha
                if changed.get("status") == "removed":
                    parents = detail.get("parents") or []
                    if len(parents) != 1:
                        raise Incomplete("a removed file has no single parent to read")
                    ref = str(parents[0].get("sha", ""))
                path = urllib.parse.quote(str(changed.get("filename", "")))
                data = github.get(f"contents/{path}?ref={ref}", raw=True)
                try:
                    patch = data.decode("utf-8")  # type: ignore[union-attr]
                except UnicodeDecodeError:
                    raise Incomplete("a changed file is not text") from None
            yield f"{kind} file", ident, names + "\n" + str(patch or "")
        if len(files) < 100:
            return
    raise Incomplete("commit file listing exceeds the page bound")


def pull_request(github: GitHub, pull: dict) -> Iterator[Item]:
    """A pull request's branch, commits and every commit's diff, completely."""
    number = str(pull["number"])
    head = pull.get("head") or {}
    yield "pull request branch", number, str(head.get("ref") or "")
    commits = list(github.pages(f"pulls/{number}/commits"))
    # The endpoint stops at 250 commits; a short listing is not completeness.
    if type(pull.get("commits")) is not int or len(commits) != pull["commits"]:
        raise Incomplete("pull request commit listing is not complete")
    for commit in commits:
        yield from commit_items(github, commit, "pull request", number)


def event(payload: dict, github: GitHub | None) -> Iterator[Item]:
    yield from _fields("issue", payload.get("issue") or {}, "title", "body")
    yield from _fields("comment", payload.get("comment") or {}, "body", "path", "diff_hunk")
    pull = payload.get("pull_request")
    if isinstance(pull, dict):
        yield from _fields("pull request", pull, "title", "body")
        if github is None:
            raise Incomplete("pull request event without API access")
        yield from pull_request(github, pull)


def cursor(github: GitHub, now: datetime | None = None) -> datetime:
    """Where the sweep starts: the last successful sweep's start, less an overlap.

    The workflow's own run history is the cursor, so a delayed or dropped
    schedule widens the next window instead of skipping it, and a failing sweep
    never advances it. Without any earlier success, the first window is
    ``FIRST_WINDOW``.
    """
    runs = github.get(
        "actions/workflows/public-text.yml/runs?status=success&event=schedule&per_page=100")
    assert isinstance(runs, dict)
    starts = [run["run_started_at"] for run in runs.get("workflow_runs", [])
              if run.get("event") == "schedule"]
    if not starts:
        return (now or datetime.now(UTC)) - FIRST_WINDOW
    latest = max(datetime.fromisoformat(start.replace("Z", "+00:00")) for start in starts)
    return latest - OVERLAP


def sweep(github: GitHub, since_time: datetime) -> Iterator[Item]:
    since = since_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    seen: set[str] = set()
    for branch in github.pages("branches"):
        # Every branch, not only the default: a pushed topic branch is public,
        # and squash or merge commits carry text written at merge time. The
        # name is public too; it is reported by a digest, never spelled out.
        raw_name = str(branch.get("name", ""))
        yield "branch name", hashlib.sha256(raw_name.encode()).hexdigest()[:12], raw_name
        name = urllib.parse.quote(raw_name, safe="")
        for commit in github.pages(f"commits?sha={name}&since={since}"):
            sha = str(commit.get("sha", ""))
            if sha not in seen:
                seen.add(sha)
                yield from commit_items(github, commit, "branch", sha[:12])
    for comment in github.pages("comments"):
        if str(comment.get("updated_at", "")) >= since:
            yield from _fields("commit comment", comment, "body", "path")
    for issue in github.pages(f"issues?state=all&since={since}"):
        yield from _fields("issue", issue, "title", "body")
        if "pull_request" in issue:
            pull = github.get(f"pulls/{issue['number']}")
            assert isinstance(pull, dict)
            yield from pull_request(github, pull)
            for review in github.pages(f"pulls/{issue['number']}/reviews"):
                yield from _fields("review", review, "body")
            for event in github.pages(f"issues/{issue['number']}/timeline"):
                dismissed = event.get("dismissed_review") or {}
                if dismissed.get("dismissal_message"):
                    yield ("review dismissal", str(issue["number"]),
                           str(dismissed["dismissal_message"]))
    for comment in github.pages(f"issues/comments?since={since}"):
        yield from _fields("comment", comment, "body")
    for comment in github.pages(f"pulls/comments?since={since}"):
        yield from _fields("review comment", comment, "body", "path", "diff_hunk")


def findings(items: Iterator[Item], compiled: list[re.Pattern[str]]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for kind, ident, text in items:
        if any(pattern.search(text) for pattern in compiled) and (kind, ident) not in found:
            found.append((kind, ident))
    return found


def main(argv: list[str], opener: Callable = urllib.request.urlopen) -> int:
    try:
        compiled = patterns(os.environ.get("PUBLIC_TEXT_PATTERNS", ""))
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GITHUB_TOKEN", "")
        if argv[1:] == ["sweep"]:
            github = GitHub(repository, token, opener)
            items = sweep(github, cursor(github))
        elif argv[1:2] == ["event"]:
            payload = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
            github = GitHub(repository, token, opener) if token else None
            items = event(payload, github)
        else:
            raise Incomplete("usage: check_public_text.py event PATH | sweep")
        found = findings(items, compiled)
    except Exception as error:  # report the class, never the content
        print(f"::error::public text check incomplete ({type(error).__name__})")
        return 1
    for kind, ident in found:
        print(f"::error::{kind} {ident} matches a private pattern")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
