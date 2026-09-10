"""Deferred Git workspace views owned by the existing invocation lease.

READ exports an exact tree. WRITE initializes a separate repository through
the concrete Linux launcher; it deliberately exposes no legacy commit_all.
Safe async capture is PR C, not an uncontained escape on this view.
"""

from __future__ import annotations

import asyncio
import io
import tarfile
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import GitSha
from constructicon.core.envelope import GitRef
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import canonical_json, parse_json_value
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseClosure,
    LeaseContext,
    LeaseReconciliation,
    StaleAcquisition,
    WorkspaceView,
    acquisition_id_for,
    lease_id_for,
)
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.git.acquisition import (
    AcquisitionClosure,
    AcquisitionPaths,
    acquisition_guard,
    dispose_acquisition,
)
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.process import GitProcess


class _WorkspaceReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    acquisition: str
    provider: str
    base: str


@dataclass
class _WorkspacePhase:
    entered: bool = False
    ready: bool = False
    closed: bool = False
    head: GitSha | None = None


@dataclass(frozen=True, eq=False)
class ContainedWorkspace:
    """A provider-minted WorkspaceView with immutable acquisition coordinates."""

    provider: ContainedWorkspaceProvider
    context: LeaseContext
    paths: AcquisitionPaths
    base: GitSha
    _phase: _WorkspacePhase = field(default_factory=_WorkspacePhase)

    @property
    def entered(self) -> bool:
        return self._phase.entered

    @property
    def ready(self) -> bool:
        return self._phase.ready

    @property
    def closed(self) -> bool:
        return self._phase.closed

    @property
    def path(self) -> str:
        return str(self.paths.payload / "workspace")

    def git_ref(self) -> GitRef:
        return GitRef(repository=self.provider.authority.repository_id, commit=self.base)

    async def materialize(self) -> None:
        if self.closed:
            raise ContractViolation("locally closed workspace cannot materialize")
        if self.entered:
            raise ContractViolation("workspace materialization already entered")
        self._phase.entered = True  # Before the first await or persistent operation.
        async with acquisition_guard(self.paths) as guard:
            await finish_owned(asyncio.create_task(asyncio.to_thread(
                self.provider.closure.require_open, self.paths,
            )))
            Path(self.path).mkdir(parents=True, exist_ok=False)
            await self.provider.populate(self, guard)
            self._phase.ready = True

    @asynccontextmanager
    async def use(self) -> AsyncIterator[int]:
        self.provider.owned_view(self, self.context)
        async with acquisition_guard(self.paths) as guard:
            self.provider.owned_view(self, self.context)
            await finish_owned(asyncio.create_task(asyncio.to_thread(
                self.provider.closure.require_open, self.paths,
            )))
            if Path(self.path).is_symlink() or not Path(self.path).is_dir():
                raise ContractViolation("workspace mount is no longer its owned directory")
            yield guard


