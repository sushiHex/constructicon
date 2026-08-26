# Invariants

Review law. A change that violates one is wrong even if it works. Do not weaken
an invariant because an implementation detail feels inconvenient — make the
implementation satisfy the invariant.

- **I1 — Authority is physical.** Effects (merge, rollback, run transitions)
  belong to deterministic code operating on git and the journal. LLMs propose —
  work *and* structure; code validates, executes, disposes. Enforcement is
  substrate-owned isolation and journal-minted attestations; backend flags are
  defense in depth, never the boundary.
- **I2 — Effects carry proof.** Irreversible actions require an attestation
  minted by trusted deterministic code into the journal and referenced by id —
  never a caller-supplied object. Attestations bind subject, evidence, and the
  attesting run's sealed world; installation re-verifies against current state.
- **I3 — No ambient authority.** Capabilities reach a node only through
  declared, admitted bindings. A proposed graph wires registered components
  under granted capabilities; it can never inject code or widen a grant.
- **I4 — Truthful telemetry.** Unemitted fields are `None`, never inferred;
  damaged streams demote to partial, never report ok; timeouts salvage partial
  output; guarantees are stated at their real strength.
- **I5 — Control plane typed, data plane in git.** Envelopes cross boundaries;
  code crosses as `GitRef`; other durable evidence crosses as content-addressed
  `ArtifactRef`; channels carry typed envelopes only.
- **I6 — No abstraction without a second consumer.** An interface exists only
  when a second real implementation *or a genuine test double* exercises the
  same contract. Internal sub-stores of one facility never count.
- **I7 — The fake path is the tested path.** The full lifecycle runs in CI with
  zero credentials; fault injection at every completion boundary; live runs are
  an opt-in local lane.
- **I8 — One structure per concept; dependencies point at contracts.**
  L0 owns contracts; L1 implements them; L2 depends on L0 contracts only; L4
  assembles and injects L1 implementations. Enforced by import-linter in CI.
- **I9 — Agents are the first-class user.** Machine-shaped surfaces: bounded,
  pageable, detail by reference; itemized, repairable errors; discoverable by
  introspection; idempotency keys on every mutating call. Humans participate
  through the same contracts — observer, advisor, approver — and every human
  rendering is derived from the machine form.
- **I10 — Complexity composes; definitions propagate.** Composite over
  monolith; define once, reference by name; immutable retained versions; bare
  references late-bind to the `stable` channel (registration never propagates);
  per-run pinned resolution under one `world_hash`; `rdeps` answers impact
  before change.
- **I11 — One connector; magnetic, deterministic, compiled binding.** Ports are
  nominal-typed with explicit cardinality; wiring two nodes is a single
  connector; binding resolves at admission into explicit resolved edges;
  ambiguity is an itemized error with a per-port override — never a guess.
- **I12 — Learning produces candidates, never mutations.** A running component
  cannot rewrite itself, its evaluator, or its current resolution. Learning
  produces a new immutable child version with recorded lineage; only
  deterministic code may promote it, and promotion affects future runs only.
  Corollary: **the learner cannot define its own exam.**
- **I13 — Intent compiles; execution is sealed.** Authoring surfaces may be
  implicit, magnetic, and compositional, but validation compiles them into one
  immutable `ExecutionManifest`. Every invocation has one stable
  `ExecutionPath`. Authority is granted through scoped capability leases. Every
  external state transition is an idempotent effect producing a receipt. New
  definitions influence future runs only through explicit promotion.

## The conceptual kernel

Almost every concept reduces to four nouns:

| Noun | Meaning |
| --- | --- |
| **Definition** | What may be reused |
| **Manifest** | What this run will execute |
| **Invocation** | Where one execution occurred |
| **Receipt** | What changed outside the run |

Everything else is a policy that transforms or admits these, a transport
carrying them, a projection rendering them, or a capability leased to execute
them.

## Dependency direction

```
core  <-  substrate
core  <-  runtime  <-  sdk  <-  api        (api assembles substrate into runtime)
```

Kernel dependency budget: `core`, `substrate`, and `runtime` import stdlib +
Pydantic only. Enforced in CI.

## Never

LLM watchdogs · a completion-level provider interface · CloudEvents internally ·
a second scheduler beyond the graph walker · a generic internal event bus · a
second workflow representation · mutable component definitions · a parallel
skill registry · a self-learning IR construct · dynamic model-invented skill
lookup · a vector database before structured journal-derived experience proves
insufficient · general JSON-Schema subtyping.
