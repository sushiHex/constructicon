"""Composition sugar that immediately produces the canonical three-construct IR."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from constructicon.core.address import NodeId
from constructicon.core.component import ComponentDef, ComponentRole
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.ports import Port
from constructicon.sdk.types import AuthoringStep, DefinitionBundle


def loop(
    body: DefinitionBundle | Ref | Graph,
    *,
    feedback: Mapping[str, str],
    continue_from: str,
    max_iterations: int,
) -> Loop:
    """Direct one-to-one sugar over M4's generic ``core.Loop``."""

    normalized = body.ref() if isinstance(body, DefinitionBundle) else body
    return Loop(
        body=normalized,
        feedback=dict(feedback),
        continue_from=continue_from,
        max_iterations=max_iterations,
    )


def component(
    name: str,
    body: DefinitionBundle | Ref | Graph | Loop,
    *,
    role: ComponentRole = "component",
    inputs: tuple[Port, ...] | None = None,
    outputs: tuple[Port, ...] | None = None,
) -> DefinitionBundle:
    """Build one named composite; roles never add execution semantics."""

    if isinstance(body, DefinitionBundle):
        inputs = body.definition.inputs if inputs is None else inputs
        outputs = body.definition.outputs if outputs is None else outputs
        body = body.ref()
    if isinstance(body, Graph):
        graph = body
        resolved_inputs = graph.inputs if inputs is None else inputs
        resolved_outputs = graph.outputs if outputs is None else outputs
    else:
        if inputs is None or outputs is None:
            raise TypeError(
                "component inputs and outputs are required when wrapping a Ref or Loop"
            )
        graph = Graph(
            name=name,
            nodes=(GraphNode(id=NodeId("body"), body=body),),
            inputs=inputs,
            outputs=outputs,
        )
        resolved_inputs = inputs
        resolved_outputs = outputs
    return DefinitionBundle(
        definition=ComponentDef(
            name=name,
            role=role,
            body=graph,
            inputs=tuple(resolved_inputs),
            outputs=tuple(resolved_outputs),
            capability_requirements=None,
        )
    )


def harness(
    name: str,
    body: DefinitionBundle | Ref | Graph | Loop,
    *,
    inputs: tuple[Port, ...] | None = None,
    outputs: tuple[Port, ...] | None = None,
) -> DefinitionBundle:
    return component(
        name,
        body,
        role="harness",
        inputs=inputs,
        outputs=outputs,
    )


def flow(
    name: str,
    *steps: AuthoringStep,
    maps: Mapping[str, Mapping[str, str]] | None = None,
    ids: Sequence[str] | None = None,
    inputs: tuple[Port, ...] | None = None,
    outputs: tuple[Port, ...] | None = None,
) -> DefinitionBundle:
    """Create one adjacent chain; granular binding remains validator-only."""

    if not steps:
        raise ValueError("flow requires at least one component reference")
    refs = tuple(_to_ref(step) for step in steps)
    node_ids = _node_ids(refs, ids)
    bundle_by_index = tuple(
        step if isinstance(step, DefinitionBundle) else None for step in steps
    )
    if inputs is None:
        first = bundle_by_index[0]
        if first is None:
            raise TypeError(
                "flow inputs must be declared when the first step is only a Ref/name"
            )
        inputs = first.definition.inputs
    if outputs is None:
        last = bundle_by_index[-1]
        if last is None:
            raise TypeError(
                "flow outputs must be declared when the last step is only a Ref/name"
            )
        outputs = last.definition.outputs

    maps_by_id = {key: dict(value) for key, value in (maps or {}).items()}
    unknown_map_ids = sorted(set(maps_by_id) - set(node_ids))
    if unknown_map_ids:
        raise ValueError(
            f"flow maps name unknown destination node ids {unknown_map_ids}; "
            f"generated ids are {list(node_ids)}"
        )
    if node_ids[0] in maps_by_id:
        raise ValueError(
            f"flow map for first node {node_ids[0]!r} has no incoming Connection; "
            "express graph-input selection through the canonical graph boundary"
        )

    nodes = tuple(
        GraphNode(id=NodeId(node_id), body=ref)
        for node_id, ref in zip(node_ids, refs, strict=True)
    )
    connections = tuple(
        Connection(
            src=NodeId(node_ids[index - 1]),
            dst=NodeId(node_ids[index]),
            map=maps_by_id.get(node_ids[index], {}),
        )
        for index in range(1, len(node_ids))
    )
    graph = Graph(
        name=name,
        nodes=nodes,
        connections=connections,
        inputs=tuple(inputs),
        outputs=tuple(outputs),
    )
    return component(name, graph, role="workflow")


