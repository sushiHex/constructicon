import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from constructicon.api import _qualification_write_assembly as assembly
from constructicon.api._qualification_write_graph import (
    CHECKER_GRANTS,
    REQUEST,
    SMOKE_CHECKER_SCOPE,
    smoke_definitions,
    smoke_graph,
)
from constructicon.api.qualification import _contained_system
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.core.qualification_write import WriteQualificationRequest
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.substrate.test_contained_gates import ObservedLauncher


@pytest.fixture(autouse=True)
def portable_owner_check(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only POSIX ownership/mode is platform-bound; real Git/path checks remain.
    monkeypatch.setattr(assembly, "_private_owner", lambda info: None)
    monkeypatch.setattr(assembly, "_ancestor_owner", lambda info: None)


def test_prepare_and_inspect_fixed_fixture(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    pin = assembly.prepare_fixture(root)
    assert assembly.inspect_fixture(root) == pin
    assert pin.target_ref == "refs/heads/n5-write"
    assert len(pin.base_commit) == 40
    with pytest.raises(ContractViolation):
        assembly.prepare_fixture(root)


def test_fixture_rejects_changed_seed(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    assembly.prepare_fixture(root)
    (root / "authority.git" / "HEAD").write_text("ref: refs/heads/other\n")
    with pytest.raises(ContractViolation):
        assembly.inspect_fixture(root)


def test_unreviewed_config_is_refused_before_git_reads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fixture"
    assembly.prepare_fixture(root)
    (root / "authority.git" / "config").write_bytes(b"[include]\npath=/other/config\n")
    calls = []
    original = assembly._git

    def observed(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(assembly, "_git", observed)
    with pytest.raises(ContractViolation, match="configuration"):
        assembly.inspect_fixture(root)
    assert calls == []


def test_linked_hook_refused_before_authority_constructor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fixture"
    assembly.prepare_fixture(root)
    outside = tmp_path / "outside"
    outside.write_bytes(b"untouched")
    os.link(outside, root / "authority.git" / "hooks" / "pre-receive")
    calls = []
    monkeypatch.setattr(assembly, "GitAuthority", lambda *args: calls.append(args))
    with pytest.raises(ContractViolation, match="unsafe filesystem"):
        assembly.inspect_fixture(root)
    assert calls == [] and outside.read_bytes() == b"untouched"


async def test_concrete_assembly_permits_exact_fixture_and_identifies_gate(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    fixture = assembly.prepare_fixture(root)
    journal = SqliteJournal(tmp_path / "journal.db")
    launcher = ObservedLauncher()
    resources = await assembly.assemble_contained_write(root, journal, launcher)
    assembly.require_contained_write(resources)
    pins = assembly.contained_pins(resources, digest("report", 1, "test"))
    assert resources.fixture == fixture
    assert resources.gate.is_assembled_from(journal)
    assert resources.workspace.launcher is resources.gate.launcher is launcher
    assert str(pins.workspace.revision) == resources.workspace.revision
    assert str(pins.gate.revision) == resources.gate.revision
    assert len(launcher.calls) == 1
    assert launcher.calls[0][1]["timeout_s"] == 30
    assert resources.gate.checks[0].timeout_s == 20
    system = _contained_system(resources)
    assert system.describe()
    for definition in smoke_definitions():
        system._register(definition)
    manifest = system.validate(smoke_graph(pins), {REQUEST.name: WriteQualificationRequest(
        authorization_id="credential-free-smoke", fixture_identity=fixture.identity,
        base_commit=fixture.base_commit,
    ).model_dump(mode="json")})
    checker = [binding for binding in manifest.capability_bindings
               if binding.scope == SMOKE_CHECKER_SCOPE]
    assert checker and all(binding.effective_grants == CHECKER_GRANTS for binding in checker)


async def test_post_probe_target_change_refused(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    assembly.prepare_fixture(root)
    launcher = ObservedLauncher()
    original = launcher.run

    async def mutate(command, **kwargs):
        result = await original(command, **kwargs)
        assembly._git(root, "update-ref", "-d", assembly.TARGET)
        return result

    launcher.run = mutate
    with pytest.raises(ContractViolation):
        await assembly.assemble_contained_write(
            root, SqliteJournal(tmp_path / "journal.db"), launcher,
        )


async def test_post_probe_workspace_revision_change_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fixture"
    assembly.prepare_fixture(root)
    launcher = ObservedLauncher()
    original = launcher.run
    revision = assembly.ContainedWriteWorkspaceProvider.revision

    async def mutate(command, **kwargs):
        result = await original(command, **kwargs)
        monkeypatch.setattr(assembly.ContainedWriteWorkspaceProvider, "revision", property(
            lambda self: str(digest("changed", 1, revision.fget(self))),
        ))
        return result

    launcher.run = mutate
    with pytest.raises(ContractViolation, match="workspace source/runtime"):
        await assembly.assemble_contained_write(
            root, SqliteJournal(tmp_path / "journal.db"), launcher,
        )


def test_fixed_check_permits_actual_git_mode_100644_archive(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    pin = assembly.prepare_fixture(root)
    blob = assembly._git(root, "hash-object", "-w", "--stdin", stdin=b"ready\n").strip()
    tree = assembly._git(root, "mktree", stdin=b"100644 blob " + blob + b"\tn5-write.txt\n").strip()
    commit = assembly._git(root, "commit-tree", tree.decode(), "-p", pin.base_commit,
                           stdin=b"candidate\n").strip().decode()
    raw = assembly._git(root, "archive", "--format=tar", commit)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        assert archive.getmember("n5-write.txt").mode & 0o111 == 0
        archive.extractall(snapshot, filter="data")
    ran = subprocess.run([sys.executable, "-I", "-c", assembly.CHECK_PROGRAM], cwd=snapshot,
                         stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False)
    assert ran.returncode == 0, ran.stderr
