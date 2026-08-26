"""The sealed executable form (I13).

An ``ExecutionManifest`` is the compiled, immutable result of resolution and
admission — executable, lockfile, and deployment manifest in one object. After
admission there is NO remaining magnetism, adjacency, scope search, or implicit
boundary behavior: only explicit resolved edges.

The walker accepts ONLY an ExecutionManifest, never an authored Graph. One
object answers: what ran, what connected, what was granted, what to resume,
what to reproduce, what an attestation binds to, what to inspect.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import ScopePath
from constructicon.core.grants import EffectiveGrants
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest
from constructicon.core.ports import PortAddress

MANIFEST_SCHEMA_VERSION = 1

# Every atomic instance carries its sealed grants under this reserved binding
# name; real capability aliases get their own rows.
SELF_BINDING = "__node__"
SELF_CAPABILITY = "__node__"

LeaseLifetime = Literal["invocation", "scope", "run"]


class ResolvedPortBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    destination: PortAddress
    # >1 sources only for cardinality="many"; a gathering binding records its
    # complete expected producer set (the silent-node-failure defense).
    sources: tuple[PortAddress, ...]


class ComponentResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: ScopePath  # static scope — iterations do not exist yet
    component: str
    requested_version: str | None
    resolved_version: Digest
    contract_hash: Digest
    implementation_digest: Digest | None


class CapabilityBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: ScopePath
    binding: str
    capability_id: str
    revision: str
    effective_grants: EffectiveGrants  # fully concrete — no None/"inherit" (I13)
    lifetime: LeaseLifetime  # build-loop worktree: "scope"


class CapabilityLease(BaseModel):
    """Runtime state of one physical capability acquisition.

    Lifecycle: RUNNING -> active; PARKED -> suspended (never finalized — parked
    resources are retained); resume -> active; terminal -> closed; LOST ->
    reconciled, then restored or reaped. ``state`` says whether live access
    exists; ``disposition`` says what happened to the resource when it ended
    (released = ended cleanly; discarded = provider-owned mutable state
    destroyed; retained = a durable reference deliberately survives).

    ``lease_id`` is computed from (run, scope, binding); ``acquisition_epoch``
    is the run ownership epoch that acquired it — a reclaimed run gets a fresh
    physical acquisition, so a stale worker can only damage its own obsolete
    one. The walker owns every transition on every exit path. The manifest
    records descriptors and grants — never live objects or credentials; the
    runtime receives real capabilities by injection (I8).
    """

    model_config = ConfigDict(frozen=True)

    lease_id: str  # digest over (run_id, scope, binding) — computed, never minted
    acquisition_epoch: int  # run ownership epoch that acquired the resource
    run_id: str
    binding_id: str
    scope: ScopePath
    lifetime: LeaseLifetime
    state: Literal["active", "suspended", "closed", "lost"]
    disposition: Literal["released", "discarded", "retained"] | None = None
    resource_ref: str | None = None


class ExecutionManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = MANIFEST_SCHEMA_VERSION
    source_graph: Graph
    source_graph_hash: Digest
    resolved_components: tuple[ComponentResolution, ...]
    resolved_connections: tuple[ResolvedPortBinding, ...]
    capability_bindings: tuple[CapabilityBinding, ...]
    input_hash: Digest  # the run's inputs
    world_hash: Digest  # the transitive component resolution
    manifest_hash: Digest  # identity of this sealed manifest (excludes itself)
