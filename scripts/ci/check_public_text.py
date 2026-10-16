"""Flag public repository text that matches a private pattern; never print the match.

Run by ``.github/workflows/public-text.yml`` from the default branch only:

- ``event PATH`` scans one issue, comment or pull-request event as it happens
  (commit comments raise no workflow event; only the sweep sees them);
- ``sweep`` (hourly) scans everything updated since its cursor, less an
  overlap: every branch's new commits with their own diffs (including squash
  and merge messages), commit comments, issue and pull-request titles and
  bodies, issue comments, reviews, review dismissals, review comments, and the
  new commits of updated pull requests with their own diffs. It also covers
  text that no event reaches, such as reviews and anything posted with
  ``GITHUB_TOKEN``. A delayed or dropped schedule widens the next window; it
  never skips one.
- ``sweep --since TIME`` is a manual backfill from an ISO time, run locally with
  a personal token; the workflow never passes it.

The cursor is the later of the last successful scheduled sweep's start and the
``PUBLIC_TEXT_SWEPT_THROUGH`` repository variable, which the owner sets to the
start time of a successful manual backfill. With neither, the sweep fails: it
never invents a window. ``GITHUB_TOKEN`` allows 1,000 requests per hour per
repository, so each commit is fetched once per sweep and every API-backed run
prints its request count. A backlog too large for one hour fails every run
until a manual backfill moves the variable.

Patterns come from the ``PUBLIC_TEXT_PATTERNS`` secret, one case-insensitive
regular expression per line, so private values never enter the repository.
Findings print only a kind and a numeric id: no text, URL, filename or pattern.
Anything that cannot be scanned completely, such as a missing token, a
non-UTF-8 file or an over-long listing, is a failure, never a pass. This is
detection after posting: GitHub keeps edited text in the item's history until
that revision is deleted by hand. Only current text is scanned, never edit
history. Text posted and then edited away with ``GITHUB_TOKEN``, which raises no
event, before the next sweep is therefore missed; such a workflow must run this
check before posting (AGENTS.md "Public text"). The sweep selects commits by
date, so a commit dated before the cursor but first pushed after it is missed
by the sweep until a ref-update cursor replaces the date filter (#216); in a
pull request, the ``pull_request_target`` event scans every commit. Commit
comments cannot be filtered by the API, so all of them are listed each sweep,
within the page bound.
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
        self.requests = 0

    def get(self, path: str, raw: bool = False) -> object:
        self.requests += 1
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


def utc(value: str) -> datetime:
    """An ISO time as UTC; a time without an offset is taken as UTC."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dated_since(commit: dict, since: str) -> bool:
    """Whether a commit's author or committer date is at or after ``since``.

    An undated commit counts as new, so it is scanned rather than skipped.
    """
    detail = commit.get("commit") or {}
    dates = [str((detail.get(role) or {}).get("date") or "") for role in ("author", "committer")]
    return not all(dates) or any(_stamp(utc(date)) >= since for date in dates)


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
                # Large or binary diffs carry no patch: scan the file itself on
                # both sides, or fail. Text deleted from a file, or a removed
                # file, still lives in the parent.
                status = changed.get("status")
                sides = []
                if status != "removed":
                    sides.append((str(changed.get("filename", "")), sha))
                if status != "added":
                    parents = detail.get("parents") or []
                    if len(parents) != 1:
                        raise Incomplete("a patchless change has no single parent to read")
                    before = changed.get("previous_filename") or changed.get("filename", "")
                    sides.append((str(before), str(parents[0].get("sha", ""))))
                texts = []
                for name, ref in sides:
                    data = github.get(f"contents/{urllib.parse.quote(name)}?ref={ref}", raw=True)
                    try:
                        texts.append(data.decode("utf-8"))  # type: ignore[union-attr]
                    except UnicodeDecodeError:
                        raise Incomplete("a changed file is not text") from None
                patch = "\n".join(texts)
            yield f"{kind} file", ident, names + "\n" + str(patch or "")
        if len(files) < 100:
            return
    raise Incomplete("commit file listing exceeds the page bound")


