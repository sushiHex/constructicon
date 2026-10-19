"""Actual composed q13 export guards over disposable local platform facts.

Installed paths, service custody, interpreter location, boot/process observations
and Windows LF plumbing are fixture boundaries. No VM or vendor is contacted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package

from tests.test_m8_operator_commands import _bash

ROOT = Path(__file__).resolve().parents[1]
HANDOFFS = ROOT / "docs/plans/handoffs"
DOCUMENT = HANDOFFS / "M8-q13-candidate-transfer.md"
BOOT = "934acecb-9042-4e02-845e-050a4d071265"
BASE = "5793ef98ef5597c9ee9811a0d1f031554eb7f514"


def fences(path, heading, language="bash"):
    return [body for lang, body in package.fences(package.section(
        path.read_bytes().decode(), heading)) if lang == language]


def steps():
    return {step.name: step for step in package.assemble(
        DOCUMENT, values={"EXPECTED_BOOT": BOOT})}


def test_boot_is_required_and_frozen_guards_are_selected_unchanged(tmp_path):
    waiting = package.assemble(DOCUMENT)
    assert len(waiting) == 2 and all(step.waiting for step in waiting)
    built = tmp_path / "waiting"
    package.build(DOCUMENT, built)
    assert list(built.iterdir()) == [built / "MANIFEST.sha256"]
    common, = fences(HANDOFFS / "M8-maintenance-diagnosis.md",
                     "D1: installed provenance, drift and no execution startup")[1:]
    record, = fences(HANDOFFS / "M8-maintenance-q12-continuation.md", "Q4: private host records")
    r19, = fences(HANDOFFS / "M8-N4-host-runtime.md", "R19 — Import check as `m8-service`")
    template = {step.name: step.text for step in package.assemble(DOCUMENT, template=True)}
    assert all(common in text for text in template.values())
    assert r19 in template["q13-export-preflight"]
    assert record in template["q13-export-preflight"]
    assert "m8-host-drift" not in "".join(template.values())
    assert "EXPECTED_BOOT=UNREVIEWED" not in "".join(step.text for step in steps().values())


def test_build_is_lf_manifest_covered_and_every_shell_fence_parses(tmp_path):
    output = tmp_path / "package"
    digest = package.build(DOCUMENT, output, values={"EXPECTED_BOOT": BOOT})
    manifest = (output / "MANIFEST.sha256").read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == digest
    assert len(manifest.splitlines()) == 4
    for line in manifest.decode().splitlines():
        expected, name = line.split("  ")
        raw = (output / name).read_bytes()
        assert b"\r" not in raw and hashlib.sha256(raw).hexdigest() == expected
    for step in steps().values():
        ran = subprocess.run([_bash(), "-n"], input=step.text.encode(),
                             capture_output=True, timeout=30, check=False)
        assert (ran.returncode, ran.stdout, ran.stderr) == (0, b"", b"")
    transport, = fences(DOCUMENT, "Exact closed transport")
    ran = subprocess.run([_bash(), "-n"], input=transport.encode(),
                         capture_output=True, timeout=30, check=False)
    assert ran.returncode == 0 and ran.stderr == b""
    for option in ("BatchMode=yes", "StrictHostKeyChecking=yes", "HostKeyAlias=",
                   "ConnectTimeout=15", "LogLevel=ERROR"):
        assert option in transport
    assert "PACKAGE.sha256" in transport and "MANIFEST.sha256" not in transport
    assert " capture --out " in transport and "transport.py" in transport


def portable(text, tmp_path):
    """Only the installed platform's path/custody/newline primitives change."""
    controller = (ROOT / "src").as_posix()
    purelib = sysconfig.get_paths()["purelib"].replace("\\", "/")
    text = text.replace("/usr/bin/python3", shlex.quote(Path(sys.executable).as_posix()))
    text = text.replace("/proc/sys/kernel/random/boot_id", (tmp_path / "boot").as_posix())
    text = text.replace("/usr/bin/pgrep -u m8-service", 'test "$TEST_ACTIVE" = yes')
    text = text.replace('sys.path.insert(0, "/opt/constructicon-m8-controller")',
                        f"sys.path[:0] = {json.dumps(controller)}, {json.dumps(purelib)}")
    text = text.replace('"/opt/constructicon-m8-controller/",',
                        f"{json.dumps(controller + '/')}, {json.dumps(purelib + '/')},")
    if os.name == "nt":
        for name in ("stdlib", "platstdlib"):
            text = text.replace(f'sysconfig.get_paths()["{name}"] + "/"',
                                f'sysconfig.get_paths()["{name}"].replace("\\\\", "/") + "/"')
        text = text.replace("roots = (", "roots = (" + json.dumps(
            (Path(sys.base_prefix) / "DLLs").as_posix() + "/") + ",")
        text = text.replace("f.startswith(roots)", 'f.replace("\\\\", "/").startswith(roots)')
        text = text.replace("info.st_uid == os.getuid()", "True")
        text = text.replace("assert info.st_mode & 0o077 == 0", "assert True")
        text = text.replace("os.O_NOFOLLOW | os.O_NONBLOCK", "0")
        # The real host is POSIX. Exercise the unchanged JSON record grammar
        # using LF bytes instead of Windows Python's text-mode CRLF output.
        before = ('print(json.dumps({"files": len(files), "outside": outside, '
                  '"passed": not outside}))')
        after = ('sys.stdout.buffer.write((json.dumps({"files": len(files), '
                 '"outside": outside, "passed": not outside}) + "\\n").encode())')
        text = text.replace(before, after)
    override = ('sudo() { if test "$1" = -n; then shift; fi; '
                'if test "$1" = -u; then shift 2; fi; "$@"; }\n')
    return override + text


