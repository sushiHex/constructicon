# 0017 — Panel membership is an authored map

**Status:** accepted (M7.1), 2026-09-06 — rev 4 approved and PR #22 merged

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

Panel gather membership is represented by explicit port maps, not inferred
from connection liveness or topology.

Several connections may map one destination of cardinality `many`. Distinct
selectors form an ordered union in graph connection order; repeating the same
selector coalesces at its first position. A destination of cardinality `one` or
`optional` admits exactly one distinct selector. A mapped destination replaces
the magnetic pool, while an unmapped port keeps the existing binding rules.
Within each connection, map entries are visited in lexical destination-port
order because JSON-object insertion order is not semantic. Canonically identical
Graphs therefore cannot disagree on ordered or truncated faults.

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

`panel()` has at least two members and writes one map per member to its single
gather port. Its member request and result contracts must differ, and the
gather must be the aggregator's only input carrying the member-result contract.
These are truthful authoring-shape rules, independent of the magnetic pool. A
one-seat workflow composes the member directly; it does not invent metadata or
a sentinel edge to make one selector prove a `many` boundary.

Because the map's published `node.port` selector form splits at its first dot,
`panel()` refuses a member node id containing `.` before constructing a Graph.
It also refuses an empty member result-port name, which would leave the selector
without a port segment. It does not escape or reinterpret an otherwise valid
general `NodeId` or `Port`.

This decision seals each member's mapped result port, not its complete output
boundary or its request routing. The SDK checks that the supplied bundles share
one exact boundary, but the emitted Graph retains only the result-port map.
Magnetic binding therefore remains authoritative for the request at admission.
A request selector alone would be insufficient: it cannot distinguish a
destination changing from `one` to `optional` or `many`. An unrelated output
added to a later member version is likewise outside the map's claim. `Ref.bind`
remains capability binding and is not repurposed as a second data-binding
language.

The Graph wire shape does not change, so Graph remains schema 1. An older
validator rejects the newly lawful multi-map shape and therefore fails closed.
The scalar-source correction is likewise an admission-law change over the
existing wire shape, not a retained-byte migration; retained definitions are
inventoried before implementation and never rewritten.
Truthful introspection does change: `SystemDescription` advances to schema 2
and `BindingVocabulary` separately publishes
`explicit_map_source_cardinality="one"` and
`mapped_many_policy="ordered_scalar_selector_union_replaces_pool"`. The first
law applies to every explicit map; the second applies only to mapped `many`
fan-in. The description digest advances to domain version 2. The embedded Graph
and admission schema documents retain their own version 1.

The exact gather-membership guarantee applies only to graphs that carry maps.
Retained pre-change panels remain unmapped. They are neither rewritten nor
granted an authored claim they never recorded.

Counterfactual admission separates baseline validity from override
compatibility. It first validates the exact retained source graph under the
source manifest's resolved-version lock. Baseline failure is `REQUEST_INVALID`
and names reproduce-or-reauthor repair. Only after that proof succeeds are
exact overrides applied; a failure there is
`COUNTERFACTUAL_LOCK_MISMATCH`. `runs_reproduce` continues to execute the
retained manifest without re-admitting it.

The exact lock governs preflight and compilation through one version-selection
rule. Neither phase may consult current stable when a pin exists, so a promotion
after the source run cannot substitute another definition during baseline or
override admission. Compilation remains responsible for lock faults and pin
accounting.

After override admission, every affected scope's final
`ComponentResolution.contract_hash` must equal the corresponding source
record's complete contract hash. Graph compatibility at the ports it consumes
is not enough: an added unrelated output or optional input is still a
contract-incompatible counterfactual. A mismatch uses the existing
`COUNTERFACTUAL_LOCK_MISMATCH` and writes no run plan.

## Consequences

- A newly authored panel's source Graph and manifest identity change because
  its connections now carry membership maps. Retained runs do not change.
- `panel()` is plural. Zero and one member are refused; direct composition is
  the one-seat spelling.
- Undrifted mapped fan-in produces the same resolved binding bytes and source
  order as the prior unmapped panel.
- A mapped member result port's contract or cardinality drift, aggregator gather
  drift, an unused map destination, and an unknown endpoint fail during
  admission. An unrelated added member output is outside the authored map.
- Member request compatibility remains an authoring-time SDK proof. Later
  request-boundary drift may bind magnetically and is outside this decision's
  exactness guarantee.
- Bystanders, graph inputs, and transitive helpers cannot widen a mapped panel.
  They retain their documented behavior at an unmapped `many` port.
- Counterfactual replay re-proves current baseline validity before override
  compatibility. A pre-change retained panel keeps its historical limitation;
  a source graph invalid under a newer admission law is refused honestly rather
  than being mislabeled as an override mismatch.
- A successful override compilation still must preserve the complete source
  contract hash at every affected scope; unused boundary drift fails closed.
- Admission rejection follows the existing command law: an exact key retry
  replays, while a repaired attempt uses a fresh key.
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
- **Adding expected destination cardinality to Graph for one-member panels.**
  It adds a second boundary declaration solely to preserve a degenerate sugar
  case. A panel is plural; one member already composes directly.
- **Duplicating a one-member selector as a cardinality sentinel.** Identical
  selectors coalesce by law, while making duplicates significant would turn
  topology noise into execution semantics.
- **Calling a `$input` request selector an exact member boundary.** It catches a
  nominal request change but still admits destination-cardinality drift, so it
  would replace one overclaim with another.
- **Pinning member versions in `panel()`.** It prevents compatible promoted
  implementations from reaching future runs rather than re-proving their
  boundary, changing dependency propagation to avoid representing the claim.
- **Adding an expected member boundary to Graph in M7.1.** That may be the shape
  of a future general late-bound-reference contract, but it is a versioned IR
  decision with consumers beyond panels. It is not smuggled into a scoped
  gather-membership correction.
- **Ignoring unused map destinations.** A component rename would erase an
  authored constraint and admit a graph different from the one requested.
- **Retrofitting maps into retained panels.** It changes immutable source bytes
  and manufactures historical author intent.
- **Grandfathering retained source graphs during counterfactual admission.** A
  caller may supply a resolution lock, so treating it as migration authority
  would let caller-shaped evidence bypass current validation. Baseline-first
  admission reports incompatibility without rewriting history.
- **Bumping Graph solely for the new semantics.** There is no new wire shape,
  and old validators already fail closed on the new combination.
- **Leaving `SystemDescription` at schema 1.** Its strict readers would either
  reject an unexplained additive field or, if loosened, miss a law required to
  author valid graphs. The version boundary should say so explicitly.
