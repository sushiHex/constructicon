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
from scripts.ops import claude_read_window as window_entry
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


def _installation(fixture_record):
    return {"schema_version": 2,
            **{key: fixture_record[key] for key in (
                "controller_commit", "controller_workspace", "launch_workspace", "mode", "pins",
            )},
            "operator_home": "/home/runner", "actor": fixture_record["values"]["ACTOR"]}


def test_rehearsal_installation_passes_actual_prepare_bindings(tmp_path):
    from tests.test_claude_read_session import binding_record

    fixture = binding_record()
    installation = tmp_path / "installation.json"
    output = tmp_path / "bindings.json"
    _json(installation, _installation(fixture))
    assert _cli(
        "prepare-bindings", "--installation", str(installation),
        "--namespace", "portable", "--out", str(output),
        "--operator-revision", commands.operator_revision(),
    ) == {"bindings_sha256": commands.sha(output.read_bytes())}
    bindings = commands.Bindings.from_file(output)
    assert bindings.mode == "subscription"
    assert bindings.values["EXPECTED_BOOT"] == "UNREVIEWED"


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
        assert argv[:9] == ["sudo", "-n", "-u", "m8-service", "/usr/bin/python3",
                            "-I", "-S", "-B", "-c"] and len(argv) == 11
        assert argv[-1] == str(tmp_path) and kwargs["stdin"] is subprocess.DEVNULL
        return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", argv[9], argv[10]],
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
        assert argv[:9] == ["sudo", "-n", "-u", "m8-service", "/usr/bin/python3",
                            "-I", "-S", "-B", "-c"]
        assert len(argv) >= 11 and kwargs["stdin"] is subprocess.DEVNULL
        return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", *argv[9:]], **kwargs)

    source = ('def main(argv):\n    try:\n        raise ValueError("PRIVATE")\n'
              '    except ValueError:\n        return 1\n')
    observed = _collector_diagnostic(source, [], local_python)
    assert observed == {"status": 1, "exceptions": [["main", 3, "ValueError"]], "files": {}}
    assert "PRIVATE" not in json.dumps(observed)


