"""Ports and port addresses (I11).

Nominal typing is ``type_id`` plus schema revision; general JSON-Schema
subsumption is never attempted. Canonical IR addresses carry static scope.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import NodeId, ScopePath
from constructicon.core.identity import canonical_json


class Port(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type_id: str
    schema_hash: str
    json_schema: dict[str, Any] | None = None
    cardinality: Literal["one", "optional", "many"] = "one"


def boundary_bytes(ports: Sequence[Port]) -> str:
    """One boundary as canonical bytes, in declared order.

    A bytes law, not model equality: ``1 == True`` and ``1 == 1.0`` are Python
    facts, and an embedded schema that differs only there is a different
    boundary.
    """

    return canonical_json([port.model_dump(mode="json") for port in ports])


def same_boundary(left: Sequence[Port], right: Sequence[Port]) -> bool:
    return boundary_bytes(left) == boundary_bytes(right)


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
