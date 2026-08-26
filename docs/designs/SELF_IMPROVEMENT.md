# Self-improvement — candidates, never mutations (I12)

The learning subsystem is ordinary userland composition; the kernel provides
only the enablers that already exist: stable-channel resolution, register ≠
promote, `runs.counterfactual` (M2+), and attestation-bound promotion. Nothing
here adds an IR construct, a parallel skill registry, or a second store.

## Three memories

- **Episodic** — the journal: exact resolutions, inputs/outputs, checks,
  failures, advice, approvals. Immutable history.
- **Semantic** — content-addressed `KnowledgeArtifact`s distilled from many
  runs (failure patterns, repo conventions, playbooks) with source-run
  provenance and redaction-policy versions. Retrieval is an ordinary component
  attaching artifacts to `TaskSpec.context`.
- **Procedural** — skills, which ARE `ComponentDef`s carrying an optional
  `LearningProfile` in their metadata (the profile participates in
  `content_hash`; lineage does not). `@skill(...)` is SDK sugar.

An *agent* is a harness binding an executor, grants, and skill refs — static,
inspectable composition. No dynamic model-invented skill dispatch; a later
router chooses among a finite, pre-granted, pre-resolved catalog only.

## The lifecycle

```
past runs
  → scoped experience selection      (capability-granted journal queries;
                                      never ambient access to history)
  → materialized ExperienceSet       (frozen, deduplicated, redacted,
                                      train/held-out split — "the last 100
                                      failures" is reproducible only if the
                                      exact 100 are frozen)
  → READ-only diagnosis              (typed, advisory)
  → candidate on a declared surface  (prompt/policy first; graph via the
                                      normal validator; code via WRITE
                                      worktree + gates; model artifacts later,
                                      training external)
  → registration as a candidate      (never propagates)
  → counterfactual replay            (baseline vs candidate on sealed held-out
                                      cases + the rdeps impact suite;
                                      effects disabled)
  → promotion attestation            (deterministic evaluator distinct from
                                      the proposer; thresholds applied by
                                      code; model judges contribute evidence,
                                      never the verdict)
  → canary → stable                  (stable initially behind ApprovalRecord;
                                      prompt-only surfaces may earn autonomy)
  → monitoring window                (regression moves the pointer back and
                                      the failed candidate becomes evidence)
```

## Role separation

Experience curator · diagnostician · proposer · evaluator · proof issuer
(deterministic) · promoter (registry effect) · human approver — each a distinct
grant. Code candidates are evaluated against the committed snapshot, never the
proposer's mutable worktree. A component's evaluator, promotion policy, and
evaluation set are never among its own change surfaces — **the learner cannot
define its own exam.**

## Honest limits

The "sealed" held-out set is sealed by capability grants and provenance
records, not cryptography — on a single-user system that is the real
guarantee, and it is stated as such (I4). Learning runs are triggered as
ordinary runs (manual, MCP, CI, external scheduler) — no internal autonomous
scheduler.

## Rollout

1. Prompt and context skills (M9) — no generated code execution, easy
   baseline/candidate comparison, cheap rollback.
2. Semantic knowledge artifacts.
3. Graph and harness learning (architect proposals through the normal
   validator; `rdeps` is the safety boundary).
4. Code skills (WRITE worktrees + gates + downstream replay + human stable
   approval).
5. Model adapters — versioned artifacts and executor capability identity;
   training stays outside the kernel.