def run_step(tmp_path, text, *, active="no"):
    script = tmp_path / "step.sh"
    script.write_bytes(portable(text, tmp_path).encode())
    return subprocess.run([_bash(), script.as_posix()], stdin=subprocess.DEVNULL,
        capture_output=True, timeout=60, check=False,
        env={**os.environ, "HOME": tmp_path.as_posix(), "TEST_ACTIVE": active})


def helper_package(tmp_path):
    directory = tmp_path / "maintenance-q13-export-package"
    directory.mkdir()
    (tmp_path / "boot").write_bytes((BOOT + "\n").encode())
    return directory


def test_actual_preflight_composition_checks_records_and_emits_only_marker(tmp_path):
    directory = helper_package(tmp_path)
    verifier_root = tmp_path / "m8-controller"
    verifier_root.mkdir()
    verifier = verifier_root / "m8_host_artifacts.py"
    record = {"schema_version": 2, "command": "verify-controller", "commit": BASE,
              "first_parent": True, "script_matches_commit": True, "installed": True,
              "observed": {"/opt/constructicon-m8-controller": {
                  "uid": 0, "state": "tree", "different": 0, "differences": []}}}
    verifier.write_bytes(("import sys\nsys.stdout.buffer.write(" + repr(
        (json.dumps(record) + "\n").encode()) + ")\n").encode())
    text = steps()["q13-export-preflight"].text
    # The installed verifier's bytes/facts are the unavailable host primitive.
    text = text.replace("c3c714b2f6c1d1c62c9e1e9c31c6851277c6b661ee9c983efbceaa255911c856",
                        hashlib.sha256(verifier.read_bytes()).hexdigest())
    ran = run_step(tmp_path, text)
    assert ran.returncode == 0 and ran.stderr == b"", ran.stderr
    assert ran.stdout == b"candidate-source-preflight-checked\n"
    assert (directory / "records/preflight.ok").read_bytes() == (BOOT + "\n" + BASE + "\n").encode()
    checked = json.loads((directory / "records/import/check.json").read_bytes())
    assert checked["passed"] is True and checked["outside"] == [] and checked["files"] > 0


@pytest.mark.parametrize("case", ["accept", "missing-preflight", "wrong-preflight", "wrong-boot",
                                  "active", "outside-import"])
def test_actual_export_bootstrap_and_guards(tmp_path, case):
    directory = helper_package(tmp_path)
    records = directory / "records"
    records.mkdir()
    if case != "missing-preflight":
        (records / "preflight.ok").write_bytes((BOOT + "\n" + (
            "b" * 40 if case == "wrong-preflight" else BASE) + "\n").encode())
    if case == "wrong-boot":
        (tmp_path / "boot").write_bytes(b"00000000-0000-0000-0000-000000000000\n")
    payload = ('import hashlib,json,sys\n'
               'def main(args):\n'
               '    sys.stdout.buffer.write(json.dumps({"sha256":hashlib.sha256('
               'sys.argv[1].encode()).hexdigest(),"args":args}).encode()+b"\\n")\n'
               '    return 0\n')
    if case == "outside-import":
        # An imported file outside controller/stdlib roots must stop before main.
        payload = ('import sys,types\nv=types.ModuleType("outside")\n'
                   'v.__file__="/outside/private.py"\nsys.modules["outside"]=v\n') + payload
    (directory / "m8_candidate_transfer.py").write_bytes(payload.encode())
    ran = run_step(tmp_path, steps()["q13-export-candidate"].text,
                   active="yes" if case == "active" else "no")
    if case == "accept":
        assert ran.returncode == 0 and ran.stderr == b"", ran.stderr
        value = json.loads(ran.stdout)
        assert value["sha256"] == hashlib.sha256(payload.encode()).hexdigest()
        assert value["args"] == ["export", "--root", "/home/m8-service/m8-maint-a5"]
    else:
        assert ran.returncode != 0 and ran.stdout == b""
        if case == "outside-import":
            assert b"candidate-transfer-import-refused" in ran.stderr


