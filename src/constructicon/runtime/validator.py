"""Admission — the one boundary every authoring surface passes through (I8, I11, I13).

The validator compiles an authored ``Graph`` into a sealed ``ExecutionManifest``:
references resolve to exact versions, magnetic port intent compiles into
explicit resolved bindings, grant requests compile into fully concrete
authority, and composite structure flattens into atomic execution units. After
admission there is no remaining magnetism, adjacency, scope search, inherited
grant, or selector string — the walker decides nothing.

Faults are itemized and name the repair (I9): the consumer of a rejection is an
agent that will fix and resubmit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from constructicon.core.address import ScopePath
from constructicon.core.component import ComponentDef
from constructicon.core.errors import AdmissionError
from constructicon.core.executor import ExecutorProfile
from constructicon.core.grants import (
    EffectiveGrants,
    GrantRequest,
    ModelSelection,
    Posture,
)
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.identity import digest
from constructicon.core.manifest import (
    CapabilityBinding,
    ComponentResolution,
    ExecutionManifest,
    ResolvedPortBinding,
)
from constructicon.core.ports import (
    GraphInputAddress,
    GraphOutputAddress,
    NodePortAddress,
    Port,
    PortAddress,
)
from constructicon.runtime.registry import ComponentRegistry, RegistryError

SELF_BINDING = "__node__"
SELF_CAPABILITY = "__node__"


@dataclass(frozen=True)
class CapabilityDescriptor:
    """What the catalog exposes about an injectable capability — never the object."""

    capability_id: str
    kind: str
    revision: str
    executor_profile: ExecutorProfile | None = None


@dataclass(frozen=True)
class _Source:
    address: PortAddress
    port: Port


@dataclass
class _Compilation:
    registry: ComponentRegistry
    catalog: dict[str, CapabilityDescriptor]
    faults: list[str] = field(default_factory=list)
    resolutions: list[ComponentResolution] = field(default_factory=list)
    bindings: list[ResolvedPortBinding] = field(default_factory=list)
    capability_bindings: list[CapabilityBinding] = field(default_factory=list)


def admit(
    graph: Graph,
    *,
    registry: ComponentRegistry,
    catalog: dict[str, CapabilityDescriptor],
    root_grants: EffectiveGrants,
    inputs: dict[str, Any],
) -> ExecutionManifest:
    comp = _Compilation(registry=registry, catalog=catalog)
    root_scope = ScopePath(segments=(graph.name,))

    input_names = {port.name for port in graph.inputs}
    missing = sorted(input_names - set(inputs))
    extra = sorted(set(inputs) - input_names)
    if missing:
        comp.faults.append(
            f"run inputs missing for graph input ports {missing}; declared inputs: "
            f"{sorted(input_names)}"
        )
    if extra:
        comp.faults.append(
            f"run inputs {extra} match no declared graph input port; declared: "
            f"{sorted(input_names)}"
        )

    input_sources = {
        port.name: [
            _Source(
                address=GraphInputAddress(scope=root_scope, port=port.name), port=port
            )
        ]
        for port in graph.inputs
    }

    output_sources = _compile_graph(
        comp,
        graph,
        scope=root_scope,
        input_sources=input_sources,
        grants=root_grants,
    )

    for port in graph.outputs:
        sources = output_sources.get(port.name)
        if not sources:
            continue  # fault already recorded inside _compile_graph
        comp.bindings.append(
            ResolvedPortBinding(
                destination=GraphOutputAddress(scope=root_scope, port=port.name),
                sources=tuple(source.address for source in sources),
            )
        )

    if comp.faults:
        raise AdmissionError(comp.faults)

    graph_hash = digest("graph", 1, graph.model_dump(mode="json"))
    world_hash = digest(
        "world",
        1,
        {
            "components": [
                {
                    "scope": list(res.scope.segments),
                    "component": res.component,
                    "version": str(res.resolved_version),
                }
                for res in comp.resolutions
            ],
            "capabilities": [
                {
                    "scope": list(binding.scope.segments),
                    "binding": binding.binding,
                    "capability": binding.capability_id,
                    "revision": binding.revision,
                }
                for binding in comp.capability_bindings
            ],
        },
    )
    input_hash = digest("inputs", 1, inputs)
    manifest_body = {
        "schema_version": 1,
        "source_graph_hash": str(graph_hash),
        "world_hash": str(world_hash),
        "input_hash": str(input_hash),
        "resolved_components": [r.model_dump(mode="json") for r in comp.resolutions],
        "resolved_connections": [b.model_dump(mode="json") for b in comp.bindings],
        "capability_bindings": [b.model_dump(mode="json") for b in comp.capability_bindings],
    }
    manifest_hash = digest("manifest", 1, manifest_body)
    return ExecutionManifest(
        source_graph=graph,
        source_graph_hash=graph_hash,
        resolved_components=tuple(comp.resolutions),
        resolved_connections=tuple(comp.bindings),
        capability_bindings=tuple(comp.capability_bindings),
        input_hash=input_hash,
        world_hash=world_hash,
        manifest_hash=manifest_hash,
    )


def _compile_graph(
    comp: _Compilation,
    graph: Graph,
    *,
    scope: ScopePath,
    input_sources: dict[str, list[_Source]],
    grants: EffectiveGrants,
) -> dict[str, list[_Source]]:
    """Compile one graph level; return final sources for its output ports."""
    upstream = _upstream_closure(graph)
    node_outputs: dict[str, dict[str, list[_Source]]] = {}
    explicit = _explicit_maps(graph)

    for node in _ordered_nodes(graph, upstream):
        pool: list[_Source] = []
        for name in upstream.get(node.id, ()):  # deterministic order
            for sources in node_outputs.get(name, {}).values():
                pool.extend(sources)
        for sources in input_sources.values():
            pool.extend(sources)

        node_outputs[node.id] = _compile_node(
            comp,
            node,
            level_scope=scope,
            pool=pool,
            explicit=explicit.get(node.id, {}),
            node_lookup=node_outputs,
            input_sources=input_sources,
            grants=grants,
        )

    outputs: dict[str, list[_Source]] = {}
    level_pool = [
        source
        for per_node in node_outputs.values()
        for sources in per_node.values()
        for source in sources
    ] + [source for sources in input_sources.values() for source in sources]
    for port in graph.outputs:
        bound = _bind_port(comp, port, level_pool, where=f"{scope.render()} output")
        if bound is not None:
            # the boundary port defines the name/type the outside world sees:
            # re-tag so renames across a composite boundary never leak inner names
            outputs[port.name] = [
                _Source(address=source.address, port=port) for source in bound
            ]
    return outputs


def _compile_node(
    comp: _Compilation,
    node: GraphNode,
    *,
    level_scope: ScopePath,
    pool: list[_Source],
    explicit: dict[str, str],
    node_lookup: dict[str, dict[str, list[_Source]]],
    input_sources: dict[str, list[_Source]],
    grants: EffectiveGrants,
) -> dict[str, list[_Source]]:
    body = node.body
    instance_scope = level_scope.child(node.id)

    if isinstance(body, Loop):
        comp.faults.append(
            f"{instance_scope.render()}: Loop execution arrives with M4; "
            "express this milestone's graphs without loops"
        )
        return {}

    if isinstance(body, Ref):
        try:
            record = comp.registry.resolve(body)
        except RegistryError as exc:
            comp.faults.append(f"{instance_scope.render()}: {exc}")
            return {}
        definition = record.definition
        node_grants = _compile_grants(comp, grants, body.grants, where=instance_scope)
        comp.resolutions.append(
            ComponentResolution(
                scope=instance_scope,
                component=definition.name,
                requested_version=body.version,
                resolved_version=record.content_hash,
                contract_hash=digest(
                    "component-contract",
                    1,
                    {
                        "inputs": [p.model_dump(mode="json") for p in definition.inputs],
                        "outputs": [p.model_dump(mode="json") for p in definition.outputs],
                    },
                ),
                implementation_digest=None,
            )
        )
        bound_inputs = _bind_node_inputs(
            comp, node, definition.inputs, level_scope, pool, explicit, node_lookup, input_sources
        )
        if isinstance(definition.body, Graph):
            declared = {port.name: port for port in definition.inputs}
            retagged = {
                name: [_Source(address=s.address, port=declared[name]) for s in sources]
                for name, sources in bound_inputs.items()
            }
            return _compile_graph(
                comp,
                definition.body,
                scope=instance_scope,
                input_sources=retagged,
                grants=node_grants,
            )
        return _register_atomic(
            comp, node, definition, instance_scope, level_scope, bound_inputs, body, node_grants
        )

    # inline nested Graph: legal only as a compiler intermediate / run root (I10)
    bound_inputs = _bind_node_inputs(
        comp, node, body.inputs, level_scope, pool, explicit, node_lookup, input_sources
    )
    return _compile_graph(
        comp, body, scope=instance_scope, input_sources=bound_inputs, grants=grants
    )


def _register_atomic(
    comp: _Compilation,
    node: GraphNode,
    definition: ComponentDef,
    instance_scope: ScopePath,
    level_scope: ScopePath,
    bound_inputs: dict[str, list[_Source]],
    ref: Ref,
    node_grants: EffectiveGrants,
) -> dict[str, list[_Source]]:
    for port_name, sources in bound_inputs.items():
        comp.bindings.append(
            ResolvedPortBinding(
                destination=NodePortAddress(
                    scope=level_scope, node=node.id, port=port_name
                ),
                sources=tuple(source.address for source in sources),
            )
        )
    # every atomic instance carries its sealed grants explicitly (I13)
    comp.capability_bindings.append(
        CapabilityBinding(
            scope=instance_scope,
            binding=SELF_BINDING,
            capability_id=SELF_CAPABILITY,
            revision="0",
            effective_grants=node_grants,
            lifetime="invocation",
        )
    )
    for alias, capability_id in sorted(ref.bind.items()):
        descriptor = comp.catalog.get(capability_id)
        if descriptor is None:
            comp.faults.append(
                f"{instance_scope.render()}: binding {alias!r} names unknown "
                f"capability {capability_id!r}; catalog: {sorted(comp.catalog)}"
            )
            continue
        profile = descriptor.executor_profile
        if profile is not None:
            if node_grants.posture not in profile.postures:
                comp.faults.append(
                    f"{instance_scope.render()}: executor {capability_id!r} does not "
                    f"offer posture {node_grants.posture.value!r}"
                )
            elif not profile.isolation.satisfies(node_grants.posture):
                comp.faults.append(
                    f"{instance_scope.render()}: executor {capability_id!r} cannot "
                    f"mechanically enforce posture {node_grants.posture.value!r} — "
                    "admission rejects, it never degrades (I1)"
                )
        comp.capability_bindings.append(
            CapabilityBinding(
                scope=instance_scope,
                binding=alias,
                capability_id=capability_id,
                revision=descriptor.revision,
                effective_grants=node_grants,
                lifetime="invocation",
            )
        )
    return {
        port.name: [
            _Source(
                address=NodePortAddress(scope=level_scope, node=node.id, port=port.name),
                port=port,
            )
        ]
        for port in definition.outputs
    }


def _bind_node_inputs(
    comp: _Compilation,
    node: GraphNode,
    inputs: tuple[Port, ...],
    level_scope: ScopePath,
    pool: list[_Source],
    explicit: dict[str, str],
    node_lookup: dict[str, dict[str, list[_Source]]],
    input_sources: dict[str, list[_Source]],
) -> dict[str, list[_Source]]:
    bound: dict[str, list[_Source]] = {}
    where = f"{level_scope.child(node.id).render()} input"
    for port in inputs:
        if port.name in explicit:
            sources = _resolve_selector(
                comp, explicit[port.name], node_lookup, input_sources, where=where
            )
            if sources is not None:
                bound[port.name] = sources
            continue
        sources = _bind_port(comp, port, pool, where=where)
        if sources is not None:
            bound[port.name] = sources
    return bound


def _bind_port(
    comp: _Compilation, port: Port, pool: list[_Source], *, where: str
) -> list[_Source] | None:
    """The magnetic rules (I11), compiled — deterministic, never a guess."""
    typed = [source for source in pool if source.port.type_id == port.type_id]
    if port.cardinality == "many":
        if not typed:
            comp.faults.append(
                f"{where} port {port.name!r} gathers type {port.type_id!r} but no "
                f"upstream output offers it; available types: "
                f"{sorted({s.port.type_id for s in pool})}"
            )
            return None
        return typed

    named = [source for source in typed if source.port.name == port.name]
    if len(named) == 1:
        return named
    if len(named) > 1:
        comp.faults.append(
            f"{where} port {port.name!r}: exact-name match must be unique but "
            f"{len(named)} upstream outputs share name and type "
            f"{port.type_id!r} — add a per-port map override"
        )
        return None
    if len(typed) == 1:
        return typed
    if len(typed) > 1:
        candidates = sorted(_describe(source) for source in typed)
        comp.faults.append(
            f"{where} port {port.name!r}: {len(typed)} candidates of type "
            f"{port.type_id!r} ({candidates}) — ambiguity is an error, never a "
            "guess; add a per-port map override naming one"
        )
        return None
    if port.cardinality == "optional":
        return None
    comp.faults.append(
        f"{where} port {port.name!r}: no upstream output of type {port.type_id!r}; "
        f"available types: {sorted({s.port.type_id for s in pool})}"
    )
    return None


def _resolve_selector(
    comp: _Compilation,
    selector: str,
    node_lookup: dict[str, dict[str, list[_Source]]],
    input_sources: dict[str, list[_Source]],
    *,
    where: str,
) -> list[_Source] | None:
    node_name, _, port_name = selector.partition(".")
    if not port_name:
        comp.faults.append(
            f"{where}: selector {selector!r} must be 'node.port' or '$input.port'"
        )
        return None
    if node_name == "$input":
        sources = input_sources.get(port_name)
    else:
        sources = node_lookup.get(node_name, {}).get(port_name)
    if not sources:
        comp.faults.append(
            f"{where}: selector {selector!r} names no known upstream output"
        )
        return None
    return sources


def _compile_grants(
    comp: _Compilation,
    parent: EffectiveGrants,
    request: GrantRequest | None,
    *,
    where: ScopePath,
) -> EffectiveGrants:
    """GrantRequest may inherit; the result is fully concrete and only narrows."""
    if request is None:
        return parent
    faults_before = len(comp.faults)
    posture = request.posture or parent.posture
    if posture is Posture.WRITE and parent.posture is Posture.READ:
        comp.faults.append(
            f"{where.render()}: grant requests may only narrow — WRITE requested "
            "under a READ parent"
        )
    model_selection = (
        ModelSelection(kind="explicit", model=request.model)
        if request.model is not None
        else parent.model_selection
    )
    allowed_tools = (
        request.allowed_tools if request.allowed_tools is not None else parent.allowed_tools
    )
    if request.allowed_tools is not None and not set(request.allowed_tools) <= set(
        parent.allowed_tools
    ):
        widened = sorted(set(request.allowed_tools) - set(parent.allowed_tools))
        comp.faults.append(
            f"{where.render()}: allowed_tools may only narrow; {widened} exceed the parent grant"
        )
    env_allowlist = (
        request.env_allowlist if request.env_allowlist is not None else parent.env_allowlist
    )
    if request.env_allowlist is not None and not set(request.env_allowlist) <= set(
        parent.env_allowlist
    ):
        widened = sorted(set(request.env_allowlist) - set(parent.env_allowlist))
        comp.faults.append(
            f"{where.render()}: env_allowlist may only narrow; {widened} exceed the parent grant"
        )
    if request.network == "inherit":
        network = parent.network
    elif request.network == "allow" and parent.network == "none":
        comp.faults.append(
            f"{where.render()}: network may only narrow — 'allow' requested under 'none'"
        )
        network = parent.network
    else:
        network = request.network
    timeout_s = request.timeout_s or parent.timeout_s
    if request.timeout_s is not None and request.timeout_s > parent.timeout_s:
        comp.faults.append(
            f"{where.render()}: timeout_s may only narrow; {request.timeout_s} exceeds "
            f"parent {parent.timeout_s}"
        )
    if len(comp.faults) > faults_before:
        return parent
    return EffectiveGrants(
        posture=posture,
        model_selection=model_selection,
        effort=request.effort or parent.effort,
        allowed_tools=allowed_tools,
        env_allowlist=env_allowlist,
        network=network,
        timeout_s=timeout_s,
    )


def _upstream_closure(graph: Graph) -> dict[str, list[str]]:
    direct: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    for connection in graph.connections:
        if connection.src not in direct or connection.dst not in direct:
            continue  # fault surfaced by _ordered_nodes
        direct[connection.dst].append(connection.src)
    closure: dict[str, list[str]] = {}

    def visit(name: str, seen: set[str]) -> list[str]:
        if name in closure:
            return closure[name]
        ordered: list[str] = []
        for parent in direct.get(name, ()):  # depth-first, deterministic
            if parent in seen:
                continue
            for ancestor in visit(parent, seen | {name}):
                if ancestor not in ordered:
                    ordered.append(ancestor)
            if parent not in ordered:
                ordered.append(parent)
        closure[name] = ordered
        return ordered

    for node in graph.nodes:
        visit(node.id, set())
    return closure


def _ordered_nodes(graph: Graph, upstream: dict[str, list[str]]) -> list[GraphNode]:
    by_id: dict[str, GraphNode] = {str(node.id): node for node in graph.nodes}
    ordered: list[GraphNode] = []
    placed: set[str] = set()

    def place(name: str, trail: tuple[str, ...]) -> None:
        if name in placed:
            return
        if name in trail:
            raise AdmissionError(
                [f"cycle outside Loop involving {' -> '.join((*trail, name))}"]
            )
        for parent in upstream.get(name, ()):  # parents first
            place(parent, (*trail, name))
        placed.add(name)
        ordered.append(by_id[name])

    for node in graph.nodes:
        place(node.id, ())
    return ordered


def _explicit_maps(graph: Graph) -> dict[str, dict[str, str]]:
    maps: dict[str, dict[str, str]] = {}
    for connection in _connections(graph):
        if connection.map:
            maps.setdefault(connection.dst, {}).update(connection.map)
    return maps


def _connections(graph: Graph) -> tuple[Connection, ...]:
    return graph.connections


def _describe(source: _Source) -> str:
    address = source.address
    if isinstance(address, NodePortAddress):
        return f"{address.node}.{address.port}"
    if isinstance(address, GraphInputAddress):
        return f"$input.{address.port}"
    return f"$output.{address.port}"
