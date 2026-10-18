"""Portable fixture evidence only; Linux composition lives in the root lane."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sysconfig

import pytest
from scripts import m8_procedure_package as package

from constructicon.api._maintenance_source import SOURCE_FILES, SOURCE_HASHES, git
from tests import preparation_preflight as seam
from tests.git_bash import git_bash
from tests.preparation_preflight import source_bundle


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


def test_actual_q13_seam_mapping_retains_producer_and_checker_fences(tmp_path):
    launch, session = tmp_path / "launch", tmp_path / "session"
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
