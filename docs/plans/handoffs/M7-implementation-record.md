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

**An open request is discoverable, not merely answerable.** A request sealed to
no recipient is a routing decision assembly made — this is anyone's to take —
not routing that went missing, so `discoverable_by` puts it in the inbox of
every actor holding the interaction's scope. Leaving it findable only by whoever
was handed its digest would make an approved decision reachable by leak alone,
which I9's discoverability requirement does not permit. Panel members stay
explicitly addressed in PR D; an open request is the exception, not the pattern.

The predicate names its kind rather than its null:

    recipient_actor_id = :actor_id
    OR (kind = 'request' AND recipient_actor_id IS NULL)

A reply carries a null recipient too, for the opposite reason — it is addressed
to the run rather than withheld from a person — so matching nulls alone would
broadcast every reply to every actor. The `kind` test is the whole guard, and a
regression pins it in both transports and in the cross-channel inbox.

SQL is a second expression of that one law, so every row a page returns is
re-checked against `discoverable_by` itself and a disagreement raises
`JournalDamaged`. Over-inclusion is the direction that leaks, and this is the
same discipline `validated_reply` applies to a stored pointer: the rule lives in
one place, and the query answers to it.

## PR C — answering and acknowledging

**One dispatch rule, stated rather than emergent.** `REPLY_CONSUMES` and
`ACK_CONSUMES` sit beside each other at the top of the command executor.
`channels_reply` consumes advice and nothing else: an approval is answered by
request-bound `runs_approve`, so possessing approve must never turn this into a
generic reply path. An acknowledgement is a delivery fact and both interactions
are delivered, so both are ackable, each under the scope its own request seals.

**A reply is actionable by nobody.** No inbox surfaces one, so acknowledging a
reply would record a delivery that never happened, and replying to one is
incoherent. `_actionable_request` refuses a reply id for both mutations —
decided in one place rather than inherited from the shared resolver, which would
happily govern a reply by the request it answers.

**Refusal order is kind, then interaction, then authority — all before the
claim.** None of the three is a domain outcome, so none writes a durable command
record or burns an idempotency key: the same key still works against the
operation that does consume the message. Order matters as much as timing.
Refusing an approver for lacking advise would be true and useless, because
acquiring advise still would not make this the operation that consumes an
approval. Both channel mutations therefore share one deliberately coarse door —
any interaction scope — and the exact scope is derived once, from the governing
request, after the wrong interaction has already been refused.

**The plan decides everything; the caller chose a payload.** Channel, sealed
interaction, actor, derived reply identity, reply port, run, and the parking
fence are all read off the request at plan time. Replay re-reads that request and
refuses a plan that drifted from it, then checks the whole relationship rather
than mere existence: `channel_reply_for` rebuilds the reply from its request, and
the stored reply must additionally carry this command's derived id, its sender,
its planned payload, and the request ack that shares its transaction.

**A different command after an admitted reply is a lost race.** One reply per
request is a hard constraint, so a fresh command that finds a stored reply
returns `CHANNEL_ALREADY_REPLIED` before applying anything. A command that
already planned takes the replay path instead, so a crash between plan and apply
still converges on one fact. The same shape holds for `channels_ack`: one
delivery fact has one owning command, and a second command over it is a typed
idempotency conflict, never damage.

**The wake is a courtesy, not the mechanism.** The reply itself is the durable
wake — `_scan_answered_waits` reads domain facts and never command state, so a
death before the command completes still wakes the run. The command additionally
launches one intent pinned to the fence its plan recorded, which only spares the
human the scan interval and cannot revive an attempt the run has moved past.

## PR C — a decision that is also an answer

**Absent, not null.** A standalone M6 decision must hash to exactly the request
it always hashed to, so `request_message_id` is omitted from the command request
rather than serialized as null, keeps `_ApprovalPlan` as its own plan family, and
`ApprovalCommandResult.reply` uses the wrap serializer that drops the field when
it is None. Hashing a null would have changed the command id of every decision
already recorded under an existing idempotency key.

**Bound approval is the mirror of `channels_reply`, not a superset.**
`APPROVE_CONSUMES` is `{"approval"}`, so an advice request is refused here
exactly as an approval request is refused there, through the same
`_actionable_request` law and in the same order: kind, interaction, authority.

**Nominal typing keeps a governance fact out of a lookalike conversation.**
`APPROVAL_REQUEST_CONTRACT` and `APPROVAL_REPLY_CONTRACT` live in `core/human.py`
so the executor and the standard component cannot drift: an approval reached
through `runs_approve` and one reached through `constructicon.std/human-approval`
are the same exchange or they are not the same exchange at all. A request with an
approval interaction but different contracts is refused.

