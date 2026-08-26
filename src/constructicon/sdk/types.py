"""Concrete SDK authoring carriers.

These objects are process-local conveniences only. They contain canonical core
objects and reduce immediately to ``Ref``/``ComponentDef``; no SDK AST is ever
serialized, admitted, journaled, or interpreted by the walker.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

from constructicon.core.component import ComponentDef
from constructicon.core.grants import GrantRequest
from constructicon.core.graph import Ref
from constructicon.runtime.context import NodeImpl


@dataclass(frozen=True)
class PortType:
    """``Annotated`` metadata selecting one public nominal port type id."""

    type_id: str


def port_type(type_id: str) -> PortType:
    if not type_id or "/" not in type_id:
        raise ValueError(
            "port type ids must be non-empty and namespaced, for example "
            "'example/Issue'"
        )
    return PortType(type_id=type_id)


@dataclass(frozen=True)
class DefinitionBundle:
    """A canonical definition plus its optional process-local implementation."""

    definition: ComponentDef
    implementation: NodeImpl | None = None

    @property
    def name(self) -> str:
        return self.definition.name

    def ref(
        self,
        *,
        version: str | None = None,
        bind: Mapping[str, str] | None = None,
        grants: GrantRequest | None = None,
    ) -> Ref:
        return Ref(
            component=self.definition.name,
            version=version,
            bind=dict(bind or {}),
            grants=grants,
        )


AuthoringStep: TypeAlias = DefinitionBundle | Ref | str
