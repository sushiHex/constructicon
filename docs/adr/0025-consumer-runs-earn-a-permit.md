# 0025 — Consumer runs earn a permit; native executors stay unavailable

**Status:** proposed, 2026-11-16. Refs
[#442](https://github.com/sushiHex/constructicon/issues/442). Not accepted.
It authorizes no source change, installation, credential, host operation or
model call. On 2026-11-16 the owner put this decision before any route; the
route waits for acceptance of this record.

Accepted [ADR 0018](0018-live-executors-are-leased-contained-processes.md),
[ADR 0021](0021-subscription-executors-bind-operator-stores.md) and
[ADR 0024](0024-retain-native-executor-metering.md) keep governing. This
record changes none of their clauses and no invariant.

Source references are to `main` at `558dc44`. Paths are relative to
`src/constructicon/` unless they begin with `docs/`, `tests/`, `examples/`
or `pyproject.toml`. What was not read is listed under "Not verified".

## Context

The owner requires subscription use inside the graph (ADR 0021:23-24). M8
and M9 delivered it for fixed tasks. #442 asks for an ordinary consumer: the
change-review example gains an explicit opt-in route in which a subscription
executor writes the review advice, metered under ADR 0024. The default route
stays credential-free and calls no model. There is no API key, third
provider, fallback or paid API.

What the source establishes:

- **Unavailable is the published fact.** "A live executor is never generally
  available" (`docs/ARCHITECTURE.md:238-243`). Codex starts with three
  prerequisites that "nothing at runtime can clear"
  (`substrate/executors/codex.py:227-240`), and its host assembly never
  narrows them (`substrate/executors/codex_host.py:263-328`). Claude's
  reason is a constant (`substrate/executors/claude_provider.py:105-107`,
  `:273-275`).
- **A permit is the earning act.** Admission omits those reasons only for a
  provider that holds a verified authorization for exactly the admitted
  graph, and never under a resolution lock (`runtime/validator.py:338-361`,
  `:926-938`). Acquisition then enforces ten checks
  (`core/permit.py:109-131`; `codex.py:2646-2671`;
  `claude_provider.py:319-338`). Owner decision, 2026-10-08: "the
  authorization is the earning act", and `available` stays false
  (`docs/plans/handoffs/M8-N5-stage1-qualification.md:37-39`).
- **One consumer already runs this way.** The M9 selector is not a
  qualification (`docs/designs/RUN_PERMIT.md:43-45`). It asks Codex READ
  one question under a `qualification-read` permit, carries its data in the
  instruction and parses the reply in its node (`api/m9_trial.py:49-71`,
  `:173-194`; `api/_m9/proposer.py:95-101`, `:121-130`, `:156-187`). It ran
  live once (`docs/plans/handoffs/M9-live-selector-record.md:14-34`).
- **A window is physical.** The store anchor refuses another boot to
  everything except maintenance
  (`substrate/executors/operator_store.py:1219-1254`). The binding digest
  names one maintenance generation (ADR 0021:138-146) and enters every
  capability revision (`core/native_operator.py:225-269`). Recorded windows
  end by withdrawing the generation and parking the host
  (`README.md:414-417`).
- **The accepted evidence denies conformance.** Host assembly requires
  `vendor_conformance_qualified` to be false for Codex
  (`codex_host.py:158-175`), and `subscription_qualified` and
  `production_available` to be false for Claude
  (`substrate/executors/claude_host.py:100-105`).
- **The task seam is narrow.** Both adapters refuse task context and a
  response schema (`codex.py:1783-1784`; `claude_provider.py:632-635`).
  Host assembly and the permit reader are Linux-only
  (`codex_host.py:269-270`; `claude_host.py:262-263`;
  `substrate/executors/qualification.py:45`).

## The question and its answer

*What proof, held by whom, makes a native executor available for an
ordinary operator-submitted graph run, outside a qualification or
maintenance window, without weakening a guarantee?*

**None exists, and this record creates none.** Four facts decide it:

1. Outside a window there is no active generation, and after a restart no
   usable anchor. Availability there means silent reuse across a boot,
   which the store refuses.
2. No retained evidence claims egress or vendor conformance; the accepted
   records must say the opposite. Clearing that reason needs a
   qualification that has never been run.
3. Private fixed-actor ingress is an availability prerequisite, never a
   caller's flag (ADR 0021:60-71;
   `docs/plans/milestones/M8-live-executors-rev3.md:67-68`). A permit
   supplies it for one run by pinning the actor and the key. Nothing
   supplies it for every run.
