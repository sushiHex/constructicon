# 0017 — Panel membership is an authored map

**Status:** proposed (M7.1) — acceptance gates implementation

## Context

`panel()` proves that each member has one request and one result and that the
aggregator gathers the result contract. It then emits plain connections. The
validator's unmapped `many` binding gathers every nominally compatible source
in the transitive upstream pool, so the admitted Graph contains no durable
statement that those particular members are the panel.

If a member resolves to a version with a different result contract, its output
can vanish from the gather without a fault. A general connector-liveness rule
does not solve this: valid connections may expose transitive sources without
binding their own outputs, explicit maps intentionally redirect a connection's
value, and liveness at a node cannot prove membership at one port. Scoping every
`many` pool to direct connections would break composite boundaries and change
the documented graph language.

`Connection.map` already expresses the missing claim: a destination input is
filled by a named selector. The current validator, however, rejects several
connections mapping the same destination, silently ignores a map destination
absent from the resolved component boundary, and compares a selected source by
nominal identity without its cardinality.

## Decision

Panel membership is represented by explicit port maps, not inferred from
connection liveness or topology.

Several connections may map one destination of cardinality `many`. Distinct
selectors form an ordered union in graph connection order; repeating the same
selector coalesces at its first position. A destination of cardinality `one` or
`optional` admits exactly one distinct selector. A mapped destination replaces
the magnetic pool, while an unmapped port keeps the existing binding rules.

Every explicit selector must resolve to exactly one source whose source port
has cardinality `one`, then match the destination's nominal contract. A `many`
destination is a fan-in of scalar producers; it does not flatten a `many` or
`optional` producer. This deliberately rejects an accidentally admitted
single-selector shape whose flattening and absence semantics were never
defined; authors compose a scalar adapter instead.

Every connection endpoint and every map destination is validated. An absent
node or a destination port absent from the resolved boundary is a
`graph.contract.invalid` refusal with an exact framed coordinate. A selector or
source-cardinality mismatch is the existing `graph.port.contract_mismatch`.
No explicit entry is silently discarded.

`panel()` writes one map per member to its single gather port. Its member
request and result contracts must differ, and the gather must be the
aggregator's only input carrying the member-result contract. These are truthful
authoring-shape rules, independent of the magnetic pool.

The Graph wire shape does not change, so Graph remains schema 1. An older
validator rejects the newly lawful multi-map shape and therefore fails closed.
The scalar-source correction is likewise an admission-law change over the
existing wire shape, not a retained-byte migration; retained definitions are
inventoried before implementation and never rewritten.
Truthful introspection does change: `SystemDescription` advances to schema 2
and `BindingVocabulary` publishes
`mapped_many_policy="ordered_scalar_selector_union_replaces_pool"`. Its
description digest advances to domain version 2. The embedded Graph and
admission schema documents retain their own version 1.

The exact-membership guarantee applies only to graphs that carry maps. Retained
pre-change panels remain unmapped. They are neither rewritten nor granted an
authored claim they never recorded.

## Consequences

- A newly authored panel's source Graph and manifest identity change because
  its connections now carry membership maps. Retained runs do not change.
- Undrifted mapped fan-in produces the same resolved binding bytes and source
  order as the prior unmapped panel.
- Member contract or cardinality drift, aggregator gather drift, an unused map
  destination, and an unknown endpoint fail during admission.
- Bystanders, graph inputs, and transitive helpers cannot widen a mapped panel.
  They retain their documented behavior at an unmapped `many` port.
- Counterfactual replay re-proves membership for mapped source graphs. A
  pre-change retained panel keeps its historical limitation.
- Strict schema-1 `SystemDescription` readers reject schema 2 instead of
  silently ignoring a new binding law.
- The walker, execution manifest shape, admission code set, fault model, and
  SQLite schema are unchanged.

## Rejected alternatives

- **General connector liveness.** It rejects valid transitive and explicitly
  mapped graphs and still reasons at the node rather than the claimed port.
- **Scoping every `many` pool to direct predecessors.** It breaks composite and
  Loop boundary behavior and changes all hand-authored gathers.
- **Inferring panel seats from topology at admission.** The Graph does not label
  a connection as a seat; inference would be a second hidden workflow language.
- **Flattening `many` sources.** It erases the one-seat/one-answer boundary and
  makes source cardinality drift look compatible.
- **Ignoring unused map destinations.** A component rename would erase an
  authored constraint and admit a graph different from the one requested.
- **Retrofitting maps into retained panels.** It changes immutable source bytes
  and manufactures historical author intent.
- **Bumping Graph solely for the new semantics.** There is no new wire shape,
  and old validators already fail closed on the new combination.
- **Leaving `SystemDescription` at schema 1.** Its strict readers would either
  reject an unexplained additive field or, if loosened, miss a law required to
  author valid graphs. The version boundary should say so explicitly.
