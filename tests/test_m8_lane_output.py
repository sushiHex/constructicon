"""Join the real lane CLI's output to the #210 boundary blocks; no host or vendor.

Evidence comes from the production lane code with a scripted peer. The CLI that
publishes it, prints its stderr summary, verdict and exit is the real
``codex_lane.main`` in a subprocess (``tests/lane_cli_double.py``), with only
custody and launch substituted. The capture, expectation, boundary and
transport programs are the document's own bytes; the frozen ``check_evidence``
supplies the checked digest. Only Unix flags, uid/mode predicates and the
installed-controller search path are substituted where a native Windows run or
a source checkout requires it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from constructicon.substrate.executors.codex_lane import run_startup, write_evidence
from constructicon.substrate.executors.codex_protocol import ExpectedAccount
from constructicon.substrate.executors.egress import EgressPolicy
from tests import test_m8_operator_commands as operator_commands
from tests.substrate import test_codex_lane as fake_lane
from tests.substrate.test_codex_protocol import IDENTITY
from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import (
    PYTHON_PROGRAM,
    _active_lane,
    _bash,
    _check_evidence,
    _evidence_program,
    seal,
)

# Registered under this attribute: the operator-command checker's scripted lane
# world, its launch set and its startup policy.
_operator_world = operator_commands.evidence_world

DOCUMENT = HANDOFFS / "M8-maintenance-lane-output.md"
G11 = HANDOFFS / "M8-maintenance-g11-continuation.md"
DOUBLE = Path(__file__).with_name("lane_cli_double.py")
SOURCE = (Path(__file__).parents[1] / "src").as_posix()
PURELIB = Path(sysconfig.get_paths()["purelib"]).as_posix()
L0 = "L0: common helpers"
L1 = "L1: qualification boundary"
L2 = "L2: H7 controls"
L3 = "L3: explicit refresh"
L4 = "L4: workstation step transport"
PYTHON_FENCE = re.compile(r"```python\n(?P<body>.*?)^```", re.MULTILINE | re.DOTALL)
CHECKED = "lane-boundary-checked\n"
REFUSED = "lane-boundary-refused\n"
CASES = {
    # case: (check_evidence mode, custody, kind, cli flags)
    "initial": ("initial", "maintenance", "clean", ()),
    "active": ("active", "active", "clean", ()),
    "denial": ("denial", "active", "refusal", ("--expect-denial",)),
    "wrongplan": ("wrongplan", "active", "refusal", ()),
    "measured": (None, "active", "refresh", ("--request-refresh",)),
    "unmeasured": (None, "active", "refresh", ("--request-refresh",)),
}


@pytest.fixture(name="evidence_world")
def _evidence_world(_operator_world: tuple[Path, Path]) -> tuple[Path, Path]:
    return _operator_world


def _helper_block() -> str:
    block, = _fences(_section(_text(DOCUMENT), L0))
    return block


def _portable(program: str) -> str:
    """The installed-controller search path becomes this checkout's; on native
    Windows only the Unix flag, uid/mode and directory-sync boundaries differ."""

    installed = 'sys.path.insert(0, "/opt/constructicon-m8-controller")'
    # JSON spells the paths with double quotes: the program sits in shell single quotes.
    program = program.replace(installed, f"sys.path[:0] = {json.dumps([SOURCE, PURELIB])}")
    if os.name == "nt":
        for flag in ("os.O_NOFOLLOW", "os.O_NONBLOCK", "os.O_CLOEXEC"):
            program = program.replace(flag, "0")
        program = program.replace("os.getuid()", "0")
        program = re.sub(r"\w+\.st_mode & 0o077 == 0", "True", program)
        sync = ("directory = os.open(out, os.O_RDONLY | os.O_DIRECTORY)\n"
                "    os.fsync(directory)\n    os.close(directory)")
        assert program.count(sync) == ("lane-capture-refused" in program)
        program = program.replace(sync, "pass")
    return program


def _programs() -> tuple[str, str, str]:
    capture, expectation, boundary = map(_portable, PYTHON_PROGRAM.findall(_helper_block()))
    assert "lane-capture-refused" in capture and "EVIDENCE_DOMAIN" in expectation
    assert "lane-boundary-checked" in boundary
    return capture, expectation, boundary


def _python(program: str, *argv: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", program, *map(str, argv)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False,
    )


def _capture(out: Path, *command: object) -> subprocess.CompletedProcess[str]:
    return _python(_programs()[0], out, *command)


def _expectation(evidence: Path, mode: str, checked: str) -> subprocess.CompletedProcess[str]:
    return _python(_programs()[1], evidence, mode, checked)


def _boundary(out: Path, kind: str, expected: str) -> subprocess.CompletedProcess[str]:
    return _python(_programs()[2], out, kind, expected)


async def _record(case: str, directory: Path) -> dict:
    """One completed-run record produced by the production lane with a scripted peer."""

    directory.mkdir(exist_ok=True)
    pro = ExpectedAccount(plan_type="pro", identity=IDENTITY)
    if case == "initial":
        _, evidence = await fake_lane.startup(
            directory, fake_lane.plan_native("pro"), expected=fake_lane.qualification_expected(),
        )
    elif case == "active":
        _, evidence = await fake_lane.startup(
            directory, lane=_active_lane(directory, fake_lane.plan_native("pro")), expected=pro,
        )
    elif case == "active-measured":
        def renewed(lane: fake_lane.Lane) -> None:
            fake_lane.FakeRelay.instances[-1].destinations["accepted:auth.openai.com:443"] += 1

        lane = _active_lane(directory, fake_lane.plan_native("pro"), during=renewed, writes=True)
        _, evidence = await fake_lane.startup(directory, lane=lane, expected=pro)
        assert evidence["refresh"] == "measured"
    elif case == "denial-derived":
        # S6b as L2 composes it: the lane runs under the derived auth-only policy.
        def denied_derived(lane: fake_lane.Lane) -> None:
            fake_lane.FakeRelay.instances[-1].observed["denied:destination"] += 1

        native = fake_lane.plan_native("pro")
        native.accounts = [{"error": {"code": -32603,
                                      "message": "workspace routing discovery failed"}}]
        lane = _active_lane(directory, native, during=denied_derived)
        evidence = await run_startup(
            lane.custody(), lane.launcher(),
            EgressPolicy(fake_lane.POLICY.destinations[:1], fake_lane.POLICY.connections),
            executable=fake_lane.EXECUTABLE, configuration=fake_lane.CONFIGURATION,
            expected=pro, lane_dir=directory / "lane", deadline_s=30, expect_denial=True,
        )
    elif case == "wrongplan":
        _, evidence = await fake_lane.startup(
            directory, lane=_active_lane(directory, fake_lane.plan_native("pro")),
            expected=ExpectedAccount(plan_type="plus", identity=IDENTITY),
        )
    elif case == "denial":
        def denied(lane: fake_lane.Lane) -> None:
            fake_lane.FakeRelay.instances[-1].observed["denied:destination"] += 1

        native = fake_lane.plan_native("pro")
        native.accounts = [{"error": {"code": -32603,
                                      "message": "workspace routing discovery failed"}}]
        _, evidence = await fake_lane.startup(
            directory, lane=_active_lane(directory, native, during=denied), expected=pro,
            expect_denial=True,
        )
    else:
        def refreshed(lane: fake_lane.Lane) -> None:
            fake_lane.FakeRelay.instances[-1].destinations["accepted:auth.openai.com:443"] += 1

        measured = case == "measured"
        lane = _active_lane(directory, fake_lane.startup_native(),
                            during=refreshed if measured else None, writes=measured)
        _, evidence = await fake_lane.startup(directory, lane=lane, expected=pro,
                                              request_refresh=True)
        assert evidence["refresh"] == case
    assert bool(evidence["faults"]) is (case in ("denial", "denial-derived", "wrongplan"))
    return evidence


def _lane_command(case: str, records: Path, evidence: Path, directory: Path) -> list[str]:
    _, custody, _, flags = CASES[case]
    custody_flags = (
        ["--custody", "maintenance", "--lock-fd", "7", "--floor", "3"] if custody == "maintenance"
        else ["--custody", "active", "--sealed", str(directory / "sealed.json"),
              "--expected", seal("plus" if case == "wrongplan" else "pro")]
    )
    (directory / "sealed.json").write_text("{}", encoding="utf-8")
    return [
        sys.executable, "-I", "-S", "-B", str(DOUBLE), SOURCE, PURELIB, str(records), "--",
        "startup", *custody_flags, "--store-root", "/s", "--key", "k", "--launch-root", "/r",
        "--configuration", str(directory / "config.toml"), "--policy", "/p",
        "--lane-dir", "/l", "--evidence", str(evidence), *flags,
    ]


async def _joined(case: str, directory: Path, policy: Path) -> tuple[Path, str, str, Path]:
    """Real CLI → actual capture → frozen check → expectation; returns its inputs."""

    records = directory / "records"
    records.mkdir()
    evidence = directory / f"{case}-published.json"
    (records / evidence.name).write_text(
        json.dumps(await _record(case, directory / "lane-run")), encoding="utf-8")
    lanes = directory / "lanes"
    lanes.mkdir(mode=0o700)
    out = lanes / case
    captured = _capture(out, *_lane_command(case, records, evidence, directory))
    assert (captured.returncode, captured.stdout, captured.stderr) == (0, "", "")
    mode, custody, kind, _ = CASES[case]
    if mode is None:
        expected = _expectation(evidence, "explicit", "-")
    else:
        checked = _check_evidence(mode, evidence, custody,
                                  "-" if mode == "initial" else seal("pro"), policy, directory)
        assert checked.returncode == 0, checked.stderr
        summary = json.loads((out / "stderr").read_bytes())
        assert summary["evidence_digest"] == checked.stdout.strip()
        expected = _expectation(evidence, "checked", checked.stdout.strip())
    assert expected.returncode == 0, expected.stderr
    return out, kind, expected.stdout.strip(), evidence


@pytest.mark.parametrize("case", sorted(CASES))
async def test_real_cli_output_passes_its_declared_boundary(evidence_world, case):
    directory, policy = evidence_world
    out, kind, expected, evidence = await _joined(case, directory, policy)
    record = json.loads(evidence.read_bytes())
    assert json.loads((out / "status.json").read_bytes()) == {
        "returncode": 1 if record["faults"] else 0}
    assert (out / "stderr").read_bytes().count(b"\n") == 1
    result = _boundary(out, kind, expected)
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == (f"refresh-{case}\n" if kind == "refresh" else CHECKED)


def _damage(out: Path, damage: str, kind: str, expected: str) -> tuple[str, str]:
    x = json.loads(expected)
    stderr = out / "stderr"
    if damage == "stderr-extra-line":
        stderr.write_bytes(stderr.read_bytes() + b"warning: unexpected diagnostic\n")
    elif damage == "stderr-prefix":
        stderr.write_bytes(b"warning\n" + stderr.read_bytes())
    elif damage == "stderr-no-lf":
        stderr.write_bytes(stderr.read_bytes()[:-1])
    elif damage == "stderr-crlf":
        stderr.write_bytes(stderr.read_bytes().replace(b"\n", b"\r\n"))
    elif damage == "stderr-empty":
        stderr.write_bytes(b"")
    elif damage == "stdout-extra":
        (out / "stdout").write_bytes((out / "stdout").read_bytes() + b"extra\n")
    elif damage == "exit-flipped":
        code = json.loads((out / "status.json").read_bytes())["returncode"]
        (out / "status.json").write_bytes(json.dumps({"returncode": 1 - code}).encode() + b"\n")
    elif damage == "exit-bool":
        code = json.loads((out / "status.json").read_bytes())["returncode"]
        (out / "status.json").write_bytes(json.dumps({"returncode": bool(code)}).encode())
    elif damage == "status-duplicate":
        (out / "status.json").write_bytes(b'{"returncode": 0, "returncode": 0}\n')
    elif damage == "status-missing":
        (out / "status.json").unlink()
    elif damage == "status-extra-file":
        (out / "notes").write_bytes(b"")
    elif damage == "other-digest":
        x["evidence_digest"] = "sha256:" + "0" * 64
    elif damage == "other-faults":
        x["faults"] = [] if x["faults"] else ["the startup gate did not complete"]
    elif damage == "reordered-faults":
        x["faults"] = list(reversed(x["faults"]))
    elif damage == "other-refresh":
        x["refresh"] = "unmeasured" if x["refresh"] == "measured" else "measured"
    elif damage == "expectation-extra-key":
        x["private"] = "PRIVATE:/payload"
    elif damage == "declared-kind":
        kind = {"clean": "refusal", "refusal": "clean", "refresh": "clean"}[kind]
    elif damage == "unknown-kind":
        kind = "hold"
    else:
        raise AssertionError(damage)
    return kind, json.dumps(x)


DAMAGE = (
    "stderr-extra-line", "stderr-prefix", "stderr-no-lf", "stderr-crlf", "stderr-empty",
    "stdout-extra", "exit-flipped", "exit-bool", "status-duplicate", "status-missing",
    "status-extra-file", "other-digest", "other-faults", "expectation-extra-key",
    "declared-kind", "unknown-kind",
)


@pytest.mark.parametrize("case", ("initial", "denial", "measured"))
@pytest.mark.parametrize("damage", DAMAGE)
async def test_every_deviation_from_the_declared_contract_refuses(evidence_world, case, damage):
    directory, policy = evidence_world
    out, kind, expected, _ = await _joined(case, directory, policy)
    kind, expected = _damage(out, damage, kind, expected)
    result = _boundary(out, kind, expected)
    assert (result.returncode, result.stdout, result.stderr) == (1, REFUSED, ""), damage


async def test_reordered_refusal_faults_and_other_verdict_refuse(evidence_world):
    directory, policy = evidence_world
    out, kind, expected, _ = await _joined("denial", directory, policy)
    assert len(json.loads(expected)["faults"]) > 1
    result = _boundary(out, *_damage(out, "reordered-faults", kind, expected))
    assert (result.returncode, result.stdout) == (1, REFUSED)


async def test_a_refresh_verdict_other_than_the_record_refuses(evidence_world):
    directory, policy = evidence_world
    out, kind, expected, _ = await _joined("measured", directory, policy)
    result = _boundary(out, *_damage(out, "other-refresh", kind, expected))
    assert (result.returncode, result.stdout) == (1, REFUSED)


async def test_boundary_stderr_guard_removal_fails_the_regression(evidence_world, monkeypatch):
    actual = _programs()
    guard = ('    assert stderr == (json.dumps({"evidence_digest": d, "faults": f})'
             ' + "\\n").encode("ascii")\n')
    assert actual[2].count(guard) == 1
    mutant = (actual[0], actual[1], actual[2].replace(guard, ""))
    monkeypatch.setattr(sys.modules[__name__], "_programs", lambda: mutant)
    with pytest.raises(AssertionError, match="stderr-extra-line"):
        await test_every_deviation_from_the_declared_contract_refuses(
            evidence_world, "initial", "stderr-extra-line")


async def test_boundary_exit_guard_removal_fails_the_regression(evidence_world, monkeypatch):
    actual = _programs()
    guard = '    assert status["returncode"] == (1 if f else 0)\n'
    assert actual[2].count(guard) == 1
    mutant = (actual[0], actual[1], actual[2].replace(guard, ""))
    monkeypatch.setattr(sys.modules[__name__], "_programs", lambda: mutant)
    with pytest.raises(AssertionError, match="exit-flipped"):
        await test_every_deviation_from_the_declared_contract_refuses(
            evidence_world, "denial", "exit-flipped")


async def test_expectation_binds_the_frozen_checked_digest(evidence_world):
    directory, policy = evidence_world
    first = directory / "first.json"
    second = directory / "second.json"
    for path, case in ((first, "initial"), (second, "active")):
        write_evidence(path, await _record(case, directory / f"run-{case}"))
    checked = _check_evidence("initial", first, "maintenance", "-", policy, directory)
    assert checked.returncode == 0, checked.stderr
    digest = checked.stdout.strip()
    assert _expectation(first, "checked", digest).returncode == 0
    for path, mode, value in (
        (second, "checked", digest), (first, "checked", "-"), (first, "explicit", "-"),
        (first, "checked", digest.upper()), (first, "unknown", digest),
    ):
        refused = _expectation(path, mode, value)
        assert refused.returncode != 0 and refused.stdout == "", (path.name, mode, value)


@pytest.mark.parametrize("damage", ("duplicate", "incomplete", "bool-faults", "schema-4",
                                    "extra-field", "not-requested"))
async def test_explicit_expectation_requires_a_complete_closed_schema_five_record(
    evidence_world, damage,
):
    directory, _ = evidence_world
    path = directory / "explicit.json"
    write_evidence(path, await _record("measured", directory / "run"))
    assert _expectation(path, "explicit", "-").returncode == 0
    raw = json.loads(path.read_bytes())
    if damage == "duplicate":
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace('"completed": true', '"completed": true, "completed": true'),
                        encoding="utf-8")
    else:
        if damage == "incomplete":
            del raw["completed"]
        elif damage == "bool-faults":
            raw["faults"] = [True]
        elif damage == "schema-4":
            raw["schema_version"] = 4
        elif damage == "extra-field":
            raw["private"] = "PRIVATE:/payload"
        else:
            raw["request_refresh"] = False
        path.write_text(json.dumps(raw), encoding="utf-8")
    refused = _expectation(path, "explicit", "-")
    assert refused.returncode != 0 and refused.stdout == "" and "PRIVATE" not in refused.stderr


def _command(program: str, *argv: object) -> list[str]:
    return [sys.executable, "-I", "-S", "-B", "-c", program, *map(str, argv)]


DIGEST = "sha256:" + "a" * 64


def _captured_summary(tmp_path: Path, faults: list[str]) -> Path:
    """A capture whose stderr is exactly the CLI summary for these faults."""

    summary = tmp_path / "summary"
    summary.write_bytes((json.dumps({"evidence_digest": DIGEST, "faults": faults}) + "\n").encode())
    lanes = tmp_path / "lanes"
    lanes.mkdir(mode=0o700)
    out = lanes / "bound"
    captured = _capture(out, *_command(
        "import pathlib, sys; sys.stderr.buffer.write(pathlib.Path(sys.argv[1]).read_bytes()); "
        "raise SystemExit(int(sys.argv[2]))", summary, 1 if faults else 0))
    assert captured.returncode == 0
    return out


@pytest.mark.parametrize("excess", (0, 1))
def test_stderr_bound_binds_at_its_limit(tmp_path, excess):
    base = len(json.dumps({"evidence_digest": DIGEST, "faults": [""]})) + 1
    faults = ["x" * (8192 - base + excess)]
    out = _captured_summary(tmp_path, faults)
    assert (out / "stderr").stat().st_size == 8192 + excess
    result = _boundary(out, "refusal", json.dumps(
        {"evidence_digest": DIGEST, "faults": faults, "refresh": "unmeasured"}))
    assert result.stdout == (REFUSED if excess else CHECKED)


@pytest.mark.parametrize("excess", (0, 1))
def test_status_bound_binds_at_its_limit(tmp_path, excess):
    out = _captured_summary(tmp_path, [])
    # Whitespace-padded JSON is still a well-formed status; only the bound refuses it.
    (out / "status.json").write_bytes(b'{"returncode": 0}'.ljust(63 + excess) + b"\n")
    result = _boundary(out, "clean", json.dumps(
        {"evidence_digest": DIGEST, "faults": [], "refresh": "unmeasured"}))
    assert result.stdout == (REFUSED if excess else CHECKED)


def test_capture_records_command_status_separately_from_capture_success(tmp_path):
    lanes = tmp_path / "lanes"
    lanes.mkdir(mode=0o700)
    out = lanes / "failing"
    result = _capture(out, *_command(
        "import sys; sys.stdout.write('out'); sys.stderr.write('err'); raise SystemExit(3)"))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert json.loads((out / "status.json").read_bytes()) == {"returncode": 3}
    assert (out / "stdout").read_bytes() == b"out" and (out / "stderr").read_bytes() == b"err"
    assert sorted(path.name for path in out.iterdir()) == ["status.json", "stderr", "stdout"]


@pytest.mark.parametrize("damage", ("occupied", "missing-parent", "relative", "no-command"))
def test_capture_refuses_before_any_command_runs(tmp_path, damage):
    lanes = tmp_path / "lanes"
    lanes.mkdir(mode=0o700)
    out = lanes / "s4"
    marker = tmp_path / "ran"
    command = _command("import pathlib, sys; pathlib.Path(sys.argv[1]).touch()", marker)
    if damage == "occupied":
        out.mkdir()
    elif damage == "missing-parent":
        out = tmp_path / "absent" / "s4"
    elif damage == "relative":
        out = Path("relative-lanes") / "s4"
    else:
        command = []
    result = _capture(out, *command)
    assert (result.returncode, result.stdout, result.stderr) == (1, "", "lane-capture-refused\n")
    assert not marker.exists()
    if damage == "occupied":
        assert list(out.iterdir()) == []


def test_unstartable_command_leaves_no_status(tmp_path):
    lanes = tmp_path / "lanes"
    lanes.mkdir(mode=0o700)
    out = lanes / "s4"
    result = _capture(out, str(tmp_path / "absent-executable"))
    assert (result.returncode, result.stderr) == (1, "lane-capture-refused\n")
    assert (out / "status.json").read_bytes() == b""
    refused = _boundary(out, "clean", json.dumps({
        "evidence_digest": "sha256:" + "0" * 64, "faults": [], "refresh": "unmeasured"}))
    assert (refused.returncode, refused.stdout) == (1, REFUSED)


POSIX_RENAME = pytest.mark.skipif(
    os.name == "nt", reason="native Windows refuses to rename a file another process holds open",
)


@POSIX_RENAME
@pytest.mark.parametrize("name", ("stdout", "stderr", "status.json"))
@pytest.mark.parametrize("replacement", ("regular", "removed"))
def test_capture_identity_loss_refuses_before_status(tmp_path, name, replacement):
    lanes = tmp_path / "lanes"
    lanes.mkdir(mode=0o700)
    out = lanes / "s4"
    program = (
        "import os, sys; path = sys.argv[1]; os.replace(path, path + '.moved')"
        if replacement == "removed" else
        "import os, sys; path = sys.argv[1]; os.replace(path, path + '.moved'); "
        "open(path, 'xb').close()"
    )
    result = _capture(out, *_command(program, out / name))
    assert (result.returncode, result.stderr) == (1, "lane-capture-refused\n"), "identity loss"
    status = out / ("status.json.moved" if name == "status.json" else "status.json")
    assert status.read_bytes() == b""


@POSIX_RENAME
def test_capture_identity_guard_removal_fails_the_regression(tmp_path, monkeypatch):
    actual = _programs()
    mutant, count = re.subn(
        r"    for name, fd in zip\(names, fds, strict=True\):\n"
        r".*?== \(opened\.st_dev, opened\.st_ino\)\n",
        "", actual[0], flags=re.S,
    )
    assert count == 1
    monkeypatch.setattr(sys.modules[__name__], "_programs",
                        lambda: (mutant, actual[1], actual[2]))
    with pytest.raises(AssertionError, match="identity loss"):
        test_capture_identity_loss_refuses_before_status(tmp_path, "stderr", "regular")


async def test_frozen_g11_empty_stderr_rule_rejects_a_clean_real_cli_run(evidence_world):
    """#210's reproduction: a clean run that returned zero still writes its summary."""

    directory, policy = evidence_world
    out, _, _, _ = await _joined("initial", directory, policy)
    assert json.loads((out / "status.json").read_bytes()) == {"returncode": 0}
    assert "Require empty stderr at every boundary" in _text(G11)
    rule = subprocess.run([_bash(), "-c", 'test ! -s "$1"', "rule", (out / "stderr").as_posix()],
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False)
    assert rule.returncode == 1


