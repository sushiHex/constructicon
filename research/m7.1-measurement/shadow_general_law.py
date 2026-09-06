"""WITHDRAWN first-pass connector-liveness instrument.

Retained unchanged in mechanism as historical provenance, not as supporting
evidence. Its module-global ``id()`` ledger permits object-id reuse, and graph
output binding leaks into the same liveness set. Consequently its JSONL and
counts are invalid. See ``../m7.1-connector-liveness-measurement.md`` for the
correction. Do not use this script to support an architectural claim.

Records, for every connection in every graph admission compiles, whether the
source contributed a source object that was actually bound at the destination.
Two variants are measured: strict (the source node's own outputs) and reachable
(the source node's outputs or those of any node upstream of it, which is what
the edge actually makes visible).

Writes findings to CONSTRUCTICON_LIVENESS_OUT. Revert with git checkout.
"""

import pathlib

TARGET = pathlib.Path("src/constructicon/runtime/validator.py")
text = TARGET.read_text(encoding="utf-8")

# --- 1. rename the two binding sites so wrappers can observe their results ---

old_bind = '''def _bind_port(
    comp: _Compilation,
    port: Port,
    pool: list[_Source],
    *,
    where: str,
) -> list[_Source] | None:
    """Apply the fixed nominal magnetic rules; ambiguity is never guessed."""
'''
new_bind = '''def _bind_port(
    comp: _Compilation,
    port: Port,
    pool: list[_Source],
    *,
    where: str,
) -> list[_Source] | None:
    result = _bind_port_impl(comp, port, pool, where=where)
    if result:
        for chosen in result:
            _LIVE_IDS.add(id(chosen))
    return result


def _bind_port_impl(
    comp: _Compilation,
    port: Port,
    pool: list[_Source],
    *,
    where: str,
) -> list[_Source] | None:
    """Apply the fixed nominal magnetic rules; ambiguity is never guessed."""
'''
assert old_bind in text, "bind_port signature not found"
text = text.replace(old_bind, new_bind, 1)

old_explicit = '''def _validate_explicit_sources(
    comp: _Compilation,
    port: Port,
    sources: list[_Source],
    *,
    where: str,
) -> list[_Source] | None:
    incompatible'''
new_explicit = '''def _validate_explicit_sources(
    comp: _Compilation,
    port: Port,
    sources: list[_Source],
    *,
    where: str,
) -> list[_Source] | None:
    result = _validate_explicit_sources_impl(comp, port, sources, where=where)
    if result:
        for chosen in result:
            _LIVE_IDS.add(id(chosen))
    return result


def _validate_explicit_sources_impl(
    comp: _Compilation,
    port: Port,
    sources: list[_Source],
    *,
    where: str,
) -> list[_Source] | None:
    incompatible'''
assert old_explicit in text, "validate_explicit_sources signature not found"
text = text.replace(old_explicit, new_explicit, 1)

# --- 2. the recorder ---

anchor = '''@dataclass(frozen=True)
class _Source:
    address: PortAddress
    port: Port
'''
recorder = '''import atexit as _atexit
import json as _json
import os as _os

_LIVE_IDS: set[int] = set()
_LIVENESS_FINDINGS: list[dict[str, object]] = []


def _dump_liveness() -> None:
    out = _os.environ.get("CONSTRUCTICON_LIVENESS_OUT")
    if not out or not _LIVENESS_FINDINGS:
        return
    with open(out, "a", encoding="utf-8") as handle:
        for row in _LIVENESS_FINDINGS:
            handle.write(_json.dumps(row, sort_keys=True) + chr(10))


_atexit.register(_dump_liveness)


@dataclass(frozen=True)
class _Source:
    address: PortAddress
    port: Port
'''
assert anchor in text, "_Source anchor not found"
text = text.replace(anchor, recorder, 1)

# --- 3. the measurement inside _compile_graph ---

old_loop = '''    for node in _ordered_nodes(graph, upstream):
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
'''
new_loop = '''    direct_sources: dict[str, list[str]] = {}
    for connection in graph.connections:
        if connection.src in upstream and connection.dst in upstream:
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

        for src_name in direct_sources.get(str(node.id), ()):
            reach = {src_name, *upstream.get(src_name, ())}
            strict = any(
                owner.get(id(source)) == src_name and id(source) in _LIVE_IDS
                for source in pool
            )
            reachable = any(
                owner.get(id(source)) in reach and id(source) in _LIVE_IDS
                for source in pool
            )
            if not strict or not reachable:
                _LIVENESS_FINDINGS.append(
                    {
                        "graph": graph.name,
                        "scope": scope.render(),
                        "src": src_name,
                        "dst": str(node.id),
                        "strict_live": strict,
                        "reachable_live": reachable,
                        "faults_already": bool(comp.faults),
                    }
                )
'''
assert old_loop in text, "compile_graph node loop not found"
text = text.replace(old_loop, new_loop, 1)

TARGET.write_text(text, encoding="utf-8", newline="\n")
print("instrumented")
