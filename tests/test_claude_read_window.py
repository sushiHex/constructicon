"""The actual window CLI with a closed, credential-free process boundary.

Synthetic phase responses test orchestration and evidence consumption only;
the existing Linux rehearsal exercises the generated programs themselves.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.ops import claude_read_commands as commands
from scripts.ops import claude_read_session as session
from scripts.ops import claude_read_window as window

from tests.test_claude_read_session import binding_record, write

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts/ops/claude_read_window.py"
TARGET, ALIAS = "fixture@192.0.2.1", "fixture-window"

# The audit guard precedes target imports. No fixture code or process executable
# is loaded from the response file, and an unrecognized call has no fallback.
FAKE_ENTRY = r'''
import base64, json, pathlib, subprocess, sys
fixture_path = pathlib.Path(sys.argv[1])
root = sys.argv[2]
arguments = sys.argv[3:]
blocked = []
def deny_spawn(event, args):
    if event.startswith(("subprocess.", "os.exec", "os.spawn", "os.posix_spawn")) or event in (
        "os.system", "os.fork", "os.forkpty", "os.startfile", "os.startfile/2",
    ):
        blocked.append(event)
        raise RuntimeError("fixture process creation denied")
sys.addaudithook(deny_spawn)
# Prove nested spawning is refused, rather than assuming a patch intercepted it.
try:
    subprocess.run([sys.executable, "-I", "-S", "-B", "vm_entry.py"],
                   stdin=subprocess.DEVNULL, check=False)
except RuntimeError:
    pass
else:
    raise AssertionError("nested spawn escaped")
sys.path[:0] = [root, str(pathlib.Path(root) / "src")]
from scripts.ops import claude_read_window as window
fixture = json.loads(fixture_path.read_bytes())
assert set(fixture) <= {"calls", "raise_timeout"}
seen = []
def external(argv, **kwargs):
    matches = [item for item in fixture["calls"] if item["argv"] == list(argv)]
    assert len(matches) == 1 and list(argv) not in seen, "unclassified fixture call"
    call = matches[0]
    assert set(call) == {"argv", "stdout", "stderr", "returncode", "timeout"}
    assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["timeout"] == call["timeout"]
    seen.append(list(argv))
    if fixture.get("raise_timeout") is True and len(seen) == 4:
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
    kwargs["stdout"].write(base64.b64decode(call["stdout"], validate=True))
    kwargs["stderr"].write(base64.b64decode(call["stderr"], validate=True))
    return subprocess.CompletedProcess(argv, call["returncode"])
code = 1
try:
    code = window.main(arguments, external=external)
except Exception:
    print("fixture window refused", file=sys.stderr)
finally:
    fixture_path.with_suffix(".observed.json").write_text(json.dumps({
        "declared": len(fixture["calls"]), "substituted": len(seen),
        "spawn_denials": blocked, "unconsumed": len(fixture["calls"]) - len(seen),
    }))
raise SystemExit(code)
'''


def cli(*args):
    return subprocess.run([sys.executable, "-I", "-B", str(ENTRY), *map(str, args)],
                          stdin=subprocess.DEVNULL, capture_output=True, check=False,
                          timeout=60, cwd=ROOT)


def new_window(tmp_path, record=None):
    bindings = tmp_path / "bindings.json"
    write(bindings, binding_record() if record is None else record)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    work = tmp_path / "window"
    result = cli("create", "--bindings", bindings, "--evidence", evidence,
                 "--work", work, "--operator-revision", commands.operator_revision(),
                 "--target", TARGET, "--alias", ALIAS)
    assert result.returncode == 0 and result.stderr == b""
    return window.ReadWindow.load(work)


def release(request, path):
    # Deliberately synthetic independent approval, scoped to this test only.
    template = request["grant_template"]
    assert template["checks"] == dict.fromkeys(request["checks"], False)
    write(path, {**template, "checks": dict.fromkeys(template["checks"], True)})
    return commands.sha(path.read_bytes())


def responses(request, *, native_code=0, marker=None, readbacks=None):
    phase, manifest = request["phase"], request["manifest"]
    package = Path(request["package"])
    _, bindings = commands.package_checked(package, manifest, commands.operator_revision())
    argv = session.transport_commands(package, manifest, bindings, TARGET, ALIAS, phase)
    calls = []
    for index, command in enumerate(argv):
        raw = b"" if index < 3 else (commands.PHASES[phase].stdout if marker is None else marker)
        calls.append({"argv": command, "stdout": base64.b64encode(raw).decode(),
                      "stderr": "", "returncode": 0 if index < 3 else native_code,
                      "timeout": 120 if index < 3 else (600 if phase == "read" else 1800)})
    for part in commands.PHASES[phase].outputs:
        raw = (readbacks or {})[part]
        calls.append({"argv": session.readback_argv(bindings, phase, part, manifest, TARGET, ALIAS),
                      "stdout": base64.b64encode(raw).decode(), "stderr": "",
                      "returncode": 0, "timeout": 45})
    return {"calls": calls}


def fake_cli(tmp_path, fixture, *args):
    wrapper = tmp_path / "fixture-entry.py"
    wrapper.write_text(FAKE_ENTRY, encoding="utf-8")
    path = tmp_path / "responses.json"
    write(path, fixture)
    result = subprocess.run([sys.executable, "-I", "-B", str(wrapper), str(path), str(ROOT),
                             *map(str, args)], stdin=subprocess.DEVNULL, capture_output=True,
                            check=False, timeout=60, cwd=ROOT)
    observed = json.loads(path.with_suffix(".observed.json").read_bytes())
    assert observed["spawn_denials"] == ["subprocess.Popen"]
    return result, observed


def test_actual_cli_checked_receipt_releases_exactly_one_successor(tmp_path):
    active = new_window(tmp_path)
    request = active.prepare_next()
    assert request["phase"] == "d2-preserve"
    grant = tmp_path / "grant.json"
    pins, bindings = commands.package_checked(Path(request["package"]), request["manifest"],
                                               commands.operator_revision())
    assert request["grant_template"] == {
        "schema_version": 1, "phase": request["phase"],
        "package_manifest": request["manifest"],
        "operator_revision": commands.operator_revision(),
        "controller_commit": bindings.controller_commit,
        "bindings_sha256": pins["bindings_sha256"], "boot": bindings.values["EXPECTED_BOOT"],
        "target_sha256": commands.sha((TARGET + "\0" + ALIAS).encode()),
        "checks": dict.fromkeys(request["checks"], False),
    }
    write(grant, request["grant_template"])
    unchanged, unissued = fake_cli(
        tmp_path, responses(request), "advance", "--work", active.work,
        "--grant", grant, "--grant-sha256", commands.sha(grant.read_bytes()),
    )
    assert unchanged.returncode == 1 and unissued["substituted"] == 0
    assert not (active.work / "d2-preserve/claim.json").exists()
    assert not (active.work / "d2-preserve/captures").exists()
    digest = release(request, grant)
    result, observed = fake_cli(tmp_path, responses(request), "advance", "--work", active.work,
                                "--grant", grant, "--grant-sha256", digest)
    assert result.returncode == 0 and result.stderr == b""
    checked = json.loads(result.stdout)
    assert checked["phase"] == "d2-preserve" and checked["checked"] is True
    assert checked["external"] == {"declared": 4, "observed": 4, "mode": "substituted"}
    assert observed["declared"] == observed["substituted"] == 4 and observed["unconsumed"] == 0
    dispositions = [json.loads(line) for line in (
        active.work / "d2-preserve/captures/external-dispositions.jsonl"
    ).read_bytes().splitlines()]
    assert [item["disposition"] for item in dispositions] == [
        "substituted-issued", "substituted-completed",
    ] * 4
    successor = cli("prepare", "--work", active.work)
    assert successor.returncode == 0
    assert json.loads(successor.stdout)["phase"] == "d2-verify"
    assert not (active.work / "d2-verify/claim.json").exists()


@pytest.mark.parametrize("fault", ["nonzero", "bad-marker", "missing-fixture"])
def test_claimed_phase_failure_never_retries_or_releases_successor(tmp_path, fault):
    active = new_window(tmp_path)
    request = active.prepare_next()
    grant = tmp_path / "grant.json"
    digest = release(request, grant)
    fixture = responses(request, native_code=1 if fault == "nonzero" else 0,
                        marker=b"bad\n" if fault == "bad-marker" else None)
    if fault == "missing-fixture":
        fixture["calls"].pop()
    result, observed = fake_cli(tmp_path, fixture, "advance", "--work", active.work,
                                "--grant", grant, "--grant-sha256", digest)
    assert result.returncode != 0
    assert observed["substituted"] == (3 if fault == "missing-fixture" else 4)
    assert (active.work / "d2-preserve/claim.json").is_file()
    assert not (active.work / "d2-preserve/checked.json").exists()
    with pytest.raises(commands.Refused):
        active.prepare_next()
    assert not (active.work / "d2-verify").exists()


def test_release_digest_checked_before_claim_or_external_call(tmp_path):
    active = new_window(tmp_path)
    request = active.prepare_next()
    grant = tmp_path / "grant.json"
    release(request, grant)
    with pytest.raises(commands.Refused):
        active.advance(grant, "0" * 64, external=lambda *_args, **_kwargs: pytest.fail("called"))
    assert not (active.work / "d2-preserve/claim.json").exists()


@pytest.mark.parametrize("cleanup", [False, True])
def test_capture_creation_failure_retains_stopped_claim_and_cleanup_intent(
    tmp_path, monkeypatch, cleanup,
):
    record = binding_record()
    record["values"].update(FLOOR="5", GENERATION="6")
    active = new_window(tmp_path, record)
    if cleanup:
        commands.build_package("withdraw-after", active.work / "initial-bindings.json",
                               active.evidence, active.evidence / "cleanup-package",
                               active.revision)
        activation = active.work / "activate"
        activation.mkdir()
        write(activation / "claim.json", {"dispatch": "uncertain_until_checked"})
    request = active.prepare_next(cleanup=cleanup)
    grant = tmp_path / "grant.json"
    digest = release(request, grant)
    original_mkdir = Path.mkdir

    def fail_captures(path, *args, **kwargs):
        if path == active.work / request["phase"] / "captures":
            raise OSError("synthetic capture creation interruption")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_captures)
    with pytest.raises(OSError, match="synthetic capture creation"):
        active.advance(grant, digest, cleanup=cleanup,
                       external=lambda *_args, **_kwargs: pytest.fail("external call issued"))
    claim = json.loads((active.work / request["phase"] / "claim.json").read_bytes())
    assert claim == {"phase": request["phase"], "manifest": request["manifest"],
                     "grant_sha256": digest, "dispatch": "uncertain_until_checked"}
    assert not (active.work / request["phase"] / "checked.json").exists()
    with pytest.raises(commands.Refused):
        active.prepare_next(cleanup=cleanup)
    if cleanup:
        assert (active.work / "activate/claim.json").is_file()
        assert (active.evidence / "cleanup-package/MANIFEST.sha256").is_file()


def test_timeout_retains_uncertain_dispatch_and_no_successor(tmp_path):
    active = new_window(tmp_path)
    request = active.prepare_next()
    grant = tmp_path / "grant.json"
    digest = release(request, grant)
    fixture = responses(request)
    fixture["raise_timeout"] = True
    result, observed = fake_cli(tmp_path, fixture, "advance", "--work", active.work,
                                "--grant", grant, "--grant-sha256", digest)
    assert result.returncode == 1 and observed["substituted"] == 4
    status = json.loads((active.evidence / "d2-preserve.status.json").read_bytes())
    assert status == {"completed": False, "returncode": None, "timed_out": True}
    assert (active.work / "d2-preserve/claim.json").is_file()
    with pytest.raises(commands.Refused):
        active.prepare_next()
    assert not (active.work / "d2-verify").exists()


def test_predecessor_transition_is_rederived_from_canonical_evidence(tmp_path):
    active = new_window(tmp_path)
    request = active.prepare_next()
    grant = tmp_path / "grant.json"
    digest = release(request, grant)
    result, _ = fake_cli(tmp_path, responses(request), "advance", "--work", active.work,
                         "--grant", grant, "--grant-sha256", digest)
    assert result.returncode == 0
    path = active.work / "d2-preserve/next-bindings.json"
    changed = json.loads(path.read_bytes())
    changed["values"]["READ_KEY"] = "tampered-read"
    write(path, changed)
    checked_path = active.work / "d2-preserve/checked.json"
    checked = json.loads(checked_path.read_bytes())
    checked["next_bindings_sha256"] = commands.sha(path.read_bytes())
    write(checked_path, checked)
    with pytest.raises(commands.Refused):
        active.prepare_next()
    assert not (active.work / "d2-verify").exists()


@pytest.mark.parametrize("argv", [
    [sys.executable, "-I", "-S", "-B", "vm_entry.py"],
    [sys.executable, "-I", "-B", "vm_entry.py"],
    [session.SSH, "-T", "-o", "StrictHostKeyChecking=no", TARGET, "true"],
    [session.SSH, "--unknown", TARGET, "true"],
])
def test_boundary_refuses_unclassified_whole_argv_without_fallback(tmp_path, argv):
    captures = tmp_path / "captures"
    captures.mkdir()
    boundary = window.ExternalBoundary([("fixed", [session.SSH, "-T", TARGET, "fixed"], 120)],
                                       captures, lambda *_args, **_kwargs: pytest.fail("called"))
    with pytest.raises(commands.Refused):
        boundary(argv)
    assert boundary.seen == set() and boundary.ledger.read_bytes() == b""


@pytest.mark.parametrize("fault", ["timeout", "stdin", "shell", "capture"])
def test_boundary_binds_timeout_closed_stdin_and_capture_ownership(tmp_path, fault):
    captures = tmp_path / "captures"
    captures.mkdir()
    argv = [session.SSH, "-T", TARGET, "fixed"]
    boundary = window.ExternalBoundary([("fixed", argv, 120)], captures,
                                       lambda *_args, **_kwargs: pytest.fail("called"))
    with (captures / "fixed.stdout").open("xb") as out, (
        captures / ("wrong.stderr" if fault == "capture" else "fixed.stderr")
    ).open("xb") as err:
        kwargs = {"cwd": captures.parent, "stdin": subprocess.DEVNULL, "shell": False,
                  "check": False, "stdout": out, "stderr": err, "timeout": 120}
        kwargs.update({"timeout": 240} if fault == "timeout" else
                      {"stdin": None} if fault == "stdin" else
                      {"shell": True} if fault == "shell" else {})
        with pytest.raises(commands.Refused):
            boundary(argv, **kwargs)
    assert boundary.seen == set()


def test_explicit_substitution_never_uses_native_executor(tmp_path, monkeypatch):
    captures = tmp_path / "captures"
    captures.mkdir()
    argv = [session.SSH, "-T", TARGET, "fixed"]
    calls = []

    def substitute(actual, **kwargs):
        calls.append(actual)
        assert kwargs["stdin"] == subprocess.DEVNULL
        return subprocess.CompletedProcess(actual, 0)

    def denied_native(*_args, **_kwargs):
        pytest.fail("native process creation denied in substitution mode")

    monkeypatch.setattr(window.subprocess, "run", denied_native)
    boundary = window.ExternalBoundary([("fixed", argv, 120)], captures, substitute)
    with (captures / "fixed.stdout").open("xb") as out, (
        captures / "fixed.stderr"
    ).open("xb") as err:
        result = boundary(argv, cwd=captures.parent, stdin=subprocess.DEVNULL, shell=False,
                          check=False, stdout=out, stderr=err, timeout=120)
    assert result.returncode == 0 and calls == [tuple(argv)]
    assert boundary.complete() == {"declared": 1, "observed": 1, "mode": "substituted"}


def test_cleanup_uses_precompiled_package_after_uncertain_activation(tmp_path):
    record = binding_record()
    record["values"].update(FLOOR="5", GENERATION="6")
    active = new_window(tmp_path, record)
    initial = active.work / "initial-bindings.json"
    commands.build_package("withdraw-after", initial, active.evidence,
                           active.evidence / "cleanup-package", active.revision)
    # Synthetic interruption prefix: activation claim exists, context may not.
    activation = active.work / "activate"
    activation.mkdir()
    write(activation / "claim.json", {"dispatch": "uncertain_until_checked"})
    (active.evidence / "qualify.stdout").write_bytes(b"damaged predecessor\n")
    request = active.prepare_next(cleanup=True)
    grant = tmp_path / "cleanup-grant.json"
    digest = release(request, grant)
    fixture = responses(request, readbacks={"stdout": b"withdrawn-checked\n", "stderr": b""})
    result, observed = fake_cli(tmp_path, fixture, "advance", "--work", active.work,
                                "--cleanup", "--grant", grant, "--grant-sha256", digest)
    assert result.returncode == 0 and result.stderr == b""
    assert json.loads(result.stdout)["cleanup_required"] is False
    assert observed["substituted"] == observed["declared"] == 6
    assert not (active.evidence / "read-status.json").exists()
    with pytest.raises(commands.Refused):
        active.prepare_next()
    with pytest.raises(commands.Refused):
        active.prepare_next(cleanup=True)


@pytest.mark.parametrize("flag", ["--fixture", "--fixture-driver", "--mode", "--wor"])
def test_real_cli_refuses_unknown_or_abbreviated_flags(tmp_path, flag):
    result = cli("prepare", "--work", tmp_path, flag, "value")
    assert result.returncode == 2 and result.stdout == b""


def test_native_boundary_refuses_fixture_environment(tmp_path, monkeypatch):
    captures = tmp_path / "captures"
    captures.mkdir()
    monkeypatch.setenv("CLAUDE_READ_WINDOW_FIXTURE_CONFIG", "untrusted")
    with pytest.raises(commands.Refused):
        window.ExternalBoundary([], captures)
