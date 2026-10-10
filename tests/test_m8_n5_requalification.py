"""Portable checks for the N5 g5 requalification successor instructions.

These parse and exercise only local shell snippets with fake seal readers. They
do not run operator commands or touch a host, store, account or vendor binary.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import PY_FENCE, _bash

SUCCESSOR = HANDOFFS / "M8-N5-requalification.md"
OPERATOR = HANDOFFS / "M8-N4-operator-commands.md"


def _successor_fences(heading: str) -> list[str]:
    return [fence.strip() for fence in _fences(_section(_text(SUCCESSOR), heading))]


def _g5_common() -> str:
    operator = _text(OPERATOR)
    setup = operator.split("## Setup", 1)[1].split("\n### ", 1)[0]
    assignments = _successor_fences("Authorization and common file after LR")[1]
    return "\n".join([*_fences(setup), assignments])


def test_every_shell_block_parses_with_the_composed_common_file():
    common = _g5_common()
    for match in PY_FENCE.finditer(_text(SUCCESSOR)):
        checked = subprocess.run(
            [_bash(), "-n"], input=common + "\n" + match.group("body"),
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert checked.returncode == 0, checked.stderr


def test_preboot_capture_reads_old_evidence_and_creates_only_private_seal():
    block = _successor_fences("Before LR's reboot: preserve the old account seal")[0]
    assert block.splitlines() == [
        'binding_check "$W/g4.sealed.json" accepted -',
        "load_final_qualification",
        'check_sealed "$W/g4.sealed.json" "$Q"',
        'test "${SEAL%%/*}" = pro \\',
        "  || { echo 'prior S6a plan is not N4-qualified pro; stop' >&2; exit 1; }",
        'test -n "$SEAL"',
        "set -C",
        'printf \'%s\\n\' "$SEAL" > "$HOME/n5-g5-account.seal"',
    ]
    assert "/home/m8-service/m8-n5-stage2" in _text(SUCCESSOR)
    assert not any("$W/" in line and ">" in line for line in block.splitlines())
    assert "Do not print or post it" in _text(SUCCESSOR)


@pytest.mark.parametrize(
    ("binding", "sealed_q", "seal", "expected"),
    [
        ("accepted", "q1", "pro/sha256:" + "a" * 64, 0),
        ("refused", "q1", "pro/sha256:" + "a" * 64, 1),
        ("accepted", "other-q", "pro/sha256:" + "a" * 64, 1),
        ("accepted", "q1", "plus/sha256:" + "a" * 64, 1),
    ],
    ids=["g4-seal-accepted", "binding-refused", "qualification-digest-mismatch", "wrong-plan"],
)
def test_preboot_capture_requires_g4_binding_digest_and_prior_plan(
    tmp_path: Path, binding: str, sealed_q: str, seal: str, expected: int,
):
    block = _successor_fences("Before LR's reboot: preserve the old account seal")[0]
    script = "\n".join([
        "set -Eeuo pipefail",
        "umask 077",
        'W="/old/stage2"',
        'binding_check() {',
        '  test "$1" = "$W/g4.sealed.json" &&',
        '    test "$2" = accepted &&',
        '  test "$FAKE_BINDING" = accepted',
        "}",
        'load_final_qualification() { Q="$FAKE_Q"; SEAL="$FAKE_SEAL"; }',
        'check_sealed() { test "$1" = "$W/g4.sealed.json" && test "$2" = "$FAKE_SEALED_Q"; }',
        block,
    ])
    home = tmp_path / "operator-home"
    home.mkdir()
    result = subprocess.run(
        [_bash(), "-c", script], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "C": "c" * 40,
            "FAKE_BINDING": binding,
            "FAKE_Q": "q1",
            "FAKE_SEALED_Q": sealed_q,
            "FAKE_SEAL": seal,
        },
    )
    assert result.returncode == expected, result.stderr
    saved = home / "n5-g5-account.seal"
    if expected == 0:
        assert saved.read_text(encoding="utf-8") == seal + "\n"
    else:
        assert not saved.exists()


def test_preboot_capture_refuses_to_overwrite_existing_seal(tmp_path: Path):
    block = _successor_fences("Before LR's reboot: preserve the old account seal")[0]
    home = tmp_path / "operator-home"
    home.mkdir()
    seal_file = home / "n5-g5-account.seal"
    seal_file.write_text("prior-value\n", encoding="utf-8")
    script = "\n".join([
        "set -Eeuo pipefail",
        "umask 077",
        'W="/old/stage2"',
        'binding_check() { test "$1" = "$W/g4.sealed.json" && test "$2" = accepted; }',
        'load_final_qualification() { Q="q1"; SEAL="pro/sha256:' + "a" * 64 + '"; }',
        'check_sealed() { test "$1" = "$W/g4.sealed.json" && test "$2" = q1; }',
        block,
    ])
    result = subprocess.run(
        [_bash(), "-c", script], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, check=False,
        env={**os.environ, "HOME": str(home)},
    )
    assert result.returncode != 0
    assert seal_file.read_text(encoding="utf-8") == "prior-value\n"


def test_new_common_uses_fresh_w_and_reads_prior_seal_without_evaluating_it():
    block = _successor_fences("Authorization and common file after LR")[1]
    assert block.splitlines() == [
        "W_OLD=/home/m8-service/m8-n4-session",
        "W_PRIOR=/home/m8-service/m8-n5-stage2",
        "W=/home/m8-service/m8-n5-stage2r",
        'PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/n5-g5-account.seal")"',
    ]
    assert "eval" not in block


def test_h1_h6_h7_h8_and_read_commands_pin_g5():
    h1 = _successor_fences("Authorization and common file after LR")[0]
    assert h1 == 'binding_check "$W/g4.sealed.json" reboot-anchor -'

    h6 = _successor_fences("H6: publish and activate g5")[0]
    assert "--generation 5" in h6
    assert '"$W/g5.sealed.json"' in h6
    assert 'binding_check "$W_PRIOR/g4.sealed.json" stale-generation "$W/g5.sealed.json"' in h6
    assert "--generation 4" not in h6

    h7 = _successor_fences("H7: repeat active startup and both refusals on g5")[0]
    assert h7.count('--sealed "$W/g5.sealed.json"') == 3
    assert 'binding_check "$W_PRIOR/g4.sealed.json" stale-generation "$W/g5.sealed.json"' in h7
    assert '"$W/g4.sealed.json"' not in h7

    h8 = _successor_fences("H8: refresh attempts on g5")[0]
    assert '--sealed "$W/g5.sealed.json"' in h8
    assert '"$W/h8-g5-$N-lane"' in h8
    assert '"$W/h8-g5-$N-refresh.json"' in h8

    read = _successor_fences("Stage 3 READ successor")
    assert 'binding_check "$W/g5.sealed.json" accepted -' in read[0]
    assert '--sealed "$W/g5.sealed.json"' in read[1]
    assert '--qualification "$W/s6a-qualification.json"' in read[1]
    assert "n5-stage3g5-$C" in read[1]
    retry = _successor_fences("Stage 3 READ successor")[2]
    assert '--sealed "$W/g5.sealed.json"' in retry
    assert '--qualification "$W/s6a-qualification.json"' in retry
    assert '"$S/stage3.attempt"' not in retry


def test_owner_transport_hashes_scp_files_and_runs_plain_bash_without_stdin_pipe():
    transport = _successor_fences("H0-H5: authorization, setup and qualification")[0]
    assert "/usr/bin/grep -Fqx \"C=$C\" n5-g5-h3.sh" in transport
    assert "grep -q $'\\r' n5-g5-common.sh n5-g5-h3.sh" in transport
    assert "/usr/bin/sha256sum -- n5-g5-common.sh n5-g5-h3.sh > n5-g5-h3.sha256" in transport
    assert "scp -o BatchMode=yes -o StrictHostKeyChecking=yes" in transport
    assert "ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes" in transport
    assert "sha256sum --check --strict n5-g5-h3.sha256" in transport
    assert "bash n5-g5-h3.sh" in transport
    assert "< /dev/null" in transport
    assert "|" not in transport
    assert "/bin/bash -se" not in transport
    document = _text(SUCCESSOR)
    assert 'source "$HOME/n5-g5-common.sh"' in document
    assert "Do not prepend or source `n5-g5-common.sh` for LR." in " ".join(document.split())
    assert "HS H5 is OC's S6a Maintenance-lock positive control" in " ".join(document.split())


def test_read_state_paths_remain_within_existing_bound_and_attempt_names_are_fresh():
    blocks = _successor_fences("Stage 3 READ successor")
    first = dict(re.findall(r"^(S|A|ID|KEY)=(\S+)$", blocks[1], re.M))
    retry = dict(re.findall(r"^(S|A|ID|KEY)=(\S+)$", blocks[2], re.M))
    old_state = "/home/m8-service/m8-n5-stage3"
    assert len(first["S"]) <= len(old_state)
    assert len(retry["S"]) <= len(old_state)
    assert set(first) == set(retry) == {"S", "A", "ID", "KEY"}
    assert all(first[name] != retry[name] for name in first)


@pytest.mark.parametrize(
    ("prior", "fresh", "expected"),
    [
        ("pro/sha256:" + "a" * 64, "pro/sha256:" + "a" * 64, 0),
        ("pro/sha256:" + "a" * 64, "pro/sha256:" + "b" * 64, 1),
    ],
    ids=["same-seal-accepted", "changed-seal-refused"],
)
def test_h4_requires_fresh_s4_to_equal_prior_seal(prior: str, fresh: str, expected: int):
    block = _successor_fences("H0-H5: authorization, setup and qualification")[1]
    script = "\n".join([
        "read_seal() { printf '%s\\n' \"$FAKE_S4\"; }",
        "W=/not-read-by-this-fake",
        'S4_SEAL="$(read_seal "$W/s4-qualification.json")"',
        'PRIOR_SEAL="$FAKE_PRIOR"',
        block,
    ])
    result = subprocess.run(
        [_bash(), "-c", script], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, check=False,
        env={**os.environ, "C": "c" * 40, "FAKE_S4": fresh, "FAKE_PRIOR": prior},
    )
    assert result.returncode == expected, result.stderr


def test_successor_references_frozen_runbooks_without_transform_commands():
    document = _text(SUCCESSOR)
    assert "M8-N4-operator-commands.md" in document
    assert "M8-N4-launch-replacement.md" in document
    assert "M8-N5-host-session.md" in document
    assert "M8-N5-read-session.md" in document
    assert "8a0d87d" in document
    assert "`sed`" in document
    assert not any(
        line.lstrip().startswith(("sed ", "perl "))
        for line in document.splitlines()
    )
