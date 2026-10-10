"""Actual W2/W3 blocks on foundation: real smoke, no vendor invocation.

W0/W1 deployment proof and W4-W6 authenticated/logged-out WRITE are not run
here. The latter would launch a vendor binary and needs separate authority.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import PurePosixPath

import pytest

from tests.test_m8_n5_host_session import _setup
from tests.test_m8_n5_read_rehearsal import ROOT, SERVICE, bash, ci_override, record, service
from tests.test_m8_n5_write_session import W2, W3, _blocks, _override


@pytest.fixture(scope="module")
def foundation_smoke():
    if not os.environ.get("M8_READ_REHEARSAL_REQUIRED"):
        pytest.skip("WRITE smoke rehearsal requires the provisioned foundation lane")
    if sys.platform != "linux":
        pytest.fail("required WRITE smoke rehearsal is not Linux")
    root = service(
        "/usr/bin/mktemp", "-d", "/home/m8-service/.n5-write-smoke.XXXXXX",
    ).decode().strip()
    path = PurePosixPath(root)
    assert path.parent == PurePosixPath("/home/m8-service")
    assert path.name.startswith(".n5-write-smoke.") and len(path.name) > len(".n5-write-smoke.")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout.strip()
    try:
        yield root, commit
    finally:
        # One service-created, positively checked temporary child; never HOME.
        subprocess.run((*SERVICE, "/bin/rm", "-rf", "--", root),
                       stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=120)


def test_actual_w2_w3_blocks_prepare_independent_fixture_and_run_real_smoke(foundation_smoke):
    root, commit = foundation_smoke
    state = root + "/session"
    script = "\n".join([
        f"C={shlex.quote(commit)}", _setup(), ci_override(),
        "SEALED=unused-credential-free-generation", _override(),
        f"S={shlex.quote(state)}", 'F="$S/write"; SM="$S/smoke"',
        *_blocks(W2), *_blocks(W3),
    ])
    ran = bash(script)
    assert ran.returncode == 0, ran.stderr[-4000:]
    lines = ran.stdout.strip().splitlines()
    assert len(lines) == 3, ran.stdout
    write_pin, smoke_pin, report = map(json.loads, lines)
    assert write_pin["identity"] != smoke_pin["identity"]
    assert write_pin["base_commit"] == smoke_pin["base_commit"]
    assert write_pin["target_ref"] == smoke_pin["target_ref"] == "refs/heads/n5-write"
    assert report["verdict"] == "passed", report
    assert report["target_unchanged"] is True
    assert report["checkpoint_chain_validated"] is True
    assert report["obligation_count"] == 2 and report["check_count"] == 1
    assert {row["role"] for row in report["obligations"]} == {"workspace", "gate"}
    assert all(row["state"] == "closed" and row["disposition"] == "released"
               for row in report["obligations"])
    assert json.loads(record(state + "/smoke-report.json")) == report
    untouched = service("/usr/bin/git", "--git-dir", state + "/write/authority.git",
                        "show-ref").decode().splitlines()
    assert untouched == [write_pin["base_commit"] + " " + write_pin["target_ref"]]
    # No executor obligation or attempt record can hide in a smoke pass.
    service("/usr/bin/test", "!", "-e", state + "/stage4.attempt")
    service("/usr/bin/test", "!", "-e", state + "/write/smoke.sqlite")