**The subject is compared as canonical bytes.** `1 == True` and `1 == 1.0` are
Python facts rather than JSON ones, so model equality would accept a decision
about a subject the request never pinned — the same hole `same_message` closed
for retry equality. `ApprovalRequestPayload.subject` is therefore plain JSON,
typed as `JsonValue`, precisely so the comparison cannot be written the wrong way.

Contract, payload shape, and subject are all properties of the request rather
than outcomes of the decision, so all three refuse before the claim: no command
record is written and the idempotency key stays reusable.

**Three facts, one commit.** `store_approval_exchange` writes the
`ApprovalRecord`, the reply, and the request acknowledgement inside one
transaction. Composing `store_approval` with `channel_reply` would commit twice,
and a death between them would leave an approval authorizing an exchange nobody
answered. `reply_in_transaction` exists at connection level for exactly this: the
reply law lives in one place and a second caller composes one commit rather than
copying it. The deciding actor is read off the approval record, so the reply's
sender and the acknowledgement's owner cannot disagree with the record that
authorizes them.

Reconciliation reads all three back and validates them relationally and
byte-for-byte. A fresh command that finds another command's reply first requires
that triple to be whole — a reply whose own sender never acknowledged the request
could not have committed, so it is damage rather than a race this command lost.

Approved and rejected are ordinary data throughout: nothing branches on the
decision, and both wake the parked run identically.

**One run, named three ways.** A bound decision names a run, the request belongs
to a run, and the wake fence is taken from the request. Each was checked against
its own source, and nothing required them to be the same run — so a request for
run A could be decided under run B whenever B existed, committing a governance
record claiming B while the reply it wrote was delivered to and woke A. The
request's run is now required to equal the command's before the claim, and the
plan additionally requires `approval.run_id == plan.run_id ==
sealed.envelope.run_id`. The full-record payload is what made this visible: a
component returning the record must be able to trust it belongs to its own run.

The pre-claim refusal is pinned by a regression with two real runs — so it
refuses on authority rather than existence — asserting no command, approval,
reply, or acknowledgement is written and that the key still works against the
correct run. The plan-validation equality is defence in depth: with the
pre-claim boundary in place it is unreachable through the public API, so it is
deliberately not claimed as test-pinned. It guards a plan written before the
rule existed or a store edited beneath the command, which is what every other
branch of `_validate_command_plan` guards.

## A payload is caller-authored; authorship is not

`Channel.ask` hands a component the reply's payload and nothing else. That
narrowness is the point — widening it would put the whole message inside every
component's reach — but it means anything a component may *promise* about
authority has to be written into the payload by the executor, from
authenticated and stored facts, rather than accepted from whoever answered.

`ApprovalDecisionPayload` therefore carries the whole `ApprovalRecord`, derived
from the stored record, not a bare decision. The standard component can parse
it, compare its subject against the one it asked about, and return a governance
fact an auditor can follow — while the transport and runtime boundary keep
validating the request, run and path, contract, and sender relationship.

`AdviceReplyPayload` applies the same law to advice: the advisor writes
`advice`, and the executor stamps `actor_id` from the authenticated command and
`message_id` from the derived reply identity. An answer that names an actor
inside its own payload is data, not a claim — the stamped fields overwrite
nothing and are read from nothing the caller supplied. `message_id` is carried
rather than recomputed in the component so the reply identity law stays in one
place.

Only the canonical advice exchange is stamped. `sealed_reply_payload` reads the
request's sealed reply contract and passes every other advice channel's answer
through verbatim — the contract decides what a reply is, here as everywhere.

Both payload laws live in `core/human.py` beside the contracts they serve, so
the executor and the components call the same functions. A plan records the
*stored* payload, and replay re-derives it from the canonical command request
rather than trusting what the plan holds: a plan is never its own evidence.

## PR C — the transport and the two standard components

**MCP carries the surface and none of its authority.** Four channel tools, one
detail resource, and `request_message_id` on `runs_approve`. Three proofs are
read off the source rather than asserted in prose: every channel handler is a
single return whose call names the same operation on `control`; none takes an
actor or a routing argument; and the module contains no identity derivation,
cursor, revision, transport, journal call, or the authorization law itself. The
scope matrix then runs through the transport that will actually be used, and
advise, approve, and read behave as three independent authorities.

**The standard components hold no authority either.** Each declares exactly one
input and one output — which is what lets admission compile its exchange with
nothing left to choose at call time — and both ports are typed by the shared L0
contracts, so executor and component type the same exchange or type nothing.
Both reach only the narrow facade: no journal, no store, no transport, no
identity law, one `ask` each.

`human-advisor` returns the authorship the executor stamped, proven by answering
with `actor_id: static:impostor` and getting `static:advisor` back. It still
validates what it returns, so a payload written straight to the transport that
is not an `AdviceReplyPayload` fails the run rather than becoming an output (I4).

