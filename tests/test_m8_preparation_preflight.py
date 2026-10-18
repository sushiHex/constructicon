"""Portable fixture evidence only; Linux composition lives in the root lane."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import sysconfig
from pathlib import PurePosixPath

import pytest
from scripts import m8_procedure_package as package

from constructicon.api._maintenance_source import SOURCE_FILES, SOURCE_HASHES, git
from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors.egress import MAX_SOCKET_PATH_BYTES, SOCKET_NAME
from tests import preparation_preflight as seam
from tests.git_bash import git_bash
from tests.preparation_preflight import source_bundle


def test_step_observation_retains_bounded_bytes_without_claiming_a_verdict(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("M8_EVIDENCE_DIRECTORY", str(tmp_path))
    stdout = b"discarded prefix" + bytes(range(256)) * 40
    stderr = b"synthetic child refusal\n"
    seam.observe_step("accept", seam.STEPS[0], {"returncode": 1}, stdout, stderr)
    record = json.loads((tmp_path / f"n3c-q13-accept-{seam.STEPS[0]}.json").read_bytes())
    assert record == {
        "schema_version": 1, "synthetic_fixture": True,
        "meaning": "step observation, not a passed verdict",
        "scenario": "accept", "step": seam.STEPS[0], "status": {"returncode": 1},
        "streams": {
            "stdout": {"bytes": len(stdout), "tail_hex": stdout[-8192:].hex()},
            "stderr": {"bytes": len(stderr), "tail_hex": stderr.hex()},
        },
    }


@pytest.mark.parametrize(("mode", "custody"), [
    ("initial", "maintenance"), ("qualify", "maintenance"),
    ("hold", "maintenance"), ("active", "active"), ("refresh", "active"),
])
def test_isolated_checker_receives_the_mode_specific_custody(tmp_path, monkeypatch, mode, custody):
    from tests.substrate import test_operator_store_maintenance_restart as isolated

    revision = "sha256:" + "a" * 64
    expected = "-" if mode == "initial" else "pro/sha256:" + "b" * 64
    calls = []

    def checked(command, *, as_service):
        assert as_service is True
        calls.append(command[-7:])
        return subprocess.CompletedProcess(command, 0, (revision + "\n").encode(), b"")

    monkeypatch.setattr(isolated, "isolated_run", checked)
    isolated.isolated_checked_revision(mode, tmp_path / "evidence.json", expected,
                                       tmp_path / "session", tmp_path / "launch", revision)
    assert calls == [[mode, str(tmp_path / "evidence.json"), custody, expected,
                      str(tmp_path / "session/startup-policy.json"),
                      str(tmp_path / "session"), str(tmp_path / "launch")]]


def test_isolated_checker_failure_exposes_only_a_bounded_synthetic_diagnostic(
    tmp_path, monkeypatch,
):
    from tests.substrate import test_operator_store_maintenance_restart as isolated

    diagnostic = b"omitted-synthetic-prefix:" + b"x" * 5000 + b"synthetic-checker-end\n"
    monkeypatch.setattr(isolated, "isolated_run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, b"", diagnostic))
    with pytest.raises(AssertionError) as failed:
        isolated.isolated_checked_revision("hold", tmp_path / "evidence.json", "pro/synthetic",
                                           tmp_path / "session", tmp_path / "launch", "synthetic")
    message = str(failed.value)
    bounded = "synthetic isolated evidence checker diagnostic: " + diagnostic.decode()[-4096:]
    assert bounded in message
    assert "omitted-synthetic-prefix" not in message


@pytest.mark.parametrize("wrong_consumer", [False, True])
async def test_preparation_bundle_is_genuine_and_consumer_damage_is_not_a_digest_mismatch(
    tmp_path, wrong_consumer,
):
    bundle, base, revision = await source_bundle(tmp_path / "fixture",
                                               wrong_consumer=wrong_consumer)
    assert revision == hashlib.sha256(bundle.read_bytes()).hexdigest()
    repository = bundle.parent / "source.git"
    assert await git(repository, "bundle", "verify", str(bundle))
    assert (await git(repository, "rev-parse", "refs/heads/main")).strip().decode() == base
    assert not await git(repository, "ls-tree", base, "--", "tests/vectors/plan_manifest.json")
    for name in SOURCE_FILES:
        raw = await git(repository, "show", f"{base}:{name}")
        if wrong_consumer and name == SOURCE_FILES[1]:
            assert hashlib.sha256(raw).hexdigest() != SOURCE_HASHES[name]
        else:
            assert hashlib.sha256(raw).hexdigest() == SOURCE_HASHES[name]


@pytest.mark.parametrize("layout", ["native", "linux-prefix"])
def test_actual_q13_seam_mapping_retains_producer_and_checker_fences(tmp_path, layout):
    launch = (PurePosixPath("/var/lib/constructicon-m8-launch/synthetic-root/isolated-launch")
              if layout == "linux-prefix" else tmp_path / "launch")
    session = tmp_path / "session"
    bundle = tmp_path / "source.bundle"
    bundle.write_bytes(b"synthetic mapping input, not an execution bundle\n")
    short_state = PurePosixPath("/home/m8-service/pf-12345678/0")
    out = seam.packaged_steps(tmp_path, launch, session, bundle, "a" * 40, "b" * 64, short_state)
    frozen = (seam.HANDOFFS / "M8-maintenance-g11-continuation.md").read_bytes().decode()
    bootstrap = "sys.path[:0] = " + json.dumps([
        str(seam.ROOT / "src"), sysconfig.get_paths()["purelib"]])
    for name, heading, fence in (
        (seam.STEPS[0], "C7: fresh closure, source bundle and authority", 2),
        (seam.STEPS[1], "C8: retain preflight and display its closed failure stage", 0),
    ):
        script = out / (name + ".sh")
        body = script.read_bytes().decode()
        state = next(line[2:] for line in body.splitlines() if line.startswith("S="))
        assert state == str(short_state)
        socket = (PurePosixPath(state) / "acquisitions/payloads" /
                  ("acq-" + "0" * 32) / SOCKET_NAME)
        assert len(os.fsencode(socket)) <= MAX_SOCKET_PATH_BYTES
        assert next(line for line in body.splitlines() if line.startswith("R=")) == (
            "R=" + str(launch / "operator-stores"))
        assert next(line for line in body.splitlines() if line.startswith("L=")) == (
            "L=" + str(launch))
        controller_python = '"${SERVICE[@]}" ' + shlex.quote(sys.executable) + ' -I -S -B -c'
        assert '"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c' not in body
        assert controller_python in body
        assert '/usr/bin/python3 -I -S -B - "$DRIFT_CAPTURE"' in body
        selected = package.fences(package.section(frozen, heading))[fence][1].replace(
            'sys.path.insert(0, "/opt/constructicon-m8-controller")', bootstrap).replace(
            '"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c', controller_python)
        assert body.count(selected) == 1
        assert body.count('binding_check "$W/g11.sealed.json" accepted -') == 1
        assert body.count('check_sealed "$W/g11.sealed.json" "$Q"') == 1
        assert 'save_sealed() {' in body
        assert body.index('DRIFT_CAPTURE="$DRIFT_RECORDS/before"') < body.index(
            'binding_check "$W/g11.sealed.json" accepted -') < body.index(selected)
        ran = subprocess.run([git_bash(), "-n", str(script)], stdin=subprocess.DEVNULL,
                             capture_output=True, timeout=10, check=False)
        assert (ran.returncode, ran.stdout, ran.stderr) == (0, b"", b"")


def test_seam_completion_evidence_matches_the_existing_ci_upload_globs(tmp_path, monkeypatch):
    from tests.substrate import test_operator_store_maintenance_restart as isolated

    published = []
    monkeypatch.setattr(seam, "exercise_seam", lambda *args: "synthetic-qualification")
    monkeypatch.setattr(isolated, "write_evidence", lambda name, value: published.append(name))
    isolated.test_actual_packaged_q13_preparation_preflight_over_isolated_production_topology(
        (tmp_path, tmp_path / "launch", tmp_path / "session", None), tmp_path)
    assert published == ["n3c-preparation-preflight.json"]
    workflow = (seam.ROOT / ".github/workflows/m8-containment.yml").read_bytes().decode()
    globs = re.findall(r"\$\{\{ env.M8_EVIDENCE \}\}/([^\s]+)", workflow)
    assert any(fnmatch.fnmatchcase(published[0], pattern) for pattern in globs)


def test_real_provider_refuses_long_fixture_state_and_accepts_short_state():
    from tests.substrate.test_codex_adapter import bare_launcher
    from tests.substrate.test_codex_egress import policy_for, provider_for

    long = PurePosixPath(
        "/var/lib/constructicon-m8-launch/n3a-restart-12345678/seam-accept/state/acquisitions")
    with pytest.raises(ContractViolation, match="too long for the native egress socket"):
        provider_for(bare_launcher(), policy=policy_for(443), root=long)
    short = PurePosixPath("/home/m8-service/pf-12345678/0/acquisitions")
    accepted = provider_for(bare_launcher(), policy=policy_for(443), root=short)
    assert accepted.egress == policy_for(443)
