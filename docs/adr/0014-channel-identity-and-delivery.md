# 0014 — Channel identity is derived and delivery is retained

**Status:** accepted (M7) — realizes I4/I5 for message channels; extends ADR 0012.

## Decision

A channel carries one exact request from a sealed invocation to a participant on
another rhythm, and exactly one authenticated reply back. Both halves are
immutable facts. Identity is derived from the invocation and the sealed binding,
never authored by a caller:

```text
request_id = digest("channel-message", 1, {
  invocation_id(run_id, path), channel_id, channel_revision,
  lane, interaction, port, kind: "request"})

reply_id   = digest("channel-reply", 1, {request_id, port: request.reply_port})
```

One invocation may therefore send at most one request per bound channel, lane,
and port. More messages require explicit ports or more invocations and loop
frames; there is no unstable ordinal and no caller-authored idempotency token.
Because the reply id derives from the request alone, a parked component computes
the id it waits on without consulting a live channel.

A request pins **both** halves of the exchange. `contract` and `port` type the
message's own envelope; `reply_contract` and `reply_port` are sealed values on
the request that say what reply is admissible. The attestation subject binds all
of them, so the reply's type is authority rather than configuration: an actor
able to vary `reply_contract` after the fact could change what the parked run is
required to accept.

Wall-clock time is deliberately absent from `ChannelSendIntent`. The trusted
transport stamps `Envelope.created_at` once, when it first appends the message.
A send reconstructed after process death reconciles against that stored
observation instead of inventing a second one; an equal logical intent is
idempotent, and a different payload or routing under one id is journal damage.

## Delivery and history

Delivery is honestly at-least-once and history is retained. There is no
destructive dequeue, no message deletion, and no acknowledgement-as-authority:

- an acknowledgement is a delivery fact about one actor. It never removes
  history from runtime recovery and never proves a component consumed the
  payload (I4);
- a reply atomically acknowledges its request for its author, so a crash cannot
  leave a reply without its delivery fact. Explicit acknowledgement remains for
  notification-only and dismissed messages;
- `UNIQUE(reply_to)` is what enforces one reply per request. Two processes
  replying concurrently admit one exact reply; the loser receives a typed
  conflict rather than damage, because losing a race is not corruption;
- a page is taken at one `ChannelRevision(message_seq, ack_seq)` vector cut and
  ordered by `(message_seq, message_id)`. Durable sequence — not a timestamp —
  is what makes the order total, so messages sharing an observation time still
  page deterministically. A later send, reply, or ack cannot shift, omit, or
  duplicate an older page, and a future or incoherent revision is refused.

## Two transports, one contract

`InProcessChannel` and `MailboxChannel` implement one L0 `Channel` protocol and
are exercised by one shared contract suite (I6). Both derive their messages from
the same contract-level constructors, so parity is structural rather than a
duplicated law that could drift.

Their profiles differ only where they honestly must. `InProcessChannel` declares
`durability="process"` and a new instance remembers nothing; it exists for
same-process composition and contract tests, not as the human-wait transport.
`MailboxChannel` declares `durability="sqlite_wal"` and persists in the one
authoritative journal database, so a channel message and the run parked on it
survive or fail together. Neither owns a second database path or schema manager.

## Consequences

- SQLite advances 5→6 by creating two empty tables and bumping `user_version`.
  No run, command, approval, effect, event, manifest, component, or promotion
  row is read or rewritten, and a database newer than the running build is
  refused rather than touched.
- `ProofSubject` gains `ChannelSendSubject` and the attestation action union
  gains `send`. Existing drafts serialize byte-identically, so historical
  attestation ids are unchanged.
- A capability descriptor may carry a `ChannelProfile`, which `describe()`
  publishes beside `ExecutorProfile`. The guarantee an agent reads is the one
  the transport actually provides.

## Rejected alternatives

- A caller-supplied message id or sequence number would make identity authored
  rather than derived, and would break reconstruction after process death.
- Deriving the reply's type from the lane, the interaction, or live channel
  configuration would leave the control plane with no sealed value to validate a
  reply against.
- Storing `created_at` inside the send intent would change the identity of a
  reconstructed send and defeat reconciliation.
- A destructive dequeue, or treating an acknowledgement as consumption, would
  hide history from runtime recovery and overstate the delivery guarantee.
- A second database or a broker would add a durability boundary that a parked
  run could survive independently of its own message.
