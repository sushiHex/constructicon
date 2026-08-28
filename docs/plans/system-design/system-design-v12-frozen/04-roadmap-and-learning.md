### II.7 Repository, policy, and hygiene

Layout as before (src/constructicon/{core,substrate,runtime,sdk,api}, tests
mirroring layers + e2e, examples as executed docs, docs/ARCHITECTURE+INVARIANTS+
CONTRIBUTING, AGENTS.md+CLAUDE.md, uv + ruff + mypy --strict + import-linter +
pytest; single `uv run verify`). Additions this round:

- **Namespaces now**: `constructicon.std/…`, `<project>/…`, `<vendor.pkg>/…` —
  cheap now, expensive to retrofit.
- **Schema evolution is public API**: versions on graph IR, journal events, MCP
  requests/responses, component contracts, SQLite schemas; documented
  compatibility policy (Pydantic gives schemas, not policy).
- **Vendoring provenance**: recorded upstream revisions (hardline-mcp @6d1187a,
  fusion-harness @01a3482), MIT license verification + preserved notices,
  files-copied vs ideas-reimplemented manifest, local-modification log, repeatable
  update procedure.
- **Retention ownership** (GC deferred, rules named): component versions are
  logically immutable — archival compacts storage, never deletes identity; crashed
  worktrees are reaped by lost-detection sweep; PARKED worktrees are retained
  until their run terminates; artifact size caps with by-reference overflow; DB
  migration + backup procedure versioned with the schema.
- **Dependency budget** (enforced): kernel = stdlib + Pydantic only (import-linter
  fails the PR otherwise); `[mcp]`, `[otel]` extras; SQLite is stdlib; git and
  agent CLIs are environment requirements; YAML/CloudEvents/HTTP-in-core cut.

### II.8 Build milestones (M0 resolved by this document)

- **M0 — semantic decisions**: boundary addresses, ExecutionManifest, ExecutionPath,
  generic loop, lease lifetimes, exact-merge-tree proofs, SQLite-authoritative
  journal, effect idempotency — *decided above; remaining details land as short
  ADRs in docs/ as implementation surfaces them.*
- **M1 — pure read-only slice**: minimal L0 wire types; in-memory registry with
  **channel-aware resolution** (bare ref → stable; register ≠ promote, the I12
  enabler that must exist before any agent registers anything); explicit port
  binding; ExecutionManifest; FakeExecutor; simple DAG walker; authoritative
  journal; the fake effect boundary; one two-node read-only graph.
  *Accept — the vertical slice that must be beautiful:* Graph → validate →
  ExecutionManifest → FakeExecutor → checkpoint → idempotent effect →
  EffectReceipt → reproduce. If this path is elegant, the rest inherits it.
- **M2 — crash & resume**: persistent SQLite registry/journal; ExecutionPath
  checkpoints; input/execution hashing; fault injection at every completion
  boundary; cancellation + lost detection.
  *Accept:* scripted kills anywhere lose no completed computation and never
  misidentify instances.
- **M3 — git authority & proofs**: read-only snapshots; WRITE leases;
  Pytest/Ruff gates; journal-minted proofs; exact-merge-tree approval;
  discard-on-failure.
  *Accept:* no fabricated proof, moved base, failed gate, or agent-authored git
  command yields an unverified merge.
- **M4 — generic bounded loops**: state threading; iteration identities; stdlib
  gate-check + repair components; exhaustion → PARKED with reason.
  *Accept:* build → red → repair → green → approved effect, with interruption and
  resume inside every iteration.
- **M5 — authoring & introspection** (early, because agents are primary authors):
  SDK combinators; direct Graph JSON; `system.describe()`; architect-proposed
  admission; itemized repair errors.
  *Accept:* an agent using only schemas, describe, and errors authors and repairs
  a valid read-only graph.
- **M6 — MCP control plane**: authenticated actors; idempotency keys; bounded
  pagination, stable cursors; detail references; conflict errors; registry
  promote/rollback and `runs_counterfactual` exposed with the same idempotency
  discipline.
  *Accept:* every mutating request retried after simulated response loss creates
  no duplicate runs, approvals, or promotions.
- **M7 — channels & panel**: InProcess + Mailbox; durable message identities;
  ack/recovery; panel; human advisor; approval round trips.
- **M8 — live CLI executors** (only after isolation works): ClaudeCode, then
  Codex, then Pi, through one executor contract suite — transcripts covering
  timeout-mid-output, corrupt records, kill-tree cancellation, wrong served-model
  reporting, tool-grant rejection, attempted filesystem escape.
- **M9 — self-improvement, phase 1 (prompt/context skills)**: experience query +
  materialization (scoped grants, deterministic redaction, frozen ExperienceSet);
  stdlib diagnostician/proposer/evaluator components; counterfactual replay of
  held-out cases + rdeps impact suite; promotion proofs; candidate → canary
  automatic on offline evaluation, canary → stable behind an ApprovalRecord.
  *Accept:* a triage-skill learner improves a prompt surface from real journal
  history, the candidate beats baseline on sealed held-out cases without
  downstream regression, is promoted by proof, and a forced regression rolls the
  pointer back with both versions and all evidence retained.

### II.9 Non-negotiable failure tests

