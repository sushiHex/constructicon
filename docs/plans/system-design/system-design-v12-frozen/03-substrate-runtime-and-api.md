### II.4 L1 — substrate

- **workspace/** — concrete class (protocol extracted when a second consumer
  exists, I6; `FakeWorkspace` is the test double). WRITE = worktree lease created
  and finalized by the walker per its CapabilityLease lifetime — crash, cancellation, and
  parking included; discard is the default exit. **Merge rule: exact-merge-tree.**
  The workspace prepares the merge commit of candidate into the *current* base,
  gates run against that exact tree, and approval installs that exact commit; if
  the base has moved since minting, approval refuses and a new candidate is
  prepared and re-gated. Fast-forward is the degenerate case. `approve(attestation_id)`
  loads the Attestation from the journal and re-verifies against repository state;
  the resulting merge emits an EffectReceipt bound to the resulting commit.
  Threat model stated honestly: this stops fabricated *data* (an LLM-authored
  all-green result has no journal-minted attestation), not hostile in-process code.
- **executors/** — implement `Executor` with `describe()` (capability profile) and
  `validate_grants()` (pre-spawn rejection). **Isolation ladder (I1), floor
  first:** READ always gets a separate read-only snapshot checkout (no write
  permission, not the primary repo path), env allowlist, process-tree ownership
  and kill-tree; WRITE gets exactly the leased worktree plus designated temp dirs;
  where a backend has a real OS sandbox (Codex) it is pinned explicitly as depth;
  namespace/container isolation is the named upgrade, not the v1 floor. The
  **extraction contract** is first-class: raw reply → structured extraction →
  schema validation → bounded repair → typed envelope; the agent-node wrapper
  validates `output` against the declared port contract before any envelope is
  emitted. Implementations: Fake, ClaudeCode, Codex, Pi (vendored adapter logic,
  async-native, lessons kept as tests).
- **gates/** — `run_gates` *mints* an `Attestation(action="merge")` into the
  journal against the prepared merge tree; ships PytestGate + RuffGate; gate-first
  helpers (author the gate, prove it red at baseline) as stdlib components, not IR
  features. Promotion attestations (`action="promote"`) are minted the same way by
  the deterministic promotion-policy evaluator (I12).
- **channels/** — InProcess + Mailbox (vendored SQLite WAL mailbox: send/inbox/ack,
  lanes, bounded batches, history-as-recovery); message identities are
  invocation-id-derived and stable across retries.
- **journal/** — **SQLite is authoritative**: runs, events (seq allocation),
  checkpoints, jobs, proofs, approvals, effects in one transactional store; node
  completion commits checkpoint + event in one transaction. JSONL per run dir is
  an append-only projection regenerated or repaired from SQLite; artifacts and
  summary.json live beside it. "One WAL database" is the *transactional* story;
  git locks, subprocess ownership, and worktree cleanup are separate, named
  concurrency concerns. Optional OTel GenAI exporter reads the same events.

### II.5 L2 — runtime

- **Stores, split by lifecycle:** `ComponentRegistry` (immutable, persistent,
  versioned definitions; content-hash identity; namespaced names; `rdeps`;
  **channel-aware**: bare refs resolve to `stable`; registration appends an
  exact-hash version and never moves any pointer (the `candidate`/`canary`
  aliases arrive with M9); `promote(component, version,
  attestation_id)` re-reads the trusted attestation and verifies candidate/baseline/evaluator
  identity, evidence existence, mandatory checks, minimum evaluation count,
  promotion authority, and any required `ApprovalRecord` before moving a pointer;
  rollback is a pointer move emitting `ComponentRolledBack`),
  `CapabilityCatalog` (descriptors + grant vocabulary — what `system.describe()`
  exposes), `CapabilityContainer` (live, process-local injected instances;
  credentials and handles never serialized, never described).
- **Resolution** at run start: every Ref → exact version; full transitive
  resolution recorded under one `world_hash`; atomic world even if a component
  updates mid-resolution; reproduce refuses if installed implementation digests no
  longer match the record (I4: refuse over silently substituting).
- **Validator** → `ExecutionManifest`: refs resolve; boundary + node ports bind per
  the fixed rules into explicit `ResolvedPortBinding`s; loops well-formed
  (state/continue ports typed correctly); no cycles outside Loop; WRITE grants
  carry leases; grants only narrow. Itemized, per-fault, repair-naming errors.
- **Walker** — accepts only an ExecutionManifest. Fires a node when every input port's
  envelope is present; gathers verify their recorded producer set and terminate
  with a complete producer-status report when any producer is terminal — never
  wait forever. **Concurrency admission** (not a scheduler): semaphores for total
  nodes, per-executor, per-repository, and concurrent WRITE leases. **Failure
  propagation states**: failed · cancelled · lost · blocked-by-dependency ·
  skipped-run-terminated · parked. Lease finalization is walker-owned `finally`.
- **Resume** — re-walk; a completed checkpoint at the same ExecutionPath (+ input
  hash + resolved version) short-circuits; first
  miss resumes live. **Effects are at-least-once**: every externally mutating
  operation crosses the effect boundary with an idempotency key derived from
  (manifest_hash, path, kind, subject) and either honors it or
  journals a prepared→receipt EffectReceipt around execution; recovery
  reconciles `unknown` records before re-execution. Checkpoint forking is native
  for journaled computation and git-backed state; external effects remain subject
  to idempotency constraints.
- **Counterfactual runs** (I12) — `runs.counterfactual(source_run_id, overrides,
  effects="disabled")`: replay a historical run's pinned world with explicit
  component-version overrides only; READ posture by default; external effects
  faked or suppressed; discard-only worktrees where execution is needed; a normal
  journaled run recording parent run + override set. This is how a candidate is
  asked "what would have happened here if you had existed."
- **Run lifecycle** — `PENDING → RUNNING → {SUCCEEDED | FAILED | CANCELLED |
  PARKED}` with machine-readable PARKED reasons: awaiting_approval ·
  awaiting_advisor · policy_exhausted · budget_exhausted · operator_intervention.
  Node records: queued → running → {completed | failed | lost}.
- **Budget** — records usage/rate-limit/overage per run and executor; enforcement
  beyond loop policy and timeouts deferred, data flowing from day one.

### II.6 L3 sdk + L4 api

SDK combinators register components and compile to IR; ports derive from
signatures (parameters in, return out; no-param = source, `-> None` = sink).
Loop sugar is preserved — `loop(body, until=..., policy=...)` compiles to the
generic state-threading Loop plus a stdlib gate-check component producing
`IterationResult{state, continue_}`; triage-after-N and gate-repair are stdlib
composition, not IR (I10). `worktree_scope(...)` compiles to a WRITE capability
binding with an `instance`-lifetime lease — the same worktree across loop
iterations. Inline nested graphs are legal only as compiler intermediates or
ephemeral run roots; registration normalizes named nested graphs to Refs.

```python
claude_build = harness("myproj/claude-build-loop",
    loop(agent("claude", grants=WRITE, render=build_task),
         until=("pytest", "ruff"), policy=LoopPolicy(max_iterations=5)))
issue_to_pr   = flow("myproj/issue-to-pr", triage, "myproj/claude-build-loop", open_pr)
review_change = flow("myproj/review-change", "constructicon.std/frontier-review",
                     task(dedupe_findings), synthesize)
```

Agent authoring is primary: published schemas + `system.describe()` are the
complete authoring contract; validation errors are the repair loop. Humans plug in
as observer (event stream), advisor (mailbox channel endpoint), approver
(ApprovalRecord with authenticated actor; PARKED/awaiting_approval). The MCP
server is the v1 front door: `runs_start/status/events/cancel/resume/reproduce/
counterfactual/approve`, `graphs_validate/describe`, `system_describe`,
`registry_rdeps/versions/candidates/compare/promote/rollback`,
`experiences_query/describe`, `evaluations_status` — every mutation takes a caller
idempotency key; every response bounded, pageable, detail-by-reference (full
evaluation results stay by-reference, never dumped into a context window); stable
cursors; schema-versioned. CLI is a human skin.
