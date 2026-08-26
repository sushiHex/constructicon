"""Workspace and leased-capability contracts (M3).

The walker owns every ``CapabilityLease`` transition on every exit path, but
it knows only the verbs on ``LeasedCapability`` — acquire, close, reconcile —
never git, paths, or what a worktree is. Identity is computed under the one
identity law: a reclaimed run carries a higher ownership epoch and therefore
a different ``acquisition_id``, so a stale worker's writes can only land in
its own obsolete physical acquisition (the journal fence protects SQLite;
acquisition epochs protect the filesystem).

Code crosses between nodes as ``GitRef`` (I5): the workspace views here hand
out paths for local work and commits for everything durable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from constructicon.core.address import ExecutionPath, GitSha, RunId, ScopePath
from constructicon.core.envelope import GitRef
from constructicon.core.identity import Digest, digest
from constructicon.core.manifest import CapabilityBinding, CapabilityLease
from constructicon.core.run import RunLease

Disposition = Literal["release", "discard", "suspend"]


@runtime_checkable
class WorkspaceView(Protocol):
    """What any node or gate holds: a place to look and a commit identity."""

    @property
    def path(self) -> str: ...

    def git_ref(self) -> GitRef: ...


@runtime_checkable
class WriteWorkspace(WorkspaceView, Protocol):
    """A staged, physically separate working repository. The candidate
    crosses onward as a commit, never as files (I5)."""

    def commit_all(self, message: str) -> GitSha: ...


@dataclass(frozen=True)
class LeaseContext:
    """Everything a provider may know about one acquisition — supplied by
    the walker, never by the node."""

    run_lease: RunLease
    binding: CapabilityBinding
    path: ExecutionPath
    manifest_hash: Digest


@dataclass(frozen=True)
class AcquiredCapability:
    """One live physical acquisition: the injected resource plus the
    identities the journal rows carry."""

    resource: object
    lease_id: str
    acquisition_id: str
    resource_ref: str


@dataclass(frozen=True)
class LeaseClosure:
    disposition: Literal["released", "discarded", "retained"]
    detail: str | None = None


@dataclass(frozen=True)
class LeaseReconciliation:
    """What post-crash reconciliation did with a run's physical leftovers."""

    reaped: tuple[str, ...] = ()  # resource_refs whose physical state was removed
    restored: tuple[str, ...] = ()
    detail: str | None = None


@dataclass(frozen=True)
class StaleAcquisition:
    """One prior-epoch acquisition the walker found still open in the journal.
    The walker decides the disposition (checkpointed invocation -> "release":
    reap the physical leftovers, durable refs stand; uncheckpointed ->
    "discard": the work replays from the pinned base — never adopt a dirty
    workspace as completed computation); the provider executes it."""

    lease: CapabilityLease
    disposition: Disposition


@runtime_checkable
class LeasedCapability(Protocol):
    """A capability whose injection is a physical acquisition the walker
    leases, closes, and reconciles — declared via
    ``CapabilityDescriptor.leased`` and verified at activation."""

    async def acquire(self, context: LeaseContext) -> AcquiredCapability: ...

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition
    ) -> LeaseClosure: ...

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...]
    ) -> LeaseReconciliation: ...


def lease_id_for(run_id: RunId, scope: ScopePath, binding_id: str) -> str:
    """Logical lease identity — computed, never minted (one per
    run/scope/binding across every ownership epoch)."""
    body = digest(
        "capability-lease",
        1,
        {"run_id": run_id, "scope": list(scope.segments), "binding": binding_id},
    )
    return f"lease-{str(body).removeprefix('sha256:')[:32]}"


def acquisition_id_for(lease_id: str, owner_epoch: int) -> str:
    """Physical acquisition identity: one per ownership epoch, so reclaim
    never reuses a stale owner's paths."""
    body = digest(
        "capability-acquisition",
        1,
        {"lease_id": lease_id, "owner_epoch": owner_epoch},
    )
    return f"acq-{str(body).removeprefix('sha256:')[:32]}"
