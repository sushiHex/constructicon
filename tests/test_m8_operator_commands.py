"""Portable syntax and entry-point checks for the N4 operator runbook.

These checks parse the runbook only.  They never execute an operator command,
touch a host path, invoke a vendor binary, resolve DNS, or require Linux.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from scripts.ci import m8_host_artifacts as artifacts

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.substrate.executors import codex_lane, operator_store
from constructicon.substrate.executors.codex_lane import write_evidence
from constructicon.substrate.executors.codex_protocol import ExpectedAccount
from tests.operator_store_world import StoreWorld
from tests.substrate import test_codex_lane as fake_lane

ROOT = Path(__file__).parents[1]
RUNBOOK = ROOT / "docs" / "plans" / "handoffs" / "M8-N4-operator-commands.md"
PY_FENCE = re.compile(r"```bash\n(?P<body>.*?)^```", re.MULTILINE | re.DOTALL)
PYTHON_PROGRAM = re.compile(
    r"(?:/usr/bin/)?python3\s+-I\s+-S\s+-B\s+-c\s+'(?P<body>.*?)'", re.DOTALL,
)


def _runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _bash() -> str:
    windows_bash = Path(r"C:/Program Files/Git/bin/bash.exe")
    if windows_bash.is_file():
        return str(windows_bash)
    found = shutil.which("bash")
    if found is None:
        pytest.skip("the runbook syntax check requires Git Bash or bash")
    return found


def _run_isolated(module: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run a module with controller-like isolation, but from this source tree."""

    source = ROOT / "src"
    purelib = sysconfig.get_paths()["purelib"]
    entry = (
        "import runpy, sys; sys.path[:0] = sys.argv[1:3]; del sys.argv[1:3]; "
        'runpy.run_module(sys.argv.pop(1), run_name="__main__", alter_sys=True)'
    )
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", entry, str(source), purelib, module, *arguments],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_every_bash_fence_parses_without_execution() -> None:
    fences = [match.group("body") for match in PY_FENCE.finditer(_runbook())]
    assert fences, "the operator runbook has no bash commands to check"
    for fence in fences:
        checked = subprocess.run(
            [_bash(), "-n"], input=fence, capture_output=True, text=True, timeout=30, check=False,
        )
        assert checked.returncode == 0, checked.stderr


def test_every_embedded_python_c_program_parses() -> None:
    programs = [match.group("body") for match in PYTHON_PROGRAM.finditer(_runbook())]
    assert programs, "the operator runbook has no embedded Python programs to check"
    for program in programs:
        ast.parse(program)
    bootstrap = re.search(r"^PY=\((?P<command>.+)\)$", _runbook(), re.MULTILINE)
    assert bootstrap is not None
    ast.parse(shlex.split(bootstrap.group("command"))[-1])


def test_runbook_bootstrap_is_the_reviewed_controller_command() -> None:
    match = re.search(r"^PY=\((?P<command>.+)\)$", _runbook(), re.MULTILINE)
    assert match is not None
    assert tuple(shlex.split(match.group("command"))) == artifacts.controller_command()


@pytest.mark.parametrize(
    ("heading",),
    [
        ("S0. Preconditions",),
        ("S1. Prepare",),
        ("S2. First provisioning",),
        ("S3. Login",),
        ("S4. Qualification",),
        ("S5. Publish",),
        ("S6a. Maintenance-lock",),
        ("S7. Activate",),
        ("S8. Active startup",),
        ("S9. Restart",),
        ("S10. Refresh",),
    ],
)
def test_runbook_has_every_operator_session_step(heading: str) -> None:
    assert f"### {heading}" in _runbook()


def test_s0_runs_the_bare_drift_check_and_stops_without_a_passing_baseline() -> None:
    section = _runbook().split("### S0. Preconditions", 1)[1].split("### S1. Prepare", 1)[0]
    wording = " ".join(section.split())
    assert "/usr/local/bin/m8-host-drift < /dev/null" in section
    assert "Require status zero and the affirmative no-drift output" in wording
    assert "does not create or update one" in wording
    assert "If any record or matching commit is missing, stop" in wording
    assert section.index("sudo -n true < /dev/null") < section.index(
        "/usr/local/bin/m8-host-drift < /dev/null",
    )


