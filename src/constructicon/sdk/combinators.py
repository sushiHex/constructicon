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

    normalized: Ref | Graph
    if isinstance(body, DefinitionBundle):
        normalized = body.ref()
    else:
        normalized = body
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


def _to_ref(step: AuthoringStep) -> Ref:
    if isinstance(step, DefinitionBundle):
        return step.ref()
    if isinstance(step, Ref):
        return step
    return Ref(component=step)


def _node_ids(refs: tuple[Ref, ...], explicit: Sequence[str] | None) -> tuple[str, ...]:
    if explicit is not None:
        if len(explicit) != len(refs):
            raise ValueError(f"flow ids has {len(explicit)} entries for {len(refs)} steps")
        result = tuple(explicit)
        if len(set(result)) != len(result):
            raise ValueError("flow ids must be unique")
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
            raise ValueError("flow node ids must be non-empty")
        if node_id.startswith("$"):
            raise ValueError("flow node ids beginning with '$' are compiler-reserved")
