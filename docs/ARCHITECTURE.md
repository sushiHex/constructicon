# Architecture

Current truth only. The invariants live in [INVARIANTS.md](INVARIANTS.md);
history and adjudication live in [adr/](adr/); the self-improvement design
lives in [designs/SELF_IMPROVEMENT.md](designs/SELF_IMPROVEMENT.md).
Historical, non-normative planning records live in
[plans/](plans/README.md).

Constructicon is an OS for agentic software-engineering pipelines. One authored
graph IR; one sealed `ExecutionManifest` per run; scoped capability leases;
journal-minted attestations; idempotent effects with receipts; component
versions that reach dependents only through explicit promotion. Agents are the
first-class user; humans are observer, advisor, and approver.

> Authored intent may be ergonomic; executed reality must be explicit.

## Layers

```
L4  api        ControlPlane · typed describe/admission · MCP server · CLI skin ·
               injection root: constructs L1, hands it to L2
L3  sdk        @task · component/flow/harness/loop sugar — process-local
               authoring carriers compiling immediately to the core IR
L2  runtime    graph IR · registry/resolution · authoring preflight + validator
               → ExecutionManifest · walker · resume/effects [L0 only]
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
  outputs, and parks with `policy_exhausted` on exhaustion.

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
admission; root inheritance is a fault), complete `LoopResolution`s (boundary
bindings, feedback substitutions, boolean continuation source, explicit
non-control exports, and topologically ordered atomic members), and three
identities: `input_hash`, `world_hash`, `manifest_hash`. Composites flatten at
admission; boundary renames never leak inner names.

**The walker accepts only an `ExecutionManifest`.** After validation it never
resolves a reference, searches for a port, inherits a grant, chooses a
capability, interprets a selector string, or decides whether an effect is safe.

Executors declare an `IsolationProfile`; admission rejects a live execution
whose executor cannot mechanically satisfy the requested posture — it never
degrades to "best effort".

## Agent authoring and introspection

M5 adds surfaces, never another workflow representation:

```text
Python SDK sugar ─┐
                  ├─→ strict Graph → one validator → ExecutionManifest