4. The production profiles authorize overage (`codex_host.py:88-90`;
   `claude_host.py:223`) and enforce no finite monetary ceiling
   (`docs/plans/handoffs/M9-model-selector-guide.md:35`). The owner's
   approval of each exact dispatch is the only bound on task data and cost
   (rev 3, `:144-149`). An available executor has no such step.

What admits a consumer run is what admits every live run today: **the
owner's run permit, held in root custody on the private host, naming one
exact run, inside a live window whose generation passed startup
qualification.** The executor is unavailable before, during and after it.

## Decision

### 1. A consumer run is a permitted run

- The published reasons do not change, and `describe()` keeps reporting
  them (`api/system.py:557-581`; `runtime/registry.py:162-173`).
- The route assembles its provider only through
  `codex_host.operator_provider(host, authorization)`
  (`codex_host.py:240-248`), which has no reason parameter.
- The permit is the existing READ permit, read only through root custody
  (`core/qualification.py:40-112`;
  `substrate/executors/qualification.py:32-73`). It pins one run, one
  invocation, one graph, one capability revision, one operator binding,
  the exact grants, epoch one, an expiry and one exclusive attempt record.
  No type, field or literal is added.
- The trusted half is an installed `api` entry with the M9 stages: `pins`
  prints what will be bound, `mint` prints a candidate and installs
  nothing, and root placement is the owner's act
  (`docs/plans/handoffs/M9-model-selector-guide.md:25-39`, `:59-61`). The
  example keeps its default commands and names the opt-in.
- Epoch one is a design constraint. A dispatching permit pins exactly one
  epoch (`core/qualification.py:94-101`), and every process that claims a
  run raises it (`substrate/journal/_sqlite_execution.py:293-323`). The
  executor node therefore runs in the submitting process, before any park.
  The route's graph is one node with one executor binding, no loop, no
  channel and an explicit version: the shape of the READ qualification
  graph (`api/qualification.py:157-176`).
- One permit means one fresh journal, as the qualification entry already
  requires, because the run host resumes whatever a journal holds
  (`api/qualification.py:268-276`).
- A completed run replays from its journal before any provider is built or
  permit read, as in M9 (`api/m9_trial.py:209-213`). After an intent, a
  death reads as possibly dispatched and is never retried
  (`substrate/executors/attempt_record.py:1-17`). Reproduce and
  counterfactual admissions are never exempt (`validator.py:346-353`).
- Nothing falls back. An absent or refused permit ends in a named refusal:
  never the human route, another vendor or an API.

### 2. The run's identity commits to what it sends

A review's inputs differ on every run, and the permit pins no input. The
graph IR carries no constants (`core/graph.py:22-67`). The manifest hash
covers the inputs (`core/manifest.py:197-209`) but exists only after
admission, which needs the permit. Yet the owner must approve the permitted
task data before a model call (rev 3, `:144-149`), as the maintenance
request pins its instruction by SHA-256 (`core/maintenance.py:7-11`).

So: **the idempotency key of a model-advice run is a fixed prefix followed
by the SHA-256 of the exact instruction bytes.** A run id derives from the
actor, the operation and the key alone (`core/control.py:1432-1453`), and
the permit pins both (`core/qualification.py:55-57`). Three guards follow,
none of them new law:

- The owner approves the digest by approving the permit. The `pins` stage
  prints the instruction text beside it.
- Acquisition refuses every other run with `permit.run`
  (`core/permit.py:118`; `codex.py:2655-2671`).
