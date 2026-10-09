"""Stage 3's READ session, rehearsed on the provisioned foundation lane.

The runbook's own blocks (M8-N5-read-session.md T2 to T6) run against the CI
host: the production entry and assembly, the production authorization reader,
the real vendor binary on the base runtime, and the CI store fixture under a
synthetic g4 (tests/substrate/_read_rehearsal_host.py). The credential is
``{}``: logged out, so the startup gate must refuse at ``account/read``, before
``turn/start``, with no connection. Every link of that refusal is pinned, not
only its "not dispatched" end: a missing credential, a configuration mismatch
or a launch failure would also end there.

What it cannot prove: anything after ``account/read`` (the spend readback,
``thread/start``, the intent, ``turn/start``, a real answer). That runs first on
the host, within the budgeted attempt. T0 and T1 are host-only and skipped.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from constructicon.substrate.executors import operator_store
from constructicon.substrate.executors.codex_protocol import NO_RESULT_FAULT
from tests.test_m8_n5_host_session import _setup
from tests.test_m8_n5_read_session import SESSION, _fences, _override, _retry, _section, _text

ROOT = Path(__file__).resolve().parents[1]
STORE_ROOT = Path("/var/lib/constructicon-m8-launch/operator-stores")
W = "/home/m8-service/m8-n5-stage2"
SERVICE = ("sudo", "-n", "-u", "m8-service", "/usr/bin/env", "-i", "PATH=/usr/bin:/bin",
           "HOME=/home/m8-service", "LANG=C.UTF-8")
EMPTY_AUTH = b"{}\n"


@pytest.fixture(scope="module")
def lane():
    if not os.environ.get("M8_READ_REHEARSAL_REQUIRED"):
        pytest.skip("the READ rehearsal needs the provisioned foundation lane")
    if sys.platform != "linux":
        pytest.fail("required READ rehearsal lane is not Linux")


def service(*argv: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(
        (*SERVICE, *argv), input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL,
        capture_output=True, check=True, timeout=120,
    ).stdout


def ci_override() -> str:
    """The CI's stand-ins for the host-only parts of the common file: OC's PY
    becomes this checkout's interpreter under the same isolated runpy entry, and
    the store key is the fixture's. Placed before the runbook's own block, so its
    QUAL and HOST capture them."""
    purelib = sysconfig.get_paths()["purelib"]
    entry = ("import runpy, sys; sys.path[:0] = sys.argv[1:3]; del sys.argv[1:3]; "
             'runpy.run_module(sys.argv.pop(1), run_name="__main__", alter_sys=True)')
    command = (sys.executable, "-I", "-S", "-B", "-c", entry, str(ROOT / "src"), purelib)
    return "\n".join(["K=n3a-fixture", f"PY=({shlex.join(command)})"])


def bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", "-s"], input=script, capture_output=True, text=True, timeout=1500,
        check=False,
    )


def steps(commit: str, *headings: str, retry: bool = False) -> str:
    """The composed common file, then each named step's blocks, as the runbook
    says to run them; T5 also reports the run's status it recorded."""
    # OC's setup refuses to start without C, the commit the host session names.
    blocks = [f"C={commit}", _setup(), ci_override(), _override(),
              *([_retry()] if retry else [])]
    for heading in headings:
        blocks.extend(_fences(_section(_text(SESSION), heading)))
    if "T5. The one READ turn" in headings:
        blocks.append('printf "run=%s\\n" "$RUN"')
    return "\n".join(blocks)


def record(path: str) -> bytes:
    return service("/bin/cat", path)


@pytest.fixture(scope="module")
def rehearsal(lane):
    """Stage 2's W, the logged-out credential, and cleanup of everything made."""
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    credential = STORE_ROOT / operator_store._bundle_token("n3a-fixture") / "store" / "auth.json"
    original = record(str(credential))
    made = (W, "/home/m8-service/m8-n5-stage3", "/home/m8-service/m8-n5-stage3r")
    installed = ("/var/lib/constructicon-m8-launch/qualification/stage3-read.json",
                 "/var/lib/constructicon-m8-launch/qualification/stage3-read-retry.json")
    try:
        sealed = json.loads(service(
            f"PYTHONPATH={ROOT}", sys.executable, "-m", "tests.substrate._read_rehearsal_host", W,
        ))
        service("/bin/sh", "-c", 'cat > "$1"', "sh", str(credential), stdin=EMPTY_AUTH)
        yield {"commit": commit, "credential": credential, **sealed}
    finally:
        service("/bin/sh", "-c", 'cat > "$1"', "sh", str(credential), stdin=original)
        assert record(str(credential)) == original
        subprocess.run(("sudo", "-n", "/bin/rm", "-rf", "--", *made, *installed), check=True,
                       stdin=subprocess.DEVNULL)