# --- composed shell blocks ---------------------------------------------------------


def _common() -> str:
    operator = _text(HANDOFFS / "M8-N4-operator-commands.md")
    return "\n".join(_fences(operator.split("## Setup", 1)[1].split("\n### ", 1)[0]))


def test_every_block_parses_after_the_composed_common():
    blocks = _fences(_text(DOCUMENT))
    assert len(blocks) == 4
    for block in blocks:
        composed = _common() + "\n" + _helper_block() + "\n" + block
        ran = subprocess.run([_bash(), "-n"], input=composed,
                             capture_output=True, text=True, timeout=30, check=False)
        assert ran.returncode == 0 and ran.stdout == "" and ran.stderr == ""


def _composable(text: str) -> str:
    """Document shell as composed, with the stock interpreter and search path substituted."""

    for program in PYTHON_PROGRAM.findall(text):
        text = text.replace(program, _portable(program))
    return text.replace("/usr/bin/python3", '"$TEST_PY"')


def _run_blocks(blocks: str, directory: Path, policy: Path, maintain: str = "",
                **environment: str) -> subprocess.CompletedProcess[str]:
    checker = directory / "check-evidence.py"
    checker.write_text(_evidence_program(), encoding="utf-8")
    entry = "import sys; sys.path[:0] = sys.argv[1:3]; del sys.argv[1:3]; exec(sys.stdin.read())"
    prefix = "\n".join((
        "set -Eeuo pipefail; umask 077; SERVICE=(); R=/s; K=k; L=/r",
        'W="$TEST_W"; LANES="$TEST_LANES"; GEN=g12; SEAL="$TEST_SEAL"',
        "GEN_PRIOR=g11; W_PRIOR=historical-q11; load_final_qualification() { :; }",
        'binding_check() { printf "%s\\n" "$*" >>"$TEST_W/binding"; }',
        'LANE=("$TEST_PY" -I -S -B "$TEST_DOUBLE" "$TEST_SOURCE" "$TEST_PURELIB" '
        '"$TEST_RECORDS" --)',
        'ROOT_STORE=("$TEST_PY" -I -S -B "$TEST_W/maintain.py")',
        'check_evidence() { "$TEST_PY" -I -S -B -c "$TEST_ENTRY" "$TEST_SOURCE" "$TEST_PURELIB" '
        '"$1" "$2" "$3" "$4" "$5" "$W" "$W" < "$TEST_CHECKER"; }',
        'read_seal() { printf "%s\\n" "$1" >>"$TEST_W/read-seal"; printf pro/seal; }',
    ))
    # Root's `maintain` drops privilege and appends its custody arguments; the
    # child inherits descriptors 0-2 and its exit is maintain's own.
    (directory / "maintain.py").write_text("\n".join((
        "import subprocess, sys",
        "argv = sys.argv[1:]",
        "lane = argv[argv.index('--') + 1:]",
        maintain,
        "raise SystemExit(subprocess.run([*lane, '--store-root=/s', '--key=k',",
        "    '--custody=maintenance', '--lock-fd=7', '--floor=3']).returncode)",
    )), encoding="utf-8")
    # A script file, not `bash -c`: native Windows argv quoting would rewrite it.
    script = directory / "composed-step.sh"
    script.write_bytes((prefix + "\n" + _composable(_helper_block() + "\n" + blocks)).encode())
    return subprocess.run(
        [_bash(), script.as_posix()],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "TEST_PY": Path(sys.executable).as_posix(),
             "TEST_DOUBLE": DOUBLE.as_posix(), "TEST_SOURCE": SOURCE, "TEST_PURELIB": PURELIB,
             "TEST_RECORDS": (directory / "records").as_posix(),
             "TEST_W": directory.as_posix(), "TEST_LANES": (directory / "lanes").as_posix(),
             "TEST_SEAL": seal("pro"), "TEST_ENTRY": entry,
             "TEST_CHECKER": checker.as_posix(), **environment},
    )


