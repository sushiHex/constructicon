"""Portable checks for the N5 Stage 3 READ-turn session runbook.

They parse and run the runbook's own programs against synthetic records: no
operator command runs, no host path is touched, and no vendor binary is used.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

import pytest

from constructicon.core.identity import digest
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors.codex import AcquisitionPaths
from constructicon.substrate.executors.codex_host import READ_GRANTS
from constructicon.substrate.executors.egress import MAX_SOCKET_PATH_BYTES, SOCKET_NAME
from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _setup, _text
from tests.test_m8_operator_commands import _bash, _run_isolated

SESSION = HANDOFFS / "M8-N5-read-session.md"


def _override() -> str:
    return _fences(_section(_text(SESSION), "How to run"))[0]


def _program(heading: str) -> str:
    """The one isolated Python program in a step's block."""
    block = _fences(_section(_text(SESSION), heading))[-1]
    (program,) = re.findall(r"python3 -I -S -B -c '(.*?)'\s", block, re.S)
    return program


def _run(program: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", program, *arguments], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, check=False,
    )


def test_every_block_parses_after_the_composed_common_file():
    common = _setup() + "\n" + _override()
    for fence in _fences(_text(SESSION)):
        checked = subprocess.run(
            [_bash(), "-n"], input=common + "\n" + fence,
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert checked.returncode == 0, checked.stderr


def test_every_step_is_present_in_order():
    document = _text(SESSION)
    headings = [
        "T0. Authorization", "T1. The host is still Stage 2's", "T2. Fresh state",
        "T3. Mint the pins", "T4. Root installs", "T5. The one READ turn", "T6. One retry",
    ]
    positions = [document.index(f"## {heading}") for heading in headings]
    assert positions == sorted(positions)


ATTEMPT_NAMES = ("S", "A", "ID", "KEY")


def _attempt(block: str) -> dict[str, str]:
    """The attempt's names, as a block assigns them."""
    return dict(re.findall(rf"^({'|'.join(ATTEMPT_NAMES)})=(\S+)$", block, re.M))


def _retry() -> str:
    return _fences(_section(_text(SESSION), "T6. One retry"))[0]


@pytest.mark.parametrize("block", ["first", "retry"])
def test_each_state_directory_fits_the_egress_socket_bound(block):
    state = _attempt(_override() if block == "first" else _retry())["S"]
    longest = AcquisitionPaths(PurePosixPath(state) / "acquisitions", "acq-" + "0" * 32).payload
    socket = str(longest).replace("\\", "/") + "/" + SOCKET_NAME
    assert len(os.fsencode(socket)) <= MAX_SOCKET_PATH_BYTES, socket


def _expanded_host(*blocks: str) -> list[str]:
    """`HOST` as bash expands it after the composed common file and blocks."""
    script = "\n".join([_setup(), _override(), *blocks, 'printf "%s\\n" "${HOST[@]}"'])
    ran = subprocess.run(
        [_bash(), "-s"], input=script, capture_output=True, text=True,
        timeout=30, check=False, env={**os.environ, "C": "c" * 40},
    )
    assert ran.returncode == 0, ran.stderr
    return ran.stdout.splitlines()


def test_each_attempt_passes_its_own_state_to_every_command():
    """`HOST` captures `S` when built, so the retry must build it again."""
    first, retry = _expanded_host(), _expanded_host(_retry())
    assert first[first.index("--state") + 1] == _attempt(_override())["S"]
    assert retry[retry.index("--state") + 1] == _attempt(_retry())["S"]


def test_the_retry_renames_everything_the_first_attempt_named():
    first, retry = _attempt(_override()), _attempt(_retry())
    assert set(first) == set(retry) == set(ATTEMPT_NAMES)
    assert all(first[name] != retry[name] for name in ATTEMPT_NAMES)
    mint = _fences(_section(_text(SESSION), "T3. Mint the pins"))[0]
    for used in ('"$S/stage3.attempt"', '"$S/stage3.sqlite"', '"$ID"', '"$KEY"'):
        assert used in mint, used


@pytest.mark.parametrize("command", ["mint", "run"])
def test_every_flag_passed_is_offered_under_the_controllers_runpy_entry(command):
    """Run as OC's `PY` runs modules: `runpy` as `__main__`, from this tree."""
    document = "\n".join([_override(), *_fences(_text(SESSION))])
    calls = re.findall(rf'"\$\{{QUAL\[@\]\}}" {command} (.*?)< /dev/null', document, re.S)
    assert calls, command
    offered = _run_isolated("constructicon.api.qualification", command, "--help")
    assert offered.returncode == 0, offered.stderr
    for flag in re.findall(r"(--[a-z][a-z-]+)", "\n".join([*calls, _override()])):
        assert flag in offered.stdout, (command, flag)


def _minted(tmp_path: Path, **changes) -> Path:
    authorization = QualificationAuthorization(**{
        "authorization_id": "n5-stage3-c", "stage": "qualification-read",
        "actor_id": "operator:n5-stage3", "idempotency_key": "stage3",
        "scope": {"segments": ["constructicon-qualification-read", "read"]},
        "binding": "executor", "source_graph_hash": digest("test-graph", 1, "read"),
        "capability_id": "codex-operator", "revision": "r",
        "operator_binding_digest": digest("test-binding", 1, "store"),
        "journal": "/s/stage3.sqlite", "max_epoch": 1,
        "not_after": datetime.now(UTC) + timedelta(hours=2), "grants": READ_GRANTS,
        "attempt_record": "/s/stage3.attempt", **changes,
    })
    path = tmp_path / "minted.json"
    path.write_text(authorization.model_dump_json(), encoding="utf-8")
    return path


def test_t3_prints_the_reviewed_pins_of_a_read_authorization(tmp_path):
    ran = _run(_program("T3. Mint the pins"), str(_minted(tmp_path)), "/s/stage3.attempt",
               "/s/stage3.sqlite")
    assert ran.returncode == 0, ran.stderr
    assert set(json.loads(ran.stdout)) == {
        "authorization_id", "source_graph_hash", "revision", "operator_binding_digest",
        "not_after",
    }


@pytest.mark.parametrize(
    "arguments", [("/s/other.attempt", "/s/stage3.sqlite"), ("/s/stage3.attempt", "/s/x")],
    ids=["record", "journal"],
)
def test_t3_refuses_pins_naming_another_record_or_journal(tmp_path, arguments):
    assert _run(_program("T3. Mint the pins"), str(_minted(tmp_path)), *arguments).returncode


@pytest.mark.parametrize(
    ("record", "run", "verdict"),
    [
        ({"phase": "outcome", "dispatch": "completed"}, "succeeded", "passed"),
        ({"phase": "outcome", "dispatch": "completed"}, "failed", "completed-run-failed"),
        ({"phase": "outcome", "dispatch": "not dispatched"}, "failed", "not-dispatched"),
        ({"phase": "outcome", "dispatch": "possibly dispatched"}, "failed", "possibly-dispatched"),
        ({"phase": "intent"}, "failed", "possibly-dispatched"),
        ({"phase": "acquired"}, "failed", "acquired-only"),
        (None, "failed", "never-acquired"),
    ],
)
def test_t5_reads_the_verdict_from_the_run_and_the_attempt_record(tmp_path, record, run, verdict):
    """Only a succeeded run and a completed record pass: the turn completes
    inside `execute`, before the run's checkpoint and closure can still fail."""
    path = tmp_path / "stage3.attempt"
    if record is not None:
        path.write_text(json.dumps(record), encoding="utf-8")
    ran = _run(_program("T5. The one READ turn"), str(path), run)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == verdict
    assert f"**`{verdict}`" in _text(SESSION)


def test_t5_records_the_runs_status_without_stopping_before_the_verdict():
    block = _fences(_section(_text(SESSION), "T5. The one READ turn"))[0]
    assert "then RUN=succeeded; else RUN=failed; fi" in block
    assert '"$S/stage3.attempt" "$RUN"' in block