class ContainedWorkspaceProvider:
    def __init__(
        self, authority: GitAuthority, *, root: Path, target_ref: str,
        provider_id: str, posture: Posture, launcher: LinuxLauncher,
    ) -> None:
        self.authority = authority
        self.root = root
        self.target_ref = target_ref
        self.provider_id = provider_id
        self.posture = posture
        self.launcher = launcher
        self.closure = AcquisitionClosure(authority)
        self._views: weakref.WeakSet[ContainedWorkspace] = weakref.WeakSet()

    @property
    def git(self) -> str:
        return self.authority.git_executable

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        if context.binding.effective_grants.posture is not self.posture:
            raise ContractViolation("workspace posture differs from its sealed acquisition")
        lease_id = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        acquisition = acquisition_id_for(lease_id, context.run_lease.epoch)
        paths = AcquisitionPaths(self.root, acquisition)
        base = await finish_owned(asyncio.create_task(asyncio.to_thread(
            self.authority.resolve_ref, self.target_ref,
        )))
        workspace = self._workspace(context, paths, base)
        self._views.add(workspace)
        reference = _WorkspaceReference(
            acquisition=acquisition, provider=self.provider_id, base=base,
        )
        return AcquiredCapability(
            resource=workspace, lease_id=lease_id, acquisition_id=acquisition,
            resource_ref=canonical_json(reference.model_dump(mode="json")),
            materialize=workspace.materialize,
        )

    def _workspace(
        self, context: LeaseContext, paths: AcquisitionPaths, base: GitSha,
    ) -> ContainedWorkspace:
        return ContainedWorkspace(self, context, paths, base)

    def owned_view(self, view: WorkspaceView | None, context: LeaseContext) -> ContainedWorkspace:
        if (
            not isinstance(view, ContainedWorkspace)
            or view.provider is not self or view not in self._views
        ):
            raise ContractViolation("workspace must be minted by the assembled provider")
        actual = view.context
        logical = lease_id_for(actual.run_lease.run_id, actual.path, actual.binding.binding)
        expected = AcquisitionPaths(self.root, acquisition_id_for(logical, actual.run_lease.epoch))
        if (
            actual.run_lease.run_id != context.run_lease.run_id
            or actual.run_lease.epoch != context.run_lease.epoch
            or actual.path != context.path
            or actual.manifest_hash != context.manifest_hash
            or context.binding.effective_grants.posture is not self.posture
            or view.paths != expected
            or view.closed or not view.ready
        ):
            raise ContractViolation("workspace does not own this open invocation and epoch")
        return view

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition,
    ) -> LeaseClosure:
        workspace = acquisition.resource
        if (
            not isinstance(workspace, ContainedWorkspace)
            or workspace.provider is not self or workspace not in self._views
        ):
            raise ContractViolation("workspace close requires its provider's acquisition")
        workspace._phase.closed = True
        if workspace.entered:
            await self._dispose(workspace.paths, workspace.context.run_lease.run_id, disposition)
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def _dispose(
        self, paths: AcquisitionPaths, run_id: str, disposition: Disposition,
    ) -> None:
        await dispose_acquisition(self.closure, paths)

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...],
    ) -> LeaseReconciliation:
        reaped = []
        for item in stale:
            row = item.lease
            logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
            if (
                row.lease_id != logical or row.run_id != context.run_lease.run_id
                or row.path != context.path or row.binding_id != context.binding.binding
                or row.acquisition_epoch >= context.run_lease.epoch or row.resource_ref is None
            ):
                raise ContractViolation("workspace recovery row is not this stale invocation")
            reference = _WorkspaceReference.model_validate(parse_json_value(row.resource_ref))
            acquisition = acquisition_id_for(logical, row.acquisition_epoch)
            if (
                reference.acquisition != acquisition or reference.provider != self.provider_id
                or canonical_json(reference.model_dump(mode="json")) != row.resource_ref
            ):
                raise ContractViolation("workspace recovery reference contradicts its durable row")
            # No current base lookup: a never-started lease is fully recoverable.
            await self._dispose(
                AcquisitionPaths(self.root, acquisition), context.run_lease.run_id,
                item.disposition,
            )
            reaped.append(row.resource_ref)
        return LeaseReconciliation(reaped=tuple(reaped))

    async def _export(self, *args: str, stdin: bytes = b"") -> bytes:
        """Bounded read of the trusted authority; it writes no acquisition path."""

        return await GitProcess(self.git, self.launcher.limits).run(
            *args, cwd=self.authority.repository_id, stdin=stdin,
        )

    async def populate(self, workspace: ContainedWorkspace, guard: int) -> None:
        if self.posture is Posture.READ:
            content = await self._export("archive", "--format=tar", workspace.base)

            def extract() -> None:
                with tarfile.open(fileobj=io.BytesIO(content)) as archive:
                    archive.extractall(workspace.path, filter="data")

            await finish_owned(asyncio.create_task(asyncio.to_thread(extract)))
            return
        content = await self._export(
            "pack-objects", "--stdout", "--revs", stdin=f"{workspace.base}\n".encode(),
        )
        setup = (
            "import subprocess,sys; "
            "subprocess.run(['/usr/bin/git','init','--template=','--initial-branch=work',"
            f"'--object-format={self.authority.environment.object_format}'],check=True); "
            "subprocess.run(['/usr/bin/git','index-pack','--stdin'],input=sys.stdin.buffer.read(),"
            "check=True); "
            f"subprocess.run(['/usr/bin/git','update-ref','refs/heads/work','{workspace.base}'],"
            "check=True); subprocess.run(['/usr/bin/git','checkout','--force'],check=True)"
        )
        result = await self.launcher.run(
            ("/usr/bin/python3", "-I", "-c", setup), workspace=Path(workspace.path),
            posture=Posture.WRITE, guard_fds=(guard,), stdin=content, timeout_s=30,
            input_kind="artifact",
        )
        if result.returncode or result.timed_out or result.bound_exceeded:
            raise ContractViolation("contained staging initialization failed")
