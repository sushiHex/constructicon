"""Workspace and leased-capability contracts (M3/M4).

The walker owns every ``CapabilityLease`` transition, but knows only acquire,
close, and reconcile — never git, paths, or worktrees. Lease identity is the
full dynamic ``ExecutionPath`` so loop iterations cannot collide.

Code crosses between nodes as ``GitRef`` (I5). A repair iteration receives the
previous candidate as data and may reset a fresh staging workspace to it; the
ref, never a shared worktree, carries state across iterations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from constructicon.core.address import ExecutionPath, GitSha, RunId
from constructicon.core.envelope import GitRef
from constructicon.core.identity import Digest, digest
from constructicon.core.manifest import CapabilityBinding, CapabilityLease
from constructicon.core.run import RunLease

Disposition = Literal["release", "discard"]


@runtime_checkable
class WorkspaceView(Protocol):
    """What any node or gate holds: a place to look and a commit identity."""

    @property
    def path(self) -> str: ...

    def git_ref(self) -> GitRef: ...


@runtime_checkable
class WriteWorkspace(WorkspaceView, Protocol):
    """A staged, physically separate working repository."""

    def reset_to(self, ref: GitRef) -> None: ...

    def commit_all(self, message: str) -> GitSha: ...


@dataclass(frozen=True)
class LeaseContext:
    """Everything a provider may know about one acquisition — walker supplied."""

    run_lease: RunLease
    binding: CapabilityBinding
    path: ExecutionPath
    manifest_hash: Digest


@dataclass(frozen=True)
class AcquiredCapability:
    """One live physical acquisition plus its computed identities."""

    resource: object
    lease_id: str
    acquisition_id: str
    resource_ref: str


@dataclass(frozen=True)
class LeaseClosure:
    disposition: Literal["released", "discarded"]
    detail: str | None = None


@dataclass(frozen=True)
class LeaseReconciliation:
    """What post-crash reconciliation did with physical leftovers."""

    reaped: tuple[str, ...] = ()
    restored: tuple[str, ...] = ()
    detail: str | None = None


@dataclass(frozen=True)
class StaleAcquisition:
    """One prior-epoch acquisition and its walker-selected disposition."""

    lease: CapabilityLease
    disposition: Disposition


@runtime_checkable
class LeasedCapability(Protocol):
    """A capability whose injection requires a physical acquisition."""

    async def acquire(self, context: LeaseContext) -> AcquiredCapability: ...

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition
    ) -> LeaseClosure: ...

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...]
    ) -> LeaseReconciliation: ...


def lease_id_for(run_id: RunId, path: ExecutionPath, binding_id: str) -> str:
    """Logical lease identity — one per run/invocation/binding.

    Schema version 2 makes the M4 shift from static scope to dynamic path
    explicit in the identity law.
    """

    body = digest(
        "capability-lease",
        2,
        {
            "run_id": run_id,
            "path": path.model_dump(mode="json"),
            "binding": binding_id,
        },
    )
    return f"lease-{str(body).removeprefix('sha256:')[:32]}"


def acquisition_id_for(lease_id: str, owner_epoch: int) -> str:
    """Physical acquisition identity: one per ownership epoch."""

    body = digest(
        "capability-acquisition",
        1,
        {"lease_id": lease_id, "owner_epoch": owner_epoch},
    )
    return f"acq-{str(body).removeprefix('sha256:')[:32]}"
