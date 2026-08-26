"""Ports and port addresses (I11).

Nominal typing is ``type_id`` plus schema revision; general JSON-Schema
subsumption is never attempted. Canonical IR addresses carry static scope.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import NodeId, ScopePath


class Port(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type_id: str
    schema_hash: str
    json_schema: dict[str, Any] | None = None
    cardinality: Literal["one", "optional", "many"] = "one"


class GraphInputAddress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["graph_input"] = "graph_input"
    scope: ScopePath
    port: str


class NodePortAddress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["node_port"] = "node_port"
    scope: ScopePath
    node: NodeId
    port: str


class GraphOutputAddress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["graph_output"] = "graph_output"
    scope: ScopePath
    port: str


PortAddress = GraphInputAddress | NodePortAddress | GraphOutputAddress
