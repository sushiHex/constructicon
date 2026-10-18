"""Portable checks of the bounded actual q13 C3/C4 rehearsal inputs."""

import json
import shlex
import signal
import subprocess
import sys
import sysconfig
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
from scripts import m8_procedure_package as package

from tests import qualification_publication as seam
from tests.git_bash import git_bash


@pytest.mark.parametrize("prefix", ["/fixture", "/var/lib/constructicon-m8-launch/fixture"])
def test_actual_packaged_c3_c4_retains_qualification_and_floor_fences(tmp_path, prefix):
    launch = PurePosixPath(prefix) / "isolated-launch"
    session = PurePosixPath("/tmp/synthetic/session")
    out = seam.packaged_steps(tmp_path, launch, session)
    bootstrap = "sys.path[:0] = " + json.dumps([
        str(seam.ROOT / "src"), sysconfig.get_paths()["purelib"]])
    controller_python = ('"${SERVICE[@]}" ' + shlex.quote(sys.executable)
                         + ' -I -S -B -c')
    for name, source, heading, fence in (
        (seam.STEPS[0], "M8-maintenance-lane-output.md", "L1: qualification boundary", 0),
        (seam.STEPS[0], "M8-N4-operator-commands.md", "S6a. Maintenance-lock positive control", 0),
        (seam.STEPS[1], "M8-maintenance-g11-continuation.md",
         "C4: checked floor 10, publish and activate g11", 0),
    ):
        body = (out / (name + ".sh")).read_bytes().decode()
        selected = package.fences(package.section(
            (seam.HANDOFFS / source).read_bytes().decode(), heading))[fence][1]
        selected = selected.replace('sys.path.insert(0, "/opt/constructicon-m8-controller")',
                                    bootstrap).replace(
            '"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c', controller_python)
        assert body.count(selected) == 1
        assert f"R={launch}/operator-stores\n" in body
        assert f"L={launch}\n" in body
        assert f"W={session}\n" in body
        assert '"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c' not in body
        assert 'save_sealed() {' in body and 'binding_check() {' in body
        ran = subprocess.run([git_bash(), "-n", str(out / (name + ".sh"))],
                             stdin=subprocess.DEVNULL, capture_output=True,
                             timeout=10, check=False)
        assert (ran.returncode, ran.stdout, ran.stderr) == (0, b"", b"")
    c3 = (out / (seam.STEPS[0] + ".sh")).read_bytes().decode()
    assert c3.index('test "$S4_SEAL" = "$PRIOR_SEAL"') < c3.index('--hold 90')
    assert 'wait "$H"' in c3 and 'if SECOND=' in c3
    expected = json.loads((out / (seam.STEPS[0] + ".expected.json")).read_bytes())
    assert expected == {"alternatives": [["drift-checked", json.dumps({
        "prepared": True, "out": str(session)}), "lane-boundary-checked"]], "record": None}


@pytest.mark.parametrize("changed", ["stdout", "stderr", "status", "transport"])
def test_whole_accepting_output_rejects_each_changed_public_surface(changed):
    values = {"stdout": b"", "stderr": b"", "status": {"returncode": 0},
              "transport": (0, b"transport-step-checked 0\n", b"")}
    seam.assert_checked(**values, expected=b"")
    values[changed] = {"stdout": b"late\n", "stderr": b"late\n",
                       "status": {"returncode": 1},
                       "transport": (1, b"transport-step-refused\n", b"")}[changed]
    with pytest.raises(AssertionError):
        seam.assert_checked(**values, expected=b"")


@pytest.mark.parametrize("floor", [9, 10])
def test_actual_floor_fence_precedes_even_a_refusing_publication(tmp_path, floor):
    """Execute the authored guard with only user/Python/downstream OS doubles.

    A floor-9 publisher still refuses generation 11. Its attempt must be caught
    affirmatively, so a later generation-law refusal cannot mask a missing fence.
    This is guard-order evidence, not Linux store-custody evidence.
    """
    for name in ("s4-qualification.json", "s6a-qualification.json"):
        (tmp_path / name).write_bytes(json.dumps({"custody": {
            "kind": "maintenance", "generation_floor": floor}}).encode())
    body = package.fences(package.section((
        seam.HANDOFFS / "M8-maintenance-g11-continuation.md").read_bytes().decode(),
        "C4: checked floor 10, publish and activate g11"))[0][1]
    # Native Windows text stdout needs the POSIX newline policy of the actual
    # host. The guard's source and predicates are otherwise unchanged.
    body = body.replace("/usr/bin/python3", shlex.quote(sys.executable)).replace(
        "-c 'import json, sys", "-c 'import json, sys; sys.stdout.reconfigure(newline=\"\\n\"); "
        "sys.stderr.reconfigure(newline=\"\\n\")")
    entered = tmp_path / "entered"
    preamble = "\n".join((
        "set -Eeuo pipefail", "SERVICE=()", "R=/synthetic; K=synthetic; Q=synthetic",
        "W=" + shlex.quote(tmp_path.as_posix()), "W_PRIOR=synthetic",
        "load_final_qualification() { :; }",
        "check_sealed() { :; }", "binding_check() { :; }",
        "save_sealed() { /usr/bin/cat > /dev/null; }",
        'publisher() { printf "%s\\n" "$1" >>' + shlex.quote(entered.as_posix()) + "; "
        + ("return 1; }" if floor == 9 else "return 0; }"),
        "ROOT_STORE=(publisher)",
    ))

    def run_and_check(script):
        if entered.exists():
            entered.unlink()
        path = tmp_path / "guard.sh"
        path.write_bytes((preamble + "\n" + script).encode())
        ran = subprocess.run([git_bash(), str(path)], stdin=subprocess.DEVNULL,
                             capture_output=True, timeout=15, check=False)
        attempts = entered.read_bytes().splitlines() if entered.exists() else []
        assert attempts == ([b"publish", b"activate"] if floor == 10 else [])
        assert ran.returncode == (0 if floor == 10 else 1)
        return ran

    ran = run_and_check(body)
    assert ran.stdout == b""
    if floor == 10:
        assert ran.stderr == b""
    else:
        assert ran.stderr.endswith(b"AssertionError\n")
        guard = ('assert type(custody["generation_floor"]) is int '
                 'and custody["generation_floor"] == 10')
        assert body.count(guard) == 1
        with pytest.raises(AssertionError, match="assert"):
            run_and_check(body.replace(guard, "assert True"))


