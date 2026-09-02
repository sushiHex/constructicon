# M7 implementation record

**Plans:** [M7 channels and panel rev 1](../milestones/M7-channels-and-panel-rev1.md)
for PRs A/B; approved
[rev 2](../milestones/M7-channels-and-panel-rev2.md) for PRs C/D

**Starting commit:** `0765072b83557aa2367732bb8cd8ec33d4962009`

**Nature:** living implementation record; approved plans remain immutable, and
this records the deviations and decisions that implementation forced

## Scope completed

PRs A, B, and C are merged (C as #18). Typed message channels have two
transports; routing and exchange are sealed into the manifest; sends carry
proof through the existing effect law; invocation parking is typed; and durable
replies drive wake recovery. PR D adds the panel pattern: `panel()` sugar, the
L0 panel contracts, the pure quorum aggregator and ballot adapter, and the
credential-free acceptance lane across process restarts.

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
  domain facts without waiting for command completion; immutable command plans
  remain reply-provenance evidence.

## Deviations from the plan

Each is a defect in the plan rather than a shortcut in the implementation. Rev
2 absorbed all seven before PR C; the table remains the implementation history
that forced those corrections.

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
serialize the historical field name `resume_command_id`; M7 records
`reply_message_id`, the immutable fact the scan observed. No command lookup
reconstructs a reply wake.

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
- one explicit acknowledgement command owns at most one delivery fact; a reply
  command may own its reply and imply that same request's acknowledgement, but
  no command id crosses to another request;
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
`ACK_CONSUMES` sit beside each other in L0 `core/channel.py` and are imported at
the command call sites.
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
its planned payload, and the request acknowledgement its transaction guarantees.

**A different command after an admitted reply is a lost race.** One reply per
request is a hard constraint, so a fresh command that finds a stored reply
returns `CHANNEL_ALREADY_REPLIED` before applying anything. A command that
already planned takes the replay path instead, so a crash between plan and apply
still converges on one fact. The same shape holds for `channels_ack`: one
delivery fact has one owning command, and a second command over it is a typed
idempotency conflict, never damage.

**The wake is a courtesy, not the mechanism.** The reply itself is the durable
wake. `_scan_answered_waits` derives eligibility from domain facts and does not
wait for command completion, so a death before completion still wakes the run.
It does validate the immutable writer command and plan as reply provenance. The
command additionally launches one intent pinned to the fence its plan recorded,
which only spares the human the scan interval and cannot revive an attempt the
run has moved past.

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

**One exchange, one deciding commit.** `store_approval_exchange` always commits
the `ApprovalRecord` and reply together. If delivery is new, that transaction
also writes the request acknowledgement; if the actor acknowledged earlier, it
preserves that immutable fact rather than stealing its command ownership.
Composing `store_approval` with `channel_reply` would split the decision across
two commits, and a death between them would leave an approval authorizing an
exchange nobody answered. `reply_in_transaction` exists at connection level
for exactly this: the reply law lives in one place and a second caller composes
one commit rather than copying it. The deciding actor is read off the approval
record, so the reply's sender and acknowledgement actor cannot disagree with
the record that authorizes them.

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

**A foreign triple was initially checked through the wrong edge (superseded).**
`_require_whole_exchange` first verified the reply and acknowledgement but not
the approval, so a raw transport write producing reply+ack looked complete. The
round-one fix tried to reach the approval through the acknowledgement's command.
That contradicted a lawful pre-ack and was removed in the next round: the
authoritative relation reaches the approval through the reply command, while
the acknowledgement independently proves delivery.

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
- **Administrator asymmetry (superseded later in this record).** At this review
  point, an administrator could act on an addressed message by id without
  discovering it in an inbox. The later fan-out proved that the domain itself
  never admitted that actor, so the wider authorization escape was removed
  rather than retained as an asymmetry.
- **`sealed_reply_payload` keys on the reply contract alone.** That is the
  contract which promises authorship, so it is the one that decides whether a
  reply carries it. The request contract does not enter into what a reply is.

The review also noted that the byte-identity claim for a standalone decision is
pinned by field absence and plan kind rather than by comparison against an M6
golden artifact. The M6 seam tests do compare stored response bytes, so the
claim is carried by the older suite rather than by the new test.

## PR C — what the second review round found

Four of these are consequences of the first round's own fixes. That is worth
recording: each fix was locally right and globally incomplete, and only reading
the branch as a whole surfaced them.

**Reaching the approval through the acknowledgement's command contradicted the
implied-ack law.** Round one made a reply *imply* an existing acknowledgement,
and then, separately, made the whole-exchange check reach the approval record
*through* the acknowledgement's owning command. Together those mean a legitimate
`channels_ack` followed by `runs_approve` produces an acknowledgement owned by a
command that wrote no approval — and the next lookup calls that damage. The check
now reaches the third fact through the reply, which carries the record:
`ApprovalDecisionPayload` names it, the store must hold an equal one, and its run
must be the request's. `channel_ack_command` and `approval_for_command` were
added for the wrong reading and are gone with it.

**A lawfully emitted refusal was not replayable.** The first race loser returned
`CHANNEL_ALREADY_REPLIED` and its exact retry raised `JournalDamaged` — the
stored answer called damage. The final law is stronger than a code whitelist:
channel reply, channel approval, and channel acknowledgement each reconstruct
one canonical refusal from the immutable plan and independently retained
foreign fact, and each is tested by asking twice.

**The two transports disagreed.** The implied-ack law landed in SQLite only, so
acknowledging before replying succeeded through the mailbox and raised through
the in-process channel — an I6 break. Both now split claim from imply, and the
scenario lives in the shared contract suite, which is what should have caught it.

**Identical concurrent replies both succeeded.** ADR 0014 admits one reply and
owes the loser a typed conflict; identical bytes were being treated as an
idempotent retry no matter which command wrote them, so two commands could both
report success over one fact. Distinguishing them needs the writer's identity, so
SQLite advances 6 → 7 with a nullable `command_id` and
`reply_provenance_version` on `channel_messages`. A current reply writes
`(command_id, 1)`; true schema-6 history retains `(NULL, NULL)`. This is
additive: reply rows are not rewritten, and each column is added by inspection
so a partly-climbed ladder is not damage. The final integrity pass below adds a
positive acknowledgement-era marker and cutoff rather than relying on NULL as
historical evidence.

**The archive was edited and its manifest went stale.** Rev 2 is an approved
plan, and approved plans are immutable: a later decision belongs in an ADR, a
successor, or an implementation record, all of which already carry it. The edit
is reverted and rev 2 is byte-identical to `main` again. The manifest records
new digests only for the archive index and this living implementation record;
the frozen rev-2 plan remains unchanged.

## PR C — what the third review round found

**A v6 reply is not ownerless, only differently recorded.** Schema 7 records the
command that wrote a reply, while migration leaves both provenance columns NULL
for everything written before. But v6 recorded the same fact elsewhere: the
reply path *claimed* its request's acknowledgement then, so no other command
could hold that row. A command that crashed under v6 between its domain write
and its completion would otherwise, on retry after the upgrade, lose a race it
never entered. One read law returns the writer column for `(command_id, 1)` and
falls back to the acknowledgement only for `(NULL, NULL)`. A mixed pair is
damage, so a current writer cannot be erased into apparent legacy. A real v6
fixture (both columns absent, version rewound) proves the compatibility path.

**Provenance is necessary and was missing; agreement is also necessary.**
`_require_whole_exchange` confirmed the carried approval existed and shared the
run, which a standalone decision spliced into an unrelated reply satisfies. The
reply names the command that wrote it, and that command must be the one that
wrote *this* approval — that link is what schema 7 makes available. Beyond it,
the three facts must agree about run, actor, and subject, each of which is
reachable with the provenance link intact and is now pinned by its own scenario.

**The authoritative documents said schema 6.** `ARCHITECTURE.md`,
`CONTRIBUTING.md`, and the schema module's own docstring now say 7. The archived
rev 1 plan still says 6, correctly: it is a historical record of what was planned
then, and plans are immutable.

## PR C — a narrow role must be able to finish what it started

An adversarial fan-out over the branch found the sharpest regression yet, and it
was mine: the family lock from the first review round sat inside `_resolve`,
which is shared between reads a caller asked for and references the system mints
onto an owner's own response. Every mutating response carries one. So an actor
holding exactly the scope its mutation requires — approve, operate, or promote,
with no `constructicon:read` — committed its domain facts, launched its wake, and
then raised `JournalDamaged` while describing what it had just done. The command
stranded, and every retry answered `COMMAND_IN_PROGRESS` forever.

`runs_approve` requires approve on paper. Locking the pointer made it require
read in fact, and fail after the point of no return rather than before it.

The lock therefore moved to the doors a caller reaches — `read`, and a new
`caller_reference` for a caller-supplied URI — and left resolution entirely.
Resolution still authorizes what only the owning family can judge: a command's
visibility, a channel message's governing request. The distinction is who chose
the URI. A pointer minted onto an owner's own response was earned by holding the
mutation's scope; a URI a caller supplied is a read.

Three roles now prove it, each holding one scope and nothing else. The same test
pins the other direction: an approve-only actor may record a decision and still
may not read the manifest, nor even the detail its own response just handed it —
reading is a read.

**The addressed read gained the page's door.** `channels_message` derives
authority from the message, which means reading the message first, so an actor
with no channel authority at all learned whether an id existed before being told
the surface was not its to read. It now refuses first, identically for a real id
and an absent one.

## PR C — what an adversarial fan-out found

Thirty-three agents across seven lenses, each finding adversarially refuted
before it counted. Sixteen survived, deduplicating to six defects. Two were
escalations, and both had the same root.

**Contracts and interaction were independent facts, and must not be.** A
component declares what crosses; assembly's endpoint declares under whose
authority. `_compiled_channel` took both and never asked whether they agreed.
Bind `human-approval` — typed by the approval contracts — to an endpoint sealing
`interaction="advice"`, and the request is answered through `channels_reply`,
which stamps only *advice* replies and so stores the advisor's payload verbatim.
A human holding `constructicon:advise` alone would author the entire
`ApprovalRecord`, actor and decision included, that the component then returns as
a trusted governance fact. The mirror parks a run forever: an advice exchange
sealed as approval is refused by `channels_reply` for its interaction and by
`runs_approve` for its contracts, so nothing can answer it.

`canonical_exchange_fault` lives in `core/human.py` beside the contracts and is
applied at admission, the only place both facts are visible. It refuses either
mismatch, and refuses a pair naming one canonical contract without its partner —
half a canonical exchange is not one half-dressed, it is a mismatch one step
earlier.

**The authorization predicate was wider than the domain's.**
`channel_authority_holder` ended its recipient test with `or
actor.allows(ADMIN_SCOPE)`; `message_for_reply` admits only the sealed recipient
and has no such clause. So an administrator answering an addressed request was
authorized, claimed a command, stored a plan, and then raised `ContractViolation`
out of the public surface — leaving the command `prepared` forever, every retry
raising again. The escape is gone: one predicate for reading and for answering,
matching the domain exactly. That also settles the asymmetry recorded earlier —
an addressed request is no more discoverable in an administrator's inbox than it
is answerable by one.

**A per-channel cut was validated by a global probe.** The coherence check asked
whether any acknowledgement below the cut belonged to a message above it, across
every channel. Once one journal carried a second channel, a transport could
refuse the cut it had just read itself. The probe is now scoped exactly as the
cut is.

**The post-plan race loser skipped a proof the pre-plan loser owes.** Whether a
torn exchange read as damage or as a lost race depended only on when the command
happened to look. Both paths now require the whole exchange.

Two documentation defects were also caught and fixed: an in-code comment and ADR
0015 both still described the read check as living in resolution, which the
narrow-role fix had moved. A record that describes a placement the code no longer
has is worse than no record.

## PR C — final integrity closure

The final pass stopped treating each damaged row as a local parser problem and
named the shared laws that make the whole durable world auditable.

**One assembled world.** `ControlPlaneStore` owns the transaction that spans
commands, approvals, replies, and acknowledgements. `ControlPlane`, its concrete
`RunHost`, mailbox, send effect, and `Constructicon` share the exact journal; the
control plane also receives the exact registry object already assembled into
the system, whether that registry uses the journal or another `RegistryStore`.
Compatible-looking replacement handles are insufficient. Built-in channel
kinds have fixed truthful durability, a mailbox proves its journal identity,
and component code receives only the sealed `ask` facade.

**One lossless durable boundary.** Durable JSON rejects duplicate keys,
non-finite numbers, and invalid Unicode scalars. Except for an explicitly named
and fixture-proven historical writer shape, model validation must render to the
same canonical fact it received, so coercions such as `true` to `1`, a
deduplicated scope set, or an unproven compatibility default cannot silently
repair a row. One exact aware-ISO decoder serves stored timestamps from which
the server mints cursor keys; cursor decoding separately binds their shape and
query. SQLite booleans and sequences accept only their exact integer forms.
Run, event, command, approval, channel, effect, capability-lease, registry, and
attestation projections fail closed through those shared decoders. The retained
field name `resume_command_id` gains authority only through the relationship
sealed below.

**An immutable row is not its own evidence.** One mechanical
`durable_fact_seals` table retains a family-separated positive observation of
each exact immutable fact, while each owner module defines that fact's bytes,
primary key, secondary selector, and relationships. Command claim/plan/
terminal, approval, attestation, registration/promotion, manifest/run world,
effect preparation, event/checkpoint, channel message/ack/provenance, and the
resume-attempt relationship all seal in their writer transaction. Current open
validates each bidirectional inventory and never fills a gap; batch and recovery
paths call the same sealed projectors as point reads. Deleting a primary row,
one half of a relationship, or changing either into a second valid fact cannot
turn a retry into permission to mint new authority.
Schema migration is the only historical sealing boundary. Before the
positive-seal chain, it adds `effects.outcome_run_id` and
`effects.outcome_event_seq`, records the two `channel_provenance` cutoffs,
stamps retained acknowledgements with era 0, populates
`runs.creation_command_id` for origin-bearing runs, and records terminal pre-v7
outcomes in `legacy_effect_seals`. It then seals
commands → pre-v7 resume-plan evidence → manifests → run worlds → attestations
→ approvals → registrations/promotions → effect preparations → events
→ opaque effect-outcome classifications → resume-attempt relationships
→ checkpoints → channel provenance → messages → acknowledgements. Rows in
`legacy_capability_lease_seals` follow the event seals. That topology lets later
facts use the same canonical projectors as current reads. ADR 0016 records the
shared law.

**Compatibility has named byte eras.** M1/M2 effect requests omit `run_id`,
`manifest_hash`, and `mode`; M3–M5 carry `run_id` and `manifest_hash` but omit
`mode`; current requests carry all three. A retained historical terminal
receipt remains bound to its original request hash, while an unfinished
preparation may execute through a lossless current view without rewriting the
stored request. A keyless pre-v7 outcome event requires a migration-only
`legacy_effect_outcome_pre_v7` seal; current outcomes must carry the exact
effect key. Schema-5/6 actor scope arrays and pre-sort component set arrays
likewise retain their original unique order; normalization exists only in the
typed view and never in the sealed fact.

**Resume provenance has disjoint eras and an atomic receipt.** Schema-7 SQLite
and in-memory writers accept only typed schema-1 envelopes. A current resume
domain plan additionally carries exact-v1; a typed pre-domain refusal remains a
separate plan family with its response embedded. Migration alone marks every
retained raw `runs_resume` plan and each weak typed schema-6 resume domain plan
under `resume_plan_pre_v7`, recording whether the command was `prepared` or
already `terminal`. Prepared evidence binds claim and plan without pretending a
future response exists; terminal evidence also binds the exact retained
response. Current plans cannot acquire that marker, and removing exact-v1
cannot make one historical. Plan creation observes the run row and latest event
position through one `RunHead` snapshot, so a concurrent transition can only
supersede a coherent fence. A current attempt atomically co-seals
`resume_attempt`, binding the command claim, plan, baseline event (or
sequence-zero PENDING fact), and exact attempt event. Event and command point
reads validate both halves, global inventory is bijective, and an unfenced
historical plan cannot own the receipt. `AttemptCause` owns one lossless
serializer/parser for the mutually exclusive resume-command and channel-reply
payload keys.

**A request carries an independent authority chain.** The effect preparation
binds its canonical request; the send attestation binds the exact run manifest
and every intent field; and the stored request revalidates that chain on every
read and wake scan. The in-process transport retains a deep first-write intent
proof, so I6 parity includes the same independent-evidence boundary rather than
comparing a message with itself. Policy minting remains closed to actions the
policy actually evaluates; it cannot mint a channel send.

**Reply and acknowledgement provenance have explicit eras.** Schema 7 records
`channel_messages.command_id`,
`channel_messages.reply_provenance_version`, and
`channel_acks.ack_provenance_version`. The singleton `channel_provenance` row
holds independent immutable `legacy_message_through` and `legacy_ack_through`
cutoffs. Migration populates the acknowledgement-era marker and the
creation-command marker for origin-bearing runs; it creates and positively
seals the cutoff row before advancing the schema version. Historical replies
lie at or below the message cutoff with both writer fields absent. Historical
acknowledgements lie at or below their cutoff with version 0. Their command id
remains an opaque
historical scalar and is never resolved into a same-named later command.
Current version-1 replies and acknowledgements lie above their respective
cutoff and name an extant writer command. Current advice, explicit
acknowledgement, and request-bound approval each validate through their own
typed plan family. A schema-6 approval may still recover its retained
`ChannelApprovalPlan` through the approval row; schema-6 advice remains opaque.
A current fact cannot be downgraded into either path by erasing a column.

**Contradiction never heals.** An explicit acknowledgement cannot complete a
torn reply, even for the same actor. A pre-existing acknowledgement may be
preserved by a later reply, but the reply must prove its own writer and the
whole exchange. A current atomic reply and implied acknowledgement share one
observation time when the reply creates the missing delivery fact; a preserved
earlier acknowledgement and schema-6 history truthfully retain their prior
observation.

**Recovery is bounded and exact.** Run and event projections share one strict
decoder. Lost-run selection probes malformed candidates, compares exact UTC
microseconds inside SQLite, and applies its bound before materialization. Wake
recovery pages PARKED facts and immutable replies without requiring command
completion, while still validating the reply's writer plan. A corrupted fact
fails closed; no watermark, outbox, unbounded query/materialization, or inferred
repair was introduced. Complete PARKED history is deliberately revisited through
bounded pages across recovery ticks.

The approved rev-2 plan remains byte-identical to `main`. Decisions discovered
after approval live here and in ADRs 0014–0016, not in rewritten history.

## PR D — the panel pattern

Design record: `research/m7-pr-d-panel-design.md` (revised after an adversarial
Codex review of the design; twelve findings, ten accepted, two narrowed).

**`panel()` is literal Graph sugar over bundles.** Its body is the members, the
aggregator, one map-free connection from each member to the aggregator, the
members' one request port plus the aggregator's non-`many` inputs as graph
inputs, and the aggregator's outputs — byte-equal to the hand-authored Graph
with equal `source_graph_hash` and `manifest_hash`. It takes definition bundles
rather than bare Refs because exactness is proved at authoring from declared
contracts: every member declares one input and one output and all share the
same pair; the aggregator declares exactly one `many` input of that result
contract; no boundary input — a policy input of the aggregator or the members'
own request — carries that result contract, because a graph input sits in
every node's pool and would be gathered as a member; boundary names are
unique. Each refusal is a typed error at authoring, not an absent member at
admission.

**The gather is the general connector law, not a panel privilege.** A `many`
port gathers every compatible source in its pool, which is the transitive
upstream closure plus every graph input. A same-level bystander contributes
nothing; a compatible graph input or a compatible helper upstream of a member
widens the gather, and the tests say so. `panel()` never emits either shape. A
`one` port fed by two members still raises the existing ambiguity fault from
the hand-authored Graph, and `panel()` refuses such an aggregator before that.

**Member identity is reported and shape-checked, not kernel-attested.** The
walker hands a `many` port payloads in sealed source order and drops the source
address; nothing stamps provenance into a payload. So a member writes
`member = ctx.path` — the genuine path it was handed — and the aggregator checks
everything the kernel makes checkable: every path begins with the aggregator's
parent scope, has a segment at that depth, which is the member's node, and
sits in the aggregator's own loop iteration, since the walker gives every
sibling in a loop body the same frame; a
node reported twice, whether by one path repeated or two paths beneath it, is a
contract violation, so a member claiming a sibling's identity collides with the
sibling rather than replacing it; any other topology is refused rather than
guessed at; a result from another run is refused. Members are ordered by the
canonical JSON of the complete `ExecutionPath`, never by `render()`, which is
not injective. Kernel-attested source identity on `many` ports would change the
atomic invocation contract and is deferred.

**The result is self-verifying.** `PanelResult` names the aggregator path and
run it was concluded for, and validating one re-derives the members'
placement, the tally, and the outcome from the members it carries: a stored or
foreign result whose conclusion contradicts its members is refused (I4), so any
aggregator that shares the contract is held to the standard one's law.

**The outcome says what happened.** `impossible_quorum` when the quorum exceeds
the member count, `approved` when approvals meet it, `insufficient_responses`
when fewer members answered than the quorum needs, and `rejected` only when
enough answered to have approved and did not. The quorum is an explicit typed
input, never a combinator default. Every member outcome — `responded`,
`declined`, `unavailable`, `timed_out` — is data a member or policy component
reports; M7 owns no clock, so the kernel infers nothing from elapsed time. A
human who does not answer keeps the run parked; one who will not answer replies
`declined`. Wall-clock timeouts need a timer owner, a durable observation, and
wake law, and stay deferred.

**A human member is composition, not a new exchange.** `human_panel_member` is
`human-advisor` followed by `constructicon.std/panel-ballot`, authored per
participant because each human needs their own channel id carrying their own
sealed endpoint. The adapter validates the outer, executor-stamped
`AdviceReplyPayload`, then reads its `advice` strictly as a `PanelBallotPayload`
with `extra="forbid"`: an `actor_id` a human writes inside their answer is a
malformed ballot that fails the run, not a claim the panel repeats. The vote
carries the stamped `actor_id` and `message_id` so it can be followed back to
its durable reply. `CANONICAL_EXCHANGES` and `sealed_reply_payload` are
unchanged. Both panel components declare `capability_requirements=()`, and the
structural tests now distinguish the channel-bound components (exactly one
input, one output, one durable channel) from the pure ones.

**What a participant can discover.** The ballot's shape travels inside the
generic advice reply, so nothing in the exchange announces it: the request
payload the workflow author writes is what the participant sees, and it should
say that the answer is read as a `PanelBallotPayload`. The panel ports embed no
JSON Schema, for the same reason the advisor and approval ports embed none: the
registry binds an embedded schema to its own digest, and a named contract
revision is not that digest. So `describe()` publishes the standard vocabulary
from L0 catalogues beside the contracts — every named revision and its shape,
including `constructicon.std/PanelBallot`, which no port names — and reports a
port's schema available when it embeds one or names a catalogued revision. All
six standard ports are now complete.

**The law is part of the identity.** `source_digest_for` hashes a component's
own source, and the two panel components' own source says almost nothing:
they delegate to `core/panel.py`. Its revision (`PANEL_LAW_REVISION`) is a
digest of the contract classes and law bodies, derived at import rather than
named, and stamped into both implementations through the same
adapter-revision mechanism a task adapter uses. A change to any contract
field, validator, placement, tallying, the outcome, or the result's
self-check is therefore a new version by construction; a test pins the
closure the digest is taken over.

**Proof.** Twenty-six mutants of the aggregation law, the authoring checks,
and the boundary checks — dropped ordering, sibling check, iteration prefix, a
second frame, a loop that does not enclose its invocation, a loop not directly
above a body, the aggregator's own frames trusted, a member's frame beneath
another seat, duplicate check, the aggregator's own seat, run check, both
off-by-one thresholds, the ballot bucket, the boundary-contract check, the
gather-contract check, member cardinality, a composite aggregator, a
composite's lying boundary at registration and at admission, a boundary
compared as models at authoring, registration, and admission, fault details
parsed from the first marker, and two ways of not re-deriving a result — are
each killed. The acceptance lane runs six fakes reporting all six buckets through
the real graph, then one fake plus one mailbox-backed human across restarts — a
fresh journal and system over the same database file, nothing carried in
memory. The system that asked is discarded; a second records the ballot and its
own control-plane host wakes the run to conclude the panel; a third records the
approval the same way. The run's history holds exactly three attempts — the
start and one resumption per reply, each caused by that reply — and exactly
two requests, two replies, two acknowledgements, and one approval exist
afterwards. A human who rejects leaves
the panel `rejected`, fails the run at the adapter, and never produces an
approval request, so the request exists only because the result said so.

## PR D — what the complete-head review found

An adversarial Codex review of the head returned five blockers and three lower
findings; four blockers were accepted and fixed, one was narrowed with
evidence.

- Accepted: a member whose request and result contracts coincide put the
  request — a graph input, so in every pool — into the gather. `panel()` now
  refuses any boundary input carrying the result contract.
- Accepted: the aggregator compared scope only; a member reporting another loop
  iteration passed. It now takes its whole path and compares iterations.
- Narrowed: a member reporting an invented sibling name is not a second vote.
  The walker delivers exactly one payload per sealed source, so the count is
  the kernel's; a misreported name that is nobody else's mislabels only its
  author. That is the recorded member-reported identity, deferred as before.
- Accepted: `PanelResult` accepted contradictions. It is now self-verifying.
- Accepted: the lane called the run directly after each reply, so a broken
  wake could pass, and the approval adapter's result parse was removable
  without a failing test. Resumption now goes through the control plane's
  host, attempt causes are asserted, and a rejecting panel proves the adapter
  reads the result.
- Accepted in part: the ballot's shape is not discoverable from the exchange.
  Recorded above; embedding a schema is refused by the registry for a named
  revision, and the request payload is the author's channel to the
  participant.
- Accepted: the claimed proof matrix was incomplete. Explicit ids, a repeated
  member, zero members, wrong member arity, two gathers, and an id collision
  are now tested.
- Accepted: `actor_id` and `message_id` in a member result are telemetry any
  component may write; a consumer that needs provenance follows `message_id`
  to the sealed reply. The contract's docstring says so.

A second review of the corrected head returned three blockers and three lower
findings; all six were accepted.

- A composite member with an `optional` result could seat nobody and one with a
  `many` result could seat every internal source. A member's request and
  result must now be cardinality `one`: a seat answers exactly once.
- The registered identity of the pure components did not cover the law they
  execute. The law's revision is stamped into both, as recorded above.
- Deferring discoverability was not acceptable for a milestone marked done.
  The named-contract catalogue above closes it without touching contract
  identity; the introspection contract is met for every standard port.
- A member could report the aggregator's own seat without colliding with
  anything. That claim is refused outright; the residual — a member may
  mislabel itself with a name nobody holds — is stated exactly.
- The result's self-check proves self-consistency, not which run or aggregator
  produced it; a consumer with a context compares `run_id` and `aggregator`
  explicitly, as the lane does.
- The wake assertion counted causes, not attempts, so a cause-less extra
  attempt could hide. The lane now asserts the exact attempt sequence: one
  start and one resumption per reply, each caused by that reply.

A third review returned four blockers and four lower findings; three blockers
and all four lower findings were accepted, one blocker rejected with evidence.

- Rejected: `panel()` emits unversioned Refs, so a later promotion could give a
  member another contract and the gather would silently omit it. That is
  every combinator's and every direct Graph's behaviour — `Ref.version` is
  optional by IR design, the stable pointer is the release law's, and
  admission seals one atomic world and re-proves the gather nominally against
  it. The authoring proof is about the bundles as authored. A validator fault
  for a connection that binds nothing would close the residual for every
  graph; it is an IR decision and stays open.
- Accepted: a composite could declare a boundary its Graph does not export,
  because admission compiles the Graph and ignores the declaration. The
  registry now refuses such a definition and `component()` refuses to
  redeclare a Graph's boundary, so a member's advertised `one` result is its
  body's.
- Accepted: a composite aggregator wrapping the standard quorum would place
  nothing, since the quorum's law reads its own seat; `panel()` now requires
  an atomic aggregator. A member whose internals iterate carries frames
  beneath its seat; the aggregator's frames must be a prefix of a member's,
  not equal to them.
- Accepted: the vocabulary's documents were shared mutable dictionaries. The
  catalogues now hold the models, every description generates its documents
  afresh, and documents are keyed by name and revision so two types cannot
  overwrite one another.
- Accepted: the identity test verified the digest formula, not that the law's
  source matches its revision. A golden digest of the four law bodies is now
  pinned to `panel-law-1`; editing the law without a bump fails it.
- Accepted: the advice request's schema is generated from a `RootModel` of
  any JSON value, so its generator is stated truthfully; the design record's
  result shape names `run_id` and `aggregator`.

A fourth review returned six findings and two nits; four accepted, one shown
already safe by a test, one rejected again with the residual stated exactly.

- Rejected again: unversioned Refs. The proposed connector-liveness rule — a
  connection's source must contribute a resolved binding somewhere beneath
  its destination — is the right shape for the open IR item, and the item
  now says so; it applies to every graph and is not this slice's.
- Accepted: the registry check covered new registrations only. Admission now
  refuses a retained composite whose declared boundary is not its Graph's,
  proven by storing one past the registry and validating a graph that seats
  it.
- Accepted: a member's extra loop frames must name loops beneath its own seat;
  a frame for a loop elsewhere is not a sibling's.
- Narrowed and kept: `panel()` still requires an atomic aggregator. A
  composite aggregator that does not read its seat would admit as a direct
  Graph, and the refusal is a choice of the sugar, recorded as such: the seat
  is the aggregator's, and transformation composes around the panel. Relaxing
  it needs a way for an aggregator to say whether its law reads its seat.
- Shown safe: a description's documents were said to share nested dictionaries
  with the registered ports. They do not — a description is built from dumped
  and re-validated documents — and a test now mutates a returned embedded
  schema, nested dictionary included, and shows the next description
  unchanged. The deep copy tried in response was dead code and was removed.
- Accepted: the law's golden covered four bodies. The revision is now derived
  from the whole closure, so there is no golden to keep complete.
- Accepted: `schema_hash` is the public key of a published schema, as it was
  before; the vocabulary asserts at import that no two named contracts share
  a revision string.
- Declined: relaxing member equality to nominal contracts. A panel's members
  share one declared pair by name too, because the pair becomes the boundary
  the sugar emits; a direct Graph may name ports differently, and the sugar
  does not promise to admit every direct Graph, only to equal the one it
  emits.

A fifth review, asked to classify each finding as introduced here, pre-existing,
or a design choice, returned four introduced defects, two introduced nits, and
one pre-existing item; all accepted.

- The three boundary checks compared ports with `==`, and `1 == True` is a
  Python fact: an embedded schema differing only there passed all three. A
  boundary is now compared as canonical bytes (`core.ports.same_boundary`) at
  authoring, registration, and admission, and the members' shared pair is
  compared the same way.
- The retained-boundary fault was a legacy string that `admit_graph()`
  classified as a graph contract fault with a repair aimed at the wrong
  thing. It now names the retained component and version in its details,
  with a repair that says the retained definition is defective. The
  Loop-body reference path re-proves the same boundary. (A new fault code was
  tried and withdrawn in the next round; see below.)
- A member's extra frame needed only to begin with its seat, so a loop that
  did not enclose the reporting invocation passed. Each further frame must
  now name a loop that encloses the invocation, and frames nest in order from
  the seat; a frame at or beneath the seat follows from that.
- The law's closure omitted the shared model config and the literal domains.
  Both are in the digest now: `_PanelModel`'s source and each literal's
  values.
- The vocabulary's uniqueness guard counted after a comprehension had already
  collapsed duplicates; it now counts the entries first. The design record's
  frame wording is corrected.
- Pre-existing, recorded below: composite registration never verifies that an
  embedded `json_schema` hashes to its declared `schema_hash`; that check is
  confined to atomic identity.

A sixth classified review returned three introduced items and two
pre-existing; all accepted.

- The frame law trusted the aggregator's own frames and accepted a loop equal
  to its invocation or repeated. A loop's body sits strictly beneath the loop,
  so every frame's loop is now a strict prefix of the invocation, frames nest
  strictly from the seat, no loop is the root, and the aggregator's path —
  data in a result — is held to the same law.
- The fifth round added a fault code to a closed enum without a schema
  version transition. The code is withdrawn: the code set is the versioned
  wire schema and this slice changes no schema. The fault stays under
  `graph.contract.invalid` with exact details and a repair that says where
  the defect is.
- Those details were scraped from prose and were not exact for names holding
  quotes or digest-like text. The validator now appends an anchored JSON
  suffix and the classifier parses that, so any legal name survives.
- Pre-existing, recorded below: registration deduplication compares
  definitions as models, and the legacy fault-scope parser drops scopes with
  spaces and truncates those with colons.

A seventh classified review returned two introduced items; both accepted.

- The frame law described nesting the walker cannot write: nested loops are
  refused at admission, an instance in a loop body carries exactly one frame,
  and the body sits directly beneath the loop under a `body` segment. The law
  now states exactly that — one frame at most, its loop directly above
  `body` — for members and the aggregator alike, and the segment is named
  once in the IR (`LOOP_BODY_SEGMENT`) and used by the validator. When nested
  loops arrive the law changes and, being digested, so does the revision.
- The details parser matched greedily from the first marker and let a decode
  error escape the typed boundary. It now reads from the last marker and
  swallows a failed decode, proven with a graph whose own name carries a
  forged marker.

## Open items

- Kernel-attested source identity on `many` ports and wall-clock timeouts for
  human members are deferred, as recorded above.
- `describe()` publishes the whole standard vocabulary in every description,
  filtered or not. It is the system's fixed L0 vocabulary rather than a
  property of the selected components; a per-selection projection would be a
  choice, not a correction.
- Registration deduplication compares definitions as models
  (`plan_registration`'s semantic match), so two truthful composites differing
  only where Python equality is blind — `1` and `true` — dedupe to one retained
  version despite distinct canonical bytes. Pre-existing; the bytes law for
  boundaries does not extend to it yet.
- The legacy fault-scope parser in `_classify_fault` drops scopes containing
  spaces and truncates those containing colons, both legal in raw Graph names
  and node ids; typed faults inherit it. Pre-existing.
- Composite registration never verifies that an embedded `json_schema` hashes
  to its declared `schema_hash`; that check is confined to atomic
  `_validate_atomic_identity`. The boundary checks compare the schema bytes a
  composite declares against its Graph's, not against the digest.
- Connector liveness is not an admission rule. A connection whose source node
  contributes no resolved binding anywhere beneath the edge is admitted, so a
  member whose stable version later changes contract is silently absent from a
  `many` gather; a fault for that would close this for every graph and is an
  IR decision.
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
