"""Admission — the one boundary every authoring surface passes through.

The validator compiles an authored ``Graph`` into a sealed
``ExecutionManifest``. References resolve to exact versions; magnetic port
intent becomes explicit bindings; grant requests become concrete authority;
composites flatten into atomic execution units; and bounded loops become sealed
``LoopResolution`` programs. After admission the walker resolves nothing and
infers no structure (I8, I11, I13).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from constructicon.core.address import NodeId, ScopePath
from constructicon.core.channel import ChannelBinding, ChannelContract
from constructicon.core.component import ComponentDef
from constructicon.core.control import ResolutionLock, ResolutionPin
from constructicon.core.errors import AdmissionError
from constructicon.core.grants import (
    EffectiveGrants,
    GrantRequest,
    ModelSelection,
    Posture,
)
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.human import canonical_exchange_fault
from constructicon.core.identity import digest, json_value
from constructicon.core.manifest import (
    CONTINUE_SCHEMA_HASH,
    CONTINUE_TYPE,
    MANIFEST_CHANNEL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    SELF_BINDING,
    SELF_CAPABILITY,
    CapabilityBinding,
    ComponentResolution,
    ExecutionManifest,
    LoopExport,
    LoopResolution,
    ResolvedPortBinding,
    manifest_hash_for,
    source_graph_hash_for,
)
from constructicon.core.ports import (
    GraphInputAddress,
    GraphOutputAddress,
    NodePortAddress,
    Port,
    PortAddress,
    same_boundary,
)
from constructicon.core.registry import RegistrySnapshot, StoredVersion
from constructicon.runtime.registry import CapabilityDescriptor


@dataclass(frozen=True)
class _Source:
    address: PortAddress
    port: Port


@dataclass
class _Compilation:
    snapshot: RegistrySnapshot
    catalog: dict[str, CapabilityDescriptor]
    capabilities: Mapping[str, object]
    faults: list[str] = field(default_factory=list)
    resolutions: list[ComponentResolution] = field(default_factory=list)
    bindings: list[ResolvedPortBinding] = field(default_factory=list)
    capability_bindings: list[CapabilityBinding] = field(default_factory=list)
    loops: list[LoopResolution] = field(default_factory=list)
    atomic_scopes: list[ScopePath] = field(default_factory=list)
    resolution_lock: dict[tuple[str, ...], ResolutionPin] | None = None
    consumed_pins: set[tuple[str, ...]] = field(default_factory=set)


def admit(
    graph: Graph,
    *,
    snapshot: RegistrySnapshot,
    catalog: dict[str, CapabilityDescriptor],
    capabilities: Mapping[str, object],
    root_grants: EffectiveGrants,
    inputs: dict[str, Any],
    resolution_lock: ResolutionLock | None = None,
) -> ExecutionManifest:
    """Compile one authored graph under one immutable registry snapshot."""

    normalized_inputs = json_value(inputs)
    if not isinstance(normalized_inputs, dict):
        raise AdmissionError(["run inputs must be a JSON object keyed by port name"])

    comp = _Compilation(
        snapshot=snapshot,
        catalog=catalog,
        capabilities=capabilities,
        resolution_lock=(
            {pin.scope.segments: pin for pin in resolution_lock.pins}
            if resolution_lock is not None
            else None
        ),
    )
    root_scope = ScopePath(segments=(graph.name,))

    _validate_unique_ports(comp, graph.inputs, where=f"{graph.name} graph inputs")
    _validate_unique_ports(comp, graph.outputs, where=f"{graph.name} graph outputs")

    input_names = {port.name for port in graph.inputs}
    required_input_names = {
        port.name for port in graph.inputs if port.cardinality != "optional"
    }
    missing = sorted(required_input_names - set(normalized_inputs))
    extra = sorted(set(normalized_inputs) - input_names)
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
                address=GraphInputAddress(scope=root_scope, port=port.name),
                port=port,
            )
        ]
        for port in graph.inputs
        if port.name in normalized_inputs
    }

    output_sources = _compile_graph(
        comp,
        graph,
        scope=root_scope,
        input_sources=input_sources,
        grants=root_grants,
        loop_depth=0,
    )

    for port in graph.outputs:
        sources = output_sources.get(port.name)
        if not sources:
            continue
        comp.bindings.append(
            ResolvedPortBinding(
                destination=GraphOutputAddress(scope=root_scope, port=port.name),
                sources=tuple(source.address for source in sources),
            )
        )

    if comp.resolution_lock is not None:
        unused = sorted(set(comp.resolution_lock) - comp.consumed_pins)
        for scope_segments in unused:
            pin = comp.resolution_lock[scope_segments]
            comp.faults.append(
                f"{'/'.join(scope_segments)}: counterfactual resolution lock pin "
                f"{pin.component!r}@{pin.version} was not consumed — the override "
                "changed the source topology or removed a source scope"
            )

    if comp.faults:
        raise AdmissionError(comp.faults)

    graph_hash = source_graph_hash_for(graph)
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
    input_hash = digest("inputs", 1, normalized_inputs)

    # Construct once with a temporary well-formed digest, then compute the real
    # identity through the schema-aware helper. This keeps one identity law.
    temporary_hash = digest("manifest-placeholder", 1, {})
    # The version states what a reader must understand. Only a manifest that
    # actually binds a channel needs an M7-aware reader.
    binds_channel = any(binding.channel is not None for binding in comp.capability_bindings)
    manifest = ExecutionManifest(
        schema_version=(
            MANIFEST_CHANNEL_SCHEMA_VERSION if binds_channel else MANIFEST_SCHEMA_VERSION
        ),
        source_graph=graph,
        source_graph_hash=graph_hash,
        resolved_components=tuple(comp.resolutions),
        resolved_connections=tuple(comp.bindings),
        capability_bindings=tuple(comp.capability_bindings),
        resolved_loops=tuple(comp.loops),
        input_hash=input_hash,
        world_hash=world_hash,
        manifest_hash=temporary_hash,
    )
    return manifest.model_copy(update={"manifest_hash": manifest_hash_for(manifest)})


def _compile_graph(
    comp: _Compilation,
    graph: Graph,
    *,
    scope: ScopePath,
    input_sources: dict[str, list[_Source]],
    grants: EffectiveGrants,
    loop_depth: int,
) -> dict[str, list[_Source]]:
    """Compile one graph level and return its declared output sources."""

    _validate_unique_ports(comp, graph.inputs, where=f"{scope.render()} graph inputs")
    _validate_unique_ports(comp, graph.outputs, where=f"{scope.render()} graph outputs")

    upstream = _upstream_closure(graph)
    node_outputs: dict[str, dict[str, list[_Source]]] = {}
    explicit = _explicit_maps(graph)

    for node in _ordered_nodes(graph, upstream):
        pool: list[_Source] = []
        for name in upstream.get(node.id, ()):
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
            loop_depth=loop_depth,
        )

    outputs: dict[str, list[_Source]] = {}
    node_pool = [
        source
        for per_node in node_outputs.values()
        for sources in per_node.values()
        for source in sources
    ]
    input_pool = [source for sources in input_sources.values() for source in sources]
    for port in graph.outputs:
        # A graph input is a pass-through fallback, not a competitor with a
        # value produced by the graph. This matters most for feedback loops:
        # the initial state and the final exported state share one nominal
        # contract, but the completed loop is the graph's output.
        compatible_node_sources = [
            source for source in node_pool if _ports_same_contract(source.port, port)
        ]
        pool = node_pool if compatible_node_sources else input_pool
        bound = _bind_port(comp, port, pool, where=f"{scope.render()} output")
        if bound is not None:
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
    loop_depth: int,
) -> dict[str, list[_Source]]:
    body = node.body
    instance_scope = level_scope.child(node.id)

    if isinstance(body, Loop):
        if loop_depth:
            comp.faults.append(
                f"{instance_scope.render()}: nested Loop arrives with a later "
                "milestone; make the inner loop an ordinary bounded component "
                "or flatten the feedback for M4"
            )
            return {}
        return _compile_loop(
            comp,
            node,
            body,
            level_scope=level_scope,
            pool=pool,
            explicit=explicit,
            node_lookup=node_lookup,
            input_sources=input_sources,
            grants=grants,
        )

    if isinstance(body, Ref):
        stored = _resolve_ref(comp, body, where=instance_scope)
        if stored is None:
            return {}
        definition = stored.definition
        node_grants = _compile_grants(comp, grants, body.grants, where=instance_scope)
        _record_resolution(comp, definition, stored, body, instance_scope)
        bound_inputs = _bind_node_inputs(
            comp,
            node,
            definition.inputs,
            level_scope,
            pool,
            explicit,
            node_lookup,
            input_sources,
        )
        if isinstance(definition.body, Graph):
            if _boundary_lies(comp, stored, where=instance_scope):
                return {}
            declared = {port.name: port for port in definition.inputs}
            retagged = {
                name: [
                    _Source(address=source.address, port=declared[name])
                    for source in sources
                ]
                for name, sources in bound_inputs.items()
            }
            return _compile_graph(
                comp,
                definition.body,
                scope=instance_scope,
                input_sources=retagged,
                grants=node_grants,
                loop_depth=loop_depth,
            )
        return _register_atomic(
            comp,
            node,
            definition,
            instance_scope,
            level_scope,
            bound_inputs,
            body,
            node_grants,
        )

    # Inline nested Graph: legal as a compiler intermediate or run root (I10).
    bound_inputs = _bind_node_inputs(
        comp,
        node,
        body.inputs,
        level_scope,
        pool,
        explicit,
        node_lookup,
        input_sources,
    )
    return _compile_graph(
        comp,
        body,
        scope=instance_scope,
        input_sources=bound_inputs,
        grants=grants,
        loop_depth=loop_depth,
    )


def _compile_loop(
    comp: _Compilation,
    node: GraphNode,
    loop: Loop,
    *,
    level_scope: ScopePath,
    pool: list[_Source],
    explicit: dict[str, str],
    node_lookup: dict[str, dict[str, list[_Source]]],
    input_sources: dict[str, list[_Source]],
    grants: EffectiveGrants,
) -> dict[str, list[_Source]]:
    """Compile one loop into a complete, sealed mini-program."""

    loop_scope = level_scope.child(node.id)
    body_scope = loop_scope.child("body")

    if isinstance(loop.body, Ref):
        stored = _resolve_ref(comp, loop.body, where=body_scope.child("$body"))
        if stored is None:
            return {}
        if _boundary_lies(comp, stored, where=body_scope.child("$body")):
            return {}
        body_inputs = stored.definition.inputs
        body_outputs_declared = stored.definition.outputs
    else:
        body_inputs = loop.body.inputs
        body_outputs_declared = loop.body.outputs

    _validate_unique_ports(comp, body_inputs, where=f"{loop_scope.render()} body inputs")
    _validate_unique_ports(
        comp, body_outputs_declared, where=f"{loop_scope.render()} body outputs"
    )
    inputs_by_name = {port.name: port for port in body_inputs}
    outputs_by_name = {port.name: port for port in body_outputs_declared}

    for input_name, output_name in loop.feedback.items():
        input_port = inputs_by_name.get(input_name)
        output_port = outputs_by_name.get(output_name)
        if input_port is None:
            comp.faults.append(
                f"{loop_scope.render()}: feedback destination {input_name!r} is not "
                f"a declared body input; available inputs: {sorted(inputs_by_name)}"
            )
        if output_port is None:
            comp.faults.append(
                f"{loop_scope.render()}: feedback source {output_name!r} is not a "
                f"declared body output; available outputs: {sorted(outputs_by_name)}"
            )
        if input_port is None or output_port is None:
            continue
        if input_port.cardinality != "one" or output_port.cardinality != "one":
            comp.faults.append(
                f"{loop_scope.render()}: feedback {input_name!r} <- {output_name!r} "
                "requires cardinality 'one' on both ports; use an explicit adapter "
                "component before the feedback edge"
            )
        if not _ports_same_contract(input_port, output_port):
            comp.faults.append(
                f"{loop_scope.render()}: feedback {input_name!r} <- {output_name!r} "
                "must preserve the exact nominal contract (type_id + schema_hash); "
                f"found {input_port.type_id!r}@{input_port.schema_hash!r} <- "
                f"{output_port.type_id!r}@{output_port.schema_hash!r}"
            )

    continue_port = outputs_by_name.get(loop.continue_from)
    if continue_port is None:
        comp.faults.append(
            f"{loop_scope.render()}: continue_from {loop.continue_from!r} is not a "
            f"declared body output; available outputs: {sorted(outputs_by_name)}"
        )
    elif (
        continue_port.type_id != CONTINUE_TYPE
        or continue_port.schema_hash != CONTINUE_SCHEMA_HASH
        or continue_port.cardinality != "one"
    ):
        comp.faults.append(
            f"{loop_scope.render()}: continuation output {loop.continue_from!r} must "
            f"be exactly {CONTINUE_TYPE!r}@{CONTINUE_SCHEMA_HASH!r} with cardinality "
            "'one'; declare a boolean control port or add a deterministic adapter"
        )

    initial_bindings: list[ResolvedPortBinding] = []
    boundary_sources: dict[str, list[_Source]] = {}
    for port in body_inputs:
        selected: list[_Source] | None
        if port.name in explicit:
            selected = _resolve_selector(
                comp,
                explicit[port.name],
                node_lookup,
                input_sources,
                where=f"{loop_scope.render()} boundary",
            )
            if selected is not None:
                selected = _validate_explicit_sources(
                    comp,
                    port,
                    selected,
                    where=f"{loop_scope.render()} boundary",
                )
        else:
            compatible = [source for source in pool if _source_matches(source, port)]
            if not compatible and port.name in loop.feedback:
                comp.faults.append(
                    f"{loop_scope.render()}: feedback port {port.name!r} needs an "
                    "initial value at the outer level; connect a matching seed or "
                    "add a per-port map override"
                )
                selected = None
            else:
                selected = _bind_port(
                    comp,
                    port,
                    pool,
                    where=f"{loop_scope.render()} boundary",
                )
        if selected is None:
            continue
        destination = GraphInputAddress(scope=body_scope, port=port.name)
        initial_bindings.append(
            ResolvedPortBinding(
                destination=destination,
                sources=tuple(source.address for source in selected),
            )
        )
        boundary_sources[port.name] = [_Source(address=destination, port=port)]

    atomic_start = len(comp.atomic_scopes)
    if isinstance(loop.body, Ref):
        synthetic = GraphNode(id=NodeId("$body"), body=loop.body)
        body_outputs = _compile_node(
            comp,
            synthetic,
            level_scope=body_scope,
            pool=[source for sources in boundary_sources.values() for source in sources],
            explicit={},
            node_lookup={},
            input_sources=boundary_sources,
            grants=grants,
            loop_depth=1,
        )
    else:
        body_outputs = _compile_graph(
            comp,
            loop.body,
            scope=body_scope,
            input_sources=boundary_sources,
            grants=grants,
            loop_depth=1,
        )
    member_order = tuple(comp.atomic_scopes[atomic_start:])
    if not member_order:
        comp.faults.append(
            f"{loop_scope.render()}: loop body contains no atomic component; "
            "M4 requires at least one checkpoint-owning invocation per iteration"
        )

    feedback_bindings: list[ResolvedPortBinding] = []
    for input_name, output_name in loop.feedback.items():
        if input_name not in inputs_by_name or output_name not in outputs_by_name:
            continue
        sources = body_outputs.get(output_name)
        if not sources:
            continue
        if len(sources) != 1:
            comp.faults.append(
                f"{loop_scope.render()}: feedback source {output_name!r} must "
                f"resolve to exactly one body source; found {len(sources)}"
            )
            continue
        feedback_bindings.append(
            ResolvedPortBinding(
                destination=GraphInputAddress(scope=body_scope, port=input_name),
                sources=tuple(source.address for source in sources),
            )
        )

    continue_sources = body_outputs.get(loop.continue_from)
    if continue_sources is None or len(continue_sources) != 1:
        if continue_port is not None:
            comp.faults.append(
                f"{loop_scope.render()}: continuation output {loop.continue_from!r} "
                "must resolve to exactly one body source"
            )
        # Use a syntactically valid placeholder; admission fails before emission.
        continue_source: PortAddress = GraphInputAddress(
            scope=body_scope, port=loop.continue_from
        )
    else:
        continue_source = continue_sources[0].address

    exports: list[LoopExport] = []
    outer_outputs: dict[str, list[_Source]] = {}
    for port in body_outputs_declared:
        if port.name == loop.continue_from:
            continue
        sources = body_outputs.get(port.name)
        if not sources:
            continue
        export_destination = NodePortAddress(
            scope=level_scope,
            node=node.id,
            port=port.name,
        )
        exports.append(
            LoopExport(
                port=port,
                destination=export_destination,
                sources=tuple(source.address for source in sources),
            )
        )
        outer_outputs[port.name] = [
            _Source(address=export_destination, port=port)
        ]

    comp.loops.append(
        LoopResolution(
            scope=loop_scope,
            body_scope=body_scope,
            max_iterations=loop.max_iterations,
            input_ports=body_inputs,
            initial_bindings=tuple(initial_bindings),
            feedback_bindings=tuple(feedback_bindings),
            continue_source=continue_source,
            exports=tuple(exports),
            member_order=member_order,
        )
    )
    return outer_outputs


def _record_resolution(
    comp: _Compilation,
    definition: ComponentDef,
    stored: StoredVersion,
    ref: Ref,
    scope: ScopePath,
) -> None:
    comp.resolutions.append(
        ComponentResolution(
            scope=scope,
            component=definition.name,
            requested_version=ref.version,
            resolved_version=stored.content_hash,
            contract_hash=digest(
                "component-contract",
                1,
                {
                    "inputs": [port.model_dump(mode="json") for port in definition.inputs],
                    "outputs": [port.model_dump(mode="json") for port in definition.outputs],
                },
            ),
            implementation_digest=(
                None if isinstance(definition.body, Graph) else definition.body.source_digest
            ),
        )
    )


def _boundary_lies(comp: _Compilation, stored: StoredVersion, *, where: ScopePath) -> bool:
    """A retained composite whose declared boundary is not its Graph's is re-proved, not trusted.

    The registry refuses such a definition at registration; a store retained
    from before that rule reaches admission only through here. The fault names
    the retained version, because the defect is in it and not in the graph
    that seats it.
    """

    definition = stored.definition
    if not isinstance(definition.body, Graph):
        return False
    if same_boundary(definition.inputs, definition.body.inputs) and same_boundary(
        definition.outputs, definition.body.outputs
    ):
        return False
    comp.faults.append(
        f"{where.render()}: retained composite {definition.name!r}@{stored.content_hash} "
        "declares a boundary its Graph does not export"
    )
    return True


def _resolve_ref(
    comp: _Compilation, ref: Ref, *, where: ScopePath
) -> StoredVersion | None:
    """Resolve a Ref against the admission's one immutable snapshot (I12)."""

    snapshot = comp.snapshot
    if comp.resolution_lock is not None:
        pin = comp.resolution_lock.get(where.segments)
        if pin is None:
            comp.faults.append(
                f"{where.render()}: counterfactual resolution lock contains no pin "
                f"for component {ref.component!r} — topology-changing replay is refused"
            )
            return None
        comp.consumed_pins.add(where.segments)
        if pin.component != ref.component:
            comp.faults.append(
                f"{where.render()}: resolution lock expects component "
                f"{pin.component!r}, graph resolves {ref.component!r} — topology changed"
            )
            return None
        stored = snapshot.get(pin.component, pin.version)
        if stored is None:
            comp.faults.append(
                f"{where.render()}: resolution lock requires retained exact version "
                f"{pin.component!r}@{pin.version}, but it is unavailable"
            )
            return None
        return stored

    if ref.component not in snapshot.versions:
        comp.faults.append(
            f"{where.render()}: unknown component {ref.component!r}; "
            f"registered components: {snapshot.names()}"
        )
        return None
    if ref.version is None:
        stable = snapshot.stable_version(ref.component)
        if stable is None:
            registered = list(snapshot.order.get(ref.component, ()))
            comp.faults.append(
                f"{where.render()}: component {ref.component!r} has no stable "
                f"version; registered versions: {registered} — promote one "
                "(registration never propagates; promotion does)"
            )
            return None
        stored = snapshot.get(ref.component, stable)
        if stored is None:
            comp.faults.append(
                f"{where.render()}: component {ref.component!r} stable pointer "
                f"{str(stable)!r} names no stored version — registry damage"
            )
        return stored
    stored = snapshot.versions.get(ref.component, {}).get(ref.version)
    if stored is None:
        registered = list(snapshot.order.get(ref.component, ()))
        comp.faults.append(
            f"{where.render()}: component {ref.component!r} has no version "
            f"{ref.version!r}; registered versions: {registered}"
        )
        return None
    return stored


