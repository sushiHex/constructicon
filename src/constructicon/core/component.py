"""Components and versions (I10, I12).

A component is defined once, registered by name, referenced everywhere. Every
registered version is immutable and retained; ``content_hash`` is the version
identity, computed over executable semantics + contract (the learning profile
participates; lineage and labels are provenance and do not).

A skill IS a ComponentDef — there is no parallel skill registry. A CANDIDATE is
not a channel: it is any eligible exact version not yet promoted; pointers are
promoted channels only, recorded append-only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from constructicon.core.address import RunId
from constructicon.core.envelope import ArtifactRef
from constructicon.core.graph import Graph, Ref
from constructicon.core.identity import Digest
from constructicon.core.ports import Port


class PythonRef(BaseModel):
    """An atomic component's implementation, by reference — never inline code."""

    model_config = ConfigDict(frozen=True)

    package: str
    module: str
    qualname: str
    contract_hash: Digest
    source_digest: Digest | None = None


class LearningProfile(BaseModel):
    """Participates in content_hash: it governs permitted evolution (I12)."""

    model_config = ConfigDict(frozen=True)

    change_surfaces: frozenset[Literal["prompt", "policy", "graph", "code", "model_artifact"]]
    experience_policy: Ref
    evaluator: Ref
    promotion_policy: Ref
    evaluation_dataset: ArtifactRef | None = None
    impact_scope: Literal["component", "reverse_dependencies"] = "reverse_dependencies"
    requires_human_stable_approval: bool = True


class ComponentLineage(BaseModel):
    """Provenance — recorded beside the definition, NOT in content_hash."""

    model_config = ConfigDict(frozen=True)

    parent_version: Digest | None
    created_by_run: RunId
    experience_set: ArtifactRef | None = None
    proposer_manifest_hash: Digest | None = None


class ComponentMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    learning: LearningProfile | None = None
    lineage: ComponentLineage | None = None
    labels: frozenset[str] = frozenset()


ComponentRole = Literal["node", "component", "harness", "workflow"]


class ComponentDef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str  # namespaced: "constructicon.std/..." | "<project>/..."
    role: ComponentRole  # semantic role; atomic-vs-composite is the mechanical split
    body: PythonRef | Graph
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    metadata: ComponentMetadata = ComponentMetadata()

    def content_hash(self) -> Digest:
        from constructicon.core.identity import digest

        payload = {
            "role": self.role,
            "body": self.body.model_dump(mode="json"),
            "inputs": [p.model_dump(mode="json") for p in self.inputs],
            "outputs": [p.model_dump(mode="json") for p in self.outputs],
            "learning": (
                self.metadata.learning.model_dump(mode="json")
                if self.metadata.learning
                else None
            ),
        }
        return digest("component", 1, payload)


class PromotionRecord(BaseModel):
    """Append-only; the current pointer derives from the latest valid record.

    Rollback is another pointer move to a retained version — nothing is ever
    overwritten, and in-flight runs keep their pinned resolution. M9 extends
    ``channel`` with ``"canary"`` via the documented schema-evolution policy.
    """

    model_config = ConfigDict(frozen=True)

    component: str
    channel: Literal["stable"]
    from_version: Digest | None
    to_version: Digest
    attestation_id: str
    actor: str
    source_run: RunId | None
    created_at: AwareDatetime
