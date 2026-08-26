"""Agent-facing graph admission contracts (M5, I9).

Expected authoring rejection is data: raw Graph JSON and semantic admission use
one bounded, versioned, machine-repairable fault model. The strict Python
``validate`` convenience still raises ``AdmissionError`` carrying these same
faults.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from constructicon.core.address import ScopePath
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest, JsonValue
from constructicon.core.manifest import ExecutionManifest

ADMISSION_SCHEMA_VERSION = 1


class AdmissionCode(StrEnum):
    GRAPH_SCHEMA_INVALID_JSON = "graph.schema.invalid_json"
    GRAPH_SCHEMA_INVALID_VALUE = "graph.schema.invalid_value"
    GRAPH_PROPOSAL_LIMIT_EXCEEDED = "graph.proposal.limit_exceeded"
    GRAPH_NODE_DUPLICATE = "graph.node.duplicate"
    GRAPH_NODE_RESERVED_ID = "graph.node.reserved_id"
    GRAPH_REFERENCE_UNKNOWN = "graph.reference.unknown"
    GRAPH_REFERENCE_UNPROMOTED = "graph.reference.unpromoted"
    GRAPH_PORT_MISSING_SOURCE = "graph.port.missing_source"
    GRAPH_PORT_AMBIGUOUS = "graph.port.ambiguous"
    GRAPH_PORT_CONTRACT_MISMATCH = "graph.port.contract_mismatch"
    GRAPH_CAPABILITY_MISSING_BINDING = "graph.capability.missing_binding"
    GRAPH_CAPABILITY_UNDECLARED_BINDING = "graph.capability.undeclared_binding"
    GRAPH_CAPABILITY_UNKNOWN = "graph.capability.unknown"
    GRAPH_CAPABILITY_KIND_MISMATCH = "graph.capability.kind_mismatch"
    GRAPH_GRANT_WIDENING = "graph.grant.widening"
    GRAPH_LOOP_INVALID = "graph.loop.invalid"
    GRAPH_CYCLE = "graph.cycle"
    GRAPH_INPUT_INVALID = "graph.input.invalid"
    GRAPH_CONTRACT_INVALID = "graph.contract.invalid"
    LEGACY_ADMISSION = "system.admission.legacy"


class AdmissionFault(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: AdmissionCode
    message: str
    path: tuple[str | int, ...] = ()
    scope: ScopePath | None = None
    repair: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class AdmissionAccepted(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[ADMISSION_SCHEMA_VERSION] = ADMISSION_SCHEMA_VERSION
    status: Literal["accepted"] = "accepted"
    proposal_digest: Digest
    graph: Graph
    manifest: ExecutionManifest


class AdmissionRejected(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[ADMISSION_SCHEMA_VERSION] = ADMISSION_SCHEMA_VERSION
    status: Literal["rejected"] = "rejected"
    proposal_digest: Digest | None = None
    graph: Graph | None = None
    faults: tuple[AdmissionFault, ...]


AdmissionResult = Annotated[
    AdmissionAccepted | AdmissionRejected,
    Field(discriminator="status"),
]
