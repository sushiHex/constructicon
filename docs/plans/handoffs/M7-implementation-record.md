# M7 implementation record

**Plan:** [M7 channels and panel rev 1](../milestones/M7-channels-and-panel-rev1.md)  
**Starting commit:** `0765072b83557aa2367732bb8cd8ec33d4962009`  
**Nature:** implementation record; the plan remains a review draft, and this
records the deviations that implementation forced

## Scope completed

Plan slices PR A and PR B. Typed message channels with two transports, routing
and its exchange sealed into the manifest, proof-carrying sends through the
existing effect law, typed invocation parking, and reply-driven wake recovery.

PR C (human control surface) and PR D (`panel()`) are not started.

- One L0 `Channel` contract with `InProcessChannel` and `MailboxChannel`,
  exercised by a single parity suite. Both derive messages from the same
  contract-level constructors, so parity is structural rather than a duplicated
  law that could drift.
- SQLite 5 → 6, additive: two empty tables and a version bump. No run, command,
  approval, effect, event, manifest, component, or promotion row is read or
  rewritten, and a database newer than the build is refused before any pragma
  writes.
- `ChannelSendSubject` joins `ProofSubject`; the attestation action union gains
  `send`. Existing merge and promote drafts serialize byte-identically, so
  historical attestation ids are unchanged.
- `await ctx.channel(alias).ask(payload)` is the entire component surface.
- `Journal.parked_waits` plus a bounded PARKED scan wake a run from durable
  domain facts alone, independent of command state.

## Deviations from the plan

Each is a defect in the plan rather than a shortcut in the implementation. A
rev 2 should absorb them before PR C.

| Plan says | Why it cannot stand | Implemented |
| --- | --- | --- |
| `ChannelSendIntent.channel_revision: Digest` | It mirrors `CapabilityBinding.revision`, which is `str`; a revision like `"1"` is not a digest | `str` |
| `ChannelContract.schema_hash: Digest` | The repo's nominal identity is `Port.schema_hash: str`; a real port's schema revision could never be read into a contract | `str` |
| `channel_messages` DDL (§ 7) | § 5 gained `reply_contract`/`reply_port`, but § 7 was never updated, so the pinned reply half would not persist | adds `reply_port`, `reply_type_id`, `reply_schema_hash` |
| `ChannelDelivery {message, acknowledged}` | `inbox(after=...)` takes `(message_seq, message_id)`, which no returned value carries; an actor's messages are sparse in shared history, so a page-position cursor redelivers | adds `message_seq` |
| "ExecutionManifest stays schema 2" | A binding carrying a channel is not readable by a pre-M7 build, so schema 2 would make the refusal an opaque parse error | schema 3 **iff** a channel is bound; otherwise 2 and byte-identical |
| "`parked_waits` with in-memory/SQLite parity" | There is no in-memory `Journal`; `SqliteJournal` is the only implementation | the durable read plus the `FakeJournal` read-surface double, which is the I6 second consumer |
| The send facade derives lane, recipient, and contract "from the sealed invocation and capability binding" | `CapabilityBinding` carried none of the three, and no admitted place existed for them | assembly supplies `ChannelEndpoint`; admission compiles it and the exchange into the binding |

`ParkedWait` also gained `created_at` and a `key` property for the same reason
`ChannelDelivery` gained `message_seq`: a page whose reader must re-read a row
to keep paging is not pageable.

## Decisions worth preserving

**Routing is a manifest fact, not a live-object detail.** Putting lane and
recipient on the assembled channel object looked simpler and satisfies I1, but
`CapabilityDescriptor.revision` is only a string and activation compared only
that string. Two hosts assembling one manifest with different routing would
diverge, and the lane case fails *silently*: lane participates in the request
id, so a changed lane derives a different id and appends a second message with
no equality conflict to catch it. Compiling routing into `CapabilityBinding`
makes divergence a `manifest_hash` disagreement instead, and activation now
compares the live endpoint against the sealed one.

**The exchange is compiled, never named at call time.** Letting a component
name its own ports keeps the ports sealed by `contract_hash`, but pinned source
is not pinned behavior: a state- or time-dependent branch could select a
different declared port on a second host and, because `port` is in the request
id, append a second request that no fence would catch. Admission therefore
requires a channel-bound component to declare exactly one input and one output
and compiles that pair. Components needing more ports compose (I10).

**One `AttemptCause`, not a second parallel parameter.** M6 continues to
serialize its exact legacy `resume_command_id`; M7 records `reply_message_id`,
the immutable fact the scan observed. No command lookup reconstructs a reply
wake.

