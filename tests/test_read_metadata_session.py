"""Portable identity/capture contracts; real generated guest execution is Linux rehearsal."""

from __future__ import annotations

import copy
import json
import shlex
import subprocess
import sys
from datetime import UTC, datetime

import pytest
from scripts.ops import claude_read_commands as commands
from scripts.ops import claude_read_session as session
from scripts.ops import read_metadata_session as metadata

from constructicon.core.address import ScopePath
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.qualification import QualificationAuthorization

OLD_BOOT, NEW_BOOT = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
PRIVATE = "PRIVATE-RAW-MODEL-OR-ACCOUNT-TEXT"


def write(path, value):
    path.write_bytes(session.json_bytes(value))


@pytest.fixture
def world(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    run = "/var/lib/m8-cr-run-history"
    authorization = QualificationAuthorization(
        authorization_id="historical-read",
        stage="qualification-read",
        actor_id="static:fixture",
        idempotency_key="historical-key",
        scope=ScopePath(segments=("fixture", "read")),
        binding="executor",
        source_graph_hash="sha256:" + "1" * 64,
        capability_id="claude-operator",
        revision="old-revision",
        operator_binding_digest="sha256:" + "2" * 64,
        journal=run + "/read.sqlite",
        max_epoch=1,
        not_after=datetime(2000, 1, 1, tzinfo=UTC),
        attempt_record=run + "/read-attempt.json",
        grants=EffectiveGrants(
            posture=Posture.READ,
            model_selection=ModelSelection(kind="explicit", model="fixture"),
            effort="low",
            allowed_tools=("read_file",),
            env_allowlist=(),
            network="allow",
            timeout_s=120,
        ),
    )
    auth = json.loads(authorization.model_dump_json())
    write(history / "authorization-candidate.json", auth)
    auth_sha = metadata.sha((history / "authorization-candidate.json").read_bytes())
    binding = {
        "controller_commit": "a" * 40,
        "values": {
            "EXPECTED_BOOT": OLD_BOOT,
            "RUN": run,
            "AUTHORIZATION_ID": authorization.authorization_id,
            "CANDIDATE_SHA256": auth_sha,
            "ACTOR": authorization.actor_id,
            "READ_KEY": authorization.idempotency_key,
        },
    }
    write(history / "bindings.json", binding)
    binding_sha = metadata.sha((history / "bindings.json").read_bytes())
    context = {
        "phase": "read",
        "boot": OLD_BOOT,
        "controller_commit": "a" * 40,
        "bindings_sha256": binding_sha,
        "operator_revision": "b" * 64,
        "package_manifest": "c" * 64,
        "script_sha256": "d" * 64,
    }
    write(history / "read-context.json", context)
    request = {
        "schema_version": 1,
        "retained": {
            "context_sha256": metadata.sha((history / "read-context.json").read_bytes()),
            "bindings_sha256": binding_sha,
            "authorization_sha256": auth_sha,
            "controller_commit": "a" * 40,
            "boot": OLD_BOOT,
            "run_root": run,
            "authorization_id": authorization.authorization_id,
            "run_id": str(authorization.run_id),
            "max_epoch": 1,
        },
        "fresh": {
            "boot": NEW_BOOT,
            "target": "fixture@192.0.2.1",
            "alias": "fixture",
            "namespace": "read-rehearsal-metadata",
            "drift_sha256": "e" * 64,
            "drift_stdout": "NO DRIFT: fixture inputs unchanged.\n",
        },
    }
    path = tmp_path / "request.json"
    write(path, request)
    return path, history, request


def compile_world(tmp_path, world):
    path, history, request = world
    package = tmp_path / "package"
    manifest = metadata.compile_package(path, history, package, metadata.revision())
    return package, manifest, history, request


def observation(invalid=False):
    return {
        "schema_version": 1,
        "attempt": {
            "state": "invalid" if invalid else "valid",
            "partial": invalid,
            "phase": None if invalid else "outcome",
            "dispatch": None if invalid else "completed",
            "status": None if invalid else "success",
            "callback_started": None if invalid else 1,
            "callback_completed": None if invalid else 1,
            "initial_binding_checked": None if invalid else True,
            "terminal_binding_checked": None if invalid else True,
            "relay_closed": None if invalid else True,
            "callback_observation": None,
        },
        "journal": {
            "state": "valid",
            "partial": False,
            "run_status": "failed",
            "event_count": 1,
            "events": [
                {
                    "kind": "NodeFailed",
                    "error_type": "ContractViolation",
                    "reason": "read_contract_refused",
                }
            ],
        },
    }


def process_double(tmp_path, monkeypatch, mode="accept"):
    """Real child/capture, substituting only SSH/SCP process boundary; no guest proof."""
    response = tmp_path / "response.json"
    write(response, observation(mode == "invalid"))
    fake = tmp_path / "fake_transport.py"
    fake.write_text(
        """import json,pathlib,sys,time
name,response,mode,log,*argv=sys.argv[1:]
assert sys.stdin.buffer.read()==b""
pathlib.Path(log).write_text(json.dumps(argv))
if mode in ("preflight","mkdir") and name.endswith(mode):raise SystemExit(1)
if name.endswith("native"):
    if mode=="timeout":time.sleep(2)
    if mode not in ("empty","exit255"):
        sys.stdout.buffer.write(pathlib.Path(response).read_bytes())
    if mode=="stderr":sys.stderr.write("unexpected")
    raise SystemExit(1 if mode=="invalid" else 255 if mode=="exit255" else 0)
""",
        encoding="utf-8",
    )
    actual_capture = session.capture
    calls = []

    def capture(name, captures, argv, timeout, max_stdout=4096):
        calls.append((name, argv))
        child = [
            sys.executable,
            "-I",
            "-B",
            str(fake),
            name,
            str(response),
            mode,
            str(tmp_path / (name + ".argv.json")),
            *argv,
        ]
        return actual_capture(
            name,
            captures,
            child,
            0.1 if mode == "timeout" and name.endswith("native") else 30,
            max_stdout,
        )

    monkeypatch.setattr(session, "capture", capture)
    return calls


def test_accepts_historical_boot_and_expired_identity_distinct_from_current(tmp_path, world):
    package, manifest, history, request = compile_world(tmp_path, world)
    actual, pins = metadata.package_checked(package, manifest, metadata.revision(), history)
    assert actual == request and actual["retained"]["boot"] != actual["fresh"]["boot"]
    assert pins["sources"].get("scripts/ops/read_attempt_evidence.py") == metadata.sha(
        (metadata.ROOT / "scripts/ops/read_attempt_evidence.py").read_bytes()
    )
    assert pins["sources"].get("src/constructicon/core/claude_read_observation.py") == metadata.sha(
        (metadata.ROOT / "src/constructicon/core/claude_read_observation.py").read_bytes()
    )
    script = (package / "phase.sh").read_bytes()
    assert commands._fence("guard", "G1: private drift boundary").encode() in script
    assert b'} > "$PWD/drift-marker.stdout"\n' in script
    assert b"exec /usr/bin/sudo -n -u m8-service -- /usr/bin/python3 -I -S -B -c " in script
    assert b"constructicon.api.claude_qualification" not in script
    assert set(p.name for p in package.iterdir()) == {*metadata.FILES, "MANIFEST.sha256"}
    with pytest.raises(FileExistsError):
        metadata.compile_package(world[0], history, package, metadata.revision())


@pytest.mark.parametrize(
    "fault",
    [
        "old-boot",
        "old-controller",
        "old-run",
        "max-bool",
        "fresh-boot",
        "extra-authority",
        "history-bytes",
        "source",
        "script",
    ],
)
def test_mismatched_identity_source_or_request_refuses(tmp_path, world, monkeypatch, fault):
    path, history, request = world
    if fault in ("history-bytes", "source", "script"):
        selected_revision = metadata.revision()
        package, manifest, _, _ = compile_world(tmp_path, world)
        if fault == "history-bytes":
            with (history / "authorization-candidate.json").open("ab") as stream:
                stream.write(b"\n")
        elif fault == "source":
            original = metadata.sources()
            monkeypatch.setattr(
                metadata,
                "sources",
                lambda: {**original, "scripts/ops/read_attempt_evidence.py": "0" * 64},
            )
        else:
            (package / "phase.sh").write_bytes(b"exit 0\n")
        with pytest.raises(commands.Refused):
            metadata.package_checked(
                package,
                manifest,
                selected_revision,
                history,
            )
        return
    if fault == "old-boot":
        request["retained"]["boot"] = NEW_BOOT
    elif fault == "old-controller":
        request["retained"]["controller_commit"] = "f" * 40
    elif fault == "old-run":
        request["retained"]["run_id"] = "different-run"
    elif fault == "max-bool":
        request["retained"]["max_epoch"] = True
    elif fault == "fresh-boot":
        request["fresh"]["boot"] = "UNREVIEWED"
    else:
        request["fresh"]["approved"] = True
    write(path, request)
    with pytest.raises(commands.Refused):
        metadata.compile_package(path, history, tmp_path / "refused", metadata.revision())
    assert not (tmp_path / "refused").exists()


def test_actual_process_capture_and_context_check_permit(tmp_path, world, monkeypatch):
    package, manifest, history, request = compile_world(tmp_path, world)
    captures = tmp_path / "captures"
    captures.mkdir()
    calls = process_double(tmp_path, monkeypatch)
    status = metadata.transport(package, manifest, metadata.revision(), history, captures)
    assert commands.completed_zero(status)
    result = metadata.check(package, manifest, metadata.revision(), history, captures)
    assert result == {"collection_checked": True, "observation": observation()}
    assert [name for name, _ in calls] == [
        "metadata-preflight",
        "metadata-mkdir",
        "metadata-copy",
        "metadata-native",
    ]
    for name, argv in calls:
        assert json.loads((tmp_path / (name + ".argv.json")).read_bytes()) == argv
    context = json.loads((captures / "metadata-context.json").read_bytes())
    assert context["historical_boot"] == OLD_BOOT and context["current_boot"] == NEW_BOOT
    assert request["retained"]["authorization_id"] not in json.dumps(result)
    with pytest.raises(FileExistsError):
        metadata.transport(package, manifest, metadata.revision(), history, captures)


@pytest.mark.parametrize("stage", ["preflight", "mkdir"])
def test_collision_or_staging_failure_never_advances(tmp_path, world, monkeypatch, stage):
    package, manifest, history, _ = compile_world(tmp_path, world)
    captures = tmp_path / "captures"
    captures.mkdir()
    calls = process_double(tmp_path, monkeypatch, stage)
    with pytest.raises(commands.Refused):
        metadata.transport(package, manifest, metadata.revision(), history, captures)
    assert [name for name, _ in calls] == (
        ["metadata-preflight"] if stage == "preflight" else ["metadata-preflight", "metadata-mkdir"]
    )
    assert not (captures / "metadata-native.status.json").exists()


def test_cross_context_receipt_cannot_pass(tmp_path, world, monkeypatch):
    package, manifest, history, _ = compile_world(tmp_path, world)
    captures = tmp_path / "captures"
    captures.mkdir()
    process_double(tmp_path, monkeypatch)
    metadata.transport(package, manifest, metadata.revision(), history, captures)
    context = json.loads((captures / "metadata-context.json").read_bytes())
    context["current_boot"] = OLD_BOOT
    write(captures / "metadata-context.json", context)
    with pytest.raises(commands.Refused):
        metadata.check(package, manifest, metadata.revision(), history, captures)


@pytest.mark.parametrize("mode", ["invalid", "exit255", "timeout", "empty", "stderr"])
def test_native_nonpositive_or_incomplete_facts_never_pass(tmp_path, world, monkeypatch, mode):
    package, manifest, history, _ = compile_world(tmp_path, world)
    captures = tmp_path / "captures"
    captures.mkdir()
    process_double(tmp_path, monkeypatch, mode)
    status = metadata.transport(package, manifest, metadata.revision(), history, captures)
    if mode == "invalid":
        assert status["returncode"] == 1
        result = metadata.check(package, manifest, metadata.revision(), history, captures)
        assert result["collection_checked"] is False and result["observation"] == observation(True)
        assert (captures / "metadata-native.stdout").read_bytes()
    else:
        with pytest.raises((commands.Refused, ValueError)):
            metadata.check(package, manifest, metadata.revision(), history, captures)
    if mode == "timeout":
        assert status == {"completed": False, "returncode": None, "timed_out": True}


@pytest.mark.parametrize(
    "fault", ["extra", "private-enum", "bool-count", "unknown-callback", "oversize", "unhashable"]
)
def test_closed_observation_does_not_publish_injected_private_values(fault):
    value = copy.deepcopy(observation())
    if fault == "extra":
        value["attempt"]["raw"] = PRIVATE
    elif fault == "private-enum":
        value["journal"]["events"][0]["reason"] = PRIVATE
    elif fault == "bool-count":
        value["attempt"]["callback_started"] = True
    elif fault == "unknown-callback":
        value["attempt"]["callback_observation"] = {"private": PRIVATE}
    elif fault == "unhashable":
        value["journal"]["events"][0]["reason"] = [PRIVATE]
    else:
        with pytest.raises(commands.Refused):
            metadata.observation_checked(b" " * (metadata.reader.OUTPUT_BYTES + 1)
                                         + session.json_bytes(value))
        return
    with pytest.raises(commands.Refused):
        metadata.observation_checked(session.json_bytes(value))


@pytest.mark.parametrize("accepted", [True, False])
def test_context_checked_and_historical_flat_observation_remains_valid(accepted):
    value = observation()
    assert metadata.observation_checked(session.json_bytes(value)) == value
    event = value["journal"]["events"][0]
    event["reason"] = "claude_read_api_retry"
    event["refusal_context"] = {
        "family": "system-api-retry", "phase": "drain", "predicate": "phase",
        "terminal_result_accepted": accepted,
    }
    assert metadata.observation_checked(session.json_bytes(value)) == value


def test_metadata_accepts_each_closed_family_and_rejects_unknown():
    from constructicon.core.claude_read_observation import ClaudeReadRefusalFamily

    value = observation()
    event = value["journal"]["events"][0]
    event["reason"] = "claude_read_system_other"
    context = event["refusal_context"] = {
        "family": "", "phase": "body-after-callback", "predicate": "unsupported-family",
        "terminal_result_accepted": False,
    }
    for family in ClaudeReadRefusalFamily:
        context["family"] = family.value
        assert metadata.observation_checked(session.json_bytes(value)) == value
    context["family"] = PRIVATE
    with pytest.raises(commands.Refused):
        metadata.observation_checked(session.json_bytes(value))


@pytest.mark.parametrize("fault", ["extra", "private", "boolean", "wrong-kind", "wrong-reason"])
def test_context_checked_rejects_open_or_inconsistent_values(fault):
    value = observation()
    event = value["journal"]["events"][0]
    event["reason"] = "claude_read_api_retry"
    context = event["refusal_context"] = {
        "family": "system-api-retry", "phase": "drain", "predicate": "phase",
        "terminal_result_accepted": False,
    }
    if fault == "extra":
        context["extra"] = PRIVATE
    elif fault == "private":
        context["family"] = PRIVATE
    elif fault == "boolean":
        context["terminal_result_accepted"] = 1
    elif fault == "wrong-kind":
        event["kind"] = "RunFailed"
    else:
        event["reason"] = "read_contract_refused"
    with pytest.raises(commands.Refused):
        metadata.observation_checked(session.json_bytes(value))


def test_real_isolated_entry_compiles_checked_package(tmp_path, world):
    path, history, _ = world
    package = tmp_path / "cli-package"
    child = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            metadata.__file__,
            "compile",
            "--request",
            str(path),
            "--history",
            str(history),
            "--out",
            str(package),
            "--revision",
            metadata.revision(),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    assert child.returncode == 0 and child.stderr == b""
    manifest = json.loads(child.stdout)["manifest"]
    metadata.package_checked(package, manifest, metadata.revision(), history)
    bad = subprocess.run(
        [sys.executable, "-I", "-B", metadata.__file__, "--private", PRIVATE],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    assert bad.returncode == 2 and PRIVATE.encode() not in bad.stderr


@pytest.mark.parametrize("mode,code", [("accept", 0), ("invalid", 1)])
def test_real_isolated_transport_entry_retains_native_status(
    tmp_path, world, monkeypatch, mode, code
):
    package, manifest, history, _ = compile_world(tmp_path, world)
    captures = tmp_path / "captures"
    captures.mkdir()
    process_double(tmp_path, monkeypatch, mode)
    driver = tmp_path / "isolated_transport_entry.py"
    driver.write_text(
        f"""import pathlib,runpy,sys
sys.path[:0]=[{str(metadata.ROOT)!r}, {str(metadata.ROOT / "src")!r}]
from scripts.ops import claude_read_session as session
original=session.capture
def process_boundary(name,captures,argv,timeout,max_stdout=4096):
    child=[sys.executable,"-I","-B",{str(tmp_path / "fake_transport.py")!r},name,
           {str(tmp_path / "response.json")!r},{mode!r},
           str(pathlib.Path({str(tmp_path)!r})/(name+".argv.json")),*argv]
    return original(name,captures,child,timeout,max_stdout)
session.capture=process_boundary
sys.argv[0]={metadata.__file__!r}
runpy.run_path({metadata.__file__!r},run_name="__main__")
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(driver),
            "transport",
            "--package",
            str(package),
            "--manifest",
            manifest,
            "--revision",
            metadata.revision(),
            "--history",
            str(history),
            "--captures",
            str(captures),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    assert result.returncode == code and result.stderr == b""
    assert json.loads(result.stdout) == {"completed": True, "returncode": code, "timed_out": False}
    assert metadata.check(package, manifest, metadata.revision(), history, captures)[
        "collection_checked"
    ] is (code == 0)


def test_old_read_transport_delegates_with_unchanged_exact_argv(tmp_path):
    from tests.test_claude_read_session import binding_record

    bindings = commands.Bindings.from_dict(binding_record())
    for leaf in (*metadata.FILES, "MANIFEST.sha256"):
        (tmp_path / leaf).write_bytes(b"fixture")
    manifest, phase, target, alias = "a" * 64, "d2-preserve", "fixture@192.0.2.1", "fixture"
    before = session.transport_commands(tmp_path, manifest, bindings, target, alias, phase)
    name = commands.remote_name(bindings, phase, manifest)
    after = session.staging_commands(tmp_path, manifest, name, target, alias)
    assert before == after
    ssh = [session.SSH, "-T", *session.ssh_options(alias), target]
    assert all(argv[: len(ssh)] == ssh for argv in (before[0], before[1], before[3]))
    # This is the pre-extraction producer body, not a call through the new helper.
    original_preflight = (
        'import os,pathlib,stat,sys;h=pathlib.Path(os.environ["HOME"]);u=os.geteuid();'
        "ok=u!=0 and h==h.resolve(strict=True) and h.stat().st_uid==u and "
        "all(stat.S_ISDIR(s.st_mode) and s.st_uid in (0,u) and not s.st_mode&0o022 "
        "for p in (h,*h.parents) for s in (p.lstat(),));"
        f"ok=ok and not os.path.lexists(h/{name!r});sys.exit(0 if ok else 1)"
    )
    assert before[0][-1] == shlex.join(
        ["/usr/bin/python3", "-I", "-S", "-B", "-c", original_preflight]
    )
    assert before[2] == [
        session.SCP,
        "-q",
        *session.ssh_options(alias),
        *(session._copy_path(tmp_path / leaf) for leaf in ("MANIFEST.sha256", *metadata.FILES)),
        f"{target}:{name}/",
    ]
    assert before[1][-1] == (
        f'umask 077;test ! -e "$HOME/{name}" && test ! -L "$HOME/{name}" && '
        f'/usr/bin/mkdir -m 0700 "$HOME/{name}"'
    )
    assert before[3][-1] == (
        f'cd "$HOME/{name}" && '
        f'test "$(/usr/bin/sha256sum MANIFEST.sha256 | /usr/bin/cut -d " " -f 1)" = {manifest} && '
        "/usr/bin/sha256sum --check --strict --quiet MANIFEST.sha256 "
        "&& /bin/bash phase.sh < /dev/null"
    )
    for invalid in ("../escape", "a" * 129, "shell;command"):
        with pytest.raises(commands.Refused):
            session.staging_commands(tmp_path, manifest, invalid, target, alias)
