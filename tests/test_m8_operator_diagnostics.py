"""Synthetic diagnostic controls for selected helpers inherited by q13.

No host or vendor is observed. Original emitters/checkers and T5 remain real;
only unavailable verification facts and deliberate diagnostic writes substitute.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package

from tests import test_m8_host_runtime as runtime
from tests import test_m8_operator_commands as operator
from tests.git_bash import git_bash

evidence_world = operator.evidence_world
HANDOFFS = Path(__file__).resolve().parents[1] / "docs/plans/handoffs"
WARNING = "synthetic undeclared verifier warning\n"


@pytest.mark.parametrize("mode", ["initial", "qualify", "active"])
async def test_existing_acceptance_rejects_real_child_warning(
    evidence_world, monkeypatch, mode,
):
    original = subprocess.run
    injected = []

    def run(argv, **kwargs):
        # Only the existing isolated evidence checker receives instrumentation.
        # The child itself emits stderr; a fake CompletedProcess cannot prove it.
        selected = (isinstance(argv, (list, tuple)) and len(argv) > 8
                    and isinstance(argv[5], str) and "exec(sys.stdin.read())" in argv[5]
                    and argv[8] == mode)
        if selected:
            prefix = "import sys\nsys.stderr.buffer.write(" + repr(WARNING.encode()) + ")\n"
            kwargs["input"] = prefix + kwargs["input"]
        result = original(argv, **kwargs)
        if selected:
            injected.append((result.returncode, result.stdout, result.stderr))
        return result

    monkeypatch.setattr(subprocess, "run", run)
    test = (operator.test_documented_checker_accepts_actual_active_startup if mode == "active"
            else operator.test_documented_evidence_checker_accepts_actual_clean_qualification)
    with pytest.raises(AssertionError):
        await test(evidence_world, "pro")
    assert len(injected) == 1
    code, stdout, stderr = injected[0]
    assert code == 0 and stdout.startswith("sha256:") and stdout.endswith("\n")
    assert len(stdout) == 72 and stderr == WARNING


@pytest.mark.parametrize("damage", ["none", "stderr", "stdout"])
def test_existing_kept_launch_capture_checks_complete_success(
    tmp_path, monkeypatch, capsys, damage,
):
    # A small portable main/formatter proof, not the Linux installation fixture.
    host = object.__new__(runtime.LaunchHost)
    host.monkeypatch = monkeypatch
    host.kernel = tmp_path / "profiles"
    host.kernel.write_text("", encoding="utf-8")
    host.commit = "a" * 40
    host.workspace = tmp_path
    entered = []
    statuses = []

    def verify(commit, root, workspace, listing, record):
        entered.append(True)
        record.update(installed=True, replacement=False)
        if damage == "stderr":
            sys.stderr.write(WARNING)
        elif damage == "stdout":
            sys.stdout.write("\n")  # valid JSON whitespace, but not the emitter's exact shape

    original = runtime.artifacts.main

    def main(argv):
        result = original(argv)
        statuses.append(result)
        return result

    monkeypatch.setattr(runtime.artifacts, "verify_launch", verify)
    monkeypatch.setattr(runtime.artifacts, "main", main)
    if damage == "none":
        status, record = host.run("verify-launch", capsys)
        assert status == 0 and record == {
            "schema_version": 2, "command": "verify-launch", "commit": "a" * 40,
            "installed": True, "replacement": False,
        }
    else:
        with pytest.raises(AssertionError):
            host.run("verify-launch", capsys)
    assert entered == [True] and statuses == [0]


@pytest.mark.parametrize("warning", [False, True])
def test_actual_kept_launch_package_through_t5_refuses_undeclared_warning(tmp_path, warning):
    step = next(s for s in package.assemble(
        HANDOFFS / "M8-maintenance-q13-continuation.md", template=True,
    ) if s.name == "q13-c2-kept-launch")
    workspace = tmp_path / "m8-launch"
    workspace.mkdir()
    payload = b'{"installed":true,"replacement":false}\n'
    # Synthetic installed-verifier primitive. Its real stdout is retained by the
    # unchanged composed shell; its optional diagnostic reaches the unchanged T5.
    (workspace / "m8_host_artifacts.py").write_bytes((
        "import sys\nsys.stdout.buffer.write(" + repr(payload) + ")\n"
        + ("sys.stderr.buffer.write(" + repr(WARNING.encode()) + ")\n" if warning else "")
    ).encode())
    text = step.text.replace("/usr/bin/python3", shlex.quote(Path(sys.executable).as_posix()))
    text = text.replace('sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles',
                        "printf 'synthetic profile listing\\n'")
    if os.name == "nt":
        text = text.replace("import json, sys\n", 'import json, sys\nsys.stdout.reconfigure('
                            'newline="\\n")\n')
    script = tmp_path / "step.sh"
    script.write_bytes(text.encode())
    expectation = tmp_path / "expected.json"
    expectation.write_bytes(step.expected().encode())
    transport, = [body for kind, body in package.fences(package.section(
        (HANDOFFS / "M8-maintenance-q12-continuation.md").read_bytes().decode(),
        "Q6: transport T5")) if kind == "python"]
    checker = tmp_path / "transport.py"
    checker.write_bytes(transport.encode())
    prefix = tmp_path / "capture"
    next_step = tmp_path / "next-step"
    command = shlex.join([
        Path(sys.executable).as_posix(), "-I", "-S", "-B", str(checker), str(prefix),
        str(expectation), "--", git_bash(), script.as_posix(),
    ]) + " && printf entered > " + shlex.quote(next_step.as_posix())
    result = subprocess.run(
        [git_bash(), "-c", command], stdin=subprocess.DEVNULL,
        capture_output=True, timeout=30, check=False,
        env={**os.environ, "HOME": tmp_path.as_posix()},
    )
    assert (result.returncode, result.stdout, result.stderr) == (
        (1, b"transport-step-refused\n", b"") if warning
        else (0, b"transport-step-checked 0\n", b""))
    assert (tmp_path / "capture.stdout").read_bytes() == b"kept-launch-verified\n"
    assert (tmp_path / "capture.stderr").read_bytes() == (WARNING.encode() if warning else b"")
    assert json.loads((tmp_path / "capture.status.json").read_bytes()) == {"returncode": 0}
    assert (workspace / "verify.json").read_bytes() == payload
    # An actual shell && gates the next command on T5, not the producer's exit.
    assert next_step.exists() is (not warning)