def panel(
    name: str,
    *members: DefinitionBundle,
    aggregator: DefinitionBundle,
    ids: Sequence[str] | None = None,
    aggregator_id: str | None = None,
) -> DefinitionBundle:
    """Fan one request out to every member and gather every result into one place.

    Literal Graph sugar and nothing more. The graph's inputs reach every member
    without a connection, because a graph input is in every node's binding
    pool; the members reach the aggregator through one plain connection each,
    and the aggregator's ``many`` port gathers what its upstream offers. No map
    is written, because a map names one ``node.port`` and a fan-in of many is
    exact by construction, not by naming.

    Exact by construction means proved here, at authoring, from declared
    contracts — which is why members and the aggregator are bundles and never
    bare names. Every member declares one request and one result, each of
    cardinality ``one`` — a seat answers exactly once — and the same pair as
    every other member; the aggregator declares exactly one ``many``
    port and it is that result contract; no boundary input — the request or an
    aggregator policy input — carries that result contract, because a graph
    input is in every node's pool and would be gathered as a member; and no
    boundary port name repeats. A member of another contract would not fail —
    it would be gathered by nobody and silently absent — so it is refused.

    The combinator executes nothing, chooses no model, infers no quorum, and
    hides no scheduler. Quorum is the aggregator's ordinary typed input and
    arrives as a graph input beside the request.
    """

    if not members:
        raise ValueError("panel requires at least one member")
    for member in members:
        if not isinstance(member, DefinitionBundle):
            raise TypeError("panel members must be definition bundles, not bare names")
    if not isinstance(aggregator, DefinitionBundle):
        raise TypeError("panel aggregator must be a definition bundle, not a bare name")
    request, result = _one_member_contract(members)
    gathers, policy_inputs = _aggregator_contract(aggregator, result)

    member_refs = tuple(member.ref() for member in members)
    member_ids = _node_ids(member_refs, ids)
    gather_id = _node_ids((aggregator.ref(),), None)[0] if aggregator_id is None else aggregator_id
    _validate_ids((gather_id,))
    if gather_id in member_ids:
        raise ValueError(
            f"panel aggregator id {gather_id!r} collides with a member id; pass aggregator_id"
        )

    inputs = (request, *policy_inputs)
    for port in inputs:
        if _same_contract(port, result):
            raise TypeError(
                f"panel boundary input {port.name!r} has the members' result contract and "
                "would be gathered as a member; a graph input is in every node's pool"
            )
    names = [port.name for port in inputs]
    if len(set(names)) != len(names):
        raise TypeError(
            f"panel boundary port names collide: {names}; the members' request and the "
            "aggregator's inputs must be distinctly named"
        )
    del gathers  # proved present and matching; it is fed by the members, not the boundary

    nodes = (
        *(
            GraphNode(id=NodeId(node_id), body=ref)
            for node_id, ref in zip(member_ids, member_refs, strict=True)
        ),
        GraphNode(id=NodeId(gather_id), body=aggregator.ref()),
    )
    connections = tuple(
        Connection(src=NodeId(member_id), dst=NodeId(gather_id)) for member_id in member_ids
    )
    graph = Graph(
        name=name,
        nodes=nodes,
        connections=connections,
        inputs=inputs,
        outputs=tuple(aggregator.definition.outputs),
    )
    return component(name, graph, role="workflow")


