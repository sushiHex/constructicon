"""Portable fixture evidence only; Linux composition lives in the root lane."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sysconfig
from pathlib import PurePosixPath

import pytest
from scripts import m8_procedure_package as package

from constructicon.api._maintenance_source import SOURCE_FILES, SOURCE_HASHES, git
from tests import preparation_preflight as seam
from tests.git_bash import git_bash
from tests.preparation_preflight import source_bundle


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
    out = seam.packaged_steps(tmp_path, launch, session, bundle, "a" * 40, "b" * 64)
    frozen = (seam.HANDOFFS / "M8-maintenance-g11-continuation.md").read_bytes().decode()
    bootstrap = "sys.path[:0] = " + json.dumps([
        str(seam.ROOT / "src"), sysconfig.get_paths()["purelib"]])
    for name, heading, fence in (
        (seam.STEPS[0], "C7: fresh closure, source bundle and authority", 2),
        (seam.STEPS[1], "C8: retain preflight and display its closed failure stage", 0),
    ):
        script = out / (name + ".sh")
        body = script.read_bytes().decode()
        assert next(line for line in body.splitlines() if line.startswith("R=")) == (
            "R=" + str(launch / "operator-stores"))
        assert next(line for line in body.splitlines() if line.startswith("L=")) == (
            "L=" + str(launch))
        selected = package.fences(package.section(frozen, heading))[fence][1].replace(
            'sys.path.insert(0, "/opt/constructicon-m8-controller")', bootstrap)
        assert body.count(selected) == 1
        assert body.count('binding_check "$W/g11.sealed.json" accepted -') == 1
        assert body.count('check_sealed "$W/g11.sealed.json" "$Q"') == 1
        assert 'save_sealed() {' in body
        assert body.index('DRIFT_CAPTURE="$DRIFT_RECORDS/before"') < body.index(
            'binding_check "$W/g11.sealed.json" accepted -') < body.index(selected)
        ran = subprocess.run([git_bash(), "-n", str(script)], stdin=subprocess.DEVNULL,
                             capture_output=True, timeout=10, check=False)
        assert (ran.returncode, ran.stdout, ran.stderr) == (0, b"", b"")
