# 0015 — Human authority is sealed on the request, never chosen by the answer

**Status:** accepted (M7) — extends ADR 0014 to the human control surface, and
ADR 0012's approval authority.

## Why this record exists

[ADR 0014](0014-channel-identity-and-delivery.md) settled what a channel message
*is*. It did not settle who may read one, who may answer one, or what happens
when answering is also a governance decision. Rev 2 of the M7 plan required a
successor record before slice C only if request-bound approval changed approval
authority. It does: an `ApprovalRecord` now has a second way into existence, and
in that path a sealed channel request — not the caller — decides who may write
it and what it may decide.

## Decision

**An advisor is its own role.** I9 names observer, advisor, and approver as three
participations, and `AuthenticatedActor.allows` has no scope implication. The
channel read surface therefore authorizes on `constructicon:advise` and
`constructicon:approve` alone. Holding `constructicon:read` neither grants nor is
granted by them, so a human advisor holds one scope and reads only its own work.

That relaxation is paid for rather than asserted. Every non-channel detail family
had been protected only by one read gate at the door of `details_read`, so
relaxing that door for channel details would have opened all of them. The read
check therefore moved to the doors a *caller* reaches — reading a reference, and
minting one for a URI the caller supplied — and not into resolution, which is
shared with the references the system mints onto an owner's own response.

That distinction is the whole of it: a pointer minted onto a response was earned
by holding the mutation's scope, and `runs_approve` requires approve, not read.
Locking resolution made a successful decision commit its facts and then fail
while describing itself, stranding its command. Resolution still authorizes what
only the owning family can judge — a command's visibility, a channel message's
governing request.

**Authority comes from the governing request, with no administrator escape.**
A reply deliberately carries no recipient: it is addressed to the run, not to a
person. Reading authority off the message actually addressed would therefore let
anyone act on an answer. Every
channel surface — page, message, detail, reply, acknowledgement — resolves
through the request that governs the message and authorizes against that. Two
sealed facts decide together: the interaction says which scope answers this kind
of question, and the recipient says whose question it is.

An unaddressed request is a routing decision, not missing routing. It is
discoverable by every actor holding the interaction's scope, matched on the
message *kind* rather than the null recipient, because a reply carries a null
recipient too and for the opposite reason.

The recipient test admits no administrator, deliberately. `message_for_reply`
admits only the sealed recipient, so an authorization predicate wider than that
would admit an actor the domain then refuses — after its command was claimed and
planned, stranding it. One law for reading and for answering also settles the
asymmetry: an addressed request is no more discoverable in an administrator's
inbox than it is answerable by one.

**Contracts and interaction are not independent.** A canonical human exchange is
typed by its contracts and sealed by its endpoint's interaction, and admission is
the only place that sees both. An approval exchange sealed as advice would be
answered through the advice path, whose payload is stored verbatim — letting a
human holding advise alone author the whole `ApprovalRecord` the run returns as
a governance fact. The mirror parks a run no operation can answer. Admission
refuses both, and refuses a pair naming one canonical contract without its
partner.

**Which operation consumes which interaction is a stated rule.** `channels_reply`
consumes advice and nothing else; an approval is consumed exclusively by
request-bound `runs_approve`. Possessing `constructicon:approve` must not turn
the advice path into a generic reply path. Refusal order is kind, then
interaction, then authority — and all three before the command is claimed,
because none of them is a domain outcome: no durable record is written and the
idempotency key remains usable against the operation that does consume the
message.

**A request-bound decision is one fact in three places.** The `ApprovalRecord`,
the reply the parked run is waiting on, and that request's acknowledgement form
one complete exchange. When delivery is new, all three commit in one
transaction. When the actor acknowledged first, the transaction preserves that
immutable fact rather than stealing its command ownership, then commits the
approval and reply together. The approval and reply name the same exact
`runs_approve` command; the deciding actor is read off the approval record and
must equal the authenticated command actor, the reply sender, and the
acknowledgement actor. One run names all of it: the command's run, the request's
run, and the wake fence must be the same run.

Binding is additive and byte-neutral. A standalone decision omits
`request_message_id` entirely rather than serializing it as null, keeps its own
plan family, and drops the additive response field, so every command already
recorded under an existing idempotency key replays unchanged.

