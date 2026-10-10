"""Execute the WRITE runbook's actual shell/program bytes without vendors."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import _bash, _run_isolated

SESSION = HANDOFFS / "M8-N5-write-session.md"


def _blocks(heading: str) -> list[str]:
    return _fences(_section(_text(SESSION), heading))


def _override() -> str:
    return _blocks("W0. Reviewed installation and authority")[0]


def _program(heading: str) -> str:
    (program,) = re.findall(r"python3 -I -S -B -c '(.*?)'\s", _blocks(heading)[0], re.S)
    return program


def _run(program: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", program, *arguments], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, check=False,
    )


def test_all_actual_blocks_parse_and_steps_are_ordered() -> None:
    text = _text(SESSION)
    headings = ["W0.", "W1.", "W2.", "W3.", "W4.", "W5.", "W6."]
    assert [text.index("## " + heading) for heading in headings] == sorted(
        text.index("## " + heading) for heading in headings
    )
    for block in _fences(text):
        ran = subprocess.run([_bash(), "-n"], input=block, capture_output=True,
                             text=True, timeout=30, check=False)
        assert ran.returncode == 0, ran.stderr


@pytest.mark.parametrize("failure", ["none", "sudo", "drift", "qualification", "binding"])
def test_actual_host_prechecks_stop_at_first_failed_control(failure: str) -> None:
    script = "\n".join([
        "set -Eeuo pipefail; SEALED=reviewed-generation",
        'check() { test "$FAILURE" != "$1"; echo "$1"; }',
        'sudo() { test "$*" = "-n true"; check sudo; }',
        'function /usr/local/bin/m8-host-drift { check drift; }',
        'load_final_qualification() { check qualification; }',
        'binding_check() { test "$*" = "reviewed-generation accepted -"; check binding; }',
        *_blocks("W1. Still the qualified host"), "echo REACHED-END",
    ])
    ran = subprocess.run([_bash(), "-c", script], stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=30, check=False,
                         env={**os.environ, "FAILURE": failure})
    controls = ["sudo", "drift", "qualification", "binding"]
    assert ran.stdout.splitlines() == (
        [*controls, "REACHED-END"] if failure == "none" else controls[:controls.index(failure)]
    )
    assert (ran.returncode == 0) is (failure == "none")


@pytest.mark.parametrize("missing", ["C", "SEALED"])
def test_declarations_require_explicit_controller_and_generation(missing: str) -> None:
    env = {**os.environ, "C": "reviewed", "SEALED": "reviewed-generation"}
    env.pop(missing, None)
    ran = subprocess.run([_bash(), "-c", "PY=(python); W=w; K=k; L=l\n" + _override()],
                         stdin=subprocess.DEVNULL, capture_output=True, text=True,
                         timeout=30, check=False, env=env)
    assert ran.returncode != 0


def test_fixtures_attempt_and_journal_use_fresh_write_names() -> None:
    script = "\n".join([
        "C=reviewed; SEALED=generation; PY=(python); W=qualified; K=key; L=launch",
        _override(), 'printf "%s\\n" "$S" "$F" "$SM" "$A" "$ID" "$KEY" "${HOST[@]}"',
    ])
    ran = subprocess.run([_bash(), "-c", script], stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=30, check=False)
    assert ran.returncode == 0, ran.stderr
    state, fixture, smoke, authorization, identity, key, *host = ran.stdout.splitlines()
    assert fixture != smoke and fixture.startswith(state + "/") and smoke.startswith(state + "/")
    assert "stage3" not in state + fixture + smoke + authorization + identity + key
    assert host[host.index("--state") + 1] == state
    for heading, names in [
        ("W4. Compute and review the WRITE pins",
         ["stage4.attempt", "stage4.sqlite", "$ID", "$KEY"]),
        ("W6. The one WRITE turn and its derived verdict", ["$F", "$A", "--timeout 1200"]),
    ]:
        assert all(name in _blocks(heading)[0] for name in names)


@pytest.mark.parametrize("command", ["prepare-write", "smoke-write", "mint", "run"])
def test_actual_helper_flags_exist(command: str) -> None:
    calls = re.findall(rf'"\$\{{QUAL\[@\]\}}" {command} (.*?)< /dev/null',
                       _text(SESSION), re.S)
    assert calls
    offered = _run_isolated("constructicon.api.qualification", command, "--help")
    assert offered.returncode == 0, offered.stderr
    for flag in re.findall(r"--[a-z][a-z-]+", "\n".join(calls)):
        assert flag in offered.stdout, (command, flag)


def _minted(tmp_path: Path, **changes) -> Path:
    value = {
        "authorization_id": "fixed", "stage": "qualification-write", "max_epoch": 1,
        "attempt_record": "/s/stage4.attempt", "journal": "/s/stage4.sqlite",
        "grants": {"posture": "write", "timeout_s": 300, "allowed_tools": ["contained_python"]},
        "write": {"fixture": {"target_ref": "refs/heads/n5-write"}},
        "source_graph_hash": "graph", "revision": "executor", "operator_binding_digest": "binding",
        "not_after": "expiry", "unprinted_private_text": "DO-NOT-PUBLISH", **changes,
    }
    path = tmp_path / "minted.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_pin_review_prints_only_whitelist_without_private_text(tmp_path: Path) -> None:
    ran = _run(_program("W4. Compute and review the WRITE pins"), str(_minted(tmp_path)),
               "/s/stage4.attempt", "/s/stage4.sqlite")
    assert ran.returncode == 0, ran.stderr
    assert set(json.loads(ran.stdout)) == {
        "authorization_id", "source_graph_hash", "revision", "operator_binding_digest",
        "not_after", "write",
    }
    assert "DO-NOT-PUBLISH" not in ran.stdout
    assert "/s/" not in ran.stdout


@pytest.mark.parametrize("change", [
    {"stage": "qualification-read"}, {"max_epoch": 2}, {"attempt_record": "/other"},
    {"journal": "/other"}, {"grants": {"posture": "write", "timeout_s": 301,
     "allowed_tools": ["contained_python"]}},
    {"grants": {"posture": "write", "timeout_s": 300, "allowed_tools": []}},
    {"write": {"fixture": {"target_ref": "refs/heads/other"}}},
])
def test_pin_review_stops_on_contradictory_authorization(tmp_path: Path, change: dict) -> None:
    ran = _run(_program("W4. Compute and review the WRITE pins"),
               str(_minted(tmp_path, **change)), "/s/stage4.attempt", "/s/stage4.sqlite")
    assert ran.returncode != 0 and ran.stdout == ""


@pytest.mark.parametrize(("verdict", "exit_code", "accepted"), [
    ("passed", "0", True), ("not-qualified", "1", True), ("incomplete", "1", True),
    ("passed", "1", False), ("not-qualified", "0", False), ("other", "1", False),
    ("incomplete", "2", False),
])
def test_verdict_program_requires_known_exit_and_report_consistency(
    tmp_path: Path, verdict: str, exit_code: str, accepted: bool,
) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"verdict": verdict}), encoding="utf-8")
    ran = _run(_program("W6. The one WRITE turn and its derived verdict"), str(path), exit_code)
    assert (ran.returncode == 0) is accepted
    if not accepted:
        assert ran.stdout == ""


@pytest.mark.parametrize("raw", ["", "not-json", "{}"])
def test_verdict_program_never_treats_missing_malformed_evidence_as_pass(
    tmp_path: Path, raw: str,
) -> None:
    path = tmp_path / "report.json"
    path.write_text(raw, encoding="utf-8")
    ran = _run(_program("W6. The one WRITE turn and its derived verdict"), str(path), "0")
    assert ran.returncode


def _shell(tmp_path: Path, *headings: str, **changes: str) -> subprocess.CompletedProcess[str]:
    """Actual blocks; only the service/root transport and qualification CLI are fake."""
    common = "\n".join([
        "set -Eeuo pipefail; umask 077",
        "C=reviewed; SEALED=generation; PY=(python); W=qualified; K=key; L=launch",
        _override(),
        'S="$TEST_STATE"; F="$S/write"; SM="$S/smoke"; A="$TEST_AUTH"',
        "SERVICE=(service); QUAL=(qual)",
        'qual() {',
        '  echo "$1" >> "$TEST_LOG"',
        '  case "$1" in',
        '    prepare-write) test "$2" = --fixture; command /bin/mkdir -m 0700 "$3" ;;',
        '    smoke-write) printf "%s\\n" "$SMOKE_REPORT"; return "$SMOKE_EXIT" ;;',
        '    mint) printf "%s\\n" "$MINTED"; return "$MINT_EXIT" ;;',
        '    run) printf "%s\\n" "$WRITE_REPORT"; return "$RUN_EXIT" ;;',
        '    *) return 97 ;;',
        '  esac',
        '}',
        'service() {',
        '  case "$1" in',
        '    qual) shift; qual "$@" ;;',
        '    /usr/bin/git) test "$2 $3 $4" = "init --bare -q"; command /bin/mkdir "$5" ;;',
        '    /usr/bin/python3) shift; "$TEST_PY" "$@" ;;',
        '    /bin/mkdir|/bin/sh) command "$@" ;;',
        '    *) return 98 ;;',
        '  esac',
        '}',
        'sudo() {',
        '  test "$1" = -n; shift',
        '  case "$1" in',
        '    /usr/bin/test) shift; command /usr/bin/test "$@" ;;',
        '    /usr/bin/install)',
        '      if test "$2" = -d; then command /bin/mkdir -p "${@: -1}";',
        '      else command /bin/cp "${@: -2:1}" "${@: -1}"; fi ;;',
        '    *) return 99 ;;',
        '  esac',
        '}',
    ])
    state = tmp_path / "state"
    minted = json.loads(_minted(tmp_path).read_text(encoding="utf-8"))
    minted.update(attempt_record=(state / "stage4.attempt").as_posix(),
                  journal=(state / "stage4.sqlite").as_posix())
    env = {
        **os.environ, "TEST_STATE": state.as_posix(),
        "TEST_AUTH": (tmp_path / "auth.json").as_posix(),
        "TEST_LOG": (tmp_path / "calls").as_posix(), "TEST_PY": Path(sys.executable).as_posix(),
        "SMOKE_REPORT": '{"verdict":"passed"}', "SMOKE_EXIT": "0",
        "MINTED": json.dumps(minted), "MINT_EXIT": "0",
        "WRITE_REPORT": '{"verdict":"passed"}', "RUN_EXIT": "0", **changes,
    }
    blocks = [block for heading in headings for block in _blocks(heading)]
    return subprocess.run([_bash(), "-c", "\n".join([common, *blocks, 'echo REACHED-END'])],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=30, check=False, env=env)


W2 = "W2. Fresh state and two independent fixtures"
W3 = "W3. Credential-free smoke"
W4 = "W4. Compute and review the WRITE pins"
W5 = "W5. Root installs the reviewed authorization"
W6 = "W6. The one WRITE turn and its derived verdict"


def test_actual_shell_blocks_complete_fresh_two_fixture_session(tmp_path: Path) -> None:
    ran = _shell(tmp_path, W2, W3, W4, W5, W6)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines()[-1] == "REACHED-END"
    assert (tmp_path / "calls").read_text().splitlines() == [
        "prepare-write", "prepare-write", "smoke-write", "mint", "run",
    ]
    assert (tmp_path / "auth.json").read_bytes() == (
        tmp_path / "state" / "minted.json"
    ).read_bytes()
    assert "DO-NOT-PUBLISH" not in ran.stdout


@pytest.mark.parametrize(
    "failure", ["existing-state", "smoke-red", "smoke-exit", "mint-exit", "auth"],
)
def test_actual_shell_blocks_stop_before_the_turn_on_failed_precondition(
    tmp_path: Path, failure: str,
) -> None:
    changes = {}
    if failure == "existing-state":
        (tmp_path / "state").mkdir()
    elif failure == "auth":
        (tmp_path / "auth.json").write_text("preserved")
    elif failure == "smoke-red":
        changes["SMOKE_REPORT"] = '{"verdict":"not-qualified"}'
    elif failure == "smoke-exit":
        changes["SMOKE_EXIT"] = "1"
    elif failure == "mint-exit":
        changes["MINT_EXIT"] = "1"
    ran = _shell(tmp_path, W2, W3, W4, W5, W6, **changes)
    assert ran.returncode != 0
    assert "REACHED-END" not in ran.stdout
    log = tmp_path / "calls"
    assert not log.exists() or "run" not in log.read_text().splitlines()
    if failure == "auth":
        assert (tmp_path / "auth.json").read_text() == "preserved"
