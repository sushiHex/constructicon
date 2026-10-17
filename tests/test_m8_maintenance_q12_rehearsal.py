"""q12's packaged steps, rehearsed through its own transport (T5) before any host.

Each test builds the reviewed composition with ``scripts/m8_procedure_package.py``,
runs a built ``<step>.sh`` with real bash as T5's command, and holds T5's verdict
against the step's built ``.expected.json``. The only test-time changes are listed
where they are made: one override inserted after OC's Setup, and the host paths
and tools a test host cannot have.

- **Portable (every verify run):** ``q12-c5-h7``, the new combined H7/H8 step. It
  runs the real lane CLI (``tests/lane_cli_double.py``: ``codex_lane.main`` with a
  scripted peer, as #210's tests do) through the real L0-L3 blocks and OC's frozen
  evidence checker. Covered: measured refresh (alternative 0), unmeasured then a
  measured H8 (alternative 1), an unmeasured H8, and a denial control that was
  accepted.
- **Foundation lane (``M8_READ_REHEARSAL_REQUIRED``):** ``q12-c2-preflight`` with
  real sudo, the real service user, the real lane CLI's ``preflight`` and the real
  launch root.

Not rehearsable here, and why (every step not rehearsed above is named):
- ``q12-c1-controller`` and ``q12-c1-history`` need the VM's installed controller
  workspace, the retained g10 generation and the g9 account seal.
  ``q12-c2-preserve`` needs the g11 boot's D2 records under the service home. All
  three fences are g11's or P1's, tested with their own documents.
- ``q12-c2-d2``, ``q12-c2-lr3``, ``q12-c2-r11``, ``q12-c2-kept-launch`` and
  ``q12-c2-controller``: C2's installers (LR2, LR3, R11, LR8, R19) need the VM's installed
  controller, launch and D2 set, and the network. Their records' grammar is tested
  in ``test_m8_maintenance_q12_continuation.py``; their fences are frozen and
  tested with their own runbooks.
- ``q12-c3-qualification``: its L1 and S6a need ``maintain`` on a store. CI's
  only store is the shared fixture, and a maintenance withdrawal would change it
  for the lane's later steps. L1 and S6a are tested as blocks in ``test_m8_lane_output.py`` and
  ``test_m8_operator_commands.py``.
- ``q12-c3-retained`` binds g11's actual evidence digest, so only its refusal is
  reachable off the host.
- ``q12-c4-publish``, ``q12-c7-prepare``, ``q12-c8-preflight``,
  ``q12-c9-authority``, ``q12-c10-application``, ``q12-c10-inspect`` and
  ``q12-c11-diagnosis`` need a published generation, the source bundle and the
  application. Their fences are g11's, unchanged and tested in
  ``test_m8_maintenance_g11_continuation.py``.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package

from tests.test_m8_lane_output import (  # noqa: F401  (fixtures)
    DOUBLE,
    PURELIB,
    PYTHON_FENCE,
    SOURCE,
    _composable,
    _evidence_program,
    _evidence_world,
    _operator_world,
    _record,
    seal,
)
from tests.test_m8_operator_commands import _bash

ROOT = Path(__file__).resolve().parents[1]
HANDOFFS = ROOT / "docs" / "plans" / "handoffs"
DOCUMENT = HANDOFFS / "M8-maintenance-q12-continuation.md"
SETUP = "Setup: fixed controller and evidence checks"
CHECKED = "transport-step-checked"
REFUSED = "transport-step-refused\n"


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _built(tmp_path: Path, name: str) -> tuple[str, Path]:
    """One step of the first package, as the operator would upload it."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "package-1"
    package.build(DOCUMENT, out)
    return _text(out / f"{name}.sh"), out / f"{name}.expected.json"


def _with_override(script: str, override: str) -> str:
    """The one inserted override: right after OC's Setup, where the CI stands in
    for host-only parts, before any of the step's own declarations."""
    setup = package.fences(package.section(_text(HANDOFFS / "M8-N4-operator-commands.md"),
                                           SETUP))[1][1]
    assert script.count(setup) == 1
    return script.replace(setup, setup + override + "\n", 1)


def _transport() -> str:
    program, = (match["body"] for match in
                PYTHON_FENCE.finditer(package.section(_text(DOCUMENT), "Q6: transport T5")))
    return program


