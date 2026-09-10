"""Privileged authority operations use the one content-bound executable."""

import os
import shutil
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.git.acquisition import AcquisitionClosure, AcquisitionPaths
from constructicon.substrate.git.authority import GitAuthority
from tests.gitworld import seed_authority
from tests.substrate.test_contained_workspace import LINUX
from tests.substrate.test_contained_workspace import provider as provider


def test_path_changes_cannot_redirect_candidate_or_closure_operations(tmp_path, monkeypatch):
    authority = GitAuthority(seed_authority(tmp_path), tmp_path / "legacy")
    base = authority.resolve_ref("refs/heads/main")
    closure = AcquisitionClosure(authority)
    paths = AcquisitionPaths(tmp_path / "owned", "acq-" + "a" * 32)
    candidate = "refs/candidates/path-test/" + paths.acquisition_id
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    try:
        closure.publish(paths, candidate, base)
        assert closure.candidate(candidate) == base
        closure.commit(paths, candidate_ref=candidate)
        assert closure.is_closed(paths) and closure.candidate(candidate) is None
    except OSError as exc:
        pytest.fail(f"an ambient PATH change redirected privileged Git: {exc}")


@LINUX
def test_modified_pinned_git_is_refused_before_any_authority_operation(tmp_path, monkeypatch):
    repo = seed_authority(tmp_path)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    copied = binaries / "git"
    shutil.copy2(shutil.which("git"), copied)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ["PATH"])
    authority = GitAuthority(repo, tmp_path / "legacy")
    expected = authority.resolve_ref("refs/heads/main")
    assert expected
    # Change only our disposable ELF copy; appending remains executable, so
    # observing success would show the missing content check, not a spawn error.
    with copied.open("ab") as stream:
        stream.write(b"changed installed artifact")
    with pytest.raises(ContractViolation, match=r"Git executable.*changed"):
        authority.resolve_ref("refs/heads/main")


def test_the_provider_uses_its_authoritys_executable_not_a_second_path_lookup(
    provider, monkeypatch
):
    from types import SimpleNamespace

    from constructicon.core.identity import digest
    from constructicon.substrate.executors.linux import ProcessLimits
    from tests.substrate.test_contained_capture import write_provider

    monkeypatch.setenv("PATH", "")
    launch = SimpleNamespace(revision=digest("fake-launch", 1, "inert"), limits=ProcessLimits())
    try:
        capture = write_provider(provider, launch)
    except ContractViolation as exc:
        pytest.fail(f"contained provider repeated executable discovery: {exc}")
    assert Path(capture.git).is_absolute()
    assert capture.git == provider.authority.git_executable
