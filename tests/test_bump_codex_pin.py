"""The vendor bump tool against a scripted GitHub: selection, digests, peel, rewrite.

Every expectation is written out here, never derived from the tool's own output.
"""

from __future__ import annotations

import hashlib
import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest
from scripts import bump_codex_pin as bump

from tests.test_m8_host_runtime import PIN_A, workflow_with

API = bump.API
PACKAGE = b"package bytes"
CATALOG = json.dumps({"models": [
    {"slug": "gpt-6-astra", "priority": 2, "visibility": "list",
     "supported_reasoning_levels": [{"effort": "high"}, {"effort": "low"}]},
    {"slug": "gpt-6.1-sol", "priority": 1, "visibility": "list",
     "supported_reasoning_levels": [{"effort": "medium"}, {"effort": "low"}]},
    {"slug": "gpt-6-sol", "priority": 3, "visibility": "list",
     "supported_reasoning_levels": [{"effort": "medium"}]},
    {"slug": "gpt-7-sol", "priority": 9, "visibility": "hide",
     "supported_reasoning_levels": [{"effort": "low"}]},
    {"slug": "gpt-6-luna", "priority": 4, "visibility": "list",
     "supported_reasoning_levels": [{"effort": "low"}, {"effort": "minimal"}]},
]}).encode()  # fmt: skip
OLD_CATALOG = b'{"models": [{"slug": "gpt-6-astra", "priority": 1, "visibility": "list"}]}'
DIGEST = hashlib.sha256(PACKAGE).hexdigest()
TAG_OBJECT = "f" * 40
COMMIT = "d" * 40
DOWNLOAD = "https://github.com/openai/codex/releases/download"
CATALOG_URL = f"https://raw.githubusercontent.com/openai/codex/{COMMIT}/codex-rs/models-manager/models.json"


def release(tag: str, *, draft: bool = False, prerelease: bool = False, digest: str = DIGEST):
    return {
        "tag_name": tag, "draft": draft, "prerelease": prerelease,
        "assets": [
            {"name": bump.ASSET, "browser_download_url": f"{DOWNLOAD}/{tag}/{bump.ASSET}",
             "digest": f"sha256:{digest}"},
            {"name": bump.SUMS, "browser_download_url": f"{DOWNLOAD}/{tag}/{bump.SUMS}"},
        ],
    }  # fmt: skip


class GitHub:
    """A scripted GitHub keyed by exact URL; anything unscripted fails the test.

    Every release's tag is listed; ``unreleased`` tags are listed with no release.
    """

    def __init__(
        self, releases: list[dict], *, unreleased: tuple[str, ...] = (),
        sums: str | None = None, tag_type: str = "tag",
    ) -> None:  # fmt: skip
        tags = [item["tag_name"] for item in releases] + list(unreleased)
        refs = [{"ref": f"refs/tags/{tag}", "object": {"type": tag_type, "sha": TAG_OBJECT}}
                for tag in tags]  # fmt: skip
        self.missing = {f"{API}/releases/tags/{tag}" for tag in unreleased}
        self.responses: dict[str, bytes] = {
            f"{API}/git/matching-refs/tags/rust-v": json.dumps(refs).encode(),
            f"{API}/git/tags/{TAG_OBJECT}": json.dumps(
                {"object": {"type": "commit", "sha": COMMIT}}
            ).encode(),
            CATALOG_URL: CATALOG,
            PIN_A["catalog_url"]: OLD_CATALOG,
        }
        for item in releases:
            tag = item["tag_name"]
            self.responses[f"{API}/releases/tags/{tag}"] = json.dumps(item).encode()
            self.responses[f"{DOWNLOAD}/{tag}/{bump.ASSET}"] = PACKAGE
            self.responses[f"{DOWNLOAD}/{tag}/{bump.SUMS}"] = (
                sums if sums is not None else f"{DIGEST}  {bump.ASSET}\n{'e' * 64}  other.tar.gz\n"
            ).encode()

    def __call__(self, url: str, limit: int) -> bytes:
        if url in self.missing:
            raise urllib.error.HTTPError(url, 404, "Not Found", Message(), io.BytesIO())
        assert url in self.responses, url
        return self.responses[url]