async def _records(directory: Path, **cases: str) -> None:
    records = directory / "records"
    records.mkdir()
    for name, case in cases.items():
        (records / name).write_text(
            json.dumps(await _record(case, directory / f"run-{name}")), encoding="utf-8")


@pytest.mark.parametrize("diagnostic", ("", "sudo: unexpected warning\n"))
async def test_qualification_block_accepts_only_the_real_summary(evidence_world, diagnostic):
    directory, policy = evidence_world
    assert policy == directory / "startup-policy.json"
    await _records(directory, **{"s4-qualification.json": "initial"})
    maintain = f"sys.stderr.write({diagnostic!r}); sys.stderr.flush()" if diagnostic else ""
    block, = _fences(_section(_text(DOCUMENT), L1))
    ran = _run_blocks(block, directory, policy, maintain)
    if not diagnostic:
        assert (ran.returncode, ran.stdout, ran.stderr) == (0, CHECKED, "")
        seal_read = f"{directory.as_posix()}/s4-qualification.json\n"
        assert (directory / "read-seal").read_text() == seal_read
    else:
        assert ran.returncode != 0 and ran.stdout == REFUSED and ran.stderr == ""
        assert not (directory / "read-seal").exists()
    assert json.loads((directory / "lanes" / "s4" / "status.json").read_bytes()) == {
        "returncode": 0}


