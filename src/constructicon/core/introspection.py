"""Agent-first authoring and introspection contracts (M5, I9).

Descriptions are derived projections over one registry snapshot and the
assembled capability catalog. They never serialize live capability objects,
credentials, implementation closures, or a parallel metadata store.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt, PositiveInt

from constructicon.core.channel import ChannelProfile
from constructicon.core.component import CapabilityRequirement, ComponentRole
from constructicon.core.executor import ExecutorProfile
from constructicon.core.grants import EffectiveGrants, Posture
from constructicon.core.identity import Digest
from constructicon.core.registry import Loadability

DESCRIPTION_SCHEMA_VERSION = 1


class SchemaDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: PositiveInt
    schema_hash: str
    schema_: dict[str, Any]
    generator: str = "pydantic-v2"


class PortDescription(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type_id: str
    schema_hash: str
    cardinality: Literal["one", "optional", "many"]
    schema_available: bool


class ContractCompleteness(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    port_schemas: bool
    capability_bindings: bool


class ComponentDescription(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: Digest
    stable: bool
    role: ComponentRole
    body_kind: Literal["atomic", "composite"]
    inputs: tuple[PortDescription, ...]
    outputs: tuple[PortDescription, ...]
    capability_requirements: tuple[CapabilityRequirement, ...]
    completeness: ContractCompleteness
    loadability: Loadability
    labels: tuple[str, ...]
    candidate_count: NonNegativeInt = 0


class CapabilityDescription(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str
    kind: str
    revision: str
    leased: bool
    requires_posture: Posture | None
    executor_profile: ExecutorProfile | None
    channel_profile: ChannelProfile | None
    available: bool


class GrantVocabulary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    postures: tuple[str, ...]
    network_values: tuple[str, ...]
    request_schema: SchemaDocument
    root_grants: EffectiveGrants


class AdmissionLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_proposal_bytes: PositiveInt = 1_000_000
    max_nodes: PositiveInt = 1_000
    max_nested_graph_depth: PositiveInt = 32
    max_faults: PositiveInt = 100
    max_fault_detail_items: PositiveInt = 25
    max_description_components: PositiveInt = 100


class ReferenceVocabulary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bare_version_semantics: Literal["stable"] = "stable"
    exact_version_format: str = "sha256:<64 lowercase hex>"


class BindingVocabulary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    nominal_identity_fields: tuple[str, ...] = ("type_id", "schema_hash")
    resolution_order: tuple[str, ...] = (
        "unique exact-name plus nominal-contract match",
        "unique nominal-contract match",
        "all nominal-contract matches for cardinality many",
    )
    selector_forms: tuple[str, ...] = ("node.port", "$input.port")
    map_destination: Literal["node_input"] = "node_input"
    ambiguity_policy: Literal["reject"] = "reject"
    reserved_node_prefix: str = "$"


class LoopVocabulary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    continue_type_id: str
    continue_schema_hash: str
    continue_cardinality: Literal["one"] = "one"
    nested_loops_supported: bool = False


class AuthoringVocabulary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    references: ReferenceVocabulary
    bindings: BindingVocabulary
    loops: LoopVocabulary
    limits: AdmissionLimits


class SystemDescription(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    graph_schema: SchemaDocument
    admission_schema: SchemaDocument
    components: tuple[ComponentDescription, ...]
    capabilities: tuple[CapabilityDescription, ...]
    schemas: tuple[SchemaDocument, ...]
    grants: GrantVocabulary
    authoring: AuthoringVocabulary
    total_components: NonNegativeInt
    truncated: bool
    registry_snapshot_digest: Digest
    catalog_digest: Digest
    description_digest: Digest
