"""Flag public repository text that matches a private pattern; never print the match.

Run by ``.github/workflows/public-text.yml`` from the default branch only:

- ``event PATH`` scans one issue, comment or pull-request event as it happens
  (commit comments raise no workflow event; only the sweep sees them);
- ``sweep`` (hourly) scans everything updated since its cursor, less an
  overlap: every commit a branch update exposed, with its own diff (including
  squash and merge messages), every tag, commit comments, issue and
  pull-request titles and bodies, issue comments, reviews, review dismissals,
  review comments, and every commit of an updated pull request with its own
  diff. It also covers text that no event reaches, such as reviews and
  anything posted with ``GITHUB_TOKEN``. A delayed or dropped schedule widens
  the next window; it never skips one.
- ``sweep --since TIME --all-history`` is a manual backfill, run locally with
  a personal token; it reads all reachable branch and tag history without a
  commit-date filter, plus both endpoints of destructive branch updates
  selected by TIME. TIME still selects activity and non-Git text. Without
  ``--all-history``, ``--since`` selects the normal sweep's time window.

The cursor is the later of the last successful scheduled sweep's start and the
``PUBLIC_TEXT_SWEPT_THROUGH`` repository variable, which the owner sets to the
start time of a successful manual backfill. A clean, completed manual scan
with ``--all-history`` prints that start as a candidate; it never writes the variable. Findings,
coverage gaps, errors and cancellation never produce a candidate. With neither,
the sweep fails: it never invents a window. ``GITHUB_TOKEN`` allows 1,000 requests per hour per
repository, so each commit is fetched once per sweep and every API-backed run
prints its request count. A backlog too large for one hour fails every run
until a manual backfill moves the variable.

Patterns come from the ``PUBLIC_TEXT_PATTERNS`` secret, one case-insensitive
regular expression per line, so private values never enter the repository.
Findings print only a kind and an identifier: an issue or pull-request number,
an item id, a commit SHA prefix, or a SHA-256 digest prefix of a branch or tag
name. Never text, a URL, a filename or a pattern. Each finding is printed as it
is made, so a run that fails, is cancelled or times out has still reported
what it found: the runner's SIGINT and SIGTERM end the scan as an incomplete
run, not a silent one. Anything that cannot be scanned completely, such as a
missing token, a non-UTF-8 file or an over-long listing, is a failure, never a
pass; the sweep still scans its other surfaces first. This is detection after
posting: GitHub keeps edited text in the item's history until that revision is
deleted by hand. Only current text is scanned, never edit history. Text posted
and then edited away with ``GITHUB_TOKEN``, which raises no event, before the
next sweep is therefore missed; such a workflow must run this check before
posting (AGENTS.md "Public text").

Branch commits are selected by ref update, not by date (#216). The repository
activity listing records every push, force push, branch creation and merge with
the ref's heads before and after; each update since the cursor is compared, so
an old-dated commit pushed late is scanned. A new branch is compared with the
default branch, whose own history earlier sweeps covered; the creation of the
default branch itself scans its whole history. A previous head that can no
longer be compared is reported as a coverage gap when the API confirms an
unavailable force-push prior head and a readable current head. A 404 establishes
only unavailability through this authenticated API, not permanent deletion;
token visibility and retention can affect it. Its readable history
and later updates are still scanned. A gap makes the run non-successful and
never advances the cursor; it is not a claim of coverage. Other comparison
errors fail the traversal. In all-history mode, deletions and force pushes
instead resolve the prior SHA and scan its complete history plus the nonzero
after-head history directly. A prior lookup's 404 is a gap even for a deletion;
downstream listing and file errors remain incomplete traversals. A retry with
the same TIME checks the same selected updates even when they predate the new
run's start. Commits dated in the window are still listed
on every branch, as a second source. The activity listing carries branches
only, so tags are scanned in full on every sweep: each name, each annotated
tag's own name, message and tagger, and every commit a tag reaches that the
default branch does not. Every existing tag is also an unconditional finding
reported by digest, supporting the repository's tag restriction. A tag naming
anything but a commit fails the run. A pull request's commits are all scanned
whenever it is updated. Commit comments
cannot be filtered by the API, so all of them are listed each sweep, within the
page bound.

Not established: how soon a ref update appears in the activity listing, and how
long it stays there. An update that appears only after the window's overlap has
passed is caught by the date listing if its commits are dated in a window, and
otherwise missed. Sweeps before #216 selected by date alone, so an old-dated
commit pushed before the first ref-update sweep stays missed until a local
``sweep --since TIME --all-history`` backfill covers reachable history regardless
of commit dates. Unreachable objects absent from reported activity and deleted
tags are not recovered by it; the tag ruleset is a separate owner action.
Pinned branch heads and the activity pass are not a repository snapshot: an
unreported destructive update can still escape the census and activity pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

API ="https://api.github.com"
MAX_PAGES = 30
MAX_TAG_DEPTH = 10
OVERLAP = timedelta(minutes=30)
NO_COMMIT = "0" * 40
SHA = re.compile(r"[0-9a-f]{40}")
# The activity listing's narrowest periods, as the API defines them ("day" is the
# past 24 hours, "week" the past 168), each less an hour for clock skew. A
# longer window lists all activity; entries are filtered by time either way.
ACTIVITY_PERIODS = (("day", timedelta(hours=23)), ("week", timedelta(hours=167)))
Item = tuple[str, str, str]  # (kind, identifier, text)


class Incomplete(ValueError):
    """Something could not be scanned completely: a failure, never a pass."""


class PatternsNotConfigured(Incomplete):
    """The secret is unset or empty."""


class MissingPriorHead(Incomplete):
    """A force-push comparison has a readable head and an unavailable prior head."""


class Cancelled(BaseException):
    """The runner stopped the scan (a cancellation or the job's timeout).

    A ``BaseException``, like ``KeyboardInterrupt``: it ends the scan wherever it
    is, and ``main`` reports it as an incomplete run."""


def _cancel(signum: int, frame: object) -> None:
    # Once: the report and handler restoration that follow are not interrupted
    # by the runner's second signal. ``main`` restores the previous handlers.
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, signal.SIG_IGN)
    raise Cancelled


def patterns(raw: str) -> list[re.Pattern[str]]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        raise PatternsNotConfigured
    return [re.compile(line, re.IGNORECASE) for line in lines]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect (#229).

    The default handler follows a redirect with every header but the body's,
    ``Authorization`` included, so a redirect to another host would be sent the
    token. The API endpoints read here do not redirect: one that does is
    incomplete, and its response is never read."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Incomplete("a request was redirected")


def open_api(request: urllib.request.Request, timeout: float):
    """``urlopen`` that never follows a redirect: the token stays with the API."""
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


class GitHub:
    """Read-only REST access with the workflow token; JSON or raw bytes."""

    def __init__(self, repository: str, token: str, opener: Callable = open_api):
        if not repository or not token:
            raise Incomplete("repository or token missing")
        self.repository, self.token, self.opener = repository, token, opener
        self.requests = 0

    def _open(self, url: str, raw: bool = False) -> tuple[bytes, Any]:
        self.requests += 1
        request = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        })
        with self.opener(request, timeout=30) as response:
            return response.read(), getattr(response, "headers", None)

    def get(self, path: str, raw: bool = False) -> object:
        """``path`` under the repository; the empty path is the repository."""
        url = f"{API}/repos/{self.repository}" + (f"/{path}" if path else "")
        body, _ = self._open(url, raw)
        return body if raw else json.loads(body)

    def linked(self, path: str) -> Iterator[dict]:
        """A listing paged by the ``Link`` header's ``next`` cursor, bounded.

        A page without headers, or a next page outside the API, is incomplete:
        the token is never sent elsewhere. A missing link is not read as the
        last page unless it can be: every later page carries a ``Link`` (its
        ``prev``), and a full page without ``next`` is refused. That refuses a
        listing whose length is an exact multiple of a page, too: a noisy
        failure that the next sweep's longer window clears, never a miss."""
        url = f"{API}/repos/{self.repository}/{path}"
        for page in range(MAX_PAGES):
            body, headers = self._open(url)
            items = json.loads(body)
            if headers is None or not isinstance(items, list):
                raise Incomplete("a linked listing page is not complete")
            link = headers.get("Link") or ""
            if page and not link:
                raise Incomplete("a linked listing page has lost its links")
            yield from items
            following = re.search(r'<([^<>]+)>\s*;\s*rel="next"', link)
            if following is None:
                if len(items) >= 100:
                    raise Incomplete("a full linked listing page has no next link")
                return
            url = following.group(1)
            if not url.startswith(f"{API}/"):
                raise Incomplete("a linked listing leaves the API")
        raise Incomplete("listing exceeds the page bound")

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


def pull_request(github: GitHub, pull: dict, seen: set[str] | None = None) -> Iterator[Item]:
    """A pull request's branch, commits and every commit's diff, completely.

    A commit already in ``seen`` was scanned in full this sweep and is skipped.
    Commit dates are not trusted to skip the rest: an old-dated commit can be
    pushed late, and its push event's run may have failed.
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
        if sha not in seen:
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


def _digest(name: str) -> str:
    """A public name's report identifier: never the name itself."""
    return hashlib.sha256(name.encode()).hexdigest()[:12]


def _unseen(github: GitHub, commits: Iterable[dict], kind: str, seen: set[str]) -> Iterator[Item]:
    for commit in commits:
        sha = str(commit.get("sha", ""))
        if sha not in seen:
            yield from commit_items(github, commit, kind, sha[:12])
            seen.add(sha)  # only once its scan is complete


def _sha(value: object) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise Incomplete("a ref update names no commit")
    return value


def compared(github: GitHub, base: str, head: str,
             force_push: bool = False) -> Iterator[dict]:
    """Every commit reachable from ``head`` and not from ``base``, completely.

    The comparison pages its commits, each yielded as it is listed; the count
    the last page declares must then be met. A ``base`` the API cannot
    resolve, such as a force-pushed-away head that is no longer stored, is an
    error, never an empty range. For a force push only, affirmative resolution
    checks distinguish an unavailable prior head as ``MissingPriorHead``."""
    path = f"compare/{urllib.parse.quote(base)}...{urllib.parse.quote(head)}"
    count = 0
    for page in range(1, MAX_PAGES + 1):
        try:
            detail = github.get(f"{path}?per_page=100&page={page}")
        except urllib.error.HTTPError as error:
            if error.code != 404 or not force_push:
                raise
            # A comparison's 404 does not establish which object is unavailable.
            # Only this request, never a later file read, can become a gap.
            current = github.get(f"commits/{head}")
            if not isinstance(current, dict) or current.get("sha") != head:
                raise Incomplete("a force-push current head is not resolved") from None
            try:
                github.get(f"commits/{base}")
            except urllib.error.HTTPError as missing:
                if missing.code != 404:
                    raise
            else:
                raise error
            raise MissingPriorHead from None
        listed = detail.get("commits") if isinstance(detail, dict) else None
        if not isinstance(listed, list):
            raise Incomplete("comparison commit listing is not complete")
        count += len(listed)
        yield from listed
        if len(listed) < 100:
            break
    else:
        raise Incomplete("comparison exceeds the page bound")
    total = detail.get("total_commits") if isinstance(detail, dict) else None
    if type(total) is not int or count != total:
        raise Incomplete("comparison commit listing is not complete")


def _history_gap(update: dict, before: str, after: str) -> Item:
    activity_id = update.get("id")
    if not ((type(activity_id) is int and activity_id >= 0)
            or (isinstance(activity_id, str) and 0 < len(activity_id) <= 128)):
        raise Incomplete("a history gap has no bounded activity identity")
    ident = f"{_digest(str(activity_id))}:{before[:12]}:{after[:12]}"
    return "history gap", ident, ""


def pushed(github: GitHub, since_time: datetime, now: datetime, default: str,
           seen: set[str], all_history: bool = False) -> Iterator[Item]:
    """Every commit a branch update exposed since ``since_time``, by ref update.

    Each update's heads are compared, whatever its commits' dates: an
    old-dated commit pushed late is in its push's range. A created branch is
    compared with the default branch; the default branch's own creation scans
    its whole history. All-history backfills scan both endpoints of destructive
    updates selected by the window, including on retries: the branch census may
    have happened after history disappeared. Other sweeps scan a deletion's name.
    """
    elapsed = now - since_time
    period = next((name for name, span in ACTIVITY_PERIODS if elapsed <= span), None)
    query = "activity?per_page=100" + (f"&time_period={period}" if period else "")
    for update in github.linked(query):
        if utc(str(update["timestamp"])) < since_time:
            continue
        ref = str(update.get("ref", ""))
        branch = ref.removeprefix("refs/heads/")
        yield ("branch name" if branch != ref else "ref name"), _digest(branch), branch
        after = _sha(update.get("after"))
        if all_history and (after == NO_COMMIT or update.get("activity_type") == "force_push"):
            before = _sha(update.get("before"))
            if before == NO_COMMIT:
                raise Incomplete("a destructive ref update has no prior head")
            try:
                prior = github.get(f"commits/{before}")
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
                yield _history_gap(update, before, after)
            else:
                if not isinstance(prior, dict) or prior.get("sha") != before:
                    raise Incomplete("a destructive ref update prior head is not resolved")
                yield from _unseen(github, github.pages(f"commits?sha={before}"), "branch", seen)
            if after != NO_COMMIT:
                yield from _unseen(github, github.pages(f"commits?sha={after}"), "branch", seen)
            continue
        if after == NO_COMMIT:
            continue
        before = _sha(update.get("before"))
        if before != NO_COMMIT:
            commits = compared(github, before, after,
                               force_push=update.get("activity_type") == "force_push")
        elif branch == default:
            commits = github.pages(f"commits?sha={after}")
        else:
            commits = compared(github, default, after)
        try:
            yield from _unseen(github, commits, "branch", seen)
        except MissingPriorHead:
            yield _history_gap(update, before, after)
            # Salvage all readable history, without pretending it covers the
            # unavailable side of the force push. Later updates still run.
            yield from _unseen(github, github.pages(f"commits?sha={after}"), "branch", seen)


def tagged(github: GitHub, default: str, seen: set[str],
           all_history: bool = False) -> Iterator[Item]:
    """Every tag, in full: its name, each annotated tag's message and tagger,
    and every commit it reaches that the default branch does not.

    Tags have no update record to select from, so every sweep reports all of
    them. A tag that names anything but a commit, at the end of at most
    ``MAX_TAG_DEPTH`` annotated tags, fails the scan."""
    for tag in github.pages("tags"):
        name = str(tag.get("name", ""))
        yield "existing tag", _digest(name), ""
        yield "tag name", _digest(name), name
        target = github.get(f"git/ref/tags/{urllib.parse.quote(name)}")
        named = (target.get("object") if isinstance(target, dict) else None) or {}
        for _ in range(MAX_TAG_DEPTH):
            if named.get("type") != "tag":
                break
            annotated = github.get(f"git/tags/{_sha(named.get('sha'))}")
            assert isinstance(annotated, dict)
            tagger = annotated.get("tagger") or {}
            # The object's own name can differ from the ref's: scan it too.
            yield "tag message", _digest(name), "\n".join([
                str(annotated.get("tag") or ""), str(annotated.get("message") or ""),
                f"{tagger.get('name', '')} {tagger.get('email', '')}"])
            named = annotated.get("object") or {}
        if named.get("type") != "commit":
            raise Incomplete("a tag names something other than a commit")
        head = _sha(named.get("sha"))
        commits = (github.pages(f"commits?sha={head}") if all_history
                   else compared(github, default, head))
        yield from _unseen(github, commits, "tag", seen)


def sweep(github: GitHub, since_time: datetime, now: datetime | None = None,
          all_history: bool = False) -> Iterator[Item]:
    since = _stamp(since_time)
    now = datetime.now(UTC) if now is None else now
    seen: set[str] = set()
    known: list[str] = []

    def default() -> str:
        if not known:
            repository = github.get("")
            name = repository.get("default_branch") if isinstance(repository, dict) else None
            if not isinstance(name, str) or not name:
                raise Incomplete("the default branch is unknown")
            known.append(name)
        return known[0]

    def branches() -> Iterator[Item]:
        for branch in github.pages("branches"):
            # Every branch, not only the default: a pushed topic branch is
            # public, and squash or merge commits carry text written at merge
            # time. The name is public too; it is reported by a digest, never
            # spelled out. Commits dated in the window are a second source
            # beside ref updates. Manual all-history scans instead pin each
            # listed head and remove that filter.
            raw_name = str(branch.get("name", ""))
            yield "branch name", _digest(raw_name), raw_name
            name = (_sha((branch.get("commit") or {}).get("sha")) if all_history
                    else urllib.parse.quote(raw_name, safe=""))
            query = f"commits?sha={name}" + ("" if all_history else f"&since={since}")
            yield from _unseen(github, github.pages(query),
                               "branch", seen)

    def updates() -> Iterator[Item]:
        yield from pushed(github, since_time, now, default(), seen, all_history)

    def tags() -> Iterator[Item]:
        yield from tagged(github, default(), seen, all_history)

    def commit_comments() -> Iterator[Item]:
        for comment in github.pages("comments"):
            if str(comment.get("updated_at", "")) >= since:
                yield from _fields("commit comment", comment, "body", "path")

    def issues() -> Iterator[Item]:
        for issue in github.pages(f"issues?state=all&since={since}"):
            yield from _fields("issue", issue, "title", "body")
            if "pull_request" in issue:
                pull = github.get(f"pulls/{issue['number']}")
                assert isinstance(pull, dict)
                yield from pull_request(github, pull, seen)
                for review in github.pages(f"pulls/{issue['number']}/reviews"):
                    yield from _fields("review", review, "body")
                for event in github.pages(f"issues/{issue['number']}/timeline"):
                    dismissed = event.get("dismissed_review") or {}
                    if dismissed.get("dismissal_message"):
                        yield ("review dismissal", str(issue["number"]),
                               str(dismissed["dismissal_message"]))

    def issue_comments() -> Iterator[Item]:
        for comment in github.pages(f"issues/comments?since={since}"):
            yield from _fields("comment", comment, "body")

    def review_comments() -> Iterator[Item]:
        for comment in github.pages(f"pulls/comments?since={since}"):
            yield from _fields("review comment", comment, "body", "path", "diff_hunk")

    # Each surface is scanned even when an earlier one fails, so one obstruction
    # (an unreachable previous head, a tag naming a blob) never hides the rest
    # for as long as it lasts. The first failure then fails the sweep. A stop
    # (``Cancelled``) is not an ``Exception``: it ends the sweep at once.
    failures: list[Exception] = []
    for surface in (branches, updates, tags, commit_comments, issues, issue_comments,
                    review_comments):
        try:
            yield from surface()
        except Exception as error:
            failures.append(error)
    if failures:
        raise failures[0]


def findings(items: Iterator[Item], compiled: list[re.Pattern[str]],
             found: list[tuple[str, str]] | None = None,
             report: Callable[[str, str], None] | None = None) -> list[tuple[str, str]]:
    """Matching (kind, id) pairs, appended to ``found`` and passed to ``report``
    as they are met, so a later failure does not hide what was already found."""
    found = [] if found is None else found
    for kind, ident, text in items:
        flagged = (kind in {"existing tag", "history gap"}
                   or any(pattern.search(text) for pattern in compiled))
        if flagged and (kind, ident) not in found:
            # Reported before it is recorded: a stop between the two loses only
            # the record, and a stopped run fails anyway.
            if report is not None:
                report(kind, ident)
            found.append((kind, ident))
    return found


def _report(kind: str, ident: str) -> None:
    # Flushed at once: a job killed after its cancellation grace keeps it.
    if kind == "history gap":
        message = "prior head unavailable through authenticated API; coverage not established"
    elif kind == "existing tag":
        message = "tag exists; repository tag restriction requires review"
    else:
        message = "matches a private pattern"
    print(f"::error::{kind} {ident} {message}", flush=True)


def main(argv: list[str], opener: Callable = open_api) -> int:
    """Scan, printing each finding as it is made; 0 only for a complete, clean scan.

    The runner cancels a step (on cancellation or the job's timeout) with
    SIGINT, then SIGTERM. Both end the scan as ``Cancelled``, which is reported
    like any other incomplete run, after the findings already printed."""
    github: GitHub | None = None
    found: list[tuple[str, str]] = []
    complete = False
    backfill_started: datetime | None = None
    previous: dict[int, object] = {}
    try:
        for name in ("SIGINT", "SIGTERM"):
            number = getattr(signal, name)
            previous[number] = signal.signal(number, _cancel)
        compiled = patterns(os.environ.get("PUBLIC_TEXT_PATTERNS", ""))
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GITHUB_TOKEN", "")
        manual = (argv[1:3] == ["sweep", "--since"]
                  and (len(argv) == 4 or (len(argv) == 5 and argv[4] == "--all-history")))
        if argv[1:] == ["sweep"] or manual:
            github = GitHub(repository, token, opener)
            started = datetime.now(UTC)
            if manual:
                since = utc(argv[3])
                if len(argv) == 5:
                    backfill_started = started
            else:
                since = cursor(github, os.environ.get("PUBLIC_TEXT_SWEPT_THROUGH", ""))
            items = sweep(github, since, started, all_history=len(argv) == 5)
        elif argv[1:2] == ["event"] and len(argv) == 3:
            payload = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
            github = GitHub(repository, token, opener) if token else None
            items = event(payload, github)
        else:
            raise Incomplete("usage: check_public_text.py event PATH | sweep "
                             "[--since TIME [--all-history]]")
        findings(items, compiled, found, _report)
        complete = True
    except BaseException as error:  # a cancellation too; the class, never the content
        print(f"::error::public text check incomplete ({type(error).__name__})", flush=True)
    finally:
        for number, handler in previous.items():
            # ``None`` is a handler not installed from Python: the default.
            signal.signal(number, signal.SIG_DFL if handler is None else handler)
    if github is not None:
        print(f"::notice::public text check made {github.requests} API requests", flush=True)
    if complete and any(kind == "history gap" for kind, _ in found):
        print("::notice::public text traversal-complete; coverage-incomplete", flush=True)
    if complete and not found and backfill_started is not None:
        print("::notice::manual backfill complete; PUBLIC_TEXT_SWEPT_THROUGH candidate "
              + _stamp(backfill_started), flush=True)
    return 0 if complete and not found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
