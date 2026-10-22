"""Portable Git proof for the fixed credential-free Claude READ fixture."""

from __future__ import annotations

import hashlib
import inspect
import os
import shutil
import stat
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from constructicon.api import _claude_read_fixture as fixture
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.identity import digest
from constructicon.core.manifest import CapabilityBinding
from constructicon.core.run import RunLease
from constructicon.core.workspace import LeaseContext
from constructicon.substrate.executors.claude_read_worker import READ_WORKER_LIMITS
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.git import acquisition, authority, contained

_REAL_SERVICE_OWNER = fixture._service_owner
_REAL_ANCESTOR_OWNER = fixture._ancestor_owner


@pytest.fixture(autouse=True)
def portable_owner_primitive(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the POSIX ownership premise is substituted. Exact Git/path checks run.
    monkeypatch.setattr(fixture, "_service_owner", lambda info: None)
    monkeypatch.setattr(fixture, "_ancestor_owner", lambda info: None)


def _context(run_id: str = "fixture-run") -> LeaseContext:
    scope = ScopePath(segments=("claude-read", "read"))
    return LeaseContext(
        run_lease=RunLease(run_id=RunId(run_id), owner_id="fixture-owner", epoch=1,
                           expires_at=datetime.now(UTC) + timedelta(minutes=5)),
        binding=CapabilityBinding(
            scope=scope, binding="workspace", capability_id=fixture.WORKSPACE_CAPABILITY,
            revision=fixture.REVISION,
            effective_grants=EffectiveGrants(
                posture=Posture.READ, model_selection=ModelSelection(kind="backend_default"),
                effort=None, allowed_tools=(), env_allowlist=(), network="none", timeout_s=30,
            ),
        ),
        path=ExecutionPath(scope=scope), manifest_hash=digest("test-manifest", 1, "fixture"),
    )


def test_prepare_inspect_exact_one_file_and_source_revision(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    identity = fixture.prepare_fixture(root)
    assert fixture.inspect_fixture(root) == identity
    assert fixture.TARGET == "refs/heads/claude-read"
    assert fixture.FILE == "ready.txt" and fixture.CONTENT == b"ready\n"
    assert len(fixture.BASE) == 40
    assert str(digest("claude-read-fixture-source", 1, {
        "fixture": hashlib.sha256(Path(fixture.__file__).read_bytes()).hexdigest(),
        "shared_config": hashlib.sha256(fixture._CONFIG).hexdigest(),
        "shared_git": hashlib.sha256(inspect.getsource(fixture._git).encode()).hexdigest(),
        "git_authority": hashlib.sha256(inspect.getsource(authority).encode()).hexdigest(),
        "contained_workspace": hashlib.sha256(inspect.getsource(contained).encode()).hexdigest(),
        "acquisition": hashlib.sha256(inspect.getsource(acquisition).encode()).hexdigest(),
    })) == fixture.REVISION
    assert fixture._git(root, "cat-file", "commit", fixture.BASE) == fixture._SEED
    assert fixture._git(root, "cat-file", "tree", fixture._TREE) == fixture._TREE_BYTES
    assert fixture._git(root, "cat-file", "blob", fixture._BLOB) == fixture.CONTENT
    with pytest.raises(ContractViolation, match="fresh canonical"):
        fixture.prepare_fixture(root)


async def test_real_workspace_acquires_the_pinned_ref(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    fixture.prepare_fixture(root)
    launcher = LinuxLauncher(
        runtime_root=tmp_path / "runtime", expected_runtime=digest("runtime", 1, "fixture"),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="0" * 64, limits=READ_WORKER_LIMITS,
    )
    provider = fixture.workspace_provider(root, launcher)
    assert provider.target_ref == fixture.TARGET
    assert provider.root == root / "workspace-acquisitions"
    assert provider.launcher.limits == fixture.MATERIALIZATION_LIMITS
    assert launcher.limits == READ_WORKER_LIMITS
    acquired = await provider.acquire(_context())
    assert acquired.resource.base == fixture.BASE
    assert (await provider.close(acquired, "discard")).disposition == "discarded"


async def test_exact_archive_materializes_under_its_distinct_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fixture"
    fixture.prepare_fixture(root)
    launcher = LinuxLauncher(
        runtime_root=tmp_path / "runtime", expected_runtime=digest("runtime", 1, "fixture"),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="0" * 64, limits=READ_WORKER_LIMITS,
    )
    provider = fixture.workspace_provider(root, launcher)

    @asynccontextmanager
    async def fake_guard(paths: object):
        paths.payload.mkdir(parents=True, exist_ok=True)
        yield 0

    async def fake_dispose(closure: object, paths: object) -> bool:
        shutil.rmtree(paths.payload)
        return True

    monkeypatch.setattr(contained, "acquisition_guard", fake_guard)
    monkeypatch.setattr(contained, "dispose_acquisition", fake_dispose)
    acquired = await provider.acquire(_context())
    completed = False
    try:
        await acquired.materialize()
        completed = True
    except ContractViolation:
        pass
    assert completed, "the fixed one-file Git archive must fit its materialization bound"
    assert (Path(acquired.resource.path) / fixture.FILE).read_bytes() == fixture.CONTENT
    assert (await provider.close(acquired, "discard")).disposition == "discarded"

    # The real one-file tar exceeds this reduced bound. A too-small bound
    # must fail at the Git output pump, not accidentally accept a short file.
    provider.launcher = replace(provider.launcher, limits=replace(
        fixture.MATERIALIZATION_LIMITS, artifact_bytes=8192,
    ))
    acquired = await provider.acquire(_context(run_id="second"))
    with pytest.raises(ContractViolation, match="materialization bound"):
        await acquired.materialize()
    assert (await provider.close(acquired, "discard")).disposition == "discarded"


def test_changed_ref_refuses_before_authority_constructor(tmp_path: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "fixture"
    fixture.prepare_fixture(root)
    changed = fixture._git(root, "hash-object", "-t", "commit", "-w", "--stdin",
                           stdin=fixture._SEED.replace(b"fixture", b"changed")).strip().decode()
    fixture._git(root, "update-ref", fixture.TARGET, changed)
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(fixture, "GitAuthority", lambda *args: calls.append(args))
    with pytest.raises(ContractViolation, match="fixed one-file seed"):
        fixture.workspace_provider(root, cast(LinuxLauncher, SimpleNamespace()))
    assert calls == []


def test_changed_config_refuses_before_git_reads(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "fixture"
    fixture.prepare_fixture(root)
    (root / "authority.git" / "config").write_bytes(b"[include]\npath=/other\n")
    calls: list[tuple[object, ...]] = []
    # Keep the source closure fixed while substituting the Git observation.
    monkeypatch.setattr(fixture, "_revision", lambda: fixture.REVISION)
    monkeypatch.setattr(fixture, "_git", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ContractViolation, match="configuration"):
        fixture.inspect_fixture(root)
    assert calls == []


def test_shared_git_configuration_drift_changes_revision_before_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fixture"
    # A mutant changing the revision law is tested from its own initially
    # coherent source world, then the shared config is changed afterward.
    monkeypatch.setattr(fixture, "REVISION", fixture._revision())
    fixture.prepare_fixture(root)
    monkeypatch.setattr(fixture, "_CONFIG", fixture._CONFIG + b"\n# changed\n")
    assert fixture._revision() != fixture.REVISION
    with pytest.raises(ContractViolation, match="source changed"):
        fixture.inspect_fixture(root)


def test_alternate_object_authority_refuses_before_git_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fixture"
    fixture.prepare_fixture(root)
    (root / "authority.git" / "objects" / "info" / "alternates").write_bytes(
        b"/untrusted/objects\n",
    )
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(fixture, "_git", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ContractViolation, match="alternate object authority"):
        fixture.inspect_fixture(root)
    assert calls == []


def test_linked_authority_entry_refuses_before_hook_write(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "fixture"
    fixture.prepare_fixture(root)
    outside = tmp_path / "outside"
    outside.write_bytes(b"untouched")
    try:
        os.link(outside, root / "authority.git" / "hooks" / "pre-receive")
    except OSError:
        pytest.skip("hardlink primitive unavailable on this filesystem")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(fixture, "GitAuthority", lambda *args: calls.append(args))
    with pytest.raises(ContractViolation, match="unsafe entry"):
        fixture.workspace_provider(root, cast(LinuxLauncher, SimpleNamespace()))
    assert calls == [] and outside.read_bytes() == b"untouched"


def test_service_owner_primitive_requires_nonroot_private_posix_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fixture, "os", SimpleNamespace(name="posix", getuid=lambda: 1001))
    _REAL_SERVICE_OWNER(SimpleNamespace(st_uid=1001, st_mode=stat.S_IFREG | 0o600))
    for uid, mode in ((0, 0o600), (1002, 0o600), (1001, 0o620), (1001, 0o602)):
        with pytest.raises(ContractViolation, match="private service-owned"):
            _REAL_SERVICE_OWNER(SimpleNamespace(st_uid=uid, st_mode=stat.S_IFREG | mode))
    monkeypatch.setattr(fixture, "os", SimpleNamespace(name="posix", getuid=lambda: 0))
    with pytest.raises(ContractViolation, match="private service-owned"):
        _REAL_SERVICE_OWNER(SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o600))


def test_ancestor_owner_primitive_requires_trusted_nonwritable_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fixture, "os", SimpleNamespace(name="posix", getuid=lambda: 1001))
    for uid in (0, 1001):
        _REAL_ANCESTOR_OWNER(SimpleNamespace(st_uid=uid, st_mode=stat.S_IFDIR | 0o755))
    for uid, mode in ((1002, 0o755), (1001, 0o775), (0, 0o757)):
        with pytest.raises(ContractViolation, match="trusted custody"):
            _REAL_ANCESTOR_OWNER(SimpleNamespace(st_uid=uid, st_mode=stat.S_IFDIR | mode))
