"""Disposable preparation inputs, not installed-controller or vendor evidence.

The source fixture imports the real committed tree without history or the task's
output path. Synthetic qualification is emitted by the real maintenance lane;
the only executable substitution remains at the shared test injection root.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import shutil
import sysconfig
from pathlib import Path

from scripts import m8_procedure_package as package

from constructicon.api._maintenance_source import SOURCE_FILES, SOURCE_HASHES, SourcePin, git
from constructicon.core.maintenance import MaintenanceAttemptAuthorization
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.maintenance_task_world import committed_tree_base

ROOT = Path(__file__).resolve().parents[1]
HANDOFFS = ROOT / "docs/plans/handoffs"
DOCUMENT = HANDOFFS / "M8-maintenance-q13-continuation.md"
SYNTHETIC_DRIFT = b"Synthetic preparation fixture: all declared drift facts agree.\n"
STEPS = ("q13-c7-prepare", "q13-c8-preflight")


async def source_bundle(directory: Path, *, wrong_consumer: bool = False):
    """An actual self-contained Git bundle, pinned independently of its consumer."""
    directory.mkdir(mode=0o700)
    repository = directory / "source.git"
    repository.mkdir(mode=0o700)
    await git(repository, "init", "--bare", "--template=", "--object-format=sha1", ".")
    authority = GitAuthority(repository, directory / "workspaces")
    base = await committed_tree_base(authority)
    if wrong_consumer:
        # Deliberately inconsistent with the production pinned consumer; its
        # bundle digest is still truthful, so digest mismatch cannot mask it.
        changed = SOURCE_FILES[1]
        await git(repository, "read-tree", base)
        original = await git(repository, "show", f"{base}:{changed}")
        from constructicon.substrate.executors.linux import ProcessLimits
        from constructicon.substrate.git.process import GitProcess

        process = GitProcess(authority.git_executable, ProcessLimits())
        blob = (await process.run("hash-object", "-w", "--stdin", cwd=repository,
                                  stdin=original + b"\n# synthetic wrong consumer\n")).strip()
        await git(repository, "update-index", "--cacheinfo", f"100644,{blob.decode()},{changed}")
        tree = (await git(repository, "write-tree")).strip().decode()
        base = (await process.run("commit-tree", tree, cwd=repository,
                                  stdin=b"synthetic mismatching consumer\n")).strip().decode()
        await git(repository, "update-ref", "refs/heads/main", base)
    bundle = directory / "reviewed.bundle"
    await git(repository, "bundle", "create", str(bundle), "refs/heads/main")
    assert (await git(repository, "rev-parse", "refs/heads/main")).strip().decode() == base
    return bundle, base, hashlib.sha256(bundle.read_bytes()).hexdigest()


def qualify(root: Path, launch: Path, session: Path):
    """Bootstrap the real isolated topology using emitted synthetic-peer evidence."""
    from tests.substrate.test_operator_store_maintenance_restart import (
        KEY,
        isolated_checked_revision,
        isolated_module,
        isolated_read,
        isolated_record,
        isolated_run,
        service,
    )

    base = ["--store-root", str(root), "--key", KEY]
    # The actual packaged qualification checker requires a genuine held S6a,
    # not a startup record with edited metadata. Pay this pause once for all
    # scenarios; the activated store then stays immutable and is never restored.
    completed = []
    for name, hold in (("s4", 0), ("s6a", 90)):
        evidence = session / f"{name}-qualification.json"
        lane = isolated_module(
            "constructicon.substrate.executors.codex_lane", "startup",
            "--launch-root", str(launch), "--configuration", str(session / "config.toml"),
            "--policy", str(session / "startup-policy.json"),
            "--lane-dir", str(session / f"{name}-lane"), "--evidence", str(evidence),
            "--hold", str(hold), "--deadline", "120",
        )
        ran = isolated_run(isolated_module(
            "constructicon.substrate.executors.operator_store", "maintain", *base,
            "--service", "m8-service", "--wait", "0", "--", *lane,
        ))
        record, revision = isolated_record(ran, evidence, 0)
        assert record["faults"] == [] and record["gate"]["completed"] is True
        assert record["custody"] == {"kind": "maintenance", "generation_floor": 1}
        assert record["hold_s"] == hold
        assert record["process"]["elapsed_s"] >= hold
        seal = f"{record['gate']['plan']}/{record['gate']['account']}"
        isolated_checked_revision("hold" if hold else "initial", evidence,
                                  seal if hold else "-", session, launch, revision)
        completed.append(name)
    assert completed == ["s4", "s6a"]
    published = isolated_run(isolated_module(
        "constructicon.substrate.executors.operator_store", "publish", *base,
        "--generation", "2", "--qualification-evidence-digest", revision,
    ))
    sealed = NativeOperatorStoreIdentityV1.model_validate_json(published.stdout)
    assert (published.returncode, published.stdout, published.stderr) == (
        0, (sealed.model_dump_json() + "\n").encode(), b"")
    assert str(sealed.subscription_mode_adapter_revision) == revision
    assert str(sealed.store_conformance_revision) == revision
    path = session / "qualified.json"
    path.write_bytes(sealed.model_dump_json().encode())
    path.chmod(0o600)
    os.chown(path, *service())
    activated = isolated_run(isolated_module(
        "constructicon.substrate.executors.operator_store", "activate", *base,
        "--generation", "2", "--sealed", str(path),
        "--qualification-evidence-digest", revision,
    ))
    assert (activated.returncode, activated.stdout, activated.stderr) == (0, b"", b"")
    isolated_read(root, sealed, "accepted")
    assert root == launch / "operator-stores"
    assert json.loads(evidence.read_bytes()) == record
    return sealed, revision


def packaged_steps(directory: Path, launch: Path, session: Path, bundle: Path,
                   base: str, revision: str):
    """Build the actual q13 package, then substitute only fixture-bound inputs.

    No fence is removed/reordered, binding checker bypassed, or CLI replaced.
    Unselected deferred steps get explicitly synthetic values and never execute.
    Inline controller checkers use this venv and checkout together, not system
    Python with incompatible compiled venv packages or an installed controller.
    Stdlib-only G1 and the actual contained runtime remain unchanged. The same
    injection-root launcher substitution as #236 also serves maintenance_entry.
    """
    from tests.substrate.test_operator_store_maintenance_restart import KEY, isolated_module

    drift = directory / "synthetic-drift"
    drift.write_bytes(b"#!/usr/bin/python3\nimport sys\nsys.stdout.buffer.write("
                      + repr(SYNTHETIC_DRIFT).encode() + b")\n")
    drift.chmod(0o555)
    out = directory / "package"
    package.build(DOCUMENT, out, values={
        "DRIFT_STDOUT_HEX": SYNTHETIC_DRIFT.hex(),
        "DRIFT_TOOL_SHA256": hashlib.sha256(drift.read_bytes()).hexdigest(),
        "PREVIEW_SHA256": "e" * 64,
        "RUN_ID": "run-" + "e" * 32,
        "EXPECTED_BOOT": "00000000-0000-4000-8000-000000000001",
    })
    controller = (HANDOFFS / "M8-N4-operator-commands.md").read_bytes().decode()
    setup = package.fences(package.section(
        controller, "Setup: fixed controller and evidence checks"))
    old_python = next(line for line in setup[0][1].splitlines() if line.startswith("PY=("))
    command = isolated_module("constructicon.api.maintenance_entry")[:-1]
    # A test-only affirmative CLI-entry inventory. --help, prepare and preflight
    # are observed before main; it supplies no CLI result or provider behavior.
    command[5] = command[5].replace("module = sys.argv.pop(1)\n", "module = sys.argv.pop(1)\n"
        "if module == 'constructicon.api.maintenance_entry':\n"
        f"    with open({str(directory / 'cli-entered')!r}, 'ab') as observed:\n"
        "        observed.write((sys.argv[1] + '\\n').encode())\n")
    substitutions = {
        old_python: "PY=(" + shlex.join(command) + ")",
        '"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c':
            '"${SERVICE[@]}" ' + shlex.quote(command[0]) + ' -I -S -B -c',
        'sys.path.insert(0, "/opt/constructicon-m8-controller")':
            "sys.path[:0] = " + json.dumps([str(ROOT / "src"), sysconfig.get_paths()["purelib"]]),
        "/var/lib/constructicon-m8-launch/operator-stores": str(launch / "operator-stores"),
        "/var/lib/constructicon-m8-launch": str(launch),
        "K=n4-codex-pro": "K=" + KEY,
        "5793ef98ef5597c9ee9811a0d1f031554eb7f514": base,
        "4afec171317d727b95a4f43e2d22c403e917e3994cfca214db8dccfb031d9282": revision,
        "BUNDLE_SIZE=4189475": "BUNDLE_SIZE=" + str(bundle.stat().st_size),
        "$HOME/maintenance-q13-c7-package/maintenance-q13-5793ef98.bundle": str(bundle),
        "/home/m8-service/maintenance-q13-5793ef98.bundle": str(session / "reviewed.bundle"),
        "/home/m8-service/m8-maint-q13": str(session),
        "/home/m8-service/m8-m5": str(directory / "state"),
        "/home/m8-service/m8-maint-a5": str(directory / "application"),
        "$HOME/maintenance-q13-drift-c7-prepare": str(directory / "drift-c7"),
        "$HOME/maintenance-q13-drift-c8-preflight": str(directory / "drift-c8"),
        "/usr/local/bin/m8-host-drift": str(drift),
    }
    # Match only authored tokens, longest first. A Linux fixture path itself
    # contains the original launch prefix; never rewrite inserted values again.
    authored = re.compile("|".join(re.escape(token) for token in
                                   sorted(substitutions, key=len, reverse=True)))
    for name in STEPS:
        for suffix in (".sh", ".expected.json"):
            path = out / (name + suffix)
            text = path.read_bytes().decode()
            text = authored.sub(lambda match: substitutions[match[0]], text)
            path.write_bytes(text.encode())
    return out


def _inventory(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def observe_step(fault, name, status, stdout, stderr):
    """Retain bounded synthetic observations before any verdict assertion."""
    from tests.substrate.test_native_codex_mediation import write_evidence

    write_evidence(f"n3c-q13-{fault}-{name}.json", {
        "schema_version": 1, "synthetic_fixture": True,
        "meaning": "step observation, not a passed verdict",
        "scenario": fault, "step": name, "status": status,
        "streams": {key: {"bytes": len(raw), "tail_hex": raw[-8192:].hex()}
                    for key, raw in (("stdout", stdout), ("stderr", stderr))},
    })


def _drift_source(application, base):
    from tests.substrate.test_operator_store_maintenance_restart import (
        isolated_module,
        isolated_run,
    )

    # Run as the actual owner: a root Git read would require an ownership bypass
    # and could create metadata that the real service correctly cannot use.
    program = """