def test_collector_diagnostic_reports_only_fixed_file_custody_booleans(tmp_path):
    def local_python(argv, **kwargs):
        assert argv[:9] == ["sudo", "-n", "-u", "m8-service", "/usr/bin/python3",
                            "-I", "-S", "-B", "-c"]
        assert len(argv) >= 11 and kwargs["stdin"] is subprocess.DEVNULL
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
    fixture_record = json.loads(Path(fixture).read_bytes())
    case = "abort" if abort_after_activation else "accept"
    revision = commands.operator_revision()
    installation = _installation(fixture_record)
    installation_path = tmp_path / "installation.json"
    _json(installation_path, installation)
    binding_path = tmp_path / "initial-bindings.json"
    prepared = _cli("prepare-bindings", "--installation", str(installation_path),
                    "--namespace", case, "--boot", fixture_record["values"]["EXPECTED_BOOT"],
                    "--out", str(binding_path), "--operator-revision", revision)
    assert prepared == {"bindings_sha256": commands.sha(binding_path.read_bytes())}
    record = json.loads(binding_path.read_bytes())
    assert record["values"]["RUN"] == "/var/lib/m8-cr-run-" + case
    bindings = commands.Bindings.from_dict(record)
    assert bindings.values["EXPECTED_BOOT"] == (
        Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    original_run = subprocess.run
    # A synthetic owner decision is an explicit input to this disposable test only.
    approval_path = evidence / "owner-approval.json"
    prepared_approval = _cli(
        "prepare-owner-approval", "--controller", record["controller_commit"],
        "--owner-decision", "https://github.com/sushiHex/constructicon/issues/77#issuecomment-1",
        "--out", str(approval_path), "--operator-revision", revision,
    )
    assert prepared_approval == {"owner_approval_sha256": commands.sha(approval_path.read_bytes())}
    operator_home = Path("/home/runner")
    assert os.getuid() == operator_home.stat().st_uid

    def local_transport(argv, **kwargs):
        # Preserve the exact remote shell program and run it with its real HOME,
        # uid and cwd. SCP is a byte-preserving install into that same directory.
        argv = list(argv)
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

    window = window_entry.ReadWindow.create(
        binding_path, evidence, tmp_path / "window", revision, TARGET, ALIAS,
        owner_approval_sha256=commands.sha(approval_path.read_bytes()),
    )

    def execute(cleanup: bool = False) -> dict:
        request = window.prepare_next(cleanup=cleanup)
        phase, manifest = request["phase"], request["manifest"]
        package = Path(request["package"])
        pins, actual = commands.package_checked(package, manifest, revision)
        grant = {"schema_version": 1, "phase": phase, "package_manifest": manifest,
                 "operator_revision": revision, "controller_commit": actual.controller_commit,
                 "bindings_sha256": pins["bindings_sha256"], "boot": actual.values["EXPECTED_BOOT"],
                 "target_sha256": commands.sha((TARGET + "\0" + ALIAS).encode()),
                 "checks": {name: True for name in request["checks"]}}
        grant_path = tmp_path / (phase + "-grant.json")
        _json(grant_path, grant)
        try:
            result = window.advance(grant_path, commands.sha(grant_path.read_bytes()),
                                    cleanup=cleanup, external=local_transport)
        except Exception as error:
            # Inspect only already-retained captures; never issue another readback.
            captures = window.work / phase / "captures"
            observations = {}
            names = [phase + "-native"] + [
                phase + "-readback-" + part for part in commands.PHASES[phase].outputs
            ]
            for name in names:
                for suffix in ("status.json", "stdout", "stderr"):
                    path = captures / (name + "." + suffix)
                    if path.is_file():
                        with path.open("rb") as stream:
                            raw = stream.read(2048)
                        observations[name + "." + suffix] = re.sub(
                            r"/[^\s:'\"]+", "<path>", raw.decode(errors="replace")
                        )
            if phase == "read":
                observations["fake_run"] = _failure_observation(actual.values["RUN"], original_run)
            pytest.fail(f"phase={phase} error={type(error).__name__} "
                        f"retained={observations!r}")
        assert result["phase"] == phase and result["checked"] is True
        assert result["external"]["mode"] == "substituted"
        assert result["external"]["declared"] == result["external"]["observed"]
        return result

    for phase in commands.PHASES:
        result = execute()
        assert result["phase"] == phase
        binding_path = window.work / phase / "next-bindings.json"
        record = json.loads(binding_path.read_bytes())
        values = record["values"]
        if phase == "activate" and abort_after_activation:
            assert (evidence / "activation-may-have-completed.json").is_file()
            receipt = evidence / "qualify.stdout"
            assert receipt.read_bytes() == commands.PHASES["qualify"].stdout
            active_bindings = commands.Bindings.from_dict(record)
            assert commands.compile_phase(active_bindings, "mint", evidence)
            receipt.write_bytes(b"damaged receipt\n")
            with pytest.raises(commands.Refused):
                window.prepare_next()
            cleanup_package = evidence / "cleanup-package"
            assert ("readonly GENERATION=" + values["GENERATION"] + "\n").encode() in (
                cleanup_package / "phase.sh"
            ).read_bytes()
            assert execute(cleanup=True)["phase"] == "withdraw-after"
            assert not (evidence / "authorization-candidate.json").exists()
            assert not (evidence / "read-status.json").exists()
            break
        if phase in ("qualify-check", "inventory"):
            damaged = (evidence / "checker.stdout" if phase == "qualify-check" else
                       evidence / "inventory-readback-inventory-context.json")
            saved = damaged.read_bytes()
            if phase == "qualify-check":
                damaged.write_bytes(b"sha256:" + b"0" * 64 + b"\n")
            else:
                context = json.loads(saved)
                context["part"] = "stderr"
                _json(damaged, context)
            try:
                with pytest.raises(commands.Refused):
                    window.prepare_next()
            finally:
                damaged.write_bytes(saved)
        if phase == "candidate-pins":
            approved = window.config["owner_approval_sha256"]
            window.config["owner_approval_sha256"] = "0" * 64
            try:
                with pytest.raises(commands.Refused):
                    window.prepare_next()
            finally:
                window.config["owner_approval_sha256"] = approved
        if phase == "reload-check":
            digest_path = evidence / "reload.digest"
            actual_digest = digest_path.read_bytes()
            digest_path.write_bytes(b"sha256:" + b"0" * 64 + b"\n")
            try:
                with pytest.raises(commands.Refused):
                    window.prepare_next()
            finally:
                digest_path.write_bytes(actual_digest)
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
                             (window.work / "read" / "package" / "bindings.json", "bindings.json"),
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
        # Metadata uses the session transport too; restrict this substitution to
        # the call and prove every declared staging operation passed through it.
        metadata_name = request["fresh"]["namespace"] + "-metadata-" + manifest[:16]
        expected = session.staging_commands(package, manifest, metadata_name, TARGET, ALIAS)
        substituted = []

        def metadata_transport(argv, **kwargs):
            assert len(substituted) < len(expected)
            assert tuple(argv) == tuple(expected[len(substituted)])
            assert kwargs["stdin"] is subprocess.DEVNULL
            substituted.append(tuple(argv))
            return local_transport(argv, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(session.subprocess, "run", metadata_transport)
            status = metadata.transport(package, manifest, metadata_revision, history,
                                        metadata_captures)
        assert len(substituted) == len(expected) == 4
        assert commands.completed_zero(status), (
            status, (metadata_captures / "metadata-native.stdout").read_bytes(),
            (metadata_captures / "metadata-native.stderr").read_bytes(),
        )
        checked = metadata.check(package, manifest, metadata_revision, history, metadata_captures)
        assert checked["collection_checked"] is True
        assert checked["observation"] == report
