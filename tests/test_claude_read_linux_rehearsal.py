"""Generated Claude operator phases on a disposable, pre-provisioned Linux host.

The fixture input names actual staged installations and their measured pins. The
only transport substitution maps the fixed SSH/SCP argv to local operator-user
processes; the generated shell, capture, readback and receipt gates are real.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.ops import claude_read_commands as commands
from scripts.ops import claude_read_session as session
from scripts.ops import read_metadata_session as metadata

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts/ops/claude_read_session.py"
TARGET = "runner@127.0.0.1"
ALIAS = "local-rehearsal"


def _json(path: Path, value: object) -> None:
    path.write_bytes((json.dumps(value, sort_keys=True) + "\n").encode())


def _cli(*args: str) -> dict:
    result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), *args],
                            stdin=subprocess.DEVNULL, capture_output=True, check=False,
                            timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""
    return json.loads(result.stdout)


def _failure_observation(run: str, run_process) -> dict:
    """Bounded fake-run metadata, with no native transcript or credential bytes."""
    code = r'''
import json, os, pathlib, re, sqlite3, stat, sys
root = pathlib.Path(sys.argv[1])
report = {"attempt": None, "journal_present": False, "event_kinds": [], "node_failures": []}
attempt = root / "read-attempt.json"
if os.path.lexists(attempt):
    info = attempt.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 8192
    fd = os.open(attempt, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        value = json.loads(stream.read(8193))
    facts = value.get("facts") or {}
    report["attempt"] = {"phase": value.get("phase"), "dispatch": value.get("dispatch"),
        "facts": {key: facts.get(key) for key in ("status", "callback_started",
            "callback_completed", "initial_binding_checked", "terminal_binding_checked",
            "relay_closed")}}
database = root / "read.sqlite"
if os.path.lexists(database):
    info = database.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    report["journal_present"] = True
    with sqlite3.connect("file:" + str(database) + "?mode=ro", uri=True) as db:
        report["event_kinds"] = [str(kind)[:80] for kind, in
            db.execute("SELECT kind FROM events ORDER BY seq LIMIT 128")]
        for payload, in db.execute("SELECT payload FROM events WHERE kind='NodeFailed' LIMIT 16"):
            data = json.loads(payload)
            message = str(data.get("error", ""))[:512]
            message = re.sub(r"/[^\s:'\"]+", "<path>", message)
            report["node_failures"].append({"error_type": str(data.get("error_type", ""))[:80],
                                            "error": message})
print(json.dumps(report, sort_keys=True))
'''
    result = run_process(
        ["sudo", "-n", "-u", "m8-service", "/usr/bin/python3", "-I", "-S", "-B", "-c",
         code, run], stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=30,
    )
    if result.returncode != 0 or len(result.stdout) > 16384:
        return {"observation_failed": result.returncode, "output_bytes": len(result.stdout)}
    try:
        return json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError):
        return {"observation_failed": "invalid output"}


def _collector_diagnostic(collector: str, arguments: list[str], run_process) -> dict:
    """Locate caught failures in the fake fixture without publishing exception text."""
    code = r'''
import json, os, stat, sys
source, arguments = sys.argv[1], sys.argv[2:]
namespace = {"__name__": "fixture_collector"}
exec(compile(source, "<fixture-collector>", "exec"), namespace)
events = []
allowed = {"ValueError", "TypeError", "KeyError", "OSError", "FileNotFoundError",
           "RuntimeError", "OperationalError", "DatabaseError", "RecursionError"}
def trace(frame, event, arg):
    if event == "exception" and frame.f_code.co_filename == "<fixture-collector>":
        kind = type(arg[1]).__name__
        events.append([frame.f_code.co_name, frame.f_lineno, kind if kind in allowed else "other"])
        del events[:-32]
    return trace
sys.settrace(trace)
try:
    status = namespace["main"](arguments)
except BaseException:
    status = -1
finally:
    sys.settrace(None)
files = {}
if len(arguments) >= 2 and arguments[0] == "--run-root":
    for name, bound in (("read.sqlite", 16 * 1024 * 1024),
                        ("read.sqlite-wal", 16 * 1024 * 1024),
                        ("read.sqlite-shm", 1024 * 1024)):
        facts = {"exists": None, "regular": None, "singlelink": None,
                 "service_owned": None, "mode_0600": None, "size_within_bound": None}
        try:
            info = os.lstat(os.path.join(arguments[1], name))
            facts.update(exists=True, regular=stat.S_ISREG(info.st_mode),
                         singlelink=info.st_nlink == 1,
                         service_owned=info.st_uid == getattr(os, "geteuid", lambda: -1)(),
                         mode_0600=stat.S_IMODE(info.st_mode) == 0o600,
                         size_within_bound=0 <= info.st_size <= bound)
        except FileNotFoundError:
            facts["exists"] = False
        except OSError:
            pass
        files[name] = facts
print(json.dumps({"status": status, "exceptions": events, "files": files}, sort_keys=True),
      file=sys.stderr)
'''
    result = run_process(
        ["sudo", "-n", "-u", "m8-service", "/usr/bin/python3", "-I", "-S", "-B",
         "-c", code, collector, *arguments], stdin=subprocess.DEVNULL,
        capture_output=True, check=False, timeout=30,
    )
    if result.returncode != 0 or len(result.stderr) > 8192:
        return {"observation_failed": result.returncode}
    try:
        return json.loads(result.stderr)
    except (ValueError, UnicodeDecodeError):
        return {"observation_failed": "invalid output"}


def test_failure_observation_keeps_bounded_facts_and_redacts_paths(tmp_path):
    _json(tmp_path / "read-attempt.json", {
        "phase": "outcome", "dispatch": "possibly dispatched",
        "facts": {"status": "failure", "callback_started": 1, "callback_completed": 0,
                  "initial_binding_checked": True, "terminal_binding_checked": True,
                  "relay_closed": True, "unrelated": "not emitted"},
    })
    with sqlite3.connect(tmp_path / "read.sqlite") as db:
        db.execute("CREATE TABLE events (seq INTEGER, kind TEXT, payload TEXT)")
        db.execute("INSERT INTO events VALUES (1, ?, ?)",
                   ("NodeFailed", json.dumps({"error_type": "ContractViolation",
                                              "error": "failed at /synthetic/private/file"})))
        db.execute("INSERT INTO events VALUES (2, ?, ?)", ("RunFailed", "not emitted"))

    def local_python(argv, **kwargs):
        return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", argv[-2], argv[-1]],
                              **kwargs)

    observed = _failure_observation(str(tmp_path), local_python)
    assert observed["attempt"]["dispatch"] == "possibly dispatched"
    assert observed["attempt"]["facts"]["callback_completed"] == 0
    assert observed["event_kinds"] == ["NodeFailed", "RunFailed"]
    assert observed["node_failures"] == [{"error_type": "ContractViolation",
                                          "error": "failed at <path>"}]
    assert "not emitted" not in json.dumps(observed)


def test_collector_diagnostic_reports_caught_location_without_exception_text():
    def local_python(argv, **kwargs):
        return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", *argv[9:]], **kwargs)

    source = ('def main(argv):\n    try:\n        raise ValueError("PRIVATE")\n'
              '    except ValueError:\n        return 1\n')
    observed = _collector_diagnostic(source, [], local_python)
    assert observed == {"status": 1, "exceptions": [["main", 3, "ValueError"]], "files": {}}
    assert "PRIVATE" not in json.dumps(observed)


def test_collector_diagnostic_reports_only_fixed_file_custody_booleans(tmp_path):
    def local_python(argv, **kwargs):
        return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", *argv[9:]], **kwargs)

    (tmp_path / "read.sqlite").write_bytes(b"fixture")
    observed = _collector_diagnostic("def main(argv): return 1\n",
                                     ["--run-root", str(tmp_path)], local_python)
    assert observed["files"]["read.sqlite"]["exists"] is True
    assert observed["files"]["read.sqlite"]["regular"] is True
    assert observed["files"]["read.sqlite"]["singlelink"] is True
    assert observed["files"]["read.sqlite"]["size_within_bound"] is True
    assert observed["files"]["read.sqlite-wal"]["exists"] is False
    assert observed["files"]["read.sqlite-wal"]["regular"] is None
    assert str(tmp_path) not in json.dumps(observed)


@pytest.mark.skipif(sys.platform != "linux", reason="requires the disposable Linux foundation")
@pytest.mark.parametrize("abort_after_activation", [False, True], ids=["accept", "abort"])
def test_generated_phases_carry_actual_receipts_through_withdrawal(
    tmp_path, monkeypatch, abort_after_activation,
):
    fixture = os.environ.get("M8_CLAUDE_REHEARSAL_BINDINGS")
    if not fixture:
        if os.environ.get("M8_CLAUDE_REHEARSAL_REQUIRED"):
            pytest.fail("required Claude rehearsal bindings are absent")
        pytest.skip("the pre-provisioned Claude rehearsal foundation is absent")
    record = json.loads(Path(fixture).read_bytes())
    case = "abort" if abort_after_activation else "accept"
    record["namespace"] += "-" + case
    for key in ("R", "RUN", "AUTH", "ACQ"):
        record["values"][key] += "-" + case
    record["values"]["QUAL"] = record["values"]["RUN"] + "/qualify.json"
    for key in ("READ_KEY", "AUTHORIZATION_ID"):
        record["values"][key] += "-" + case
    assert record["values"]["RUN"] == "/var/lib/m8-cr-run-" + case
    bindings = commands.Bindings.from_dict(record)
    assert bindings.values["EXPECTED_BOOT"] == (
        Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    )
    evidence, captures = tmp_path / "evidence", tmp_path / "captures"
    evidence.mkdir()
    captures.mkdir()
    revision = commands.operator_revision()
    original_run = subprocess.run
    operator_home = Path("/home/runner")
    assert os.getuid() == operator_home.stat().st_uid

    def local_transport(argv, **kwargs):
        # Preserve the exact remote shell program and run it with its real HOME,
        # uid and cwd. SCP is a byte-preserving install into that same directory.
        if argv[0] == session.SSH:
            assert argv[-2] == TARGET
            return original_run(["/usr/bin/env", "-i",
                                 "HOME=/home/runner", "PATH=/usr/bin:/bin", "LANG=C.UTF-8",
                                 "/bin/sh", "-c", argv[-1]], **kwargs)
        assert argv[0] == session.SCP and argv[-1].startswith(TARGET + ":")
        directory = argv[-1].split(":", 1)[1]
        assert directory.endswith("/") and "/" not in directory[:-1]
        assert argv[1:2 + len(session.ssh_options(ALIAS))] == ["-q", *session.ssh_options(ALIAS)]
        files = argv[2 + len(session.ssh_options(ALIAS)):-1]
        assert files
        for source in files:
            result = original_run(["/usr/bin/install", "-m", "0600", source,
                                   str(operator_home / directory / Path(source).name)], **kwargs)
            if result.returncode:
                return result
        return result

    monkeypatch.setattr(session.subprocess, "run", local_transport)
    # The CLI remains a separate real interpreter; bypass only the transport
    # adapter when invoking it from this process.
    def cli(*args: str) -> dict:
        monkeypatch.setattr(session.subprocess, "run", original_run)
        try:
            return _cli(*args)
        finally:
            monkeypatch.setattr(session.subprocess, "run", local_transport)

    def build(phase: str, output: Path) -> tuple[str, Path]:
        value_path = tmp_path / (phase + "-bindings.json")
        _json(value_path, record)
        made = cli("compile", "--phase", phase, "--bindings", str(value_path),
                   "--evidence", str(evidence), "--out", str(output),
                   "--operator-revision", revision)
        assert made["phase"] == phase
        return made["package_manifest"], output

    def execute(phase: str, manifest: str, package: Path) -> None:
        pins, actual = commands.package_checked(package, manifest, revision)
        grant = {"schema_version": 1, "phase": phase, "package_manifest": manifest,
                 "operator_revision": revision, "controller_commit": actual.controller_commit,
                 "bindings_sha256": pins["bindings_sha256"], "boot": actual.values["EXPECTED_BOOT"],
                 "target_sha256": commands.sha((TARGET + "\0" + ALIAS).encode()),
                 "checks": {name: True for name in (
                     commands.COMMON_CHECKS | commands.PHASES[phase].checks)}}
        grant_path = tmp_path / (phase + "-grant.json")
        _json(grant_path, grant)
        status = session.one_phase(package, manifest, revision, evidence, grant_path, captures,
                                   TARGET, ALIAS, commands.sha(grant_path.read_bytes()))
        if not commands.completed_zero(status):
            observations = {}
            if status["completed"] and status["returncode"] in (0, 1) and not status["timed_out"]:
                parts = commands.PHASES[phase].outputs
                for part in ("stderr", "stdout", "result"):
                    if part not in parts:
                        continue
                    try:
                        readback_status = session.readback(
                            package, manifest, revision, evidence, part, captures, TARGET, ALIAS,
                        )
                        _, _, _, slot = commands.readback_spec(actual, phase, part, manifest)
                        raw = commands.bounded(evidence / slot, parts[part][2], empty=True)
                        safe = re.sub(r"/[^\s:'\"]+", "<path>", raw.decode(errors="replace"))
                        observations[part] = {"status": readback_status, "bytes": safe[:2048]}
                    except Exception as error:
                        name = phase + "-readback-" + part
                        details = {"readback_error": type(error).__name__}
                        for suffix in ("status.json", "stderr"):
                            capture_path = captures / (name + "." + suffix)
                            if capture_path.is_file():
                                with capture_path.open("rb") as stream:
                                    raw = stream.read(1024)
                                safe = re.sub(r"/[^\s:'\"]+", "<path>",
                                              raw.decode(errors="replace"))
                                details[suffix] = safe[:1024]
                        observations[part] = details
            if phase == "read":
                observations["fake_run"] = _failure_observation(actual.values["RUN"], original_run)
            outer = (evidence / (phase + ".stderr")).read_bytes().decode(errors="replace")
            outer = re.sub(r"/[^\s:'\"]+", "<path>", outer)[:2048]
            pytest.fail(f"phase={phase} status={status} outer_stderr={outer!r} "
                        f"readbacks={observations!r}")
        for part in commands.PHASES[phase].outputs:
            assert commands.completed_zero(session.readback(package, manifest, revision, evidence,
                                                             part, captures, TARGET, ALIAS))
        checked = cli("check", "--package", str(package), "--manifest", manifest,
                      "--evidence", str(evidence), "--operator-revision", revision)
        assert checked == {"phase": phase, "checked": True}

    cleanup = None
    for phase in commands.PHASES:
        if phase == "activate":
            cleanup = build("withdraw-after", evidence / "cleanup-package")
        if phase == "withdraw-after":
            assert cleanup is not None
            manifest, package = cleanup
        else:
            manifest, package = build(phase, tmp_path / ("package-" + phase))
        execute(phase, manifest, package)
        values = record["values"]
        if phase == "activate" and abort_after_activation:
            # The actual activation completed. Damage its predecessor receipt,
            # demonstrate that a later compile refuses, and use the previously
            # compiled withdrawal without minting or dispatching a READ.
            assert (evidence / "activation-may-have-completed.json").is_file()
            receipt = evidence / "qualify.stdout"
            assert receipt.read_bytes() == commands.PHASES["qualify"].stdout
            active_bindings = commands.Bindings.from_dict(record)
            assert commands.compile_phase(active_bindings, "mint", evidence)
            receipt.write_bytes(b"damaged receipt\n")
            with pytest.raises(commands.Refused):
                commands.compile_phase(active_bindings, "mint", evidence)
            assert cleanup is not None
            cleanup_manifest, cleanup_package = cleanup
            assert ("readonly GENERATION=" + values["GENERATION"] + "\n").encode() in (
                cleanup_package / "phase.sh"
            ).read_bytes()
            execute("withdraw-after", cleanup_manifest, cleanup_package)
            assert not (evidence / "authorization-candidate.json").exists()
            assert not (evidence / "read-status.json").exists()
            break
        if phase == "reload-check":
            digest_path = evidence / "reload.digest"
            actual_digest = digest_path.read_bytes()
            digest_path.write_bytes(b"sha256:" + b"0" * 64 + b"\n")
            try:
                with pytest.raises(commands.Refused):
                    commands.compile_phase(commands.Bindings.from_dict(record), "qualify", evidence)
            finally:
                digest_path.write_bytes(actual_digest)
        elif phase == "qualify-check":
            values["Q"] = (evidence / "checker.stdout").read_text().strip()
            values["QUAL_RAW_SHA256"] = commands.sha((evidence / "qualification.json").read_bytes())
        elif phase == "inventory":
            floor = json.loads((evidence / "inventory.json").read_bytes())["highest_generation"]
            values["FLOOR"], values["GENERATION"] = str(floor), str(floor + 1)
        elif phase == "publish":
            values["SEALED_SHA256"] = commands.sha(
                (evidence / "published-sealed.json").read_bytes())
        elif phase == "mint":
            values["CANDIDATE_SHA256"] = commands.sha(
                (evidence / "authorization-candidate.json").read_bytes())
        elif phase == "candidate-pins":
            approval = {"schema": 1, "owner_decision": "https://github.com/sushiHex/constructicon/issues/77#issuecomment-1",
                        "procedure_sha256": commands.DOC_SHA,
                        "source_c": record["controller_commit"],
                        "acceptance": commands.ACCEPTANCE}
            _json(evidence / "owner-approval.json", approval)
            values["OWNER_APPROVAL_SHA256"] = commands.sha(
                (evidence / "owner-approval.json").read_bytes())
    if not abort_after_activation:
        assert (evidence / "read-status.json").read_bytes() == b'{"status": "succeeded"}\n'
    assert (evidence / "withdraw-after.command.stdout").read_bytes() == b"withdrawn-checked\n"
    if not abort_after_activation:
        from constructicon.core.qualification import QualificationAuthorization

        authorization = QualificationAuthorization.model_validate_json(
            (evidence / "authorization-candidate.json").read_bytes()
        )
        assert authorization.authorization_id == values["AUTHORIZATION_ID"]
        collector = (ROOT / "scripts/ops/read_attempt_evidence.py").read_text(encoding="utf-8")
        collector_arguments = ["--run-root", values["RUN"], "--authorization-id",
                               authorization.authorization_id, "--run-id",
                               str(authorization.run_id), "--max-epoch", "1"]
        result = original_run(
            ["sudo", "-n", "-u", "m8-service", "/usr/bin/python3", "-I", "-S", "-B",
             "-c", collector, *collector_arguments],
            stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=30,
        )
        if result.returncode != 0:
            diagnostic = _collector_diagnostic(collector, collector_arguments, original_run)
            print("COLLECTOR_DIAGNOSTIC " + json.dumps(diagnostic, sort_keys=True))
            pytest.fail(f"collector returned {result.returncode}: "
                        f"{result.stdout[:32768]!r} {result.stderr[:4096]!r}")
        assert result.stderr == b""
        assert len(result.stdout) <= 32768
        report = json.loads(result.stdout)
        assert report["schema_version"] == 1
        assert report["attempt"]["state"] == "valid"
        assert report["attempt"]["partial"] is False
        assert report["attempt"]["phase"] == "outcome"
        assert report["attempt"]["dispatch"] == "completed"
        assert report["attempt"]["status"] == "success"
        assert report["attempt"]["callback_started"] == 1
        assert report["attempt"]["callback_completed"] == 1
        assert report["attempt"]["callback_observation"] is None
        assert report["journal"]["state"] == "valid"
        assert report["journal"]["partial"] is False
        assert report["journal"]["run_status"] == "succeeded"

        history = tmp_path / "metadata-history"
        history.mkdir()
        for source, name in ((evidence / "read-context.json", "read-context.json"),
                             (tmp_path / "read-bindings.json", "bindings.json"),
                             (evidence / "authorization-candidate.json",
                              "authorization-candidate.json")):
            (history / name).write_bytes(source.read_bytes())
        request = {
            "schema_version": 1,
            "retained": {
                "context_sha256": commands.sha((history / "read-context.json").read_bytes()),
                "bindings_sha256": commands.sha((history / "bindings.json").read_bytes()),
                "authorization_sha256": commands.sha(
                    (history / "authorization-candidate.json").read_bytes()),
                "controller_commit": record["controller_commit"],
                "boot": values["EXPECTED_BOOT"], "run_root": values["RUN"],
                "authorization_id": authorization.authorization_id,
                "run_id": str(authorization.run_id), "max_epoch": 1,
            },
            "fresh": {"boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                      "target": TARGET, "alias": ALIAS, "namespace": "read-rehearsal-accept",
                      "drift_sha256": record["pins"]["drift_sha256"],
                      "drift_stdout": record["pins"]["drift_stdout"]},
        }
        request_path = tmp_path / "metadata-request.json"
        _json(request_path, request)
        package, metadata_captures = tmp_path / "metadata-package", tmp_path / "metadata-captures"
        metadata_captures.mkdir()
        metadata_revision = metadata.revision()
        manifest = metadata.compile_package(request_path, history, package, metadata_revision)
        status = metadata.transport(package, manifest, metadata_revision, history,
                                    metadata_captures)
        assert commands.completed_zero(status), (
            status, (metadata_captures / "metadata-native.stdout").read_bytes(),
            (metadata_captures / "metadata-native.stderr").read_bytes(),
        )
        checked = metadata.check(package, manifest, metadata_revision, history, metadata_captures)
        assert checked["collection_checked"] is True
        assert checked["observation"] == report
