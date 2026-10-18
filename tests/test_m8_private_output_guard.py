"""Synthetic host interface evidence, never a measurement of the private host.

The exact reviewed guard is assembled by the real packager, then executed by
Bash. Only host-bound primitives (Python and the drift executable) are replaced.
Every synthetic success has different plausible output that the same step
refuses; no stub here is evidence of the installed tool's interface.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package

from tests.git_bash import git_bash

HANDOFF = Path(__file__).parents[1] / "docs/plans/handoffs/M8-private-output-guard.md"
HEADING = "G1: private drift boundary"
SYNTHETIC = b"Synthetic affirmative drift verdict: all nine checked facts agree.\n"


def _procedure(tmp_path: Path, calls: str = "once", extra: str = "") -> Path:
    """A successor-shaped composition, using the real reviewed fence by digest."""
    guard = HANDOFF.read_bytes()
    (tmp_path / "guard.md").write_bytes(guard)
    selected = '{source = "guard", heading = "' + HEADING + '", fences = [0]}'
    if calls == "conditional":
        parts = ['{literal = "if true; then"}', selected, '{literal = "fi"}']
    elif calls == "condition":
        parts = ['{literal = "if {"}', selected, '{literal = "}; then :; fi"}']
    elif calls == "twice":
        parts = [selected, '{literal = \'DRIFT_CAPTURE="$TEST_ROOT/second"\'}', selected]
    else:
        parts = [selected]
    parts.append('{literal = \'printf "next-command\\n"; printf x >"$TEST_ROOT/next"\'}')
    if extra:
        parts.insert(0, '{literal = ' + json.dumps(extra) + '}')
    spec = '\n'.join([
        "# Synthetic procedure", "## Composition", "```toml", "[sources.guard]",
        'path = "guard.md"', f'sha256 = "{hashlib.sha256(guard).hexdigest()}"',
        "[[steps]]", 'name = "guarded"',
        'stdout = ' + json.dumps(["drift-checked"] * (2 if calls == "twice" else 1)
                                + ["next-command"]), "parts = [",
        '{literal = ' + json.dumps('set -Eeuo pipefail\nDRIFT_STDOUT_HEX=UNREVIEWED\n'
                                  'DRIFT_TOOL_SHA256=UNREVIEWED\n'
                                  'DRIFT_CAPTURE="$TEST_ROOT/first"') + '},',
        ",\n".join(parts), "]", "```", "",
    ])
    path = tmp_path / "procedure.md"
    path.write_bytes(spec.encode())
    return path


def _run(tmp_path: Path, *, stdout: bytes = SYNTHETIC, stderr: bytes = b"", status: int = 0,
         calls: str = "once", digest: str | None = None, mutate: tuple[str, str] | None = None,
         second_stdout: bytes | None = None, launch_error: bool = False,
         expected_stdout: bytes = SYNTHETIC):
    # Synthetic primitive, explicitly unrelated to private host bytes. Binary I/O
    # avoids CRLF even when the very same portable test executes on Windows.
    tool = tmp_path / "synthetic-drift.py"
    tool.write_bytes(("import os, sys\n"
                      "from pathlib import Path\n"
                      "prior = Path(os.environ['TEST_ROOT'], 'invoked')\n"
                      "second = prior.exists()\n"
                      "with Path(os.environ['TEST_ROOT'], 'invoked').open('ab') as f: "
                      "f.write(b'x')\n"
                      f"sys.stdout.buffer.write({second_stdout!r} if second and "
                      f"{second_stdout is not None!r} else {stdout!r})\n"
                      f"sys.stderr.buffer.write({stderr!r})\n"
                      f"raise SystemExit({status})\n").encode())
    values = {"DRIFT_STDOUT_HEX": expected_stdout.hex(), "DRIFT_TOOL_SHA256":
              digest or hashlib.sha256(tool.read_bytes()).hexdigest()}
    out = tmp_path / "package"
    package.build(_procedure(tmp_path, calls), out, values=values)
    script = (out / "guarded.sh").read_bytes().decode()
    # Replace only the host interpreter and executable, at their actual boundary.
    script = script.replace("/usr/bin/python3", shlex.quote(Path(sys.executable).as_posix()))
    script = script.replace('subprocess.run([str(tool)]',
                            'subprocess.run([sys.executable, str(tool)]')
    script = script.replace('Path("/usr/local/bin/m8-host-drift")',
                            f"Path({tool.as_posix()!r})")
    if launch_error:
        script = script.replace('subprocess.run([sys.executable, str(tool)]',
                                'subprocess.run([str(tool.parent / "absent-executable")]')
    if mutate:
        before, after = mutate
        assert script.count(before) == 1
        script = script.replace(before, after)
    (out / "guarded.sh").write_bytes(script.encode())
    ran = subprocess.run([git_bash(), str(out / "guarded.sh")], stdin=subprocess.DEVNULL,
                         capture_output=True, timeout=30,
                         env={**os.environ, "TEST_ROOT": tmp_path.as_posix()})
    return ran


@pytest.mark.parametrize("calls", ["once", "conditional", "condition", "twice"])
def test_synthetic_acceptance_retains_complete_output_and_status(tmp_path, calls):
    ran = _run(tmp_path, calls=calls)
    count = 2 if calls == "twice" else 1
    assert (ran.returncode, ran.stdout, ran.stderr) == (
        0, b"drift-checked\n" * count + b"next-command\n", b"")
    expected = json.loads((tmp_path / "package/guarded.expected.json").read_bytes())
    assert expected == {"alternatives": [["drift-checked"] * count + ["next-command"]],
                        "record": None}
    assert (tmp_path / "invoked").read_bytes() == b"x" * count
    assert (tmp_path / "next").read_bytes() == b"x"
    for name in (["first", "second"] if calls == "twice" else ["first"]):
        record = tmp_path / name
        assert (record / "stdout").read_bytes() == SYNTHETIC
        assert (record / "stderr").read_bytes() == b""
        assert json.loads((record / "status.json").read_bytes()) == {
            "launch_requested": True, "returncode": 0}


@pytest.mark.parametrize(("stdout", "stderr", "status"), [
    (b"Synthetic no drift: a different plausible affirmative line.\n", b"", 0),
    (SYNTHETIC + b"extra\n", b"", 0),
    (SYNTHETIC[:-1], b"", 0),
    (SYNTHETIC.replace(b"\n", b"\r\n"), b"", 0),
    (SYNTHETIC, b"synthetic host warning\n", 0),
    (SYNTHETIC, b"", 2),
    (b"x" * 4097 + b"\n", b"", 0),
])
@pytest.mark.parametrize("calls", ["once", "conditional", "condition", "twice"])
def test_unexpected_synthetic_output_stops_before_next_command(tmp_path, stdout, stderr,
                                                              status, calls):
    ran = _run(tmp_path, stdout=stdout, stderr=stderr, status=status, calls=calls)
    assert ran.returncode != 0
    assert (ran.stdout, ran.stderr) == (b"", b"drift-guard-refused\n")
    assert not (tmp_path / "next").exists()
    assert not (tmp_path / "second").exists()
    assert (tmp_path / "invoked").read_bytes() == b"x"
    record = tmp_path / "first"
    assert (record / "stdout").read_bytes() == stdout
    assert (record / "stderr").read_bytes() == stderr
    assert json.loads((record / "status.json").read_bytes()) == {
        "launch_requested": True, "returncode": status}


def test_tool_digest_mismatch_refuses_without_executing(tmp_path):
    ran = _run(tmp_path, digest="0" * 64)
    assert (ran.returncode, ran.stdout, ran.stderr) == (1, b"", b"drift-guard-refused\n")
    assert not (tmp_path / "invoked").exists()
    assert not (tmp_path / "next").exists()
    assert json.loads((tmp_path / "first/status.json").read_bytes()) == {
        "launch_requested": False, "returncode": None}


def test_launch_exception_keeps_requested_true_and_status_unknown(tmp_path):
    ran = _run(tmp_path, launch_error=True)
    assert (ran.returncode, ran.stdout, ran.stderr) == (1, b"", b"drift-guard-refused\n")
    assert not (tmp_path / "next").exists()
    assert json.loads((tmp_path / "first/status.json").read_bytes()) == {
        "launch_requested": True, "returncode": None}


def test_second_diagnostic_call_has_its_own_gate_and_capture(tmp_path):
    different = b"Synthetic affirmative drift verdict changed between two calls.\n"
    ran = _run(tmp_path, calls="twice", second_stdout=different)
    assert (ran.returncode, ran.stdout, ran.stderr) == (
        1, b"drift-checked\n", b"drift-guard-refused\n")
    assert (tmp_path / "invoked").read_bytes() == b"xx"
    assert (tmp_path / "first/stdout").read_bytes() == SYNTHETIC
    assert (tmp_path / "second/stdout").read_bytes() == different
    assert not (tmp_path / "next").exists()


@pytest.mark.parametrize("occupied", ["directory", "file", "symlink"])
def test_capture_is_exclusive_and_occupied_target_is_untouched(tmp_path, occupied):
    target = tmp_path / "first"
    if occupied == "directory":
        target.mkdir()
        (target / "preserved").write_bytes(b"kept")
    elif occupied == "file":
        target.write_bytes(b"kept")
    else:
        destination = tmp_path / "destination"
        destination.mkdir()
        try:
            target.symlink_to(destination, target_is_directory=True)
        except OSError:
            pytest.skip("creating a symlink requires Windows developer mode")
    ran = _run(tmp_path)
    assert (ran.returncode, ran.stdout, ran.stderr) == (1, b"", b"drift-guard-refused\n")
    assert not (tmp_path / "invoked").exists()
    assert not (tmp_path / "next").exists()
    if occupied == "directory":
        assert (target / "preserved").read_bytes() == b"kept"
        assert list(target.iterdir()) == [target / "preserved"]
    elif occupied == "file":
        assert target.read_bytes() == b"kept"
    else:
        assert list(destination.iterdir()) == []


@pytest.mark.parametrize("value", ["", "00", "0A", "0a", "abc", "zz",
                                   "780d0a", "78000a", "780a790a", "ff0a",
                                   "78" * 4096 + "0a", "$(id)"])
def test_drift_expectation_has_one_bounded_canonical_byte_shape(value):
    with pytest.raises(package.Refused, match="drift stdout"):
        package._checked({"DRIFT_STDOUT_HEX": value})


def test_exact_byte_bound_and_shell_metacharacters_are_data():
    value = (b"x" * 4095 + b"\n").hex()
    assert package._checked({"DRIFT_STDOUT_HEX": value}) == {"DRIFT_STDOUT_HEX": value}
    value = b"Synthetic ' \" $() ` & ; | \\ text\n".hex()
    assert package._checked({"DRIFT_STDOUT_HEX": value}) == {"DRIFT_STDOUT_HEX": value}


def test_private_values_file_and_filled_bytes_round_trip(tmp_path):
    value = b"Synthetic ' \" $() ` & ; | \\ text\n".hex()
    private = tmp_path / "values.toml"
    private.write_bytes((f'DRIFT_STDOUT_HEX = "{value}"\n'
                         f'DRIFT_TOOL_SHA256 = "{"1" * 64}"\n').encode())
    values = package.session_values(private)
    steps = package.assemble(_procedure(tmp_path), values=values)
    assert f"readonly DRIFT_STDOUT_HEX={value}\n" in steps[0].text
    assert f"readonly DRIFT_TOOL_SHA256={'1' * 64}\n" in steps[0].text
    assert bytes.fromhex(values["DRIFT_STDOUT_HEX"]) == bytes.fromhex(value)
    assert "UNREVIEWED" not in steps[0].text


def test_shell_metacharacters_remain_exact_private_output_bytes(tmp_path):
    sentence = b"Synthetic ' \" $(exit 91) `exit 92` & ; | \\ text\n"
    ran = _run(tmp_path, stdout=sentence, expected_stdout=sentence)
    assert (ran.returncode, ran.stdout, ran.stderr) == (
        0, b"drift-checked\nnext-command\n", b"")
    assert (tmp_path / "first/stdout").read_bytes() == sentence


def test_guard_requires_an_exact_expected_lf():
    with pytest.raises(package.Refused, match="drift stdout"):
        package._checked({"DRIFT_STDOUT_HEX": b"Synthetic no final LF".hex()})


def test_guard_requires_printable_text_without_extra_lines():
    with pytest.raises(package.Refused, match="drift stdout"):
        package._checked({"DRIFT_STDOUT_HEX": b"Synthetic\nextra\n".hex()})


def test_guard_expectation_bound_binds():
    with pytest.raises(package.Refused, match="drift stdout"):
        package._checked({"DRIFT_STDOUT_HEX": (b"x" * 4096 + b"\n").hex()})


@pytest.mark.parametrize("extra", [
    "/usr/local/bin/m8-host-drift", '"/usr/local/bin/m8-host-"drift',
    "/usr/local/bin/m8-host-\\drift", "sudo /usr/local/bin/m8-host-drift",
    "if true; then /usr/local/bin/m8-host-drift; fi",
    # A matched count elsewhere is not proof that this direct call was guarded.
    "DRIFT_CAPTURE=x; /usr/local/bin/m8-host-drift",
])
def test_every_direct_call_outside_exact_reviewed_guard_refuses(tmp_path, extra):
    with pytest.raises(package.Refused, match="reviewed drift-guard"):
        package.assemble(_procedure(tmp_path, extra=extra), template=True)


def test_reviewed_guard_does_not_authorize_an_extra_direct_call(tmp_path):
    with pytest.raises(package.Refused, match="reviewed drift-guard"):
        package.assemble(_procedure(tmp_path, extra="/usr/local/bin/m8-host-drift"), template=True)


def test_shell_fragments_cannot_hide_an_unguarded_drift_call(tmp_path):
    with pytest.raises(package.Refused, match="reviewed drift-guard"):
        package.assemble(_procedure(tmp_path, extra='"/usr/local/bin/m8-host-"drift'),
                         template=True)


def test_guard_review_standing_is_its_exact_bytes(tmp_path):
    path = _procedure(tmp_path)
    changed = HANDOFF.read_bytes().replace(b"status != 0", b"status == 0")
    assert changed != HANDOFF.read_bytes()
    (tmp_path / "guard.md").write_bytes(changed)
    text = path.read_bytes().decode().replace(hashlib.sha256(HANDOFF.read_bytes()).hexdigest(),
                                            hashlib.sha256(changed).hexdigest())
    path.write_bytes(text.encode())
    with pytest.raises(package.Refused, match="reviewed drift-guard"):
        package.assemble(path, template=True)


def test_historical_q12_assembly_exception_requires_exact_document_bytes(monkeypatch):
    historical = HANDOFF.with_name("M8-maintenance-q12-continuation.md")
    original = Path.read_bytes
    assert len(package.assemble(historical)) == 19
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b"\n"
                        if path == historical else original(path))
    with pytest.raises(package.Refused, match="reviewed drift-guard"):
        package.assemble(historical)


@pytest.mark.parametrize(("before", "after", "arguments"), [
    ("or actual != expected", "or False", {"stdout": b"Synthetic changed verdict.\n"}),
    ("or diagnostic", "or False", {"stderr": b"Synthetic warning\n"}),
    ("status != 0", "False", {"status": 2}),
    ('if hashlib.sha256(tool.read_bytes()).hexdigest() != digest:', 'if False:',
     {"digest": "0" * 64}),
    ('result["launch_requested"] = True', 'pass', {"launch_error": True}),
    ('stdout.read(4097)', 'stdout.read(len(expected))',
     {"stdout": SYNTHETIC + b"extra\n"}),
])
def test_each_guard_fact_is_sensitive_to_an_assertion_mutation(tmp_path, before, after, arguments):
    """Run the modified production fence, then its actual outcome assertion.

    Only AssertionError counts; a syntax error, missing file or harness exception
    is never presented as a kill. The launch latch mutant changes evidence rather
    than verdict, so its assertion covers that exact evidence field.
    """
    ran = _run(tmp_path, mutate=(before, after), **arguments)
    with pytest.raises(AssertionError):
        if arguments.get("launch_error"):
            assert json.loads((tmp_path / "first/status.json").read_bytes()) == {
                "launch_requested": True, "returncode": None}
        else:
            assert ran.returncode != 0