- The node rebuilds the instruction from its actual input, hashes it,
  recomputes the run id and refuses unless it equals `ctx.run_id`
  (`runtime/context.py:47-63`), before it calls `execute`.
- That guard is pinned only if its source is. `PythonRef.source_digest` is
  optional (`core/component.py:44`), and `source_digest_for` hashes only
  `inspect.getsource` of the implementation, plus an explicitly supplied
  adapter revision (`runtime/registry.py:357-374`), not the helpers or
  module globals it calls. The implementation must therefore give every
  part of the guard a positive source identity: the instruction builder, its
  canonicalization, the run-id recomputation, and the fixed actor,
  operation, prefix and framing. Either it inlines the whole guard in the
  hashed implementation or it uses the existing explicit adapter-revision
  mechanism; no new framework. A test must show the component version
  moving when any of those helpers or literals changes. Only then does
  `permit.source_graph`, which names the exact component versions, pin the
  guard.

Within one approved permit and its journal, the same bytes are the same run,
so a repeat replays and never dispatches again; this is not a global
deduplication across permits or journals. Different bytes cannot spend the
permit's turn. The entry makes the
same comparison before `runs_start`: the walker acquires and materializes
the executor, which reserves the attempt record, before the node body runs
(`runtime/walker.py:1918-1931`, `:1963-1969`; `codex.py:2674-2686`), so a
mismatch first seen by the node spends the permit without a dispatch.

### 3. One instruction, one bounded reply

The adapters are not extended. Either extension edits at least `codex.py`,
which the adapter revision hashes whole (`codex.py:2770-2772`), widens what
reaches a vendor, and has one consumer (I6).

- The task is `TaskSpec(instruction=...)` and nothing else
  (`core/executor.py:40-45`).
- The instruction is fixed framing plus the canonical JSON of the bounded
  summary: scope, the two hashes, syntax errors, availability, symbol
  lists, counts and the partial flag (`examples/change_review.py:83-95`).
  It is LF-only UTF-8 of at most 8,192 bytes, the maintenance instruction's
  bound (`core/maintenance.py:40`). Symbol names are bounded in characters,
  not bytes, so an oversized instruction refuses by name; it is never
  truncated.
- It never carries source text, a `GitRef` or a host path. A `GitRef` holds
  the repository's absolute path (`examples/change_review.py:306`).
- Symbol names are text chosen by the author of the reviewed code, and can
  carry injected instructions. The Codex READ profile has no tools, no
  workspace and only vendor-session egress (`codex_host.py:62-91`), so an
  injection gains no mediated tool or workspace authority. What it does to
  the reply, to vendor-side behavior and to token use is not proven.
- The node accepts only a success whose output is non-empty text within a
  fixed byte bound, as the READ qualification node does
  (`api/qualification.py:99-104`). The reply is stored as text. Nothing
  parses it for control: it is never an effect subject, an approval, a
  gate input or a branch condition (I1).

### 4. Model advice is not human advice

`AdviceReplyPayload` promises authorship: its `actor_id` and `message_id`
are stamped from the authenticated command (`core/human.py:167-183`,
`:963-987`). A model reply on that contract would be a false statement of
who advised.

- Model advice leaves on its own nominal port and contract. Its payload
  holds the advice text, the metering source literal, the capability
  revision, the requested model, the served model or null, the instruction
  digest and the reply's byte length. It holds no actor and no message id.
- The route's graph binds no channel and mints no actor.
- The default graph (`examples/change_review.py:189-204`), its component
  versions and its source graph hash do not change.

### 5. Codex READ first; Claude by its own decision

Codex READ needs no workspace, offers no tools and has a capability
revision that no task changes (`codex_host.py:62-91`;
`codex.py:1781-1782`). It is the profile the M9 selector already used
(`api/m9_trial.py:35`).

Claude READ requires a contained workspace (`claude_host.py:206-224`;
`claude_provider.py:174-211`). Its identity binds the workspace base, so
its capability revision changes with every reviewed commit
(`claude_provider.py:155-164`). It refuses a turn that makes no mediated
read (`claude_provider.py:774-786`), so a Claude review sends file content
to the vendor. That is a different data decision and a larger assembly. It
is not taken here.

