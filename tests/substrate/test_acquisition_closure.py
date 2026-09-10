"""Literal revocation facts: real Git, no Linux containment claim."""

from __future__ import annotations

from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.git.acquisition import AcquisitionClosure, AcquisitionPaths
from constructicon.substrate.git.authority import GitAuthority, GitAuthorityDamaged
from tests.gitworld import seed_authority


@pytest.fixture
def closure(tmp_path):
    authority = GitAuthority(seed_authority(tmp_path), tmp_path / "legacy")
    return AcquisitionClosure(authority)


def test_closure_is_inert_until_committed_and_names_no_merge_subject(closure, tmp_path):
    paths = AcquisitionPaths(tmp_path / "owned", acquisition_id_for("lease-example", 1))
    before = closure.authority.resolve_ref("refs/heads/main")
    assert not paths.root.exists() and not closure.is_closed(paths)
    closure.commit(paths)
    assert closure.is_closed(paths)
    assert not paths.root.exists()
    assert closure.authority.resolve_ref("refs/heads/main") == before
    assert closure.authority._run("cat-file", "-t", paths.closure_ref).stdout.strip() == "blob"
    assert closure.authority._run("cat-file", "-s", paths.closure_ref).stdout.strip() == "0"
    # The legacy commit-peeling helper would misread this as absence.
    assert closure.authority.read_ref(paths.closure_ref) is None
    with pytest.raises(ContractViolation, match="permanently closed"):
        closure.require_open(paths)


def test_closure_is_idempotent_and_different_epochs_never_reopen_one_another(closure, tmp_path):
    old = AcquisitionPaths(tmp_path, acquisition_id_for("lease-shared", 1))
    fresh = AcquisitionPaths(tmp_path, acquisition_id_for("lease-shared", 2))
    closure.commit(old)
    closure.commit(old)
    assert closure.is_closed(old) and not closure.is_closed(fresh)
    assert old.guard != fresh.guard and old.payload != fresh.payload
    closure.commit(fresh)
    assert closure.is_closed(old) and closure.is_closed(fresh)


@pytest.mark.parametrize("symbolic", [False, True])
def test_wrong_or_symbolic_closure_is_damage_never_open_or_repaired(closure, tmp_path, symbolic):
    paths = AcquisitionPaths(tmp_path, acquisition_id_for("lease-damaged", 1))
    authority = closure.authority
    if symbolic:
        # Even an alias resolving to the exact sentinel must not count.
        authority._run("hash-object", "-w", "--stdin", input_text="")
        authority._run("update-ref", "refs/other/sentinel", closure.sentinel)
        authority._run("symbolic-ref", paths.closure_ref, "refs/other/sentinel")
    else:
        authority._run("update-ref", paths.closure_ref, authority.resolve_ref("refs/heads/main"))
    for action in (closure.is_closed, closure.commit):
        with pytest.raises(GitAuthorityDamaged):
            action(paths)
    if symbolic:
        actual = authority._run("symbolic-ref", paths.closure_ref).stdout.strip()
        assert actual == "refs/other/sentinel"


@pytest.mark.parametrize("key", [
    "", "acq-short", "../outside", "acq-" + "A" * 32, "x\ncreate refs/x",
])
def test_recovery_locator_cannot_supply_a_path_or_refspec(tmp_path, key):
    with pytest.raises(ContractViolation, match="identity"):
        AcquisitionPaths(tmp_path, key)


def test_recovery_root_must_be_absolute():
    with pytest.raises(ContractViolation, match="absolute"):
        AcquisitionPaths(Path("relative"), acquisition_id_for("lease", 1))
