"""Offline composition, using the immutable development #393 producer.

Git preparation, entry result publication and joined shutdown are real. Host
custody/assembly and process containment are the existing portable fixture seams;
the T5 subprocess executes the actual inspector, never a vendor binary. This
proves local glue, not installation, qualification or authority to spend.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import m8_procedure_package as package

from constructicon.api import _maintenance_source as source_module
from constructicon.api import maintenance_entry as entry
from constructicon.api.plan_manifest_application import CHANNEL_STORED_REPLY
from constructicon.core.run import RunStatus
from constructicon.substrate.executors import operator_store
from tests.api import test_channel_reply_entry as producer
from tests.operator_store_world import StoreWorld
from tests.test_m8_operator_commands import PYTHON_PROGRAM, _bash

concrete_application = producer.concrete_application
portable_binding = producer.portable_binding
layout = producer.layout
ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs/plans/handoffs/maintenance-channel-reply-session.md"
CHANNEL = producer.CHANNEL


def _fences(document, heading, language="bash"):
    return [body for kind, body in package.fences(package.section(
        document.read_bytes().decode(), heading)) if kind == language]


def _checker(heading):
    programs = PYTHON_PROGRAM.findall("\n".join(_fences(DOCUMENT, heading)))
    assert len(programs) == 1
    return programs[0].replace(
        'sys.path.insert(0, "/opt/constructicon-m8-controller")',
        f"sys.path.insert(0, {(ROOT / 'src').as_posix()!r})",
    )


def _t5(tmp_path, expected, argv):
    tmp_path.mkdir()
    transport, = _fences(DOCUMENT.parent / "M8-maintenance-q12-continuation.md",
                         "Q6: transport T5", "python")
    script = tmp_path / "transport.py"
    script.write_bytes(transport.encode())
    expectation = tmp_path / "expected.json"
    expectation.write_bytes(expected.encode())
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(script), str(tmp_path / "capture"),
         str(expectation), "--", *argv],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=False,
    )
    return result, json.loads((tmp_path / "capture.status.json").read_bytes())


def _step(name):
    return next(step for step in package.assemble(DOCUMENT, template=True) if step.name == name)


def test_actual_compiler_checks_template_and_refuses_normal_package(tmp_path):
    command = [sys.executable, "-I", "-S", "-B", str(ROOT / "scripts/m8_procedure_package.py")]
    check = subprocess.run([*command, "check", str(DOCUMENT), "--template"],
                           stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert (check.returncode, check.stderr) == (0, b"")
    assert check.stdout.strip() == b"composition-checked 15 steps"
    destination = tmp_path / "unreleased"
    refusal = subprocess.run([*command, "build", str(DOCUMENT), str(destination)],
                             stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert refusal.returncode == 1 and b"unreviewed placeholder remains" in refusal.stderr
    assert not destination.exists()
    template = tmp_path / "template"
    built = subprocess.run([*command, "build", str(DOCUMENT), str(template), "--template"],
                           stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert (built.returncode, built.stderr) == (0, b"")
    for line in (template / "MANIFEST.sha256").read_text().splitlines():
        digest, name = line.split("  ")
        raw = (template / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest and b"\r" not in raw
    # Syntax proof only; no unresolved source declaration is executed.
    for path in template.glob("*.sh"):
        parsed = subprocess.run([_bash(), "-n", path.as_posix()],
                                stdin=subprocess.DEVNULL, capture_output=True, check=False)
        assert (parsed.returncode, parsed.stdout, parsed.stderr) == (0, b"", b""), path.name


def test_filled_private_copy_builds_a_complete_normal_package(tmp_path):
    """Synthetic compile-only data: never execute/upload this package."""
    text = DOCUMENT.read_bytes().decode()
    declarations = {
        "C": "a" * 40, "BASE": "b" * 40, "TARGET_SHA256": "1" * 64,
        "BUNDLE_SHA256": "2" * 64, "BUNDLE_SIZE": "100", "BUNDLE": "/synthetic/source.bundle",
        "W": "/synthetic/g15/session", "K": "synthetic-store",
        "W_PRIOR": "/synthetic/g14/session", "GEN": "g15", "GEN_PRIOR": "g14",
        "GENERATION": "15", "FLOOR": "14", "S": "/synthetic/state",
        "APP": "/synthetic/application", "A": "/synthetic/authority.json",
        "ID": "synthetic-authorization", "ACTOR": "operator:synthetic", "KEY": "synthetic-key",
        "REPORT": "/synthetic/report", "SOURCE_UPLOAD": "/synthetic/upload.bundle",
        "QUIESCENCE_CAPTURE": "/synthetic/quiescence.stdout",
        "QUIESCENCE_STDERR": "/synthetic/quiescence.stderr",
    }
    for name, value in declarations.items():
        text, count = re.subn(rf"^{name}=UNREVIEWED$", f"{name}={shlex.quote(value)}",
                              text, flags=re.M)
        assert count == 1, name
    for source in package.composition(text)["sources"].values():
        before = "path = " + json.dumps(source["path"])
        after = "path = " + json.dumps((DOCUMENT.parent / source["path"]).as_posix())
        assert text.count(before) == 1
        text = text.replace(before, after)
    private = tmp_path / "synthetic-only.md"
    private.write_bytes(text.encode())
    values = {
        "EXPECTED_BOOT": "00000000-0000-0000-0000-000000000001",
        "DRIFT_STDOUT_HEX": b"Synthetic drift observation only.\n".hex(),
        "DRIFT_TOOL_SHA256": "3" * 64, "PREVIEW_SHA256": "4" * 64,
        "RUN_ID": "run-" + "5" * 32,
    }
    measured = tmp_path / "synthetic-values-only.toml"
    measured.write_bytes(("\n".join(f"{key} = {json.dumps(value)}"
                                    for key, value in values.items()) + "\n").encode())
    command = [sys.executable, "-I", "-S", "-B", str(ROOT / "scripts/m8_procedure_package.py"),
               "build", str(private)]
    # The former recipe filled every declaration but omitted label metadata.
    missing = tmp_path / "missing-labels"
    refused = subprocess.run([*command, str(missing), "--values", str(measured)],
                             stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert refused.returncode == 1 and b"['g14', 'g15']" in refused.stderr
    assert not missing.exists()
    recipe = package.section(DOCUMENT.read_bytes().decode(), "Private specialization")
    assert "labels.current" in recipe, "the private recipe must admit literal label metadata"
    declaration = "labels = {current = [], historical = []}"
    assert text.count(declaration) == 1
    private.write_bytes(text.replace(declaration,
        'labels = {current = ["g15"], historical = []}').encode())
    missing_prior = tmp_path / "missing-prior"
    refused = subprocess.run([*command, str(missing_prior), "--values", str(measured)],
                             stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert refused.returncode == 1 and b"['g14']" in refused.stderr
    assert not missing_prior.exists()
    private.write_bytes(text.replace(declaration,
        'labels = {current = ["g14", "g15"], historical = []}').encode())
    out = tmp_path / "synthetic-normal-package"
    built = subprocess.run([*command, str(out), "--values", str(measured)],
                           stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert (built.returncode, built.stderr) == (0, b"")
    manifest = (out / "MANIFEST.sha256").read_bytes()
    assert built.stdout.strip() == hashlib.sha256(manifest).hexdigest().encode()
    steps = package.assemble(private, values=values)
    assert len(steps) == 15 and not any(step.waiting for step in steps)
    expected_files = {step.name + suffix for step in steps
                      for suffix in (".sh", ".expected.json")}
    assert {path.name for path in out.iterdir()} == expected_files | {"MANIFEST.sha256"}
    assert {line.split("  ")[1] for line in manifest.decode().splitlines()} == expected_files
    for line in manifest.decode().splitlines():
        digest, name = line.split("  ")
        raw = (out / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest and b"\r" not in raw
        assert b"UNREVIEWED" not in raw
    for step in steps:
        assert (out / (step.name + ".sh")).read_bytes() == step.text.encode()
        assert (out / (step.name + ".expected.json")).read_bytes() == step.expected().encode()
        parsed = subprocess.run([_bash(), "-n", (out / (step.name + ".sh")).as_posix()],
                                stdin=subprocess.DEVNULL, capture_output=True, check=False)
        assert (parsed.returncode, parsed.stdout, parsed.stderr) == (0, b"", b""), step.name

    check = [sys.executable, "-I", "-B",
             str(ROOT / "scripts/ops/check_native_state_path.py")]
    for path in (private, out / "cr-preflight.sh"):
        accepted = subprocess.run([*check, str(path)], stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, check=False)
        assert (accepted.returncode, accepted.stdout, accepted.stderr) == (
            0, "native-state-socket-checked: 87 <= 107 bytes\n", "",
        )
    long_state = "/synthetic/" + "a" * 54
    raw = private.read_bytes()
    assert raw.count(b"S=/synthetic/state\n") == 1
    private.write_bytes(raw.replace(b"S=/synthetic/state\n", f"S={long_state}\n".encode()))
    long_package = tmp_path / "long-state-package"
    compiled = subprocess.run([*command, str(long_package), "--values", str(measured)],
                              stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert (compiled.returncode, compiled.stderr) == (0, b"")
    for path in (private, long_package / "cr-preflight.sh"):
        refused = subprocess.run([*check, str(path)], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, check=False)
        assert (refused.returncode, refused.stdout, refused.stderr) == (
            1, "", "native-state-socket-too-long: 136 > 107 bytes\n",
        )


def test_reused_capture_and_lane_bytes_remain_exact():
    old, = _fences(DOCUMENT.parent / "M8-maintenance-g11-continuation.md",
                   "C10: one application, independent statuses and closed outcome")
    current, = _fences(DOCUMENT, "Application capture")
    assert current == old.replace("g11-application-capture", "channel-reply-application-capture")
    steps = {step.name: step for step in package.assemble(DOCUMENT, template=True)}
    for name, heading in (("cr-qualification", "L1: qualification boundary"),
                          ("cr-controls", "L2: H7 controls"),
                          ("cr-refresh", "L3: explicit refresh")):
        lane, = _fences(DOCUMENT.parent / "M8-maintenance-lane-output.md", heading)
        assert lane in steps[name].text
    lane_parents = [re.findall(r'^LANES="([^"]+)"$', steps[name].text, re.M)
                    for name in ("cr-qualification", "cr-controls", "cr-refresh")]
    assert all(len(paths) == 1 for paths in lane_parents)
    assert len({paths[0] for paths in lane_parents}) == 3


@pytest.mark.parametrize("valid", [True, False], ids=["inherited-receipt", "wrong-parent"])
def test_withdrawal_cli_producer_and_receipt_join_before_return(
    tmp_path, monkeypatch, capsys, valid,
):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    inherited = world.install_inheritance(monkeypatch, parent=os.getppid())
    entered, waited = [], []
    program = _checker("Store withdrawal")

    class ServiceChild:
        def __init__(self, argv, **kwargs):
            # Replace only privilege/process launch; retain the real root CLI,
            # durable withdrawal, inherited receipt decoder and body through exit.
            assert argv[:3] == ["/usr/bin/python3", "-c", program]
            assert kwargs["user"] == kwargs["group"] == 1000
            assert kwargs["extra_groups"] == [] and kwargs["close_fds"] is True
            fd, = kwargs["pass_fds"]
            assert world.holder == fd
            entered.append(json.loads(world.metadata["active.json"]))
            world.inherited[fd] = world.lock
            world.fdinfos[fd] = world.fdinfo(world.flock_line(
                os.getppid() if valid else os.getpid()))
            with monkeypatch.context() as child:
                child.setattr(sys, "argv", ["-c", *argv[3:]])
                try:
                    exec(program, {"__name__": "__main__"})
                except Exception:
                    self.returncode = 1
                else:
                    self.returncode = 0

        def wait(self):
            waited.append(True)
            return self.returncode

    monkeypatch.setattr(operator_store, "_service", lambda name: (1000, 1000))
    monkeypatch.setattr(operator_store.subprocess, "Popen", ServiceChild)
    try:
        status = operator_store.main([
            "maintain", "--store-root", str(world.root), "--key", world.key,
            "--service", "m8-service", "--wait", "0", "--",
            "/usr/bin/python3", "-c", program,
        ])
        assert len(entered) == 1 and entered[0]["generation_floor"] == 1
        assert waited == [True] and world.holder is None
        assert status == (0 if valid else 1)
        output = capsys.readouterr()
        assert output.err == ""
        if valid:
            assert json.loads(output.out) == {"highest_generation": 1, "withdrawn": True}
        else:
            assert output.out == ""
        assert not world.credential_opens
    finally:
        os.close(inherited)


async def test_preparation_producer_flows_through_new_source_checker_and_t5(tmp_path, monkeypatch):
    bundle, base = await producer._bundle(tmp_path, producer.BASE)
    root = tmp_path / "application"
    def portable_custody(path):
        assert path.is_absolute() and path.resolve() == path and path.is_dir()
        assert path.is_relative_to(tmp_path)

    monkeypatch.setattr(source_module, "private_root", portable_custody)
    args = Namespace(command="prepare", root=root, bundle=bundle,
        bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(), base=base,
        target_ref="refs/heads/maintenance", task="channel-stored-reply")
    record = await entry._command(args)
    prepared = tmp_path / "source-prepared.json"
    prepared.write_bytes(json.dumps(record).encode())
    program = ("import sys;sys.stdout.reconfigure(newline=chr(10))\n"
               "print('drift-checked')\nprint('maintenance-bundle-transferred')\n"
               + _checker("Application preparation"))
    argv = [sys.executable, "-c", program, str(prepared), str(root), base,
            args.bundle_sha256, hashlib.sha256(producer.BASE).hexdigest()]
    accepted, status = _t5(tmp_path / "accept", _step("cr-prepare").expected(), argv)
    assert status == {"returncode": 0}
    assert (accepted.returncode, accepted.stdout, accepted.stderr) == (
        0, b"transport-step-checked 0\n", b"")
    refused, status = _t5(tmp_path / "refuse", _step("cr-prepare").expected(),
                          [*argv[:-1], "0" * 64])
    assert status["returncode"] != 0
    assert (refused.returncode, refused.stdout) == (1, b"transport-step-refused\n")


@CHANNEL
async def test_actual_preflight_preview_flows_through_channel_checker(
    concrete_application, tmp_path, monkeypatch,
):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    root = tmp_path / "preview"
    root.mkdir()

    async def source(path):
        assert path == root

    async def assembly(**kwargs):
        assert kwargs["authorization"] is None
        return SimpleNamespace(resources=resources, executor=SimpleNamespace(
            identity=SimpleNamespace(revision=executor.identity.revision,
                store=SimpleNamespace(operator_binding_digest="sha256:" + "1" * 64))))

    # The actual command producer is retained; only host assembly/custody is fake.
    monkeypatch.setattr(entry, "inspect_source", source)
    monkeypatch.setattr(entry, "assemble_maintenance", assembly)
    monkeypatch.setattr(entry, "SqliteJournal", lambda path: resources.journal)
    args = Namespace(command="preflight", root=root, session=root, sealed=root,
        qualification=root, state=root, launch_root=root, store_key="fake-key",
        authorization_id="operator-package", actor="operator:test", key="single-attempt")
    record = await entry._command(args)
    preview = root / "preflight.json"
    preview.write_bytes(json.dumps(record).encode())
    preview.chmod(0o600)
    # This fixture's authority uses refs/heads/main; the public preflight checker
    # deliberately selects maintenance. Substitute only that fixture locator.
    checker = _checker("Actual WRITE preflight").replace(
        'a.request.target_ref == "refs/heads/maintenance"',
        'a.request.target_ref == "refs/heads/main"',
    )
    if os.name == "nt":
        checker = "import os\nos.getuid=lambda: 0\n" + checker.replace(
            "assert info.st_uid == os.getuid() and info.st_mode & 0o077 == 0",
            "assert path.resolve().is_relative_to(Path(sys.argv[2]).resolve())")
        checker = checker.replace(
            'a.journal == sys.argv[2] + "/maintenance.sqlite"',
            'Path(a.journal) == Path(sys.argv[2]) / "maintenance.sqlite"',
        ).replace(
            'a.attempt_record == sys.argv[2] + "/maintenance-attempt.json"',
            'Path(a.attempt_record) == Path(sys.argv[2]) / "maintenance-attempt.json"',
        )
    argv = [sys.executable, "-c", "import sys;sys.stdout.reconfigure(newline=chr(10))\n"
            "print('drift-checked')\n" + checker,
            str(preview), str(root), args.authorization_id, args.actor, args.key,
            resources.request.base_commit, resources.request.target_sha256, "0", "0"]
    accepted, status = _t5(tmp_path / "preview-accept", _step("cr-preflight").expected(), argv)
    assert (accepted.returncode, accepted.stdout, accepted.stderr) == (
        0, b"transport-step-checked 0\n", b"")
    assert status == {"returncode": 0}
    refused, status = _t5(tmp_path / "preview-refuse", _step("cr-preflight").expected(),
                          [*argv[:-1], "1"])
    assert status["returncode"] == 1
    assert (refused.returncode, refused.stdout) == (1, b"transport-step-refused\n")
    # Retain the actual producer's preview bytes. Substitute root-file custody
    # only, keeping the production two-case authority reader and digest check.
    custody = (
        f"import sys;sys.path.insert(0,{(ROOT / 'src').as_posix()!r})\n"
        "sys.stdout.reconfigure(newline=chr(10))\n"
        "from pathlib import Path\n"
        "from constructicon.api._maintenance_source import read_bounded\n"
        "from constructicon.substrate.executors import maintenance\n"
        "def fixture_custody(path):\n"
        f"    assert path.resolve() == Path({str(preview)!r}).resolve()\n"
        "    return read_bounded(path,8192)\n"
        "maintenance._read_authorization_bytes=fixture_custody\n"
    )
    # The RunId is computed by the typed producer, never guessed from the preview.
    model = CHANNEL_STORED_REPLY.authorization_model.model_validate(record)
    retained_args = [sys.executable, "-c", custody + _checker("Retained authorization"),
                     str(preview), hashlib.sha256(preview.read_bytes()).hexdigest(),
                     str(model.run_id)]
    retained, status = _t5(tmp_path / "retained-accept",
                           _step("cr-authorization-retained").expected(), retained_args)
    assert status == {"returncode": 0}
    assert (retained.returncode, retained.stdout, retained.stderr) == (
        0, b"transport-step-checked 0\n", b"")
    wrong = [*retained_args]
    wrong[-2] = "0" * 64
    retained, status = _t5(tmp_path / "retained-refuse",
                           _step("cr-authorization-retained").expected(), wrong)
    assert status["returncode"] != 0
    assert (retained.returncode, retained.stdout) == (1, b"transport-step-refused\n")


@CHANNEL
@pytest.mark.parametrize("change", [True, False], ids=["contribution", "successful-noop"])
async def test_joined_entry_producer_and_real_inspector_cross_t5(
    concrete_application, layout, tmp_path, monkeypatch, change,
):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    if not change:
        executor.executor.candidate = producer.BASE
    authorization = producer.authorize(resources, executor, CHANNEL_STORED_REPLY)
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=authorization)
    state = resources.journal.run_state(authorization.run_id)
    assert state.owner_id is None
    rows = resources.journal.capability_leases(authorization.run_id)
    # The fixed graph acquires workspace/executor for the writer; only a changed
    # candidate reaches the checker's gate (plan_manifest_application.py:249-255).
    expected_bindings = {
        ((CHANNEL_STORED_REPLY.graph_name, "writer"), "workspace"),
        ((CHANNEL_STORED_REPLY.graph_name, "writer"), "executor"),
    }
    if change:
        expected_bindings.add(((CHANNEL_STORED_REPLY.graph_name, "checker"), "gate"))
    assert len(rows) == len(expected_bindings)
    assert {(row.path.scope.segments, row.binding_id) for row in rows} == expected_bindings
    assert all(row.state == "closed" for row in rows)
    assert not list(resources.workspace.root.glob("payloads/*"))
    assert not list(resources.gate.root.glob("payloads/*"))
    published = Path(authorization.journal).parent / "maintenance-result.json"
    assert (result is not None, published.exists()) == (change, change)
    assert state.status is (RunStatus.SUCCEEDED if change else RunStatus.FAILED)
    # The compiled inspector fence is the complete command body. Substitute the
    # installed interpreter/service boundary with this checkout's actual CLI.
    command, = _fences(DOCUMENT, "Historical inspection and report")[:1]
    script = tmp_path / "inspect.sh"
    bootstrap = (f"import sys;sys.stdout.reconfigure(newline=chr(10));"
                 f"sys.path.insert(0,{(ROOT / 'src').as_posix()!r});"
                 "import runpy;runpy.run_module(sys.argv.pop(1),"
                 "run_name='__main__',alter_sys=True)")
    preamble = "\n".join([
        "set -Eeuo pipefail", "SERVICE=()",
        "ENTRY=(" + " ".join(shlex.quote(v) for v in (
            Path(sys.executable).as_posix(), "-I", "-B", "-c", bootstrap,
            "constructicon.api.maintenance_entry")) + ")",
        "APP=" + shlex.quote(published.parent.as_posix()),
    ])
    script.write_bytes((preamble + "\n" + command).encode())
    transported, status = _t5(tmp_path / "inspect-transport", _step("cr-inspect").expected(),
                              [_bash(), script.as_posix()])
    assert status["returncode"] == (0 if change else 1)
    assert (transported.returncode, transported.stdout, transported.stderr) == (
        (0, b"transport-step-checked 0\n", b"") if change
        else (1, b"transport-step-refused\n", b""))
    # Lay out the real producer's durable data as the shipped report reads it.
    # This copy is intentionally not its authority; the report must say unknown.
    from tests.api.test_maintenance_report import tree

    root, out = layout
    root.mkdir(mode=0o700)
    source = sqlite3.connect(resources.journal._db_path)
    copy = sqlite3.connect(root / "maintenance.sqlite")
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    if published.exists():
        shutil.copyfile(published, root / "maintenance-result.json")
    # The entry's normal return renderer (maintenance_entry._command) has these
    # exact two fields. The L0 writer double emits no native attempt record.
    (root / "application-run.json").write_bytes(json.dumps({
        "accepted": result is not None, "run_id": str(authorization.run_id),
    }).encode())
    assert not Path(authorization.attempt_record).exists()
    before = tree(root)
    # The portable workspace remover is scoped to tmp_path; the independent
    # report copy lives elsewhere. No producer resource remains to remove.
    monkeypatch.setattr(shutil, "rmtree", producer._RMTREE)
    report_program = "\n".join([
        "import os,sys,pytest",
        f"sys.path[:0]=[{ROOT.as_posix()!r},{(ROOT / 'src').as_posix()!r}]",
        "sys.stdout.reconfigure(newline=chr(10))",
        "from tests.substrate.journal.conftest import portable_capture_custody",
        "from constructicon.substrate.journal import maintenance_diagnostic as diagnostic",
        "patch=pytest.MonkeyPatch()",
        "portable_capture_custody.__wrapped__(patch)",
        "if os.name=='nt':",
        "    identity=diagnostic._identity",
        "    patch.setattr(diagnostic,'_identity',lambda value:(*identity(value)[:-1],0))",
        "from constructicon.api import maintenance_report",
        # Explicit synthetic G1 seam: this child exercises the report command,
        # not drift, sudo, boot or the complete fifteen-stage host procedure.
        "print('drift-checked')",
        "raise SystemExit(maintenance_report.main(sys.argv[1:]))",
    ])
    report_args = [sys.executable, "-I", "-B", "-c", report_program,
        "--root", str(root), "--out", str(out),
        "--command-report", str(root / "application-run.json"),
        "--run-id", str(authorization.run_id), "--authorization-id", authorization.authorization_id]
    report_capture = tmp_path / "report-transport"
    transported, status = _t5(report_capture, _step("cr-report").expected(), report_args)
    assert status == {"returncode": 0}
    assert (transported.returncode, transported.stdout, transported.stderr) == (
        0, b"transport-step-checked 0\n", b"")
    raw = (report_capture / "capture.stdout").read_bytes().removeprefix(b"drift-checked\n")
    packet = json.loads(raw)
    assert len(raw) <= 8192 and raw.endswith(b"\n")
    assert packet["purpose"] == "channel-stored-reply" and packet["complete"] is True
    assert packet["outcome"] == ("succeeded-with-acceptance-record" if change else "refused")
    assert packet["leases"]["summary"] == "recorded-closed"
    assert {(item["node"], item["binding"]) for item in packet["leases"]["items"]} == {
        (scope[-1], binding) for scope, binding in expected_bindings}
    assert packet["target"]["reason"] == "request-names-another-repository"
    if change:
        assert packet["result"]["base_sha256"] == result.base_sha256
        assert packet["result"]["candidate_sha256"] == result.candidate_sha256
    else:
        assert packet["result"] == {"observation": "missing"}
    assert tree(root) == before
    # A different, absent RunId contradicts the retained command record. The
    # actual report emits a named refusal, and T5 refuses the complete-packet
    # contract rather than accepting that shorter diagnostic shape.
    refused_args = [*report_args]
    refused_args[refused_args.index("--out") + 1] = str(out.parent / "refused-capture")
    absent = "run-" + "0" * 32
    assert absent != str(authorization.run_id)
    refused_args[refused_args.index("--run-id") + 1] = absent
    refused_capture = tmp_path / "report-refused"
    transported, status = _t5(refused_capture, _step("cr-report").expected(), refused_args)
    assert status == {"returncode": 1}
    assert (transported.returncode, transported.stdout, transported.stderr) == (
        1, b"transport-step-refused\n", b"")
    refusal = json.loads((refused_capture / "capture.stdout").read_bytes().removeprefix(
        b"drift-checked\n"))
    assert refusal["complete"] is False and refusal["stage"] == "diagnostic"
    assert refusal["diagnostic_stage"] == "command"
    assert tree(root) == before