**A payload is caller-authored; authorship is not.** `Channel.ask` hands a
component the reply's payload and nothing else — deliberately, because widening
it would put the whole message inside every component's reach. Anything a
component may *promise* about authority is therefore written into the payload by
the executor from authenticated and stored facts: the approval reply carries the
whole trusted `ApprovalRecord`, and the canonical advice reply is stamped with
the authenticated actor and the derived reply identity. An answer that names an
actor inside its own payload is data, never a claim.

## Consequences

- `constructicon:advise` joins the known scope set. Scopes remain independent:
  advise, approve, and read grant nothing to each other.
- Non-channel detail families are authorized at the caller-facing doors rather
  than at one shared door. Behaviour for every existing family is unchanged; the
  check moved, and a mutation's own response is not a caller-facing read.
- The canonical human exchange contracts live once in L0 (`core/human.py`), so
  the control plane and the standard components type the same exchange or type
  nothing. An `ApprovalRecord` cannot be written into an approval-interaction
  conversation that merely looks similar.
- Control response schema stays 3 and channel schema stays 1. SQLite advances
  6 → 7, additively: nullable reply-writer, reply-provenance, and
  acknowledgement-provenance columns; independent immutable legacy-message and
  legacy-acknowledgement sequence cutoffs; and a partial unique writer index.
  Two NULL reply fields at or below the message cutoff and a version-0
  acknowledgement at or below the acknowledgement cutoff mark true schema-6
  history. A current reply carries its writer and provenance version 1 above
  its cutoff. If it creates a missing acknowledgement, that row is version 1
  above its cutoff and names an extant command; if the actor acknowledged under
  schema 6, the reply preserves that equal version-0 delivery fact rather than
  rewriting history. The sealed cutoff pair makes erasing current evidence
  insufficient to downgrade it into the legacy path. See
  [ADR 0016](0016-positive-durable-facts-and-provenance-eras.md).
  A current reply is projected only through that command's immutable plan,
  which independently proves its payload. A retained schema-6
  `ChannelApprovalPlan` still proves its exact three-fact exchange; schema-6
  advice replies and version-0 acknowledgements remain opaque and gain no such
  authority.
- `ControlPlane`, its concrete `RunHost`, its registry, its durable mailbox, and
  its send effect are assembled over one exact system world. Compatible-looking
  handles are insufficient because they do not share process-local state.
- The MCP transport keeps no channel law: handlers derive one actor and delegate
  once. Channel transports still enforce their L0 dispatch, identity,
  acknowledgement, and retry laws as a defence at the persistence boundary.

## Rejected alternatives

- **Requiring read alongside advise.** It would have made the advisor an observer
  with extra rights, which I9 does not say, and would have handed a human
  advisor every run in the store to answer one question.
- **Reading authority off the addressed message.** A reply has no recipient, so
  this grants an answer to anyone who can name it.
- **An administrator escape from the recipient seal.** It makes the
  authorization predicate wider than the domain's, which is not a wider
  permission but an exception thrown after a command is durably planned.
- **Locking detail resolution rather than the caller's door.** Every mutating
  response carries a minted pointer, so this makes each mutation require read in
  fact, and fail after the point of no return.
- **Matching a null recipient to find open requests.** A reply carries a null
  recipient too; this broadcasts every reply to every actor.
- **Letting `channels_reply` answer approvals when the actor holds approve.** The
  scope an actor happens to carry would then decide which operation applies,
  rather than the seal on the request.
- **Composing `store_approval` with `channel_reply`.** Two commits, so a death
  between them leaves an approval authorizing an exchange nobody answered.
- **Widening `Channel.ask` to return the whole message.** It would give every
  component the transport's view in order to fix a payload's contents, when the
  payload is where authorship belongs.
- **Serializing `request_message_id: null` for a standalone decision.** It would
  change the request hash, and therefore the command id, of every approval
  already recorded.
- **Treating a NULL reply writer as sufficient evidence of schema-6 history.**
  Erasing one current writer would then bypass its independent command plan;
  the additive provenance version makes legacy a positive row shape instead of
  an inference from one missing field.
