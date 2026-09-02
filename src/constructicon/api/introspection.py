"""Derive the complete agent authoring contract from existing system truth."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

import pydantic
from pydantic import TypeAdapter

from constructicon.core.admission import AdmissionResult
from constructicon.core.component import ComponentDef
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import EffectiveGrants, GrantRequest, Posture
from constructicon.core.graph import Graph
from constructicon.core.human import CONTRACT_SCHEMAS as _HUMAN_CONTRACT_SCHEMAS
from constructicon.core.identity import Digest, digest
from constructicon.core.introspection import (
    AdmissionLimits,
    AuthoringVocabulary,
    BindingVocabulary,
    CapabilityDescription,
    ComponentDescription,
    ContractCompleteness,
    GrantVocabulary,
    LoopVocabulary,
    PortDescription,
    ReferenceVocabulary,
    SchemaDocument,
    SystemDescription,
)
from constructicon.core.manifest import CONTINUE_SCHEMA_HASH, CONTINUE_TYPE
from constructicon.core.panel import CONTRACT_SCHEMAS as _PANEL_CONTRACT_SCHEMAS
from constructicon.core.registry import RegistrySnapshot, registry_snapshot_digest
from constructicon.runtime.registry import CapabilityDescriptor, ComponentRegistry


def build_system_description(
    *,
    registry: ComponentRegistry,
    snapshot: RegistrySnapshot,
    catalog: Mapping[str, CapabilityDescriptor],
    available_capabilities: frozenset[str],
    root_grants: EffectiveGrants,
    limits: AdmissionLimits,
    component_names: Sequence[str] | None,
    limit: int,
) -> SystemDescription:
    if limit <= 0:
        raise ValueError("describe limit must be positive")
    if limit > limits.max_description_components:
        raise ValueError(
            f"describe limit {limit} exceeds the published maximum "
            f"{limits.max_description_components}"
        )
    stable_names = sorted(name for name in snapshot.names() if name in snapshot.stable)
    if component_names is None:
        selected_names = stable_names[:limit]
        truncated = len(stable_names) > limit
    else:
        requested = tuple(dict.fromkeys(component_names))
        unknown = sorted(name for name in requested if name not in snapshot.versions)
        if unknown:
            raise ContractViolation(
                f"describe requested unknown components {unknown}; available: {snapshot.names()}"
            )
        selected_names = list(requested[:limit])
        truncated = len(requested) > limit

    component_descriptions: list[ComponentDescription] = []
    schema_by_hash: dict[str, SchemaDocument] = {}
    for key in NAMED_CONTRACT_SCHEMAS:
        _publish(schema_by_hash, _named_document(key))
    for name in selected_names:
        stable_hash = snapshot.stable_version(name)
        if stable_hash is None:
            continue
        stored = snapshot.get(name, stable_hash)
        if stored is None:
            raise ContractViolation(
                f"registry stable pointer {name!r}@{stable_hash} names no stored version"
            )
        component_descriptions.append(
            _component_description(
                registry,
                snapshot,
                stored.definition,
                stable_hash,
                schema_by_hash,
            )
        )

    capabilities = tuple(
        CapabilityDescription(
            capability_id=capability_id,
            kind=descriptor.kind,
            revision=descriptor.revision,
            leased=descriptor.leased,
            requires_posture=descriptor.requires_posture,
            executor_profile=descriptor.executor_profile,
            channel_profile=descriptor.channel_profile,
            channel_endpoint=descriptor.endpoint,
            available=capability_id in available_capabilities,
        )
        for capability_id, descriptor in sorted(catalog.items())
    )

    graph_schema = _schema_document(
        "constructicon.graph",
        1,
        Graph.model_json_schema(),
        default_title="Graph",
    )
    admission_schema = _schema_document(
        "constructicon.admission-result",
        1,
        TypeAdapter(AdmissionResult).json_schema(),
        default_title="Admission Result",
    )
    grant_schema = _schema_document(
        "constructicon.grant-request",
        1,
        GrantRequest.model_json_schema(),
        default_title="Grant Request",
    )
    grants = GrantVocabulary(
        postures=tuple(posture.value for posture in Posture),
        network_values=("inherit", "none", "allow"),
        request_schema=grant_schema,
        root_grants=root_grants,
    )
    authoring = AuthoringVocabulary(
        references=ReferenceVocabulary(),
        bindings=BindingVocabulary(),
        loops=LoopVocabulary(
            continue_type_id=CONTINUE_TYPE,
            continue_schema_hash=CONTINUE_SCHEMA_HASH,
        ),
        limits=limits,
    )
    registry_digest = registry_snapshot_digest(snapshot)
    catalog_digest = digest(
        "capability-catalog",
        1,
        [
            {
                "capability_id": item.capability_id,
                "kind": item.kind,
                "revision": item.revision,
                "leased": item.leased,
                "requires_posture": (
                    item.requires_posture.value if item.requires_posture else None
                ),
                "executor_profile": (
                    item.executor_profile.model_dump(mode="json") if item.executor_profile else None
                ),
                "channel_profile": (
                    item.channel_profile.model_dump(mode="json") if item.channel_profile else None
                ),
                "channel_endpoint": (
                    item.channel_endpoint.model_dump(mode="json")
                    if item.channel_endpoint
                    else None
                ),
                "available": item.available,
            }
            for item in capabilities
        ],
    )
    schemas = tuple(schema_by_hash[key] for key in sorted(schema_by_hash))
    body: dict[str, Any] = {
        "schema_version": 1,
        "graph_schema": graph_schema.model_dump(mode="json"),
        "admission_schema": admission_schema.model_dump(mode="json"),
        "components": [item.model_dump(mode="json") for item in component_descriptions],
        "capabilities": [item.model_dump(mode="json") for item in capabilities],
        "schemas": [item.model_dump(mode="json") for item in schemas],
        "grants": grants.model_dump(mode="json"),
        "authoring": authoring.model_dump(mode="json"),
        "total_components": len(stable_names),
        "truncated": truncated,
        "registry_snapshot_digest": str(registry_digest),
        "catalog_digest": str(catalog_digest),
    }
    return SystemDescription(
        **body,
        description_digest=digest("system-description", 1, body),
    )


def build_component_description(
    *,
    registry: ComponentRegistry,
    snapshot: RegistrySnapshot,
    name: str,
    version: Digest | None,
) -> ComponentDescription:
    selected = version or snapshot.stable_version(name)
    if selected is None:
        raise ContractViolation(
            f"component {name!r} has no stable version; supply an exact version"
        )
    stored = snapshot.get(name, selected)
    if stored is None:
        raise ContractViolation(f"component {name!r} has no version {selected}")
    schemas: dict[str, SchemaDocument] = {}
    return _component_description(
        registry,
        snapshot,
        stored.definition,
        selected,
        schemas,
    )


def _component_description(
    registry: ComponentRegistry,
    snapshot: RegistrySnapshot,
    definition: ComponentDef,
    version: Digest,
    schema_by_hash: dict[str, SchemaDocument],
) -> ComponentDescription:
    for port in (*definition.inputs, *definition.outputs):
        document = _port_schema(port)
        if document is not None:
            _publish(schema_by_hash, document)
    stored = snapshot.get(definition.name, version)
    if stored is None:
        raise ContractViolation(
            f"component {definition.name!r}@{version} disappeared from the supplied snapshot"
        )
    bound = registry.bind(stored)
    requirements = definition.capability_requirements
    return ComponentDescription(
        name=definition.name,
        version=version,
        stable=snapshot.stable_version(definition.name) == version,
        role=definition.role,
        body_kind="composite" if isinstance(definition.body, Graph) else "atomic",
        inputs=tuple(_port_description(port) for port in definition.inputs),
        outputs=tuple(_port_description(port) for port in definition.outputs),
        capability_requirements=tuple(requirements or ()),
        completeness=ContractCompleteness(
            port_schemas=all(
                _port_schema(port) is not None for port in (*definition.inputs, *definition.outputs)
            ),
            capability_bindings=requirements is not None,
        ),
        loadability=bound.loadability,
        labels=tuple(sorted(definition.metadata.labels)),
        candidate_count=len(
            [
                item
                for item in snapshot.order.get(definition.name, ())
                if item != snapshot.stable.get(definition.name)
            ]
        ),
    )


def _port_description(port: Any) -> PortDescription:
    return PortDescription(
        name=port.name,
        type_id=port.type_id,
        schema_hash=port.schema_hash,
        cardinality=port.cardinality,
        schema_available=_port_schema(port) is not None,
    )


def _port_schema(port: Any) -> SchemaDocument | None:
    """The shape a port's payload has: embedded on the port, or a named contract's.

    Built fresh on every call: a description owns its documents, so a caller
    that mutates one changes nothing another description will publish.
    """

    if port.json_schema is not None:
        return _schema_document(
            f"port:{port.schema_hash}",
            1,
            port.json_schema,
            declared_hash=port.schema_hash,
        )
    key = (port.type_id, port.schema_hash)
    return _named_document(key) if key in NAMED_CONTRACT_SCHEMAS else None


def _named_document(key: tuple[str, str]) -> SchemaDocument:
    type_id, schema_hash = key
    return _schema_document(
        f"contract:{type_id}",
        1,
        NAMED_CONTRACT_SCHEMAS[key].model_json_schema(),
        declared_hash=schema_hash,
    )


def _publish(schema_by_hash: dict[str, SchemaDocument], document: SchemaDocument) -> None:
    """One document per revision: `schema_hash` is the public key a port declares."""

    schema_by_hash.setdefault(document.schema_hash, document)


def _schema_document(
    name: str,
    version: int,
    schema: dict[str, Any],
    *,
    default_title: str | None = None,
    declared_hash: str | None = None,
) -> SchemaDocument:
    normalized = dict(schema)
    if default_title is not None:
        normalized.setdefault("title", default_title)
    schema_hash = declared_hash or str(digest("json-schema", 1, normalized))
    return SchemaDocument(
        name=name,
        version=version,
        schema_hash=schema_hash,
        schema_=normalized,
        generator=f"pydantic-{pydantic.__version__}",
    )


_NAMED_CONTRACT_ENTRIES = tuple(
    ((contract.type_id, contract.schema_hash), model)
    for catalog in (_HUMAN_CONTRACT_SCHEMAS, _PANEL_CONTRACT_SCHEMAS)
    for contract, model in catalog.items()
)
if len({schema_hash for (_, schema_hash), _ in _NAMED_CONTRACT_ENTRIES}) != len(
    _NAMED_CONTRACT_ENTRIES
):
    raise RuntimeError("two named contracts share one revision string; the revision is the key")
NAMED_CONTRACT_SCHEMAS: Mapping[tuple[str, str], type[pydantic.BaseModel]] = MappingProxyType(
    dict(_NAMED_CONTRACT_ENTRIES)
)
"""The standard vocabulary: every named contract revision and the model whose shape it names.

A named revision is not the digest of a schema, so the registry refuses to
embed one on a port; the shape is published from here instead, keyed by the
nominal pair a port declares. Every description carries the whole vocabulary,
so a payload no port names — a panel ballot inside an advice reply — is
discoverable too (I9). Documents are generated per description, never shared.
"""
