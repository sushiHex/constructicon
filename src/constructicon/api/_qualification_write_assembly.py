"""Concrete, custody-checked resources for the one N5 WRITE fixture."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.manifest import parse_manifest_json, source_graph_hash_for
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.qualification_write import (
    QualificationCapabilityPin,
    QualificationFixturePin,
    WriteQualificationPins,
)
from constructicon.substrate.executors import codex_lane
from constructicon.substrate.executors.codex import CodexOperatorProvider
from constructicon.substrate.executors.codex_host import (
    WRITE_GRANTS,
    WRITE_PROFILE,
    HostSession,
    write_operator_provider,
)
from constructicon.substrate.executors.codex_protocol import CONTAINED_PYTHON_CATALOG
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.gates.contained import ContainedGateRunner
from constructicon.substrate.gates.runner import CheckSpec
from constructicon.substrate.git.authority import _PINNED_ENV, GitAuthority
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.journal.sqlite import SqliteJournal

WORKSPACE_CAPABILITY = "n5-write-workspace"
GATE_CAPABILITY = "n5-write-gate"
TARGET = "refs/heads/n5-write"
_SEED = (
    b"tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904\n"
    b"author constructicon <authority@constructicon.invalid> 1767225600 +0000\n"
    b"committer constructicon <authority@constructicon.invalid> 1767225600 +0000\n"
    b"\nconstructicon N5 WRITE seed\n"
)
_BASE = hashlib.sha1(b"commit " + str(len(_SEED)).encode() + b"\0" + _SEED).hexdigest()
_CONFIG = (
    b"[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = true\n"
    b"\tsharedRepository = 0600\n"
)
_CHILDREN = ("authority.git", "authority-workspaces", "workspace-acquisitions", "gate-acquisitions")
_ACQUISITION_PREFIXES = tuple(
    f"{root}/{child}" for root in ("workspace-acquisitions", "gate-acquisitions")
    for child in ("guards", "payloads")
)
CHECK_PROGRAM = (
    "import pathlib,stat\n"
    "p=pathlib.Path('n5-write.txt')\n"
    "assert sorted(x.name for x in pathlib.Path('.').iterdir()) == ['n5-write.txt']\n"
    "s=p.lstat()\n"
    "assert stat.S_ISREG(s.st_mode) and not (s.st_mode & 0o111)\n"
    "assert p.read_bytes() == b'ready\\n'\n"
)
WRITE_CHECKS = (CheckSpec(
    name="n5-write-exact-file", argv=("/usr/bin/python3", "-I", "-c", CHECK_PROGRAM),
    timeout_s=20,
),)


def _private_owner(info: os.stat_result) -> None:
    uid = getattr(os, "getuid", lambda: -1)()
    if os.name != "posix" or uid <= 0 or info.st_uid != uid or info.st_mode & 0o022:
        raise ContractViolation("the WRITE fixture requires private service-owned POSIX custody")


def _private_directory(info: os.stat_result) -> None:
    _private_owner(info)
    if os.name == "posix" and stat.S_IMODE(info.st_mode) != 0o700:
        raise ContractViolation("WRITE fixture roots require private 0700 custody")


def _ancestors(path: Path) -> None:
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or parent.resolve() != parent:
            raise ContractViolation("WRITE fixture ancestors must be canonical directories")
        _ancestor_owner(info)


def _ancestor_owner(info: os.stat_result) -> None:
    if os.name == "posix" and (
        info.st_uid not in (0, getattr(os, "getuid", lambda: -1)()) or info.st_mode & 0o022
    ):
        raise ContractViolation("WRITE fixture ancestors lack trusted custody")


def _directory(path: Path) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise ContractViolation("the WRITE fixture path is not canonical")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ContractViolation("the WRITE fixture contains a non-directory")
    _private_directory(info)


def _acquisition_container(path: Path) -> None:
    """The service-owned container is metadata; its contents are model data.

    It may inherit 0775 at creation, but only below a checked 0700 payloads
    prefix. No other user can reach it. An alias/foreign owner is never allowed
    to redirect materialization outside that prefix.
    """
    if path.resolve() != path or not stat.S_ISDIR(path.lstat().st_mode):
        raise ContractViolation("WRITE acquisition container is not a canonical directory")
    if os.name == "posix" and path.lstat().st_uid != getattr(os, "getuid", lambda: -1)():
        raise ContractViolation("WRITE acquisition container belongs to another service owner")


def _custody(root: Path) -> None:
    try:
        _ancestors(root)
        paths = (
            root, *(root / child for child in (*_CHILDREN, *_ACQUISITION_PREFIXES)),
            root / "authority.git" / "hooks",
        )
        for path in paths:
            _directory(path)
        for name in ("workspace-acquisitions", "gate-acquisitions"):
            for path in (root / name / "payloads").iterdir():
                _acquisition_container(path)
        # Construction overwrites the hook: reject links before that write.
        # This is authority metadata custody, not a second validator for model
        # payloads. Acquired workspaces/snapshots live below their own canonical
        # private roots and their adapters own validation and disposal. They
        # legitimately contain archive modes and untrusted links while active.
        for path in (root / "authority.git").rglob("*"):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (
                stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
            ) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                raise ContractViolation("the WRITE authority contains an unsafe filesystem entry")
            _private_owner(info)
        for forbidden in ("objects/info/alternates", "info/grafts", "refs/replace"):
            if (root / "authority.git" / forbidden).exists():
                raise ContractViolation("the WRITE authority contains alternate object authority")
    except OSError as exc:
        raise ContractViolation("the WRITE fixture custody is unavailable") from exc


def _git(root: Path, *args: str, stdin: bytes = b"") -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise ContractViolation("the WRITE fixture requires trusted Git")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(
        (str(Path(executable).resolve()), "--git-dir", str(root / "authority.git"), *args),
        input=stdin, capture_output=True, timeout=60, env={**env, **_PINNED_ENV}, check=False,
        # Popen sets this in the child only. Never alter the service's process-
        # global umask while other invocations may be creating files.
        umask=0o077 if os.name == "posix" else -1,
    )
    if result.returncode:
        raise ContractViolation("the WRITE fixture Git check failed")
    return result.stdout


def prepare_fixture(root: Path) -> QualificationFixturePin:
    """Prepare only a fresh canonical private fixture, with literal seed bytes."""
    if not root.is_absolute() or root.resolve() != root or root.exists():
        raise ContractViolation("WRITE preparation requires a fresh canonical absolute root")
    _ancestors(root)
    _private_owner(root.parent.stat())
    root.mkdir(mode=0o700)
    _directory(root)
    for name in (*_CHILDREN, *_ACQUISITION_PREFIXES):
        (root / name).mkdir(mode=0o700)
    _git(root, "init", "--bare", "--object-format=sha1", "--template=")
    # Git may inherit host defaults at init; no such setting survives preparation.
    (root / "authority.git" / "config").write_bytes(_CONFIG)
    (root / "authority.git" / "hooks").mkdir(mode=0o700, exist_ok=True)
    _git(root, "mktree")
    seed = _git(root, "hash-object", "-t", "commit", "-w", "--stdin", stdin=_SEED)
    if seed.strip().decode() != _BASE:
        raise ContractViolation("trusted Git produced another WRITE seed")
    _git(root, "update-ref", TARGET, _BASE)
    _git(root, "symbolic-ref", "HEAD", TARGET)
    return inspect_fixture(root)


def inspect_fixture(root: Path) -> QualificationFixturePin:
    _custody(root)
    if (root / "authority.git" / "config").read_bytes() != _CONFIG:
        raise ContractViolation("the WRITE authority contains unreviewed Git configuration")
    if (
        _git(root, "rev-parse", "--is-bare-repository").strip() != b"true"
        or _git(root, "rev-parse", "--show-object-format").strip() != b"sha1"
        or _git(root, "symbolic-ref", "HEAD").strip().decode() != TARGET
        or _git(root, "rev-parse", "--verify", TARGET).strip().decode() != _BASE
        or _git(root, "cat-file", "commit", _BASE) != _SEED
    ):
        raise ContractViolation("the WRITE fixture is not the reviewed fixed seed")
    return QualificationFixturePin(
        identity=digest("qualification-write-fixture", 1, {
            "root": str(root), "authority": str(root / "authority.git"),
            "seed": _SEED.decode(), "target": TARGET, "file": "n5-write.txt",
            "contents": "ready\n", "mode": "100644",
        }), base_commit=_BASE, target_ref=TARGET,
    )


@dataclass(frozen=True)
class ContainedWriteResources:
    journal: SqliteJournal
    authority: GitAuthority
    fixture: QualificationFixturePin
    workspace: ContainedWriteWorkspaceProvider
    gate: ContainedGateRunner


@dataclass(frozen=True)
class WriteAssembly:
    executor: CodexOperatorProvider
    resources: ContainedWriteResources
    pins: WriteQualificationPins


def require_contained_write(resources: ContainedWriteResources) -> None:
    if not (
        isinstance(resources.journal, SqliteJournal)
        and isinstance(resources.authority, GitAuthority)
        and isinstance(resources.workspace, ContainedWriteWorkspaceProvider)
        and isinstance(resources.gate, ContainedGateRunner)
    ):
        raise ContractViolation("WRITE assembly requires concrete contained resource kinds")
    root = Path(resources.authority.repository_id).parent
    if inspect_fixture(root) != resources.fixture or not (
        Path(resources.authority.repository_id) == root / "authority.git"
        and resources.authority._repo == root / "authority.git"
        and resources.authority._root == root / "authority-workspaces"
        and resources.workspace.authority is resources.authority
        and resources.gate.authority is resources.authority
        and resources.gate.is_assembled_from(resources.journal)
        and resources.workspace.launcher is resources.gate.launcher
        and resources.workspace.root == root / "workspace-acquisitions"
        and resources.gate.root == root / "gate-acquisitions"
        and resources.workspace.target_ref == resources.gate.target_ref == TARGET
        and resources.workspace.provider_id == WORKSPACE_CAPABILITY
        and resources.gate.provider_id == GATE_CAPABILITY
        and resources.gate.checks == WRITE_CHECKS
        and resources.workspace.posture is Posture.WRITE
    ):
        raise ContractViolation("WRITE resources differ from the concrete fixed assembly")
    _ = resources.workspace.revision, resources.gate.revision


def contained_pins(
    resources: ContainedWriteResources, report_definition: Digest,
) -> WriteQualificationPins:
    require_contained_write(resources)
    return WriteQualificationPins(
        workspace=QualificationCapabilityPin(
            capability_id=WORKSPACE_CAPABILITY, revision=resources.workspace.revision,
        ),
        gate=QualificationCapabilityPin(
            capability_id=GATE_CAPABILITY, revision=resources.gate.revision,
        ),
        fixture=resources.fixture, report_definition=report_definition,
    )


async def assemble_contained_write(
    fixture_root: Path, journal: SqliteJournal, launcher: LinuxLauncher,
) -> ContainedWriteResources:
    fixture = inspect_fixture(fixture_root)  # Before constructor installs its hook.
    authority = GitAuthority(fixture_root / "authority.git", fixture_root / "authority-workspaces")
    workspace = ContainedWriteWorkspaceProvider(
        authority, root=fixture_root / "workspace-acquisitions", target_ref=TARGET,
        provider_id=WORKSPACE_CAPABILITY, posture=Posture.WRITE, launcher=launcher,
    )
    before = workspace.revision
    gate = await ContainedGateRunner.create(
        journal=journal, authority=authority, root=fixture_root / "gate-acquisitions",
        target_ref=TARGET, provider_id=GATE_CAPABILITY, launcher=launcher, checks=WRITE_CHECKS,
    )
    resources = ContainedWriteResources(journal, authority, fixture, workspace, gate)
    require_contained_write(resources)  # Runtime probes awaited: recheck the mutable world.
    if workspace.revision != before:
        raise ContractViolation("WRITE workspace source/runtime changed during identification")
    return resources


def require_write_assembly(
    assembly: WriteAssembly, authorization: QualificationAuthorization,
) -> None:
    from constructicon.api._qualification_write_graph import (
        EXECUTOR,
        WRITER_SCOPE,
        write_graph,
        write_inputs,
    )
    from constructicon.api._qualification_write_report import write_report_definition
    from constructicon.runtime.registry import CapabilityDescriptor
    from constructicon.runtime.validator import admit

    try:
        QualificationAuthorization.model_validate(authorization.model_dump(mode="json"))
    except ValidationError as exc:
        raise ContractViolation("WRITE authorization violates its closed core contract") from exc
    require_contained_write(assembly.resources)
    actual = contained_pins(assembly.resources, write_report_definition())
    provider = assembly.executor
    if not (
        isinstance(provider, CodexOperatorProvider)
        and assembly.pins == actual and authorization.write == actual
        and authorization.stage == "qualification-write"
        and canonical_json(authorization.grants) == canonical_json(WRITE_GRANTS)
        and provider.profile == WRITE_PROFILE
        and provider.identity.profile == WRITE_PROFILE
        and provider.catalog == CONTAINED_PYTHON_CATALOG
        and provider.configuration == codex_lane.production_configuration()
        and provider.launcher is assembly.resources.workspace.launcher
        and authorization.revision == str(provider.identity.revision)
        and authorization.operator_binding_digest == provider.identity.store.operator_binding_digest
        and authorization.scope == WRITER_SCOPE and authorization.binding == EXECUTOR
        and authorization.source_graph_hash == source_graph_hash_for(
            write_graph(authorization.capability_id, actual),
        )
        and Path(authorization.journal).is_absolute()
        and Path(authorization.journal).resolve() == Path(
            assembly.resources.journal._db_path,
        ).resolve()
        and canonical_json(provider.qualification) == canonical_json(authorization)
    ):
        raise ContractViolation("WRITE authorization differs from actual assembled resources")
    journal = assembly.resources.journal
    retained_hash = journal.run_manifest_hash(authorization.run_id)
    if retained_hash is not None:
        raw = journal.load_manifest_json(retained_hash)
        retained_inputs = journal.run_inputs(authorization.run_id)
        if raw is None or canonical_json(retained_inputs) != canonical_json(
            write_inputs(authorization),
        ):
            raise ContractViolation("retained WRITE run has different or unavailable inputs")
        resources = assembly.resources
        capability = authorization.capability_id
        catalog = {
            capability: CapabilityDescriptor(
                capability_id=capability, kind="executor", leased=True,
                revision=provider.identity.revision, executor_profile=provider.profile,
            ),
            WORKSPACE_CAPABILITY: CapabilityDescriptor(
                capability_id=WORKSPACE_CAPABILITY, kind="workspace.contained", leased=True,
                revision=resources.workspace.revision, requires_posture=Posture.WRITE,
            ),
            GATE_CAPABILITY: CapabilityDescriptor(
                capability_id=GATE_CAPABILITY, kind="gates.contained", leased=True,
                revision=resources.gate.revision,
            ),
        }
        expected = admit(
            write_graph(capability, actual), snapshot=journal.snapshot(), catalog=catalog,
            capabilities={capability: provider, WORKSPACE_CAPABILITY: resources.workspace,
                          GATE_CAPABILITY: resources.gate},
            root_grants=WRITE_GRANTS, inputs=write_inputs(authorization),
        )
        if canonical_json(parse_manifest_json(raw)) != canonical_json(expected):
            raise ContractViolation("retained WRITE manifest differs from actual admitted assembly")


async def assemble_write(
    host: HostSession, fixture_root: Path, journal: SqliteJournal,
    authorization: QualificationAuthorization | None = None,
) -> WriteAssembly:
    from constructicon.api._qualification_write_report import write_report_definition

    resources = await assemble_contained_write(
        fixture_root, journal, codex_lane._launcher(host.launch_root),
    )
    executor = write_operator_provider(host, resources.workspace, authorization)
    pins = contained_pins(resources, write_report_definition())
    assembly = WriteAssembly(executor, resources, pins)
    if authorization is not None:
        require_write_assembly(assembly, authorization)
    return assembly
