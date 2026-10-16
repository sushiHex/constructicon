"""Flag public repository text that matches a private pattern; never print the match.

Run by ``.github/workflows/public-text.yml`` on every issue, comment, review and
pull-request event. Patterns come from the ``PUBLIC_TEXT_PATTERNS`` secret, one
case-insensitive regular expression per line, so the private values never
appear in the repository. Pull-request events also scan the changed files'
patches, read through the API without checking out the head.

Exit 1 with one ``::error`` line naming only the event's kind and public URL;
the matched text, the pattern and its position are never written to the public
log. An unset or invalid pattern list is itself a failure, not a pass. This is
detection after posting: it cannot un-post, and GitHub keeps edited text in
the comment's history until that revision is deleted.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from collections.abc import Iterator
from pathlib import Path

API = "https://api.github.com"
MAX_PATCH_PAGES = 30


class PatternsNotConfigured(ValueError):
    """The secret is unset or empty: a failure, never a pass."""


def patterns(raw: str) -> list[re.Pattern[str]]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        raise PatternsNotConfigured
    return [re.compile(line, re.IGNORECASE) for line in lines]


def texts(event: dict) -> Iterator[tuple[str, str, str]]:
    """(kind, public url, text) for every user-written field in the event."""
    for kind in ("issue", "pull_request", "comment", "review"):
        item = event.get(kind)
        if not isinstance(item, dict):
            continue
        url = str(item.get("html_url") or "")
        for field in ("title", "body"):
            value = item.get(field)
            if isinstance(value, str) and value:
                yield kind, url, value


def patches(
    event: dict, token: str, opener=urllib.request.urlopen,
) -> Iterator[tuple[str, str, str]]:
    """Changed-file patches of a pull-request event, read through the API."""
    pull = event.get("pull_request")
    repository = (event.get("repository") or {}).get("full_name")
    if not isinstance(pull, dict) or not repository or not token:
        return
    url = str(pull.get("html_url") or "")
    for page in range(1, MAX_PATCH_PAGES + 1):
        request = urllib.request.Request(
            f"{API}/repos/{repository}/pulls/{pull['number']}/files?per_page=100&page={page}",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
        )
        with opener(request, timeout=30) as response:
            files = json.load(response)
        for changed in files:
            yield "pull_request file", url, str(changed.get("filename", "")) + "\n" + str(
                changed.get("patch") or "")
        if len(files) < 100:
            return
    raise ValueError("pull request has too many changed files to scan")


def findings(event: dict, compiled: list[re.Pattern[str]], token: str = "",
             opener=urllib.request.urlopen) -> list[tuple[str, str]]:
    found = []
    for kind, url, text in [*texts(event), *patches(event, token, opener)]:
        if any(pattern.search(text) for pattern in compiled) and (kind, url) not in found:
            found.append((kind, url))
    return found


def main(argv: list[str]) -> int:
    try:
        compiled = patterns(os.environ.get("PUBLIC_TEXT_PATTERNS", ""))
        event = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        found = findings(event, compiled, os.environ.get("GITHUB_TOKEN", ""))
    except Exception as error:  # report the class, never the content
        print(f"::error::public text check could not run ({type(error).__name__})")
        return 1
    for kind, url in found:
        print(f"::error::{kind} at {url or 'this event'} matches a private pattern")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