def test_each_ssh_step_reloads_setup_and_retained_evidence() -> None:
    document = _runbook()
    assert "n4-common.sh n4-s0.sh" in document
    assert '/usr/bin/ssh -T -o BatchMode=yes "$SSH_TARGET" "C=$C /bin/bash -se"' in document
    assert "do not paste commands into an interactive VM shell" in " ".join(document.split())
    assert 'test ! -e "$W"' not in document
    assert "load_s4_plan() {" in document
    assert "load_final_qualification() {" in document
    assert 'check_evidence qualify "$W/s4-qualification.json"' in document
    assert 'check_evidence hold "$W/s6a-qualification.json"' in document
    steps = {
        "### S6a.": "load_s4_plan",
        "### S5.": "load_final_qualification",
        "### S7.": "load_final_qualification",
        "### S8.": "load_final_qualification",
        "### S9.": "load_final_qualification",
        "### S10.": "load_final_qualification",
    }
    for heading, call in steps.items():
        section = document.split(heading, 1)[1].split("### ", 1)[0]
        assert f"{call}\n" in section
    for heading in ("### S9.", "### S10."):
        section = document.split(heading, 1)[1].split("### ", 1)[0]
        drift = section.index("/usr/local/bin/m8-host-drift < /dev/null")
        assert drift < section.index("load_final_qualification")
    assert 'binding_check "$W/g2.sealed.json" reboot-anchor -' in document
    assert 'binding_check "$W/g1.sealed.json" stale-generation "$W/g2.sealed.json"' in document


@pytest.mark.parametrize(
    ("module", "arguments", "needle"),
    [
        ("constructicon.substrate.executors.operator_store", ("provision", "--help"), "provision"),
        ("constructicon.substrate.executors.operator_store", ("publish", "--help"), "publish"),
        ("constructicon.substrate.executors.operator_store", ("activate", "--help"), "activate"),
        ("constructicon.substrate.executors.codex_lane", ("prepare", "--help"), "prepare"),
        ("constructicon.substrate.executors.codex_lane", ("preflight", "--help"), "preflight"),
    ],
)
def test_documented_entry_points_offer_isolated_help(
    module: str, arguments: tuple[str, ...], needle: str,
) -> None:
    result = _run_isolated(module, *arguments)
    assert result.returncode == 0, result.stderr
    assert needle in result.stdout


def _evidence_program() -> str:
    """Extract the exact Python body run by the documented shell function."""

    section = _runbook().split("check_evidence() {\n", 1)[1].split("\ncheck_sealed() {", 1)[0]
    return section.split("-c '", 1)[1].split("' \\\n    \"$1\"", 1)[0]


def _binding_program() -> str:
    section = _runbook().split("binding_check() {\n", 1)[1].split("\nload_s4_plan() {", 1)[0]
    return section.split("-c '", 1)[1].split("' \"$R\"", 1)[0]