def _t5(directory: Path, script: Path, expected: Path, **environment: str):
    t5 = directory / "m8-q12-transport.py"
    t5.write_text(_transport(), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(t5), str(directory / "step"), str(expected),
         "--", _bash(), script.as_posix()],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180, check=False,
        cwd=directory, env={**os.environ, **environment},
    )


REHEARSED = {"q12-c5-h7", "q12-c2-preflight"}


def test_every_step_is_rehearsed_or_named_with_its_reason():
    """Q0 criterion 2, mechanically: no step is silently left out of the rehearsal."""
    steps = {step.name for step in package.assemble(DOCUMENT)}
    named = set(re.findall(r"``(q12-[a-z0-9-]+)``", __doc__ or ""))
    assert steps - REHEARSED == named - REHEARSED and named - REHEARSED <= steps
    assert steps >= REHEARSED


# --- portable: the combined H7/H8 step --------------------------------------------

# Host paths and the host-only drift tool, replaced for a test host.
HOST_PATHS = {
    "/home/m8-service/m8-maint-q12": "$TEST_W",
    "/home/m8-service/m8-maint-q10": "$TEST_W_PRIOR",
    "/usr/local/bin/m8-host-drift": "\"$TEST_PY\" -c \"print('NO DRIFT')\"",
}
OVERRIDE = "\n".join((
    'SERVICE=(); R=/s; K=k; L=/r; SEAL="$TEST_SEAL"; Q=sha256:' + "0" * 64,
    "load_final_qualification() { :; }",
    'binding_check() { printf "%s\\n" "$*" >>"$TEST_W/binding"; }',
    "check_sealed() { :; }",
    'sudo() { test "$*" = "-n true"; }',
    'LANE=("$TEST_PY" -I -S -B "$TEST_DOUBLE" "$TEST_SOURCE" "$TEST_PURELIB" "$TEST_RECORDS" --)',
    'check_evidence() { "$TEST_PY" -I -S -B -c "$TEST_ENTRY" "$TEST_SOURCE" "$TEST_PURELIB" '
    '"$1" "$2" "$3" "$4" "$5" "$W" "$W" < "$TEST_CHECKER"; }',
))


async def _h7(directory: Path, home: Path, **records: str) -> subprocess.CompletedProcess[str]:
    script, expected = _built(directory / "build", "q12-c5-h7")
    for host, test in HOST_PATHS.items():
        assert host in script or host.endswith("q10")
        script = script.replace(host, test)
    path = directory / "q12-c5-h7.sh"
    path.write_bytes(_composable(_with_override(script, OVERRIDE)).encode())
    (directory / "records").mkdir()
    for name, case in records.items():
        (directory / "records" / name).write_text(
            json.dumps(await _record(case, directory / f"run-{name}")), encoding="utf-8")
    (directory / "g11.sealed.json").write_text("{}", encoding="utf-8")
    home.mkdir()
    (home / "maintenance-g9-account.seal").write_text("pro/seal\n", encoding="utf-8")
    checker = directory / "check-evidence.py"
    checker.write_text(_evidence_program(), encoding="utf-8")
    entry = "import sys; sys.path[:0] = sys.argv[1:3]; del sys.argv[1:3]; exec(sys.stdin.read())"
    return _t5(directory, path, expected, HOME=home.as_posix(),
               TEST_PY=Path(sys.executable).as_posix(), TEST_DOUBLE=DOUBLE.as_posix(),
               TEST_SOURCE=SOURCE, TEST_PURELIB=PURELIB,
               TEST_RECORDS=(directory / "records").as_posix(), TEST_W=directory.as_posix(),
               TEST_W_PRIOR=(directory / "q10").as_posix(), TEST_SEAL=seal("pro"),
               TEST_ENTRY=entry, TEST_CHECKER=checker.as_posix())


H7 = {"h7-g11-s6b-denial.json": "denial-derived", "h7-g11-s6c-plan-refusal.json": "wrongplan"}
# T5 compares bytes; native Windows Python writes CRLF to a text-mode stdout, so
# these run where the host's bytes are produced: POSIX, including CI's verify job.
POSIX = pytest.mark.skipif(os.name == "nt", reason="T5 is byte-exact; Windows prints CRLF")