def _h7_block() -> str:
    block, = _fences(_section(_text(DOCUMENT), L2))
    return block


@pytest.mark.parametrize(("active", "verdict"), (
    ("active", "refresh-unmeasured"), ("active-measured", "refresh-measured"),
))
async def test_complete_h7_block_runs_every_control_in_its_declared_order(
    evidence_world, active, verdict,
):
    directory, policy = evidence_world
    assert policy == directory / "startup-policy.json"
    (directory / "g12.sealed.json").write_text("{}", encoding="utf-8")
    await _records(directory, **{"h7-g12-active.json": active,
                                 "h7-g12-s6b-denial.json": "denial-derived",
                                 "h7-g12-s6c-plan-refusal.json": "wrongplan"})
    ran = _run_blocks(_h7_block(), directory, policy)
    assert (ran.returncode, ran.stderr) == (0, ""), ran.stderr
    assert ran.stdout == CHECKED + verdict + "\n" + CHECKED * 2
    statuses = [json.loads((directory / "lanes" / name / "status.json").read_bytes())
                for name in ("h7-active", "h7-s6b", "h7-s6c")]
    assert statuses == [{"returncode": 0}, {"returncode": 1}, {"returncode": 1}]
    derived = json.loads((directory / "h7-g12-no-chatgpt-policy.json").read_bytes())
    assert [destination[0] for destination in derived["destinations"]] == ["auth.openai.com"]
    assert (directory / "binding").read_text() == (
        f"historical-q11/g11.sealed.json stale-generation {directory.as_posix()}/g12.sealed.json\n")


