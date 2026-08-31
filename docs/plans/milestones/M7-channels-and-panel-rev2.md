# M7 — channels and panel rev 2

**Status:** review draft; supersedes rev 1. Slices A and B are merged; C and D
await an explicit approval decision

**Planning base:** `e0053a2` (`main` after PR #15 and PR #16)

**Scope:** typed message channels, durable human round trips, and an
ordinary-Graph panel pattern

**Authority:** `docs/INVARIANTS.md` → `docs/ARCHITECTURE.md` → accepted ADRs →
code/tests → this draft

Rev 1 was written against the M6 codebase before any of it was built.
Implementation found seven places where it could not be followed as written;
[rev 1](M7-channels-and-panel-rev1.md) remains immutable and the
[M7 implementation record](../handoffs/M7-implementation-record.md) lists each
deviation with its cause. This revision absorbs them so slices C and D are
planned against what the code actually is.

## 1. What rev 1 got wrong

Every item was a defect in the plan, not a shortcut in the implementation.

| Rev 1 said | Why it could not stand | Rev 2 |
| --- | --- | --- |
| `ChannelSendIntent.channel_revision: Digest` | It mirrors `CapabilityBinding.revision`, which is `str` | `str` |
| `ChannelContract.schema_hash: Digest` | Nominal identity here is `Port.schema_hash: str` | `str` |
| `channel_messages` DDL omitted the reply half | § 5 gained `reply_contract`/`reply_port`; § 7 was never updated | adds `reply_port`, `reply_type_id`, `reply_schema_hash` |
| `ChannelDelivery {message, acknowledged}` | `inbox(after=…)` needs a key no returned value carried | adds `message_seq` |
| "ExecutionManifest stays schema 2" | A binding carrying a channel is unreadable by a pre-M7 build | schema 3 **iff** a channel is bound |
| "`parked_waits` with in-memory/SQLite parity" | There is no in-memory `Journal` | the durable read plus the `FakeJournal` read-surface double |
| The facade derives lane/recipient/contract "from the sealed invocation and capability binding" | `CapabilityBinding` carried none of the three | assembly supplies `ChannelEndpoint`; admission compiles it and the exchange |

`ParkedWait` likewise carries `created_at` and a `key`, for the reason
`ChannelDelivery` carries `message_seq`: a page whose reader must re-read a row
to keep paging is not pageable.

## 2. Established authority (slices A and B, merged)

These are no longer proposals. They are the contracts C and D build on.

**Identity is derived and is a bytes law.** A request id comes from
`invocation_id(run_id, path)` plus channel id/revision, lane, interaction, and
port; a reply id from `digest("channel-reply", 1, {request_id, reply_port})`.
Retry equality compares canonical bytes, never `BaseModel.__eq__`, because
Python equality holds `1 == True` and `1 == 1.0` while canonical JSON does not.
A transport re-derives an intent's id rather than trusting it.

**Routing is a manifest fact.** `ChannelEndpoint(lane, interaction,
recipient_actor_id)` is supplied by assembly on a `CapabilityDescriptor` and
compiled by admission into the scoped `CapabilityBinding`. Capability bindings
participate in manifest identity, so divergent assembly changes `manifest_hash`
rather than silently deriving a second message; activation compares the live
endpoint against the sealed one, because a revision is only a string.

**The exchange is compiled, never named at call time.** A channel-bound atomic
component declares exactly one input and one output; admission compiles that
pair with both nominal contracts into the binding. Pinned source is not pinned
behavior, so a component free to name its own port could branch differently on a
second host and append a second request. Components needing more ports compose
(I10). The whole component surface is `await ctx.channel(alias).ask(payload)`.

**Waiting is not failing.** `InvocationParked` names the exact request; the
walker records parking facts and checkpoints nothing, and holds no workspace,
lease, or coroutine open.

**Wake recovery reads durable domain facts.** `Journal.parked_waits` projects
PARKED runs and their latest exact `RunParked` event; `answered_requests` says
which of those requests already carry a reply, validating the derived reply id
rather than trusting a `reply_to` pointer. A bounded scan wakes the run at the
projection's event fence, keeping its cut across ticks. PARKED never joins the
ordinary recovery statuses. One `AttemptCause` names why an attempt started —
M6's committed resume command, byte-identical, or M7's stored reply.

**Only the sealed recipient may answer.** One reply per request is a hard
constraint, so an unaddressed request is the only one open to any authenticated
actor. One delivery fact has one owning command.

## 3. Slice C — human control surface

Unchanged from rev 1 in intent. Corrected in three places.

Add `constructicon:advise` to the known scope set, distinct from
`constructicon:approve`.

| Operation | Scope | Behavior |
| --- | --- | --- |
| `channels_inbox` | derived per row | Actor-derived bounded page at one `ChannelRevision`; only messages whose sealed interaction the actor's scopes authorize; the caller cannot name another recipient |
| `channels_message` | derived from request | Exact immutable summary plus digest-bound detail reference |
| `channels_reply` | advise | One authenticated request-derived reply plus request ack and one bounded wake intent |
| `channels_ack` | derived from request | One exact actor/message acknowledgement under the request interaction's scope |
| `runs_approve` (extended) | approve | Existing `ApprovalRecord`; when request-bound, the approval reply, ack, and wake are one transactional domain application |

There is no public `channels_send`: outbound requests originate only from a
manifest-bound invocation and the effect law.

**Corrections to rev 1's § 10–11.**

1. A cursor for `channels_inbox` must carry the exact continuation key
   `Channel.inbox` publishes: `(delivery.message_seq,
   str(delivery.message.message_id))`, matching its `tuple[int, str]` parameter
   and its `(message_seq, message_id)` ordering. Naming the sequence alone would
   lean on its being unique today rather than on the published contract, and a
   page-position count is wrong outright — an actor's messages are sparse in
   shared history, so counting rows redelivers.
2. `runs_approve` already accepts any `ProofSubject`, and M7 widened that union
   with `ChannelSendSubject`. Request-bound approval must therefore refuse a
   subject that is not the one its request pinned, rather than relying on the
   union to constrain it.
3. The two standard components (`constructicon.std/human-advisor`,
   `constructicon.std/human-approval`) must each declare exactly one input and
   one output, because that is what admission requires of a channel-bound
   component. Their request contract is the input and their reply contract is
   the output; a reply cannot arrive into an input, because a non-optional input
   must already be bound before the invocation starts.

Reply validation at the component boundary is nominal — request id, run/path,
nominal contract, authenticated actor, exact subject. Deep payload-schema
validation is not attempted and must not be claimed.

## 4. Slice D — panel pattern and integrated acceptance

Unchanged from rev 1. `panel()` emits only a strict Graph: a request fanned out
to advisor Refs and gathered by an explicit aggregator Ref with a `many` input.
The combinator executes nothing, chooses no model, infers no quorum, and hides
no scheduler. SDK and direct Graph forms must be byte-equal.

Expected advisor outcomes are data (`responded`, `declined`, `unavailable`,
`timed_out`); the aggregator returns every member result plus its explicit
policy outcome. M7 waits for all declared members; early quorum cancellation and
dynamic membership stay deferred.

One correction: a panel of human advisors is several channel-bound components,
and each addresses its own participant, so each needs its own capability id
carrying its own `ChannelEndpoint`. That is correct rather than incidental —
`recipient_actor_id` does not participate in the request id, so sharing one
channel id across recipients would collide.

## 5. Compatibility and version table

| Contract | M7 decision | State |
| --- | --- | --- |
| Graph IR | stays schema 1 | held |
| ExecutionManifest | schema 3 iff a channel is bound; otherwise 2, byte-identical | done |
| Control responses | stays schema 3 | C |
| Cursor | stays schema 2; `ChannelRevision` is a new bound payload | C |
| Channel models | new schema 1 | done |
| SQLite | 5 → 6, additive empty message/ack tables | done |
| Component identity | unchanged; no new field | done |
| Historical approvals | unchanged; request binding is optional | C |
| M4 parking | old policy-exhausted payloads retain their semantics | done |

[ADR 0014](../../adr/0014-channel-identity-and-delivery.md) records the accepted
channel identity and delivery decisions. A successor ADR is required before
slice C only if request-bound approval changes approval authority.

It does: a sealed request became a second authority source for an
`ApprovalRecord`, deciding who may write one and what it may decide. Recorded as
[ADR 0015](../../adr/0015-human-authority-on-channels.md).

## 6. Implementation sequence

- **PR A — contracts and transports.** Merged as #15.
- **PR B — bound send, parking, and wake recovery.** Merged as #15 and #16.
- **PR C — human control and approval consumption.** Advise scope, stable
  inbox/message reads, detail resources, `channels_reply` and `channels_ack`
  under typed command plans, request-bound `runs_approve`, MCP delegation and
  actor/scope/response-loss matrices, and the two standard components.
- **PR D — panel pattern and integrated acceptance.** `panel()` sugar and
  equality tests, canonical member/vote/result contracts and a deterministic
  aggregator, fake-first advisor and approval lanes across process restart, and
  the closing documentation and record update.

Mechanical compression found during C or D stays behind behavioral proof and
does not share a commit with a schema or authority change.

## 7. Required failure proof

### Already proven (A and B)

Identity and retry equality including JSON scalar types; reconstructed sends at
every crash seam with one message, one receipt, and the original observation
time; causally coherent revisions; one owning command per delivery fact; sealed
recipient enforcement; sealed routing in manifest identity and at activation;
parking without a checkpoint; wake from durable facts past the per-tick page
budget; a reply validated against the request it claims to answer; migration
v0–v5 → 6 with unchanged rows and a refusal that touches nothing.

### Slice C must add

- a caller cannot select actor, recipient, lane, channel id, run id, path,
  contract, request id, reply id, or wake fence;
- advice requires advise and approval requires approve; the wrong scope, wrong
  actor, wrong request kind, and cross-run reply are refused before mutation;
- `channels_reply`, `channels_ack`, and request-bound `runs_approve` each pass
  the plan, domain, and completion response-loss seams and replay one exact
  fact;
- request-bound approval refuses a subject its request did not pin;
- an inbox cursor continues correctly for a sparse recipient and never
  redelivers;
- a malformed reply payload never becomes a successful typed component output;
- MCP handlers derive their actor, delegate once, and hold no store or routing
  import.

### Slice D must add

- the SDK panel Graph equals the direct Graph byte-for-byte;
- a second compatible producer still raises the existing ambiguity fault unless
  the `many` aggregator binding is exact;
- every declared member appears in the aggregate result, including expected
  unavailable and timed-out outcomes;
- one advisor round trip and one approval round trip complete across a real
  process restart, credential-free.

## 8. Review decision requested

1. approve rev 2 for slices C and D;
2. approve with redlines, producing rev 3 while preserving this file;
3. reject with the violated invariant or missing contract named.

Slices A and B are merged and are not reopened by this decision. What is being
approved is the corrected authority they established plus the plan for C and D.