def _same_contract(left: Port, right: Port) -> bool:
    return left.type_id == right.type_id and left.schema_hash == right.schema_hash


def _one_member_contract(members: tuple[DefinitionBundle, ...]) -> tuple[Port, Port]:
    """Every member asks the same question and answers in the same shape."""

    first = members[0].definition
    if len(first.inputs) != 1 or len(first.outputs) != 1:
        raise TypeError(
            f"panel member {first.name!r} must declare exactly one input and one output; "
            f"it declares {len(first.inputs)} and {len(first.outputs)}"
        )
    request, result = first.inputs[0], first.outputs[0]
    if request.cardinality != "one" or result.cardinality != "one":
        # A composite whose result is `optional` may seat nobody; one whose
        # result is `many` may seat every internal source it gathers. A member
        # is one seat, and one seat answers exactly once.
        raise TypeError(
            f"panel member {first.name!r} must declare a one-cardinality request and result; "
            f"it declares {request.cardinality!r} -> {result.cardinality!r}"
        )
    for other in members[1:]:
        definition = other.definition
        if definition.inputs != first.inputs or definition.outputs != first.outputs:
            raise TypeError(
                f"panel member {definition.name!r} declares "
                f"{[p.name for p in definition.inputs]} -> "
                f"{[p.name for p in definition.outputs]}, but {first.name!r} declares "
                f"{[p.name for p in first.inputs]} -> {[p.name for p in first.outputs]}; "
                "a panel's members share one exact request and result contract"
            )
    return request, result


def _aggregator_contract(
    aggregator: DefinitionBundle,
    result: Port,
) -> tuple[Port, tuple[Port, ...]]:
    """One `many` port for the members' result, and the rest as boundary inputs."""

    definition = aggregator.definition
    gathering = [port for port in definition.inputs if port.cardinality == "many"]
    if len(gathering) != 1:
        raise TypeError(
            f"panel aggregator {definition.name!r} must declare exactly one many-cardinality "
            f"input; it declares {len(gathering)}"
        )
    gathers = gathering[0]
    if not _same_contract(gathers, result):
        raise TypeError(
            f"panel aggregator {definition.name!r} gathers {gathers.type_id!r}@"
            f"{gathers.schema_hash!r}, but the members produce {result.type_id!r}@"
            f"{result.schema_hash!r}"
        )
    return gathers, tuple(port for port in definition.inputs if port.cardinality != "many")


def _to_ref(step: AuthoringStep) -> Ref:
    if isinstance(step, DefinitionBundle):
        return step.ref()
    if isinstance(step, Ref):
        return step
    return Ref(component=step)


def _node_ids(refs: tuple[Ref, ...], explicit: Sequence[str] | None) -> tuple[str, ...]:
    if explicit is not None:
        if len(explicit) != len(refs):
            raise ValueError(f"ids has {len(explicit)} entries for {len(refs)} steps")
        result = tuple(explicit)
        if len(set(result)) != len(result):
            raise ValueError("node ids must be unique")
        _validate_ids(result)
        return result

    counts: dict[str, int] = {}
    generated: list[str] = []
    for ref in refs:
        segment = ref.component.rsplit("/", 1)[-1]
        base = re.sub(r"[^A-Za-z0-9_]+", "_", segment).strip("_") or "component"
        count = counts.get(base, 0) + 1
        counts[base] = count
        generated.append(base if count == 1 else f"{base}_{count}")
    result = tuple(generated)
    _validate_ids(result)
    return result


def _validate_ids(ids: tuple[str, ...]) -> None:
    for node_id in ids:
        if not node_id:
            raise ValueError("node ids must be non-empty")
        if node_id.startswith("$"):
            raise ValueError("node ids beginning with '$' are compiler-reserved")