### 6. Metering is the existing projection

No metering code is added. `Constructicon` wraps an exact native provider
whenever the journal is SQLite (`api/system.py:278-282`). The wrapper binds
a journal meter before materialization (`api/_metered_native.py:93-108`);
the handle records intent and passes its dispatch check before
`turn/start` is written, then settles (`codex.py:1802-1832`;
`docs/ARCHITECTURE.md:274-277`). Result version 3 carries the summary
(`core/control.py:1221-1250`), and the example already returns it
(`examples/change_review.py:394-396`). A permitted READ run already
reports `supported_observations` with one `codex_fresh_thread_total_v1`
group in tests (`tests/api/test_qualification_entry.py:496-533`). The
default route keeps reporting `unmeasured`
(`docs/CHANGE_REVIEW.md:97-101`). Estimate and confirmed charge stay
unknown.

### 7. Every refusal names its guard

| Refusal | Named by |
| --- | --- |
| No permit, or another graph | admission fault `executor_unavailable`, one per published reason (`validator.py:926-938`) |
| Any permit mismatch | `permit.*` codes sealed in the failed-node event (`core/permit.py:30-58`; `runtime/walker.py:113-118`) |
| Expiry at the task write | `permit.expired` (`codex.py:1821-1832`) |
| The route's own guards: instruction differs, instruction over bound, reply not positive, reply over bound | a closed code chosen at each guard |
| Not Linux | "the host assembly requires the Linux host" (`codex_host.py:269-270`) |
| Unreadable permit | one sentence that discloses nothing, by design (`substrate/executors/qualification.py:29-39`) |

Two existing refusals on this path carry a sentence and no code: "an
unavailable operator provider cannot acquire" (`codex.py:2649-2650`) and
"the authorization's one attempt is spent"
(`substrate/executors/attempt_record.py:54-55`). Coding them edits files
that adapter revisions hash; see "What moves".

## Alternatives evaluated

**(a) A standing availability authorization** over a graph family.

- *Adds:* a family, a run budget and a ledger for it. One exclusive file
  budgets one permit today, and says of itself that it is not a ledger
  (`attempt_record.py:1-17`; ADR 0018:331-332). *Retires:* nothing; the
  per-run permits remain for qualification and maintenance.
- *Trades:* the owner's approval of each exact dispatch, unless it lists
  every run's digest. Then it is N permits in one file.
- *Cannot be standing:* a permit must name the provider's binding
  (`codex.py:2600-2607`; `core/permit.py:124`), and the binding names one
  generation. It dies at withdrawal.
- *Moves:* `core/permit.py` and `codex.py`, so the maintenance application
  revision and both adapter revisions (`api/_maintenance_identity.py:11-21`;
  `claude_provider.py:891-897`; `codex.py:2770-2772`). *Live step:*
  requalification and a multi-run rehearsal. *Per run:* one turn, no
  approval. *Refusals:* new codes for the family and the budget.
- Rejected. Approving N exact permits in one owner step gives the same
  saving and trades nothing.

**(b) Assembly clears the prerequisites on positive physical evidence.**

- This is the only path on which "available" would be true. ADR 0021
  names it (`:382-388`) and the code leaves room for it
  (`codex.py:239-240`); nothing builds it.
- *Adds:* an evidence record that asserts conformance, where today's must
  deny it; a proof of private ingress that is not a flag; and a spend bound
  to replace per-run approval. *Retires:* the permit, for consumers only.
- *Moves:* for Claude, the adapter revision, because its reason is a
  constant in a hashed module (`claude_provider.py:105-107`, `:891-897`).
  For Codex, no source-derived revision: host assembly would pass one
  argument (`codex.py:2464`). The gate there is evidence, not code.
- *Live step:* a positive-conformance campaign per vendor, each separately
  authorized (ADR 0021:16-19), then startup qualification on every boot as
  now. *Per run:* one turn, no approval, and no limit on how many.
