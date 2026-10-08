"""Portable checks for the N5 Stage 2 host-session runbook and LR9.

They parse the runbooks only: no operator command runs, no host path is
touched, and no vendor binary or DNS is used.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
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


@pytest.mark.parametrize(
    ("seal", "status"),
    [(f"pro/sha256:{'a' * 64}", 0), (f"prolite/sha256:{'a' * 64}", 1), ("pro", 0)],
)
def test_s4s_plan_must_continue_n4s(seal, status):
    """Run, not read: the seal is `<plan>/<identity>`, and only N4's `pro` passes."""
    block = _fences(_section(_text(SESSION), "H4. S4, and the plan's continuity"))[0]
    script = f"set -Eeuo pipefail\nS4_SEAL='{seal}'\n{block}"
    ran = subprocess.run(
        [_bash(), "-c", script], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert ran.returncode == status, ran.stderr


def test_s1s_documented_output_is_what_prepare_prints(tmp_path, monkeypatch, capsys):
    from constructicon.substrate.executors import codex_lane

    monkeypatch.setattr(codex_lane, "prepare", lambda out: None)
    assert codex_lane.main(["prepare", "--out", str(tmp_path / "w")]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["prepared"] is True
    assert '`"prepared": true`' in _text(SESSION)


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


COMMANDS = {
    "startup": ("constructicon.substrate.executors.codex_lane", "startup"),
    "publish": ("constructicon.substrate.executors.operator_store", "publish"),
    "activate": ("constructicon.substrate.executors.operator_store", "activate"),
}


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_every_flag_each_command_passes_is_its_own_parsers(command):
    """Per command, not pooled: a store flag on a lane command must fail here."""
    module, subcommand = COMMANDS[command]
    calls = re.findall(
        rf"\b{command} (--.*?)(?:< /dev/null|\|)", "\n".join(_fences(_text(SESSION))), re.S,
    )
    assert calls, command
    offered = _run_isolated(module, subcommand, "--help")
    assert offered.returncode == 0, offered.stderr
    for call in calls:
        for flag in re.findall(r"(--[a-z][a-z-]+)", call):
            assert flag in offered.stdout, (command, flag)


def _lr9_gate() -> str:
    section = _section(_text(REPLACEMENT), "LR9. Controller replacement after login")
    (block,) = _fences(section)
    return re.search(r"-c '(?P<body>.*?)' \"\$W/verify\.json\"", block, re.S).group("body")


@pytest.mark.parametrize(
    ("record", "refused_a_tree"),
    [
        ({"installed": False, "observed": {"/opt/constructicon-m8-controller": {
            "state": "tree", "different": 7}}}, True),
        ({"installed": True, "observed": {"/opt/constructicon-m8-controller": {
            "state": "tree", "different": 0}}}, False),
        ({"installed": False, "observed": {"/opt/constructicon-m8-controller": {
            "state": "absent"}}}, False),
        ({"installed": False, "failure": "the plan never computed"}, False),
    ],
    ids=["refused-tree", "current", "absent", "uncomputed"],
)
def test_lr9_removes_only_after_lr8_refused_an_installed_tree(tmp_path, record, refused_a_tree):
    """Run, not read: LR9's gate on the four shapes LR8's record can take."""
    record_path = tmp_path / "verify.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    ran = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", _lr9_gate(), str(record_path)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False,
    )
    assert (ran.stdout.strip() == "lr8-refused-a-tree") is refused_a_tree


def test_lr9_sets_lr8s_workspace_aside_then_runs_r17_to_r19_verbatim():
    section = _section(_text(REPLACEMENT), "LR9. Controller replacement after login")
    (block,) = _fences(section)
    order = [
        block.index("lr8-refused-a-tree"),
        block.index('/usr/bin/mv -n "$W" "$HOME/m8-controller-refused-$C"'),
        block.index("sudo /usr/bin/rm -rf --one-file-system /opt/constructicon-m8-controller"),
        block.index("test ! -e /opt/constructicon-m8-controller"),
    ]
    assert order == sorted(order)
    assert "run R17 to R19 exactly as written, with their failure table" in " ".join(
        section.split(),
    )
    order_text = " ".join(_section(_text(REPLACEMENT), "Order").split())
    assert "LR0 to LR6, then LR8, then LR9 if LR8 refused, then LR7" in order_text


@pytest.mark.parametrize("phrase", ["gpt-5.5", "s3-completed-at.utc\" < /dev/null | /usr/bin/grep"])
def test_no_stale_session_literal_is_reused(phrase):
    assert phrase not in _text(SESSION)