@POSIX
async def test_measured_active_refresh_is_alternative_0_and_skips_h8(evidence_world, tmp_path):
    directory, _ = evidence_world
    ran = await _h7(directory, tmp_path / "home", **H7, **{"h7-g11-active.json": "active-measured"})
    assert (ran.returncode, ran.stdout, ran.stderr) == (0, f"{CHECKED} 0\n", "")
    assert not (tmp_path / "home" / "maintenance-q12-lanes-c6").exists()
    assert (directory / "binding").read_text().endswith(
        f"{directory.as_posix()}/q10/g10.sealed.json stale-generation "
        f"{directory.as_posix()}/g11.sealed.json\n")


@POSIX
async def test_unmeasured_active_refresh_runs_one_h8_as_alternative_1(evidence_world, tmp_path):
    directory, _ = evidence_world
    ran = await _h7(directory, tmp_path / "home", **H7, **{
        "h7-g11-active.json": "active", "h8-g11-explicit-refresh.json": "measured"})
    assert (ran.returncode, ran.stdout, ran.stderr) == (0, f"{CHECKED} 1\n", "")
    status = tmp_path / "home" / "maintenance-q12-lanes-c6" / "h8-explicit" / "status.json"
    assert json.loads(status.read_bytes()) == {"returncode": 0}


@POSIX
async def test_an_unmeasured_h8_is_no_declared_alternative(evidence_world, tmp_path):
    directory, _ = evidence_world
    ran = await _h7(directory, tmp_path / "home", **H7, **{
        "h7-g11-active.json": "active", "h8-g11-explicit-refresh.json": "unmeasured"})
    assert (ran.returncode, ran.stdout) == (1, REFUSED)
    assert (directory / "step.stdout").read_text().endswith("NO DRIFT\nrefresh-unmeasured\n")


@POSIX
async def test_an_accepted_denial_control_stops_before_h8(evidence_world, tmp_path):
    directory, _ = evidence_world
    ran = await _h7(directory, tmp_path / "home", **{
        "h7-g11-active.json": "active", "h7-g11-s6b-denial.json": "active",
        "h7-g11-s6c-plan-refusal.json": "wrongplan"})
    assert (ran.returncode, ran.stdout) == (1, REFUSED)
    assert not (tmp_path / "home" / "maintenance-q12-lanes-c6").exists()
    assert json.loads((directory / "step.status.json").read_bytes())["returncode"] != 0


# --- foundation lane: real tools ----------------------------------------------------


@pytest.fixture(scope="module")
def foundation():
    if not os.environ.get("M8_READ_REHEARSAL_REQUIRED"):
        pytest.skip("the q12 rehearsal's real-tool steps need the provisioned foundation lane")
    if sys.platform != "linux":
        pytest.fail("required foundation lane is not Linux")


def _ci_override() -> str:
    """OC's PY becomes this checkout's interpreter under the same isolated runpy
    entry, and the arrays OC built from it are rebuilt; the store key is the CI
    fixture's (as tests/test_m8_n5_read_rehearsal.py)."""
    entry = ("import runpy, sys; sys.path[:0] = sys.argv[1:3]; del sys.argv[1:3]; "
             'runpy.run_module(sys.argv.pop(1), run_name="__main__", alter_sys=True)')
    command = (sys.executable, "-I", "-S", "-B", "-c", entry, str(ROOT / "src"),
               sysconfig.get_paths()["purelib"])
    return "\n".join((f"K=n3a-fixture\nPY=({shlex.join(command)})",
                      'LANE=("${PY[@]}" "$LANE_MODULE")'))


def test_physical_preflight_with_real_tools(foundation, tmp_path):
    script, expected = _built(tmp_path, "q12-c2-preflight")
    path = tmp_path / "q12-c2-preflight.sh"
    path.write_bytes(_with_override(script, _ci_override()).encode())
    ran = _t5(tmp_path, path, expected)
    assert (ran.returncode, ran.stdout, ran.stderr) == (0, f"{CHECKED} 0\n", ""), (
        (tmp_path / "step.stderr").read_text()[-4000:])
    assert re.fullmatch(r"physical-preflight-checked\n", (tmp_path / "step.stdout").read_text())