- *Refusals:* the existing admission fault names each missing reason.
- Not taken. It is recorded as the one legitimate route to availability
  and needs its own ADR.

**(c) A single-use permit per consumer run.** Adopted, in the form of (d).

**(d) The smallest form of (c): no new permit type, literal or field.**
Adopted. The consumer reuses the READ permit's unchanged law, as the
separately reviewed M9 consumer does, for this one reviewed graph only (see
"Exact authority delta"). It binds its task data through the run's identity.

- *Adds:* one nominal output contract and one installed entry.
  *Retires:* availability as a goal for consumers.
- *Moves:* see below. *Live step:* one permit and one READ turn in a live
  window. *Per run:* one user turn, never retried; one owner approval; a
  share of one window. *Refusals:* section 7.

Also rejected: model text on `ADVICE_REPLY` (section 4); extending the
adapters for context or a schema (section 3); Claude first (section 5).

## What moves

| Change | Source-derived identity moved |
| --- | --- |
| The decision as written: new files under `api/`, the example's opt-in, two import contracts | the installed controller tree; the M9 selector's source identity, which hashes every package file, so existing trial directories refuse (`api/_m9/proposer.py:52-86`; `api/_m9/trial.py:46-63`) |
| The same | no adapter, protocol, launcher, application or law revision; no permit wire or schema |
| Optional: closed codes for the route's guards (`core/refusal.py`) | the maintenance application revision (`api/_maintenance_identity.py:11-21`) |
| Optional: codes for the two uncoded refusals (`codex.py`, `attempt_record.py`) | the Codex adapter revision, hence every Codex capability revision (`codex.py:2770-2772`; `core/native_operator.py:264-269`); the Claude adapter revision (`claude_provider.py:891-897`) |
| Optional: a consumer stage literal or an explicit digest field (`core/qualification.py`) | the Claude adapter revision (`claude_provider.py:891-897`); the permit's schema and printed-byte goldens |

The new entry joins both import contracts, so the MCP adapter can never
reach it (`pyproject.toml:84-144`).

Main's adapter and protocol sources already need fresh qualification before
live use (`docs/AGENT_HANDOFF.md:90-92`). Whether the route and any optional
row can share a later requalification is not established here: the #438
record authorizes no requalification and no freeze exception, and the exact
overlap with the pins current at implementation is determined then.

Cost of one real run: one native user turn. The one comparable turn on
record took about 6.5 seconds and reported 5,812 input and 7 output tokens
(`docs/plans/handoffs/M9-live-selector-record.md:26-34`). Each window also
costs a host start, one startup qualification of four methods and no
thread (`codex.py:9-19`; `substrate/executors/codex_lane.py:111`), a
withdrawal and a park. Money stays unknown.

## Proof

No route exists yet; this section states the proof a future implementation
must supply. Credential-free tests already drive the real adapter, walker,
journal and control plane over a scripted byte channel
(`tests/substrate/test_codex_adapter.py:154-206`, `:334-398`). The route's
tests must use the permit path, as the READ entry's do
(`tests/api/test_qualification_entry.py:404-425`, `:496-533`), and never
an emptied reason tuple.

Required proof:

- the exact graph is admitted and every reason is still published;
- each of the ten mismatches refuses with its code before a handle exists;
- exactly one `turn/start`, and a reset journal cannot spend it again;
- the bytes the peer received hash to the permitted digest and contain no
  path; another packet under the same key refuses before any `turn/start`;
- empty, oversized and failed replies refuse and never checkpoint;
- metering reaches result version 3 at the accounting cut;
- the model-advice port cannot bind where human advice is required;
- the default route's graph hash, outputs and `unmeasured` metering are
  byte-identical to the base.

Such tests cannot prove:

- that a real model answers this instruction usefully, or at all. A
  scripted peer returns what the test wrote;
- vendor facts: subscription mode, account and limit readings, real egress
  destinations, the served model, real token counts, overage;
- containment on the private host at the installed revision and boot;
- owner provenance of a permit. CI seals what the service minted
  (`docs/plans/handoffs/M8-N5-stage1-qualification.md:183-184`);
