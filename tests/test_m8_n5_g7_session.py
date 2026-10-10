"""Credential-free composition checks for the additive g7 deployment package."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_m8_n5_g6_session import SEAL, _run
from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import PYTHON_PROGRAM, _bash

DOCUMENT = HANDOFFS / "M8-N5-g7-session.md"


def _blocks(heading: str) -> list[str]:
    return [block.strip() for block in _fences(_section(_text(DOCUMENT), heading))]


def test_all_blocks_parse_with_frozen_operator_and_refresh_sources():
    operator = _text(HANDOFFS / "M8-N4-operator-commands.md")
    setup = operator.split("## Setup", 1)[1].split("\n### ", 1)[0]
    common = "\n".join([
        *_fences(setup), _blocks("H2-H5: fresh g7 maintenance qualification")[0],
    ])
    refresh, = _fences(_text(HANDOFFS / "M8-N5-explicit-refresh.md"))
    for block in [*_fences(_text(DOCUMENT)), refresh]:
        result = subprocess.run(
            [_bash(), "-n"], input=common + "\n" + block,
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_controller_guard_refuses_unpinned_before_transport_and_accepts_a_pin():
    transport, = _blocks("H0: authorization and immutable scripts")
    assignment = re.search(r"^C=(UNPINNED|[0-9a-f]{40})$", transport, re.M)
    assert assignment is not None
    assert assignment[1] == "d22bff86e8695a7efef04dc3f47c6d4b0847599c"
    guard = re.search(r'\[\[ "\$C" =~ .*?exit 1; \}', transport, re.S)
    assert guard is not None
    for controller, expected in (("UNPINNED", 1), ("a" * 40, 0), ("a" * 39, 1)):
        result = _run('set -Eeuo pipefail; C="$CONTROLLER"\n' + guard[0], CONTROLLER=controller)
        assert result.returncode == expected, result.stderr
    assert transport.index(guard[0]) < transport.index("scp ")
    for literal in (
        '/usr/bin/grep -Fqx "C=$C" n5-g7-h3.sh',
        "grep -q $'\\r' n5-g7-common.sh n5-g7-h3.sh",
        "sha256sum -- n5-g7-common.sh n5-g7-h3.sh > n5-g7-h3.sha256",
        "sha256sum --check --strict n5-g7-h3.sha256 && bash n5-g7-h3.sh",
        "StrictHostKeyChecking=yes", "BatchMode=yes", "< /dev/null",
    ):
        assert literal in transport


@pytest.mark.parametrize(
    ("failure", "seal", "existing"),
    [("none", SEAL, False), ("binding", SEAL, False), ("qualification", SEAL, False),
     ("seal", SEAL, False), ("none", "plus/private", False), ("none", SEAL, True)],
    ids=["accepted", "binding", "qualification", "digest", "plan", "existing"],
)
def test_fresh_g6_capture_requires_checked_evidence_without_overwrite(
    tmp_path: Path, failure: str, seal: str, existing: bool,
):
    prior, capture = _blocks("Before LR's reboot: capture checked g6 continuity")
    assert prior == "W=/home/m8-service/m8-n5-stage2g6"
    home = tmp_path / "private-home"
    home.mkdir()
    private = home / "n5-g7-account.seal"
    if existing:
        private.write_text("preserved\n", encoding="utf-8")
    result = _run("\n".join([
        "set -Eeuo pipefail; umask 077", prior,
        'check() { test "$FAILURE" != "$1"; }',
        'binding_check() { test "$*" = "$W/g6.sealed.json accepted -"; check binding; }',
        'load_final_qualification() { check qualification; Q=q; SEAL="$FAKE_SEAL"; }',
        'check_sealed() { test "$*" = "$W/g6.sealed.json q"; check seal; }', capture,
    ]), HOME=str(home), FAILURE=failure, FAKE_SEAL=seal)
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


@pytest.mark.parametrize(
    ("installed", "state", "different", "accepted"),
    [(False, "tree", 1, True), (True, "tree", 1, False), (False, "absent", 1, False),
     (False, "tree", 0, False), (False, "tree", -1, False)],
    ids=["affirmative-tree-drift", "installed", "absent", "same-tree", "invalid-count"],
)
def test_unchanged_lr9_requires_an_affirmatively_observed_tree_difference(
    tmp_path: Path, installed: bool, state: str, different: int, accepted: bool,
):
    replacement = _section(_text(HANDOFFS / "M8-N4-launch-replacement.md"),
                           "LR9. Controller replacement after login")
    program = PYTHON_PROGRAM.search(replacement)
    assert program is not None
    record = tmp_path / "verify.json"
    record.write_text(json.dumps({
        "installed": installed,
        "observed": {"/opt/constructicon-m8-controller": {
            "state": state, "different": different,
        }},
    }), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", program["body"], str(record)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr
    assert result.stdout == ("lr8-refused-a-tree\n" if accepted else "")


@pytest.mark.parametrize("fresh", [SEAL, "pro/changed"], ids=["same", "changed"])
def test_fresh_s4_must_equal_the_checked_g6_account(fresh: str):
    common, compare = _blocks("H2-H5: fresh g7 maintenance qualification")
    assert common.splitlines() == [
        "W_PRIOR=/home/m8-service/m8-n5-stage2g6", "W=/home/m8-service/m8-n5-stage2g7",
        'PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/n5-g7-account.seal")"',
    ]
    anchor, = _blocks("H1: LR and D2 on one fresh boot")
    assert anchor == 'binding_check "$W/g6.sealed.json" reboot-anchor -'
    result = _run('set -Eeuo pipefail; PRIOR_SEAL="$PRIOR"; S4_SEAL="$FRESH"\n' + compare,
                  PRIOR=SEAL, FRESH=fresh)
    assert result.returncode == (0 if fresh == SEAL else 1), result.stderr


@pytest.mark.parametrize(
    "failure", ["none", "qualification", "publish", "seal", "activate", "accepted", "stale"],
)
def test_g7_activation_uses_fresh_digest_and_affirmatively_retires_g6(failure: str):
    block, = _blocks("H6: publish and activate g7")
    result = _run("\n".join([
        "set -Eeuo pipefail; R=store; K=key; W=fresh; W_PRIOR=prior",
        'check() { test "$FAILURE" != "$1"; }',
        'load_final_qualification() { check qualification; Q=new-q; }',
        'root_store() { local operation="$1"; shift; case "$operation" in',
        'publish) test "$*" = "--store-root store --key key --generation 7 '
        '--qualification-evidence-digest new-q --service m8-service --wait 0" ;;',
        'activate) test "$*" = "--store-root store --key key --generation 7 '
        '--sealed fresh/g7.sealed.json --qualification-evidence-digest new-q '
        '--service m8-service --wait 0" ;;',
        '*) return 2 ;; esac; check "$operation"; echo "$operation"; }',
        'save_sealed() { test "$1" = fresh/g7.sealed.json; /usr/bin/cat; }',
        'check_sealed() { test "$*" = "fresh/g7.sealed.json new-q"; check seal; }',
        'binding_check() { if test "$2" = accepted; then '
        'test "$*" = "fresh/g7.sealed.json accepted -"; check accepted; else '
        'test "$*" = "prior/g6.sealed.json stale-generation fresh/g7.sealed.json"; '
        'check stale; echo g6-stale; fi; }',
        "ROOT_STORE=(root_store)", block,
    ]), FAILURE=failure)
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["publish", "activate", "g6-stale"]
    else:
        assert result.returncode != 0
        assert "g6-stale" not in result.stdout
        if failure in {"qualification", "publish", "seal"}:
            assert "activate" not in result.stdout


@pytest.mark.parametrize(
    ("failure", "refresh"),
    [("none", "unmeasured"), ("none", "measured"),
     *[(failure, "measured") for failure in (
         "qualification", "active-run", "active", "policy", "denial-status",
         "denial", "wrongplan-status", "wrongplan", "stale",
     )]],
)
def test_g7_h7_never_skips_either_control_even_after_measured_refresh(failure: str, refresh: str):
    block, = _blocks("H7: active startup and both refusals on g7")
    result = _run("\n".join([
        "set -Eeuo pipefail",
        "R=store; K=key; L=launch; W=fresh; W_PRIOR=prior; SERVICE=(service); LANE=(lane)",
        'check() { test "$FAILURE" != "$1"; }',
        'load_final_qualification() { check qualification; SEAL=pro/private; }',
        'service() { if test "$1" = /usr/bin/python3; then echo policy; check policy; return; fi',
        'test "$1 $2" = "lane startup"; case "$*" in',
        '*h7-g7-s6b-denial.json*) echo denial-run; '
        'test "$FAILURE" = denial-status && return 0; return 1 ;;',
        '*h7-g7-s6c-plan-refusal.json*) echo wrongplan-run; '
        'test "$FAILURE" = wrongplan-status && return 2; return 1 ;;',
        '*h7-g7-active.json*) echo active-run; check active-run ;;',
        '*) return 3 ;; esac; }',
        'check_evidence() { if test "$1" = refresh; then '
        'test "$REFRESH" = measured; else check "$1"; fi; }',
        'binding_check() { '
        'test "$*" = "prior/g6.sealed.json stale-generation fresh/g7.sealed.json"; '
        'check stale; echo g6-stale; }', block,
    ]), FAILURE=failure, REFRESH=refresh)
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "active-run", "refresh-" + refresh, "policy", "denial-run", "wrongplan-run", "g6-stale",
        ]
    else:
        assert result.returncode != 0
        assert "g6-stale" not in result.stdout
        if failure not in {"wrongplan-status", "wrongplan", "stale"}:
            assert "wrongplan-run" not in result.stdout
    assert block.count('--sealed "$W/g7.sealed.json"') == 3
    assert "--request-refresh" not in block


@pytest.mark.parametrize(
    "failure", ["none", "sudo", "drift", "qualification", "binding", "seal", "launch"],
)
def test_g7_h8_uses_unchanged_er_with_one_new_generation_attempt(failure: str):
    declarations, = _blocks("H8: one explicit-refresh attempt if still unmeasured")
    r1, = _fences(_text(HANDOFFS / "M8-N5-explicit-refresh.md"))
    # Only the platform-owned command is substituted, matching the g6 harness.
    r1 = r1.replace("/usr/local/bin/m8-host-drift", "drift")
    result = _run("\n".join([
        "set -Eeuo pipefail; R=store; K=key; L=launch; W=fresh; SERVICE=(service); LANE=(lane)",
        'check() { test "$FAILURE" != "$1"; }',
        'sudo() { test "$*" = "-n true"; check sudo; }; drift() { check drift; }',
        'load_final_qualification() { check qualification; Q=q; SEAL=pro/private; }',
        'binding_check() { test "$*" = "fresh/g7.sealed.json accepted -"; check binding; }',
        'check_sealed() { test "$*" = "fresh/g7.sealed.json q"; check seal; }',
        'service() { check launch; printf "ARG:%s\\n" "$@"; }', declarations, r1,
    ]), FAILURE=failure)
    if failure == "none":
        assert result.returncode == 0, result.stderr
        arguments = result.stdout.splitlines()
        assert arguments.count("ARG:--request-refresh") == 1
        assert "ARG:fresh/g7.sealed.json" in arguments
        assert "ARG:fresh/h8-g7-explicit-lane" in arguments
        assert "ARG:fresh/h8-g7-explicit-refresh.json" in arguments
        assert "ARG:--expect-denial" not in arguments
    else:
        assert result.returncode != 0
        assert result.stdout == ""


def test_route_preserves_positive_lr9_gate_strict_denial_and_write_pin_pause():
    document = _text(DOCUMENT)
    assert "O=585df33eb196cd4afd10d5c12cb1efb37fd5a6e1" in document
    assert "D=8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3" in document
    assert "not fresh observations of the host" in document
    assert "LR9 only if LR8 affirmatively reports" in document
    assert "`installed` false and the observed `/opt/constructicon-m8-controller` entry" in document
    assert "has `state` equal to `tree` and `different` greater than zero" in document
    assert "an arbitrary LR8 refusal never authorizes replacement" in document
    assert "existing exact four account/read refusal faults" in document
    assert "EOF-only, destination plus" in document
    assert "No natural-refresh fallback, second attempt, retry" in document
    assert "schema-5 evidence" in document and "schema-4 `check_evidence`" in document
    assert "If H7 printed `refresh-measured`, omit H8" in document
    declaration, = _blocks("WRITE: unchanged W0-W6 after the g7 evidence review")
    assert declaration == 'SEALED="$W/g7.sealed.json"'
    assert "copy WS W0 through W6 unchanged, in order" in document
    assert "Pause after W4 for owner review of the exact pins and smoke verdict," in document
    assert "before W5 root installation" in document
    assert "1200-second observation" in document and "not a total cleanup deadline" in document
    assert "No recovery/retry command" in document
    assert "No READ rerun" in document and "no T6" in document
