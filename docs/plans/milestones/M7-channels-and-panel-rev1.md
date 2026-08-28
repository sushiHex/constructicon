# M7 — channels and panel rev 1

**Status:** review draft; not approved for implementation

**Planning base:** `55daa62992f2982ab7cd9a2449fefe7e6db62ce8` (`main` after M6.2 / PR #13)

**Scope:** typed message channels, durable human round trips, and an ordinary-Graph panel pattern

**Authority:** `docs/INVARIANTS.md` → `docs/ARCHITECTURE.md` → accepted ADRs → code/tests → this draft

This document is the first full M7 implementation plan. It turns the short
milestone line preserved in frozen System Design v12 into a reviewable plan
against the completed M6 codebase. The frozen design is provenance, not current
authority. Approval requires an explicit review decision and, if redlined, a
successor revision; the presence of this file does not authorize implementation.

## 1. Outcome

M7 makes a person or agent on another rhythm an ordinary typed participant in a
run. A component can send one exact request through a bound channel, park without
losing its run or inventing failure, and complete after an authenticated reply.
The same mechanism carries human advice and an exact `ApprovalRecord`. A panel
is only a reusable Graph fan-out/fan-in pattern over ordinary components.

The acceptance story is deliberately small:

```text
typed review request
  → two in-process advisors + one mailbox-backed human advisor
  → durable request; run PARKED/awaiting_advisor
  → authenticated reply; exactly one wake attempt
  → every typed member result reaches an explicit aggregator
  → complete panel result
  → exact approval request; run PARKED/awaiting_approval
  → runs_approve records the decision and its channel reply atomically
  → exactly one resumed attempt observes the ApprovalRecord
```

Crashing after message planning, durable send, reply storage, acknowledgement,
command completion, or wake handoff does not duplicate a message, reply, ack,
approval, or run attempt.

## 2. Explicit cuts

M7 does **not** add:

- a fourth Graph construct, panel AST, workflow representation, event bus, or
  scheduler;
- executor adapters or live ClaudeCode/Codex/Pi sessions (M8);
- debate rounds, fusion acknowledgements, dynamic membership, or early quorum
  cancellation; those wait for a real workflow that needs them;
- candidate/canary release aliases, experience selection, learning, or
  self-improvement machinery (M9);
- a second database, broker, hosted queue, background dispatch service, or
  distributed-worker claim;
- arbitrary caller-selected actors, recipients, lanes, channel ids, type tags,
  run ids, invocation paths, or message identities;
- destructive dequeue, message deletion, or acknowledgement-as-authority;
- automatic repair of an invalid external reply;
- a CLI executor or a general HTTP service;
- a new control response version, cursor version, manifest version, or component
  release channel.

The words *message channel* below never mean a component release pointer.
Registration still never propagates and a candidate remains a query.

## 3. Invariant review

| Law | M7 consequence |
| --- | --- |
| I1 physical authority | Channel endpoints and actor routing come from assembled capabilities and authenticated transports, never message payloads. |
| I2 proof-carrying effects | A run-originated durable send crosses the existing effect boundary under a journal-minted attestation bound to its exact channel subject. |
| I3 no ambient authority | A node can address only its sealed channel binding. Public reply operations derive the actor and target from the stored request. |
| I4 truthful telemetry | Delivery is explicitly at-least-once; an ack never claims consumption; invalid payloads fail honestly at the typed component boundary. |
| I5 typed control / data | Channels carry `Envelope[JsonValue]` plus exact nominal type identity. Code remains `GitRef`; durable evidence remains `ArtifactRef`. |
| I6 two consumers | One L0 channel contract is exercised by `InProcessChannel`, `MailboxChannel`, and the shared contract suite. No protocol is extracted merely to split SQLite files. |
| I7 fake path | Full advice, approval, crash, recovery, and MCP lanes run with SQLite, in-process endpoints, and fake actors; no credential is required. |
| I8 one structure | L0 owns message contracts; L1 implements transports; L2 only binds them into execution; L3 emits Graph; L4 delegates control and transport. |
| I9 agents first | Inbox reads are bounded and cursor-stable; replies and acks take caller idempotency keys; humans use the same typed operations. |
| I10 composition | `panel()` emits the existing Graph and references registered advisors and an explicit aggregator. |
| I11 one connector | Panel fan-out and gathering use ordinary compiled port bindings, including the existing `many` cardinality. |
| I12 candidates only | No release channel or learning behavior changes. |
| I13 sealed execution | Channel capability id/revision and effective grants are manifest-pinned; the walker performs the compiled invocation and decides no routing policy. |

## 4. Existing owners M7 must reuse

The base already supplies the required nouns and laws:

- `Envelope`, `ExecutionPath`, and `invocation_id()` own typed data and dynamic
  invocation identity;
- generic capability requirements, descriptors, bindings, and `NodeContext`
  carry non-ambient services into one invocation;
- `EffectRequest`, journal-minted attestations, receipts, and reconciliation own
  run-originated external mutation;
- `RunStatus.PARKED`, `awaiting_advisor`, and `awaiting_approval` already name the
  run outcome;
- `ApprovalRecord`, `runs_approve`, and `ControlStore` already own authenticated
  human decisions;
- the command law owns every external mutation and `RunHost` already recovers a
  committed process-local handoff;
- cursor schema 2 and `DetailResolver` own bounded, actor-bound reads;
- one schema-5 SQLite WAL database is authoritative.

M7 extends those owners. It does not create parallel envelope, task, approval,
cursor, receipt, host, or store concepts.

## 5. L0 message contracts and identity

Add `core/channel.py`. All models are frozen, strict, JSON-round-trippable, and
schema-versioned independently at channel schema 1.

```python
class ChannelContract(BaseModel):
    type_id: str
    schema_hash: Digest

class ChannelSendIntent(BaseModel):
    schema_version: Literal[1] = 1
    message_id: Digest
    channel_id: str
    channel_revision: Digest
    lane: str
    interaction: Literal["advice", "approval"]
    recipient_actor_id: str | None
    contract: ChannelContract
    run_id: RunId
    path: ExecutionPath
    port: str
    payload: JsonValue

class ChannelMessage(BaseModel):
    schema_version: Literal[1] = 1
    message_id: Digest
    channel_id: str
    lane: str
    interaction: Literal["advice", "approval"]
    kind: Literal["request", "reply"]
    reply_to: Digest | None
    recipient_actor_id: str | None
    sender_actor_id: str | None
    contract: ChannelContract
    envelope: Envelope[JsonValue]

class ChannelRevision(BaseModel):
    message_seq: NonNegativeInt
    ack_seq: NonNegativeInt

class ChannelDelivery(BaseModel):
    message: ChannelMessage
    acknowledged: bool

class ChannelAck(BaseModel):
    message_id: Digest
    actor_id: str
    acked_at: AwareDatetime

class ChannelProfile(BaseModel):
    durability: Literal["process", "sqlite_wal"]
    delivery: Literal["at_least_once"] = "at_least_once"
    history: Literal["retained"] = "retained"
    max_batch: PositiveInt
```

Validation pins the two legal shapes:

- a request has no `reply_to` or sender actor, names the configured recipient
  actor, and carries the originating run/path/port;
- a reply names exactly one request, has the authenticated sender actor, inherits
  the request's run/path, uses the request-pinned reply contract, and never lets
  the caller select its target.

The request message identity is:

```text
digest("channel-message", 1, {
  "invocation_id": invocation_id(run_id, path),
  "channel_id": manifest-pinned capability id,
  "channel_revision": manifest-pinned capability revision,
  "lane": configured lane,
  "interaction": configured human interaction,
  "port": envelope.port,
  "kind": "request",
})
```

One invocation may therefore send at most one request per bound channel, lane,
and port. More messages require explicit ports or more invocations/loop frames;
there is no unstable ordinal or caller-authored idempotency token.

The reply id is `digest("channel-reply", 1, {"request_id": ..., "port": ...})`.
The request pins that reply port and contract. Payload bytes do not participate
in either id, but they are part of exact retry equality.

Wall-clock time is deliberately absent from `ChannelSendIntent`. The trusted
transport stamps `Envelope.created_at` once, when it first appends the message;
reconciliation returns that stored message rather than rebuilding it. This
keeps the effect request and idempotency key stable across process death while
retaining a truthful observation time. An equal logical intent is idempotent;
different payload or routing under one id is `JournalDamaged` inside trusted
storage and a typed conflict at an external control boundary.

Add `ChannelSendSubject` to the existing `ProofSubject` union and add `send` to
the attestation action union. It binds message id, channel id/revision, lane,
interaction, recipient, run id, execution path, port, contract, and payload
digest. The adapter recomputes the message id from those values. `interaction`
is sealed authority metadata: it determines whether the reply must pass the
advice command or the approval command and its corresponding scope. Trusted
deterministic runtime code checks the sealed binding and mints the attestation;
component code and external callers can never author one.

## 6. One channel contract, two transports

Define one L0 `Channel` protocol around observable behavior, not SQLite. The
transport accepts the timestamp-free intent; only it may construct the durable
request message:

```python
class Channel(Protocol):
    @property
    def profile(self) -> ChannelProfile: ...

    def append_request(
        self, intent: ChannelSendIntent, attestation_id: str
    ) -> ChannelMessage: ...
    def message(self, message_id: Digest) -> ChannelMessage | None: ...
    def reply_for(self, request_id: Digest) -> ChannelMessage | None: ...
    def inbox(...) -> tuple[ChannelDelivery, ...]: ...
    def latest_revision(self, actor_id: str) -> ChannelRevision: ...
    def reply(...) -> ChannelMessage: ...
    def acknowledge(...) -> ChannelAck: ...
```

Method arguments are fully typed in implementation; the ellipses above avoid
duplicating the paging tuple in this overview. Shared tests pin canonical bytes,
identity, bounds, ordering, revisions, authorization inputs, write-once equality,
and at-least-once behavior for both implementations.

`ChannelSendEffect`, an L1 `EffectAdapter` registered once as `channel_send`,
owns effect execution and reconciliation. The injection root gives it an
immutable catalog from exact `(channel_id, channel_revision)` pairs to assembled
`Channel` objects. It verifies the attestation and the intent, then performs a
mechanical catalog lookup and append. That is physical dispatch against an
admitted binding, not name resolution or a choice delegated to the walker.
Reconciliation looks up the deterministic message id, validates it against the
timestamp-free intent, and returns the stored observation. Simulation returns a
simulated receipt without consulting or mutating a live channel.

### 6.1 `InProcessChannel`

`substrate/channels/in_process.py` uses an asyncio-safe in-memory append-only
history. Its profile says `durability="process"`; it never pretends to survive a
new process. It exists for same-process composition and contract tests, not as
the human-wait transport.

### 6.2 `MailboxChannel`

`substrate/channels/mailbox.py` uses the same SQLite WAL database as the journal.
It does not own a second database path or schema manager. SQLite persistence is
implemented in a new `_sqlite_channels.py` responsibility mixed into the one
public `SqliteJournal`; this is internal decomposition, not a new L0 store.

Human waiting components declare capability descriptor kind
`channel.mailbox`. Process-local-only components may declare
`channel.in_process`. Both live objects implement the same `Channel` protocol,
and `system.describe()` publishes their honest `ChannelProfile`s. Exact
capability id and revision remain explicit Ref bindings and manifest facts.

## 7. Persistence: append-only facts, not a queue that forgets

SQLite schema 6 adds two tables:

```text
channel_messages(
  message_seq INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT UNIQUE NOT NULL,
  channel_id TEXT NOT NULL,
  lane TEXT NOT NULL,
  interaction TEXT NOT NULL,
  kind TEXT NOT NULL,
  reply_to TEXT,
  recipient_actor_id TEXT,
  sender_actor_id TEXT,
  run_id TEXT NOT NULL,
  path_json TEXT NOT NULL,
  port TEXT NOT NULL,
  type_id TEXT NOT NULL,
  schema_hash TEXT NOT NULL,
  envelope_json TEXT NOT NULL,
  attestation_id TEXT,
  UNIQUE(reply_to)
)

channel_acks(
  ack_seq INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  command_id TEXT NOT NULL UNIQUE,
  acked_at TEXT NOT NULL,
  UNIQUE(message_id, actor_id)
)
```

Requests require their exact send attestation; externally authenticated replies
store no caller-authored attestation. A reply has a unique `reply_to`, enforcing
one reply per request. Foreign keys are not used as a substitute for semantic
validation: storage loads the request and verifies the full relationship in one
transaction.

Acknowledgement is an append-only delivery fact. It never deletes or hides
history from runtime recovery, and it never proves that a component consumed the
payload. A reply atomically acknowledges its request for that actor; explicit
ack exists for notification-only/dismissed messages.

The first inbox page captures `ChannelRevision(message_seq, ack_seq)`. Every
continuation reconstructs that exact vector cut, ordered by
`(message_seq, message_id)`. Later sends, replies, and acks cannot shift, omit, or
duplicate an older page. A fresh query sees the new revision. Future or
incoherent revisions are refused.

Migration 5→6 creates only these empty tables and advances `user_version`. It
does not rewrite runs, commands, approvals, effects, events, manifests,
components, or promotions. Source-schema fixtures prove v0→6, v5→6, reopen,
old-binary refusal, and canonical row preservation.

## 8. Run-originated send and recovery

Raw channel mutation is never handed to component code. `NodeContext` exposes a
bound channel facade for an admitted alias. The facade derives run id, execution
path, channel id/revision, lane, recipient, message id, and contract from the
sealed invocation and capability binding. The component supplies only its
declared output port and payload.

The facade enters the existing effect sequence:

```text
sealed binding check
  → journal-minted ChannelSendSubject attestation
  → prepared EffectRequest(kind="channel_send")
  → ChannelSendEffect dispatch to the exact admitted Channel
  → EffectReceipt
  → reconcile before any retry after unknown outcome
```

The request subject is the canonical `ChannelSendIntent`, so neither wall-clock
time nor an ambient live object enters its identity. Mailbox reconciliation
loads the exact message id and validates its immutable row against that intent.
Found returns `committed`; absent permits execute; contradictory is damage. The
ordinary walker remains the only graph scheduler and existing effect simulation
rules apply. Counterfactual runs call `simulate()` and write no live message or
ack.

Fault probes cover after attestation, after prepared effect, after message
insert, and after effect receipt. A process death at any seam converges on one
message and one receipt.

## 9. Parking and waking without a second scheduler

Generalize the existing `ParkedUnit` rather than introducing a channel-specific
run state:

```python
class ParkedUnit(BaseModel):
    path: ExecutionPath
    reason: ParkedReason
    completed_iterations: PositiveInt | None = None
    waiting_on: Digest | None = None
```

Validation requires `completed_iterations` only for `policy_exhausted` and
`waiting_on` only for advisor/approval waits. Historical M4 payloads retain the
same values and parse unchanged.

A standard waiting component sends/reconciles its request, checks immutable
channel history for the deterministic reply id, and, if absent, raises one typed
`InvocationParked` runtime signal containing the exact request id. The walker
records the ordinary invocation/run parking facts. It does not checkpoint an
output that does not exist and does not hold a coroutine, workspace, lease, or
process open while a human thinks.

An authenticated reply or request-bound approval stores its durable fact first,
then creates a process-local wake intent for that PARKED run at the exact event
fence observed in its immutable command plan. Generalize M6's committed resume
handoff scanner to committed wake-producing command plans. The periodic bounded
scan reconstructs a lost handoff after process death. The exact next attempt
transition records the triggering command id; duplicate discoveries coalesce at
the existing run/event fence.

If the run was manually resumed, cancelled, completed, or advanced before the
wake applies, the reply remains a valid immutable fact and the wake reports
`already_advanced`; it never revives an older attempt. Server shutdown abandons
local wake work without inventing cancellation.

## 10. Human control surface

Add `constructicon:advise` to the known scope set. It is distinct from
`constructicon:approve`; role separation is authority, not UI decoration.

### Reads

| Operation | Scope | Behavior |
| --- | --- | --- |
| `channels_inbox` | derived per row | Actor-derived bounded page at one `ChannelRevision`; it includes only messages whose sealed interaction the actor's scopes authorize, and the caller cannot name another recipient. |
| `channels_message` | derived from request | Exact immutable summary for the recipient actor (or admin) plus digest-bound detail reference; advice requires advise and approval requires approve. |

`DetailResolver` adds `constructicon://channels/messages/<message_id>`. Full
payload remains by-reference. Cursor schema stays 2 and binds actor, endpoint,
query, vector bound, and continuation.

### Mutations

| Operation | Scope | Domain fact |
| --- | --- | --- |
| `channels_reply` | advise | One authenticated, request-derived reply plus request ack and one bounded wake intent. |
| `channels_ack` | derived from request | One exact actor/message acknowledgement under the request interaction's scope. |
| `runs_approve` (extended) | approve | Existing ApprovalRecord; when request-bound, the exact approval reply + ack + wake are one transactional domain application. |

There is no public `channels_send`: outbound requests originate only from a
manifest-bound invocation and the effect law.

Every new mutation follows authorize → lifecycle admission → claim → typed plan
→ apply/reconcile once → exact terminal response. Its plan binds the request
message, recipient actor, run/path, expected reply contract, baseline event
sequence, derived reply id, and wake disposition. The actor never supplies those
fields. Advice requests can be answered only by `channels_reply`; approval
requests can be answered only by request-bound `runs_approve`. Same key/different
payload is an idempotency conflict; a second key for a request already answered
returns a typed `CHANNEL_ALREADY_REPLIED`, never journal damage.

`runs_approve` gains an optional `request_message_id`. Omission preserves the M6
standalone decision behavior and bytes. When present, planning requires an
approval request addressed to the actor and an exact request subject equal to
the command subject. SQLite stores approval, reply, and ack in one transaction;
the in-memory contract uses one critical section. Recovery validates all facts
relationally before completing the command.

MCP adds actor-derived `channels_inbox`, `channels_reply`, and `channels_ack`
handlers/resources that delegate once. No handler opens SQLite, interprets a
cursor, selects a lane, computes a message id, or wakes a run. Stdio and OAuth
identity rules remain unchanged. A human CLI remains a later skin over the same
ControlPlane methods.

Control response schema remains 3. New channel payloads use channel schema 1;
old response models and v1/v2 replay upgrades are byte-identical.

## 11. Human advisor and approval components

Ship two restart-importable standard atomic components:

- `constructicon.std/human-advisor`: accepts one canonical `AdviceRequest`, uses
  a `channel.mailbox` binding, parks on its deterministic request, and returns a
  typed `AdviceResponse` containing actor, advice, optional evidence refs, and
  the reply message id;
- `constructicon.std/human-approval`: accepts an exact `ProofSubject`, emits an
  approval request, parks, and returns the trusted `ApprovalRecord` carried by
  the request-bound `runs_approve` reply. Approved and rejected are both data.

Both components verify the reply's request id, run/path, nominal contract,
authenticated actor, and exact subject before returning. Malformed payload is a
typed component-boundary failure with the message detail reference; it is never
silently repaired or reported as a valid response.

Registration and initial promotion use M6's keyed local commands. No import-time
mutation or transport-only bootstrap path is added.

## 12. Panel is a pattern, not a primitive

Add one L3 `panel()` combinator. It emits only a strict Graph:

```text
panel request
  ├─→ advisor Ref A ─┐
  ├─→ advisor Ref B ─┼─→ explicit aggregator Ref (many input) → panel result
  └─→ advisor Ref C ─┘
```

The combinator takes a name, advisor Refs, and an explicit aggregator Ref. It
does not execute advisors, choose models, hide a scheduler, infer a quorum, or
invent a policy. Every advisor has the same exact request/output contract; the
aggregator's `many` port and the validator's existing nominal binding law prove
the fan-in. SDK and direct Graph forms must be equal.

Expected advisor outcomes are data (`responded`, `declined`, `unavailable`,
`timed_out`) in a complete member-result contract. Advisor adapters are
failure-total for those expected outcomes; unexpected component failure still
uses the walker's complete dependency report. The aggregator returns every
member result plus its explicit policy outcome; partial is never dropped.

Ship a small deterministic quorum aggregator over the canonical panel vote
contract. Quorum is ordinary typed input or a separately registered policy
component, never a hidden combinator default. M7 waits for all declared members;
early quorum cancellation and dynamic membership remain deferred.

The acceptance panel uses credential-free fake advisors plus one mailbox-backed
human advisor. No M8 executor is pulled forward.

## 13. Compatibility and version table

| Contract | M7 decision |
| --- | --- |
| Graph IR | stays schema 1; no construct or field added |
| ExecutionManifest | stays schema 2; existing generic capability bindings pin channels |
| Control responses | stays schema 3; new operations use the current control family |
| Cursor | stays schema 2; `ChannelRevision` is a new bound payload |
| Channel models | new schema 1 |
| Journal events | existing open event schema; new event kinds use strict payload models at owners |
| SQLite | 5→6, additive empty message/ack tables only |
| Component identity | unchanged; new standard components are new definitions |
| Historical approvals | unchanged; request binding is optional and no old row is rewritten |
| M4 parking | old policy-exhausted payloads retain their semantics |

Add an accepted ADR before the first implementation merge because M7 makes new
durable decisions about channel identity, actor-derived routing, retained ack
history, and wake recovery. The ADR records decisions; this plan records build
sequence and acceptance.

## 14. Implementation sequence

Implementation begins only after this plan or a successor is explicitly
approved. Each slice starts from the previous green merge.

### PR A — contracts and transports

- L0 channel models, identity functions, profile, protocol, and channel proof
  subject;
- `InProcessChannel` and shared contract suite;
- schema-6 migration, `_sqlite_channels.py`, `MailboxChannel`, reopen/parity and
  two-process tests;
- introspection profiles and contributor recipe;
- ADR for channel identity/delivery.

No runtime parking, panel, MCP, or human command is added in PR A.

### PR B — bound send, parking, and wake recovery

- manifest-bound NodeContext channel facade and proof-carrying send;
- truthful counterfactual simulation;
- generalized `ParkedUnit` and typed invocation parking;
- committed wake handoff recovery generalized from M6 resume scanning;
- crash seams and hard-death tests.

No external reply API or SDK panel is added in PR B.

### PR C — human control and approval consumption

- advise scope, stable inbox/message reads, detail resources;
- `channels_reply` and `channels_ack` under typed command plans;
- request-bound `runs_approve` transaction and automatic wake;
- MCP delegation and actor/scope/response-loss matrices;
- standard human advisor and approval components.

### PR D — panel pattern and integrated acceptance

- `panel()` Graph sugar and equality tests;
- canonical member/vote/result contracts and deterministic aggregator;
- fake-first advisor + approval end-to-end lanes across process restart;
- current `ARCHITECTURE.md`, `CONTRIBUTING.md`, planning index status, and M7
  implementation record.

Mechanical compression found during M7 stays behind behavioral proof and does
not share a commit with a schema or authority change.

## 15. Required failure proof

### Shared channel contract

- identical request/reply/ack retries return one exact fact;
- contradictory logical intent under one derived id is damage internally and a
  typed conflict externally; a reconstructed send does not invent a new time;
- request and reply identities remain stable across process restart and loop
  frames remain distinct;
- bounds reject zero, negative, and excessive sizes;
- inbox order is total for tied timestamps because it uses durable sequence;
- an old `ChannelRevision` neither absorbs nor loses a later message or ack;
- a future/incoherent revision is refused;
- ack never removes history and never claims component consumption;
- InProcess honestly loses state with a new instance; Mailbox survives reopen.

### Authority and typing

- a node with no sealed channel binding cannot send;
- a caller cannot select actor, recipient, lane, channel id, run id, path,
  contract, request id, reply id, or wake fence;
- wrong actor, wrong scope, wrong request kind, wrong reply contract, wrong
  subject, and cross-run reply are refused before mutation;
- a caller-authored ChannelSendSubject or attestation cannot authorize send;
- counterfactual send records only a simulated receipt and no channel row;
- malformed reply payload never becomes a successful typed component output;
- MCP handlers delegate once and have no store/routing imports.

### Crash and concurrency

- crash after send attestation, prepared effect, message insert, and effect
  receipt converges to one message/receipt;
- reply and ack pass plan/domain/completion response-loss seams;
- request-bound approval passes the same seams with one ApprovalRecord, reply,
  ack, and wake intent;
- two processes replying concurrently admit one exact reply; the loser receives
  a typed terminal result;
- process death after committed reply but before local launch is recovered by
  another host;
- reply/manual-resume and reply/cancel races never revive an older fence;
- shutdown abandons local workers while the PARKED run and messages remain.

### Panel and human round trips

- SDK panel Graph equals the direct Graph byte-for-byte;
- second compatible producers still trigger the existing ambiguity fault unless
  the `many` aggregator binding is exact;
- every declared member appears in the aggregate result, including expected
  unavailable/timeout outcomes;
- a human advisor parks with `awaiting_advisor`, survives reopen, replies, and
  completes one later attempt;
- a human approval parks with `awaiting_approval`; rejected and approved records
  both return as exact data;
- duplicate discoveries, replies, commands, and wake scans create one attempt;
- a freshly registered component candidate still never resolves through a bare
  Ref (the historical channel-name regression remains pinned).

### Migration and compatibility

- source schemas v0 through v5 migrate to 6 with old semantic rows unchanged;
- a schema-6 database is refused by an old binary;
- M1–M6 manifests, commands, approvals, effects, and registry snapshots reopen
  and replay without rewrite;
- M4 policy-exhausted parking and M6 resume-command receipts remain exact.

## 16. Acceptance gate

M7 is complete only when:

1. all four implementation slices are merged from the same approved plan line;
2. `uv run verify` passes with Ruff, strict mypy, import-linter, and the full
   credential-free suite;
3. the two-process mailbox/advisor/approval acceptance lane passes repeatedly
   without timing sleeps as correctness;
4. the public Graph and manifest schemas are unchanged;
5. every new mutation has all three response-loss seams and actor/scope tests;
6. SQLite migration/reopen fixtures prove additive schema-6 behavior;
7. current architecture, contributor guidance, accepted ADR, and implementation
   record describe the code that actually landed.

## 17. Review checklist

Review must answer explicitly:

- Does the request/reply identity permit every M7 use without an unstable
  sequence or caller-authored authority?
- Is one-reply-per-request the correct M7 boundary, with multi-round debate
  honestly deferred?
- Does the channel-send attestation bind every value an adapter could otherwise
  redirect or substitute?
- Are retained history and vector-cut ack semantics sufficient for two-process
  recovery without destructive dequeue?
- Does automatic wake reuse M6 fencing without turning RunHost into a second
  scheduler?
- Can request-bound `runs_approve` preserve every legacy call and durable row?
- Does `panel()` remain literal Graph sugar with explicit aggregation policy?
- Are any M8 executor or M9 learning concerns leaking into this milestone?

An approval with redlines produces rev 2. This rev 1 file then remains immutable
and is marked superseded in the planning index; it is never edited into a
fictional approved document.