- anything about Linux from a Windows run;
- cost. Tokens are observations, not a charge.

## Premortem

The three likeliest ways this decision weakens a guarantee.

1. **Availability returns under another name.** The route passes an empty
   reason tuple because tests do
   (`tests/substrate/test_codex_adapter.py:415-440`;
   `tests/api/test_executor_metering_origin.py:41-43`); or the permit grows
   a key prefix, a count or an epoch range for convenience.
   *Guard:* host assembly is the route's only constructor and has no reason
   parameter. A test asserts the published reasons and `available: false`
   before, during and after a permitted run. A mutation needle fails on
   any reason argument in `src`. The validator keeps one epoch for every
   dispatching permit (`core/qualification.py:94-101`).
2. **Data reaches the vendor that the owner did not approve.** A different
   packet is submitted under a permitted key; or the instruction builder
   later gains source text or a path "for better advice".
   *Guard:* section 2, enforced by the provider and by the pinned node. The
   builder takes the bounded summary and nothing else; a test fails on any
   field outside the closed list and on any byte over the bound.
3. **Model text acquires authority.** It is delivered as human advice, or a
   later node treats it as a decision.
   *Guard:* section 4. An admission test shows the model-advice port
   refused wherever `constructicon.std/AdviceResponse` is required. The
   reply is text; no component of this route reads it.

## The strongest case against

*A review that needs a host start, a startup qualification and an owner
approval is a ceremony, not a consumer. If every run is a permitted run,
this is M9 again with a different prompt.*

- The costs named are the cost of the guarantees, not of this design.
  Every live run pays each of them today.
- It is a consumer in the sense #442 asks for: operator-chosen data, a
  useful output, metering in the public result. M9's input was a constant.
- The cost falls where the owner controls it. One window can carry N exact
  permits approved in one step. It cannot carry a dispatch nobody approved.
- If that cost is too high, the answer is (b), earned by evidence under
  its own ADR. It is not a cheaper word for this one.

## Exact authority delta

No wire, schema or invariant delta. This record supersedes no clause of
ADR 0018, 0021 or 0024, and reuses the permit law unchanged.

There is one authority delta, and acceptance would grant it. The permit
type is documented for exactly one fixed qualification run
(`core/qualification.py:1-8`, `:40-48`). The M9 selector is a separately
reviewed fixed consumer, not a precedent for ordinary consumers. Acceptance
would add one more accepted use: this specific, reviewed change-review
advice graph, named by its exact component versions. It would not authorize
arbitrary graphs, a family of graphs, or any other use of an existing
permit, and it repurposes no permit already minted. Publishing this proposal changes no current-truth
document. Only after a separately authorized implementation merges would
`ARCHITECTURE.md` record that the READ permit also serves consumer advice.

Not decided here, and not authorized: availability by evidence (b); a
Claude route; a rename of the permit's stage; structured output or task
context; any second consumer; any live window, credential or model call.

## Decision requested

Accept or redline: (1) no availability, and a consumer run as a permitted
run; (2) the run-identity binding of task data; (3) instruction-only tasks
with a bounded text reply; (4) the separate model-advice contract; (5)
Codex READ first. Acceptance authorizes credential-free construction of
the route. A live run needs its own permit and its own owner approval, as
every live run does.

## Not verified

- "What moves" is derived from source at `558dc44` and must be reconciled
  with the revision-unit record for
  [#438](https://github.com/sushiHex/constructicon/issues/438) before
  acceptance.
- The controller revision installed on the private host, and whether
  `examples/` is present there. `pyproject.toml` does not package it.
- Whether the M9 READ window's operator tooling under `scripts/ops/` can
  carry a second consumer. It was not read.
- That source digests agree between a Windows and a Linux checkout. The
  permit is minted on the host that runs it
  (`docs/plans/handoffs/M8-N5-stage1-qualification.md:133-135`).
- The token count of a review instruction. Only the M9 turn is on record.
- `api/plan_manifest_application.py`, ADR 0019, ADR 0020 and the M8
  implementation record were not opened in drafting.
