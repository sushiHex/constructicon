"""Every CI uv bootstrap is the pinned action, the pinned uv and its platform checksum (#395).

setup-uv v5 fetched an unpinned "latest" uv from GitHub Releases only, and held
no known checksum for it, so a release 504 failed required jobs before any
check (run 42468371511). v10.3.3 downloads from the Astral mirror first, falls
back to GitHub Releases, and refuses bytes that miss the provided checksum.
The checksums are the release's own ``.sha256`` files for uv 0.13.7, matched
by bytes fetched from both routes.
"""

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).parents[1] / ".github/workflows"
ACTION = "astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2 # v10.3.3"
UV_VERSION = "0.13.7"
CHECKSUMS = {
    "linux": "c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83",
    "windows": "0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021",
}
SITES = {"verify.yml": 3, "m8-containment.yml": 2, "m8-pi-local-read.yml": 1}
# Every runner label a bootstrap job may name, all x86-64.
RUNNERS = {"ubuntu-latest": "linux", "ubuntu-24.04": "linux", "windows-latest": "windows"}


def _platform(runs_on: str) -> str:
    assert runs_on in RUNNERS, f"no uv checksum for runner {runs_on}"
    return RUNNERS[runs_on]


def assert_pinned_uv_bootstrap(workflow: str) -> int:
    """Return how many bootstraps the workflow holds; each must be exact."""
    jobs = re.split(r"^  (?=[\w-]+:$)", workflow.split("\njobs:\n", 1)[1], flags=re.M)
    sites = 0
    for job in jobs:
        if "setup-uv" not in job:
            continue
        runs_on = re.findall(r"^    runs-on: (\S+)$", job, re.M)
        assert len(runs_on) == 1, "a uv bootstrap job names exactly one runner"
        checksum = CHECKSUMS[_platform(runs_on[0])]
        # A step runs to the next step or the end of its job, blank lines included,
        # so nothing placed after a blank line escapes the exact comparison.
        steps = [
            "      - " + chunk for chunk in re.split(r"^      - ", job, flags=re.M)[1:]
            if chunk.startswith("uses: astral-sh/setup-uv@")
        ]
        assert len(steps) == job.count("setup-uv"), "setup-uv appears outside a step's uses line"
        for step in steps:
            python = re.findall(r'^          python-version: "(3\.1[12])"$', step, re.M)
            assert len(python) == 1, "a bootstrap names one Python version"
            assert step == (
                f"      - uses: {ACTION}\n"
                "        with:\n"
                f'          version: "{UV_VERSION}"\n'
                f"          checksum: {checksum}\n"
                f'          python-version: "{python[0]}"\n'
                "          activate-environment: true\n"
                "          prune-cache: true\n"
            ), "a uv bootstrap differs from the pinned action, version or platform checksum"
        sites += len(steps)
    return sites


@pytest.mark.parametrize(("filename", "count"), SITES.items())
def test_every_workflow_bootstraps_the_pinned_verified_uv(filename, count):
    assert assert_pinned_uv_bootstrap((WORKFLOWS / filename).read_text(encoding="utf-8")) == count


def test_no_other_workflow_bootstraps_uv():
    others = [path.name for path in WORKFLOWS.iterdir()
              if path.suffix in {".yml", ".yaml"} and path.name not in SITES
              and "setup-uv" in path.read_text(encoding="utf-8")]
    assert others == []


@pytest.mark.parametrize("fault", [
    "floating", "old-pin", "unpinned-version", "no-checksum", "crossed-platform",
    "unknown-runner", "arm-runner", "made-up-runner", "inactive", "extra-input",
    "input-after-blank", "condition-after-blank",
])
def test_the_bootstrap_guard_refuses_each_drift(fault):
    text = (WORKFLOWS / "verify.yml").read_text(encoding="utf-8")
    linux = f"          checksum: {CHECKSUMS['linux']}\n"
    windows = f"          checksum: {CHECKSUMS['windows']}\n"
    edits = {
        "floating": (ACTION, "astral-sh/setup-uv@v10"),
        "old-pin": (ACTION, "astral-sh/setup-uv@e58605a9b6da7c637471fab8847a5e5a6b8df081 # v5"),
        "unpinned-version": (f'version: "{UV_VERSION}"', 'version: "latest"'),
        "no-checksum": (linux, ""),
        "crossed-platform": (windows, linux),
        "unknown-runner": ("    runs-on: windows-latest\n", "    runs-on: macos-latest\n"),
        "arm-runner": ("    runs-on: ubuntu-24.04\n    env:\n",
                       "    runs-on: ubuntu-24.04-arm\n    env:\n"),
        "made-up-runner": ("    runs-on: ubuntu-24.04\n    env:\n",
                           "    runs-on: ubuntu-made-up\n    env:\n"),
        "inactive": ("activate-environment: true", "activate-environment: false"),
        "extra-input": (linux, linux + "          download-from-astral-mirror: false\n"),
        "input-after-blank": (
            "          prune-cache: true\n",
            "          prune-cache: true\n\n          download-from-astral-mirror: false\n",
        ),
        "condition-after-blank": (
            "          prune-cache: true\n", "          prune-cache: true\n\n        if: false\n",
        ),
    }
    before, after = edits[fault]
    assert before in text
    with pytest.raises(AssertionError):
        assert_pinned_uv_bootstrap(text.replace(before, after, 1))
