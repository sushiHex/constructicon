"""Portable operator-contract unit tests.

Synthetic receipt helpers below exercise consumer rejection only. Actual
generated-command execution and receipt propagation belong to the Linux
rehearsal; compilation or Bash syntax is never labeled native execution.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.ops import claude_read_commands as commands
from scripts.ops import claude_read_session as session

from tests.git_bash import git_bash


def binding_record():
    values = dict.fromkeys((*commands.BASE, *commands.LATE), "UNREVIEWED")
    values.update(
        EXPECTED_BOOT="00000000-0000-4000-8000-000000000001",
        R="/home/fixture/m8-claude-first-read-fixture",
        RUN="/var/lib/m8-cr-run-fixture",
        AUTH="/var/lib/m8-cr-auth-fixture",
        ACQ="/var/lib/m8-cr-acq-fixture",
        QUAL="/var/lib/m8-cr-run-fixture/qualify.json",
        ACTOR="static:fixture",
        READ_KEY="fixture-read",
        AUTHORIZATION_ID="fixture-read",
    )
    return {
        "schema_version": 1,
        "controller_commit": "4adb8298bb933c4fac1894308ad9b4e39823c19d",
        "namespace": "fixture-read-session",
        "controller_workspace": "/home/fixture/controller",
        "launch_workspace": "/home/fixture/launch",
        "selected_plan": "pro",
        "values": values,
        "pins": {
            "launch_commit": "1" * 40,
            "configuration_sha256": "2" * 64,
            "controller_helper_sha256": "3" * 64,
            "launch_helper_sha256": "4" * 64,
            "checker_path": "/var/lib/fixture-checker/check_claude_phase.py",
            "checker_sha256": "5" * 64,
            "checker_size": 17476,
            "drift_sha256": "6" * 64,
            "drift_stdout": "NO DRIFT: fixture\n",
            "d2_commit": "8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3",
            "d2_workspace": "/home/fixture/m8-host",
        },
    }


def write(path, value):
    path.write_bytes(session.json_bytes(value))


def build(tmp_path, record, phase, evidence):
    binding_file = tmp_path / (phase + "-bindings.json")
    write(binding_file, record)
    package = tmp_path / phase
    revision = commands.operator_revision()
    manifest = commands.build_package(phase, binding_file, evidence, package, revision)
    pins, bindings = commands.package_checked(package, manifest, revision)
    return package, manifest, pins, bindings


def synthetic_receipt(evidence, package, manifest, pins, bindings):
    """Consumer unit input, deliberately not a claim that the script executed."""
    phase = pins["phase"]
    write(
        evidence / (phase + ".status.json"),
        {"completed": True, "returncode": 0, "timed_out": False},
    )
    (evidence / (phase + ".stdout")).write_bytes(commands.PHASES[phase].stdout)
    (evidence / (phase + ".stderr")).write_bytes(b"")
    (evidence / (phase + "-context.json")).write_bytes(
        commands.context_bytes(manifest, pins, bindings),
    )


@pytest.fixture
def consumer_world(tmp_path):
    record = binding_record()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for phase in ("d2-preserve", "d2-verify"):
        package, manifest, pins, bindings = build(tmp_path, record, phase, evidence)
        synthetic_receipt(evidence, package, manifest, pins, bindings)
    verify = {
        "command": "verify",
        "commit": record["pins"]["d2_commit"],
        "first_parent": True,
        "script_matches_commit": True,
        "installed": True,
    }
    probe = {
        "qualified": True,
        "commit": record["pins"]["d2_commit"],
        "scope": "runner_prerequisites_only",
        "production_available": False,
    }
    (evidence / "d2-lr2.out").write_bytes(
        (
            record["values"]["EXPECTED_BOOT"]
            + "\nverify exit 0\n"
            + json.dumps(verify)
            + "\nprobe exit 0\n"
            + json.dumps(probe)
            + "\n"
        ).encode()
    )
    for phase in ("controller-verify", "launch-verify", "checker-verify"):
        package, manifest, pins, bindings = build(tmp_path, record, phase, evidence)
        synthetic_receipt(evidence, package, manifest, pins, bindings)
    return record, evidence


def test_isolated_real_entry_compiles_exclusive_package(tmp_path):
    record = binding_record()
    binding_file = tmp_path / "bindings.json"
    write(binding_file, record)
    output = tmp_path / "package"
    argv = [
        sys.executable,
        "-I",
        "-B",
        str(Path(session.__file__)),
        "compile",
        "--phase",
        "d2-preserve",
        "--bindings",
        str(binding_file),
        "--evidence",
        str(tmp_path),
        "--out",
        str(output),
        "--operator-revision",
        commands.operator_revision(),
    ]
    child = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert child.returncode == 0 and child.stderr == b""
    result = json.loads(child.stdout)
    pins, bound = commands.package_checked(
        output, result["package_manifest"], commands.operator_revision()
    )
    assert pins["controller_commit"] == record["controller_commit"]
    assert pins["operator_revision"] == commands.operator_revision()
    assert bound.selected_plan == "pro" and pins["controller_commit"] != pins["operator_revision"]
    repeated = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert repeated.returncode == 1


@pytest.mark.parametrize("fault", ["extra", "size-bool", "unsafe-path", "plan", "drift"])
def test_binding_shape_refuses_unknown_or_unsafe_data(fault):
    record = binding_record()
    if fault == "extra":
        record["command"] = "arbitrary"
    elif fault == "size-bool":
        record["pins"]["checker_size"] = True
    elif fault == "unsafe-path":
        record["controller_workspace"] = "/home/fixture/../other"
    elif fault == "plan":
        record["selected_plan"] = "unknown"
    else:
        record["pins"]["drift_stdout"] = "unbounded\nextra\n"
    with pytest.raises(commands.Refused):
        commands.Bindings.from_dict(record)


def test_phase_owns_producer_and_consumer_marker(consumer_world):
    record, evidence = consumer_world
    bindings = commands.Bindings.from_dict(record)
    commands.check_phase_receipt(bindings, "controller-verify", evidence)
    checker = commands.compile_phase(bindings, "checker-verify", evidence)
    assert record["pins"]["checker_sha256"].encode() in checker
    assert b"0o444" in checker and b"0o555" in checker
    assert "installed_checker_custody" not in commands.PHASES["checker-verify"].checks
    assert b" reload " in commands.compile_phase(bindings, "reload", evidence)
    with pytest.raises(TypeError):
        commands.phase_receipt(
            evidence, bindings.expanded(), "controller-verify", expected_stdout=b""
        )


@pytest.mark.parametrize(
    "fault", ["missing", "source", "controller", "boot", "script", "marker", "native", "timeout"]
)
def test_checker_receipt_is_load_bearing_consumer_guard(consumer_world, fault):
    record, evidence = consumer_world
    bindings = commands.Bindings.from_dict(record)
    if fault == "missing":
        (evidence / "checker-verify.status.json").unlink()
    elif fault in ("source", "controller", "boot", "script"):
        path = evidence / "checker-verify-context.json"
        value = json.loads(path.read_bytes())
        key = {
            "source": "operator_revision",
            "controller": "controller_commit",
            "boot": "boot",
            "script": "script_sha256",
        }[fault]
        value[key] = "0" * 64
        write(path, value)
    elif fault == "marker":
        (evidence / "checker-verify.stdout").write_bytes(b"drift-checked\nextra\n")
    else:
        write(
            evidence / "checker-verify.status.json",
            {
                "completed": fault == "native",
                "returncode": 1 if fault == "native" else None,
                "timed_out": fault == "timeout",
            },
        )
    with pytest.raises((commands.Refused, FileNotFoundError)):
        commands.compile_phase(bindings, "reload", evidence)


def test_all_names_and_readbacks_share_the_bound_namespace(consumer_world):
    record, _ = consumer_world
    bindings = commands.Bindings.from_dict(record)
    names = {commands.remote_name(bindings, phase, "a" * 64) for phase in commands.PHASES}
    assert len(names) == 21 and all(name.startswith(record["namespace"] + "-") for name in names)
    for phase in ("controller-verify", "launch-verify"):
        path, _, _, _ = commands.readback_spec(bindings, phase, "verification", "a" * 64)
        assert record["namespace"] in path


def test_generated_readiness_bash_syntax_only(consumer_world):
    record, evidence = consumer_world
    bindings = commands.Bindings.from_dict(record)
    for phase in (
        "d2-preserve",
        "d2-verify",
        "controller-verify",
        "launch-verify",
        "checker-verify",
        "parents",
        "reload",
        "reload-check",
    ):
        raw = commands.compile_phase(bindings, phase, evidence)
        checked = subprocess.run([git_bash(), "-n"], input=raw, capture_output=True, check=False)
        assert checked.returncode == 0 and checked.stdout == checked.stderr == b""


def test_actual_capture_preserves_nonzero_and_closed_stdin(tmp_path):
    child = tmp_path / "finite_child.py"
    child.write_text(
        'import sys\nassert sys.stdin.buffer.read()==b""\n'
        'sys.stdout.buffer.write(b"finite\\n")\nraise SystemExit(23)\n',
        encoding="utf-8",
    )
    result, out, err = session.capture(
        "finite", tmp_path, [sys.executable, "-I", "-B", str(child)], 30
    )
    assert result == {"completed": True, "returncode": 23, "timed_out": False}
    assert out == b"finite\n" and err == b"" and not commands.completed_zero(result)


def test_failed_transport_preflight_never_requests_mkdir_or_copy(tmp_path, monkeypatch):
    record = binding_record()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    package, manifest, pins, bindings = build(tmp_path, record, "d2-preserve", evidence)
    captures = tmp_path / "captures"
    captures.mkdir()
    target, alias = "fixture@192.0.2.1", "fixture"
    grant = tmp_path / "grant.json"
    write(
        grant,
        {
            "schema_version": 1,
            "phase": "d2-preserve",
            "package_manifest": manifest,
            "operator_revision": commands.operator_revision(),
            "controller_commit": bindings.controller_commit,
            "bindings_sha256": pins["bindings_sha256"],
            "boot": bindings.values["EXPECTED_BOOT"],
            "target_sha256": commands.sha((target + "\0" + alias).encode()),
            "checks": dict.fromkeys(commands.COMMON_CHECKS, True),
        },
    )
    seen = []

    def refused(argv, **kwargs):
        assert kwargs["stdin"] is subprocess.DEVNULL and kwargs["shell"] is False
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(session.subprocess, "run", refused)
    with pytest.raises(commands.Refused):
        session.one_phase(
            package,
            manifest,
            commands.operator_revision(),
            evidence,
            grant,
            captures,
            target,
            alias,
            commands.sha(grant.read_bytes()),
        )
    assert len(seen) == 1 and "lexists" in seen[0][-1]
    assert commands.remote_name(bindings, "d2-preserve", manifest) in seen[0][-1]
    assert not (evidence / "d2-preserve.status.json").exists()


def test_cleanup_stays_compilable_without_post_activation_pins(tmp_path):
    record = binding_record()
    record["values"].update(FLOOR="5", GENERATION="6")
    first = commands.compile_phase(commands.Bindings.from_dict(record), "withdraw-after", tmp_path)
    changed = copy.deepcopy(record)
    changed["values"].update(
        Q="sha256:" + "a" * 64,
        QUAL_RAW_SHA256="b" * 64,
        SEALED_SHA256="c" * 64,
        CANDIDATE_SHA256="d" * 64,
    )
    assert (
        commands.compile_phase(commands.Bindings.from_dict(changed), "withdraw-after", tmp_path)
        == first
    )
    assert b'--expected-floor "$GENERATION"' in first


@pytest.mark.parametrize("native_code", [0, 1])
def test_real_cli_exit_matches_retained_native_status(tmp_path, native_code):
    """Actual CLI/process boundary; fake SSH does not claim to execute Bash."""
    evidence, captures = tmp_path / "evidence", tmp_path / "captures"
    evidence.mkdir()
    captures.mkdir()
    package, manifest, pins, bindings = build(
        tmp_path,
        binding_record(),
        "d2-preserve",
        evidence,
    )
    target, alias = "fixture@192.0.2.1", "fixture"
    grant = tmp_path / "grant.json"
    write(
        grant,
        {
            "schema_version": 1,
            "phase": "d2-preserve",
            "package_manifest": manifest,
            "operator_revision": commands.operator_revision(),
            "controller_commit": bindings.controller_commit,
            "bindings_sha256": pins["bindings_sha256"],
            "boot": bindings.values["EXPECTED_BOOT"],
            "target_sha256": commands.sha((target + "\0" + alias).encode()),
            "checks": dict.fromkeys(commands.COMMON_CHECKS, True),
        },
    )
    fake = tmp_path / "fake_ssh.py"
    fake.write_text(
        """import json,sys