async def test_h7_refusal_control_that_was_accepted_stops(evidence_world):
    directory, policy = evidence_world
    assert policy == directory / "startup-policy.json"
    (directory / "g12.sealed.json").write_text("{}", encoding="utf-8")
    # The S6b control returns a clean active record: its frozen checker refuses.
    await _records(directory, **{"h7-g12-active.json": "active",
                                 "h7-g12-s6b-denial.json": "active",
                                 "h7-g12-s6c-plan-refusal.json": "wrongplan"})
    ran = _run_blocks(_h7_block(), directory, policy)
    assert ran.returncode != 0 and ran.stdout == CHECKED + "refresh-unmeasured\n"
    assert not (directory / "binding").exists()
    assert not (directory / "lanes" / "h7-s6c").exists()


@pytest.mark.parametrize("case", ("measured", "unmeasured"))
async def test_explicit_refresh_block_re_emits_only_the_checked_verdict(evidence_world, case):
    directory, policy = evidence_world
    assert policy == directory / "startup-policy.json"
    (directory / "g12.sealed.json").write_text("{}", encoding="utf-8")
    await _records(directory, **{"h8-explicit.json": case})
    block, = _fences(_section(_text(DOCUMENT), L3))
    root = directory.as_posix()
    ran = _run_blocks(block, directory, policy, SEALED=f"{root}/g12.sealed.json",
                      REFRESH_LANE="/l", REFRESH_EVIDENCE=f"{root}/h8-explicit.json")
    assert (ran.returncode, ran.stdout, ran.stderr) == (0, f"refresh-{case}\n", "")


