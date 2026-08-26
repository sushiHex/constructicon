# Architecture

Current truth only. The invariants live in [INVARIANTS.md](INVARIANTS.md);
history and adjudication live in [adr/](adr/); the self-improvement design
lives in [designs/SELF_IMPROVEMENT.md](designs/SELF_IMPROVEMENT.md).

Constructicon is an OS for agentic software-engineering pipelines. One authored
graph IR; one sealed `ExecutionManifest` per run; scoped capability leases;
journal-minted attestations; idempotent effects with receipts; component
versions that reach dependents only through explicit promotion. Agents are the
first-class user; humans are observer, advisor, and approver.

> Authored intent may be ergonomic; executed reality must be explicit.

## Layers

```
L4  api        system object · MCP server (front door, M6) · CLI skin ·
               injection root: constructs L1 implementations, hands them to L2
L3  sdk        @task, combinators, component/harness registration — sugar
               compiling to the L2 IR (arrives with M5)
L2  runtime    graph IR · registry/resolution · validator -> ExecutionManifest ·
               walker · resume/effects            [depends on L0 contracts only]
L1  substrate  workspace · executors · gates · channels · journal
L0  core       every contract in the system, defined once
```

Two ladders, deliberately distinct: code layers depend downward on contracts
(I8); the component ladder — functions → atomic nodes → components → harnesses
→ workflows — composes upward from simpler pieces (I10). Authoring starts at
the highest component that fits.

## The graph IR

Exactly three constructs, closed under composition:

- **`Ref`** — a namespaced name in the registry, never code. `version=None`
  resolves the `stable` channel at run start; `sha256:<hash>` pins exactly.
- **`Graph`** — composition; nests; declares typed boundary ports.
- **`Loop`** — generic feedback: a body, a `feedback` map (next input ←
  previous output), a typed `continue_from` decision, `max_iterations`. The
  kernel does not know what a gate is — gate checking, triage, and repair are
  ordinary registered components inside the body. A loop executes its body at
  least once, threads feedback into the next iteration, reads `continue_from`
  after each completed iteration, exports the final iteration's non-control
  outputs, and parks with `policy_exhausted` on exhaustion. (Executes at M4.)

Ports are nominal (`type_id` + schema hash + cardinality `one|optional|many`).
The magnetic rules, applied once at admission: exact name + exact type; else
unique exact type; `many` gathers every exact-type producer and records the
complete expected set; conversions require an explicit adapter component; zero
or multiple candidates is an itemized fault naming the per-port override.

## Admission → ExecutionManifest

Every authoring surface passes one validator. Its output is the sealed
manifest: resolved component versions (`ScopePath`-addressed, so nested
duplicates stay distinct), explicit resolved connections (typed `PortAddress`
endpoints — graph inputs, node ports, graph outputs), capability bindings with
fully concrete `EffectiveGrants` (no `None`, no `"inherit"` survives
admission; root inheritance is a fault), and three identities: `input_hash`,
`world_hash`, `manifest_hash`. Composites flatten at admission; boundary
renames never leak inner names.

**The walker accepts only an `ExecutionManifest`.** After validation it never
resolves a reference, searches for a port, inherits a grant, chooses a
capability, interprets a selector string, or decides whether an effect is safe.

Executors declare an `IsolationProfile`; admission rejects a live execution
whose executor cannot mechanically satisfy the requested posture — it never
degrades to "best effort".

## Identity

One law (`constructicon.core.identity`): every hash is a domain-separated
SHA-256 over canonical JSON — `digest(domain, schema_version, payload)`.
Digest fields never participate in their own payloads; idempotency keys are
computed, never caller-authored. A static `ScopePath` locates a definition
instance in the manifest; a dynamic `ExecutionPath` (scope + iteration frames)
locates one invocation; `invocation_id(run_id, path)` is the identity used by
envelopes, checkpoints, events, receipts, channels, cancellation, and API
references. One invocation, one address, everywhere.

## Effects

Evidence → authority → outcome, one mechanism for every externally visible
action:

```
CheckResult  →  Attestation  →  EffectReceipt
(observed)      (journal-minted authority        (what actually happened)
                 for THIS action on THIS subject)
```

A `Gate` is one producer of `CheckResult`s; a promotion evaluator is another.
Every effect adapter declares native idempotency or reconcilability; the
recovery law: prepared + no receipt → reconcile externally — found → record
receipt; absent → execute; indeterminate → park. Never blindly repeat an
unknown external effect. Idempotency keys derive from
`(manifest_hash, path, kind, subject)`.

