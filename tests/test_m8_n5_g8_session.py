"""Execute the additive g8 blocks with credential-free transport doubles."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests import test_m8_n5_write_session as write_session
from tests.test_m8_n5_g6_session import SEAL, _run
from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import _bash

DOCUMENT = HANDOFFS / "M8-N5-g8-session.md"
C = "59de73bbc9b6f6a9a814b6193f0252e92d1bdd3e"
OLD = "f6cd85a6ed247fdcbb44dc002b8a99fdf18f1324"


def _blocks(heading: str) -> list[str]:
    return [block.strip() for block in _fences(_section(_text(DOCUMENT), heading))]


def test_every_new_block_parses_with_the_actual_common_and_delegated_steps():
    operator = _text(HANDOFFS / "M8-N4-operator-commands.md")
    setup = operator.split("## Setup", 1)[1].split("\n### ", 1)[0]
    common = "\n".join([
        *_fences(setup), _blocks("H2-H5: fresh g8 maintenance evidence")[0],
    ])
    delegated = []
    for document, heading in (
        ("M8-N4-operator-commands.md", "S1. Prepare"),
        ("M8-N4-operator-commands.md", "S4. Qualification"),
        ("M8-N4-operator-commands.md", "S6a. Maintenance-lock positive control"),
        ("M8-N5-host-session.md", "H2. S0 at `C`"),
    ):
        delegated.extend(_fences(_section(_text(HANDOFFS / document), heading)))
    delegated.extend(_fences(_text(HANDOFFS / "M8-N5-explicit-refresh.md")))
    delegated.extend(_fences(_text(HANDOFFS / "M8-N5-write-session.md"))[1:])
    for block in [*_fences(_text(DOCUMENT)), *delegated]:
        result = subprocess.run(
            [_bash(), "-n"], input=common + "\n" + block,
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_actual_controller_guard_stops_before_any_transport():
    transport, = _blocks("H0: authority and immutable source map")
    assert transport.splitlines()[1] == "C=" + C
    guard = re.search(r'\[\[ "\$C" =~ .*?exit 1; \}', transport, re.S)
    assert guard is not None
    for controller, accepted in ((C, True), ("UNPINNED", False), ("a" * 39, False)):
        result = _run('C="$CONTROLLER"\n' + guard[0] + "\necho transport-permitted",
                      CONTROLLER=controller)
        assert (result.returncode == 0) is accepted
        assert result.stdout == ("transport-permitted\n" if accepted else "")
    assert transport.index(guard[0]) < transport.index("scp ")
    assert "StrictHostKeyChecking=yes" in transport and "BatchMode=yes" in transport
    assert "sha256sum --check --strict" in transport and "< /dev/null" in transport


@pytest.mark.parametrize("occupied", [False, True], ids=["fresh", "occupied"])
def test_composed_transport_never_overwrites_a_remote_package(tmp_path: Path, occupied: bool):
    transport, = _blocks("H0: authority and immutable source map")
    mkdir_boundary = ""
    if os.name == "nt":
        # Git Bash's chmod-backed mkdir -m cannot establish Linux permissions
        # here. Substitute directory creation only; no POSIX-mode proof.
        transport = transport.replace("/usr/bin/mkdir", "platform_mkdir")
        mkdir_boundary = (
            'platform_mkdir() { "$TEST_PY" -I -c '
            "'import sys; from pathlib import Path; Path(sys.argv[1]).mkdir()' "
            '"${@: -1}"; }; export -f platform_mkdir'
        )
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    remote.mkdir()
    package = remote / "n5-g8-h3-package"
    if occupied:
        package.mkdir()
        (package / "n5-g8-common.sh").write_bytes(b"historical-common")
    (local / "n5-g8-common.sh").write_text("set -Eeuo pipefail\n", encoding="utf-8")
    (local / "n5-g8-h3.sh").write_text(
        "C=" + C + '\nsource "$HOME/n5-g8-h3-package/n5-g8-common.sh"\necho executed\n',
        encoding="utf-8",
    )
    # Only SSH/SCP are substituted. Actual shell guards, LF/hash checks, files
    # and execution of the transmitted fake step run on private local paths.
    result = _run("\n".join([
        mkdir_boundary,
        'ssh() { HOME="$TEST_REMOTE" /bin/bash -c "${@: -1}"; }',
        'scp() { shift 4; local destination="$TEST_REMOTE/n5-g8-h3-package";',
        '  while test "$#" -gt 1; do /usr/bin/cp -- "$1" "$destination/"; shift; done; }',
        'cd "$TEST_LOCAL"', transport,
    ]), SSH_TARGET="fake-only", TEST_LOCAL=local.as_posix(), TEST_REMOTE=remote.as_posix(),
        TEST_PY=Path(sys.executable).as_posix())
    assert (result.returncode == 0) is not occupied, result.stderr
    if occupied:
        assert result.stdout == ""
        assert (package / "n5-g8-common.sh").read_bytes() == b"historical-common"
        assert not (package / "n5-g8-h3.sh").exists()
    else:
        assert result.stdout.splitlines() == [
            "n5-g8-common.sh: OK", "n5-g8-h3.sh: OK", "executed",
        ]
        for name in ("n5-g8-common.sh", "n5-g8-h3.sh", "n5-g8-h3.sha256"):
            assert (package / name).read_bytes() == (local / name).read_bytes()


@pytest.mark.parametrize(
    ("failure", "seal", "existing"),
    [("none", SEAL, False), ("sudo", SEAL, False), ("drift", SEAL, False),
     ("binding", SEAL, False), ("qualification", SEAL, False), ("seal", SEAL, False),
     ("none", "plus/private", False), ("none", SEAL, True)],
    ids=["accepted", "sudo", "drift", "binding", "qualification", "digest", "plan", "occupied"],
)
def test_composed_preboot_checks_old_g7_before_fresh_capture(
    tmp_path: Path, failure: str, seal: str, existing: bool,
):
    prior, capture = _blocks("Before reboot: checked g7 continuity at the old controller")
    assert prior == "W=/home/m8-service/m8-n5-stage2g7"
    private = tmp_path / "n5-g8-account.seal"
    if existing:
        private.write_text("preserved\n", encoding="utf-8")
    checks, = _fences(_section(_text(HANDOFFS / "M8-N5-host-session.md"), "H2. S0 at `C`"))
    checks = checks.replace("/usr/local/bin/m8-host-drift", "drift")
    result = _run("\n".join([
        "set -Eeuo pipefail; umask 077", "C=" + OLD, prior,
        'check() { test "$FAILURE" != "$1"; }',
        'sudo() { test "$*" = "-n true"; check sudo; }',
        'drift() { check drift; }',
        'binding_check() { test "$C" = "$EXPECTED_OLD"; '
        'test "$*" = "$W/g7.sealed.json accepted -"; check binding; }',
        'load_final_qualification() { check qualification; Q=q; SEAL="$FAKE_SEAL"; }',
        'check_sealed() { test "$*" = "$W/g7.sealed.json q"; check seal; }',
        checks, capture, "echo captured",
    ]), HOME=tmp_path.as_posix(), FAILURE=failure, FAKE_SEAL=seal, EXPECTED_OLD=OLD)
    accepted = failure == "none" and seal == SEAL and not existing
    assert (result.returncode == 0) is accepted, result.stderr
    assert result.stdout == ("captured\n" if accepted else "")
    if accepted:
        assert private.read_text(encoding="utf-8") == SEAL + "\n"
    elif existing:
        assert private.read_text(encoding="utf-8") == "preserved\n"
    else:
        assert not private.exists()
    anchor, = _blocks("H1: normal LR and D2 on one fresh boot")
    assert anchor == 'binding_check "$W/g7.sealed.json" reboot-anchor -'


@pytest.mark.parametrize("fresh", [SEAL, "pro/changed"], ids=["same", "changed"])
def test_new_s4_account_must_equal_checked_old_g7(fresh: str):
    common, compare = _blocks("H2-H5: fresh g8 maintenance evidence")
    assert common.splitlines() == [
        "W_PRIOR=/home/m8-service/m8-n5-stage2g7",
        "W=/home/m8-service/m8-n5-stage2g8",
        'PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/n5-g8-account.seal")"',
    ]
    result = _run('set -Eeuo pipefail; PRIOR_SEAL="$PRIOR"; S4_SEAL="$FRESH"\n'
                  + compare + "\necho account-checked", PRIOR=SEAL, FRESH=fresh)
    assert result.returncode == (0 if fresh == SEAL else 1)
    assert result.stdout == ("account-checked\n" if fresh == SEAL else "")


@pytest.mark.parametrize(
    ("record", "floor", "kind", "failure"),
    [("s4", 7, "maintenance", "none"),
     *[(record, floor, "maintenance", "none")
       for record in ("s4", "s6a") for floor in (True, 7.0, 6, 8, None)],
     ("s4", 7, "active", "none"),
     *[("s4", 7, "maintenance", failure)
       for failure in ("qualification", "publish", "seal", "activate", "accepted", "stale")]],
    ids=["accept", *[f"{record}-{floor}" for record in ("s4", "s6a")
                      for floor in ("bool", "float", "low", "high", "missing")],
         "wrong-custody", "qualification", "publish", "seal", "activate", "accepted", "stale"],
)
def test_h6_requires_both_checked_historical_floors_before_one_publication(
    tmp_path: Path, record: str, floor: object, kind: str, failure: str,
):
    for name in ("s4", "s6a"):
        custody = {"kind": kind if name == record else "maintenance",
                   "generation_floor": floor if name == record else 7}
        if name == record and floor is None:
            custody.pop("generation_floor")
        (tmp_path / (name + "-qualification.json")).write_text(
            json.dumps({"custody": custody}), encoding="utf-8",
        )
    block, = _blocks("H6: checked maintenance floor 7, publish and activate g8")
    result = _run("\n".join([
        'set -Eeuo pipefail; R=store; K=key; W="$TEST_WORLD"; W_PRIOR=prior',
        'check() { test "$FAILURE" != "$1"; }',
        'load_final_qualification() { check qualification; Q=new-q; }',
        'service() { test "$1" = /usr/bin/python3; shift; "$TEST_PY" "$@"; }',
        'root_store() { local operation="$1"; shift; case "$operation" in',
        'publish) test "$*" = "--store-root store --key key --generation 8 '
        '--qualification-evidence-digest new-q --service m8-service --wait 0" ;;',
        'activate) test "$*" = "--store-root store --key key --generation 8 '
        '--sealed $W/g8.sealed.json --qualification-evidence-digest new-q '
        '--service m8-service --wait 0" ;;',
        '*) return 2 ;; esac; check "$operation"; echo "$operation" >> "$TEST_LOG"; '
        'echo "$operation"; }',
        'save_sealed() { test "$1" = "$W/g8.sealed.json"; /usr/bin/cat; }',
        'check_sealed() { test "$*" = "$W/g8.sealed.json new-q"; check seal; }',
        'binding_check() { if test "$2" = accepted; then '
        'test "$*" = "$W/g8.sealed.json accepted -"; check accepted; else '
        'test "$*" = "prior/g7.sealed.json stale-generation $W/g8.sealed.json"; '
        'check stale; echo g7-stale; fi; }',
        "ROOT_STORE=(root_store); SERVICE=(service)", block, "echo completed",
    ]), FAILURE=failure, TEST_WORLD=tmp_path.as_posix(), TEST_PY=sys.executable,
        TEST_LOG=(tmp_path / "calls").as_posix())
    valid_floor = type(floor) is int and floor == 7 and kind == "maintenance"
    accepted = valid_floor and failure == "none"
    assert (result.returncode == 0) is accepted, result.stderr
    log = tmp_path / "calls"
    calls = log.read_text().splitlines() if log.exists() else []
    assert calls.count("publish") <= 1 and calls.count("activate") <= 1
    if not valid_floor or failure in {"qualification", "publish"}:
        assert calls == []
    if failure == "seal":
        assert calls == ["publish"]
    if accepted:
        assert calls == ["publish", "activate"]
        assert result.stdout.splitlines() == ["publish", "activate", "g7-stale", "completed"]
    else:
        assert "completed" not in result.stdout and "g7-stale" not in result.stdout


@pytest.mark.parametrize(
    ("failure", "refresh"),
    [("none", "unmeasured"), ("none", "measured"),
     *[(failure, "measured") for failure in (
         "qualification", "active-run", "active", "policy", "denial-status",
         "denial", "wrongplan-status", "wrongplan", "stale",
     )]],
)
def test_h7_runs_every_control_even_when_refresh_is_measured(failure: str, refresh: str):
    block, = _blocks("H7: every active and refusal control on g8")
    result = _run("\n".join([
        "set -Eeuo pipefail",
        "R=store; K=key; L=launch; W=fresh; W_PRIOR=prior; SERVICE=(service); LANE=(lane)",
        'check() { test "$FAILURE" != "$1"; }',
        'load_final_qualification() { check qualification; SEAL=pro/private; }',
        'service() { if test "$1" = /usr/bin/python3; then echo policy; check policy; return; fi',
        'test "$1 $2" = "lane startup"; case "$*" in',
        '*h7-g8-s6b-denial.json*) echo denial-run; '
        'test "$FAILURE" = denial-status && return 0; return 1 ;;',
        '*h7-g8-s6c-plan-refusal.json*) echo wrongplan-run; '
        'test "$FAILURE" = wrongplan-status && return 2; return 1 ;;',
        '*h7-g8-active.json*) echo active-run; check active-run ;;',
        '*) return 3 ;; esac; }',
        'check_evidence() { if test "$1" = refresh; then '
        'test "$REFRESH" = measured; else check "$1"; fi; }',
        'binding_check() { '
        'test "$*" = "prior/g7.sealed.json stale-generation fresh/g8.sealed.json"; '
        'check stale; echo g7-stale; }', block,
    ]), FAILURE=failure, REFRESH=refresh)
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "active-run", "refresh-" + refresh, "policy", "denial-run", "wrongplan-run", "g7-stale",
        ]
    else:
        assert result.returncode != 0
        assert "g7-stale" not in result.stdout
        if failure not in {"wrongplan-status", "wrongplan", "stale"}:
            assert "wrongplan-run" not in result.stdout
    assert block.count('--sealed "$W/g8.sealed.json"') == 3
    assert "--request-refresh" not in block


@pytest.mark.parametrize(
    "failure", ["none", "sudo", "drift", "qualification", "binding", "seal", "launch"],
)
def test_conditional_h8_composes_exact_er_with_one_fresh_attempt(failure: str):
    declarations, = _blocks("H8: at most one conditional explicit refresh")
    r1, = _fences(_text(HANDOFFS / "M8-N5-explicit-refresh.md"))
    r1 = r1.replace("/usr/local/bin/m8-host-drift", "drift")
    result = _run("\n".join([
        "set -Eeuo pipefail; R=store; K=key; L=launch; W=fresh; SERVICE=(service); LANE=(lane)",
        'check() { test "$FAILURE" != "$1"; }',
        'sudo() { test "$*" = "-n true"; check sudo; }; drift() { check drift; }',
        'load_final_qualification() { check qualification; Q=q; SEAL=pro/private; }',
        'binding_check() { test "$*" = "fresh/g8.sealed.json accepted -"; check binding; }',
        'check_sealed() { test "$*" = "fresh/g8.sealed.json q"; check seal; }',
        'service() { check launch; printf "ARG:%s\\n" "$@"; }', declarations, r1,
    ]), FAILURE=failure)
    if failure == "none":
        assert result.returncode == 0, result.stderr
        arguments = result.stdout.splitlines()
        assert arguments.count("ARG:--request-refresh") == 1
        assert "ARG:fresh/g8.sealed.json" in arguments
        assert "ARG:fresh/h8-g8-explicit-lane" in arguments
        assert "ARG:fresh/h8-g8-explicit-refresh.json" in arguments
    else:
        assert result.returncode != 0 and result.stdout == ""


def test_complete_w0_override_has_fresh_names_and_qualified_g8():
    declarations, = _blocks("WRITE: fresh W0 names, exact W1-W6 and owner pin pause")
    result = _run("\n".join([
        "C=" + C, "PY=(python); W=qualified; K=store-key", declarations,
        'printf "%s\\n" "$S" "$F" "$SM" "$A" "$ID" "$KEY" "${HOST[@]}"',
    ]))
    assert result.returncode == 0, result.stderr
    state, fixture, smoke, authority, identity, key, *host = result.stdout.splitlines()
    assert state == "/home/m8-service/m8-n5-w8"
    assert fixture == state + "/write" and smoke == state + "/smoke"
    assert authority.endswith("/qualification/stage4-write-g8.json")
    assert identity == "n5-stage4g8-" + C and key == "stage4g8"
    assert host[host.index("--sealed") + 1] == "qualified/g8.sealed.json"
    assert host[host.index("--state") + 1] == state


@pytest.mark.parametrize("occupied", ["state", "authorization"])
def test_exact_ws_blocks_refuse_occupied_new_names_without_touching_old_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, occupied: str,
):
    declarations, = _blocks("WRITE: fresh W0 names, exact W1-W6 and owner pin pause")
    monkeypatch.setattr(write_session, "_override", lambda: declarations)
    old = tmp_path / "m8-n5-w"
    old.mkdir()
    for name in ("stage4.attempt", "stage4.sqlite", "stage4.sqlite-wal", "diagnostic-copy"):
        (old / name).write_bytes(("preserved-" + name).encode())
    before = {path.name: path.read_bytes() for path in old.iterdir()}
    if occupied == "state":
        (tmp_path / "state").mkdir()
        (tmp_path / "state" / "spent").write_bytes(b"preserved")
        result = write_session._shell(tmp_path, "W2. Fresh state and two independent fixtures")
        assert (tmp_path / "state" / "spent").read_bytes() == b"preserved"
    else:
        authorization = tmp_path / "auth.json"
        authorization.write_bytes(b"preserved-installed-authorization")
        result = write_session._shell(tmp_path, "W5. Root installs the reviewed authorization")
        assert authorization.read_bytes() == b"preserved-installed-authorization"
    assert result.returncode != 0
    assert {path.name: path.read_bytes() for path in old.iterdir()} == before
    log = tmp_path / "calls"
    assert not log.exists() or "run" not in log.read_text().splitlines()


def test_fresh_g8_declarations_compose_the_exact_ws_accepting_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    declarations, = _blocks("WRITE: fresh W0 names, exact W1-W6 and owner pin pause")
    monkeypatch.setattr(write_session, "_override", lambda: declarations)
    result = write_session._shell(tmp_path, *[
        "W2. Fresh state and two independent fixtures", "W3. Credential-free smoke",
        "W4. Compute and review the WRITE pins", "W5. Root installs the reviewed authorization",
        "W6. The one WRITE turn and its derived verdict",
    ])
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "REACHED-END"
    assert (tmp_path / "calls").read_text().splitlines() == [
        "prepare-write", "prepare-write", "smoke-write", "mint", "run",
    ]
    assert (tmp_path / "auth.json").read_bytes() == (tmp_path / "state/minted.json").read_bytes()
    assert "DO-NOT-PUBLISH" not in result.stdout


def test_normal_route_preserves_old_archives_pin_pause_and_nonpassing_stop():
    document = _text(DOCUMENT)
    assert "normal fresh LR route" in document and "Do not replay" in document
    assert "O=" + OLD in document
    assert "R6 baseline creation or drift" in document
    assert "historical maintenance custody" in document
    assert "not a claim about the current live floor after" in document
    assert "If H7 printed `refresh-measured`, omit H8" in document
    assert "No second attempt" in document
    assert "before WRITE" in document and "Pause after W4 for owner review" in document
    assert "Copy WS W1-W6 at `C` unchanged" in document
    assert "strict report schema 2; smoke stays at schema 1" in document
    assert "No automatic retry, checker recovery, redispatch, refund" in document
    assert "No READ rerun/T6" in document
