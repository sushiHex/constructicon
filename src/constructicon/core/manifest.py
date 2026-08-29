"""The sealed executable form (I13).

An ``ExecutionManifest`` is the compiled, immutable result of resolution and
admission — executable, lockfile, and deployment manifest in one object. After
admission there is no remaining magnetism, adjacency, scope search, inherited
grant, selector string, or loop structure to infer: only explicit resolved
edges and loop programs.

The walker accepts only an ExecutionManifest, never an authored Graph.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    PositiveInt,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import ChannelEndpoint
from constructicon.core.grants import EffectiveGrants
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest, digest
from constructicon.core.ports import NodePortAddress, Port, PortAddress

MANIFEST_SCHEMA_VERSION = 2

# The one continuation contract. A matching label with any other schema is not
# a continuation port; admission rejects it rather than trusting a name.
CONTINUE_TYPE = "constructicon/continue"
CONTINUE_SCHEMA = {"type": "boolean"}
CONTINUE_SCHEMA_HASH = str(digest("json-schema", 1, CONTINUE_SCHEMA))

# Every atomic instance carries its sealed grants under this reserved binding
# name; real capability aliases get their own rows.
SELF_BINDING = "__node__"
SELF_CAPABILITY = "__node__"

# M4 deliberately has one real consumer: invocation lifetime. Scope/run
# lifetimes return only with their first concrete use (I6).
LeaseLifetime = Literal["invocation"]


class ResolvedPortBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    destination: PortAddress
    # >1 sources only for cardinality="many"; a gathering binding records its
    # complete expected producer set (the silent-node-failure defense).
    sources: tuple[PortAddress, ...]


class ComponentResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ScopePath  # static scope — iterations do not exist yet
    component: str
    requested_version: str | None
    resolved_version: Digest
    contract_hash: Digest
    implementation_digest: Digest | None


class CapabilityBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ScopePath
    binding: str
    capability_id: str
    revision: str
    effective_grants: EffectiveGrants  # fully concrete — no None/"inherit" (I13)
    lifetime: LeaseLifetime = "invocation"
    # None = this binding addresses no channel endpoint.
    endpoint: ChannelEndpoint | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Keep the additive nullable field absent in legacy durable bytes.

        Capability bindings participate in manifest identity, so a binding with
        no endpoint must serialize exactly as it did before M7.
        """

        data = handler(self)
        if not isinstance(data, dict):
            raise TypeError("CapabilityBinding serializer expected an object")
        if self.endpoint is None:
            data.pop("endpoint", None)
        return data


class LoopExport(BaseModel):
    """One non-control value a completed loop publishes to its outer graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    port: Port
    destination: NodePortAddress
    sources: tuple[PortAddress, ...]


class LoopResolution(BaseModel):
    """The complete executable form of one bounded feedback loop.

    ``member_order`` contains atomic scopes only, already topologically ordered.
    The walker never inspects ``Loop.body`` or derives membership, bindings,
    exports, or continuation behavior at runtime.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ScopePath
    body_scope: ScopePath
    max_iterations: PositiveInt

    input_ports: tuple[Port, ...]
    initial_bindings: tuple[ResolvedPortBinding, ...]
    feedback_bindings: tuple[ResolvedPortBinding, ...]

    continue_source: PortAddress
    exports: tuple[LoopExport, ...]
    member_order: tuple[ScopePath, ...]


class CapabilityLease(BaseModel):
    """Runtime state of one physical, invocation-lifetime acquisition.

    ``lease_id`` is logical across ownership epochs; the frame-aware ``path``
    makes distinct loop iterations distinct logical leases. ``acquisition_epoch``
    fences physical paths after run reclamation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    lease_id: str
    acquisition_epoch: int
    run_id: RunId
    binding_id: str
    path: ExecutionPath
    lifetime: LeaseLifetime = "invocation"
    state: Literal["active", "closed", "lost"]
    disposition: Literal["released", "discarded"] | None = None
    resource_ref: str | None = None


class ExecutionManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = MANIFEST_SCHEMA_VERSION
    source_graph: Graph
    source_graph_hash: Digest
    resolved_components: tuple[ComponentResolution, ...]
    resolved_connections: tuple[ResolvedPortBinding, ...]
    capability_bindings: tuple[CapabilityBinding, ...]
    resolved_loops: tuple[LoopResolution, ...] = ()
    input_hash: Digest  # the run's inputs
    world_hash: Digest  # the transitive component resolution
    manifest_hash: Digest  # identity of this sealed manifest (excludes itself)


def manifest_identity_payload(manifest: ExecutionManifest) -> dict[str, Any]:
    """Return exactly the fields covered by ``manifest_hash`` for its schema.

    The authored graph is identified separately by ``source_graph_hash``; it is
    retained in the manifest for inspection but never duplicated in the hash
    payload. Schema v1 predates loops and therefore excludes ``resolved_loops``.
    """

    payload: dict[str, Any] = {
        "schema_version": manifest.schema_version,
        "source_graph_hash": str(manifest.source_graph_hash),
        "world_hash": str(manifest.world_hash),
        "input_hash": str(manifest.input_hash),
        "resolved_components": [
            item.model_dump(mode="json") for item in manifest.resolved_components
        ],
        "resolved_connections": [
            item.model_dump(mode="json") for item in manifest.resolved_connections
        ],
        "capability_bindings": [
            item.model_dump(mode="json") for item in manifest.capability_bindings
        ],
    }
    if manifest.schema_version >= 2:
        payload["resolved_loops"] = [
            item.model_dump(mode="json") for item in manifest.resolved_loops
        ]
    return payload


def manifest_hash_for(manifest: ExecutionManifest) -> Digest:
    """Recompute a manifest identity under its declared public schema."""

    return digest(
        "manifest",
        manifest.schema_version,
        manifest_identity_payload(manifest),
    )


def parse_manifest_json(raw: str) -> ExecutionManifest:
    """Parse one persisted manifest with version-aware, fail-closed semantics.

    V1 remains readable and receives the additive empty ``resolved_loops``
    default. Unknown versions and unknown top-level fields are refused. The
    stored identity is recomputed under the declared version.
    """

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("manifest JSON must be an object")
    version = data.get("schema_version", 1)
    if version not in (1, MANIFEST_SCHEMA_VERSION):
        raise ValueError(
            f"manifest schema version {version!r} is unsupported; "
            f"supported versions are 1 and {MANIFEST_SCHEMA_VERSION}"
        )
    if version == 1 and data.get("resolved_loops") not in (None, [], ()):
        raise ValueError(
            "manifest schema version 1 cannot carry loop resolutions; "
            "upgrade the manifest identity to schema version 2"
        )
    manifest = ExecutionManifest.model_validate(data)
    observed = manifest_hash_for(manifest)
    if observed != manifest.manifest_hash:
        raise ValueError(
            f"manifest identity mismatch: recorded {manifest.manifest_hash}, "
            f"recomputed {observed}"
        )
    return manifest
