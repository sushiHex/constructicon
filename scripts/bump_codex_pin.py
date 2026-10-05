"""Bump the vendor Codex pin: the upgrade routine's one tool (M8-N5-state-review.md).

Run by a person or an agent, never by CI::

    uv run python scripts/bump_codex_pin.py [--version X.Y.Z] [--dry-run]

It selects a published stable release from every ``rust-vX.Y.Z`` tag, never a
downgrade. The package must agree with the release's ``codex-package_SHA256SUMS``,
GitHub's asset digest and the downloaded bytes. The tag is peeled to its commit
and the catalog is hashed there. Then the workflow's one acquisition step is
rewritten, only if the workflow is still the one read at the start.

The report names what a bump cannot derive: the catalog's newest model per
family, and the recorded vendor behaviour to re-observe before relying on it.
Stdlib only, and no file is written until every check has passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ci"))
import m8_host_artifacts as artifacts

REPOSITORY = Path(__file__).resolve().parents[1]
API = "https://api.github.com/repos/openai/codex"
ASSET = "codex-package-x86_64-unknown-linux-musl.tar.gz"
SUMS = "codex-package_SHA256SUMS"
STABLE_TAG = re.compile(r"rust-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
CANDIDATES = 10
LIMITS = {
    "refs": 16 << 20, "api": 1 << 20, "sums": 1 << 20, "package": 512 << 20, "catalog": 8 << 20,
}  # fmt: skip
FAMILIES = ("astra", "sol", "luna", "terra")
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
RECORDED = (
    "tests/native_startup.py MODELS (models the native fixtures name)",
    "tests/native_combined.py efforts and request shapes",
    "tests/fixtures/native_combined_sol_tools.json (recorded tool serialization)",
    "the pinned facts in docs/plans/handoffs/M8-N5-state-review.md",
)

Fetch = Callable[[str, int], bytes]


class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    """Every hop stays on HTTPS. The token is unredirected, so no hop receives it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError(f"refusing a redirect off HTTPS: {newurl}")
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl
        )


OPENER = urllib.request.build_opener(HTTPSOnly)


def fetch(url: str, limit: int) -> bytes:
    """One bounded, unpaginated HTTPS GET. An API token is sent to GitHub's API only."""

    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-HTTPS URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "constructicon-bump"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    with OPENER.open(request, timeout=60) as response:
        if 'rel="next"' in (response.headers.get("Link") or ""):
            raise ValueError(f"{url} is paginated; a listing must be complete")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{url} exceeds its {limit}-byte bound")
    return data


def version_of(tag: str) -> tuple[int, int, int] | None:
    match = STABLE_TAG.fullmatch(tag)
    return None if match is None else (int(match[1]), int(match[2]), int(match[3]))


def stable_tags(get: Fetch) -> dict[tuple[int, int, int], dict]:
    """Every exact ``rust-vX.Y.Z`` tag and the object it names, from one complete listing."""

    refs = json.loads(get(f"{API}/git/matching-refs/tags/rust-v", LIMITS["refs"]))
    return {
        version: ref["object"] for ref in refs
        if (version := version_of(ref["ref"].removeprefix("refs/tags/"))) is not None
    }  # fmt: skip


def published(tag: str, get: Fetch) -> dict | None:
    """The tag's release if it is published and stable; a draft is invisible here."""

    try:
        release = json.loads(get(f"{API}/releases/tags/{tag}", LIMITS["api"]))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    return None if release.get("draft") or release.get("prerelease") else release


def select(get: Fetch, requested: str | None) -> tuple[dict, dict]:
    """The requested release, or the greatest tag with a published stable release."""

    tags = stable_tags(get)
    if requested is not None:
        version = version_of(f"rust-v{requested}")
        order = [version] if version in tags else []
    else:
        order = sorted(tags, reverse=True)[:CANDIDATES]
    for version in order:
        release = published("rust-v{}.{}.{}".format(*version), get)
        if release is not None:
            return release, tags[version]
    if requested is not None:
        raise ValueError(f"rust-v{requested} is not a published stable release")
    raise ValueError(f"none of the {CANDIDATES} greatest stable tags is a published release")


def peel(target: dict, get: Fetch) -> str:
    """The commit a tag's object names, through annotated tag objects."""

    for _ in range(4):
        if target["type"] == "commit":
            return target["sha"]
        if target["type"] != "tag":
            raise ValueError(f"the tag names a {target['type']}, not a commit")
        target = json.loads(get(f"{API}/git/tags/{target['sha']}", LIMITS["api"]))["object"]
    raise ValueError("the tag does not peel to a commit")


