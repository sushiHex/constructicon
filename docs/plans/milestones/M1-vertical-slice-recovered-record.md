# M1 — the vertical slice (recovered implementation record)

> **Provenance:** The standalone M1 planning document was not recovered from the
> conversation archive. This historical record preserves the frozen M1 acceptance
> line from System Design v12 and the merged PR #1 implementation record. It is not
> a substitute for current `docs/ARCHITECTURE.md`, `docs/INVARIANTS.md`, or the
> accepted ADRs.

## Frozen milestone line

> **M1 — pure read-only slice:** minimal L0 wire types; in-memory registry with
> channel-aware resolution (bare ref → stable; register ≠ promote); explicit port
> binding; `ExecutionManifest`; `FakeExecutor`; simple DAG walker; authoritative
> journal; the fake effect boundary; one two-node read-only graph.
>
> **Accept — the vertical slice that must be beautiful:** Graph → validate →
> ExecutionManifest → FakeExecutor → checkpoint → idempotent effect →
> EffectReceipt → reproduce. If this path is elegant, the rest inherits it.

## Implemented slice

```text
Graph → validate → ExecutionManifest → FakeExecutor → checkpoint
      → idempotent effect → EffectReceipt → resume / reproduce
```

### Documentation: law separated from history

- `docs/INVARIANTS.md` — the thirteen invariants, four-noun conceptual kernel,
  dependency direction, and never list.
- `docs/ARCHITECTURE.md` — current truth: layers, three-construct graph IR,
  admission → sealed manifest, effect chain, registry/release model, journal,
  milestones, and the non-negotiable failure-test table.
- `docs/designs/SELF_IMPROVEMENT.md` — learning as candidates, never mutations.
- `docs/adr/0001–0008` — adjudication history by reference.
- `AGENTS.md` / `CLAUDE.md` — agent-first contributor guidance.

### L0 core

- one identity law: `digest(domain, schema_version, payload)` over canonical JSON;
- static `ScopePath` and dynamic `ExecutionPath` with one `invocation_id`;
- nominal ports with explicit cardinality and typed scoped `PortAddress`es;
- the graph IR: `Ref | Graph | Loop`;
- immutable `ComponentDef` versions and append-only `PromotionRecord`s;
- sealed `ExecutionManifest`, accepted as the walker's only input;
- `GrantRequest` → concrete `EffectiveGrants` plus `IsolationProfile`;
- discriminated executor outcomes sharing one truthful observation;
- `CheckResult` → journal-minted `Attestation` → `EffectReceipt`.

### L2 runtime

- channel-aware registry where registration never propagates and promotion
  requires a matching journal-minted attestation;
- magnetic port binding compiled into explicit resolved connections;
- composite flattening under distinct scopes;
- grants that only narrow;
- manifest-only walking, checkpoint resume, and an effect boundary that reconciles
  before re-execution.

### L1 substrate and L4 API

- authoritative SQLite journal;
- checkpoint and `NodeCompleted` committed in one transaction;
- credential-free `FakeExecutor` and fake effect adapter;
- `Constructicon` as the injection root.

## Acceptance proofs

1. Once validation returns, the walker never resolves a reference, searches for a
   port, inherits a grant, chooses a capability, interprets a selector string, or
   decides whether an effect is safe.
2. Once an effect returns a committed receipt, no replay, crash, or retry causes a
   second externally visible transition.

The merged PR also pinned these failure cases:

- a freshly registered candidate never resolves from a bare reference;
- caller-authored or subject-mismatched attestations cannot promote;
- a second compatible producer causes itemized ambiguity, never silent rebinding;
- resume restores checkpoints without re-invoking completed work;
- reproduce replays the sealed world without repeating an external transition;
- crash after external success and before receipt commit reconciles rather than
  repeats.

## Verification record

The M1 PR reported `uv run verify` green across Ruff, strict mypy,
import-linter, and 26 credential-free tests.

## Source record

- [Merged PR #1](https://github.com/sushiHex/constructicon/pull/1)
- Merge commit: `7431522269018c7a3b7b7d10528ad0f1354cea36`