def test_actual_historical_seal_comparison_stops_before_held_dispatch(tmp_path):
    body = package.fences(package.section((
        seam.HANDOFFS / "M8-maintenance-g11-continuation.md").read_bytes().decode(),
        "C3: fresh q11 and checked historical account continuity"))[1][1]
    entered = tmp_path / "held-entered"
    script = "set -Eeuo pipefail\nS4_SEAL=pro/synthetic; PRIOR_SEAL=prolite/synthetic\n"
    dispatch = '\nprintf held > ' + shlex.quote(entered.as_posix()) + "\n"

    def run_and_check(comparison):
        path = tmp_path / "seal.sh"
        path.write_bytes((script + comparison + dispatch).encode())
        ran = subprocess.run([git_bash(), str(path)], stdin=subprocess.DEVNULL,
                             capture_output=True, timeout=10, check=False)
        assert not entered.exists()
        assert (ran.returncode, ran.stdout, ran.stderr) == (
            1, b"", b"fresh S4 account differs from historical checked g10; stop\n")

    run_and_check(body)
    assert body.count('test "$S4_SEAL" = "$PRIOR_SEAL"') == 1
    with pytest.raises(AssertionError):
        run_and_check(body.replace('test "$S4_SEAL" = "$PRIOR_SEAL"', "true"))


@pytest.mark.parametrize("same_identity", [False, True])
def test_cleanup_signals_only_the_still_observed_cli_identity(
    tmp_path, monkeypatch, same_identity,
):
    inventory = tmp_path / "entered"
    inventory.write_bytes(json.dumps({"pid": 123, "starttime": "100"}).encode() + b"\n")
    killed = []

    def stat_text(path):
        assert path.as_posix() == "/proc/123/stat"
        return "123 (synthetic peer) " + " ".join([
            "Z" if killed else "R", *(["0"] * 18), "100" if same_identity else "200"])

    monkeypatch.setattr(Path, "read_text", stat_text)
    monkeypatch.setattr(seam.os, "kill", lambda *args: killed.append(args), raising=False)
    times = iter(range(0, 1000, 151))
    monkeypatch.setattr(seam.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(seam.time, "sleep", lambda _: None)
    if same_identity:
        with pytest.raises(AssertionError, match="did not complete"):
            seam._drain_observed(inventory)
        assert killed == [(123, signal.SIGTERM)]
    else:
        seam._drain_observed(inventory)
        assert killed == []


def test_t5_timeout_escalates_and_joins_owned_child_before_cli_drain(tmp_path, monkeypatch):
    events = []
    waited = []

    def communicate(*, timeout):
        events.append(("communicate", timeout))
        raise subprocess.TimeoutExpired("synthetic T5", timeout)

    def wait(*, timeout):
        events.append(("wait", timeout))
        waited.append(True)
        if len(waited) == 1:
            raise subprocess.TimeoutExpired("synthetic T5", timeout)
        return 0

    process = SimpleNamespace(pid=123, communicate=communicate, wait=wait,
                              poll=lambda: None)
    monkeypatch.setattr(seam.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(seam.os, "killpg", lambda *args: events.append(("killpg", *args)),
                        raising=False)
    monkeypatch.setattr(seam.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(seam, "_drain_observed", lambda path: events.append(("drain", path)))
    inventory = tmp_path / "entered"
    with pytest.raises(subprocess.TimeoutExpired):
        seam._run_step(tmp_path, tmp_path / "step.sh", tmp_path / "expected.json", inventory)
    assert events == [("communicate", 180), ("communicate", 150),
                      ("killpg", 123, signal.SIGTERM), ("wait", 10),
                      ("killpg", 123, 9), ("wait", 10), ("drain", inventory)]
