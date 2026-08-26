"""The graph IR — exactly three constructs (I10, I11).

``Ref`` (a name in the registry — never code), ``Graph`` (composition,
nestable), and ``Loop`` (bounded feedback). Everything richer — panels,
reviews, gates, repairs, learning loops — is an ordinary registered component
built from these, never a new IR construct.

Loop semantics, in one sentence: a loop executes its body at least once,
threads declared feedback outputs into the next iteration, reads
``continue_from`` after each completed iteration, exports the final completed
iteration's non-control outputs, and parks with ``policy_exhausted`` when
``max_iterations`` is reached while continuation remains true.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from constructicon.core.address import NodeId
from constructicon.core.grants import GrantRequest
from constructicon.core.ports import Port

GRAPH_SCHEMA_VERSION = 1


class Ref(BaseModel):
    model_config = ConfigDict(frozen=True)

    component: str  # namespaced: "constructicon.std/panel"
    # None = the STABLE channel at run start; "<sha256:...>" = exact version.
    # v1 ships only these two; "candidate"/"canary" aliases arrive with M9.
    # I12: registration never propagates — promotion does.
    version: str | None = None
    bind: dict[str, str] = Field(default_factory=dict)  # capability aliases
    # Authoring form; may inherit. Admission compiles it into EffectiveGrants
    # and verifies it only narrows, never widens.
    grants: GrantRequest | None = None


class Loop(BaseModel):
    """Generic feedback loop. The kernel does not know what a gate is."""

    model_config = ConfigDict(frozen=True)

    body: Ref | Graph
    feedback: dict[str, str]  # next-iteration input -> previous output
    continue_from: str  # body output carrying the typed continuation decision
    max_iterations: PositiveInt


class GraphNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: NodeId
    body: Ref | Graph | Loop


class Connection(BaseModel):
    """The authored single connector (sugar level).

    ``map`` exists only to break ambiguity the resolver refuses to guess
    about: destination port -> source node-local "node.port" selector. The
    canonical resolved form holds typed PortAddresses; string selectors are
    authoring sugar that admission compiles away.
    """

    model_config = ConfigDict(frozen=True)

    src: NodeId
    dst: NodeId
    map: dict[str, str] = Field(default_factory=dict)


class Graph(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = GRAPH_SCHEMA_VERSION
    name: str
    nodes: tuple[GraphNode, ...]
    connections: tuple[Connection, ...] = ()
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