Workspace merges follow the exact-merge-tree rule: gates run against the
prepared merge commit of candidate into the *current* base;
`merge_verified(attestation_id)` installs that exact commit or refuses if the
base moved. "Approval" is reserved for human discretion (`ApprovalRecord`).

## Registry and release

Registration appends an immutable exact-hash version and moves no pointer.
Bare references resolve `stable`; `promote(component, version, attestation_id)`
re-reads the journal-minted attestation, verifies subject identity and checks,
and appends a `PromotionRecord`; rollback is another pointer move; in-flight
runs keep their pinned resolution. A *candidate* is a query (any eligible
unpromoted version), never a channel. `rdeps(name)` answers what a change
touches before it is changed.

## Journal

One transactional log, many projections. SQLite (stdlib, WAL) is authoritative
for runs, events (per-run monotonic sequence), checkpoints, attestations, and
effect records; node completion commits checkpoint + event in one transaction.
JSONL, summaries, and renderings are regenerable projections (M2+). Resume
re-walks the graph: a checkpoint at the same `ExecutionPath` with matching
input hash and resolved version restores; the first miss resumes live.
Reproduce starts a new run under a past run's exact manifest and inputs.

One canonical `InvocationStatus` enum serves runtime, journal, API, and
renderings. Run lifecycle: `PENDING → RUNNING → {SUCCEEDED | FAILED |
CANCELLED | PARKED}` with machine-readable parked reasons.

## Milestones

- **M1 (done)** — the vertical slice: Graph → validate → ExecutionManifest →
  FakeExecutor → checkpoint → idempotent effect → EffectReceipt → reproduce;
  channel-aware resolution; SQLite journal; itemized admission faults.
- **M2 (done)** — crash & resume hardening: fenced run leases with continuous
  heartbeats; write-once durable facts; persistent registry with immutable
  snapshots and one activation path (start/resume/reproduce all refuse
  drift); fault probes at every completion/effect/transition boundary with a
  unit lane (`InjectedCrash`) and a real `os._exit` subprocess lane over a
  durable fake external world; cooperative cancellation; read-time liveness
  (never a persisted LOST); dependency blocking with complete
  `DependencyReport`s; canonical JSONL/summary projections; `user_version`
  schema migration from M1.
- **M3** — git authority: read-only snapshots, WRITE worktree leases,
  Pytest/Ruff gates, exact-merge-tree attestations, discard-on-failure.
- **M4** — generic bounded loops with iteration identities and PARKED reasons.
- **M5** — SDK combinators; `system.describe()`; architect-proposed graph
  admission; agent-repairable errors end-to-end.
- **M6** — MCP control plane with idempotency keys and bounded pagination.
- **M7** — channels (InProcess + Mailbox over the journal) and the panel
  pattern; human advisor and approval round trips.
- **M8** — live CLI executors (ClaudeCode, Codex, Pi) once isolation profiles
  are enforceable; recorded-transcript contract suites.
- **M9** — self-improvement phase 1 (prompt/context skills); see
  [designs/SELF_IMPROVEMENT.md](designs/SELF_IMPROVEMENT.md).

## Non-negotiable failure tests

| Area | Required failure test |
| --- | --- |
| Registry | Component updates during run-start resolution → one atomic world |
| Channels | A freshly registered candidate never resolves from a bare reference |
| Promotion | Mismatched subject identity or missing evidence → refused |
| Port binding | A second compatible producer → itemized ambiguity error, never a rebind |
| Nested graphs | Reused local node ids stay distinct via scope paths |
| Journal | Crash between event and checkpoint → recoverable, truthful state |
| Effects | Crash after external success, before receipt → reconcile, no duplicate |
| Git proof | Base moves after gates pass → refused or revalidated (M3) |
| Forgery | A caller-authored all-green result cannot authorize any effect |
| READ isolation | Shell writes fail physically, or the executor is inadmissible (M3/M8) |
| Gather | One producer fails → complete producer-status report, never a hang (M2) |
| MCP | Retried mutation with the same idempotency key → one run (M6) |
| Telemetry | Damaged executor output never reports clean success |
| Reproduction | Installed code differs from recorded digest → refuse (M2) |
| Rollback | Both versions and all evidence retained; in-flight runs keep pins |
