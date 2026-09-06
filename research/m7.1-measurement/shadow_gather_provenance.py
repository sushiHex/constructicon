"""Measure where every `many`-port source actually comes from.

Classifies each source bound to a `many` input port as:

  direct     -- produced by a node with a Connection straight into this node
  transitive -- produced by a node reachable only through the upstream closure
  input      -- a graph input, which sits in every node's pool

If the corpus is overwhelmingly `direct`, then scoping a gather to its
directly-connected sources is a viable law and membership becomes exact by
construction. If it leans on `transitive`/`input`, it is not.
"""

import pathlib

TARGET = pathlib.Path("src/constructicon/runtime/validator.py")
text = TARGET.read_text(encoding="utf-8")

old_comp = """    atomic_scopes: list[ScopePath] = field(default_factory=list)
    resolution_lock: dict[tuple[str, ...], ResolutionPin] | None = None
    consumed_pins: set[tuple[str, ...]] = field(default_factory=set)
"""
new_comp = """    atomic_scopes: list[ScopePath] = field(default_factory=list)
    resolution_lock: dict[tuple[str, ...], ResolutionPin] | None = None
    consumed_pins: set[tuple[str, ...]] = field(default_factory=set)
    # (level scope, node id) -> [(port name, cardinality, bound sources)]
    boundary: dict[tuple[tuple[str, ...], str], list[tuple[str, str, list["_Source"]]]] = (
        field(default_factory=dict)
    )
"""
assert old_comp in text
text = text.replace(old_comp, new_comp, 1)

old_bni = """        sources = _bind_port(comp, port, pool, where=where)
        if sources is not None:
            bound[port.name] = sources
    return bound
"""
new_bni = """        sources = _bind_port(comp, port, pool, where=where)
        if sources is not None:
            bound[port.name] = sources
    comp.boundary[(level_scope.segments, str(node.id))] = [
        (port.name, port.cardinality, list(bound.get(port.name, ())))
        for port in inputs
    ]
    return bound
"""
assert old_bni in text
text = text.replace(old_bni, new_bni, 1)

old_loop_head = """    initial_bindings: list[ResolvedPortBinding] = []
    boundary_sources: dict[str, list[_Source]] = {}"""
new_loop_head = """    initial_bindings: list[ResolvedPortBinding] = []
    boundary_sources: dict[str, list[_Source]] = {}
    _loop_boundary: list[tuple[str, str, list[_Source]]] = []"""
assert old_loop_head in text
text = text.replace(old_loop_head, new_loop_head, 1)

old_loop_tail = """        boundary_sources[port.name] = [_Source(address=destination, port=port)]

    atomic_start = len(comp.atomic_scopes)"""
new_loop_tail = """        boundary_sources[port.name] = [_Source(address=destination, port=port)]
        _loop_boundary.append((port.name, port.cardinality, list(selected)))

    comp.boundary[(level_scope.segments, str(node.id))] = _loop_boundary

    atomic_start = len(comp.atomic_scopes)"""
assert old_loop_tail in text
text = text.replace(old_loop_tail, new_loop_tail, 1)

anchor = """@dataclass(frozen=True)
class _Source:
    address: PortAddress
    port: Port
"""
recorder = """import atexit as _atexit
import json as _json
import os as _os

_FINDINGS: list[dict[str, object]] = []


def _dump() -> None:
    out = _os.environ.get("CONSTRUCTICON_GATHER_OUT")
    if not out or not _FINDINGS:
        return
    with open(out, "a", encoding="utf-8") as handle:
        for row in _FINDINGS:
            handle.write(_json.dumps(row, sort_keys=True) + chr(10))


_atexit.register(_dump)


@dataclass(frozen=True)
class _Source:
    address: PortAddress
    port: Port
"""
assert anchor in text
text = text.replace(anchor, recorder, 1)

old_loop = """    for node in _ordered_nodes(graph, upstream):
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
"""
new_loop = """    known = {str(item.id) for item in graph.nodes}
    direct_sources: dict[str, set[str]] = {}
    for connection in graph.connections:
        if str(connection.src) in known and str(connection.dst) in known:
            direct_sources.setdefault(str(connection.dst), set()).add(str(connection.src))

    for node in _ordered_nodes(graph, upstream):
        pool: list[_Source] = []
        owner: dict[int, str] = {}
        for name in upstream.get(node.id, ()):
            for sources in node_outputs.get(name, {}).values():
                for source in sources:
                    owner[id(source)] = name
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

        recorded = comp.boundary.get((scope.segments, str(node.id)))
        if recorded is None:
            continue
        straight = direct_sources.get(str(node.id), set())
        for port_name, cardinality, sources in recorded:
            if cardinality != "many" or not sources:
                continue
            tally = {"direct": 0, "transitive": 0, "input": 0}
            for source in sources:
                origin = owner.get(id(source))
                if origin is None:
                    tally["input"] += 1
                elif origin in straight:
                    tally["direct"] += 1
                else:
                    tally["transitive"] += 1
            _FINDINGS.append(
                {
                    "graph": graph.name,
                    "scope": scope.render(),
                    "node": str(node.id),
                    "port": port_name,
                    **tally,
                    "faults_already": bool(comp.faults),
                }
            )
"""
assert old_loop in text
text = text.replace(old_loop, new_loop, 1)

TARGET.write_text(text, encoding="utf-8", newline="\n")
print("instrumented")
