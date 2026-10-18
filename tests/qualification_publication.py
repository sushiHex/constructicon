"""Actual packaged q13 C3/C4 over disposable synthetic inputs, never host evidence.

Substitutions are paths/interpreter, the existing injection-root native peer,
deterministic prepare DNS, the prior account seal and the private G1 tool. All
producer, transport, evidence, custody, floor and binding checkers stay real.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from scripts import m8_procedure_package as package

from constructicon.core.identity import canonical_json, digest
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN
from tests.preparation_preflight import SYNTHETIC_DRIFT, _inventory, observe_step

ROOT = Path(__file__).resolve().parents[1]
HANDOFFS = ROOT / "docs/plans/handoffs"
DOCUMENT = HANDOFFS / "M8-maintenance-q13-continuation.md"
STEPS = ("q13-c3-qualification", "q13-c4-publish")


def packaged_steps(directory: Path, launch: Path, session: Path):
    from tests.substrate.test_operator_store_maintenance_restart import KEY, isolated_module

    drift = directory / "synthetic-drift"
    drift.write_bytes(b"#!/usr/bin/python3\nimport sys\nsys.stdout.buffer.write("
                      + repr(SYNTHETIC_DRIFT).encode() + b")\n")
    drift.chmod(0o555)
    out = directory / "package"
    package.build(DOCUMENT, out, values={
        "DRIFT_STDOUT_HEX": SYNTHETIC_DRIFT.hex(),
        "DRIFT_TOOL_SHA256": hashlib.sha256(drift.read_bytes()).hexdigest(),
        "PREVIEW_SHA256": "e" * 64, "RUN_ID": "run-" + "e" * 32,
        "EXPECTED_BOOT": "00000000-0000-4000-8000-000000000001",
    })
    setup = package.fences(package.section(
        (HANDOFFS / "M8-N4-operator-commands.md").read_bytes().decode(),
        "Setup: fixed controller and evidence checks"))
    old_python = next(line for line in setup[0][1].splitlines() if line.startswith("PY=("))
    command = isolated_module("constructicon.substrate.executors.codex_lane")[:-1]
    # Affirmative entry inventory, not a supplied CLI result. O_APPEND writes
    # one bounded JSON line before real main, from both root and service.
    observation = (
        "import json, os\nfrom pathlib import Path\n"
        f"with open({str(session.parent / 'cli-entered')!r}, 'ab', buffering=0) as observed:\n"
        "    observed.write((json.dumps({'module': module, 'args': sys.argv[1:], "
        "'pid': os.getpid(), 'starttime': "
        "Path('/proc/self/stat').read_text().rpartition(')')[2].split()[19]}) + '\\n').encode())\n"
        "if module == 'constructicon.substrate.executors.codex_lane':\n"
        "    import socket\n"
        "    def resolve(host, port, *, family, type):\n"
        "        assert family == socket.AF_INET and type == socket.SOCK_STREAM and port == 443\n"
        "        assert host in ('auth.openai.com', 'chatgpt.com')\n"
        "        address = '8.8.8.8' if host == 'auth.openai.com' else '8.8.4.4'\n"
        "        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))]\n"
        "    socket.getaddrinfo = resolve\n"
    )
    command[5] = command[5].replace("module = sys.argv.pop(1)\n",
                                   "module = sys.argv.pop(1)\n" + observation)
    substitutions = {
        old_python: "PY=(" + shlex.join(command) + ")",
        '"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c':
            '"${SERVICE[@]}" ' + shlex.quote(command[0]) + ' -I -S -B -c',
        'sys.path.insert(0, "/opt/constructicon-m8-controller")':
            "sys.path[:0] = " + json.dumps([str(ROOT / "src"), sysconfig.get_paths()["purelib"]]),
        "/var/lib/constructicon-m8-launch/operator-stores": str(launch / "operator-stores"),
        "/var/lib/constructicon-m8-launch": str(launch),
        "K=n4-codex-pro": "K=" + KEY,
        "/home/m8-service/m8-maint-q13": str(session),
        "/home/m8-service/m8-maint-q10": str(session.parent / "prior"),
        "$HOME/maintenance-q13-lanes-c3": str(directory / "lanes"),
        "$HOME/maintenance-q13-drift-c3-qualification": str(directory / "drift"),
        "$HOME/maintenance-g9-account.seal": str(directory / "synthetic-prior.seal"),
        "/usr/local/bin/m8-host-drift": str(drift),
    }
    authored = re.compile("|".join(re.escape(token) for token in
                                   sorted(substitutions, key=len, reverse=True)))
    for name in STEPS:
        for suffix in (".sh", ".expected.json"):
            path = out / (name + suffix)
            path.write_bytes(authored.sub(lambda m: substitutions[m[0]],
                                         path.read_bytes().decode()).encode())
    return out


def assert_checked(*, transport, status, stdout, stderr, expected):
    assert transport == (0, b"transport-step-checked 0\n", b"")
    assert (status, stdout, stderr) == ({"returncode": 0}, expected, b"")


def _run_step(directory, script, expected, inventory):
    """Own and join T5; cleanup is outside the unchanged packaged command.

    Normal S6a joins its own holder before T5 returns. On an unexpected timeout
    give the bounded startup a grace period before terminating this test session.
    No crash-cleanup or power-loss guarantee is inferred from this harness.
    """
    from tests.test_m8_maintenance_q12_rehearsal import _transport

    t5 = directory / "transport.py"
    t5.write_bytes(_transport().encode())
    process = subprocess.Popen([
        sys.executable, "-I", "-S", "-B", str(t5), str(directory / "step"),
        str(expected), "--", "/bin/bash", str(script),
    ], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True)
    try:
        try:
            stdout, stderr = process.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            # Do not remove fixture inputs beneath a still-held S6a command.
            stdout, stderr = process.communicate(timeout=150)
            raise AssertionError("packaged rehearsal exceeded its normal deadline") from None
        return process.returncode, stdout, stderr
    finally:
        try:
            # Signal only while the direct child is still ours and unreaped.
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        finally:
            _drain_observed(inventory)


def _drain_observed(inventory):
    """Wait for observed CLI identities before deleting their fixture inputs.

    This is a bounded test cleanup, not a general descendant/process-tree proof.
    PID start time is checked before signaling to exclude PID reuse.
    """
    records = [json.loads(line) for line in inventory.read_bytes().splitlines()]

    def live(record):
        path = Path(f"/proc/{record['pid']}/stat")
        try:
            fields = path.read_text().rpartition(")")[2].split()
        except FileNotFoundError:
            return False
        return fields[19] == record["starttime"] and fields[0] != "Z"

    deadline = time.monotonic() + 150
    while any(live(record) for record in records) and time.monotonic() < deadline:
        time.sleep(0.1)
    remaining = [record for record in records if live(record)]
    for record in remaining:
        if live(record):
            with suppress(ProcessLookupError):
                os.kill(record["pid"], signal.SIGTERM)
    terminated = time.monotonic() + 10
    while any(live(record) for record in remaining) and time.monotonic() < terminated:
        time.sleep(0.1)
    for record in remaining:
        if live(record):
            with suppress(ProcessLookupError):
                os.kill(record["pid"], signal.SIGKILL)
    killed = time.monotonic() + 10
    while any(live(record) for record in remaining) and time.monotonic() < killed:
        time.sleep(0.1)
    assert not any(live(record) for record in remaining), "observed CLI survived cleanup"
    assert not remaining, "observed CLI did not complete before fixture cleanup"


def _calls(path):
    records = [json.loads(line) for line in path.read_bytes().splitlines()]
    assert all(set(record) == {"module", "args", "pid", "starttime"}
               and record["starttime"].isdigit() and type(record["pid"]) is int
               and record["pid"] > 0 for record in records)
    return [(record["module"].rsplit(".", 1)[1], record["args"][0]) for record in records]


def exercise_seam(root: Path, launch: Path, parent: Path, scenario: str):
    from tests.substrate.test_codex_protocol import EXPECTED
    from tests.substrate.test_native_codex_mediation import write_evidence
    from tests.substrate.test_operator_store_maintenance_restart import (
        KEY,
        bundle_of,
        isolated_read,
        publish,
        service,
    )

    floor = 9 if scenario == "wrong-floor" else 10
    for generation in range(2, floor + 1):
        retained = publish(root, generation, runtime_uid=service()[0])
    bundle = bundle_of(root)
    descriptors = _inventory(bundle / "descriptors")
    assert set(descriptors) == {f"{n}.json" for n in range(1, floor + 1)}
    with tempfile.TemporaryDirectory(prefix="qp-", dir="/tmp") as name:
        service_parent = Path(name)
        os.chown(service_parent, *service())
        session = service_parent / "session"  # S1 must create it, never precreated.
        prior = service_parent / "prior"
        prior.mkdir(mode=0o700)
        os.chown(prior, *service())
        seal_file = prior / "g10.sealed.json"
        seal_file.write_bytes(retained.model_dump_json().encode())
        seal_file.chmod(0o600)
        os.chown(seal_file, *service())
        inventory = service_parent / "cli-entered"
        inventory.touch(mode=0o600)
        os.chown(inventory, *service())
        directory = parent / "composition"
        directory.mkdir(mode=0o700)
        expected_seal = EXPECTED.seal
        (directory / "synthetic-prior.seal").write_bytes((
            (expected_seal.replace("pro/", "prolite/", 1)
             if scenario == "historical-seal" else expected_seal) + "\n").encode())
        out = packaged_steps(directory, launch, session)
        completed = []
        revision = None
        for step in STEPS:
            capture = directory / step
            capture.mkdir(mode=0o700)
            before = _inventory(root) if step == STEPS[1] else None
            try:
                transport = _run_step(capture, out / (step + ".sh"),
                                      out / (step + ".expected.json"), inventory)
            except BaseException:
                status_path = capture / "step.status.json"
                observe_step("c3c4-" + scenario, step,
                    json.loads(status_path.read_bytes()) if status_path.exists() else {
                        "returncode": None, "capture_complete": False},
                    (capture / "step.stdout").read_bytes()
                    if (capture / "step.stdout").exists() else b"",
                    (capture / "step.stderr").read_bytes()
                    if (capture / "step.stderr").exists() else b"")
                raise
            status = json.loads((capture / "step.status.json").read_bytes())
            stdout = (capture / "step.stdout").read_bytes()
            stderr = (capture / "step.stderr").read_bytes()
            observe_step("c3c4-" + scenario, step, status, stdout, stderr)
            calls = _calls(inventory)
            s4 = json.loads((session / "s4-qualification.json").read_bytes())
            assert s4["completed"] is True and s4["gate"]["completed"] is True
            assert s4["faults"] == [] and s4["custody"] == {
                "kind": "maintenance", "generation_floor": floor}
            assert f"{s4['gate']['plan']}/{s4['gate']['account']}" == expected_seal
            if step == STEPS[0]:
                wanted = (b"drift-checked\n" + json.dumps({
                    "prepared": True, "out": str(session)}).encode()
                    + b"\nlane-boundary-checked\n")
                if scenario == "historical-seal":
                    assert transport == (1, b"transport-step-refused\n", b"")
                    assert (status, stdout, stderr) == ({"returncode": 1}, wanted,
                        b"fresh S4 account differs from historical checked g10; stop\n")
                    assert calls == [("codex_lane", "prepare"), ("operator_store", "maintain"),
                                     ("codex_lane", "startup")]
                    assert _inventory(bundle / "descriptors") == descriptors
                    assert json.loads((bundle / "active.json").read_bytes()) == {
                        "schema_version": 1, "key": KEY, "generation_floor": floor}
                    assert not (session / "s6a-qualification.json").exists()
                    assert not (directory / STEPS[1]).exists()
                    completed.append(step)
                    break
                assert_checked(transport=transport, status=status, stdout=stdout,
                               stderr=stderr, expected=wanted)
                assert calls[:4] == [("codex_lane", "prepare"),
                                     ("operator_store", "maintain"),
                                     ("codex_lane", "startup"),
                                     ("operator_store", "maintain")]
                # The lock probe can resume before the held child reaches its
                # entry observation. Neither ordering is ownership evidence;
                # completed held custody and the unchanged S6a checks supply it.
                assert sorted(calls[4:]) == [("codex_lane", "startup"),
                                             ("operator_store", "maintain")]
                held = json.loads((session / "s6a-qualification.json").read_bytes())
                assert held["completed"] is True and held["faults"] == []
                assert held["custody"] == {"kind": "maintenance", "generation_floor": floor}
                assert held["hold_s"] == 90 and held["process"]["elapsed_s"] >= 90
                assert f"{held['gate']['plan']}/{held['gate']['account']}" == expected_seal
                revision = str(digest(EVIDENCE_DOMAIN, 1,
                                      json.loads(canonical_json(held))))
                # Producer records are retained before C4 can refuse or publish.
                write_evidence("n3c-q13-c3c4-" + scenario + "-qualification.json", {
                    "schema_version": 1, "synthetic_fixture": True,
                    "s4": s4, "s6a": held, "qualification_evidence_digest": revision,
                })
                completed.append(step)
                prior_calls = calls
                continue
            if scenario == "wrong-floor":
                assert transport == (1, b"transport-step-refused\n", b"")
                assert status == {"returncode": 1} and stdout == b""
                assert stderr.endswith(b"AssertionError\n")
                assert calls == prior_calls
                assert _inventory(root) == before
            else:
                assert_checked(transport=transport, status=status, stdout=stdout,
                               stderr=stderr, expected=b"")
                assert calls == [*prior_calls, ("operator_store", "publish"),
                                 ("operator_store", "activate")]
                sealed = NativeOperatorStoreIdentityV1.model_validate_json(
                    (session / "g11.sealed.json").read_bytes())
                assert str(sealed.subscription_mode_adapter_revision) == revision
                assert str(sealed.store_conformance_revision) == revision
                published = _inventory(bundle / "descriptors")
                assert set(published) == set(descriptors) | {"11.json"}
                assert {name: raw for name, raw in published.items()
                        if name != "11.json"} == descriptors
                active = json.loads((bundle / "active.json").read_bytes())
                assert active["generation"] == 11 and active["key"] == KEY
                assert active["binding_digest"] == str(sealed.operator_binding_digest)
                isolated_read(root, sealed, "accepted")
                isolated_read(root, retained, "refused")
            completed.append(step)
        # Establish the exact final durable state even for the early refusal.
        if scenario != "accept":
            assert _inventory(bundle / "descriptors") == descriptors
            assert not (session / "g11.sealed.json").exists()
            assert json.loads((bundle / "active.json").read_bytes()) == {
                "schema_version": 1, "key": KEY, "generation_floor": floor}
        assert completed == ([STEPS[0]] if scenario == "historical-seal" else list(STEPS))
        return revision