def pull_request(github: GitHub, pull: dict, seen: set[str] | None = None,
                 since: str | None = None) -> Iterator[Item]:
    """A pull request's branch, commits and every commit's diff, completely.

    A commit already in ``seen`` was scanned in full this sweep and is skipped.
    With ``since`` (the sweep), only commits dated at or after it are fetched;
    the event that announced each push scanned the whole pull request.
    """
    number = str(pull["number"])
    head = pull.get("head") or {}
    yield "pull request branch", number, str(head.get("ref") or "")
    commits = list(github.pages(f"pulls/{number}/commits"))
    # The endpoint stops at 250 commits; a short listing is not completeness.
    if type(pull.get("commits")) is not int or len(commits) != pull["commits"]:
        raise Incomplete("pull request commit listing is not complete")
    seen = set() if seen is None else seen
    for commit in commits:
        sha = str(commit.get("sha", ""))
        if sha not in seen and (since is None or _dated_since(commit, since)):
            yield from commit_items(github, commit, "pull request", number)
            seen.add(sha)  # only once its scan is complete


def event(payload: dict, github: GitHub | None) -> Iterator[Item]:
    yield from _fields("issue", payload.get("issue") or {}, "title", "body")
    yield from _fields("comment", payload.get("comment") or {}, "body", "path", "diff_hunk")
    pull = payload.get("pull_request")
    if isinstance(pull, dict):
        yield from _fields("pull request", pull, "title", "body")
        if github is None:
            raise Incomplete("pull request event without API access")
        yield from pull_request(github, pull)


def cursor(github: GitHub, anchor: str = "") -> datetime:
    """Where the sweep starts, less an overlap: the later of the last successful
    scheduled sweep's start and ``anchor``, a manual backfill's start time.

    The workflow's own run history is the cursor, so a delayed or dropped
    schedule widens the next window instead of skipping it, and a failing sweep
    never advances it. With neither a success nor an anchor there is no window
    to scan, which is a failure: a window measured back from now would let
    unscanned text slide out of coverage.
    """
    runs = github.get(
        "actions/workflows/public-text.yml/runs?status=success&event=schedule&per_page=100")
    assert isinstance(runs, dict)
    starts = [utc(run["run_started_at"]) for run in runs.get("workflow_runs", [])
              if run.get("event") == "schedule"]
    if anchor.strip():
        starts.append(utc(anchor))
    if not starts:
        raise Incomplete("no successful sweep and no PUBLIC_TEXT_SWEPT_THROUGH")
    return max(starts) - OVERLAP


def sweep(github: GitHub, since_time: datetime) -> Iterator[Item]:
    since = _stamp(since_time)
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
                yield from commit_items(github, commit, "branch", sha[:12])
                seen.add(sha)  # only once its scan is complete
    for comment in github.pages("comments"):
        if str(comment.get("updated_at", "")) >= since:
            yield from _fields("commit comment", comment, "body", "path")
    for issue in github.pages(f"issues?state=all&since={since}"):
        yield from _fields("issue", issue, "title", "body")
        if "pull_request" in issue:
            pull = github.get(f"pulls/{issue['number']}")
            assert isinstance(pull, dict)
            yield from pull_request(github, pull, seen, since)
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


def findings(items: Iterator[Item], compiled: list[re.Pattern[str]],
             found: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """Matching (kind, id) pairs, appended to ``found`` as they are met, so a
    later failure does not hide what was already found."""
    found = [] if found is None else found
    for kind, ident, text in items:
        if any(pattern.search(text) for pattern in compiled) and (kind, ident) not in found:
            found.append((kind, ident))
    return found


def main(argv: list[str], opener: Callable = urllib.request.urlopen) -> int:
    github: GitHub | None = None
    found: list[tuple[str, str]] = []
    complete = False
    try:
        compiled = patterns(os.environ.get("PUBLIC_TEXT_PATTERNS", ""))
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GITHUB_TOKEN", "")
        if argv[1:] == ["sweep"] or (argv[1:3] == ["sweep", "--since"] and len(argv) == 4):
            github = GitHub(repository, token, opener)
            if len(argv) == 4:
                since = utc(argv[3])
            else:
                since = cursor(github, os.environ.get("PUBLIC_TEXT_SWEPT_THROUGH", ""))
            items = sweep(github, since)
        elif argv[1:2] == ["event"] and len(argv) == 3:
            payload = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
            github = GitHub(repository, token, opener) if token else None
            items = event(payload, github)
        else:
            raise Incomplete("usage: check_public_text.py event PATH | sweep [--since TIME]")
        findings(items, compiled, found)
        complete = True
    except Exception as error:  # report the class, never the content
        print(f"::error::public text check incomplete ({type(error).__name__})")
    for kind, ident in found:
        print(f"::error::{kind} {ident} matches a private pattern")
    if github is not None:
        print(f"::notice::public text check made {github.requests} API requests")
    return 0 if complete and not found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
