# Constructicon — System Design (v12 — architecture frozen; next act is M1)

## Context

Constructicon is an OS for agentic software-engineering pipelines: simple and
advanced system graphs from one IR; an SDK (authoring) and API (control); easy for
its first-class user — agents — to build in, operate, and contribute to; elegant,
layered, modular in code and graph; no duplicated structure; everything versioned at
the component level. Humans are secondary: observer, advisor, approver.

Inputs: brainstorm doc; seven argued positions (three rounds); two vendoring
sources — sushiHex/hardline-mcp (subscription-CLI adapters, SQLite mailbox, at
/home/user/sushihex/hardline-mcp) and disler/fusion-harness (multi-model
panel/debate/fusion/delegation topologies, at /home/user/disler/fusion-harness);
and an external "Plan review" (ChatGPT) whose findings were adjudicated in round 9 —
adopted where they made the invariants mechanically true (the sealed manifest, boundary
port addresses, generic loops, journal-minted proofs, effect idempotency,
SQLite-authoritative journal, physical READ isolation, nominal port typing,
execution-path identity, typed executor outcomes), calibrated where noted in the
decision log.

## Part I — Decision log

1. **One graph IR; one admission boundary.** SDK combinators, hand-authored JSON,
   and architect-proposed graphs all compile to the same `Graph` and pass one
   validator. The validator's output is a first-class **`ExecutionManifest`** —
   the compiled, sealed result of resolution and admission: executable, lockfile,
   and deployment manifest in one immutable object. The authored Graph remains the
   single workflow language; the manifest is not a second language, it is the
   pinned, bound, hashed form of the same graph, and the walker accepts nothing
   else. **Authored intent may be ergonomic; executed reality must be explicit.**
