"""Ports and port addresses (I11).

Nominal typing: a port's identity is its ``type_id`` plus schema revision —
never general JSON-Schema subsumption. ``cardinality`` replaces schema-shape
inference: a ``many`` input gathers every upstream output of the exact type.

Port addresses carry their static scope so repeated local ``NodeId``s inside
nested component instances stay distinct. ``"node.port"`` strings are SDK/CLI
sugar only; canonical IR holds typed addresses.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import NodeId, ScopePath


class Port(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    type_id: str  # nominal identity, namespaced
    schema_hash: str
    json_schema: dict[str, Any] | None = None
    cardinality: Literal["one", "optional", "many"] = "one"


class GraphInputAddress(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["graph_input"] = "graph_input"
    scope: ScopePath
    port: str


class NodePortAddress(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["node_port"] = "node_port"
    scope: ScopePath
    node: NodeId
    port: str


class GraphOutputAddress(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["graph_output"] = "graph_output"
    scope: ScopePath
    port: str


PortAddress = GraphInputAddress | NodePortAddress | GraphOutputAddress
