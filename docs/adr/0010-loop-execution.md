# 0010 — Generic bounded loops: sealed feedback, framed execution, closure parking

**Status:** accepted (M4) · completes the third and final graph construct.

## Decision

A `Loop` remains generic. The kernel knows only how to seed typed inputs,
thread declared outputs back into inputs, read one canonical boolean decision,
and stop or park. Gate checking, repair, triage, and learning remain ordinary
registered composition.

Admission compiles each authored loop into one immutable `LoopResolution`:

- a static loop scope and a synthetic child `body` scope;
- every initial boundary binding from the outer graph;
- every exact feedback substitution;
- one continuation source with nominal identity
  `constructicon/continue` plus the canonical boolean schema hash and
  cardinality `one`;
- every non-control export and its static outer destination;
- a topologically ordered tuple of atomic member scopes.

The walker obeys that mini-program. It never inspects `Loop.body`, resolves a
reference, searches for a port, infers an export, or reconstructs membership.
A direct `Ref` body is normalized through a compiler-only one-node body named
`$body`, so atomic, composite, and inline graph bodies share one boundary
model.

Each iteration executes the existing atomic-invocation path with one
`IterationFrame(loop, index)` appended to every member `ExecutionPath`.
Checkpoint restoration, event identity, effect idempotency, and capability
leases therefore become iteration-aware without parallel machinery. A durable
checkpoint is fail-closed: exact input hash and version restore it; any
contradiction refuses before implementation, capability acquisition, or effect.
All wire values are canonical JSON; domain models such as `GitRef` are rebuilt
explicitly at component boundaries, so live and restored execution have the
same semantics.

A loop executes at least once. After a completely successful iteration:

- exact `False` publishes only the sealed non-control exports from that
  iteration and completes;
- exact `True` seeds the next iteration through the feedback map;
- exact `True` on the last permitted iteration yields
  `PARKED/policy_exhausted` and publishes nothing.

Parking is a root outcome decided at graph closure, symmetric with failure.
Independent siblings finish. Dependents become BLOCKED with a complete
producer report naming the loop as PARKED. Closure precedence is failure,
then parking, then success; every parked root remains in the machine-shaped
result and terminal event.

## Deliberate cuts

- **No nested loops in M4.** Admission rejects even a nested loop hidden behind
  a composite reference. `ExecutionPath` already supports multiple frames; the
  execution policy waits for a real consumer.
- **No scope- or run-lifetime capability lease.** A fresh invocation workspace
  calls `reset_to(previous: GitRef)` and commits from that exact durable state.
  The ref, not a shared mutable worktree, carries feedback. Invocation lifetime
  is the only implemented lifetime until another real consumer exists (I6).
- **No decision leakage.** The control port is excluded from outer exports. A
  workflow that needs a decision report declares a separate ordinary output.
- **No second scheduler.** A loop is one root execution unit inside the
  walker's existing pass and invokes the same atomic execution function as
  every outer node.

## Git state across iterations

`StagedWriteWorkspace.reset_to(GitRef)` validates repository identity, fetches
and verifies the exact commit, hard-resets and cleans the staging repository,
and is legal only before that acquisition imports a candidate. Every repair
iteration receives a fresh epoch-fenced staging repository; its commit has the
prior candidate as parent. Checkpoints are truth and authority-owned candidate
refs are durable evidence. Crash recovery reads checkpoint data, never
reconstructs state by ref archaeology.

## Persistence and compatibility

- `ExecutionManifest` schema version 2 adds `resolved_loops`; v1 manifests load
  with the semantic empty default and are re-hashed under their declared
  version. Unknown versions, unknown fields, nonempty v1 loop data, or identity
  mismatch are refused.
- SQLite schema version 4 rewrites historical capability lease scope data into
  an empty-frame `ExecutionPath` while preserving lease identity and resource
  references. Old binaries continue to refuse the newer schema.
- Manifest write-once comparison has a byte fast path and a version-aware
  semantic fallback, allowing a v1 document reserialized by the v2 model to
  reproduce without permitting changed semantics under one hash.

## Consequences

The frozen loop sentence is executable clause by clause. A real acceptance
workflow starts with a red Git candidate, repairs it over frame-distinct fresh
workspaces, gates the exact prepared merge with Ruff and Pytest, terminates on
boolean false, and installs one attested idempotent merge. Interrupted and
exhausted runs converge through the same checkpoints, leases, effects, and
journal used everywhere else.
