"""Synthetic host interface evidence, never a measurement of the private host.

The exact reviewed guard is assembled by the real packager, then executed by
Bash. Host-bound primitives (Python and the drift executable) are replaced;
descendant cases also instrument drain/comparison boundaries for synchronization.
Every synthetic success has different plausible output that the same step
refuses; no stub here is evidence of the installed tool's interface.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shlex
import socket
import subprocess
import sys
import threading
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
    script = script.replace('subprocess.Popen([str(tool)]',
                            'subprocess.Popen([sys.executable, str(tool)]')
    script = script.replace('Path("/usr/local/bin/m8-host-drift")',
                            f"Path({tool.as_posix()!r})")
    if launch_error:
        script = script.replace('subprocess.Popen([sys.executable, str(tool)]',
                                'subprocess.Popen([str(tool.parent / "absent-executable")]')
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


def _two_guarded_steps(tmp_path: Path, change: tuple[str, str] | None = None) -> Path:
    path = _procedure(tmp_path)
    original = path.read_bytes().decode()
    step = original.split("[[steps]]", 1)[1].rsplit("```", 1)[0]
    step = step.replace('name = "guarded"', 'name = "second-guarded"')
    if change:
        before, after = change
        assert step.count(before) == 1
        step = step.replace(before, after)
    path.write_bytes((original.rsplit("```", 1)[0] + "[[steps]]" + step + "```\n").encode())
    return path


PRIVATE_VALUES = {"DRIFT_STDOUT_HEX": SYNTHETIC.hex(), "DRIFT_TOOL_SHA256": "1" * 64}


def test_each_guarded_step_declares_and_fills_its_own_private_values(tmp_path):
    steps = package.assemble(_two_guarded_steps(tmp_path), values=PRIVATE_VALUES)
    assert len(steps) == 2
    for step in steps:
        for key, value in PRIVATE_VALUES.items():
            assert step.text.count(f"readonly {key}={value}\n") == 1


@pytest.mark.parametrize("key", ["DRIFT_STDOUT_HEX", "DRIFT_TOOL_SHA256"])
@pytest.mark.parametrize("replacement", ["", ": ${KEY?}", "KEY=UNREVIEWED\\nKEY=UNREVIEWED"])
def test_guarded_steps_cannot_borrow_or_duplicate_another_steps_private_fill(
    tmp_path, key, replacement,
):
    replacement = replacement.replace("KEY", key)
    path = _two_guarded_steps(tmp_path, (f"{key}=UNREVIEWED", replacement))
    with pytest.raises(package.Refused, match="exactly one private declaration"):
        package.assemble(path, values=PRIVATE_VALUES)


def test_guard_without_private_declarations_cannot_use_literal_values(tmp_path):
    path = _procedure(tmp_path)
    text = path.read_bytes().decode().replace("DRIFT_STDOUT_HEX=UNREVIEWED",
                                            "DRIFT_STDOUT_HEX=780a")
    text = text.replace("DRIFT_TOOL_SHA256=UNREVIEWED", "DRIFT_TOOL_SHA256=" + "1" * 64)
    path.write_bytes(text.encode())
    with pytest.raises(package.Refused, match="exactly one private declaration"):
        package.assemble(path)


def test_guard_cannot_duplicate_a_private_declaration(tmp_path):
    path = _two_guarded_steps(tmp_path, (
        "DRIFT_STDOUT_HEX=UNREVIEWED",
        "DRIFT_STDOUT_HEX=UNREVIEWED\\nDRIFT_STDOUT_HEX=UNREVIEWED",
    ))
    with pytest.raises(package.Refused, match="exactly one private declaration"):
        package.assemble(path, values=PRIVATE_VALUES)


@pytest.mark.parametrize("template", [False, True])
def test_deferred_or_template_guard_still_requires_each_private_declaration(tmp_path, template):
    path = _procedure(tmp_path)
    text = path.read_bytes().decode().replace('name = "guarded"',
                                            'name = "guarded"\ndeferred = true')
    text = text.replace("DRIFT_TOOL_SHA256=UNREVIEWED", ": ${DRIFT_TOOL_SHA256?}")
    path.write_bytes(text.encode())
    with pytest.raises(package.Refused, match="exactly one private declaration"):
        package.assemble(path, template=template)


@pytest.mark.parametrize("key", ["DRIFT_STDOUT_HEX", "DRIFT_TOOL_SHA256"])
@pytest.mark.parametrize("mode", ["values", "template", "deferred"])
def test_private_declarations_must_precede_the_first_guard(tmp_path, key, mode):
    path = _procedure(tmp_path)
    text = path.read_bytes().decode().replace(f"{key}=UNREVIEWED", "")
    literal = "{literal = " + json.dumps(f"{key}=UNREVIEWED") + "},"
    assert text.count("fences = [0]},") == 1
    text = text.replace("fences = [0]},", "fences = [0]},\n" + literal)
    if mode == "deferred":
        text = text.replace('name = "guarded"', 'name = "guarded"\ndeferred = true')
    path.write_bytes(text.encode())
    with pytest.raises(package.Refused, match="before its first reviewed drift guard"):
        package.assemble(path, template=mode == "template",
                         values=PRIVATE_VALUES if mode == "values" else None)


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


def _descendant_run(tmp_path, stream, *, mutation=None, drain_failure=None):
    """Test-only socket barriers: no sleep decides whether a writer finished.

    A descendant holds inherited output open until the guard either awaits EOF
    or prematurely passes validation. The latter releases its bytes only after
    that decision, deterministically reproducing the old regular-file race.
    Instrumentation observes standard futures/copy boundaries and the existing
    comparison; it supplies no verdict and changes no captured byte.
    """
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    events = queue.Queue()

    def line(connection):
        raw = bytearray()
        while len(raw) < 128 and not raw.endswith(b"\n"):
            part = connection.recv(1)
            if not part:
                raise OSError("test synchronization closed")
            raw.extend(part)
        if not raw.endswith(b"\n"):
            raise OSError("test synchronization line too long")
        return bytes(raw)

    def accept():
        try:
            while True:
                connection, _ = listener.accept()
                connection.settimeout(15)
                raw = line(connection)
                events.put((raw.decode().strip(), connection))
        except OSError:
            pass

    threading.Thread(target=accept, daemon=True).start()
    tool = tmp_path / "descendant-drift.py"
    tool.write_bytes((
        "import os, socket, subprocess, sys\n"
        "if len(sys.argv) == 1:\n"
        f"    os.write(1, {SYNTHETIC!r})\n"
        "    subprocess.Popen([sys.executable, __file__, 'writer'], stdin=subprocess.DEVNULL,\n"
        "                     stdout=sys.stdout, stderr=sys.stderr)\n"
        "    os._exit(0)\n"
        f"stream = {stream!r}\n"
        "if stream == 'stdout': os.close(2)\n"
        "if stream == 'stderr': os.close(1)\n"
        "with socket.create_connection(('127.0.0.1', int(os.environ['TEST_SYNC'])), "
        "15) as control:\n"
        "    control.sendall(b'writer-ready\\n')\n"
        "    assert control.recv(1) == b'g'\n"
        "    if stream != 'silent':\n"
        "        os.write(1 if stream == 'stdout' else 2, b'synthetic descendant line\\n')\n"
        "    if stream != 'stderr': os.close(1)\n"
        "    if stream != 'stdout': os.close(2)\n"
        "    control.sendall(b'writer-finished\\n')\n"
        "os._exit(0)\n"
    ).encode())
    values = {"DRIFT_STDOUT_HEX": SYNTHETIC.hex(),
              "DRIFT_TOOL_SHA256": hashlib.sha256(tool.read_bytes()).hexdigest()}
    out = tmp_path / "package"
    package.build(_procedure(tmp_path), out, values=values)
    script = (out / "guarded.sh").read_bytes().decode()
    script = script.replace("/usr/bin/python3", shlex.quote(Path(sys.executable).as_posix()))
    for primitive in ("run", "Popen"):
        script = script.replace(f"subprocess.{primitive}([str(tool)]",
                                f"subprocess.{primitive}([sys.executable, str(tool)]")
    script = script.replace('Path("/usr/local/bin/m8-host-drift")', f"Path({tool.as_posix()!r})")
    synchronization = f'''
import os, shutil, socket, threading
from concurrent.futures import Future
_ready = threading.Event()
def _note(event):
    with socket.create_connection(("127.0.0.1", int(os.environ["TEST_SYNC"])), 15) as control:
        control.sendall((event + "\\n").encode())
        if control.recv(1) != b"g": raise OSError("test synchronization closed")
_result = Future.result
def _observed_result(self, *args, **kwargs):
    _note("eof-wait")
    return _result(self, *args, **kwargs)
Future.result = _observed_result
_copy = shutil.copyfileobj
def _observed_copy(source, destination, *args):
    class Destination:
        def write(self, data):
            result = destination.write(data)
            destination.flush()
            if destination.name.endswith("stdout") and destination.tell() >= {len(SYNTHETIC)}:
                _ready.set()
            return result
    _copy(source, Destination(), *args)
    if destination.name.endswith({drain_failure!r} or "never-match"):
        raise OSError("synthetic completed-drain failure")
shutil.copyfileobj = _observed_copy
def _validation(stdout):
    if os.fstat(stdout.fileno()).st_size >= {len(SYNTHETIC)}: _ready.set()
    if not _ready.wait(15): raise RuntimeError("test stdout drain did not run")
    _note("validation")
'''
    script = script.replace("from pathlib import Path\n",
                            "from pathlib import Path\n" + synchronization)
    script, matches = re.subn(r'(?m)^( +)stdout.seek\(0\)$',
                             r'\1_validation(stdout)\n\1stdout.seek(0)', script)
    assert matches == 1
    script, matches = re.subn(r'(?m)^( +)    raise ValueError\("output contract"\)$',
                             r'\1    raise ValueError("output contract")\n'
                             r'\1_note("decision-passed")', script)
    assert matches == 1
    if mutation:
        before, after = mutation
        assert script.count(before) == 1
        script = script.replace(before, after)
    path = out / "guarded.sh"
    path.write_bytes(script.encode())
    process = subprocess.Popen([git_bash(), str(path)], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env={**os.environ, "TEST_ROOT": tmp_path.as_posix(),
                                    "TEST_SYNC": str(listener.getsockname()[1])})

    def completed():
        try:
            stdout, stderr = process.communicate(timeout=20)
            events.put(("done", (process.returncode, stdout, stderr)))
        except BaseException as error:
            events.put(("error", error))

    threading.Thread(target=completed, daemon=True).start()
    writer = None
    release = False
    writer_finished = False
    observed = []
    waiting = []
    try:
        while True:
            event, detail = events.get(timeout=25)
            observed.append(event)
            if event == "error":
                raise RuntimeError("descendant test process did not complete") from detail
            if event == "done":
                return detail, observed, writer_finished
            if event == "writer-ready":
                writer = detail
            elif event in {"eof-wait", "decision-passed"}:
                release = True
                waiting.append(detail)
            else:
                detail.sendall(b"g")
                detail.close()
            if writer is not None and release:
                writer.sendall(b"g")
                assert line(writer) == b"writer-finished\n"
                writer.close()
                writer = None
                writer_finished = True
            if writer_finished:
                for connection in waiting:
                    connection.sendall(b"g")
                    connection.close()
                waiting.clear()
    finally:
        if writer is not None:
            writer.sendall(b"g")
            writer.close()
        for connection in waiting:
            connection.close()
        listener.close()
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_descendant_late_output_is_captured_before_the_guard_decides(tmp_path, stream):
    result, observed, finished = _descendant_run(tmp_path, stream)
    assert result == (1, b"", b"drift-guard-refused\n")
    assert finished
    assert observed.index("eof-wait") < observed.index("validation")
    assert (tmp_path / "first/stdout").read_bytes() == SYNTHETIC + (
        b"synthetic descendant line\n" if stream == "stdout" else b"")
    assert (tmp_path / "first/stderr").read_bytes() == (
        b"synthetic descendant line\n" if stream == "stderr" else b"")
    assert json.loads((tmp_path / "first/status.json").read_bytes()) == {
        "launch_requested": True, "returncode": 0}
    assert not (tmp_path / "next").exists()


def test_silent_descendant_closes_both_streams_before_acceptance(tmp_path):
    result, observed, finished = _descendant_run(tmp_path, "silent")
    assert result == (0, b"drift-checked\nnext-command\n", b"")
    assert finished and observed.count("eof-wait") == 2
    assert observed.index("eof-wait") < observed.index("validation")
    assert (tmp_path / "first/stdout").read_bytes() == SYNTHETIC
    assert (tmp_path / "first/stderr").read_bytes() == b""
    assert json.loads((tmp_path / "first/status.json").read_bytes()) == {
        "launch_requested": True, "returncode": 0}


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_completed_drain_exception_refuses_even_when_bytes_match(tmp_path, stream):
    result, observed, finished = _descendant_run(tmp_path, "silent", drain_failure=stream)
    assert result == (1, b"", b"drift-guard-refused\n")
    assert finished and "validation" not in observed
    assert (tmp_path / "first/stdout").read_bytes() == SYNTHETIC
    assert (tmp_path / "first/stderr").read_bytes() == b""
    assert json.loads((tmp_path / "first/status.json").read_bytes()) == {
        "launch_requested": True, "returncode": 0}
    assert not (tmp_path / "next").exists()


@pytest.mark.parametrize(("before", "stream", "failure"), [
    ("stdout_copied.result()", "silent", "stdout"),
    ("stderr_copied.result()", "silent", "stderr"),
    ("stdout_copied.result()\n                stderr_copied.result()", "stdout", None),
    ("stdout_copied.result()\n                stderr_copied.result()", "stderr", None),
])
def test_eof_and_drain_success_gates_are_assertion_sensitive(tmp_path, before, stream, failure):
    """Each removed result must fail a verdict assertion, never a harness error.

    Executor shutdown still joins threads in these mutants. That is insufficient:
    it neither propagates their exceptions nor undoes a comparison made too soon.
    The control peer releases real late bytes only after that premature decision.
    """
    result, _, finished = _descendant_run(tmp_path, stream, mutation=(before, "pass"),
                                         drain_failure=failure)
    assert finished
    assert result == (0, b"drift-checked\nnext-command\n", b"")
    with pytest.raises(AssertionError):
        assert result == (1, b"", b"drift-guard-refused\n")
    assert (tmp_path / "first/stdout").read_bytes() == SYNTHETIC + (
        b"synthetic descendant line\n" if stream == "stdout" else b"")
    assert (tmp_path / "first/stderr").read_bytes() == (
        b"synthetic descendant line\n" if stream == "stderr" else b"")