2. **Executor seam** (user's words): "all models whether subscription or API fit the
   same data model schema; interchangeable as nodes/plugs" — qualified per review:
   executors are substitutable where their declared **capability profile**
   (structured-output reliability, tools, context, posture, streaming, accepted
   model/effort vocabulary) satisfies the node's contract; `Executor.describe()` and
   `validate_grants()` make the check mechanical and pre-spawn. No completion-level
   provider layer, ever.
3. **Workspace**: git worktree lease per WRITE binding; journal-minted, base-aware
   gate proofs; merge = install of an exactly-tested merge tree; discard-by-default.
4. **hardline-mcp / fusion-harness**: vendor the patterns, async-native, with a
   concrete provenance record (upstream revision, MIT license notices, files-copied
   vs ideas-reimplemented, update procedure).
5. **Channels v1**: typed InProcess + Mailbox transports; panel as a stdlib
   component; debate/fusion-ACK later.
6. **Journal**: SQLite is authoritative and transactional (runs, events,
   checkpoints, jobs, proofs, effects); JSONL per run dir is a regenerable
   projection; OTel GenAI exporter optional. Resume = re-walk skipping
   checkpointed execution keys; external effects are at-least-once bounded by
   idempotency records (never assumed exactly-once).
7. **First workflows**: issue→PR (terminal effect: open a PR from the approved run
   branch; merges *into the run branch* carry gate proofs; the PR to the default
   branch is where human approval lives) + multi-model review panel.
8. **Never**: LLM watchdogs, completion-level provider interface, CloudEvents
   internally, a second scheduler (bounded-concurrency admission inside the walker
   is not a scheduler), a generic internal event bus, a second workflow
   representation, mutable component definitions. Python ≥ 3.11.
9. **Agents are the first-class user** (I9): MCP is the v1 control surface with
   idempotency keys on every mutation; architect-proposed graphs are a primary
   authoring path; humans enter as observer / advisor / approver only; bounded,
   pageable, by-reference responses; AGENTS.md + one `verify` command.
10. **Composition with reference semantics** (I10): definitions once, referenced by
    name, immutable versions retained forever; a bare reference late-binds at run
    start **to the component's `stable` channel — never to the latest registered
    version** (amended in round 10: registration ≠ promotion, see decision 13);
    reproducible = versioned at the component level; `rdeps` before change.
    Mechanical distinction is **atomic vs composite**; component/harness/workflow
    are semantic roles with validation policies, not a rigid type ladder — same-tier
    composition is legal, upward references and cycles are not.
11. **Single-connector wiring, magnetic ports** (I11): zero-or-more typed ports per
    node; one connector per modular connection; binding resolved deterministically
    at validation into explicit `ResolvedPortBinding`s — **nominal** typing
    (`type_id` + schema hash), no general JSON-Schema subsumption; ambiguity is an
    itemized error, never a guess; the walker never searches for ports at runtime.
12. **Review adjudication (round 9).** Adopted: items 1–11 of the external review,
    its operational-semantics section, milestone reordering, and failure-test
    table. Calibrated: (a) Milestone 0's "semantic addendum" is *this document* —
    the open choices it demanded are decided here (merge rule = exact-merge-tree;
    resource scopes = leases on capability bindings, not a fourth IR construct;
    journal = SQLite-authoritative; port typing = nominal; loops = generic state
    threading with SDK sugar); (b) READ isolation is specified as an enforcement
    ladder with the honest floor stated, not a kernel-namespace mandate for v1;
    (c) proof security is scoped to its real threat model: LLM-fabricated data
    moving through legitimate channels — not malicious in-process Python, which no
    in-process design can stop; (d) I6 is rewritten (see II.1) rather than
    inconsistently applied.
13. **Self-improvement: candidates, never mutations (round 10, invariant I12).**
    A skill is a `ComponentDef`; an agent is a harness binding executor + grants +
    skills; a learner is an ordinary workflow that proposes a new immutable child
    version; learning happens when deterministic evaluation *promotes* that
    candidate for future runs. The registry gains **release channels**
    (`candidate` / `canary` / `stable`; bare ref = stable) with append-only
    `PromotionRecord`s — rollback is a pointer move, in-flight runs keep their
    pins. Proofs generalize into one effect chain — GateCheck (evidence) →
    `Attestation` (authority) → `EffectReceipt` (outcome) — with typed subjects
    (git merge | component promotion) instead of parallel proof systems. Memory splits three
    ways: episodic (the journal, exists), semantic (content-addressed
    `KnowledgeArtifact`s with provenance), procedural (skills). Placement
    discipline: the four kernel enablers — stable-channel resolution,
    register≠promote, `runs.counterfactual` (overrides, effects disabled),
    proof-bound promotion — land inside the core milestones; the learning
    pipeline itself (curation, diagnosis, evaluation, promotion policies) is
    userland composition, staged as M9 phases (prompt skills first, then semantic
    knowledge, graph, code, model adapters). No new IR construct, no parallel
    skill registry, no vector store before structured journal-derived experience
    proves insufficient, no dynamic model-named skill dispatch in v1.
14. **Final compression (round 11), under one principle: "authored intent may be
    ergonomic; executed reality must be explicit."** Adjudication of the
    seven-change review (written against v6; four of its seven were already
    present since v9/v10 — explicit boundary addresses, generic loops, nominal
    typing, register≠promote, registry/container split, SQLite-authoritative
    journal). Genuine deltas adopted: `ExecutableGraph` renamed **ExecutionManifest**
    with `input_hash`/`world_hash`/`manifest_hash`; `ExecutionKey` compressed into
    one hierarchical **ExecutionPath** (string/int segments, derived
    invocation_id — one invocation, one address, everywhere); the effect chain
    named **GateCheck → Attestation → EffectReceipt** with `EffectRequest`
    idempotency derived from (manifest, path, kind, subject); **CapabilityLease**
    generalized from worktrees to every capability; Port gains explicit
    `cardinality`; Loop generalizes to a `feedback` map + `continue_from`;
    channels simplified for v1 to exact-hash + `stable` (candidate/canary aliases
    land with M9); capstone invariant **I13** and the four-noun conceptual kernel
    added. With this, architecture planning freezes: the next act is M1's
    vertical slice.
