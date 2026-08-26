"""The graph IR — exactly three constructs (I10, I11).

``Ref`` (a name in the registry — never code), ``Graph`` (composition,
nestable), and ``Loop`` (bounded feedback). Everything richer is an ordinary
registered component built from these, never a new IR construct.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from constructicon.core.address import NodeId
from constructicon.core.grants import GrantRequest
from constructicon.core.ports import Port

GRAPH_SCHEMA_VERSION = 1


class Ref(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    component: str
    version: str | None = None
    bind: dict[str, str] = Field(default_factory=dict)
    grants: GrantRequest | None = None


class Loop(BaseModel):
    """Generic feedback loop. The kernel does not know what a gate is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    body: Ref | Graph
    feedback: dict[str, str]
    continue_from: str
    max_iterations: PositiveInt


class GraphNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: NodeId
    body: Ref | Graph | Loop


class Connection(BaseModel):
    """The authored single connector; ``map`` breaks ambiguity only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    src: NodeId
    dst: NodeId
    map: dict[str, str] = Field(default_factory=dict)


class Graph(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    name: str
    nodes: tuple[GraphNode, ...]
    connections: tuple[Connection, ...] = ()
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