@pytest.fixture
def workflow(tmp_path: Path) -> Path:
    path = tmp_path / "m8-containment.yml"
    path.write_bytes(workflow_with(bump.artifacts.render_vendor_step(
        {**PIN_A, "catalog_sha256": hashlib.sha256(OLD_CATALOG).hexdigest()}
    )))  # fmt: skip
    return path


def test_the_greatest_published_stable_release_is_chosen() -> None:
    github = GitHub(
        [
            release("rust-v0.180.0", draft=True), release("rust-v0.170.0", prerelease=True),
            release("rust-v0.160.1"), release("rust-v0.160.0"), release("rust-v0.99.0"),
            release("rust-v0.200.0-alpha.1"), release("rust-v0.0999.0"), release("v1.0.0"),
        ],
        unreleased=("rust-v0.165.0",),
    )  # fmt: skip
    chosen, target = bump.select(github, None)
    assert chosen["tag_name"] == "rust-v0.160.1"
    assert target == {"type": "tag", "sha": TAG_OBJECT}
    assert bump.select(github, "0.160.0")[0]["tag_name"] == "rust-v0.160.0"
    for requested in ("0.180.0", "0.170.0", "0.165.0", "0.161.0", "0.200.0-alpha.1"):
        with pytest.raises(ValueError, match="not a published stable release"):
            bump.select(github, requested)


@pytest.mark.parametrize(("unpublished", "chosen"), [(9, "rust-v0.160.1"), (10, None)])
def test_only_the_ten_greatest_stable_tags_are_tried(unpublished: int, chosen: str | None) -> None:
    github = GitHub(
        [release("rust-v0.160.1")],
        unreleased=tuple(f"rust-v0.{161 + n}.0" for n in range(unpublished)),
    )
    if chosen is None:
        with pytest.raises(ValueError, match="none of the 10 greatest stable tags"):
            bump.select(github, None)
    else:
        assert bump.select(github, None)[0]["tag_name"] == chosen


@pytest.mark.parametrize(
    ("target", "commit"),
    [({"type": "tag", "sha": TAG_OBJECT}, COMMIT), ({"type": "commit", "sha": "e" * 40}, "e" * 40)],
)
def test_a_tag_peels_to_its_commit(target: dict, commit: str) -> None:
    assert bump.peel(target, GitHub([])) == commit


def test_a_bump_rewrites_only_the_acquisition_step_to_the_verified_pin(workflow: Path) -> None:
    before = workflow.read_bytes()
    report = bump.bump(None, workflow, GitHub([release("rust-v0.160.1")]), dry_run=False)
    after = workflow.read_bytes()
    pin = bump.artifacts.vendor_pin(after)
    assert pin["version"] == "0.160.1" and pin["catalog_commit"] == COMMIT
    assert pin["codex_sha256"] == DIGEST
    assert pin["catalog_sha256"] == hashlib.sha256(CATALOG).hexdigest()
    head = before.split(b"      - name: Acquire", 1)[0]
    tail = before[before.rindex(b"      - name: Next") :]
    assert after.startswith(head) and after.endswith(tail) and after != before
    assert report["from"] == "0.153.4" and report["to"] == "0.160.1" and report["changed"]
    assert report["models"]["to"] == {
        "default": "gpt-6.1-sol",
        "astra": {"model": "gpt-6-astra", "lowest_effort": "low"},
        "sol": {"model": "gpt-6.1-sol", "lowest_effort": "low"},
        "luna": {"model": "gpt-6-luna", "lowest_effort": None},
    }
    assert report["re_observe"] == list(bump.RECORDED)
    assert sorted(workflow.parent.iterdir()) == [workflow]