# --- workstation transport ---------------------------------------------------------


def _transport() -> str:
    program, = (match["body"] for match in PYTHON_FENCE.finditer(_section(_text(DOCUMENT), L4)))
    return program


@pytest.mark.parametrize(("stdout", "stderr", "code", "accepted"), (
    ("lane-boundary-checked\n", "", 0, True),
    ("lane-boundary-checked\n", "", 255, False),
    ("lane-boundary-checked\n", "", 1, False),
    ("lane-boundary-checked\n", "Warning: Permanently added\n", 0, False),
    ("", "", 0, False),
    ("lane-boundary-checked\nextra\n", "", 0, False),
    ("lane-boundary-checked", "", 0, False),
))
def test_transport_retains_ssh_status_and_outputs_separately(tmp_path, stdout, stderr, code,
                                                            accepted):
    expected = tmp_path / "expected"
    expected.write_bytes(b"lane-boundary-checked\n")
    script = tmp_path / "transport.py"
    script.write_text(_transport(), encoding="utf-8")
    ssh = _command("import sys; sys.stdout.buffer.write(sys.argv[1].encode()); "
                   "sys.stderr.buffer.write(sys.argv[2].encode()); "
                   "raise SystemExit(int(sys.argv[3]))", stdout, stderr, code)
    step = tmp_path / "step"
    ran = subprocess.run([sys.executable, "-I", "-S", "-B", str(script), str(step), str(expected),
                          "--", *ssh], stdin=subprocess.DEVNULL, capture_output=True,
                         timeout=60, check=False)
    assert ran.stdout == (b"transport-step-checked\n" if accepted else b"transport-step-refused\n")
    assert ran.returncode == (0 if accepted else 1) and ran.stderr == b""
    assert json.loads((tmp_path / "step.status.json").read_bytes()) == {"returncode": code}
    assert (tmp_path / "step.stdout").read_bytes() == stdout.encode()
    assert (tmp_path / "step.stderr").read_bytes() == stderr.encode()


def test_transport_refuses_an_occupied_output_before_ssh(tmp_path):
    expected = tmp_path / "expected"
    expected.write_bytes(b"x\n")
    script = tmp_path / "transport.py"
    script.write_text(_transport(), encoding="utf-8")
    (tmp_path / "step.stderr").write_bytes(b"retained")
    marker = tmp_path / "ran"
    ran = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(script), str(tmp_path / "step"), str(expected),
         "--", *_command("import pathlib, sys; pathlib.Path(sys.argv[1]).touch()", marker)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)
    assert (ran.returncode, ran.stdout) == (1, b"transport-step-refused\n")
    assert not marker.exists() and (tmp_path / "step.stderr").read_bytes() == b"retained"
