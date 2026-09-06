"""Shadow-measure the narrowed law — corrected methodology.

Defects in the previous pass, both under-reporting:

  * liveness was a module-global set of id() values that outlived the objects,
    so a collected _Source could hand its id to a later one and mark it live;
  * a source bound to a GRAPH OUTPUT entered the same global set, so it read as
    live at any node whose pool contained it.

This pass records consumption per destination, at the node boundary that
actually mediates it, holding references to the _Source objects for the whole
admission so id() stays meaningful.
"""

import pathlib

TARGET = pathlib.Path("src/constructicon/runtime/validator.py")
text = TARGET.read_text(encoding="utf-8")

# --- 1. per-admission ledger on _Compilation ---

old_comp = """    atomic_scopes: list[ScopePath] = field(default_factory=list)
    resolution_lock: dict[tuple[str, ...], ResolutionPin] | None = None
    consumed_pins: set[tuple[str, ...]] = field(default_factory=set)
"""
new_comp = """    atomic_scopes: list[ScopePath] = field(default_factory=list)
    resolution_lock: dict[tuple[str, ...], ResolutionPin] | None = None
    consumed_pins: set[tuple[str, ...]] = field(default_factory=set)
    # (level scope, node id) -> (declares a `many` input, sources bound there).
    # The list holds references for the whole admission so id() is stable.
    boundary: dict[tuple[tuple[str, ...], str], tuple[bool, list["_Source"]]] = field(
        default_factory=dict
    )
"""
assert old_comp in text, "_Compilation fields not found"
text = text.replace(old_comp, new_comp, 1)

# --- 2. record what a node's declared boundary consumed (Ref / inline Graph) ---

old_bni = """        sources = _bind_port(comp, port, pool, where=where)
        if sources is not None:
            bound[port.name] = sources
    return bound
"""
new_bni = """        sources = _bind_port(comp, port, pool, where=where)
        if sources is not None:
            bound[port.name] = sources
    comp.boundary[(level_scope.segments, str(node.id))] = (
        any(port.cardinality == "many" for port in inputs),
        [source for sources in bound.values() for source in sources],
    )
    return bound
"""
assert old_bni in text, "_bind_node_inputs tail not found"
text = text.replace(old_bni, new_bni, 1)

# --- 3. the same for a Loop node's body boundary ---

old_loop_tail = """        boundary_sources[port.name] = [_Source(address=destination, port=port)]

    atomic_start = len(comp.atomic_scopes)"""
new_loop_tail = """        boundary_sources[port.name] = [_Source(address=destination, port=port)]
        _loop_consumed.extend(selected)

    comp.boundary[(level_scope.segments, str(node.id))] = (
        any(port.cardinality == "many" for port in body_inputs),
        _loop_consumed,
    )

    atomic_start = len(comp.atomic_scopes)"""
assert old_loop_tail in text, "_compile_loop boundary tail not found"
text = text.replace(old_loop_tail, new_loop_tail, 1)

old_loop_head = """    initial_bindings: list[ResolvedPortBinding] = []
    boundary_sources: dict[str, list[_Source]] = {}"""
new_loop_head = """    initial_bindings: list[ResolvedPortBinding] = []
    boundary_sources: dict[str, list[_Source]] = {}
    _loop_consumed: list[_Source] = []"""
assert old_loop_head in text, "_compile_loop boundary head not found"
text = text.replace(old_loop_head, new_loop_head, 1)

# --- 4. the recorder ---

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
    out = _os.environ.get("CONSTRUCTICON_LIVENESS_OUT")
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
assert anchor in text, "_Source anchor not found"
text = text.replace(anchor, recorder, 1)

# --- 5. the check, inside _compile_graph ---

old_loop = """    upstream = _upstream_closure(graph)
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
"""
new_loop = """    upstream = _upstream_closure(graph)
    node_outputs: dict[str, dict[str, list[_Source]]] = {}
    explicit = _explicit_maps(graph)

    known = {str(item.id) for item in graph.nodes}
    for index, connection in enumerate(graph.connections):
        if str(connection.src) not in known or str(connection.dst) not in known:
            _FINDINGS.append(
                {
                    "rule": "endpoint",
                    "graph": graph.name,
                    "scope": scope.render(),
                    "src": str(connection.src),
                    "dst": str(connection.dst),
                    "index": index,
                    "faults_already": bool(comp.faults),
                }
            )

    direct_sources: dict[str, list[str]] = {}
    for connection in graph.connections:
        if str(connection.src) in known and str(connection.dst) in known:
            direct_sources.setdefault(str(connection.dst), []).append(str(connection.src))

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
            for src_name in direct_sources.get(str(node.id), ()):
                _FINDINGS.append(
                    {
                        "rule": "unmeasured",
                        "graph": graph.name,
                        "scope": scope.render(),
                        "src": src_name,
                        "dst": str(node.id),
                        "faults_already": bool(comp.faults),
                    }
                )
            continue
        gathers, consumed = recorded
        if not gathers:
            continue
        consumed_origins = {owner.get(id(source)) for source in consumed}
        for src_name in direct_sources.get(str(node.id), ()):
            if src_name not in consumed_origins:
                _FINDINGS.append(
                    {
                        "rule": "gather",
                        "graph": graph.name,
                        "scope": scope.render(),
                        "src": src_name,
                        "dst": str(node.id),
                        "faults_already": bool(comp.faults),
                    }
                )
"""
assert old_loop in text, "_compile_graph node loop not found"
text = text.replace(old_loop, new_loop, 1)

TARGET.write_text(text, encoding="utf-8", newline="\n")
print("instrumented")
