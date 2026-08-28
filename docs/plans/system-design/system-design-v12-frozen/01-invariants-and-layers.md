## Part II — The system

### II.1 The thirteen invariants (review law)

- **I1 — Authority is physical.** Effects belong to deterministic code operating on
  git and the journal. LLMs propose work *and* structure; code validates, executes,
  disposes. Enforcement is substrate-owned isolation and journal-minted proofs;
  backend flags are defense in depth, never the boundary.
- **I2 — Effects carry proof.** Irreversible actions require a proof **minted by
  trusted deterministic code into the journal and referenced by id** — never a
  caller-supplied object. Proofs bind candidate, base, tested tree, gate-set hash,
  and workspace identity; approval re-verifies against current repository state.
- **I3 — No ambient authority.** Capabilities reach a node only through declared,
  granted bindings. A proposed graph wires registered components under granted
  capabilities; it can never inject code or widen a grant. `allowed_tools=None`
  means "inherit the parent's already-constrained grant", never "backend default".
- **I4 — Truthful telemetry.** Unemitted fields are None, never inferred; damaged
  streams demote to partial, never ok; timeouts salvage partial output; a damaged
  journal has its own status distinct from executor stream damage; guarantees are
  stated at their real strength (at-least-once is called at-least-once).
- **I5 — Control plane typed, data plane in git.** Envelopes cross boundaries; code
  crosses as commits; `ArtifactRef` bridges; channels carry typed envelopes only.
- **I6 — No abstraction without a second consumer.** An interface may exist only
  when a second real implementation *or a genuine test double exercising the same
  contract* ships with it; internal sub-stores of one facility never count as two
  implementations. Where one concrete implementation is intended, write the
  concrete class and extract the protocol when the second consumer arrives.
- **I7 — The fake path is the tested path.** Full lifecycle in CI with zero
  credentials; fault injection at every completion boundary; recorded transcripts
  for drivers; live runs are an opt-in local lane. "Green-local implies green-CI"
  is the goal the single `verify` command serves, not an absolute guarantee.
- **I8 — One structure per concept; dependencies point at contracts.** Every
  concept has one defining type in one layer. L0 owns contracts; L1 implements
  them; L2 depends on L0 contracts only (never concrete L1 modules); L4 constructs
  and injects L1 implementations. Enforced by import-linter in CI.
- **I9 — Agents are the first-class user.** Machine-shaped surfaces: bounded,
  pageable, detail by reference; self-describing, itemized, repairable errors;
  discoverable by introspection; idempotency keys on every mutating API call;
  humans participate through the same contracts; human renderings are derived.
- **I10 — Complexity composes; definitions propagate.** Composite over monolith;
  build from the highest existing component that fits; define once, reference by
  name; immutable retained versions; bare references late-bind at run start to the
  `stable` channel (registration alone never propagates); per-run pinned
  resolution under one `world_hash`; `rdeps` answers impact before change.
- **I11 — One connector; magnetic, deterministic, *compiled* binding.** Ports are
  nominal-typed; a single connector per node pair; resolution rules (below) run at
  admission and emit explicit bindings into the ExecutionManifest; zero or multiple
  candidates is an itemized error with a per-port override; adding a candidate can
  fail validation but can never silently rebind.
- **I12 — Learning produces candidates, never mutations.** A running component
  cannot rewrite itself, its evaluator, or its current resolution. Learning
  produces a new immutable child version with recorded lineage; the candidate is
  evaluated against a pinned baseline, frozen evidence, and an independently
  defined promotion policy; only deterministic code may promote it, and promotion
  affects future runs only. Corollary: **the learner cannot define its own exam** —
  a component's evaluator, promotion policy, and evaluation set are never among
  the surfaces it is permitted to change, inspect beyond their public contract, or
  select for itself.
- **I13 — Intent compiles; execution is sealed** (the capstone). Authoring
  surfaces may be implicit, magnetic, and compositional, but validation compiles
  them into one immutable ExecutionManifest. Every invocation has one stable
  ExecutionPath. Authority is granted through scoped capability leases. Every
  external state transition is an idempotent effect producing a receipt. New
  definitions influence future runs only through explicit promotion.

**The conceptual kernel** — almost every concept reduces to four nouns:
**Definition** (what may be reused) · **Manifest** (what this run will execute) ·
**Invocation** (where one execution occurred) · **Receipt** (what changed outside
the run). Everything else is a policy that transforms or admits these, a transport
carrying them, a projection rendering them, or a capability leased to execute them.

### II.2 Layers and ladders

```
L4  api        system object · MCP server (v1 front door) · CLI skin · injection
               root: constructs L1 implementations and hands them to L2
L3  sdk        @task, combinators, component/harness registration — sugar
               compiling to L2 IR; stdlib patterns (panel, build-loop) are
               registered components
L2  runtime    Graph IR · registry/resolution · validator → ExecutionManifest ·
               walker (with concurrency admission, leases, finalization) ·
               resume/effects · budget            [depends on L0 contracts only]
L1  substrate  workspace · executors · gates · channels · journal
               [implement L0 contracts; constructed at L4, injected into L2]
L0  core       every contract in the system, defined once
```

Two ladders, one word deliberately split: code layers depend downward on contracts
(I8); the component ladder — atomic → composite, with component/harness/workflow as
*roles* — composes upward (I10). Authoring starts at the highest component that
fits; same-role composition is legal; cycles and upward references are not.