Architect JSON ───┘
```

`@task` lowers a module-level typed function into a canonical atomic
`ComponentDef` and an importable async adapter. The adapter's source identity
covers both the user function and the SDK adapter revision, so a persisted task
can be activated by a fresh process without receiving an in-memory closure.
`component`, `flow`, `harness`, and loop sugar emit only `Ref`, `Graph`, and
`Loop`; `DefinitionBundle` is process-local registration convenience and never
crosses admission.

Graph JSON is strict (`extra=forbid`, exact schema version, `$`-prefixed ids
reserved). `system.admit_graph()` accepts JSON, mappings, or canonical Graphs,
applies bounded authoring preflight, and enters the same validator. Expected
rejection is typed data:

```text
AdmissionFault{code, message, path, scope, repair, details}
AdmissionAccepted{graph, manifest}
AdmissionRejected{graph?, faults}
```

Semantic rejection returns the canonical parsed Graph. Constructicon never
auto-repairs: the caller edits and resubmits. An accepted manifest is an
inspection preview, not a public execution token; `ControlPlane.runs_start()`
re-admits the Graph while creating its durable command and run.

`system.describe()` derives one bounded, secret-free authoring contract from an
immutable `RegistrySnapshot`, the assembled capability catalog and live
availability, the effective root grants, and shared authoring constants. It
publishes strict Graph and AdmissionResult schemas, deduplicated port schemas by
their exact contract hash, component contracts and completeness, capability
requirements and availability, binding/selector and loop vocabulary, limits,
and content identities for the snapshot, catalog, and description. Legacy
components remain usable but are marked honestly as capability-opaque or
schema-opaque where applicable. See
[adr/0011](adr/0011-agent-authoring-and-introspection.md).

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
unknown external effect. Preparing an effect returns the first durable request
under its derived identity; every contender reconciles or executes that
canonical request, never its caller's losing value. A receipt is valid only
over that preparation and its `(receipt_json, receipted_at)` lifecycle is
all-or-nothing. Idempotency keys derive from `(manifest_hash, path, kind,
subject)`.

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

Atomic M5 components may declare required capability aliases and descriptor
kinds. `None` means a historical capability-opaque definition; `()` means a
complete declaration with no capabilities. Complete declarations participate
in the next component-identity version; legacy definitions preserve their
M1–M4 hashes. Composite capability bindings remain encoded in their Graph body.

Every `RegistrySnapshot` identifies one coherent vector cut:

```text
RegistryRevision{registration_seq, promotion_seq}
```

The SQLite store reconstructs that exact cut from its append-only registration
and promotion sequences; the memory store implements the same contract. Version,
candidate, reverse-dependency, comparison, and description reads use one
snapshot. A continuation cursor carries the vector, so later registrations and
promotions cannot drift into an older page. A future or incoherent vector is a
refusal, never a best-effort reconstruction.

## Durable control plane

`ControlPlane` is the only public mutation gateway. Its two private delegation
collaborators have disjoint responsibilities:

```text
_CommandExecutor   twelve mutations; claim, immutable plan, apply/reconcile, record
_ControlQueries    authorized bounded reads and page continuations
```

Every mutation follows one command law:

```text
authorize → lifecycle admission → claim → plan → apply once → record → replay
```

The caller supplies a bounded idempotency key; actor, operation, key, canonical
request hash, plan, domain receipt, and terminal response are related and
validated. Response loss after the plan, domain fact, or command completion
cannot duplicate a run, attempt, approval, registration, promotion, rollback,
or cancellation. Historical v1/v2 responses replay as control schema 3 in
memory without rewriting their durable bytes.

A rejection is an exact fact, not a lawful error code. A pre-domain refusal
stores its complete typed response in the rejection plan; a post-plan race uses
one response derivable from the immutable domain plan and retained facts. A
command that already owns a co-located approval, reply, or acknowledgement
cannot become rejected, because that lifecycle would contradict the mutation
the same store already committed.

The control plane is one assembled world, not a set of compatible-looking
handles. Its store is the exact journal already assembled into `Constructicon`
and implements `ControlPlaneStore`, which co-locates commands, approvals, and
channel exchange transactions. Its registry is the system's exact registry,
and a concrete `RunHost` serves that same system and journal. A second handle is
refused even when it points at the same SQLite file: object identity also binds
the live implementation cache and process-local scheduler state.

Local component registration and initial promotion use the same command law.
They require a launcher-minted static actor with admin scope and are absent from
MCP. `Constructicon` exposes neither public mutation wrappers nor mutable
journal/registry handles. See [ADR 0012](adr/0012-durable-control-plane-and-mcp.md)
and [ADR 0013](adr/0013-local-assembly-through-command-law.md).

`ControlPlane` also owns the race-safe process lifecycle:

```text
new → starting → started → stopping → stopped
```

Authorized first mutations join the same full startup as explicit launchers;
unauthorized calls start nothing. Shutdown admits no new commands, waits for
already-admitted command orchestration to reach a durable terminal response,
then abandons workers without inventing user cancellation. `RunHost` owns only
bounded process-local workers and recovery scans; the walker remains the sole
graph scheduler. A resume command is receipted by one `resume_attempt`
relationship co-committed with the exact transition carrying its
`resume_command_id`. The relationship binds the command claim, plan, baseline
event (or the sequence-zero PENDING fact), and attempt event. Command and event
point reads validate both halves; current-open inventory proves their
bijection, and a command that owns the relationship cannot later be rejected.

Opaque cursor schema 2 binds actor, endpoint, canonical query, calibrated
checksum, snapshot bound, and continuation key. The checksum detects accidental
corruption; it grants no authority. Run/event pages use immutable upper bounds,
registry pages use `RegistryRevision`, and detail chunks remain digest-bound.

## Channels

A channel makes a participant on another rhythm an ordinary typed participant in
a run. One L0 `Channel` contract has two transports: `InProcessChannel` for
same-process composition and contract tests, and `MailboxChannel`, which
persists in the one authoritative journal database so a message and the run
parked on it survive or fail together. Neither owns a second database, broker,
or schema manager, and `describe()` publishes each transport's honest
`ChannelProfile`.

Identity is derived, never authored. A request id comes from
`invocation_id(run_id, path)` plus the sealed channel binding, lane, interaction,
and port; a reply id comes from the request it answers. One invocation therefore
sends at most one request per bound channel, lane, and port, and a send
reconstructed after process death recomputes the same id rather than appending a
second message. A request pins both halves of the exchange: `contract`/`port`
type its own envelope, while `reply_contract`/`reply_port` are sealed values
saying what reply is admissible.

History is retained and delivery is honestly at-least-once. Nothing is deleted
or dequeued; an acknowledgement is a delivery fact about one actor and never
claims a component consumed the payload. `UNIQUE(reply_to)` admits one reply per
request, so concurrent repliers yield one exact reply and a typed conflict. A
reply records its writing command and ensures the sender's acknowledgement in
the same transaction; an acknowledgement written earlier remains its original
command's fact rather than being stolen by the reply. One command cannot write
two replies or cross from reply ownership into an unrelated acknowledgement.
Schema 7 adds a nullable writer and nullable reply-provenance version plus a
partial unique writer index: two NULLs identify true schema-6 history, while a
current reply must carry both its writer and provenance version 1. It also adds
an acknowledgement-provenance version and independent immutable message and
acknowledgement migration cutoffs. Migration bounds schema-6 replies by the
captured `message_seq` and marks acknowledgements at or below the captured
`ack_seq` as version 0; current replies and acknowledgements carry version 1,
lie above their respective cutoff, and name an extant writer command. The
sealed cutoff pair makes legacy provenance a positive historical fact rather
than something a damaged current row can imitate by losing one column.
A current durable reply is readable only when its writer's operation-specific
immutable typed plan independently proves the payload and every derived field:
`ChannelReplyPlan` for advice, or `ChannelApprovalPlan` plus its exact approval
exchange. A schema-6 advice reply retains only acknowledgement-owned
provenance: its version-0 acknowledgement's command id is an opaque historical
scalar and is never resolved into a current command. A schema-6 approval
exchange may still recover and validate its `ChannelApprovalPlan` through the
retained approval row. Neither compatibility path can manufacture a current
command plan.
Inbox pages are taken at one `ChannelRevision(message_seq, ack_seq)` vector cut
ordered by durable sequence, so tied observation times still order totally and a
later write cannot shift an older page.

Routing is a manifest fact, not a live-object detail. Assembly supplies a
`ChannelEndpoint` (lane, interaction, recipient) on a capability descriptor;
admission compiles it into the scoped `CapabilityBinding` together with the one
request/reply pair it may carry, taken from the component's single declared
input and output. Capability bindings participate in manifest identity, so two
hosts that assemble one manifest with different routing disagree on
`manifest_hash` instead of silently deriving a second message — and activation
compares the live endpoint against the sealed one, because a revision is only a
string. A manifest that binds a channel declares schema 3; one that binds none
stays schema 2 and byte-identical.

Assembly also binds the physical world: descriptor identity, channel id,
profile, and live transport must agree; a durable mailbox uses the system's
exact journal; and `ChannelSendEffect` uses that same journal and the exact
transport objects used for reads and replies. Component code receives only the
sealed `ask` facade. The two built-in capability kinds are fixed facts:
`channel.mailbox` means `sqlite_wal`, and `channel.in_process` means `process`;
a custom kind may declare its own truthful profile. A `sqlite_wal` channel must
implement `JournalBackedChannel` and prove that its journal is the system
journal. The raw transport never appears through
`ctx.capability(alias)`, including when a leased provider tries to return one.

Nothing about the message is therefore chosen at call time. A component holds
only `await ctx.channel(alias).ask(payload)`, and pinned source is not pinned
behavior: a component free to name its own port could branch differently on a
second host and append a second request.

A panel is a Graph pattern over this, not a primitive. `panel()` emits the
literal fan-out and fan-in: each member sees the graph's one request input, and
one explicit aggregator gathers every member through an ordinary `many` port.
The combinator executes nothing, chooses no model, infers no quorum, and hides
no scheduler; its Graph is byte-equal to the hand-authored one. Exactness is
proved at authoring from bundles' declared contracts — every member shares one
request/result pair of cardinality one, the aggregator is atomic and has
exactly one `many` port of that result contract, and no boundary input, the
request included, carries that contract —
because the gather is the general connector law: a graph input sits in every
node's pool, and a compatible graph input or a compatible helper upstream of a
member would widen it. The standard aggregator
`constructicon.std/panel-quorum` is pure and declares no capability; it derives
each member's node from the member's reported path against its own path —
same parent scope, the aggregator's loop frames as a prefix of the member's,
any further frame naming a loop beneath the member's seat that encloses the
reporting invocation, nested in order — refuses any other topology, the
aggregator's own seat, or a node reported twice, orders members by the
canonical JSON of their path, and concludes one of four explicit outcomes
(`approved`, `rejected`, `insufficient_responses`, `impossible_quorum`) from an
explicit quorum input. The result names its aggregator and run and is
self-verifying: validating one re-derives placement, tally, and outcome from
the members it carries and refuses a contradiction, whichever aggregator wrote
it. Every outcome a member reports — `responded`,
`declined`, `unavailable`, `timed_out` — is data; the kernel owns no clock. A
human member is `human-advisor` followed by `constructicon.std/panel-ballot`,
which reads the human's reply strictly as a ballot and carries the actor and
message id the executor stamped, so the vote can be followed back to its
durable reply. Member identity is member-reported and shape-checked, not
kernel-attested; attesting `many`-port sources is deferred. The two panel
components delegate their behaviour to the law in `core/panel.py`, so its
revision — a digest of the contract classes and law bodies, derived rather
than named — is stamped into their implementation identity: a changed law is
a new version by construction, never a silent change of a retained one. A
composite's declared boundary is its Graph's — admission exposes the Graph's
ports, so the registry refuses a declaration that differs, `component()`
refuses to redeclare one, and admission re-proves a retained store rather than
trusting it, as a typed `graph.reference.invalid` fault naming the retained
version. A boundary is compared as canonical bytes, never as models: `1 ==
True` is a Python fact, and an embedded schema that differs only there is a
different boundary.
The sugar emits unversioned Refs like every combinator: the authoring proof is
about the bundles as authored, and admission re-proves the gather nominally
against the one atomic world it seals.

A named contract revision is not the digest of a schema, so the registry
refuses to embed one on a port. `system.describe()` publishes the standard
vocabulary instead — every named contract revision and the shape it names,
from the L0 catalogues beside the contracts — and reports a port's schema
available when the port embeds one or names a catalogued revision. A shape no
port carries, such as the ballot inside an advice reply, is published the
same way (I9).

## Parking and waking

Waiting is not failing. A component that has sent or reconciled its request and
found no reply raises `InvocationParked` naming that request; the walker records
ordinary parking facts and checkpoints nothing, because there is no output yet
and a checkpoint would make the next attempt skip the wait. No workspace, lease,
or coroutine stays open while a human thinks.

Recovery eligibility comes from durable domain facts, never command
completion. `Journal.parked_waits` projects current PARKED runs and their latest
exact `RunParked` event; a bounded scan asks which of those requests already
carry a reply and wakes the run at the projection's event fence. The reply's
immutable writer command and plan are checked as provenance, but whether that
command is already complete is not the wake signal. A death after the reply's
domain transaction but before command completion therefore still produces the
wake, with no wake outbox. Scanning parking facts rather than watermarking
replies also closes the race where a fast reply lands just before the park is
recorded. A missing or non-request wait target is journal damage, not an
unanswered request; the projection fails closed instead of stranding the run
silently.

PARKED never joins the ordinary recovery statuses: a parked run waits on a
human, not on a lost worker, so only an observed reply may wake it. One
`AttemptCause` names exactly one reason why an attempt started — M6's committed
resume command or M7's stored reply — and M6 keeps its exact legacy key. Its
single serializer/parser owns both reserved payload keys and refuses a payload
that claims both causes. See
[ADR 0014](adr/0014-channel-identity-and-delivery.md).

Who may read and answer a message is sealed on the request, never chosen by the
answer. An advisor is its own role rather than an observer with extra rights, so
the channel surface authorizes on `constructicon:advise` and
`constructicon:approve` alone. A reply carries no recipient — it is addressed to
the run, not a person — so authority is read from the request it answers.
Advising is not approving: `channels_reply` consumes advice, and an approval is
consumed only by request-bound `runs_approve`, which commits the
`ApprovalRecord`, the reply, and the request's acknowledgement in one
transaction when the acknowledgement is new, or preserves an equal earlier
delivery fact. The approval and reply always share the exact `runs_approve`
command and authenticated actor; a retry validates those durable relationships
rather than trusting its own plan. A component sees only a payload, so anything
it may promise about authorship the executor writes there from authenticated
facts. See
[ADR 0015](adr/0015-human-authority-on-channels.md).

## Journal

One transactional log, many projections. SQLite (stdlib, WAL) is authoritative
for runs, events (per-run monotonic sequence), checkpoints, attestations,
channel messages/acks, and effect records; node completion commits checkpoint
and event in one transaction.
JSONL, summaries, and renderings are regenerable projections (M2+). Resume
re-walks the graph: a checkpoint at the same `ExecutionPath` with matching
input hash and resolved version restores; the first miss resumes live.
Reproduce starts a new run under a past run's exact manifest and inputs.

One public `SqliteJournal` implements the separate L0 `Journal`,
`RegistryStore`, and `ControlPlaneStore` contracts over one schema-7 WAL
database. `ControlPlaneStore` extends the standalone `ControlStore` ledger with
the transaction that must also own channel facts. Its private modules are named
by enduring responsibility:

```text
_sqlite_base             connections, transactions, exact scalar/JSON decoders
_sqlite_schema           creation, versioned migrations, inventory validation
_sqlite_fact_seals       mechanical write-once positive-seal storage
_sqlite_runs             manifests and the immutable run-creation world
_sqlite_execution_facts  event/checkpoint and resume-attempt relationship facts
_sqlite_effects          effect preparation and historical request/outcome eras
_sqlite_leases           current event provenance and historical lease seals
_sqlite_attestations     attestation identity and historical provenance eras
_sqlite_execution        fenced lifecycle writers over those projections
_sqlite_registry         registrations, promotions, coherent snapshots
_sqlite_actors           exact actor decoding and its named legacy shape
_sqlite_commands         command phases and pre-v7 resume-plan evidence
_sqlite_approvals        approval projection and durable relationships
_sqlite_control          command transactions and approval application
_sqlite_channels         messages, acknowledgements, provenance, bounded reads
_sqlite_queries          bounded run/event projections
```

This is implementation decomposition, not multiple stores.

Every durable JSON boundary rejects duplicate keys, non-finite numbers, and
non-scalar Unicode before typing. Except for an explicitly named,
fixture-proven historical writer shape, a typed projection must render to the
same canonical JSON fact it decoded; model coercion is never repair. Relational
copies of identities and lifecycle fields are independently checked, and stored
timestamps use one exact aware-ISO decoder so a projection cannot change the
lexical key used by a cursor. Durable SQLite booleans and sequences are exact
integers, not Python truthiness. Contradiction is `JournalDamaged`, never a
best-effort projection or a silently healed fact.

An immutable row is not its own evidence. Each current durable fact or
authority-bearing relationship family co-commits one positive seal over every
exact relational and JSON scalar under an independently selected key. A
current open validates the complete bidirectional inventory and never repairs
or reseals it. An ordinary read uses
the owner's canonical projector and requires the selected fact's matching
seal; it does not rescan or weaken that inventory. Only the versioned 6→7
migration may classify retained historical bytes, and it does so in dependency
order under closed, named writer eras. Missing current provenance therefore
cannot become legacy compatibility, and deleting a fact cannot turn its
identity back into permission to create. See
[ADR 0016](adr/0016-positive-durable-facts-and-provenance-eras.md).

Compatibility preserves exact writer bytes rather than normalizing them into
today's shape. M1/M2 effect requests omit `run_id`, `manifest_hash`, and `mode`;
M3–M5 requests carry `run_id` and `manifest_hash` but omit `mode`; current
requests carry all three. Historical terminal receipts remain hashed over their
own request era. A pre-v7 keyless outcome event carries a second,
migration-only positive classification; a current outcome must carry its exact
effect key and can never acquire that historical marker. Schema-5/6 actor scope
arrays and pre-sort component set arrays retain their original unique ordering
while producing a lossless typed view; current writers always emit the
canonical order. No other coercion is implied by these named exceptions.

Resume-plan wire eras are disjoint. Schema-7 SQLite and in-memory writers accept
only typed schema-1 envelopes. A current resume domain plan additionally carries
`terminal_rejection_policy="exact-v1"`; a typed pre-domain refusal is a separate
plan family whose response is already sealed in that plan. Only the 6→7
migration may mint `resume_plan_pre_v7`, for every retained raw `runs_resume`
plan and for a weak typed resume domain plan. Its explicit `prepared` phase
binds the claim and plan without inventing future terminal evidence; its
`terminal` phase also binds the exact retained response. An exact-v1 plan is
never historical, so removing its policy cannot downgrade it into
compatibility. A new resume intent observes the run row and latest retained
event through one `RunHead` snapshot, so a concurrent transition can supersede
a coherent fence but cannot manufacture a mismatched immutable plan.

Loops use that same machinery rather than a second scheduler. Every iteration
adds one `IterationFrame` to each member's `ExecutionPath`; checkpoints,
effects, leases, and events therefore remain frame-distinct automatically. A
checkpoint at an invocation either matches and restores or contradicts and
refuses before any implementation, capability, or effect runs. Continuation is
the one canonical nominal boolean contract. A false decision exports only the
manifest-listed non-control values from that completed iteration; all-true
exhaustion publishes nothing and becomes a typed root PARKED outcome at graph
closure. Independent siblings still finish; dependents report their producer
as PARKED. See [adr/0010](adr/0010-loop-execution.md).

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
- **M3 (done)** — git authority: a bare, protected authority repository
  (deny-all pre-receive; zero protected-ref authority in agent workspaces);
  staged WRITE workspace leases fenced by ownership epoch; exported
  read-only snapshots; real Ruff/Pytest gates over the prepared merge
  commit; one complete typed `MergeSubject`; journal-computed attestations
  minted from drafts; `merge_verified` installing that exact commit through
  one git ref transaction (target CAS + idempotency marker ref) with
  marker-based crash reconciliation; discard-on-failure with
  reconcile-on-reclaim. See [adr/0009](adr/0009-git-authority.md).
- **M4 (done)** — generic bounded loops compiled completely into the manifest;
  frame-aware checkpoints, effects, and invocation leases; strict boolean
  continuation; feedback and final exports; graph-closure PARKED semantics;
  convergent resume/materialization; v3→v4 lease migration and historical v1
  manifest compatibility; staging-local `reset_to(GitRef)`; a real Ruff/Pytest
  red→repair→green Git loop installing exactly one attested merge. See
  [adr/0010](adr/0010-loop-execution.md).
- **M5 (done)** — strict direct Graph JSON; restart-safe `@task`; canonical
  component/flow/harness/loop sugar; declarative capability contracts with
  legacy identity compatibility; typed and bounded `system.describe()`;
  architect-proposed admission with one versioned repair-fault model; SDK,
  direct, and repaired JSON Graphs proving identical manifest identities; a
  serialized architect repairing schema and semantic faults and executing
  successfully. See [adr/0011](adr/0011-agent-authoring-and-introspection.md).
- **M6 (done)** — one authenticated durable command law for ten mutations;
  keyed local assembly; race-safe `ControlPlane`/`RunHost` lifecycle; committed
  resume handoff recovery; schema-3 control responses; revision-vector registry
  snapshots; schema-2 snapshot cursors and digest-bound details; counterfactual
  simulation; optional stdio/OAuth MCP adapter; and schema-5 SQLite decomposed
  by permanent responsibility. See [ADR 0012](adr/0012-durable-control-plane-and-mcp.md)
  and [ADR 0013](adr/0013-local-assembly-through-command-law.md).
- **M7 (done)** — channels (InProcess + Mailbox over the journal), typed
  human inbox/reply/ack and request-bound approval commands, MCP delegation,
  standard advisor/approval components, and the panel pattern: `panel()` sugar
  byte-equal to the direct Graph, nominal member/quorum/result contracts, a
  pure deterministic quorum aggregator, and a human member composed from the
  advisor and a ballot adapter, proven across restarts through the control
  plane's own host. See
  [ADR 0014](adr/0014-channel-identity-and-delivery.md),
  [ADR 0015](adr/0015-human-authority-on-channels.md), and
  [ADR 0016](adr/0016-positive-durable-facts-and-provenance-eras.md).
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
| Agent authoring | Unknown Graph fields are refused; a serialized architect repairs schema and magnetic ambiguity faults using describe + rejection data only (M5) |
| SDK identity | A persisted decorated task activates in a fresh process; SDK/direct/repaired Graphs produce one manifest identity (M5) |
| Command law | Response loss after plan, domain fact, or completion across all twelve mutations → one exact fact and response (M6/M7) |
| Control lifecycle | Startup/shutdown and mutation/shutdown races → no orphan pump, command after close, or invented cancellation (M6) |
| Registry pages | Registration or promotion between pages → old vector cut unchanged; fresh query sees the new revision (M6) |
| MCP | Actor-derived handler delegates once; local assembly and mutable services have no transport route (M6) |
| Message channels | One derived id survives process death: a reconstructed send appends no second message and invents no new time; a second differing reply is a typed conflict (M7) |
| Channel cuts | A send or ack between pages → old vector cut unchanged; a future revision is refused (M7) |
| Channel parking | A death at any send seam yields one message; a provenance-valid stored reply wakes the PARKED run without waiting for command completion (M7) |
| Telemetry | Damaged executor output never reports clean success |
| Reproduction | Installed code differs from recorded digest → refuse (M2) |
| Loops | Contradictory iteration checkpoint, hidden nested loop, or non-boolean control → refuse before new work; exhausted roots report PARKED (M4) |
| Rollback | Both versions and all evidence retained; in-flight runs keep pins |