def test_a_dry_run_writes_nothing(workflow: Path) -> None:
    before = workflow.read_bytes()
    report = bump.bump(None, workflow, GitHub([release("rust-v0.160.1")]), dry_run=True)
    assert report["changed"] and workflow.read_bytes() == before


def test_line_endings_survive_a_bump(workflow: Path) -> None:
    workflow.write_bytes(workflow.read_bytes().replace(b"\n", b"\r\n"))
    bump.bump(None, workflow, GitHub([release("rust-v0.160.1")]), dry_run=False)
    data = workflow.read_bytes()
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert bump.artifacts.vendor_pin(data.replace(b"\r\n", b"\n"))["version"] == "0.160.1"


def test_mixed_line_endings_refuse(workflow: Path) -> None:
    workflow.write_bytes(workflow.read_bytes().replace(b"\n", b"\r\n", 1))
    before = workflow.read_bytes()
    with pytest.raises(ValueError, match="mixes line endings"):
        bump.bump(None, workflow, GitHub([release("rust-v0.160.1")]), dry_run=False)
    assert workflow.read_bytes() == before


@pytest.mark.parametrize(
    ("found", "requested", "message"),
    [
        ([release("rust-v0.150.0")], None, "refusing to downgrade"),
        ([release("rust-v0.150.0"), release("rust-v0.153.4")], "0.150.0", "refusing to downgrade"),
        # GitHub agrees with itself about 0.153.4, but not with the bytes the workflow pins.
        ([release("rust-v0.153.4")], None, "different bytes"),
    ],
)
def test_a_downgrade_or_a_changed_pinned_version_refuses(
    workflow: Path, found: list, requested: str | None, message: str
) -> None:
    before = workflow.read_bytes()
    with pytest.raises(ValueError, match=message):
        bump.bump(requested, workflow, GitHub(found), dry_run=False)
    assert workflow.read_bytes() == before


def test_the_pinned_release_unchanged_is_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bump, "apply", lambda *_: pytest.fail("an unchanged pin was rewritten"))
    pin = {
        "codex_url": f"{DOWNLOAD}/rust-v0.153.4/{bump.ASSET}", "codex_sha256": DIGEST,
        "catalog_url": CATALOG_URL, "catalog_sha256": hashlib.sha256(CATALOG).hexdigest(),
    }  # fmt: skip
    workflow = tmp_path / "m8-containment.yml"
    workflow.write_bytes(workflow_with(bump.artifacts.render_vendor_step(pin)))
    before = workflow.read_bytes()
    report = bump.bump(None, workflow, GitHub([release("rust-v0.153.4")]), dry_run=False)
    assert not report["changed"] and report["re_observe"] == []
    assert workflow.read_bytes() == before


def test_a_current_pin_whose_catalog_moved_refuses(workflow: Path) -> None:
    github = GitHub([release("rust-v0.160.1")])
    github.responses[PIN_A["catalog_url"]] = OLD_CATALOG + b" "
    with pytest.raises(ValueError, match="no longer matches its digest"):
        bump.bump(None, workflow, github, dry_run=False)


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("unlisted", "does not list"),
        ("listed twice", "does not list"),
        ("github disagrees", "GitHub's digest"),
        ("bytes differ", "not the listed one"),
        ("tree tag", "names a tree"),
    ],
)
def test_every_digest_and_the_peel_must_agree(workflow: Path, fault: str, message: str) -> None:
    before = workflow.read_bytes()
    found = [release("rust-v0.160.1", digest="1" * 64 if fault == "github disagrees" else DIGEST)]
    sums = {
        "unlisted": f"{DIGEST}  other.tar.gz\n",
        "listed twice": f"{DIGEST}  {bump.ASSET}\n{DIGEST}  {bump.ASSET}\n",
    }.get(fault)
    github = GitHub(found, sums=sums, tag_type="tree" if fault == "tree tag" else "tag")
    if fault == "bytes differ":
        github.responses[f"{DOWNLOAD}/rust-v0.160.1/{bump.ASSET}"] = b"tampered"
    with pytest.raises(ValueError, match=message):
        bump.bump(None, workflow, github, dry_run=False)
    assert workflow.read_bytes() == before