**Identity is a bytes law.** `BaseModel.__eq__` compares payloads with Python
semantics, where `1 == True` and `1 == 1.0`. Those are distinct canonical JSON
facts, so model equality accepted a genuinely different intent as an idempotent
retry and returned the wrong payload. Retry equality compares canonical bytes.

## Strengthened failure proof

Beyond the plan's list, these are pinned because review found them broken:

- a reconstructed send returns the original message and stamps no second
  observation time — at every one of the four send seams;
- only a request's sealed recipient may answer it; one reply per request is a
  hard constraint, so an unchecked actor could have locked the recipient out;
- a channel revision must be causally coherent, not merely within bounds;
- one delivery fact has one owning command, so no command id addresses two
  messages;
- a transport re-derives an intent's message id rather than trusting it, because
  `model_copy` and `model_construct` skip validators;
- no `ChannelSendIntent` field escapes both the derived id and retry equality —
  a property test, so a future field cannot silently reopen the hole.

## PR C — the human read surface

**An advisor is its own role, not an observer with extra rights.** I9 names
observer, advisor, and approver as three participations, and `allows()` has no
scope implication: `constructicon:advise` neither grants nor requires
`constructicon:read`. `channels_inbox` and `channels_message` therefore
authorize on the interaction scopes alone, so a human advisor holds one scope
and reads only its own work.

That relaxation had to be paid for. `details_read` and `resource_read` gated
every family on read, and the run, event, result, approval, attestation, and
component branches of `DetailResolver._resolve` carried no actor check because
that outer gate protected them. Simply opening the door for channel details
would have handed an advise-only actor every run in the store. The read check
moved into `_resolve`, where the family that owns a fact holds its own lock; the
door now only asks whether the actor may read any family at all.

**One authorization law, four surfaces.** `authorized_delivery` is the single
entry to page, message, detail, reply, and ack. A reply carries no recipient of
its own — it is addressed to the run, not a person — so `governing_request`
validates the request it answers in full and authority is read from that. The
sharing is not tidiness: `ChannelMessageSummary.detail` is a required reference,
so a page whose law disagreed with the detail resolver's would raise
`JournalDamaged` on a legitimate page rather than merely refuse a read.

**A cursor is a self-checking envelope, not an authority token.** Its checksum
detects corruption, never forgery, so an inbox cursor re-validates every field
it carries and binds both halves of the reader's authority: the codec binds
`actor_id`, and the normalized authorized-interaction set rides in the query
hash. A page cannot be resumed across identities, and a scope change refuses
rather than silently narrowing a stream mid-walk. The cut travels as
`ActorInboxRevision.model_dump(mode="json")` and is validated by that model, so
there is no second hand-written schema to drift from it.

**An empty page and a refusal are different claims.** Holding no interaction
scope is refused; an advise-only actor with only approvals pending gets an empty
page. The first says the surface is not yours, the second says nothing here is
your work. Scope filtering happens inside the bounded query, so `limit` counts
rows the reader may actually see.

## Open items

- PR C mutations (`channels_reply`, `channels_ack`, request-bound
  `runs_approve`), MCP delegation, the two standard components, and PR D remain.
- **Unaddressed requests are answerable but not discoverable.** Rev 2 states an
  unaddressed request is the only one open to any authenticated actor, and both
  `channel_authority_holder` and `message_for_reply` implement that. But both
  transports' inboxes filter `recipient_actor_id = actor_id`, so a request
  addressed to no one appears in no inbox: it can be answered only by an actor
  who learned its id elsewhere. Whether the inbox should surface it to every
  holder of the interaction scope, or whether a panel is expected to address
  each member explicitly, is not settled by the plan. Left as it was rather than
  changing a merged transport contract on one reading.
- A message a caller may not act on is refused with `AUTH_REQUIRED_SCOPE` rather
  than reported absent, which confirms that a supplied id exists. Deliberate:
  ids are derived digests over run, path, channel, lane, interaction, and port,
  so an id cannot be guessed without already knowing the message, and a sealed
  recipient holding the wrong scope needs to be told which scope, not sent
  chasing a phantom.
- Nominal reply-contract checking is enforced at the facade; deep payload-schema
  validation is not attempted and is not claimed.
- The wake scan fails closed on a damaged parking event, consistent with the M6
  committed-resume scan. The blast radius — one bad row stopping recovery for
  unrelated runs — is the same accepted trade, not a new decision.
