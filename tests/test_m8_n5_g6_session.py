"""Exercise the g6 successor's local shell composition without a private host."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import PY_FENCE, _bash

DOCUMENT = HANDOFFS / "M8-N5-g6-session.md"
C = "585df33eb196cd4afd10d5c12cb1efb37fd5a6e1"
OLD_COMMIT = "ce08c6b363a56dcbac942edf021afc94800334fb"
D = "8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3"
SEAL = "pro/sha256:" + "a" * 64


def _blocks(heading: str) -> list[str]:
    return [block.strip() for block in _fences(_section(_text(DOCUMENT), heading))]


def _run(script: str, **environment: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_bash(), "-c", script], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, check=False,
        env={**os.environ, **environment},
    )


def test_every_shell_block_parses_with_the_composed_common():
    operator = _text(HANDOFFS / "M8-N4-operator-commands.md")
    setup = operator.split("## Setup", 1)[1].split("\n### ", 1)[0]
    common = "\n".join([
        *_fences(setup), _blocks("H2-H5: fresh g6 maintenance qualification")[0],
    ])
    refresh = _fences(_text(HANDOFFS / "M8-N5-explicit-refresh.md"))
    assert len(refresh) == 1
    blocks = [match.group("body") for match in PY_FENCE.finditer(_text(DOCUMENT))]
    for block in [*blocks, refresh[0]]:
        result = subprocess.run(
            [_bash(), "-n"], input=common + "\n" + block,
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_deployment_commit_and_old_install_records_are_distinct_from_document_revision():
    document = _text(DOCUMENT)
    assert C in document and OLD_COMMIT in document and D in document
    assert "later documentation revision" in document
    assert "not an artifact present at" in document
    assert "not fresh observations of the host" in document
    assert "Run no host command until" in document
    assert "Before continuity capture or reboot, reconfirm exclusive operator custody" in document
    assert "Stop if ownership or quiescence is uncertain" in document
    assert "at `O`" in document
    for name in (
        "M8-N4-operator-commands.md", "M8-N4-launch-replacement.md",
        "M8-N5-host-session.md", "M8-N5-read-session.md", "M8-N5-explicit-refresh.md",
        "M8-D2-host-installation.md",
    ):
        assert name in document
    assert not any(line.lstrip().startswith(("sed ", "perl ")) for line in document.splitlines())


@pytest.mark.parametrize(
    ("failure", "seal", "existing"),
    [
        ("none", SEAL, False), ("binding", SEAL, False),
        ("qualification", SEAL, False), ("seal", SEAL, False),
        ("none", "plus/sha256:" + "a" * 64, False), ("none", SEAL, True),
    ],
    ids=[
        "checked-g5", "binding-refused", "qualification-refused", "digest-refused",
        "plan-refused", "existing-file",
    ],
)
def test_prior_g5_capture_requires_checked_evidence_and_exclusive_private_file(
    tmp_path: Path, failure: str, seal: str, existing: bool,
):
    prior, capture = _blocks("Before LR's reboot: capture checked g5 continuity")
    assert prior == "W=/home/m8-service/m8-n5-stage2r"
    home = tmp_path / "operator-home"
    home.mkdir()
    private = home / "n5-g6-account.seal"
    if existing:
        private.write_text("preserved\n", encoding="utf-8")
    script = "\n".join([
        "set -Eeuo pipefail", "umask 077", prior,
        'check() { test "$FAILURE" != "$1"; }',
        'binding_check() { test "$*" = "$W/g5.sealed.json accepted -"; check binding; }',
        'load_final_qualification() { check qualification; Q=q; SEAL="$FAKE_SEAL"; }',
        'check_sealed() { test "$*" = "$W/g5.sealed.json q"; check seal; }',
        capture,
    ])
    result = _run(script, HOME=str(home), FAILURE=failure, FAKE_SEAL=seal)
    assert result.stdout == ""
    if failure == "none" and seal == SEAL and not existing:
        assert result.returncode == 0, result.stderr
        assert private.read_text(encoding="utf-8") == SEAL + "\n"
    else:
        assert result.returncode != 0
        if existing:
            assert private.read_text(encoding="utf-8") == "preserved\n"
        else:
            assert not private.exists()
    assert not any("$W/" in line and ">" in line for line in capture.splitlines())


def test_new_common_reads_private_seal_as_data_and_keeps_g5_history():
    block = _blocks("H2-H5: fresh g6 maintenance qualification")[0]
    assert block.splitlines() == [
        "W_PRIOR=/home/m8-service/m8-n5-stage2r",
        "W=/home/m8-service/m8-n5-stage2g6",
        'PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/n5-g6-account.seal")"',
    ]
    assert "eval" not in block
    anchor = _blocks("H1: LR and D2 on one fresh boot")[0]
    assert anchor == 'binding_check "$W/g5.sealed.json" reboot-anchor -'


@pytest.mark.parametrize(
    "fresh", [SEAL, "pro/sha256:" + "b" * 64], ids=["same-account", "changed-account"],
)
def test_h4_compares_fresh_s4_with_checked_prior_g5(fresh: str):
    block = _blocks("H2-H5: fresh g6 maintenance qualification")[1]
    result = _run(
        "\n".join(["set -Eeuo pipefail", 'PRIOR_SEAL="$PRIOR"', 'S4_SEAL="$FRESH"', block]),
        PRIOR=SEAL, FRESH=fresh,
    )
    assert result.returncode == (0 if fresh == SEAL else 1), result.stderr


@pytest.mark.parametrize(
    "failure", ["none", "qualification", "publish", "seal", "activate", "accepted", "stale"],
)
def test_h6_checks_new_qualification_before_activation_and_requires_stale_g5(failure: str):
    block = _blocks("H6: publish and activate g6")[0]
    script = "\n".join([
        "set -Eeuo pipefail", "R=store; K=key; W=fresh; W_PRIOR=prior",
        'check() { test "$FAILURE" != "$1"; }',
        'load_final_qualification() { check qualification; Q=new-q; }',
        'root_store() {',
        '  local operation="$1"; shift',
        '  case "$operation" in',
        '    publish) test "$*" = "--store-root store --key key --generation 6 '
        '--qualification-evidence-digest new-q --service m8-service --wait 0" ;;',
        '    activate) test "$*" = "--store-root store --key key --generation 6 '
        '--sealed fresh/g6.sealed.json --qualification-evidence-digest new-q '
        '--service m8-service --wait 0" ;;',
        '    *) return 2 ;;',
        '  esac',
        '  check "$operation"',
        '  printf "%s\\n" "$operation"',
        "}",
        'save_sealed() { test "$1" = fresh/g6.sealed.json; /usr/bin/cat; }',
        'check_sealed() { test "$*" = "fresh/g6.sealed.json new-q"; check seal; }',
        'binding_check() {',
        '  if test "$2" = accepted; then',
        '    test "$*" = "fresh/g6.sealed.json accepted -"; check accepted',
        '  else',
        '    test "$*" = "prior/g5.sealed.json stale-generation fresh/g6.sealed.json"; check stale',
        '    echo g5-stale',
        "  fi", "}", "ROOT_STORE=(root_store)", block,
    ])
    result = _run(script, FAILURE=failure)
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["publish", "activate", "g5-stale"]
    else:
        assert result.returncode != 0
        assert "g5-stale" not in result.stdout
        if failure in {"qualification", "publish", "seal"}:
            assert "activate" not in result.stdout


@pytest.mark.parametrize(
    ("failure", "refresh"),
    [
        ("none", "unmeasured"), ("none", "measured"),
        *[(failure, "unmeasured") for failure in (
            "qualification", "active-run", "active", "policy", "denial-status",
            "denial", "wrongplan-status", "wrongplan", "stale",
        )],
    ],
)
def test_h7_executes_all_controls_and_stops_on_failed_control(failure: str, refresh: str):
    block = _blocks("H7: active startup and both refusals on g6")[0]
    script = "\n".join([
        "set -Eeuo pipefail",
        "R=store; K=key; L=launch; W=fresh; W_PRIOR=prior; SERVICE=(service); LANE=(lane)",
        'check() { test "$FAILURE" != "$1"; }',
        'load_final_qualification() { check qualification; SEAL=pro/private; }',
        'service() {',
        '  if test "$1" = /usr/bin/python3; then echo policy; check policy; return; fi',
        '  test "$1 $2" = "lane startup"',
        '  case "$*" in',
        '    *h7-g6-s6b-denial.json*) echo denial-run; '
        'test "$FAILURE" = denial-status && return 0; return 1 ;;',
        '    *h7-g6-s6c-plan-refusal.json*) echo wrongplan-run; '
        'test "$FAILURE" = wrongplan-status && return 2; return 1 ;;',
        '    *h7-g6-active.json*) echo active-run; check active-run ;;',
        '    *) return 3 ;;',
        '  esac', "}",
        'check_evidence() { '
        'if test "$1" = refresh; then test "$REFRESH" = measured; else check "$1"; fi; }',
        'binding_check() { '
        'test "$*" = "prior/g5.sealed.json stale-generation fresh/g6.sealed.json"; '
        'check stale; echo g5-stale; }',
        block,
    ])
    result = _run(script, FAILURE=failure, REFRESH=refresh)
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "active-run", "refresh-" + refresh, "policy", "denial-run", "wrongplan-run", "g5-stale",
        ]
    else:
        assert result.returncode != 0
        assert "g5-stale" not in result.stdout
        if failure in {
            "qualification", "active-run", "active", "policy", "denial-status", "denial",
        }:
            assert "wrongplan-run" not in result.stdout
    assert block.count('--sealed "$W/g6.sealed.json"') == 3
    assert "--request-refresh" not in block


@pytest.mark.parametrize(
    "failure", ["none", "sudo", "drift", "qualification", "binding", "seal", "launch"],
)
def test_h8_composes_exact_g6_declarations_with_one_unchanged_r1_attempt(failure: str):
    declarations = _blocks("H8: one explicit-refresh attempt if still unmeasured")[0]
    r1, = _fences(_text(HANDOFFS / "M8-N5-explicit-refresh.md"))
    # Substitute only the platform-owned absolute command, as in the ER test.
    r1 = r1.replace("/usr/local/bin/m8-host-drift", "drift")
    script = "\n".join([
        "set -Eeuo pipefail",
        "R=store; K=key; L=launch; W=fresh; SERVICE=(service); LANE=(lane)",
        'check() { test "$FAILURE" != "$1"; }',
        'sudo() { test "$*" = "-n true"; check sudo; }',
        'drift() { check drift; }',
        'load_final_qualification() { check qualification; Q=q; SEAL=pro/private; }',
        'binding_check() { test "$*" = "fresh/g6.sealed.json accepted -"; check binding; }',
        'check_sealed() { test "$*" = "fresh/g6.sealed.json q"; check seal; }',
        'service() { check launch; printf "ARG:%s\\n" "$@"; }',
        declarations, r1,
    ])
    result = _run(script, FAILURE=failure)
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "ARG:" + item for item in (
                "lane", "startup", "--request-refresh", "--custody", "active",
                "--store-root", "store", "--key", "key", "--sealed", "fresh/g6.sealed.json",
                "--expected", "pro/private", "--launch-root", "launch", "--configuration",
                "fresh/config.toml", "--policy", "fresh/startup-policy.json",
                "--lane-dir", "fresh/h8-g6-explicit-lane", "--evidence",
                "fresh/h8-g6-explicit-refresh.json",
            )
        ]
    else:
        assert result.returncode != 0
        assert result.stdout == ""


def test_h8_and_read_preserve_measurement_review_and_no_retry_gates():
    document = _text(DOCUMENT)
    assert "If H7 printed `refresh-measured`, omit H8" in document
    assert "every H7" in document
    assert "ER R1's\nsole Bash block unchanged" in document
    assert "schema-5 evidence" in document and "schema-4 `check_evidence`" in document
    assert "No natural-refresh fallback, second attempt, retry" in document
    assert "T5/no-T6" in document
    assert "No T6 command or retry path" in document
    assert "T3's minted pins reviewed by the owner before T4" in document
    assert "No READ authorization is included in H0" in document
    read = _blocks("Stage 3: fresh READ inputs for separate review")
    names = dict(re.findall(r"^(S|A|ID|KEY)=(\S+)$", read[0], re.M))
    assert names == {
        "S": "/home/m8-service/m8-n5-r6",
        "A": "/var/lib/constructicon-m8-launch/qualification/stage3-read-g6.json",
        "ID": '"n5-stage3g6-$C"', "KEY": "stage3g6",
    }
    assert len(names["S"]) <= len("/home/m8-service/m8-n5-stage3")
    assert '--sealed "$W/g6.sealed.json"' in read[0]
    assert '--qualification "$W/s6a-qualification.json"' in read[0]
    assert 'binding_check "$W/g6.sealed.json" accepted -' in read[1]


def test_transport_pins_c_and_hashes_files_before_noninteractive_execution():
    transport = _blocks("H0: authorization and immutable scripts")[0]
    assert f"C={C}" in transport
    assert '/usr/bin/grep -Fqx "C=$C" n5-g6-h3.sh' in transport
    assert "grep -q $'\\r' n5-g6-common.sh n5-g6-h3.sh" in transport
    assert "sha256sum -- n5-g6-common.sh n5-g6-h3.sh > n5-g6-h3.sha256" in transport
    assert "sha256sum --check --strict n5-g6-h3.sha256 && bash n5-g6-h3.sh" in transport
    assert "StrictHostKeyChecking=yes" in transport and "BatchMode=yes" in transport
    assert "< /dev/null" in transport and "|" not in transport
