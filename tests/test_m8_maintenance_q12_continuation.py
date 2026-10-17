"""The q12 continuation as composed: pins, renamed copies, records and T5; no host.

The packager builds the document from its pinned sources. The record checker and
transport T5 run as the document's own bytes against private fakes; nothing
reaches a VM, a vendor or the network.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package

from constructicon.core.control import command_id_for, run_id_for_command
from tests.test_m8_operator_commands import PYTHON_PROGRAM, _bash

HANDOFFS = Path(__file__).parents[1] / "docs" / "plans" / "handoffs"
DOCUMENT = HANDOFFS / "M8-maintenance-q12-continuation.md"
G11 = "M8-maintenance-g11-continuation.md"
Q1 = "Q1: workstation sequence"
Q2 = "Q2: pins"
Q3 = "Q3: declarations"
Q4 = "Q4: private host records"
Q5 = "Q5: new and renamed VM fences"
Q6 = "Q6: transport T5"
C = "5793ef98ef5597c9ee9811a0d1f031554eb7f514"
D = "8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3"
RUN = "run-5c7172babff67a7d53412b6c598bc34b"
VALUES = {"PREVIEW_SHA256": "ab" * 32, "RUN_ID": RUN,
          "EXPECTED_BOOT": "934acecb-9042-4e02-845e-050a4d071265"}
DEFERRED = {"q12-c9-authority", "q12-c10-application", "q12-c11-diagnosis"}
LINUX = pytest.mark.skipif(
    sys.platform != "linux",
    reason="the record checker checks uid and mode and reads /proc; Linux CI runs it",
)


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _fence(document: str, heading: str, index: int, lang: str = "bash") -> str:
    """The index-th fence of one language under exactly one heading."""
    found = [body for kind, body in package.fences(package.section(document, heading))
             if kind == lang]
    return found[index]


def _guard() -> dict[str, str]:
    return dict(re.findall(r"^([A-Z_0-9]+)=(\S+)$", _fence(_text(DOCUMENT), Q2, 0), re.M))


@pytest.fixture(scope="module")
def packages(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str, str]:
    root = tmp_path_factory.mktemp("q12")
    first, second = root / "maintenance-q12-package-1", root / "maintenance-q12-package-2"
    return (first, second, package.build(DOCUMENT, first),
            package.build(DOCUMENT, second, values=VALUES))


# --- composition ---------------------------------------------------------------------


def test_assembly_has_nineteen_steps_in_table_order_and_three_wait():
    steps = package.assemble(DOCUMENT)
    assert len(steps) == 19
    assert {step.name for step in steps if step.waiting} == DEFERRED
    # The Q7 table names the same steps, in the same order, as the composition.
    table = re.findall(r"^\| `(q12-[a-z0-9-]+)` \|", _text(DOCUMENT), re.M)
    assert table == [step.name for step in steps]


def _manifest(out: Path) -> list[str]:
    names = []
    for line in (out / "MANIFEST.sha256").read_bytes().decode().splitlines():
        expected, name = line.split("  ")
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == expected
        names.append(name)
    return names


def test_first_build_writes_sixteen_steps_and_defers_three(packages):
    first, _, digest, _ = packages
    names = [step.name for step in package.assemble(DOCUMENT) if not step.waiting]
    assert len(names) == 16
    written = [f"{name}{suffix}" for name in names for suffix in (".sh", ".expected.json")]
    assert _manifest(first) == written
    assert sorted(path.name for path in first.iterdir()) == sorted([*written, "MANIFEST.sha256"])
    assert digest == hashlib.sha256((first / "MANIFEST.sha256").read_bytes()).hexdigest()


def test_second_build_writes_all_nineteen_with_every_value_filled(packages):
    first, second, _, _ = packages
    steps = package.assemble(DOCUMENT, values=VALUES)
    assert len(steps) == 19 and not any(step.waiting for step in steps)
    assert len(_manifest(second)) == 38
    for step in steps:
        script = (second / f"{step.name}.sh").read_bytes()
        assert script == step.text.encode() and b"UNREVIEWED" not in script
        assert (second / f"{step.name}.expected.json").read_bytes() == step.expected().encode()
        if step.name not in DEFERRED:
            # Session values fill only the deferred steps.
            assert (first / f"{step.name}.sh").read_bytes() == script
    filled = {name: (second / f"{name}.sh").read_text(encoding="utf-8") for name in DEFERRED}
    preview, run, boot = (f"{key}={value}\n" for key, value in VALUES.items())
    assert preview in filled["q12-c9-authority"]
    assert preview in filled["q12-c10-application"] and run in filled["q12-c10-application"]
    assert run in filled["q12-c11-diagnosis"] and boot in filled["q12-c11-diagnosis"]


def test_rebuilding_reproduces_both_manifest_hashes(packages, tmp_path):
    _, _, first, second = packages
    assert package.build(DOCUMENT, tmp_path / "again-1") == first
    assert package.build(DOCUMENT, tmp_path / "again-2", values=VALUES) == second
    assert first != second


def test_every_built_step_parses_under_bash(packages):
    _, second, _, _ = packages
    scripts = sorted(second.glob("*.sh"))
    assert len(scripts) == 19
    for script in scripts:
        ran = subprocess.run([_bash(), "-n", script.as_posix()], stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=30, check=False)
        assert (ran.returncode, ran.stderr) == (0, ""), script.name


def test_no_built_step_publishes(packages):
    _, second, _, _ = packages
    scripts = sorted(second.glob("*.sh"))
    assert len(scripts) == 19
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        for public in ("git push", " gh ", "curl -X", "--data", "api.github.com"):
            assert public not in text, (script.name, public)


# --- pins -----------------------------------------------------------------------------


def test_every_set_declaration_is_the_guard_literal():
    guard = _guard()
    spec = package.composition(_text(DOCUMENT))
    filled = [(name, value) for step in spec["steps"] for part in step["parts"]
              for name, value in part.get("set", {}).items()]
    assert {name for name, _ in filled} == {"C", "O", "D"}
    for name, value in filled:
        assert value == guard[name], name
    assert guard["D"] == D


def test_guard_names_one_installed_commit_and_passes_its_own_checks():
    guard = _guard()
    assert guard["C"] == guard["O"] == guard["BASE"] == C
    ran = subprocess.run([_bash(), "-c", "set +e\n" + _fence(_text(DOCUMENT), Q2, 0)
                          + "echo transport-permitted\n"], stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=30, check=False)
    assert (ran.returncode, ran.stdout, ran.stderr) == (0, "transport-permitted\n", "")
    prepare = {step.name: step for step in package.assemble(DOCUMENT)}["q12-c7-prepare"]
    pin, = prepare.alternatives
    assert json.loads(pin[-1]) == {"base": guard["BASE"], "source_prepared": True,
                                   "bundle_sha256": guard["BUNDLE_SHA256"]}


def test_application_run_id_is_derived_from_the_fourth_actor_and_key():
    derived = str(run_id_for_command(
        command_id_for("operator:maintenance-4", "runs_start", "maintenance-4")))
    assert derived == RUN == VALUES["RUN_ID"]
    steps = {step.name: step for step in package.assemble(DOCUMENT, values=VALUES)}
    alternatives = steps["q12-c10-application"].alternatives
    assert [json.loads(lines[1])["accepted"] for lines in alternatives] == [True, False]
    assert {json.loads(lines[1])["run_id"] for lines in alternatives} == {derived}
    assert f"must equal `{derived}`" in _text(DOCUMENT)


def test_application_declarations_name_the_fourth_actor_and_key():
    lines = _fence(_text(DOCUMENT), Q3, 2).splitlines()
    assert "ACTOR=operator:maintenance-4" in lines and "KEY=maintenance-4" in lines


# --- renamed copies -------------------------------------------------------------------

C1 = "C1: one fresh boot, historical g10 and the retained capture"
C2 = "C2: preserve current D2 records and verify the kept launch"
C7 = "C7: fresh closure, source bundle and authority"
C11 = "C11: one same-session installed diagnosis, then preserve and park"
SESSION = (("maintenance-g11-", "maintenance-q12-"),)


@pytest.mark.parametrize(("heading", "index", "lang", "target", "target_index", "renames"), [
    pytest.param(C1, 0, "python", Q1, 0, (*SESSION, ("g11-vm-start-", "q12-vm-start-")),
                 id="d0-start"),
    # The section's second fence; its only python one.
    pytest.param(C11, 0, "python", Q1, 1, (*SESSION, ("g11-vm-park-", "q12-vm-park-")),
                 id="d4-park"),
    pytest.param(C2, 0, "bash", Q5, 0, (
        ("maintenance-g11-d2-prior", "maintenance-q12-d2-prior"),
        ("g10-boot-d2-records-preserved", "g11-boot-d2-records-preserved"),
    ), id="d2-archive"),
    pytest.param(C7, 0, "bash", Q3, 2, (
        ("/home/m8-service/m8-m3", "/home/m8-service/m8-m4"),
        ("m8-maint-a3", "m8-maint-a4"),
        ("constructicon-m8-maintenance-3/application-3.json",
         "constructicon-m8-maintenance-4/application-4.json"),
        ('ID="maintenance-3-$C"', 'ID="maintenance-4-$C"'),
        ("operator:maintenance-3", "operator:maintenance-4"),
        ("KEY=maintenance-3", "KEY=maintenance-4"),
    ), id="application-declarations"),
    pytest.param(C7, 1, "bash", Q5, 4, SESSION, id="bundle-transfer"),
    pytest.param(C11, 0, "bash", Q5, 5, (
        # Its quiescence capture goes into the uploaded second package (no c11 package).
        ("maintenance-g11-c11-package", "maintenance-q12-package-2"),
        ("g11-diagnostic-capture", "q12-diagnostic-capture"),
        ("m8-maint-diagnosis-3-evidence", "m8-maint-diagnosis-4-evidence"),
    ), id="diagnosis"),
])
def test_renamed_copy_is_its_frozen_source_with_exactly_these_renames(
    heading, index, lang, target, target_index, renames,
):
    copied = _fence(_text(HANDOFFS / G11), heading, index, lang)
    for old, new in renames:
        assert old in copied, old
        copied = copied.replace(old, new)
    assert copied == _fence(_text(DOCUMENT), target, target_index, lang)


def test_explicit_refresh_preconditions_are_r1_without_its_lane_line():
    source = _fence(_text(HANDOFFS / "M8-N5-explicit-refresh.md"),
                    "R1: one explicit-refresh attempt", 0).splitlines(keepends=True)
    copied = _fence(_text(DOCUMENT), Q5, 3)
    assert "".join(source[:8]) == copied and copied.count("\n") == 8
    lane = source[8:]
    assert lane[0].startswith('"${SERVICE[@]}" "${LANE[@]}" startup --request-refresh')
    # One command: every line but the last continues, and only it names the lane.
    assert all(line.endswith(" \\\n") for line in lane[:-1])
    assert lane[-1].endswith("< /dev/null\n")
    assert package.LANE_INVOCATION.search("".join(lane))
    assert not package.LANE_INVOCATION.search(package._normalized(copied))


# --- the record checker ---------------------------------------------------------------

BOOT = "{BOOT}"  # filled from /proc at run time, on Linux only


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


def _controller(**changes: object) -> dict:
    entry = {"uid": 0, "mode": "0o755", "state": "tree", "different": 0, "differences": []}
    record = {"command": "verify-controller", "commit": C, "first_parent": True,
              "script_matches_commit": True, "schema_version": 2, "installed": True,
              "observed": {"/opt/constructicon-m8-controller": entry}}
    entry.update(changes.pop("entry", {}))
    record.update(changes)
    return record


def _d2(verify: str = "verify exit 0", **probe: object) -> str:
    checked = {"command": "verify", "commit": D, "first_parent": True,
               "script_matches_commit": True, "schema_version": 2, "installed": True}
    probed = {"qualified": True, "commit": D, "scope": "runner_prerequisites_only",
              "production_available": False, **probe}
    return f"{BOOT}\n{verify}\n{_json(checked)}probe exit 0\n{_json(probed)}"


LR3 = ("/usr/bin/bwrap: OK\n-rwxr-xr-x 1 root root 4 /usr/bin/git\npython3.12 3.12.3\n"
       "Password locked.\nUser m8-service is not allowed to run sudo on vm.\nLR3 passed\n")
FETCHED = f"{C}\n{C}\trefs/heads/main\nfirst-parent\n100644 blob 0\tuv.lock\n"
VENDOR = {"command": "vendor-inputs", "commit": C, "first_parent": True,
          "script_matches_commit": True, "listed": True, "schema_version": 2}
LR8 = f"{FETCHED}LR8 fetched\nverify exit 0\n"
R19 = 'check exit 0\n{"files": 3, "outside": [], "passed": true}\n'
CONTROLLER = _json(_controller())
NESTED_DUPLICATE = CONTROLLER.replace('"different": 0,', '"different": 0, "different": 0,')

RECORDS = [
    # (kind, case, record, commit argument, mode, accepted)
    ("controller", "accepted", CONTROLLER, C, 0o600, True),
    ("controller", "wrong-commit", CONTROLLER, "a" * 40, 0o600, False),
    ("controller", "installed-false", _json(_controller(installed=False)), C, 0o600, False),
    ("controller", "different-1", _json(_controller(entry={"different": 1})), C, 0o600, False),
    ("controller", "nested-duplicate", NESTED_DUPLICATE, C, 0o600, False),
    ("controller", "trailing-line", CONTROLLER + "extra\n", C, 0o600, False),
    ("controller", "two-documents", CONTROLLER * 2, C, 0o600, False),
    ("controller", "no-final-newline", CONTROLLER[:-1], C, 0o600, False),
    ("controller", "mode-0644", CONTROLLER, C, 0o644, False),
    ("d2", "accepted", _d2(), D, 0o600, True),
    ("d2", "verify-exit-1", _d2("verify exit 1"), D, 0o600, False),
    ("d2", "other-boot", _d2().replace(BOOT, "00000000-0000-4000-8000-000000000000"), D,
     0o600, False),
    ("d2", "not-qualified", _d2(qualified=False), D, 0o600, False),
    ("d2", "probe-missing", _d2().split("probe exit 0\n")[0] + "probe exit 0\n", D, 0o600, False),
    ("d2", "wrong-commit", _d2(), C, 0o600, False),
    ("lr3", "accepted", LR3, None, 0o600, True),
    ("lr3", "no-completion", LR3.replace("LR3 passed\n", ""), None, 0o600, False),
    ("lr3", "no-bwrap-line", LR3.split("\n", 1)[1], None, 0o600, False),
    ("lr3", "trailing-line", LR3 + "extra\n", None, 0o600, False),
    ("r11", "accepted", f"{FETCHED}R11 complete\n{_json(VENDOR)}", C, 0o600, True),
    ("r11", "no-completion", f"{FETCHED}{_json(VENDOR)}", C, 0o600, False),
    ("r11", "not-listed", f"{FETCHED}R11 complete\n{_json({**VENDOR, 'listed': False})}", C,
     0o600, False),
    ("r11", "two-documents", f"{FETCHED}R11 complete\n{_json(VENDOR) * 2}", C, 0o600, False),
    ("lr8", "accepted", LR8 + CONTROLLER, C, 0o600, True),
    ("lr8", "verify-exit-1", LR8.replace("exit 0", "exit 1") + CONTROLLER, C, 0o600, False),
    ("lr8", "no-completion", LR8.replace("LR8 fetched\n", "") + CONTROLLER, C, 0o600, False),
    ("lr8", "installed-false", LR8 + _json(_controller(installed=False)), C, 0o600, False),
    ("lr8", "different-1", LR8 + _json(_controller(entry={"different": 1})), C, 0o600, False),
    ("lr8", "nested-duplicate", LR8 + NESTED_DUPLICATE, C, 0o600, False),
    ("r19", "accepted", R19, None, 0o600, True),
    ("r19", "check-exit-1", R19.replace("exit 0", "exit 1"), None, 0o600, False),
    ("r19", "outside", R19.replace("[]", '["/usr/lib/x.py"]'), None, 0o600, False),
    ("r19", "extra-key", R19.replace("}", ', "private": 1}'), None, 0o600, False),
    ("r19", "two-documents", R19 + R19.split("\n", 1)[1], None, 0o600, False),
    ("r19", "no-final-newline", R19[:-1], None, 0o600, False),
    ("r19", "mode-0644", R19, None, 0o644, False),
    ("hold", "unknown-kind", R19, None, 0o600, False),
]


def _record_program() -> str:
    program, = PYTHON_PROGRAM.findall(_fence(_text(DOCUMENT), Q4, 0))
    return program


@LINUX
@pytest.mark.parametrize(("kind", "case", "record", "commit", "mode", "accepted"), RECORDS,
                         ids=[f"{kind}-{case}" for kind, case, *_ in RECORDS])
def test_record_checker_accepts_only_the_exact_grammar(
    tmp_path, kind, case, record, commit, mode, accepted,
):
    boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").rstrip("\n")
    path = tmp_path / "record"
    path.write_bytes(record.replace(BOOT, boot).encode())
    path.chmod(mode)
    ran = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", _record_program(), kind, str(path),
         *([] if commit is None else [commit])],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False)
    expected = (0, f"{kind}-record-checked\n") if accepted else (1, "record-refused\n")
    assert (ran.returncode, ran.stdout, ran.stderr) == (*expected, ""), case


# --- transport T5 ---------------------------------------------------------------------

EMIT = ("import pathlib, sys; pathlib.Path(sys.argv[4]).write_bytes(b'ran'); "
        "sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes()); "
        "sys.stderr.buffer.write(pathlib.Path(sys.argv[2]).read_bytes()); "
        "raise SystemExit(int(sys.argv[3]))")
CHECKED = b"transport-step-checked %d\n"
REFUSED = b"transport-step-refused\n"
SINGLE = {"alternatives": [["NO DRIFT", "controller-record-checked"]], "record": None}
BRANCHED = {"alternatives": [["lane-boundary-checked", "refresh-measured"],
                             ["lane-boundary-checked", "refresh-unmeasured"]], "record": None}
LINE = b'{"accepted": true, "run_id": "run-x"}\n'


def _record(bound: int = 64, alternatives: list | None = None) -> dict:
    return {"alternatives": [["NO DRIFT"]] if alternatives is None else alternatives,
            "record": {"keys": ["accepted", "run_id"], "max_bytes": bound}}


def _t5(directory: Path, expected: bytes, stdout: bytes = b"", stderr: bytes = b"",
        code: int = 0, step: str = "step") -> subprocess.CompletedProcess[bytes]:
    script = directory / "t5.py"
    script.write_bytes(_fence(_text(DOCUMENT), Q6, 0, "python").encode())
    declared = directory / f"{step}.declared.json"
    declared.write_bytes(expected)
    (directory / "emit.out").write_bytes(stdout)
    (directory / "emit.err").write_bytes(stderr)
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(script), str(directory / step), str(declared),
         "--", sys.executable, "-I", "-S", "-B", "-c", EMIT, str(directory / "emit.out"),
         str(directory / "emit.err"), str(code), str(directory / f"{step}.ran")],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)


def _retained(directory: Path, stdout: bytes, stderr: bytes, code: int, step: str = "step"):
    assert (directory / f"{step}.ran").read_bytes() == b"ran"
    assert (directory / f"{step}.stdout").read_bytes() == stdout
    assert (directory / f"{step}.stderr").read_bytes() == stderr
    assert json.loads((directory / f"{step}.status.json").read_bytes()) == {"returncode": code}


EXACT = b"NO DRIFT\ncontroller-record-checked\n"


@pytest.mark.parametrize(("spec", "stdout", "stderr", "code", "verdict"), [
    pytest.param(SINGLE, EXACT, b"", 0, CHECKED % 0, id="exact-single"),
    pytest.param(BRANCHED, b"lane-boundary-checked\nrefresh-unmeasured\n", b"", 0, CHECKED % 1,
                 id="second-alternative"),
    pytest.param(_record(), b"NO DRIFT\n" + LINE, b"", 0, CHECKED % 0, id="record"),
    pytest.param(_record(len(LINE)), b"NO DRIFT\n" + LINE, b"", 0, CHECKED % 0,
                 id="record-at-bound"),
    pytest.param(SINGLE, EXACT + b"x", b"", 0, REFUSED, id="extra-trailing-byte"),
    pytest.param(_record(alternatives=[[]]), b"", b"", 0, REFUSED, id="missing-record-line"),
    pytest.param(_record(), b"NO DRIFT\n", b"", 0, REFUSED, id="record-missing-alt-matches"),
    pytest.param(_record(), b"NO DRIFT\n" + LINE[:-1], b"", 0, REFUSED, id="record-without-lf"),
    pytest.param(_record(), b"NO DRIFT\n" + LINE * 2, b"", 0, REFUSED, id="two-record-lines"),
    pytest.param(_record(), b'NO DRIFT\n{"accepted": true, "run_id": "r", "x": 1}\n', b"", 0,
                 REFUSED, id="record-extra-key"),
    pytest.param(_record(), b'NO DRIFT\n{"accepted": true}\n', b"", 0, REFUSED,
                 id="record-missing-key"),
    pytest.param(_record(), b'NO DRIFT\n{"accepted": true, "accepted": true, "run_id": "r"}\n',
                 b"", 0, REFUSED, id="record-duplicate-key"),
    pytest.param(_record(), 'NO DRIFT\n{"accepted": true, "run_id": "é"}\n'.encode(), b"", 0,
                 REFUSED, id="record-non-ascii"),
    pytest.param(_record(len(LINE) - 1), b"NO DRIFT\n" + LINE, b"", 0, REFUSED,
                 id="record-over-bound"),
    pytest.param(SINGLE, EXACT, b"Warning: Permanently added\n", 0, REFUSED, id="stderr"),
    pytest.param(SINGLE, EXACT, b"", 1, REFUSED, id="exit-1"),
    pytest.param(SINGLE, EXACT, b"", 255, REFUSED, id="exit-255"),
])
def test_t5_accepts_exactly_one_declared_alternative(tmp_path, spec, stdout, stderr, code,
                                                     verdict):
    ran = _t5(tmp_path, json.dumps(spec).encode(), stdout, stderr, code)
    assert (ran.returncode, ran.stdout, ran.stderr) == (0 if verdict != REFUSED else 1,
                                                        verdict, b"")
    _retained(tmp_path, stdout, stderr, code)


def test_t5_refuses_an_occupied_stdout_before_running_the_command(tmp_path):
    (tmp_path / "step.stdout").write_bytes(b"retained")
    ran = _t5(tmp_path, json.dumps(SINGLE).encode(), EXACT)
    assert (ran.returncode, ran.stdout, ran.stderr) == (1, REFUSED, b"")
    assert not (tmp_path / "step.ran").exists()
    assert (tmp_path / "step.stdout").read_bytes() == b"retained"
    assert not (tmp_path / "step.stderr").exists()
    assert not (tmp_path / "step.status.json").exists()


@pytest.mark.parametrize("expected", [
    pytest.param({**SINGLE, "extra": 1}, id="extra-key"),
    pytest.param({"alternatives": [["x"], ["x"]], "record": None}, id="non-distinct"),
    pytest.param({"alternatives": [["x"]]}, id="no-record-key"),
    pytest.param({"alternatives": [], "record": None}, id="no-alternative"),
    pytest.param({"alternatives": [["x"]], "record": {"keys": ["a", "a"], "max_bytes": 64}},
                 id="repeated-record-key"),
    pytest.param({"alternatives": [["x"]], "record": {"keys": ["a"], "max_bytes": 8193}},
                 id="bound-over-limit"),
])
def test_t5_refuses_a_malformed_expectation_before_running(tmp_path, expected):
    ran = _t5(tmp_path, json.dumps(expected).encode(), b"x\n")
    assert (ran.returncode, ran.stdout, ran.stderr) == (1, REFUSED, b"")
    assert not (tmp_path / "step.ran").exists()
    assert not any(tmp_path.glob("step.std*")) and not (tmp_path / "step.status.json").exists()


@pytest.mark.parametrize(("stdout", "verdict"), [
    (b'a\n{"k": 1}\n', b"transport-step-checked 0\n"),
    (b'a\nb\n{"k": 1}\n', b"transport-step-checked 1\n"),
    (b'a\nb\n', REFUSED),
])
def test_t5_tries_every_alternative_when_one_prefixes_another(tmp_path, stdout, verdict):
    """With a record declared, a longer alternative's next line is no record for the
    shorter one: that alternative simply does not match."""
    spec = {"alternatives": [["a"], ["a", "b"]], "record": {"keys": ["k"], "max_bytes": 64}}
    ran = _t5(tmp_path, json.dumps(spec).encode(), stdout)
    assert (ran.stdout, ran.returncode) == (verdict, 0 if verdict != REFUSED else 1)


def test_t5_refuses_a_duplicate_key_in_the_expectation(tmp_path):
    raw = b'{"alternatives": [["x"]], "record": null, "record": null}'
    ran = _t5(tmp_path, raw, b"x\n")
    assert (ran.returncode, ran.stdout) == (1, REFUSED)
    assert not (tmp_path / "step.ran").exists()


def test_every_built_expectation_admits_its_last_declared_alternative(packages, tmp_path):
    """The packager's own expected.json files and T5 agree on the framing."""
    _, second, _, _ = packages
    declared = sorted(second.glob("*.expected.json"))
    assert len(declared) == 19
    for path in declared:
        step = path.name.removesuffix(".expected.json")
        spec = json.loads(path.read_bytes())
        lines = spec["alternatives"][-1]
        stdout = "".join(line + "\n" for line in lines).encode()
        if spec["record"] is not None:
            stdout += json.dumps({key: 0 for key in spec["record"]["keys"]}).encode() + b"\n"
        ran = _t5(tmp_path, path.read_bytes(), stdout, step=step)
        index = len(spec["alternatives"]) - 1
        assert (ran.returncode, ran.stdout, ran.stderr) == (0, CHECKED % index, b""), step
        _retained(tmp_path, stdout, b"", 0, step)
