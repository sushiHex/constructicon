"""The vendor pin as the workflow's acquisition step states it.

The one place a test reads the pinned Codex release and catalog, so a bump
changes the workflow and nothing here. Behaviour recorded from a release (the
models a fixture names, request shapes, efforts) is an observation, not the
pin, and is re-observed on a bump rather than derived.
"""

from __future__ import annotations

from pathlib import Path

from scripts.ci import m8_host_artifacts as artifacts

_WORKFLOW = Path(__file__).parents[1] / artifacts.WORKFLOW
PIN = artifacts.vendor_pin(_WORKFLOW.read_bytes().replace(b"\r\n", b"\n"))
VERSION = PIN["version"]
CODEX_SHA256 = PIN["codex_sha256"]
CATALOG_SHA256 = PIN["catalog_sha256"]