def package_digest(release: dict, get: Fetch) -> tuple[str, str]:
    """The package's URL and sha256, agreed by SHA256SUMS, GitHub's digest and the bytes."""

    assets = {asset["name"]: asset for asset in release.get("assets", [])}
    if ASSET not in assets or SUMS not in assets:
        raise ValueError(f"{release['tag_name']} lacks {ASSET} or {SUMS}")
    sums = get(assets[SUMS]["browser_download_url"], LIMITS["sums"]).decode()
    listed = [line.split()[0] for line in sums.splitlines() if line.split()[1:] == [ASSET]]
    if len(listed) != 1 or not re.fullmatch(r"[0-9a-f]{64}", listed[0]):
        raise ValueError(f"{SUMS} does not list {ASSET} exactly once")
    if assets[ASSET].get("digest") != f"sha256:{listed[0]}":
        raise ValueError(f"GitHub's digest for {ASSET} disagrees with {SUMS}")
    url = assets[ASSET]["browser_download_url"]
    if hashlib.sha256(get(url, LIMITS["package"])).hexdigest() != listed[0]:
        raise ValueError(f"the downloaded {ASSET} is not the listed one")
    return url, listed[0]


def newest(catalog: bytes) -> dict[str, object]:
    """The catalog's default, and per family its newest listed model and lowest effort.

    Efforts are ranked by name, never by list position. An effort the ranking does
    not know might be lower, so the lowest is then reported as unknown.
    """

    models = [m for m in json.loads(catalog)["models"] if m.get("visibility") == "list"]
    report: dict[str, object] = {"default": min(models, key=lambda m: m["priority"])["slug"]}
    for family in FAMILIES:
        members = [m for m in models if m["slug"].endswith(f"-{family}")]
        if members:
            top = max(members, key=lambda m: [int(p) for p in re.findall(r"\d+", m["slug"])])
            efforts = {level["effort"] for level in top.get("supported_reasoning_levels", [])}
            ranked = efforts and efforts <= set(EFFORTS)
            lowest = min(efforts, key=EFFORTS.index) if ranked else None
            report[family] = {"model": top["slug"], "lowest_effort": lowest}
    return report


def apply(workflow: Path, original: bytes, old: dict[str, str], new: dict[str, str]) -> None:
    """Swap the one acquisition step if the workflow is still ``original``.

    The bytes go to a private staging file, then replace the workflow atomically.
    Only a write in the instant between the last comparison and the replace is
    not seen; the tool has no concurrent writer of its own.
    """

    crlf = b"\r\n" in original
    if crlf and original.count(b"\n") != original.count(b"\r\n"):
        raise ValueError("the workflow mixes line endings; nothing written")
    text = original.replace(b"\r\n", b"\n")
    before, after = (artifacts.render_vendor_step(pin).encode() for pin in (old, new))
    if text.count(before) != 1:
        raise ValueError("the workflow's acquisition step is not the current pin's")
    updated = text.replace(before, after)
    if {k: v for k, v in artifacts.vendor_pin(updated).items() if k in new} != new:
        raise ValueError("the rewritten workflow does not parse back to the new pin")
    data = updated.replace(b"\n", b"\r\n") if crlf else updated
    descriptor, staged = tempfile.mkstemp(prefix=f".{workflow.name}.", dir=workflow.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        if workflow.read_bytes() != original:
            raise ValueError("the workflow changed during the bump; nothing written")
        os.replace(staged, workflow)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def bump(requested: str | None, workflow: Path, get: Fetch, *, dry_run: bool) -> dict:
    original = workflow.read_bytes()
    current = artifacts.vendor_pin(original.replace(b"\r\n", b"\n"))
    release, target = select(get, requested)
    version = release["tag_name"].removeprefix("rust-v")
    now, then = version_of(release["tag_name"]), version_of(f"rust-v{current['version']}")
    if now is None or then is None or now < then:
        raise ValueError(f"refusing to downgrade {current['version']} to {version}")
    url, digest = package_digest(release, get)
    commit = peel(target, get)
    catalog_url = f"https://raw.githubusercontent.com/openai/codex/{commit}/codex-rs/models-manager/models.json"
    catalog = get(catalog_url, LIMITS["catalog"])
    new = {
        "codex_url": url, "codex_sha256": digest,
        "catalog_url": catalog_url, "catalog_sha256": hashlib.sha256(catalog).hexdigest(),
    }  # fmt: skip
    old = {key: current[key] for key in new}
    if now == then and new != old:
        raise ValueError(f"{version} is pinned with different bytes; investigate before any bump")
    old_catalog = get(old["catalog_url"], LIMITS["catalog"])
    if hashlib.sha256(old_catalog).hexdigest() != old["catalog_sha256"]:
        raise ValueError("the current pin's catalog no longer matches its digest")
    report = {
        "from": current["version"], "to": version, "commit": commit, "changed": new != old,
        "pin": new, "models": {"from": newest(old_catalog), "to": newest(catalog)},
        "re_observe": list(RECORDED) if new != old else [],
    }  # fmt: skip
    if new != old and not dry_run:
        apply(workflow, original, old, new)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", help="an exact stable version, e.g. 0.160.1")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args(argv)
    workflow = REPOSITORY / artifacts.WORKFLOW
    print(json.dumps(bump(args.version, workflow, fetch, dry_run=args.dry_run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