@pytest.mark.parametrize("helper_newlines", ["lf", "crlf"])
def test_documented_preparation_reads_reviewed_blob_and_covers_staged_helper(
    tmp_path, helper_newlines,
):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    documents = (DOCUMENT, *(HANDOFFS / name for name in (
        "M8-maintenance-diagnosis.md", "M8-maintenance-q12-continuation.md",
        "M8-N4-host-runtime.md")))
    files = [*documents, ROOT / "scripts/m8_procedure_package.py",
             ROOT / "scripts/m8_candidate_transfer.py", ROOT / "docs/plans/MANIFEST.sha256"]
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(checkout), *arguments],
            stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30, env=environment)

    git("init", "--quiet", "--template=")
    # Model Git's LF index independently from the platform's working-copy
    # spelling. Retain the conversion setting for the real prepare/status call.
    git("config", "core.autocrlf", "input")
    helper_lf = (ROOT / "scripts/m8_candidate_transfer.py").read_bytes().replace(b"\r\n", b"\n")
    assert b"\r" not in helper_lf
    helper_working = helper_lf.replace(b"\n", b"\r\n") if helper_newlines == "crlf" else helper_lf
    for path in files:
        target = checkout / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(helper_working if path.name == "m8_candidate_transfer.py"
                           else path.read_bytes())
    git("-c", "core.autocrlf=input", "add", ".")
    git("-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c",
        "commit.gpgSign=false", "-c", "core.hooksPath=" + os.devnull,
        "commit", "--quiet", "-m", "fixture")
    revision = git("rev-parse", "HEAD").decode().strip()
    reviewed_helper = git("show", revision + ":scripts/m8_candidate_transfer.py")
    assert reviewed_helper == helper_lf and b"\r" not in reviewed_helper
    assert (checkout / "scripts/m8_candidate_transfer.py").read_bytes() == helper_working
    program, = fences(DOCUMENT, "Exact local preparation", "python")
    prepare = tmp_path / "prepare.py"
    prepare.write_bytes(program.encode())
    values = tmp_path / "values.toml"
    values.write_bytes(f'EXPECTED_BOOT = "{BOOT}"\n'.encode())
    output = tmp_path / "package"
    argv = [sys.executable, "-I", "-S", "-B", str(prepare), str(checkout), str(output),
            str(values), revision]
    ran = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                         timeout=30, check=False, env=environment)
    assert ran.returncode == 0 and ran.stderr == b"", ran.stderr
    manifest = (output / "PACKAGE.sha256").read_bytes()
    assert ran.stdout.strip().decode() == hashlib.sha256(manifest).hexdigest()
    names = []
    for line in manifest.decode().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
        names.append(name)
    assert len(names) == 7
    assert {"m8_candidate_transfer.py", "transport.py", "MANIFEST.sha256"} <= set(names)
    assert (output / "m8_candidate_transfer.py").read_bytes() == reviewed_helper
    assert (checkout / "scripts/m8_candidate_transfer.py").read_bytes() == helper_working
    # The reviewed revision cannot silently bless a dirty tracked helper.
    (checkout / "scripts/m8_candidate_transfer.py").write_bytes(b"unexpected\n")
    dirty = subprocess.run([*argv[:6], str(tmp_path / "dirty-output"), *argv[7:]],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                           check=False, env=environment)
    assert dirty.returncode != 0 and not (tmp_path / "dirty-output").exists()


