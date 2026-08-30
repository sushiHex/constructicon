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
_CommandExecutor   ten mutations; claim, immutable plan, apply/reconcile, record
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
graph scheduler. A resume command is receipted by the exact attempt transition
carrying its `resume_command_id`, not by status polling or an unrelated event.

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
request, so concurrent repliers yield one exact reply and a typed conflict.
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

Nothing about the message is therefore chosen at call time. A component holds
only `await ctx.channel(alias).ask(payload)`, and pinned source is not pinned
behavior: a component free to name its own port could branch differently on a
second host and append a second request.

## Parking and waking

Waiting is not failing. A component that has sent or reconciled its request and
found no reply raises `InvocationParked` naming that request; the walker records
ordinary parking facts and checkpoints nothing, because there is no output yet
and a checkpoint would make the next attempt skip the wait. No workspace, lease,
or coroutine stays open while a human thinks.

Recovery reads durable domain facts, never command state. `Journal.parked_waits`
projects current PARKED runs and their latest exact `RunParked` event; a bounded
scan asks which of those requests already carry a reply and wakes the run at the
projection's event fence. A death after a reply's domain transaction but before
its command completes therefore still produces the wake, with no command lookup
and no wake outbox. Scanning parking facts rather than watermarking replies also
closes the race where a fast reply lands just before the park is recorded.

PARKED never joins the ordinary recovery statuses: a parked run waits on a
human, not on a lost worker, so only an observed reply may wake it. One
`AttemptCause` names why an attempt started — M6's committed resume command or
M7's stored reply — and M6 keeps its exact legacy key. See
[ADR 0014](adr/0014-channel-identity-and-delivery.md).

## Journal

One transactional log, many projections. SQLite (stdlib, WAL) is authoritative
for runs, events (per-run monotonic sequence), checkpoints, attestations,
channel messages/acks, and effect records; node completion commits checkpoint + event in one transaction.
JSONL, summaries, and renderings are regenerable projections (M2+). Resume
re-walks the graph: a checkpoint at the same `ExecutionPath` with matching
input hash and resolved version restores; the first miss resumes live.
Reproduce starts a new run under a past run's exact manifest and inputs.

One public `SqliteJournal` implements the separate L0 `Journal`,
`RegistryStore`, and `ControlStore` contracts over one schema-5 WAL database.
Its private modules are named by enduring responsibility:

```text
_sqlite_base       connections, transactions, clock, fault hook
_sqlite_schema     creation and explicitly versioned migrations
_sqlite_execution  runs, events, checkpoints, effects, leases, attestations
_sqlite_registry   registrations, promotions, coherent snapshots
_sqlite_control    commands and approvals
_sqlite_queries    bounded read projections
```

This is implementation decomposition, not multiple stores and not schema 6.

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
| Agent authoring | Unknown Graph fields are refused; a serialized architect repairs schema and magnetic ambiguity faults using describe + rejection data only (M5) |
| SDK identity | A persisted decorated task activates in a fresh process; SDK/direct/repaired Graphs produce one manifest identity (M5) |
| Command law | Response loss after plan, domain fact, or completion across all ten mutations → one exact fact and response (M6) |
| Control lifecycle | Startup/shutdown and mutation/shutdown races → no orphan pump, command after close, or invented cancellation (M6) |
| Registry pages | Registration or promotion between pages → old vector cut unchanged; fresh query sees the new revision (M6) |
| MCP | Actor-derived handler delegates once; local assembly and mutable services have no transport route (M6) |
| Message channels | One derived id survives process death: a reconstructed send appends no second message and invents no new time; a second differing reply is a typed conflict (M7) |
| Channel cuts | A send or ack between pages → old vector cut unchanged; a future revision is refused (M7) |
| Channel parking | A death at any send seam yields one message; a stored reply wakes the PARKED run with no command lookup (M7) |
| Telemetry | Damaged executor output never reports clean success |
| Reproduction | Installed code differs from recorded digest → refuse (M2) |
| Loops | Contradictory iteration checkpoint, hidden nested loop, or non-boolean control → refuse before new work; exhausted roots report PARKED (M4) |
| Rollback | Both versions and all evidence retained; in-flight runs keep pins |
