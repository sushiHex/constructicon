"""Execute only the successor's shell ordering with platform primitives faked."""

from __future__ import annotations

import os
import subprocess

import pytest

from tests.test_m8_n5_host_session import HANDOFFS, _fences, _text
from tests.test_m8_operator_commands import _bash

DOCUMENT = HANDOFFS / "M8-N5-explicit-refresh.md"


@pytest.mark.parametrize("failure", ["none", "sudo", "drift", "qualification", "binding", "seal"])
def test_explicit_refresh_procedure_stops_before_launch_on_failed_precondition(failure):
    blocks = _fences(_text(DOCUMENT))
    assert len(blocks) == 1
    block = blocks[0]
    assert block.count("/usr/local/bin/m8-host-drift") == 1
    # Substitute only the platform-owned absolute command; no host is contacted.
    block = block.replace("/usr/local/bin/m8-host-drift", "drift")
    script = "\n".join([
        "set -Eeuo pipefail",
        'check() { test "$FAILURE" != "$1"; }',
        'sudo() { test "$*" = "-n true"; check sudo; }',
        "drift() { check drift; }",
        "load_final_qualification() { check qualification; Q=q; SEAL=private; }",
        'binding_check() { test "$*" = "descriptor accepted -"; check binding; }',
        'check_sealed() { test "$*" = "descriptor q"; check seal; }',
        'service() { printf "ARG:%s\\n" "$@"; }',
        "SERVICE=(service); LANE=(lane)",
        "R=store; K=key; L=launch; W=session",
        "SEALED=descriptor; REFRESH_LANE=fresh-lane; REFRESH_EVIDENCE=fresh-evidence",
        block,
    ])
    result = subprocess.run(
        [_bash(), "-c", script], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, check=False,
        env={**os.environ, "FAILURE": failure},
    )
    if failure != "none":
        assert result.returncode != 0
        assert result.stdout == ""
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "ARG:" + item for item in (
                "lane", "startup", "--request-refresh", "--custody", "active",
                "--store-root", "store", "--key", "key", "--sealed", "descriptor",
                "--expected", "private", "--launch-root", "launch", "--configuration",
                "session/config.toml", "--policy", "session/startup-policy.json",
                "--lane-dir", "fresh-lane", "--evidence", "fresh-evidence",
            )
        ]


def test_explicit_refresh_procedure_preserves_the_owner_gates_and_old_checkers():
    document = _text(DOCUMENT)
    assert "Old schema-4 runbook checkers must reject explicit evidence" in document
    assert "No automatic second attempt" in document
    assert "T5/no-T6 gate" in document
    assert "not a controller-installation runbook" in document
    assert "separate host\nauthorization" in document
    assert "refresh-unmeasured" in document
