"""One typed authoring boundary over the existing runtime validator (M5).

SDK, direct ``Graph`` construction, and architect-proposed JSON all arrive here
as the same canonical Graph. Preflight adds only authoring-contract checks that
need registry/catalog metadata; the existing validator remains the sole source
of resolution, magnetic binding, grants, loop compilation, and manifest
sealing.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any

from constructicon.core.address import ScopePath
from constructicon.core.admission import AdmissionCode, AdmissionFault
from constructicon.core.control import ResolutionLock
from constructicon.core.errors import AdmissionError
from constructicon.core.grants import EffectiveGrants
from constructicon.core.graph import Graph, Loop, Ref
from constructicon.core.introspection import AdmissionLimits
from constructicon.core.manifest import ExecutionManifest
from constructicon.core.registry import RegistrySnapshot, StoredVersion
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.runtime.validator import admit


@dataclass
class _Preflight:
    snapshot: RegistrySnapshot
    catalog: dict[str, CapabilityDescriptor]
    limits: AdmissionLimits
    faults: list[AdmissionFault]
    node_count: int = 0


def admit_authored_graph(
    graph: Graph,
    *,
    snapshot: RegistrySnapshot,
    catalog: dict[str, CapabilityDescriptor],
    root_grants: EffectiveGrants,
    inputs: dict[str, Any],
    limits: AdmissionLimits,
    resolution_lock: ResolutionLock | None = None,
) -> ExecutionManifest:
    """Admit a canonical Graph, raising only typed graph authoring faults."""

    preflight = _Preflight(
        snapshot=snapshot,
        catalog=catalog,
        limits=limits,
        faults=[],
    )
    _preflight_graph(
        preflight,
        graph,
        scope=ScopePath(segments=(graph.name,)),
        path=(),
        depth=1,
        component_stack=(),
    )
    if preflight.faults:
        raise AdmissionError(_bounded_faults(preflight.faults, limits))
    try:
        return admit(
            graph,
            snapshot=snapshot,
            catalog=catalog,
            root_grants=root_grants,
            inputs=inputs,
            resolution_lock=resolution_lock,
        )
    except AdmissionError as exc:
        typed = [
            _classify_fault(fault, graph=graph, limits=limits)
            for fault in exc.faults
        ]
        raise AdmissionError(_bounded_faults(typed, limits)) from None


def _preflight_graph(
    state: _Preflight,
    graph: Graph,
    *,
    scope: ScopePath,
    path: tuple[str | int, ...],
    depth: int,
    component_stack: tuple[tuple[str, str], ...],
) -> None:
    if depth > state.limits.max_nested_graph_depth:
        state.faults.append(
            AdmissionFault(
                code=AdmissionCode.GRAPH_PROPOSAL_LIMIT_EXCEEDED,
                message=(
                    f"graph nesting depth {depth} exceeds the authoring limit "
                    f"{state.limits.max_nested_graph_depth}"
                ),
                path=path,
                scope=scope,
                repair="flatten the proposal or reference a registered composite",
                details={
                    "observed": depth,
                    "limit": state.limits.max_nested_graph_depth,
                },
            )
        )
        return

    seen: dict[str, int] = {}
    for index, node in enumerate(graph.nodes):
        state.node_count += 1
        node_path = (*path, "nodes", index)
        node_scope = scope.child(str(node.id))
        if state.node_count > state.limits.max_nodes:
            state.faults.append(
                AdmissionFault(
                    code=AdmissionCode.GRAPH_PROPOSAL_LIMIT_EXCEEDED,
                    message=f"graph contains more than {state.limits.max_nodes} nodes",
                    path=node_path,
                    scope=node_scope,
                    repair="split the proposal into registered composites",
                    details={
                        "observed_at_least": state.node_count,
                        "limit": state.limits.max_nodes,
                    },
                )
            )
            return
        node_id = str(node.id)
        if node_id in seen:
            state.faults.append(
                AdmissionFault(
                    code=AdmissionCode.GRAPH_NODE_DUPLICATE,
                    message=f"node id {node_id!r} is declared more than once",
                    path=(*node_path, "id"),
                    scope=node_scope,
                    repair="rename this node so every id in the graph is unique",
                    details={"first_index": seen[node_id], "duplicate_index": index},
                )
            )
        else:
            seen[node_id] = index
        if node_id.startswith("$"):
            state.faults.append(
                AdmissionFault(
                    code=AdmissionCode.GRAPH_NODE_RESERVED_ID,
                    message=f"node id {node_id!r} uses the compiler-reserved '$' prefix",
                    path=(*node_path, "id"),
                    scope=node_scope,
                    repair="rename the node without a leading '$'",
                    details={"reserved_prefix": "$"},
                )
            )

        body = node.body
        if isinstance(body, Ref):
            _preflight_ref(
                state,
                body,
                scope=node_scope,
                path=(*node_path, "body"),
                depth=depth,
                component_stack=component_stack,
            )
        elif isinstance(body, Loop):
            loop_body = body.body
            if isinstance(loop_body, Ref):
                _preflight_ref(
                    state,
                    loop_body,
                    scope=node_scope.child("body").child("$body"),
                    path=(*node_path, "body", "body"),
                    depth=depth + 1,
                    component_stack=component_stack,
                )
            else:
                _preflight_graph(
                    state,
                    loop_body,
                    scope=node_scope.child("body"),
                    path=(*node_path, "body", "body"),
                    depth=depth + 1,
                    component_stack=component_stack,
                )
        else:
            _preflight_graph(
                state,
                body,
                scope=node_scope,
                path=(*node_path, "body"),
                depth=depth + 1,
                component_stack=component_stack,
            )


def _preflight_ref(
    state: _Preflight,
    ref: Ref,
    *,
    scope: ScopePath,
    path: tuple[str | int, ...],
    depth: int,
    component_stack: tuple[tuple[str, str], ...],
) -> None:
    stored = _resolve_for_preflight(state.snapshot, ref)
    if stored is None:
        return
    definition = stored.definition
    key = (definition.name, str(stored.content_hash))
    if key in component_stack:
        return

    if isinstance(definition.body, Graph):
        if ref.bind:
            aliases = sorted(ref.bind)
            state.faults.append(
                AdmissionFault(
                    code=AdmissionCode.GRAPH_CAPABILITY_UNDECLARED_BINDING,
                    message=(
                        f"composite component {definition.name!r} does not accept "
                        f"outer capability bindings {aliases}"
                    ),
                    path=(*path, "bind"),
                    scope=scope,
                    repair=(
                        "remove the outer bindings; capability-parameterized "
                        "composites are not part of the M5 contract"
                    ),
                    details={"aliases": aliases},
                )
            )
        _preflight_graph(
            state,
            definition.body,
            scope=scope,
            path=path,
            depth=depth + 1,
            component_stack=(*component_stack, key),
        )
        return

    requirements = definition.capability_requirements
    if requirements is None:
        return
    declared = {requirement.alias: requirement for requirement in requirements}
    for alias, requirement in sorted(declared.items()):
        capability_id = ref.bind.get(alias)
        if capability_id is None:
            available = sorted(
                capability.capability_id
                for capability in state.catalog.values()
                if capability.kind == requirement.kind
            )
            state.faults.append(
                AdmissionFault(
                    code=AdmissionCode.GRAPH_CAPABILITY_MISSING_BINDING,
                    message=(
                        f"{scope.render()}: component {definition.name!r} requires "
                        f"capability alias {alias!r} of kind {requirement.kind!r}"
                    ),
                    path=(*path, "bind", alias),
                    scope=scope,
                    repair=(
                        f"add body.bind[{alias!r}] using one described capability "
                        f"of kind {requirement.kind!r}"
                    ),
                    details={
                        "alias": alias,
                        "required_kind": requirement.kind,
                        "available_capability_ids": available[
                            : state.limits.max_fault_detail_items
                        ],
                        "available_total": len(available),
                        "truncated": len(available)
                        > state.limits.max_fault_detail_items,
                    },
                )
            )
            continue
        descriptor = state.catalog.get(capability_id)
        if descriptor is None:
            available = sorted(state.catalog)
            state.faults.append(
                AdmissionFault(
                    code=AdmissionCode.GRAPH_CAPABILITY_UNKNOWN,
                    message=(
                        f"{scope.render()}: binding {alias!r} names unknown "
                        f"capability {capability_id!r}"
                    ),
                    path=(*path, "bind", alias),
                    scope=scope,
                    repair="replace it with a capability id from system.describe()",
                    details={
                        "alias": alias,
                        "requested": capability_id,
                        "available_capability_ids": available[
                            : state.limits.max_fault_detail_items
                        ],
                        "available_total": len(available),
                        "truncated": len(available)
                        > state.limits.max_fault_detail_items,
                    },
                )
            )
        elif descriptor.kind != requirement.kind:
            state.faults.append(
                AdmissionFault(
                    code=AdmissionCode.GRAPH_CAPABILITY_KIND_MISMATCH,
                    message=(
                        f"{scope.render()}: capability {capability_id!r} has kind "
                        f"{descriptor.kind!r}, but alias {alias!r} requires "
                        f"{requirement.kind!r}"
                    ),
                    path=(*path, "bind", alias),
                    scope=scope,
                    repair=(
                        f"bind alias {alias!r} to a described capability of kind "
                        f"{requirement.kind!r}"
                    ),
                    details={
                        "alias": alias,
                        "capability_id": capability_id,
                        "expected_kind": requirement.kind,
                        "observed_kind": descriptor.kind,
                    },
                )
            )
    extra = sorted(set(ref.bind) - set(declared))
    for alias in extra:
        state.faults.append(
            AdmissionFault(
                code=AdmissionCode.GRAPH_CAPABILITY_UNDECLARED_BINDING,
                message=(
                    f"{scope.render()}: component {definition.name!r} does not "
                    f"declare capability alias {alias!r}"
                ),
                path=(*path, "bind", alias),
                scope=scope,
                repair="remove the undeclared binding",
                details={
                    "alias": alias,
                    "declared_aliases": sorted(declared),
                },
            )
        )


def _resolve_for_preflight(
    snapshot: RegistrySnapshot,
    ref: Ref,
) -> StoredVersion | None:
    if ref.version is None:
        stable = snapshot.stable_version(ref.component)
        return snapshot.get(ref.component, stable) if stable is not None else None
    return snapshot.versions.get(ref.component, {}).get(ref.version)


def _classify_fault(
    fault: AdmissionFault,
    *,
    graph: Graph,
    limits: AdmissionLimits,
) -> AdmissionFault:
    if fault.code is not AdmissionCode.LEGACY_ADMISSION:
        return fault
    message = fault.message
    lowered = message.lower()
    code = AdmissionCode.GRAPH_CONTRACT_INVALID
    repair = "repair the named graph contract and resubmit"
    details: dict[str, Any] = {}
    scope = _scope_from_message(message)

    if "unknown component" in lowered:
        code = AdmissionCode.GRAPH_REFERENCE_UNKNOWN
        repair = "replace the component name with one returned by system.describe()"
        requested = _quoted_after(message, "unknown component")
        if requested:
            details["requested"] = requested
    elif "has no stable version" in lowered:
        code = AdmissionCode.GRAPH_REFERENCE_UNPROMOTED
        repair = "pin an exact retained version or promote one to stable"
    elif "no upstream output" in lowered or "needs an initial value" in lowered:
        code = AdmissionCode.GRAPH_PORT_MISSING_SOURCE
        repair = "connect a matching upstream output or graph input"
    elif "ambiguity is an error" in lowered or "exact-name match must be unique" in lowered:
        code = AdmissionCode.GRAPH_PORT_AMBIGUOUS
        candidates = _candidate_list(message)
        port = _port_from_message(message)
        destination = scope.segments[-1] if scope and scope.segments else None
        connection_index = _incoming_connection_index(graph, destination)
        if candidates:
            details["candidates"] = candidates[: limits.max_fault_detail_items]
            details["candidate_total"] = len(candidates)
            details["truncated"] = len(candidates) > limits.max_fault_detail_items
        if port:
            details["destination_port"] = port
        if candidates and port:
            details["map_example"] = {port: candidates[0]}
        if connection_index is not None and port:
            details["connection_index"] = connection_index
            details["map_path"] = ["connections", connection_index, "map", port]
        repair = (
            "add a Connection.map override selecting one candidate"
            if connection_index is not None
            else "add an explicit adapter/selection node before this graph output"
        )
    elif ("requires" in lowered and "contract" in lowered) or "explicit selector" in lowered:
        code = AdmissionCode.GRAPH_PORT_CONTRACT_MISMATCH
        repair = "select a source with the exact type_id and schema_hash"
    elif "unknown capability" in lowered:
        code = AdmissionCode.GRAPH_CAPABILITY_UNKNOWN
        repair = "replace it with a capability id returned by system.describe()"
    elif "only narrow" in lowered or "may only narrow" in lowered:
        code = AdmissionCode.GRAPH_GRANT_WIDENING
        repair = "remove the widening request or narrow it beneath the root grants"
    elif "loop" in lowered or "continuation" in lowered or "feedback" in lowered:
        code = AdmissionCode.GRAPH_LOOP_INVALID
        repair = "repair the named feedback, continuation, or loop boundary contract"
    elif "cycle outside loop" in lowered or "dependency cycle" in lowered:
        code = AdmissionCode.GRAPH_CYCLE
        repair = "remove the cycle or express bounded feedback through Loop"
    elif "run inputs" in lowered or "graph input" in lowered:
        code = AdmissionCode.GRAPH_INPUT_INVALID
        repair = "supply exactly the graph's declared required input names"

    return AdmissionFault(
        code=code,
        message=message,
        scope=scope,
        repair=repair,
        details=details,
    )


def _scope_from_message(message: str) -> ScopePath | None:
    match = re.match(r"^(?P<scope>[^:]+?) (?:input|output) port ", message)
    if match:
        prefix = match.group("scope").strip()
    else:
        prefix = message.split(":", 1)[0].strip()
        if " " in prefix:
            return None
    segments = tuple(segment for segment in prefix.split("/") if segment)
    return ScopePath(segments=segments) if segments else None


def _quoted_after(message: str, marker: str) -> str | None:
    match = re.search(re.escape(marker) + r"\s+['\"]([^'\"]+)['\"]", message)
    return match.group(1) if match else None


def _port_from_message(message: str) -> str | None:
    match = re.search(r"port ['\"]([^'\"]+)['\"]", message)
    return match.group(1) if match else None


def _candidate_list(message: str) -> list[str]:
    for match in re.finditer(r"\[(?:[^\[\]]|['\"][^'\"]*['\"])*\]", message):
        try:
            value = ast.literal_eval(match.group(0))
        except (SyntaxError, ValueError):
            continue
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            # Validator diagnostics carry fully scoped addresses; Connection.map
            # authoring selectors are node-local ``node.port`` strings. Return
            # the exact repair vocabulary rather than an unparseable scope path.
            return [item.rsplit("/", 1)[-1] for item in value]
    return []


def _incoming_connection_index(graph: Graph, destination: str | None) -> int | None:
    if destination is None:
        return None
    for index, connection in enumerate(graph.connections):
        if str(connection.dst) == destination:
            return index
    return None


def _bounded_faults(
    faults: list[AdmissionFault],
    limits: AdmissionLimits,
) -> tuple[AdmissionFault, ...]:
    ordered = sorted(
        faults,
        key=lambda fault: (
            tuple(str(item) for item in fault.path),
            fault.scope.render() if fault.scope else "",
            fault.code.value,
            fault.message,
        ),
    )
    if len(ordered) <= limits.max_faults:
        return tuple(ordered)
    retained = ordered[: limits.max_faults - 1]
    retained.append(
        AdmissionFault(
            code=AdmissionCode.GRAPH_PROPOSAL_LIMIT_EXCEEDED,
            message=(
                f"admission produced {len(ordered)} faults; response is capped at "
                f"{limits.max_faults}"
            ),
            repair="fix the returned faults and resubmit to reveal any remaining faults",
            details={
                "fault_total": len(ordered),
                "returned": limits.max_faults,
                "truncated": True,
            },
        )
    )
    return tuple(retained)
