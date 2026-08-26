"""Components and versions (I10, I12).

A component is defined once, registered by name, referenced everywhere. Every
registered version is immutable and retained; ``content_hash`` is the version
identity, computed over executable semantics + contract (the learning profile
and complete capability contract participate; lineage and labels are
provenance and do not).

A skill IS a ComponentDef — there is no parallel skill registry. A CANDIDATE is
not a channel: it is any eligible exact version not yet promoted; pointers are
promoted channels only, recorded append-only.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from constructicon.core.address import RunId
from constructicon.core.envelope import ArtifactRef
from constructicon.core.graph import Graph, Ref
from constructicon.core.identity import Digest
from constructicon.core.ports import Port


class PythonRef(BaseModel):
    """An atomic component's implementation, by reference — never inline code."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    package: str
    module: str
    qualname: str
    contract_hash: Digest
    source_digest: Digest | None = None


class CapabilityRequirement(BaseModel):
    """One required capability alias in an atomic component contract.

    The declaration names only a stable alias and descriptor kind. It never
    contains a live object, credentials, or an environment-specific capability
    id. ``ComponentDef.capability_requirements is None`` means the historical
    definition predates this contract and is capability-opaque; ``()`` means a
    complete declaration with no capability requirements.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    alias: str
    kind: str


class LearningProfile(BaseModel):
    """Participates in content_hash: it governs permitted evolution (I12)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    change_surfaces: frozenset[Literal["prompt", "policy", "graph", "code", "model_artifact"]]
    experience_policy: Ref
    evaluator: Ref
    promotion_policy: Ref
    evaluation_dataset: ArtifactRef | None = None
    impact_scope: Literal["component", "reverse_dependencies"] = "reverse_dependencies"
    requires_human_stable_approval: bool = True


class ComponentLineage(BaseModel):
    """Provenance — recorded beside the definition, NOT in content_hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_version: Digest | None
    created_by_run: RunId
    experience_set: ArtifactRef | None = None
    proposer_manifest_hash: Digest | None = None


class ComponentMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    learning: LearningProfile | None = None
    lineage: ComponentLineage | None = None
    labels: frozenset[str] = frozenset()


ComponentRole = Literal["node", "component", "harness", "workflow"]


class ComponentDef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    role: ComponentRole
    body: PythonRef | Graph
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    metadata: ComponentMetadata = ComponentMetadata()
    # None = legacy/opaque; () = complete declaration of no requirements.
    capability_requirements: tuple[CapabilityRequirement, ...] | None = None

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        """Keep the additive nullable field absent in legacy durable bytes."""

        data = handler(self)
        if not isinstance(data, dict):
            raise TypeError("ComponentDef serializer expected an object")
        if self.capability_requirements is None:
            data.pop("capability_requirements", None)
        return data

    def content_hash(self) -> Digest:
        from constructicon.core.identity import digest

        payload: dict[str, Any] = {
            "role": self.role,
            "body": self.body.model_dump(mode="json"),
            "inputs": [port.model_dump(mode="json") for port in self.inputs],
            "outputs": [port.model_dump(mode="json") for port in self.outputs],
            "learning": (
                self.metadata.learning.model_dump(mode="json")
                if self.metadata.learning
                else None
            ),
        }
        if self.capability_requirements is None:
            # Preserve the exact identity law of M1-M4 definitions.
            return digest("component", 1, payload)
        payload["capability_requirements"] = [
            requirement.model_dump(mode="json")
            for requirement in sorted(
                self.capability_requirements,
                key=lambda item: (item.alias, item.kind),
            )
        ]
        return digest("component", 2, payload)


class PromotionRecord(BaseModel):
    """Append-only; the current pointer derives from the latest valid record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component: str
    channel: Literal["stable"]
    from_version: Digest | None
    to_version: Digest
    attestation_id: str
    actor: str
    source_run: RunId | None
    created_at: AwareDatetime