def test_an_edit_made_while_the_bump_fetches_is_never_overwritten(workflow: Path) -> None:
    github = GitHub([release("rust-v0.160.1")])

    def editing(url: str, limit: int) -> bytes:
        if url == PIN_A["catalog_url"]:
            workflow.write_bytes(workflow.read_bytes() + b"# edited\n")
        return github(url, limit)

    with pytest.raises(ValueError, match="changed during the bump"):
        bump.bump(None, workflow, editing, dry_run=False)
    assert workflow.read_bytes().endswith(b"# edited\n")
    assert bump.artifacts.vendor_pin(workflow.read_bytes())["version"] == "0.153.4"
    assert sorted(workflow.parent.iterdir()) == [workflow]


def test_a_second_copy_of_the_step_outside_any_step_refuses(workflow: Path) -> None:
    """vendor_pin ignores a copy not followed by a step; the rewrite must not touch it."""
    step = bump.artifacts.render_vendor_step(
        {**PIN_A, "catalog_sha256": hashlib.sha256(OLD_CATALOG).hexdigest()}
    )
    workflow.write_bytes(workflow.read_bytes() + step.encode())
    before = workflow.read_bytes()
    with pytest.raises(ValueError, match="not the current pin's"):
        bump.bump(None, workflow, GitHub([release("rust-v0.160.1")]), dry_run=False)
    assert workflow.read_bytes() == before


class Response:
    def __init__(self, data: bytes, link: str | None = None) -> None:
        self.data = data
        self.headers = Message()
        if link is not None:
            self.headers["Link"] = link

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self.data[:size]


class Opener:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.sent: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: float) -> Response:
        self.sent.append(request)
        return self.response


def test_a_token_goes_to_the_github_api_only(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = Opener(Response(b"{}"))
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setattr(bump, "OPENER", opener)
    urls = (f"{API}/releases/tags/x", f"{DOWNLOAD}/rust-v0.160.1/{bump.ASSET}", CATALOG_URL)
    for url in urls:
        bump.fetch(url, 8)
    # urllib copies request.headers onto a redirect to any host; never the unredirected ones.
    assert all("Authorization" not in request.headers for request in opener.sent)
    assert [request.unredirected_hdrs.get("Authorization") for request in opener.sent] == [
        "Bearer secret", None, None,
    ]  # fmt: skip


def test_a_redirect_stays_on_https_and_never_carries_the_token() -> None:
    redirects = [
        handler for handler in bump.OPENER.handlers
        if isinstance(handler, urllib.request.HTTPRedirectHandler)
    ]  # fmt: skip
    assert len(redirects) == 1 and isinstance(redirects[0], bump.HTTPSOnly)
    request = urllib.request.Request(f"{API}/releases/tags/x")
    request.add_unredirected_header("Authorization", "Bearer secret")
    onward = redirects[0].redirect_request(request, None, 302, "Found", {}, "https://elsewhere.test/")
    assert onward.full_url == "https://elsewhere.test/" and not onward.has_header("Authorization")
    with pytest.raises(ValueError, match="off HTTPS"):
        redirects[0].redirect_request(request, None, 302, "Found", {}, "http://elsewhere.test/")


def test_a_fetch_is_https_bounded_and_unpaginated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bump, "OPENER", Opener(Response(b"12345")))
    assert bump.fetch("https://example.test/x", 5) == b"12345"
    with pytest.raises(ValueError, match="exceeds its 4-byte bound"):
        bump.fetch("https://example.test/x", 4)
    with pytest.raises(ValueError, match="non-HTTPS"):
        bump.fetch("http://example.test/x", 5)
    monkeypatch.setattr(bump, "OPENER", Opener(Response(b"[]", '<https://x/?page=2>; rel="next"')))
    with pytest.raises(ValueError, match="is paginated"):
        bump.fetch("https://example.test/x", 5)
