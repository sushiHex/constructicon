"""Actual WRITE session blocks on the disposable foundation CI lane.

W2/W3 exercise real smoke; W4-W6 use the pinned vendor binary with an empty
credential and must refuse at account/read, before any turn or connection.
Neither rehearsal establishes W0/W1 deployment or authenticated acceptance.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import PurePosixPath

import pytest

from constructicon.substrate.executors import operator_store
from constructicon.substrate.executors.codex_protocol import NO_RESULT_FAULT
from tests.test_m8_n5_host_session import _setup
from tests.test_m8_n5_read_rehearsal import (
    EMPTY_AUTH,
    ROOT,
    SERVICE,
    STORE_ROOT,
    bash,
    ci_override,
    record,
    service,
)
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


@pytest.fixture(scope="module")
def logged_out_write(foundation_smoke):
    """A separate short session and authorization; restore the CI store exactly."""
    root = service("/usr/bin/mktemp", "-d", "/home/m8-service/.wXXXXXX").decode().strip()
    path = PurePosixPath(root)
    assert path.parent == PurePosixPath("/home/m8-service")
    assert re.fullmatch(r"\.w[A-Za-z0-9]{6}", path.name)
    session, state = root + "/h", root + "/s"
    authorization = (
        "/var/lib/constructicon-m8-launch/qualification/" + path.name + "-write.json"
    )
    credential = STORE_ROOT / operator_store._bundle_token("n3a-fixture") / "store" / "auth.json"
    original = record(str(credential))
    try:
        sealed = json.loads(service(
            f"PYTHONPATH={ROOT}", sys.executable, "-m", "tests.substrate._read_rehearsal_host",
            session,
        ))
        service("/bin/sh", "-c", 'cat > "$1"', "sh", str(credential), stdin=EMPTY_AUTH)
        assert record(str(credential)) == EMPTY_AUTH
        yield {
            "commit": foundation_smoke[1], "session": session, "state": state,
            "authorization": authorization, "credential": credential, **sealed,
        }
    finally:
        service("/bin/sh", "-c", 'cat > "$1"', "sh", str(credential), stdin=original)
        assert record(str(credential)) == original
        # Both targets derive from the positively checked fresh temporary child.
        # Remove only this root-installed authorization and this service session.
        subprocess.run(("sudo", "-n", "/bin/rm", "-f", "--", authorization),
                       stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=120)
        service("/bin/rm", "-rf", "--", root)


def test_actual_w4_w6_logged_out_write_refuses_account_gate_and_preserves_attempt(logged_out_write):
    rehearsal = logged_out_write
    state = rehearsal["state"]
    script = "\n".join([
        f"C={shlex.quote(rehearsal['commit'])}", _setup(), ci_override(),
        f"W={shlex.quote(rehearsal['session'])}", 'SEALED="$W/g4.sealed.json"', _override(),
        f"S={shlex.quote(state)}", 'F="$S/write"; SM="$S/smoke"',
        f"A={shlex.quote(rehearsal['authorization'])}",
        'HOST=(--session "$W" --store-key "$K" --sealed "$SEALED"',
        '  --qualification "$W/s6a-qualification.json" --state "$S")',
        *_blocks(W2), *_blocks(W3),
        *_blocks("W4. Compute and review the WRITE pins"),
        *_blocks("W5. Root installs the reviewed authorization"),
        *_blocks("W6. The one WRITE turn and its derived verdict"),
    ])
    ran = bash(script)
    assert ran.returncode == 0, ran.stderr[-4000:]
    lines = ran.stdout.strip().splitlines()
    assert len(lines) == 5, ran.stdout
    write_pin, smoke_pin, smoke, pins, report = map(json.loads, lines)
    assert smoke["verdict"] == "passed"
    assert write_pin["identity"] != smoke_pin["identity"]
    assert pins["write"]["fixture"] == write_pin
    assert record(rehearsal["authorization"]) == record(state + "/minted.json")
    assert json.loads(record(state + "/write-report.json")) == report
    assert report["verdict"] != "passed" and report["run_status"] == "failed"
    assert report["turn_dispatch"] == "not dispatched" and report["turn_status"] == "failure"
    assert report["checkpoint_chain_validated"] is False
    assert report["candidate"] is report["candidate_tree"] is report["attestation_id"] is None
    assert report["checks"] == [] and report["check_count"] is None

    attempt = record(state + "/stage4.attempt")
    written = json.loads(attempt)
    assert (written["phase"], written["dispatch"]) == ("outcome", "not dispatched")
    facts = written["facts"]
    # Pin the accepting startup path up to its precise account-gate refusal:
    # launch/configuration/credential failures cannot substitute for this fact.
    assert facts["status"] == "failure"
    assert facts["refusal"] == f"unavailable: {NO_RESULT_FAULT}"
    assert facts["relay"] == {"destinations": {}, "denied": {}}
    process = facts["process"]
    assert process is not None and process["returncode"] == process["payload_returncode"] == 0
    assert process["timed_out"] is False and process["bound_exceeded"] is False
    assert facts["readbacks"] is None and facts["answer_bytes"] is None
    assert facts["usage"] == "unknown" and facts["served_model"] == "unknown"
    assert facts["identities"]["qualification"] == rehearsal["qualification"]
    assert facts["identities"]["operator_binding_digest"] == rehearsal["operator_binding_digest"]
    assert record(str(rehearsal["credential"])) == EMPTY_AUTH
    assert record(state + "/stage4.attempt") == attempt
