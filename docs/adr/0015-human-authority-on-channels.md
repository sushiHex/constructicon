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
had been protected only by the read gate at the door of `details_read`, so the
read check moved into `DetailResolver._resolve`, where the family that owns a
fact holds its own lock. Opening the door for channel details could then widen
nothing else.

**Authority comes from the governing request.** A reply deliberately carries no
recipient: it is addressed to the run, not to a person. Reading authority off the
message actually addressed would therefore let anyone act on an answer. Every
channel surface — page, message, detail, reply, acknowledgement — resolves
through the request that governs the message and authorizes against that. Two
sealed facts decide together: the interaction says which scope answers this kind
of question, and the recipient says whose question it is.

An unaddressed request is a routing decision, not missing routing. It is
discoverable by every actor holding the interaction's scope, matched on the
message *kind* rather than the null recipient, because a reply carries a null
recipient too and for the opposite reason.

**Which operation consumes which interaction is a stated rule.** `channels_reply`
consumes advice and nothing else; an approval is consumed exclusively by
request-bound `runs_approve`. Possessing `constructicon:approve` must not turn
the advice path into a generic reply path. Refusal order is kind, then
interaction, then authority — and all three before the command is claimed,
because none of them is a domain outcome: no durable record is written and the
idempotency key remains usable against the operation that does consume the
message.

**A request-bound decision is one fact in three places.** The `ApprovalRecord`,
the reply the parked run is waiting on, and that request's acknowledgement commit
in one transaction. The deciding actor is read off the approval record, so the
reply's sender and the acknowledgement's owner cannot disagree with the record
that authorizes them. One run names all of it: the command's run, the request's
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
- Non-channel detail families are now authorized where they resolve rather than
  at the door. Behaviour for every existing family is unchanged; the check moved.
- The canonical human exchange contracts live once in L0 (`core/human.py`), so
  the control plane and the standard components type the same exchange or type
  nothing. An `ApprovalRecord` cannot be written into an approval-interaction
  conversation that merely looks similar.
- Control response schema stays 3 and channel schema stays 1. No migration.
- The transport keeps no channel law: MCP handlers derive one actor and delegate
  once.

## Rejected alternatives

- **Requiring read alongside advise.** It would have made the advisor an observer
  with extra rights, which I9 does not say, and would have handed a human
  advisor every run in the store to answer one question.
- **Reading authority off the addressed message.** A reply has no recipient, so
  this grants an answer to anyone who can name it.
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