@pytest.mark.parametrize("case", ["accept", "changed-helper", "preflight-refused"])
def test_exact_closed_transport_joins_manifests_t5_and_capture_argv(tmp_path, case):
    """SSH/SCP are local argv recorders; the preflight uses the actual frozen T5.

    Actual q13 bytes are unavailable locally, so final capture dispatch is a
    named fixture boundary. Its real byte/EOF/deadline pump has separate proofs.
    """
    output = tmp_path / "package"
    package.build(DOCUMENT, output, values={"EXPECTED_BOOT": BOOT})
    transport, = fences(HANDOFFS / "M8-maintenance-q12-continuation.md",
                         "Q6: transport T5", "python")
    (output / "transport.py").write_bytes(transport.encode())
    (output / "m8_candidate_transfer.py").write_bytes(
        (ROOT / "scripts/m8_candidate_transfer.py").read_bytes())
    manifest = "".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n"
                       for path in sorted(output.iterdir())).encode()
    (output / "PACKAGE.sha256").write_bytes(manifest)
    digest = hashlib.sha256(manifest).hexdigest()
    if case == "changed-helper":
        (output / "m8_candidate_transfer.py").write_bytes(b"changed\n")
    trace = tmp_path / "trace.jsonl"
    stub = tmp_path / "transport-platform.py"
    stub.write_bytes(('import json,sys\nfrom pathlib import Path\n'
        f'with Path({str(trace)!r}).open("a",encoding="utf-8") as out:\n'
        '    out.write(json.dumps(sys.argv[1:])+"\\n")\n'
        'assert not sys.stdin.buffer.read()\n'
        'if sys.argv[1]=="ssh" and "q13-export-preflight.sh" in sys.argv[-1]:\n'
        + ('    sys.stdout.buffer.write(b"unexpected-preflight\\n")\n'
           if case == "preflight-refused" else
           '    sys.stdout.buffer.write(b"candidate-source-preflight-checked\\n")\n')
        + 'if sys.argv[1]=="capture":\n'
        '    sys.stdout.buffer.write(b"capture-dispatched\\n")\n').encode())
    text, = fences(DOCUMENT, "Exact closed transport")
    selection, = [line for line in text.splitlines() if line.startswith("SSH=")]
    text = text.replace(selection, 'SSH="$TEST_PY"')
    text = text.replace('"$SSH" -T', '"$SSH" "$TEST_STUB" ssh -T')
    # Replace only the platform interpreter/SSH/SCP and final capture dispatch;
    # leave the frozen T5 and every remaining command/join intact.
    text = text.replace("uv run python scripts/m8_candidate_transfer.py capture",
                        '"$TEST_PY" -I -S -B "$TEST_STUB" capture')
    text = text.replace("uv run python", '"$TEST_PY" -I -S -B')
    text = 'scp() { "$TEST_PY" -I -S -B "$TEST_STUB" scp "$@"; }\n' + text
    script = tmp_path / "transport.sh"
    script.write_bytes(text.encode())
    ran = subprocess.run([_bash(), script.as_posix()], stdin=subprocess.DEVNULL,
        capture_output=True, timeout=30, check=False, env={**os.environ,
        "PACKAGE": output.as_posix(), "CAPTURE": (tmp_path / "capture").as_posix(),
        "SSH_TARGET": "private-example.invalid", "SSH_HOST_KEY_ALIAS": "retained-alias",
        "PACKAGE_SHA256": digest, "TEST_PY": Path(sys.executable).as_posix(),
        "TEST_STUB": stub.as_posix()})
    rows = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    if case == "changed-helper":
        assert ran.returncode != 0 and rows == []
        return
    assert [row[0] for row in rows] == ["ssh", "scp", "ssh"] + (
        ["capture"] if case == "accept" else [])
    for row in rows:
        for option in ("BatchMode=yes", "StrictHostKeyChecking=yes",
                       "HostKeyAlias=retained-alias", "ConnectTimeout=15", "LogLevel=ERROR"):
            assert option in row
    preflight = rows[2][-1]
    assert digest in preflight and "PACKAGE.sha256" in preflight
    assert preflight.endswith("&& bash q13-export-preflight.sh")
    if case == "accept":
        assert ran.returncode == 0 and ran.stderr == b"", ran.stderr
        assert ran.stdout == b"transport-step-checked 0\ncapture-dispatched\n"
        capture = rows[-1]
        assert capture[1:4] == ["--out", (tmp_path / "capture").as_posix(), "--"]
        assert capture[-1].endswith("&& bash q13-export-candidate.sh")
        assert digest in capture[-1] and "sha256sum --check --strict --quiet" in capture[-1]
    else:
        assert ran.returncode != 0 and ran.stdout == b"transport-step-refused\n"
