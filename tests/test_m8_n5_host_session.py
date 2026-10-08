"""Portable checks for the N5 Stage 2 host-session runbook and LR9.

They parse the runbooks only: no operator command runs, no host path is
touched, and no vendor binary or DNS is used.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.test_m8_operator_commands import PY_FENCE, _bash, _run_isolated

HANDOFFS = Path(__file__).parents[1] / "docs" / "plans" / "handoffs"
SESSION = HANDOFFS / "M8-N5-host-session.md"
OPERATOR = HANDOFFS / "M8-N4-operator-commands.md"
REPLACEMENT = HANDOFFS / "M8-N4-launch-replacement.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(document: str, heading: str) -> str:
    return document.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]


def _fences(text: str) -> list[str]:
    return [match.group("body") for match in PY_FENCE.finditer(text)]


def _setup() -> str:
    """OC's two Setup blocks followed by the session's override, as composed."""
    operator = _text(OPERATOR)
    setup = operator.split("## Setup", 1)[1].split("\n### ", 1)[0]
    override = _fences(_section(_text(SESSION), "How to run"))[0]
    return "\n".join([*_fences(setup), override])


def test_every_session_block_parses_after_the_composed_common_file():
    common = _setup()
    for fence in _fences(_text(SESSION)):
        checked = subprocess.run(
            [_bash(), "-n"], input=common + "\n" + fence,
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert checked.returncode == 0, checked.stderr


def test_the_session_writes_a_fresh_directory_and_only_reads_n4s():
    override = _fences(_section(_text(SESSION), "How to run"))[0]
    assert override.splitlines() == [
        "W_OLD=/home/m8-service/m8-n4-session",
        "W=/home/m8-service/m8-n5-stage2",
    ]
    assert "W=/home/m8-service/m8-n4-session" in _text(OPERATOR)
    for fence in _fences(_text(SESSION)):
        for line in fence.splitlines():
            if "$W_OLD" in line:
                assert line.lstrip().startswith("binding_check"), line


def test_every_step_is_present_in_order():
    document = _text(SESSION)
    headings = [
        "H0. Authorization", "H1. Launch and controller", "H2. S0", "H3. S1",
        "H4. S4", "H5. S6a", "H6. Publish and activate g4", "H7. Active startup on g4",
        "H8. Refresh attempts",
    ]
    positions = [document.index(f"## {heading}") for heading in headings]
    assert positions == sorted(positions)
    operator = _text(OPERATOR)
    for reused in ("S1. Prepare", "S4. Qualification", "S6a. Maintenance-lock", "S5. Publish"):
        assert f"### {reused}" in operator


def test_g4_is_published_activated_and_g3_refuses_against_it():
    block = _fences(_section(_text(SESSION), "H6. Publish and activate g4"))[0]
    assert "publish --store-root \"$R\" --key \"$K\" --generation 4" in block
    assert "activate --store-root \"$R\" --key \"$K\" --generation 4" in block
    assert 'binding_check "$W/g4.sealed.json" accepted -' in block
    assert 'binding_check "$W_OLD/g3.sealed.json" stale-generation "$W/g4.sealed.json"' in block
    document = _text(SESSION)
    assert not re.search(r"--generation [123]\b|g[12]\.sealed", document)


def test_s4s_plan_must_continue_n4s():
    block = _fences(_section(_text(SESSION), "H4. S4, and the plan's continuity"))[0]
    assert 'test "${S4_SEAL%%/*}" = pro' in block


def test_every_active_startup_names_g4_its_seal_and_a_fresh_name():
    document = _text(SESSION)
    startups = re.findall(r"startup --custody active.*?--evidence \"(\S+)\"", document, re.S)
    assert len(startups) == len(set(startups)) == 4
    for match in re.finditer(r"startup --custody active(.*?)< /dev/null", document, re.S):
        assert '--sealed "$W/g4.sealed.json"' in match.group(1)
        assert "--expected" in match.group(1)


def test_each_refresh_attempt_is_numbered_checked_active_first_and_timeless():
    block = _fences(_section(_text(SESSION), "H8. Refresh attempts"))[0]
    assert block.splitlines()[0] == '[[ "${N:?Set the attempt number}" =~ ^[1-9][0-9]?$ ]]'
    assert '--lane-dir "$W/h8-$N-lane" --evidence "$W/h8-$N-refresh.json"' in block
    assert block.index("m8-host-drift") < block.index("load_final_qualification")
    assert block.index("check_evidence active") < block.index("check_evidence refresh")
    assert "s3-completed-at" not in _text(SESSION)


def test_every_lane_flag_the_session_passes_is_offered():
    flags = set(re.findall(r"(--[a-z][a-z-]+)", "\n".join(_fences(_text(SESSION)))))
    lane = _run_isolated("constructicon.substrate.executors.codex_lane", "startup", "--help")
    publish = _run_isolated("constructicon.substrate.executors.operator_store", "publish", "--help")
    activate = _run_isolated(
        "constructicon.substrate.executors.operator_store", "activate", "--help",
    )
    offered = lane.stdout + publish.stdout + activate.stdout
    assert lane.returncode == publish.returncode == activate.returncode == 0
    for flag in flags - {"--generation"}:
        assert flag in offered, flag
    assert "--generation" in publish.stdout and "--generation" in activate.stdout


def test_lr9_removes_only_the_controller_and_runs_after_lr8s_fetch():
    section = _section(_text(REPLACEMENT), "LR9. Controller replacement after login")
    (block,) = _fences(section)
    assert 'test -s "$W/wheels.txt" && test -s "$W/verify.json"' in block
    assert "sudo /usr/bin/rm -rf --one-file-system /opt/constructicon-m8-controller" in block
    assert block.index("test -s") < block.index("rm -rf") < block.index("test ! -e")
    assert "run R18 and R19 exactly as written" in " ".join(section.split())
    order = " ".join(_section(_text(REPLACEMENT), "Order").split())
    assert "LR0 to LR6, then LR8, then LR9 if LR8 refused, then LR7" in order


@pytest.mark.parametrize("phrase", ["gpt-5.5", "s3-completed-at.utc\" < /dev/null | /usr/bin/grep"])
def test_no_stale_session_literal_is_reused(phrase):
    assert phrase not in _text(SESSION)