import asyncio, shutil, sys
from pathlib import Path
from constructicon.api._maintenance_source import git
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.git.process import GitProcess
async def main():
    repository, base = Path(sys.argv[1]) / 'authority.git', sys.argv[2]
    tree = (await git(repository, 'rev-parse', base + '^{tree}')).strip().decode()
    process = GitProcess(shutil.which('git'), ProcessLimits())
    moved = (await process.run('commit-tree', tree, cwd=repository,
        stdin=b'synthetic source drift\\n')).strip().decode()
    await git(repository, 'update-ref', 'refs/heads/maintenance', moved)
    print(moved)
asyncio.run(main())
"""
    entry = ("import sys; sys.path[:0] = sys.argv[1:3]; del sys.argv[1:3]; "
             "exec(sys.argv.pop(1))")
    ran = isolated_run([*isolated_module("unused")[:5], entry, str(ROOT / "src"),
                        sysconfig.get_paths()["purelib"], program, str(application), base],
                       as_service=True)
    assert (ran.returncode, ran.stderr) == (0, b"")
    assert re.fullmatch(rb"[0-9a-f]{40}\n", ran.stdout)
    assert ran.stdout.decode().strip() != base


def exercise_seam(root: Path, launch: Path, foundation: Path, parent: Path):
    """One immutable qualified topology; fresh service state for every scenario."""
    from tests.substrate.test_operator_store_maintenance_restart import service
    from tests.test_m8_maintenance_q12_rehearsal import _t5

    sealed, qualification = qualify(root, launch, foundation)
    durable = _inventory(root)
    inputs = _inventory(foundation)
    reviewed = asyncio.run(source_bundle(parent / "reviewed-source"))
    wrong = asyncio.run(source_bundle(parent / "wrong-source", wrong_consumer=True))
    completed = []
    for fault in ("accept", "wrong-consumer", "source-drift", "qualification", "diagnostic"):
        directory = parent / ("seam-" + fault)
        directory.mkdir(mode=0o700)
        os.chown(directory, *service())
        session = directory / "session"
        session.mkdir(mode=0o700)
        os.chown(session, *service())
        for name in ("config.toml", "startup-policy.json", "s4-qualification.json",
                     "s6a-qualification.json", "qualified.json"):
            destination = session / ("g11.sealed.json" if name == "qualified.json" else name)
            shutil.copyfile(foundation / name, destination)
            os.chown(destination, *service())
            destination.chmod(0o600)
        bundle, base, revision = wrong if fault == "wrong-consumer" else reviewed
        package_dir = packaged_steps(directory, launch, session, bundle, base, revision)
        if fault == "diagnostic":
            path = package_dir / (STEPS[0] + ".sh")
            path.write_bytes(path.read_bytes() + b"printf 'synthetic preparation warning\\n' >&2\n")
        entered = []
        continued = False
        for name in STEPS:
            entered.append(name)
            capture = directory / ("capture-" + name)
            capture.mkdir(mode=0o700)
            ran = _t5(capture, package_dir / (name + ".sh"),
                      package_dir / (name + ".expected.json"))
            stdout = (capture / "step.stdout").read_bytes()
            stderr = (capture / "step.stderr").read_bytes()
            status = json.loads((capture / "step.status.json").read_bytes())
            observe_step(fault, name, status, stdout, stderr)
            application = directory / "application"
            state = directory / "state"
            if name == STEPS[0]:
                if fault == "wrong-consumer":
                    assert (status, stdout, stderr) == (
                        {"returncode": 1}, b"drift-checked\nmaintenance-bundle-transferred\n", b"")
                    assert (state / "source-prepared.json").read_bytes() == (
                        b'{"accepted":false,"error":"maintenance command refused or incomplete"}\n')
                    assert not (application / "source-pin.json").exists()
                else:
                    expected = b"drift-checked\nmaintenance-bundle-transferred\n" + (
                        json.dumps({"source_prepared": True, "base": base,
                                    "bundle_sha256": revision}, sort_keys=True) + "\n").encode()
                    assert (status, stdout, stderr) == (
                        {"returncode": 0}, expected,
                        b"synthetic preparation warning\n" if fault == "diagnostic" else b"")
                    pin = SourcePin.model_validate_json(
                        (state / "source-prepared.json").read_bytes())
                    retained = SourcePin.model_validate_json(
                        (application / "source-pin.json").read_bytes())
                    assert pin == retained
                    assert pin.base_commit == base and pin.bundle_sha256 == revision
                    assert pin.sources == SOURCE_HASHES
                    assert pin.target_ref == "refs/heads/maintenance"
                    assert (application / "reviewed.bundle").read_bytes() == bundle.read_bytes()
                if fault in {"wrong-consumer", "diagnostic"}:
                    assert (ran.returncode, ran.stdout, ran.stderr) == (
                        1, "transport-step-refused\n", "")
                    break
                assert (ran.returncode, ran.stdout, ran.stderr) == (
                    0, "transport-step-checked 0\n", "")
                if fault == "source-drift":
                    # A real ref transition between the two packaged commands;
                    # no source inspector or provider is replaced.
                    _drift_source(application, base)
                elif fault == "qualification":
                    path = session / "s6a-qualification.json"
                    changed = json.loads(path.read_bytes())
                    changed["refresh"] = (
                        "measured" if changed["refresh"] == "unmeasured" else "unmeasured")
                    path.write_bytes(json.dumps(changed).encode())
                continue
            if fault == "source-drift":
                assert (status, stdout, stderr) == ({"returncode": 1}, b"drift-checked\n" + (
                    json.dumps({"preflight": False, "stage": "source"}, sort_keys=True)
                    + "\n").encode(), b"")
                assert json.loads((state / "preflight.json").read_bytes()) == {
                    "accepted": False, "error": "maintenance command refused or incomplete",
                    "stage": "source"}
            elif fault == "qualification":
                # The actual prefix notices the changed digest before the CLI.
                script = (package_dir / (name + ".sh")).read_text()
                match = re.search(r"check_sealed\(\) \{.*?-c '(.*?)' ", script, re.S)
                assert match is not None
                line = next(index for index, text in enumerate(match[1].splitlines(), 1)
                            if 'raise ValueError("sealed identity revisions do not match")' in text)
                expected = (f'Traceback (most recent call last):\n'
                            f'  File "<string>", line {line}, in <module>\n'
                            'ValueError: sealed identity revisions do not match\n').encode()
                assert (status, stdout, stderr) == ({"returncode": 1}, b"drift-checked\n", expected)
                assert not (state / "preflight.json").exists()
            else:
                assert fault == "accept"
                raw = (state / "preflight.json").read_bytes()
                preview = MaintenanceAttemptAuthorization.model_validate_json(raw)
                assert preview.request.base_commit == base
                assert preview.request.target_ref == "refs/heads/maintenance"
                assert preview.journal == str(application / "maintenance.sqlite")
                assert preview.attempt_record == str(application / "maintenance-attempt.json")
                assert preview.operator_binding_digest == sealed.operator_binding_digest
                assert preview.authorization_id == "maintenance-5-" + base
                assert preview.actor_id == "operator:maintenance-5"
                assert preview.idempotency_key == "maintenance-5"
                journal = SqliteJournal(application / "maintenance.sqlite")
                assert journal.run_records(limit=2) == []
                fields = {"preview_sha256": hashlib.sha256(raw).hexdigest(),
                          "run_id": str(preview.run_id),
                          "authorization_id": preview.authorization_id,
                          "base": base, "source_graph_hash": str(preview.source_graph_hash),
                          "application_revision": str(preview.application_revision),
                          "revision": preview.revision,
                          "operator_binding_digest": str(sealed.operator_binding_digest),
                          "workspace": preview.workspace.model_dump(mode="json"),
                          "gate": preview.gate.model_dump(mode="json"),
                          "not_after": preview.not_after.isoformat(),
                          "grants": preview.grants.model_dump(mode="json")}
                assert (status, stdout, stderr) == ({"returncode": 0}, b"drift-checked\n" +
                    (json.dumps(fields, sort_keys=True) + "\n").encode(), b"")
                assert (ran.returncode, ran.stdout, ran.stderr) == (
                    0, "transport-step-checked 0\n", "")
                continued = True  # Harmless next-step sentinel, never C9 authority.
            if fault != "accept":
                assert (ran.returncode, ran.stdout, ran.stderr) == (
                    1, "transport-step-refused\n", "")
        assert entered == list(STEPS[:1] if fault in {"wrong-consumer", "diagnostic"} else STEPS)
        assert continued is (fault == "accept")
        expected_calls = b"--help\nprepare\n" + (
            b"preflight\n" if fault in {"accept", "source-drift"} else b"")
        assert (directory / "cli-entered").read_bytes() == expected_calls
        assert not (directory / "application/maintenance-attempt.json").exists()
        assert not (directory / "application/maintenance-result.json").exists()
        if fault != "accept":
            assert not (directory / "application/maintenance.sqlite").exists()
        assert _inventory(root) == durable and _inventory(foundation) == inputs
        completed.append(fault)
    assert completed == ["accept", "wrong-consumer", "source-drift", "qualification", "diagnostic"]
    return qualification