`human-approval` returns the trusted `ApprovalRecord` and compares its subject
against the one it asked about as canonical bytes. The transport already proved
the reply belongs to this request, run, and path; only the request knows what it
asked. A record about another subject fails the run.

**Nothing registers at import.** Restart recovery re-imports the module named by
a stored `PythonRef` precisely because importing must not mutate, so
`definitions()` returns bundles and a launcher decides. Checked structurally,
since the module is already imported by the time an assertion could run, and
proven end to end: one process asks and parks, a second process over the same
database imports the component, decides, and completes the run.

## PR C — what the complete-head review found

Codex reviewed the whole branch and blocked it. Six findings were real and are
fixed; three are recorded as accepted, with the reasoning.

**An acknowledgement had been consuming the right to answer.** Acknowledging a
request wrote a delivery fact owned by that command, and the reply then tried to
claim the same row under its own command and conflicted — so an actor who
acknowledged a request before answering it could never answer it, and for an
addressed request nobody else could take it up. A reply does not *claim* a
delivery fact, it implies one: an actor that answers a request plainly received
it. The law split into `_claim_acknowledgement`, which one command owns, and
`_imply_acknowledgement`, which is satisfied by whoever recorded it first.

**A lost race escaped as an exception.** Preflight and the domain write are not
one transaction, so two commands could both pass the already-replied check. The
loser hit `ChannelReplyConflict` uncaught, keeping a planned command whose
retries hit the same exception. Both reply paths now convert it to
`CHANNEL_ALREADY_REPLIED`, so a race loser learns it lost the way a late caller
does.

**The standard components were capability-opaque.** `capability_requirements is
None` means *historical*, not *authority-free*: admission then validates no
alias, no kind, and no extra binding, so a graph could bind these newly
introduced components any capability it liked — an I3 violation, and it made
"holds no authority of its own" false as encoded. Both now declare the one alias
they need, of kind `channel.mailbox`. The kind is not incidental: a human waits
across process death, and `channel.in_process` honestly declares
`durability="process"`.

**A foreign triple was checked two-thirds of the way.** `_require_whole_exchange`
verified the reply and the acknowledgement but never the approval, so a raw
transport write producing reply+ack would have been classified as a complete
foreign decision rather than damage. The third fact is now reached from the
reply: its sender names the acknowledgement, and the acknowledgement names the
command that must also have written the approval.

**A record could claim another run.** `human_approval` compared the subject but
not the run. The transport proves the *reply* belongs to this run; the record
inside it is separate data, so it must say so too or the component returns a
governance fact about another run.

**The result alias resolved before its family authorized.** Moving the read gate
into `_resolve` left `_canonical_uri` — which reads the run record, its status,
and its terminal event to pin a result alias — running ahead of it. An
advise-only actor could distinguish unknown run, non-terminal run, and terminal
run before being refused. The family lock now applies wherever a URI first
reaches the journal, not only where it resolves.

### Accepted, not fixed

- **A forged cursor can skip or duplicate the caller's own rows.** The codec
  says plainly that it is not an authority token, and the review confirmed no
  route to another actor's or interaction's rows: those come from the
  authenticated actor on every call, never from the cursor. Making continuation
  unforgeable needs a keyed MAC, which every paged surface would share; that is
  a system decision, not a PR C fix.
- **An administrator can act on an addressed message by id but not discover it
  in an inbox.** An inbox is the actor's own work queue; making an admin's
  contain every message addressed to anyone would be worse than the asymmetry.
  Stated here rather than changed.
- **`sealed_reply_payload` keys on the reply contract alone.** That is the
  contract which promises authorship, so it is the one that decides whether a
  reply carries it. The request contract does not enter into what a reply is.

The review also noted that the byte-identity claim for a standalone decision is
pinned by field absence and plan kind rather than by comparison against an M6
golden artifact. The M6 seam tests do compare stored response bytes, so the
claim is carried by the older suite rather than by the new test.

## Open items

- PR D remains: `panel()` sugar, the deterministic quorum aggregator, and the
  integrated acceptance lane.
- A message a caller may not act on is refused with `AUTH_REQUIRED_SCOPE` rather
  than reported absent, which confirms that a supplied id exists. Deliberate:
  ids are derived digests over run, path, channel, lane, interaction, and port,
  so an id cannot be guessed without already knowing the message, and a sealed
  recipient holding the wrong scope needs to be told which scope, not sent
  chasing a phantom. Ids are identifiers, not bearer secrets; the refusal
  discloses no payload, recipient, run, or path.
- Nominal reply-contract checking is enforced at the facade; deep payload-schema
  validation is not attempted and is not claimed.
- The wake scan fails closed on a damaged parking event, consistent with the M6
  committed-resume scan. The blast radius — one bad row stopping recovery for
  unrelated runs — is the same accepted trade, not a new decision.