def _run_binding_program(
    world: StoreWorld, old: Path, mode: str, comparison: Path | None,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    monkeypatch.setattr(sys, "argv", [
        "binding-check", str(world.root), world.key, str(old), mode,
        str(comparison) if comparison is not None else "-",
    ])
    before = sys.path[:]
    output = StringIO()
    try:
        with redirect_stdout(output):
            exec(compile(_binding_program(), "runbook-binding-check", "exec"), {})
    finally:
        sys.path[:] = before
    return output.getvalue().strip()


def test_documented_binding_checker_accepts_current_and_specific_stale_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    g1 = tmp_path / "g1.sealed.json"
    g1.write_text(world.sealed.model_dump_json(), encoding="utf-8")
    assert _run_binding_program(world, g1, "accepted", None, monkeypatch) == "accepted"
    world.write_descriptor(2)
    world.activate(2)
    g2 = tmp_path / "g2.sealed.json"
    g2.write_text(world.sealed_for(2).model_dump_json(), encoding="utf-8")
    assert _run_binding_program(world, g2, "accepted", None, monkeypatch) == "accepted"
    assert (
        _run_binding_program(world, g1, "stale-generation", g2, monkeypatch)
        == "stale-generation"
    )
    original = operator_store.BindingStore.open_candidate

    def unrelated_old_refusal(
        self: operator_store.BindingStore,
    ) -> operator_store.OpenedBundle:
        if self.sealed.operator_binding_digest == world.sealed.operator_binding_digest:
            raise ContractViolation("unrelated old-binding refusal")
        return original(self)

    with monkeypatch.context() as local:
        local.setattr(operator_store.BindingStore, "open_candidate", unrelated_old_refusal)
        with pytest.raises(ContractViolation, match="unrelated old-binding refusal"):
            _run_binding_program(world, g1, "stale-generation", g2, monkeypatch)
    with pytest.raises(ValueError, match="binding digests are identical"):
        _run_binding_program(world, g2, "stale-generation", g2, monkeypatch)
    del world.metadata["active.json"]
    with pytest.raises(ContractViolation, match="active selection is unavailable"):
        _run_binding_program(world, g1, "stale-generation", g2, monkeypatch)


def test_documented_binding_checker_requires_exact_reboot_anchor_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    sealed = tmp_path / "g1.sealed.json"
    sealed.write_text(world.sealed.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="pre-reanchor binding was accepted"):
        _run_binding_program(world, sealed, "reboot-anchor", None, monkeypatch)
    world.bundle = replace(world.bundle, boot_id="00000000-0000-0000-0000-000000000002")
    assert (
        _run_binding_program(world, sealed, "reboot-anchor", None, monkeypatch)
        == "reboot-anchor"
    )
    with pytest.raises(ContractViolation, match="anchor is unavailable"):
        _run_binding_program(world, sealed, "accepted", None, monkeypatch)

    def other_refusal(self: operator_store.BindingStore) -> operator_store.OpenedBundle:
        raise ContractViolation("unrelated store refusal")

    monkeypatch.setattr(operator_store.BindingStore, "open_candidate", other_refusal)
    with pytest.raises(ContractViolation, match="unrelated store refusal"):
        _run_binding_program(world, sealed, "reboot-anchor", None, monkeypatch)


def _check_evidence(
    mode: str, path: Path, custody: str, expected: str, policy: Path, directory: Path,
) -> subprocess.CompletedProcess[str]:
    """Run those exact bytes with only the installed-controller search path substituted."""

    entry = "import sys; sys.path[:0] = sys.argv[1:3]; del sys.argv[1:3]; exec(sys.stdin.read())"
    return subprocess.run(
        [
            sys.executable, "-I", "-S", "-B", "-c", entry,
            str(ROOT / "src"), sysconfig.get_paths()["purelib"],
            mode, str(path), custody, expected, str(policy), str(directory),
        ],
        input=_evidence_program(), capture_output=True, text=True, timeout=30, check=False,
    )


@pytest.fixture
def evidence_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """The production lane's scripted peer, relay and sealed data with no vendor."""

    fake_lane.FakeRelay.instances = []
    fake_lane.FakeRelay.closes = True
    monkeypatch.setattr(codex_lane, "EgressRelay", fake_lane.FakeRelay)

    def sealed(data: bytes) -> int:
        path = tmp_path / f"sealed-{len(list(tmp_path.iterdir()))}"
        path.write_bytes(data)
        return os.open(path, os.O_RDONLY)

    monkeypatch.setattr(codex_lane, "sealed_data_fd", sealed)
    (tmp_path / "config.toml").write_text(fake_lane.CONFIGURATION, encoding="utf-8")
    policy = tmp_path / "startup-policy.json"
    policy.write_text(json.dumps({
        "destinations": [
            [item.host, item.port, item.address] for item in fake_lane.POLICY.destinations
        ],
        "connections": fake_lane.POLICY.connections,
    }), encoding="utf-8")
    return tmp_path, policy


@pytest.mark.parametrize("plan", ["pro", "prolite"])
async def test_documented_evidence_checker_accepts_actual_clean_qualification(
    evidence_world: tuple[Path, Path], plan: str,
) -> None:
    directory, policy = evidence_world
    _, evidence = await fake_lane.startup(
        directory, fake_lane.plan_native(plan), expected=fake_lane.qualification_expected(),
    )
    path = directory / "qualification.json"
    revision = write_evidence(path, evidence)
    result = _check_evidence("qualify", path, "maintenance", "-", policy, directory)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(revision)


async def test_documented_checker_refuses_missing_completion_and_new_fault(
    evidence_world: tuple[Path, Path],
) -> None:
    directory, policy = evidence_world
    _, evidence = await fake_lane.startup(directory, fake_lane.startup_native())
    path = directory / "clean.json"
    write_evidence(path, evidence)
    assert _check_evidence("qualify", path, "maintenance", "-", policy, directory).returncode == 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({key: value for key, value in raw.items() if key != "completed"}),
                    encoding="utf-8")
    assert _check_evidence("qualify", path, "maintenance", "-", policy, directory).returncode != 0
    raw["faults"] = ["unexpected fault"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert _check_evidence("qualify", path, "maintenance", "-", policy, directory).returncode != 0


def _active_lane(directory: Path, native: object, *, during=None, writes=None) -> fake_lane.Lane:
    lane = fake_lane.Lane(directory, native, kind="active", during=during, writes=writes)
    original = lane.custody

    def custody() -> codex_lane.Custody:
        held = original()
        return replace(held, detail={"binding_digest": str(digest("fake-active-binding", 1, "g2"))})

    lane.custody = custody
    return lane


@pytest.mark.parametrize("plan", ["pro", "prolite"])
async def test_documented_checker_accepts_actual_active_startup(
    evidence_world: tuple[Path, Path], plan: str,
) -> None:
    directory, policy = evidence_world
    lane = _active_lane(directory, fake_lane.plan_native(plan))
    _, evidence = await fake_lane.startup(
        directory, lane=lane, expected=ExpectedAccount(plan_type=plan),
    )
    path = directory / "active.json"
    revision = write_evidence(path, evidence)
    result = _check_evidence("active", path, "active", plan, policy, directory)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(revision)
    assert _check_evidence("active", path, "active", "wrong", policy, directory).returncode != 0
    assert _check_evidence("active", path, "maintenance", plan, policy, directory).returncode != 0
    assert _check_evidence("qualify", path, "active", plan, policy, directory).returncode != 0


async def test_documented_checker_accepts_actual_login_record(
    evidence_world: tuple[Path, Path],
) -> None:
    directory, policy = evidence_world
    lane = fake_lane.Lane(directory, fake_lane.Printing())
    evidence = await fake_lane.login(lane, directory)
    path = directory / "login.json"
    revision = write_evidence(path, evidence)
    result = _check_evidence("login", path, "maintenance", "-", policy, directory)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(revision)


@pytest.mark.parametrize("plan", ["pro", "prolite"])
async def test_documented_checker_accepts_actual_wrong_plan_refusal(
    evidence_world: tuple[Path, Path], plan: str,
) -> None:
    directory, policy = evidence_world
    lane = _active_lane(directory, fake_lane.plan_native(plan))
    _, evidence = await fake_lane.startup(
        directory, lane=lane, expected=ExpectedAccount(plan_type="plus"),
    )
    assert evidence["faults"], "the scripted peer did not produce a refusal"
    path = directory / "wrongplan.json"
    revision = write_evidence(path, evidence)
    result = _check_evidence("wrongplan", path, "active", plan, policy, directory)
    assert result.returncode == 0, (result.stderr, evidence["faults"])
    assert result.stdout.strip() == str(revision)
    assert _check_evidence("active", path, "active", plan, policy, directory).returncode != 0


async def test_documented_checker_accepts_actual_readback_denial_refusal(
    evidence_world: tuple[Path, Path],
) -> None:
    directory, policy = evidence_world

    def denied(lane: fake_lane.Lane) -> None:
        fake_lane.FakeRelay.instances[-1].observed["denied:destination"] += 1

    native = fake_lane.plan_native("pro")
    native.spends = [{"error": {"code": -32000, "message": "denied by fake relay"}}]
    lane = _active_lane(directory, native, during=denied)
    _, evidence = await fake_lane.startup(
        directory, lane=lane, expected=ExpectedAccount(plan_type="pro"),
        expect_denial=True,
    )
    assert evidence["faults"], "the scripted peer did not produce a refusal"
    path = directory / "denial.json"
    revision = write_evidence(path, evidence)
    result = _check_evidence("denial", path, "active", "pro", policy, directory)
    assert result.returncode == 0, (result.stderr, evidence["faults"])
    assert result.stdout.strip() == str(revision)
    assert _check_evidence("active", path, "active", "pro", policy, directory).returncode != 0


async def test_documented_checker_accepts_actual_maintenance_hold(
    evidence_world: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, policy = evidence_world
    observed: list[float] = []

    async def no_wait(seconds: float) -> None:
        observed.append(seconds)

    monkeypatch.setattr(codex_lane.asyncio, "sleep", no_wait)
    lane = fake_lane.Lane(directory, fake_lane.plan_native("pro"))
    evidence = await codex_lane.run_startup(
        lane.custody(), lane.launcher(), fake_lane.POLICY,
        executable=fake_lane.EXECUTABLE, configuration=fake_lane.CONFIGURATION,
        expected=fake_lane.qualification_expected(), lane_dir=directory / "lane",
        deadline_s=120, hold_s=90,
    )
    assert observed == [90] and evidence["faults"] == []
    path = directory / "hold.json"
    revision = write_evidence(path, evidence)
    result = _check_evidence("hold", path, "maintenance", "-", policy, directory)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(revision)


async def test_documented_checker_accepts_actual_measured_refresh_shape(
    evidence_world: tuple[Path, Path],
) -> None:
    directory, policy = evidence_world

    def refresh(lane: fake_lane.Lane) -> None:
        fake_lane.FakeRelay.instances[-1].destinations["accepted:auth.openai.com:443"] += 1

    lane = _active_lane(directory, fake_lane.plan_native("pro"), during=refresh, writes=True)
    _, evidence = await fake_lane.startup(
        directory, lane=lane, expected=ExpectedAccount(plan_type="pro"),
    )
    assert evidence["refresh"] == "measured" and evidence["faults"] == []
    path = directory / "refresh.json"
    revision = write_evidence(path, evidence)
    result = _check_evidence("refresh", path, "active", "pro", policy, directory)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(revision)
