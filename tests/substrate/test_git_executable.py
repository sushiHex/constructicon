"""Privileged authority operations use the one content-bound executable."""

import os
import shutil
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.git.acquisition import AcquisitionClosure, AcquisitionPaths
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.contained import ContainedWorkspaceProvider
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
        snapshot = authority.read_snapshot(base)
        try:
            assert snapshot.git_ref().commit == base
        finally:
            authority.discard_snapshot(snapshot)
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


@LINUX
@pytest.mark.parametrize("mode", [0o755, 0o555])
def test_contained_git_refuses_service_replaceable_artifacts(provider, tmp_path, monkeypatch, mode):
    binaries = tmp_path / "replaceable-bin"
    binaries.mkdir()
    copied = binaries / "git"
    shutil.copy2(provider.authority.git_executable, copied)
    copied.chmod(mode)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ["PATH"])
    # A historical authority can still use an operator-supplied installation.
    # A contained provider cannot publish it as an immutable launch artifact.
    authority = GitAuthority(provider.authority.repository_id, tmp_path / "legacy-copy")
    assert authority.resolve_ref("refs/heads/main")
    provider = ContainedWorkspaceProvider(
        authority, root=provider.root, target_ref=provider.target_ref,
        provider_id=provider.provider_id, posture=provider.posture, launcher=provider.launcher,
    )
    with pytest.raises(ContractViolation, match="fixed root-owned"):
        _ = provider.git


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


def test_capture_revision_binds_the_selected_bootstrap_content(provider, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from constructicon.core.identity import digest
    from constructicon.substrate.executors.linux import ProcessLimits
    from constructicon.substrate.git import process
    from tests.substrate.test_contained_capture import write_provider

    # This identity probe supplies artifact bytes, never an executable to run.
    # The native test separately proves the physical interpreter selection.
    artifact = tmp_path / "bootstrap-artifact"
    artifact.write_bytes(b"installed interpreter A")
    monkeypatch.setattr(process, "git_interpreter", lambda: artifact)
    launch = SimpleNamespace(revision=digest("fake-launch", 1, "inert"), limits=ProcessLimits())
    capture = write_provider(provider, launch)
    before = capture.revision
    artifact.write_bytes(b"installed interpreter B")
    assert capture.revision != before, "bootstrap content is absent from capture identity"
