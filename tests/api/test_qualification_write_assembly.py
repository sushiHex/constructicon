import io
import os
import subprocess
import sys
import tarfile
import tempfile
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


def test_fixture_supplies_private_git_policy_before_initial_config_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fixture"
    original = assembly._git
    initialization = []

    def observed(directory, *args, **kwargs):
        if args[0] == "init":
            initialization.append((args, (directory / "authority.git" / "config").exists()))
        return original(directory, *args, **kwargs)

    monkeypatch.setattr(assembly, "_git", observed)
    pin = assembly.prepare_fixture(root)
    assert initialization == [((
        "init", "--bare", "--shared=0600", "--object-format=sha1", "--template=",
    ), False)]
    assert (root / "authority.git" / "config").read_bytes() == assembly._CONFIG
    assert assembly.inspect_fixture(root) == pin


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


def test_fixture_git_subprocess_seals_child_umask_without_changing_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def spawned(command, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(command, 0, b"checked", b"")

    with monkeypatch.context() as patch:
        # Only the POSIX spawn primitive is observed; no process-global umask
        # or platform filesystem claim is substituted into fixture custody.
        patch.setattr(assembly.subprocess, "run", spawned)
        patch.setattr(assembly, "Path", type(tmp_path))
        patch.setattr(assembly.os, "name", "posix")
        actual = assembly._git(tmp_path, "rev-parse", "--is-bare-repository")
    assert actual == b"checked"
    assert len(calls) == 1 and calls[0].get("umask") == 0o077
    assert "os.umask(" not in Path(assembly.__file__).read_text(encoding="utf-8")


def test_private_acquisition_payload_is_not_interpreted_as_authority_metadata(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fixture"
    pin = assembly.prepare_fixture(root)
    payload = root / "workspace-acquisitions" / "payloads" / "untrusted" / "workspace"
    payload.mkdir(parents=True, mode=0o775)
    outside = tmp_path / "outside"
    outside.write_bytes(b"untrusted worker output")
    os.link(outside, payload / "linked")
    (payload / "linked").chmod(0o664)
    assert assembly.inspect_fixture(root) == pin
    # The identical unsafe alias in the authority remains refused.
    os.link(outside, root / "authority.git" / "hooks" / "pre-receive")
    with pytest.raises(ContractViolation, match="unsafe filesystem"):
        assembly.inspect_fixture(root)


@pytest.mark.parametrize("prefix", [
    "workspace-acquisitions/guards", "workspace-acquisitions/payloads",
    "gate-acquisitions/guards", "gate-acquisitions/payloads",
])
def test_acquisition_metadata_prefix_cannot_redirect_fixture_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str,
) -> None:
    root = tmp_path / "fixture"
    assembly.prepare_fixture(root)
    original = type(root).resolve
    redirected = root / prefix

    def aliased(path, *args, **kwargs):
        # Observe the one canonical-path primitive; actual filesystem checks
        # and other paths remain real (Windows may not create directory links).
        return tmp_path / "outside" if path == redirected else original(path, *args, **kwargs)

    monkeypatch.setattr(type(root), "resolve", aliased)
    with pytest.raises(ContractViolation, match="not canonical"):
        assembly.inspect_fixture(root)


@pytest.mark.parametrize("name", ["workspace-acquisitions", "gate-acquisitions"])
def test_acquisition_container_alias_refused_without_reading_untrusted_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str,
) -> None:
    root = tmp_path / "fixture"
    pin = assembly.prepare_fixture(root)
    container = root / name / "payloads" / ("acq-" + "a" * 32)
    container.mkdir(mode=0o775)
    assert assembly.inspect_fixture(root) == pin
    original = type(root).resolve

    def aliased(path, *args, **kwargs):
        return tmp_path / "outside" if path == container else original(path, *args, **kwargs)

    monkeypatch.setattr(type(root), "resolve", aliased)
    with pytest.raises(ContractViolation, match="container is not a canonical directory"):
        assembly.inspect_fixture(root)


async def test_actual_acquisition_directory_alias_refused_before_constructor_or_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fixture"
    assembly.prepare_fixture(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = root / "workspace-acquisitions" / "payloads" / ("acq-" + "1" * 32)
    if os.name == "nt":
        # The Windows directory-alias primitive, not a substitute resolver.
        subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(alias), str(outside)],
                       stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=30)
    else:
        alias.symlink_to(outside, target_is_directory=True)
    calls = []
    original = assembly.GitAuthority

    class ObservedAuthority(original):
        def __init__(self, *args):
            calls.append(args)
            super().__init__(*args)

    monkeypatch.setattr(assembly, "GitAuthority", ObservedAuthority)
    try:
        with pytest.raises(ContractViolation, match="container is not a canonical directory"):
            await assembly.assemble_contained_write(
                root, SqliteJournal(tmp_path / "journal.db"), ObservedLauncher(),
            )
        assert calls == []
        assert list(outside.iterdir()) == []
    finally:
        if os.name == "nt":
            alias.rmdir()  # Only the checked test junction, never its target.
        else:
            alias.unlink()


_PERMISSIVE_PARENT = """
import asyncio, os, stat, sys
from pathlib import Path
from constructicon.api._qualification_write_assembly import prepare_fixture, inspect_fixture
from constructicon.substrate.executors.linux import DEFAULT_PROCESS_LIMITS
from constructicon.substrate.git.acquisition import AcquisitionClosure, AcquisitionPaths
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.process import GitProcess

os.umask(0o002)
root = Path(sys.argv[1])
pin = prepare_fixture(root)
authority = GitAuthority(root / 'authority.git', root / 'authority-workspaces')
paths = AcquisitionPaths(root / 'workspace-acquisitions', 'acq-' + '0' * 32)
closure = AcquisitionClosure(authority)
closure.publish(paths, 'refs/constructicon/test-candidate', pin.base_commit)
closure.commit(paths, candidate_ref='refs/constructicon/test-candidate')
assert closure.is_closed(paths)
# Export bytes through the actual bounded trusted Git pump, then index them.
git = GitProcess(authority.git_executable, DEFAULT_PROCESS_LIMITS)
async def imported():
    packed = await git.run('pack-objects', '--stdout', '--revs',
        cwd=authority.repository_id, stdin=(pin.base_commit + '\\n').encode())
    indexed = await git.run('index-pack', '--stdin', cwd=authority.repository_id, stdin=packed)
    assert indexed.startswith(b'pack\\t')
asyncio.run(imported())
assert inspect_fixture(root) == pin
for path in (root / 'authority.git').rglob('*'):
    assert not (path.stat().st_mode & 0o022), str(path)
# The parent's deliberately permissive policy was not globally changed.
probe = root / 'workspace-acquisitions' / 'parent-mode'
probe.write_bytes(b'parent')
assert stat.S_IMODE(probe.stat().st_mode) == 0o664
print('private fixture, candidate closure and pack; parent umask unchanged')
"""


@pytest.mark.skipif(os.name != "posix", reason="actual POSIX creation modes require Linux")
def test_permissive_parent_umask_preserves_private_fixture_future_refs_and_packs() -> None:
    with tempfile.TemporaryDirectory(prefix=".n5-custody-", dir=Path.home()) as private:
        root = Path(private).resolve() / "fixture"
        ran = subprocess.run([sys.executable, "-I", "-c", _PERMISSIVE_PARENT, str(root)],
                             stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, timeout=60, check=False)
        assert ran.returncode == 0, ran.stderr
        assert ran.stdout.strip() == (
            "private fixture, candidate closure and pack; parent umask unchanged"
        )