def _compiled_channel(
    comp: _Compilation,
    definition: ComponentDef,
    instance_scope: ScopePath,
    *,
    alias: str,
    descriptor: CapabilityDescriptor,
) -> ChannelBinding | None:
    """Compile the one exchange a channel-bound component may carry.

    The request/reply pair is admitted here and never chosen at call time.
    Pinned source is not pinned behavior: a component free to name its own port
    on replay could derive a second request id and append a second message,
    which no equality fence would catch.

    A component needing more ports composes around a one-exchange component
    rather than teaching admission to guess which pair is the exchange (I10).
    """

    capability_id = descriptor.capability_id
    incoherence = descriptor.channel_incoherence(comp.capabilities.get(capability_id))
    if incoherence is not None:
        comp.faults.append(
            f"{instance_scope.render()}: binding {alias!r} names capability "
            f"{capability_id!r}, but {incoherence}"
        )
        return None
    if descriptor.channel_profile is None:
        return None
    endpoint = descriptor.endpoint
    if endpoint is None:
        comp.faults.append(
            f"{instance_scope.render()}: binding {alias!r} names channel "
            f"{capability_id!r}, but assembly supplied no ChannelEndpoint — a "
            "channel-bound component requires sealed lane, interaction, and recipient"
        )
        return None
    if len(definition.inputs) != 1 or len(definition.outputs) != 1:
        comp.faults.append(
            f"{instance_scope.render()}: binding {alias!r} addresses channel "
            f"{capability_id!r}, so {definition.name!r} must declare exactly one "
            "input (the request) and one output (the reply); it declares "
            f"{len(definition.inputs)} and {len(definition.outputs)} — compose "
            "around a one-exchange component instead"
        )
        return None
    request, reply = definition.inputs[0], definition.outputs[0]
    request_contract = ChannelContract(type_id=request.type_id, schema_hash=request.schema_hash)
    reply_contract = ChannelContract(type_id=reply.type_id, schema_hash=reply.schema_hash)
    mismatch = canonical_exchange_fault(request_contract, reply_contract, endpoint.interaction)
    if mismatch is not None:
        comp.faults.append(
            f"{instance_scope.render()}: binding {alias!r} to channel "
            f"{capability_id!r} {mismatch}"
        )
        return None
    return ChannelBinding(
        endpoint=endpoint,
        port=request.name,
        contract=request_contract,
        reply_port=reply.name,
        reply_contract=reply_contract,
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
                    scope=level_scope,
                    node=node.id,
                    port=port_name,
                ),
                sources=tuple(source.address for source in sources),
            )
        )
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
        if (
            descriptor.requires_posture is Posture.WRITE
            and node_grants.posture is not Posture.WRITE
        ):
            comp.faults.append(
                f"{instance_scope.render()}: capability {capability_id!r} requires "
                f"WRITE posture; node grants are {node_grants.posture.value!r} — "
                "isolation is admission logic, it never degrades (I1)"
            )
        comp.capability_bindings.append(
            CapabilityBinding(
                scope=instance_scope,
                binding=alias,
                capability_id=capability_id,
                revision=descriptor.revision,
                effective_grants=node_grants,
                lifetime="invocation",
                channel=_compiled_channel(
                    comp,
                    definition,
                    instance_scope,
                    alias=alias,
                    descriptor=descriptor,
                ),
            )
        )
    comp.atomic_scopes.append(instance_scope)
    return {
        port.name: [
            _Source(
                address=NodePortAddress(
                    scope=level_scope,
                    node=node.id,
                    port=port.name,
                ),
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
                comp,
                explicit[port.name],
                node_lookup,
                input_sources,
                where=where,
            )
            if sources is not None:
                validated = _validate_explicit_sources(comp, port, sources, where=where)
                if validated is not None:
                    bound[port.name] = validated
            continue
        sources = _bind_port(comp, port, pool, where=where)
        if sources is not None:
            bound[port.name] = sources
    return bound


def _source_matches(source: _Source, port: Port) -> bool:
    return (
        source.port.type_id == port.type_id
        and source.port.schema_hash == port.schema_hash
    )


def _ports_same_contract(left: Port, right: Port) -> bool:
    return left.type_id == right.type_id and left.schema_hash == right.schema_hash


def _bind_port(
    comp: _Compilation,
    port: Port,
    pool: list[_Source],
    *,
    where: str,
) -> list[_Source] | None:
    """Apply the fixed nominal magnetic rules; ambiguity is never guessed."""

    typed = [source for source in pool if _source_matches(source, port)]
    if port.cardinality == "many":
        if not typed:
            comp.faults.append(
                f"{where} port {port.name!r} gathers nominal type "
                f"{port.type_id!r}@{port.schema_hash!r} but no upstream output "
                f"offers it; available contracts: {_available_contracts(pool)}"
            )
            return None
        return typed

    named = [source for source in typed if source.port.name == port.name]
    if len(named) == 1:
        return named
    if len(named) > 1:
        comp.faults.append(
            f"{where} port {port.name!r}: exact-name match must be unique but "
            f"{len(named)} upstream outputs share nominal contract "
            f"{port.type_id!r}@{port.schema_hash!r} — add a per-port map override"
        )
        return None
    if len(typed) == 1:
        return typed
    if len(typed) > 1:
        candidates = sorted(_describe(source) for source in typed)
        comp.faults.append(
            f"{where} port {port.name!r}: {len(typed)} candidates of nominal "
            f"contract {port.type_id!r}@{port.schema_hash!r} ({candidates}) — "
            "ambiguity is an error; add a per-port map override naming one"
        )
        return None
    if port.cardinality == "optional":
        return None
    comp.faults.append(
        f"{where} port {port.name!r}: no upstream output of type "
        f"{port.type_id!r} (nominal contract @{port.schema_hash!r}); available contracts: "
        f"{_available_contracts(pool)}"
    )
    return None


def _validate_explicit_sources(
    comp: _Compilation,
    port: Port,
    sources: list[_Source],
    *,
    where: str,
) -> list[_Source] | None:
    incompatible = [source for source in sources if not _source_matches(source, port)]
    if incompatible:
        comp.faults.append(
            f"{where} port {port.name!r}: explicit selector names "
            f"{sorted(_describe(source) for source in incompatible)}, but the port "
            f"requires {port.type_id!r}@{port.schema_hash!r}"
        )
        return None
    if port.cardinality != "many" and len(sources) != 1:
        comp.faults.append(
            f"{where} port {port.name!r}: explicit selector resolves to "
            f"{len(sources)} sources but cardinality is {port.cardinality!r}"
        )
        return None
    return sources


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
    """GrantRequest may inherit; the result is concrete and only narrows."""

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
        request.allowed_tools
        if request.allowed_tools is not None
        else parent.allowed_tools
    )
    if request.allowed_tools is not None and not set(request.allowed_tools) <= set(
        parent.allowed_tools
    ):
        widened = sorted(set(request.allowed_tools) - set(parent.allowed_tools))
        comp.faults.append(
            f"{where.render()}: allowed_tools may only narrow; {widened} exceed "
            "the parent grant"
        )
    env_allowlist = (
        request.env_allowlist
        if request.env_allowlist is not None
        else parent.env_allowlist
    )
    if request.env_allowlist is not None and not set(request.env_allowlist) <= set(
        parent.env_allowlist
    ):
        widened = sorted(set(request.env_allowlist) - set(parent.env_allowlist))
        comp.faults.append(
            f"{where.render()}: env_allowlist may only narrow; {widened} exceed "
            "the parent grant"
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
            f"{where.render()}: timeout_s may only narrow; {request.timeout_s} "
            f"exceeds parent {parent.timeout_s}"
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
            continue
        direct[connection.dst].append(connection.src)
    closure: dict[str, list[str]] = {}

    def visit(name: str, seen: set[str]) -> list[str]:
        if name in closure:
            return closure[name]
        ordered: list[str] = []
        for parent in direct.get(name, ()):
            if parent in seen:
                continue
            for ancestor in visit(parent, seen | {name}):
                if ancestor not in ordered:
                    ordered.append(ancestor)
            if parent not in ordered:
                ordered.append(parent)
        closure[name] = ordered
        return ordered

    for graph_node in graph.nodes:
        visit(graph_node.id, set())
    return closure


def _ordered_nodes(graph: Graph, upstream: dict[str, list[str]]) -> list[GraphNode]:
    by_id: dict[str, GraphNode] = {str(node.id): node for node in graph.nodes}
    if len(by_id) != len(graph.nodes):
        raise AdmissionError([f"graph {graph.name!r} contains duplicate node ids"])
    ordered: list[GraphNode] = []
    placed: set[str] = set()

    def place(name: str, trail: tuple[str, ...]) -> None:
        if name in placed:
            return
        if name not in by_id:
            raise AdmissionError([f"graph {graph.name!r} references unknown node {name!r}"])
        if name in trail:
            raise AdmissionError(
                [f"cycle outside Loop involving {' -> '.join((*trail, name))}"]
            )
        for parent in upstream.get(name, ()):
            place(parent, (*trail, name))
        placed.add(name)
        ordered.append(by_id[name])

    for graph_node in graph.nodes:
        place(graph_node.id, ())
    return ordered


def _explicit_maps(graph: Graph) -> dict[str, dict[str, str]]:
    maps: dict[str, dict[str, str]] = {}
    for connection in _connections(graph):
        if connection.map:
            destination = maps.setdefault(connection.dst, {})
            for port, selector in connection.map.items():
                prior = destination.get(port)
                if prior is not None and prior != selector:
                    raise AdmissionError(
                        [
                            f"graph {graph.name!r} maps destination port {port!r} "
                            f"twice ({prior!r}, {selector!r})"
                        ]
                    )
                destination[port] = selector
    return maps


def _connections(graph: Graph) -> tuple[Connection, ...]:
    return graph.connections


def _validate_unique_ports(
    comp: _Compilation,
    ports: tuple[Port, ...],
    *,
    where: str,
) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for port in ports:
        if port.name in seen:
            duplicates.add(port.name)
        seen.add(port.name)
    if duplicates:
        comp.faults.append(
            f"{where} declare duplicate port names {sorted(duplicates)}; port names "
            "are identities inside feedback and boundary maps"
        )


def _available_contracts(pool: list[_Source]) -> list[str]:
    return sorted({f"{source.port.type_id}@{source.port.schema_hash}" for source in pool})


def _describe(source: _Source) -> str:
    address = source.address
    if isinstance(address, NodePortAddress):
        return f"{address.scope.render()}/{address.node}.{address.port}"
    if isinstance(address, GraphInputAddress):
        return f"{address.scope.render()}/$input.{address.port}"
    return f"{address.scope.render()}/$output.{address.port}"
