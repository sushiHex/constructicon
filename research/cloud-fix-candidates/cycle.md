# Cloud fix candidate: reject authored graph cycles (issue #367)

Base: `b22581ac2922b27f35b0a83b528a25a2cb279073`. Branch: `fix/cloud-cycle`.
Tier: validator (admission) change; no walker, workflow, ADR, or plan edits.

## Reproduction (confirmed at the base commit)

`Constructicon.validate` admitted nodes `back` (BRIEF->ISSUE) and `triage`
(ISSUE->BRIEF) with connections `triage->back` and `back->triage`.
`_upstream_closure` skips any parent already on its DFS stack, so a cycle
member silently loses its back edge (`triage=[]`, `back=[triage]`);
`_ordered_nodes`' "cycle outside Loop" guard was therefore unreachable. The
manifest omitted the `back->triage` binding. Each new test in
`tests/runtime/test_graph_cycles.py` fails on the base source (17 of 19 fail
with `src` stashed; the 2 accepting tests pass on both, as intended).

## Design

`_reject_cycles` in `runtime/validator.py` runs inside `_compile_graph`
immediately after `_validate_connection_endpoints` and before ports, closure,
ordering, or node compilation. It is an iterative DFS over connections in
declaration order; each back edge yields one located `graph_cycle` fault
(message `cycle outside Loop involving a -> b -> a`, details `cycle`,
`connection_index`, `source_node`, `destination_node`, path of the offending
connection) and then raises `AdmissionError`. `authoring.py` maps the defect to
`AdmissionCode.GRAPH_CYCLE` with a repair hint.

- Linear time; no new graph syntax. Loop feedback lives only in `Loop.feedback`
  (M4 rev2), never in connections, so every connection cycle at one level is
  illegal; Loop bodies and retained bodies are compiled through the same
  `_compile_graph`, so they are covered at their own scope/coordinates.
- Fault precedence preserved: endpoint faults still stop first, so cycle
  detection never runs on an endpoint-invalid graph.
- Node ids are opaque strings, so the approved empty `NodeId` is untouched.
- The walker is unchanged.
- `_reject_cycles` raises itself so `_compile_graph` keeps exactly one
  `raise AdmissionError(comp.faults)`, which the M7.1 mutation inventory
  targets by exact-once text.

## Evidence

Refusing (root, inline, retained wrappers): two-node cycle, self-edge,
unanchored three-node cycle with a lone node, cycle downstream of an acyclic
prefix; a cycle inside an explicit Loop body; two independent cycles produce
two faults; cycle check precedes closure/compilation; endpoint-fault
precedence; empty-NodeId self-edge.
Accepting: diamond and shared-ancestor DAGs; explicit Loop with feedback
(`basic_loop`) yields one resolved loop.

Observed passing: `uv run pytest tests/runtime tests/api/test_endpoint_admission.py
tests/test_mutation_inventories.py tests/test_refusal_names.py` (434 passed);
`uv run ruff check` on the three touched files; `uv run mypy src/constructicon/runtime`.
Mutation inventories were checked for target validity only
(`tests/test_mutation_inventories.py`); the mutants themselves were not run.

## Not run

Full `uv run verify`, import-linter, mutation harness execution, CI (no CI
result observed; none is claimed), any live/vendor/credential lane.
The `tests/sdk` + `tests/api` run is reported in the hand-off message.

## Limitations

- Only the first back edge per DFS path is reported per cycle; a graph with
  overlapping cycles may need repeated repair rounds.
- Existing passing fixtures were not audited for unintended cycles beyond the
  suites listed above.
- Refs #367. Delivery handoff and implementation record are left to the
  orchestrator's reviewed PR.