| Area | Required failure test |
|---|---|
| Registry | Component updates during run-start resolution → run still gets one atomic world |
| Port binding | Second compatible upstream output → itemized ambiguity error, never silent rebind |
| Nested graphs | Reused internal node IDs stay distinct via instance paths |
| Loop resume | Crash in attempt 3 resumes attempt 3; never reuses attempt 2's checkpoint |
| Journal | Crash between event and checkpoint → recoverable, truthful state |
| Effects | Crash after external success, before checkpoint → no duplicate effect |
| Git proof | Base moves after gates pass → approval refused or revalidated |
| Gate forgery | Caller-constructed all-green result cannot authorize a merge |
| READ isolation | Read agent's shell writes (inside and outside repo) fail physically |
| WRITE isolation | Write agent cannot touch parent repo or another run's worktree |
| Gather | One producer fails → consumer terminates with complete producer-status report |
| MCP | Retried `runs_start` with same idempotency key → one run |
| Telemetry | Damaged executor output never reports clean success |
| Reproduction | Installed code differs from recorded digest → refuse, never substitute |
| Channels | A freshly registered candidate never resolves from a bare reference |
| Promotion | Mismatched baseline/evaluator identity or missing evidence → promotion refused |
| Learning authority | A candidate touching its own evaluator or promotion policy fails validation |
| Counterfactual | A counterfactual run performs zero external effects; parent + overrides recorded |
| Rollback | Rollback retains both versions and all evidence; in-flight runs keep their pins |

### II.10 Self-improvement (I12) — the learning subsystem

**Three memories.** Episodic = the journal (exists; immutable history). Semantic =
content-addressed `KnowledgeArtifact`s distilled from many runs (failure patterns,
repo conventions, playbooks) with source-run provenance, curator version, and
redaction-policy version — retrieval is an ordinary component attaching artifacts
to `TaskSpec.context`. Procedural = **skills, which are ComponentDefs** — no
parallel skill registry, no `SkillDef`; `@skill(...)` is pure SDK sugar attaching a
`LearningProfile` to component metadata; an *agent* is a harness binding an
executor, grants, and skill Refs (static, inspectable composition — no dynamic
model-invented skill dispatch in v1; a later router chooses among a finite,
pre-granted, pre-resolved catalog only).

**The lifecycle** (an ordinary registered workflow, `Ref | Graph | Loop` inside):
past runs → scoped experience selection (`ExperienceQuery` under a capability
grant limiting repos, components, event categories, run counts, and redaction
policy — never ambient journal access) → materialized immutable `ExperienceSet`
(deterministic secret/PII removal, dedup, contamination checks, train/held-out
split; "the last 100 failures" is only reproducible if the exact 100 are frozen)
→ READ-only diagnosis (typed `SkillDiagnosis`, advisory) → candidate on a declared
change surface (prompt/policy first; graph via the normal validator; code via
WRITE worktree + gates; model artifacts later, training external) → registration
**as candidate** (never propagates) → counterfactual replay of baseline vs
candidate on sealed held-out cases plus the `rdeps`-derived impact suite (a better
triage must not degrade issue-to-pr) → deterministic promotion-policy evaluator
mints `Attestation(action="promote")` (evaluator distinct from proposer, both
sides pinned, symmetric evaluation, thresholds applied by code — model judges
contribute evidence, never the final verdict) → candidate → canary (automatic on
offline proof) → stable (initially behind `ApprovalRecord`; prompt-only surfaces
may earn autonomy) → monitoring window; regression moves the pointer back,
emits `ComponentRolledBack`, and the failed candidate becomes new evidence.

**Role separation** (each a distinct grant): experience curator · diagnostician ·
proposer · evaluator · proof issuer (deterministic) · promoter (registry effect) ·
human approver. Code candidates are evaluated against the committed snapshot,
never the proposer's mutable worktree. A component's evaluator and promotion
policy are never among its own change surfaces (I12 corollary).

**Journal event additions** (same union): ExperienceSelected/Materialized,
CandidateProposed/Registered, EvaluationStarted/Completed, PromotionProofIssued,
ComponentPromoted/PromotionRejected/RolledBack.

**Honest limits**: the "sealed" held-out set is sealed by capability grants and
provenance records, not cryptography — on a single-user system that is the real
guarantee, and it is stated as such (I4). No new learning database: journal +
artifacts + registry storage carry everything until a second real store exists
(I6). Learning runs are triggered as ordinary runs (manual, MCP, CI, external
scheduler) — no internal autonomous scheduler.

## Deferred, with named triggers

HTTP skin (first non-MCP consumer) · entry points (first out-of-tree package) ·
debate/fusion-ACK patterns (first adversarial-rounds workflow) · budget
enforcement (first starved window) · executors beyond Pi / local models (when
local weights arrive) · distributed/durable backend — wrap Temporal, don't rebuild
(outgrowing one machine) · garbage collection (rules named above, collection
deferred) · learning phases 2–5 — semantic knowledge curation, graph/harness
learning, code skills, model adapters (each gated on the prior phase's evaluation
system proving itself) · skill router over a finite pre-granted catalog (after
static skill composition ships) · live canary traffic splitting (canary starts as
an explicit alias for designated validation workflows) · vector/embedding store
(only if structured journal-derived experience proves insufficient).