from pathlib import Path
argv=json.loads(sys.argv[1])
assert sys.stdin.buffer.read()==b""
with Path(sys.argv[2]).open("a",encoding="utf-8") as stream:
    stream.write(json.dumps(argv)+"\\n")
if "/bin/bash phase.sh" in argv[-1]:
    sys.stdout.buffer.write(b"g11-boot-d2-records-preserved\\n")
    raise SystemExit(int(sys.argv[3]))
""",
        encoding="utf-8",
    )
    harness = tmp_path / "isolated_entry.py"
    harness.write_text(
        """import json,runpy,subprocess,sys
from pathlib import Path
root,fake,log,code=sys.argv[1:5]
entry=Path(root)/"scripts/ops/claude_read_session.py"
original=subprocess.run
def process_boundary(argv,**kwargs):
    assert argv[0].endswith(("ssh","ssh.exe","scp","scp.exe"))
    return original([sys.executable,"-I","-B",fake,json.dumps(argv),log,code],**kwargs)
subprocess.run=process_boundary
sys.argv=[str(entry),*sys.argv[5:]]
runpy.run_path(str(entry),run_name="__main__")
""",
        encoding="utf-8",
    )
    log = tmp_path / "argv.jsonl"
    child = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(harness),
            str(commands.ROOT),
            str(fake),
            str(log),
            str(native_code),
            "transport",
            "--package",
            str(package),
            "--manifest",
            manifest,
            "--operator-revision",
            commands.operator_revision(),
            "--evidence",
            str(evidence),
            "--captures",
            str(captures),
            "--grant",
            str(grant),
            "--grant-sha256",
            commands.sha(grant.read_bytes()),
            "--target",
            target,
            "--alias",
            alias,
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    expected = {"completed": True, "returncode": native_code, "timed_out": False}
    assert child.returncode == native_code and child.stderr == b""
    assert json.loads(child.stdout) == expected
    assert json.loads((evidence / "d2-preserve.status.json").read_bytes()) == expected
    assert len(log.read_text(encoding="utf-8").splitlines()) == 4


@pytest.mark.parametrize("phase", ["controller-verify", "launch-verify"])
def test_actual_verifier_marker_statement_matches_phase_contract(tmp_path, phase):
    """Execute the emitted marker statement only, not the verifier/helper."""
    bindings = commands.Bindings.from_dict(binding_record())
    marker = commands._verification_body(bindings.expanded(), phase).splitlines()[-1]
    path = tmp_path / "marker.sh"
    path.write_bytes((marker + "\n").encode())
    child = subprocess.run(
        [git_bash(), str(path)], stdin=subprocess.DEVNULL, capture_output=True, check=False
    )
    assert child.returncode == 0 and child.stderr == b""
    assert child.stdout == commands.PHASES[phase].stdout.removeprefix(b"drift-checked\n")
