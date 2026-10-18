"""One additive q13 composition, with synthetic values, never host evidence.

Structural assertions use the production packager and frozen public sources.
The preservation producer runs through the original T5 over disposable files.
Only interpreter/path and unavailable Windows file-flag boundaries are replaced;
native POSIX runs retain the real flags. There is no platform-based test skip.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package

from constructicon.core.control import command_id_for, run_id_for_command
from tests import test_m8_lane_output as lane_output
from tests.test_m8_lane_output import (
    DOUBLE,
    PURELIB,
    SOURCE,
    _composable,
    _evidence_program,
    _record,
    seal,
)
from tests.test_m8_maintenance_q12_rehearsal import OVERRIDE, _with_override
from tests.test_m8_operator_commands import PYTHON_PROGRAM, _bash

_q13_operator_world = lane_output._operator_world

HANDOFFS = Path(__file__).parents[1] / "docs/plans/handoffs"
DOCUMENT = HANDOFFS / "M8-maintenance-q13-continuation.md"
Q12 = HANDOFFS / "M8-maintenance-q12-continuation.md"
GUARD = HANDOFFS / "M8-private-output-guard.md"
RUN = "run-4c5df557e3d2f6a0f44030084115f865"
SYNTHETIC = b"Synthetic affirmative drift verdict: all nine checked facts agree.\n"
PRIVATE_VALUES = {"DRIFT_STDOUT_HEX": SYNTHETIC.hex(), "DRIFT_TOOL_SHA256": "cd" * 32}
VALUES = {**PRIVATE_VALUES, "RUN_ID": RUN, "PREVIEW_SHA256": "ab" * 32,
          "EXPECTED_BOOT": "934acecb-9042-4e02-845e-050a4d071265"}
DEFERRED = {"q13-c9-authority", "q13-c10-application", "q13-c11-diagnosis"}
GUARDED = {"q13-c1-controller": 1, "q13-c2-d2": 1, "q13-c3-qualification": 1,
           "q13-c5-h7": 1, "q13-c7-prepare": 1, "q13-c8-preflight": 1,
           "q13-c9-authority": 1, "q13-c10-application": 1, "q13-c11-diagnosis": 2}


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _fences(path: Path, heading: str, language: str = "bash") -> list[str]:
    return [body for kind, body in package.fences(package.section(_text(path), heading))
            if kind == language]


def _renamed(text: str) -> str:
    return (text.replace("q12", "q13").replace("m8-m4", "m8-m5")
            .replace("m8-maint-a4", "m8-maint-a5").replace("maintenance-4", "maintenance-5")
            .replace("application-4", "application-5").replace("diagnosis-4", "diagnosis-5")
            .replace("run-5c7172babff67a7d53412b6c598bc34b", RUN))


def _steps(**kwargs) -> dict[str, package.Step]:
    return {step.name: step for step in package.assemble(DOCUMENT, **kwargs)}


def _manifest(out: Path) -> list[str]:
    names = []
    for line in (out / "MANIFEST.sha256").read_bytes().decode().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest
        names.append(name)
    return names


def test_all_nineteen_steps_are_named_in_order_and_evidence_is_not_overclaimed():
    steps = package.assemble(DOCUMENT, template=True)
    table = re.findall(r"^\| `(q13-[a-z0-9-]+)` \|", _text(DOCUMENT), re.M)
    assert len(steps) == 19 and table == [step.name for step in steps]
    assert {step.name for step in steps if "PREVIEW_SHA256=UNREVIEWED" in step.text
            or "EXPECTED_BOOT=UNREVIEWED" in step.text} == DEFERRED
    assert "Existing q12 composed rehearsals cover only physical preflight and" in _text(DOCUMENT)
    assert "No VM, vendor, model or private host" in _text(DOCUMENT)
    assert "complete synthetic-value test builds are not" in _text(DOCUMENT)


def test_unknown_private_inputs_cannot_build_an_operator_package(tmp_path):
    with pytest.raises(package.Refused, match="unreviewed placeholder remains"):
        package.build(DOCUMENT, tmp_path / "unknown")
    assert not (tmp_path / "unknown").exists()


def test_private_pair_builds_sixteen_and_only_runtime_steps_wait(tmp_path):
    first = tmp_path / "first"
    package.build(DOCUMENT, first, values=PRIVATE_VALUES)
    steps = package.assemble(DOCUMENT, values=PRIVATE_VALUES)
    assert len(steps) == 19 and {s.name for s in steps if s.waiting} == DEFERRED
    names = [s.name for s in steps if not s.waiting]
    assert len(names) == 16
    assert _manifest(first) == [name + suffix for name in names
                                for suffix in (".sh", ".expected.json")]
    for name in DEFERRED:
        assert not (first / f"{name}.sh").exists()
        assert not (first / f"{name}.expected.json").exists()


def test_full_synthetic_build_is_reproducible_and_parses_all_nineteen(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    assert package.build(DOCUMENT, first, values=VALUES) == package.build(
        DOCUMENT, second, values=VALUES)
    assert len(_manifest(first)) == 38
    for step in package.assemble(DOCUMENT, values=VALUES):
        script = first / f"{step.name}.sh"
        raw = script.read_bytes()
        assert raw == step.text.encode() and b"UNREVIEWED" not in raw
        assert (first / f"{step.name}.expected.json").read_bytes() == step.expected().encode()
        ran = subprocess.run([_bash(), "-n", script.as_posix()], stdin=subprocess.DEVNULL,
                             capture_output=True, timeout=30, check=False)
        assert (ran.returncode, ran.stdout, ran.stderr) == (0, b"", b""), step.name
        assert not any(public in step.text for public in ("git push", " gh ", "curl -X",
                                                          "--data", "api.github.com"))


def test_only_fresh_names_change_in_pins_declarations_and_lifecycle_wrappers():
    for heading, language in (("Q2: pins", "bash"), ("Q3: declarations", "bash"),
                              ("Q1: workstation sequence", "python"),
                              ("Q1b: exact workstation commands", "bash")):
        assert _fences(DOCUMENT, heading, language) == [
            _renamed(body) for body in _fences(Q12, heading, language)]
    assert str(run_id_for_command(command_id_for(
        "operator:maintenance-5", "runs_start", "maintenance-5"))) == RUN
    pin, = _fences(DOCUMENT, "Q2: pins")
    for name in ("C", "O", "BASE"):
        assert f"{name}=5793ef98ef5597c9ee9811a0d1f031554eb7f514\n" in pin
    assert "D=8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3\n" in pin


def test_split_wrappers_preserve_all_non_drift_bytes_except_fresh_names():
    old = _fences(Q12, "Q5: new and renamed VM fences")
    new = _fences(DOCUMENT, "Q5: new and renamed VM fences")
    assert len(old) == 6 and len(new) == 7
    assert new[:3] == [_renamed(old[0]), old[1], old[2]]
    assert new[3] == old[3].removeprefix(
        "sudo -n true < /dev/null\n/usr/local/bin/m8-host-drift < /dev/null\n")
    assert new[4] == _renamed(old[4])
    assert new[5] + "/usr/local/bin/m8-host-drift < /dev/null\n" + new[6] == _renamed(old[5])


def test_sources_lane_blocks_record_checker_and_transport_stay_exact():
    spec = package.composition(_text(DOCUMENT))
    assert spec["sources"]["q12"] == {"path": Q12.name, "sha256": hashlib.sha256(
        Q12.read_bytes()).hexdigest()}
    assert spec["sources"]["guard"] == {"path": GUARD.name, "sha256": hashlib.sha256(
        GUARD.read_bytes()).hexdigest()}
    old = package.composition(_text(Q12))
    for name, source in old["sources"].items():
        assert spec["sources"][name] == source
    def lane(composition):
        return [p for s in composition["steps"] for p in s["parts"]
                if p.get("source") == "lane"]

    assert lane(spec) == lane(old)
    record = [p for s in spec["steps"] for p in s["parts"]
              if p.get("heading") == "Q4: private host records"]
    assert len(record) == 5 and all(p["source"] == "q12" and p["fences"] == [0] for p in record)
    assert _fences(Q12, "Q6: transport T5", "python")


def test_every_drift_site_is_exact_g1_and_has_one_private_pair_and_unique_capture():
    guard, = _fences(GUARD, "G1: private drift boundary")
    assert hashlib.sha256(guard.encode()).hexdigest() in package.DRIFT_BLOCKS
    steps = _steps(template=True)
    assert {name: step.text.count(guard) for name, step in steps.items()
            if guard in step.text} == GUARDED
    assert sum(GUARDED.values()) == 10
    for name, step in steps.items():
        # Any call left over after removing the exact guard is forbidden.
        assert "m8-host-drift" not in step.text.replace(guard, ""), name
        if name not in GUARDED:
            continue
        for key in PRIVATE_VALUES:
            declaration = f"{key}=UNREVIEWED\n"
            assert step.text.count(declaration) == 1
            assert step.text.index(declaration) < step.text.index(guard)
        captures = re.findall(r'^DRIFT_CAPTURE="(.*?)"$', step.text, re.M)
        assert len(captures) == len(set(captures)) == GUARDED[name]
        suffix = name.removeprefix("q13-")
        assert f'DRIFT_RECORDS="$HOME/maintenance-q13-drift-{suffix}"' in step.text
        assert 'mkdir -m 0700 -- "$DRIFT_RECORDS" || exit "$?"' in step.text


def test_h7_and_diagnosis_keep_guards_in_their_required_control_flow():
    guard, = _fences(GUARD, "G1: private drift boundary")
    h7 = _steps(template=True)["q13-c5-h7"]
    assert h7.alternatives == (
        ("lane-boundary-checked", "refresh-measured", "lane-boundary-checked",
         "lane-boundary-checked"),
        ("lane-boundary-checked", "refresh-unmeasured", "lane-boundary-checked",
         "lane-boundary-checked", "drift-checked", "refresh-measured"))
    l2, = _fences(HANDOFFS / "M8-maintenance-lane-output.md", "L2: H7 controls")
    l3, = _fences(HANDOFFS / "M8-maintenance-lane-output.md", "L3: explicit refresh")
    assert h7.text.index(l2) < h7.text.index('if test "$ACTIVE_REFRESH" = unmeasured; then')
    assert h7.text.index('if test "$ACTIVE_REFRESH" = unmeasured; then') < h7.text.index(guard)
    assert h7.text.index(guard) < h7.text.index(l3) < h7.text.rindex("fi\n")
    diag = _steps(template=True)["q13-c11-diagnosis"].text
    assert diag.index(guard) < diag.index('printf \'%s\\n\' diagnosis-quiescence-checked')
    assert diag.index('printf \'%s\\n\' diagnosis-quiescence-checked') < diag.rindex(guard)
    assert diag.rindex(guard) < diag.index("q13-diagnostic-capture")


@pytest.mark.parametrize("damage", (
    "none", "occupied", "missing", "linked", "oversized", "warning"))
def test_actual_packaged_preservation_through_t5_with_disposable_files(tmp_path, damage):
    """Synthetic prior files, real producer/saver/T5; no claim about host D2.

    Windows lacks the two Unix open flags. Only those flags and interpreter/LF
    plumbing are substituted there; file identity, nlink, exclusive creation,
    fsync, source retention and byte comparison still run. POSIX uses real flags.
    """
    source, archive = tmp_path / "m8-host", tmp_path / "maintenance-q13-d2-prior"
    source.mkdir()
    names = ("profiles-verify", "verify.json", "qualification.json")
    for name in names:
        (source / name).write_bytes(f"synthetic prior record: {name}\n".encode())
    if damage == "occupied":
        archive.mkdir()
        (archive / "retained").write_bytes(b"never replace")
    elif damage == "missing":
        (source / names[0]).unlink()
    elif damage == "linked":
        os.link(source / names[0], tmp_path / "alias")
    elif damage == "oversized":
        (source / names[0]).write_bytes(b"x" * 1048577)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    out = tmp_path / "package"
    package.build(DOCUMENT, out, values=VALUES)
    script = (out / "q13-c2-preserve.sh").read_bytes().decode()
    script = script.replace('"$HOME/m8-host"', shlex.quote(source.as_posix()))
    script = script.replace('"$HOME/maintenance-q13-d2-prior"', shlex.quote(archive.as_posix()))
    script = script.replace("/usr/bin/python3", shlex.quote(Path(sys.executable).as_posix()))
    if os.name == "nt":
        script = script.replace("os.O_NOFOLLOW", "0").replace("os.O_NONBLOCK", "0")
        script = script.replace("from pathlib import Path\n",
                                'from pathlib import Path\nsys.stdout.reconfigure(newline="\\n")\n')
    if damage == "warning":
        script += "printf 'synthetic preservation warning\\n' >&2\n"
    runnable = tmp_path / "preserve.sh"
    runnable.write_bytes(script.encode())
    t5 = tmp_path / "transport.py"
    transport, = _fences(Q12, "Q6: transport T5", "python")
    t5.write_bytes(transport.encode())
    prefix = tmp_path / "step"
    ran = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(t5), str(prefix),
         str(out / "q13-c2-preserve.expected.json"), "--", _bash(), runnable.as_posix()],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)
    status = json.loads((tmp_path / "step.status.json").read_bytes())
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    assert ran.stderr == b""
    if damage == "none":
        assert (ran.returncode, ran.stdout) == (0, b"transport-step-checked 0\n")
        assert status == {"returncode": 0}
        assert (tmp_path / "step.stdout").read_bytes() == b"g11-boot-d2-records-preserved\n"
        assert (tmp_path / "step.stderr").read_bytes() == b""
        assert {p.name: p.read_bytes() for p in archive.iterdir()} == before
    else:
        assert (ran.returncode, ran.stdout) == (1, b"transport-step-refused\n")
        if damage == "warning":
            assert status == {"returncode": 0}
            assert (tmp_path / "step.stderr").read_bytes() == b"synthetic preservation warning\n"
        else:
            assert status["returncode"] != 0
            assert (tmp_path / "step.stdout").read_bytes() == b""
        if damage == "occupied":
            assert {p.name: p.read_bytes() for p in archive.iterdir()} == {
                "retained": b"never replace"}


@pytest.mark.parametrize("case", (
    "measured", "h8", "drift-mismatch", "h8-unmeasured", "accepted-denial"))
async def test_actual_h7_packaged_step_keeps_g1_inside_conditional_and_all_controls(
    _q13_operator_world, tmp_path, case,
):
    """Real L0/L2/L3, original T5, scripted lane records and synthetic G1 tool.

    The q12 fixture's custody/binding substitutes are explicit and unchanged;
    this is an output/control-flow join, not the real qualification/store seam.
    A plausible different drift sentence uses its own matching tool digest, so
    refusal exercises output comparison, not a deliberately incorrect hash.
    """
    directory, _ = _q13_operator_world
    home = tmp_path / "home"
    home.mkdir()
    (home / "maintenance-g9-account.seal").write_bytes(b"pro/seal\n")
    tool = directory / "synthetic-drift.py"
    verdict = SYNTHETIC if case != "drift-mismatch" else (
        b"Synthetic affirmative drift verdict: eight checked facts agree.\n")
    tool.write_bytes(("import sys\nfrom pathlib import Path\n"
                      "Path(__file__).with_suffix(\".invoked\").write_bytes(b\"invoked\")\n"
                      f"sys.stdout.buffer.write({verdict!r})\n").encode())
    values = {**VALUES, "DRIFT_TOOL_SHA256": hashlib.sha256(tool.read_bytes()).hexdigest()}
    out = directory / "package"
    package.build(DOCUMENT, out, values=values)
    script = (out / "q13-c5-h7.sh").read_bytes().decode()
    script = script.replace("/home/m8-service/m8-maint-q13", "$TEST_W")
    script = script.replace("/home/m8-service/m8-maint-q10", "$TEST_W_PRIOR")
    script = _with_override(script, OVERRIDE)
    script = script.replace('Path("/usr/local/bin/m8-host-drift")',
                            f"Path({tool.as_posix()!r})")
    script = script.replace('subprocess.Popen([str(tool)]',
                            'subprocess.Popen([sys.executable, str(tool)]')
    # C-program print plumbing is the host Python boundary, not a relaxed T5.
    if os.name == "nt":
        for program in PYTHON_PROGRAM.findall(script):
            script = script.replace(program,
                                    'import sys\nsys.stdout.reconfigure(newline="\\n")\n' + program)
    script = _composable(script)
    runnable = directory / "h7.sh"
    runnable.write_bytes(script.encode())
    records = directory / "records"
    records.mkdir()
    cases = {"h7-g11-active.json": "active-measured" if case == "measured" else "active",
             "h7-g11-s6b-denial.json": "active" if case == "accepted-denial" else "denial-derived",
             "h7-g11-s6c-plan-refusal.json": "wrongplan",
             "h8-g11-explicit-refresh.json": (
                 "unmeasured" if case == "h8-unmeasured" else "measured")}
    for name, record_case in cases.items():
        (records / name).write_bytes(json.dumps(
            await _record(record_case, directory / f"run-{name}")).encode())
    (directory / "g11.sealed.json").write_bytes(b"{}")
    checker = directory / "check-evidence.py"
    checker.write_bytes(_evidence_program().encode())
    entry = ('import sys; sys.stdout.reconfigure(newline="\\n"); '
             'sys.path[:0] = sys.argv[1:3]; del sys.argv[1:3]; exec(sys.stdin.read())')
    transport, = _fences(Q12, "Q6: transport T5", "python")
    t5 = directory / "transport.py"
    t5.write_bytes(transport.encode())
    ran = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(t5), str(directory / "step"),
         str(out / "q13-c5-h7.expected.json"), "--", _bash(), runnable.as_posix()],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=180, check=False,
        env={**os.environ, "HOME": home.as_posix(), "TEST_PY": Path(sys.executable).as_posix(),
             "TEST_DOUBLE": DOUBLE.as_posix(), "TEST_SOURCE": SOURCE, "TEST_PURELIB": PURELIB,
             "TEST_RECORDS": records.as_posix(), "TEST_W": directory.as_posix(),
             "TEST_W_PRIOR": (directory / "q10").as_posix(), "TEST_SEAL": seal("pro"),
             "TEST_ENTRY": entry, "TEST_CHECKER": checker.as_posix()})
    assert ran.stderr == b""
    child_status = json.loads((directory / "step.status.json").read_bytes())
    captured = (directory / "step.stdout").read_bytes()
    if case in {"measured", "h8"}:
        alternative = 0 if case == "measured" else 1
        assert (ran.returncode, ran.stdout) == (
            0, f"transport-step-checked {alternative}\n".encode())
        assert child_status == {"returncode": 0}
        assert (directory / "step.stderr").read_bytes() == b""
        expected = _steps(values=values)["q13-c5-h7"].alternatives[alternative]
        assert captured == "".join(line + "\n" for line in expected).encode()
    else:
        assert (ran.returncode, ran.stdout) == (1, b"transport-step-refused\n")
        if case == "h8-unmeasured":
            # A normal unmeasured verdict is not an allowed q13 alternative.
            # T5, not a fabricated command failure, enforces that distinction.
            assert child_status == {"returncode": 0}
            assert captured.endswith(b"drift-checked\nrefresh-unmeasured\n")
        else:
            assert child_status["returncode"] != 0
    drift = home / "maintenance-q13-drift-c5-h7" / "conditional-h8"
    if case == "measured" or case == "accepted-denial":
        assert not drift.exists() and not tool.with_suffix(".invoked").exists()
    else:
        assert json.loads((drift / "status.json").read_bytes()) == {
            "launch_requested": True, "returncode": 0}
        assert (drift / "stdout").read_bytes() == verdict
        assert (drift / "stderr").read_bytes() == b""
    if case == "drift-mismatch":
        assert captured.endswith(b"lane-boundary-checked\n") and b"drift-checked" not in captured
        assert not (home / "maintenance-q13-lanes-c6").exists()
    if case != "accepted-denial":
        # All H7 controls completed before the conditional G1 (also when measured).
        for control, returncode in (("h7-active", 0), ("h7-s6b", 1), ("h7-s6c", 1)):
            status = home / "maintenance-q13-lanes-c5" / control / "status.json"
            assert json.loads(status.read_bytes()) == {"returncode": returncode}
        assert (directory / "binding").read_text().find("stale-generation") >= 0