def turn(rehearsal, *, retry: bool = False) -> dict:
    ran = bash(steps(rehearsal["commit"], "T5. The one READ turn", retry=retry))
    assert ran.returncode == 0, ran.stderr[-4000:]
    lines = ran.stdout.strip().splitlines()
    return {"verdict": lines[-2], "run": lines[-1].removeprefix("run=")}


def test_t2_to_t5_refuse_at_the_gate_before_any_turn(rehearsal):
    prepared = bash(steps(rehearsal["commit"], "T2. Fresh state", "T3. Mint the pins",
                          "T4. Root installs"))
    assert prepared.returncode == 0, prepared.stderr[-4000:]
    assert turn(rehearsal) == {"verdict": "not-dispatched", "run": "failed"}
    written = json.loads(record("/home/m8-service/m8-n5-stage3/stage3.attempt"))
    assert (written["phase"], written["dispatch"]) == ("outcome", "not dispatched")
    facts = written["facts"]
    # The gate's own refusal, exactly: no other fault, no relay fault.
    assert facts["status"] == "failure"
    assert facts["refusal"] == f"unavailable: {NO_RESULT_FAULT}"
    # No connection at all: a nonzero count here would be a real one.
    assert facts["relay"] == {"destinations": {}, "denied": {}}
    # The vendor ran and exited cleanly on the production base runtime.
    process = facts["process"]
    assert process is not None and process["returncode"] == 0
    assert process["payload_returncode"] == 0
    assert process["timed_out"] is False and process["bound_exceeded"] is False
    # Stopped before the spend readback: nothing observed, nothing answered.
    assert facts["readbacks"] is None and facts["answer_bytes"] is None
    assert facts["usage"] == "unknown" and facts["served_model"] == "unknown"
    assert facts["identities"]["qualification"] == rehearsal["qualification"]
    assert facts["identities"]["operator_binding_digest"] == rehearsal["operator_binding_digest"]
    # The run left the logged-out credential as it found it.
    assert record(str(rehearsal["credential"])) == EMPTY_AUTH


def test_a_second_run_dispatches_nothing_with_or_without_its_journal(rehearsal):
    path = "/home/m8-service/m8-n5-stage3/stage3.attempt"
    before = hashlib.sha256(record(path)).hexdigest()
    # The journal still holds the first run: it replays, and acquires nothing.
    assert turn(rehearsal) == {"verdict": "not-dispatched", "run": "failed"}
    assert hashlib.sha256(record(path)).hexdigest() == before
    # Reset: acquisition refuses at the spent record, before writing anything.
    service("/bin/sh", "-c", 'rm -f -- "$1".sqlite "$1".sqlite-wal "$1".sqlite-shm', "sh",
            "/home/m8-service/m8-n5-stage3/stage3")
    assert turn(rehearsal) == {"verdict": "not-dispatched", "run": "failed"}
    assert hashlib.sha256(record(path)).hexdigest() == before


def test_t6_retries_under_entirely_new_names(rehearsal):
    first = hashlib.sha256(record("/home/m8-service/m8-n5-stage3/stage3.attempt")).hexdigest()
    prepared = bash(steps(rehearsal["commit"], "T2. Fresh state", "T3. Mint the pins",
                          "T4. Root installs", retry=True))
    assert prepared.returncode == 0, prepared.stderr[-4000:]
    assert turn(rehearsal, retry=True) == {"verdict": "not-dispatched", "run": "failed"}
    retried = json.loads(record("/home/m8-service/m8-n5-stage3r/stage3.attempt"))
    assert retried["dispatch"] == "not dispatched"
    assert retried["facts"]["refusal"] == f"unavailable: {NO_RESULT_FAULT}"
    assert retried["authorization_id"] != json.loads(
        record("/home/m8-service/m8-n5-stage3/stage3.attempt"),
    )["authorization_id"]
    assert hashlib.sha256(record("/home/m8-service/m8-n5-stage3/stage3.attempt")).hexdigest() \
        == first
