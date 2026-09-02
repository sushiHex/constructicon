# 0016 — Durable facts have positive seals and explicit provenance eras

**Status:** accepted (M7) — strengthens the SQLite persistence boundary used by
ADRs 0012, 0014, and 0015.

## Why this record exists

An immutable row cannot be its own evidence. A derived id, redundant column,
or typed payload can expose malformed data, but none distinguishes an absent
fact from a fact that existed and was erased. Nor does it expose a
valid-to-valid rewrite when every value in the primary row is changed
consistently. On a retry boundary, treating either case as ordinary absence can
authorize the system to mint a second fact.

Compatibility creates the mirror hazard. A missing current provenance field
must not make a row look historical, and a historical row must not acquire
authority that its original writer never recorded. Compatibility therefore
needs positive evidence of a named writer era, not a permissive fallback.

## Decision

**Every immutable current fact and authority-bearing cross-row relationship has
an independently selected positive seal.** The owner defines one family, one
primary key, one secondary selector where the fact carries a second identity,
and the exact relational and JSON bytes that constitute it. Single-identity
facts repeat their stable key as the selector. The shared seal mechanism stores
only that tuple and its domain-separated hash; it does not interpret semantics.

The primary row and seal commit in the same transaction. Reads and retries use
the owner's one canonical projector: validate exact durable scalar types and
JSON bytes, prove redundant identities and relationships, then require the
matching seal. A missing primary row is not permission to create when its seal
or another retained durable fact still names it.

The sealed families are command claim, plan, and terminal response; approval;
attestation; component registration and promotion; retained manifest and the
immutable run world; effect preparation; event and checkpoint; channel message,
acknowledgement, and channel-provenance cutoffs; and the resume-attempt
event/command relationship. Mutable lifecycles remain governed by their
existing append-only evidence and fences: current effect outcomes name exact
events, current capability leases name exact lifecycle events, and run
lifecycle agrees with its complete event history.

**Inventory is bidirectional.** Opening a current schema validates the complete
family inventory: every primary fact has exactly one lawful seal, every seal has
exactly one primary fact, and unknown families are damage. Owner-specific
inventories additionally prove relationships that a global count cannot, such
as checkpoint/completion-event parity and the command phases allowed by each
state. A current open never creates, repairs, or reseals evidence.

**Migration is the only historical sealing authority.** The 6→7 migration
observes retained pre-v7 bytes once, inside the schema transaction, and seals
them in dependency order. A migration seal says exactly what was observed; it
does not manufacture evidence the old writer lacked. Later facts may therefore
validate through already sealed earlier facts without a weaker migration-only
projector.

Before the positive-seal chain, migration records the two channel cutoffs,
marks retained acknowledgements as version 0, populates the creation-command
marker for origin-bearing runs, seals legacy terminal effect outcomes, and
classifies only genuine raw or weak typed pre-v7 resume plans with their exact
migration-time phase. It then seals in this topological order:

```text
commands → pre-v7 resume-plan evidence → pre-v7 domain-plan evidence
→ manifests → run worlds → attestations → approvals
→ component registrations/promotions → effect preparations
→ events → opaque effect-outcome classifications
→ resume-attempt relationships → checkpoints
→ channel provenance → messages → acknowledgements
```

Legacy capability-lease lifecycle seals follow event seals, because the
historical/current lease classification reads the sealed acquisition event.
Only after those inventories agree does the migration advance the schema
version.

The compatibility paths tightened by this decision are closed, named eras:

- M1/M2 attestations retain their random ids and narrower recorded provenance;
- effect requests have three exact wire eras: M1/M2 omit `run_id`,
  `manifest_hash`, and `mode`; M3–M5 carry `run_id` and `manifest_hash` but omit
  `mode`; current requests carry all three. Historical terminal receipts retain
  the hash of their stored request era, and an unfinished historical preparation
  may execute through a lossless current view without rewriting its request
  bytes;
- `runs_resume` plans have disjoint wire eras. Current schema-7 writers emit
  only typed schema-1 envelopes. A current resume domain plan carries
  `exact-v1`; a typed pre-domain refusal is a separate plan family whose
  response is embedded in its sealed plan. Migration alone marks every retained
  raw `runs_resume` plan and each weak typed schema-6 resume domain plan under
  `resume_plan_pre_v7`. A `prepared` marker binds claim and plan without
  inventing a future terminal fact; a `terminal` marker also binds the exact
  retained response. Unfenced history cannot own an attributed attempt receipt;
- two further domain-plan families predate the exact proofs they now answer
  to, and share the resume family's mechanism under `domain_plan_pre_v7`. A
  registry promotion, evaluated promotion, or rollback plan written before
  `terminal_rejection_policy` existed cannot have its refusal re-derived
  byte-for-byte; a `runs_cancel` plan that found its run already terminal
  before `observed_event_seq` existed cannot be re-proved against the event
  that made it true. Migration alone witnesses each retained plan of either
  shape with the phase it found it in. A `prepared` witness binds claim and
  plan; a `terminal` witness also binds the exact retained response, and only
  that witness lets the stored refusal or observation replay. A command that
  is claimed but unplanned at migration receives no witness, so a plan stored
  for it afterwards must carry the current shape. Current writers refuse to
  mint either legacy shape, so the same bytes without a witness are a
  downgrade and remain damage;
- schema-5/6 actors may retain one unique unsorted array of known scopes, and
  pre-sort component definitions may retain the unique array order of `labels`,
  `change_surfaces`, and `capability_requirements`. The typed view is
  reconstructed only after reproducing the historical bytes and identity;
  current writers emit canonical order;
- pre-v7 promotions retain the authority relation their writer actually
  recorded and never authorize a new current promotion;
- pre-v7 terminal effects and capability leases retain exact migration-time
  lifecycle seals. A keyless pre-v7 effect outcome event additionally carries
  a migration-only `legacy_effect_outcome_pre_v7` seal; a current outcome must
  carry its exact effect key and can never enter that family. Current leases
  require their event provenance;
- schema-6 channel history is bounded independently by immutable maximum
  message and acknowledgement sequences. A historical reply keeps its absent
  writer/version pair, and a historical acknowledgement carries version 0.
  That acknowledgement's command id remains an opaque historical scalar, even
  if a same-named command exists later. A historical approval exchange may
  recover its plan through its approval row; advice remains opaque. Current
  replies and acknowledgements carry version 1 and their required writer. The
  two cutoffs and their singleton row are themselves one sealed fact.

No current row may enter a historical path by losing a field, and no historical
row is rewritten into a current shape. When a historical fact is genuinely
opaque, that opacity remains part of its contract.

## Consequences

- Exact valid-to-valid mutation, relocation, phase erasure, and primary-row
  deletion fail closed as `JournalDamaged`; a retry cannot reinterpret them as
  an unclaimed identity.
- Bulk recovery and query paths use the same canonical fact and relationship
  projectors as point reads. Batching changes query shape and cost, never
  evidentiary strength.
- The pending schema-7 migration owns `durable_fact_seals`,
  `legacy_effect_seals`, `legacy_capability_lease_seals`,
  the `legacy_effect_outcome_pre_v7` fact family,
  the `resume_plan_pre_v7`, `domain_plan_pre_v7`, and `resume_attempt` fact
  families,
  `runs.creation_command_id`, `effects.outcome_run_id`,
  `effects.outcome_event_seq`, `channel_messages.command_id`,
  `channel_messages.reply_provenance_version`,
  `channel_acks.ack_provenance_version`, and the
  `channel_provenance(legacy_ack_through, legacy_message_through)` cutoffs. It
  also owns the partial unique `channel_reply_command_unique` index. Because
  schema 7 is not yet released, these corrections complete the existing 6→7
  step rather than create a second migration whose only input would be an
  intermediate draft. Current attempt insertion writes its relationship seal
  atomically; migration seals only retained relationships that satisfy the same
  command, fence, and event law.
- A positive seal is a consistency boundary, not protection from an actor able
  to rewrite the entire database and every independent witness. SQLite remains
  the one trusted journal boundary.
- New durable fact or relationship families must define their exact bytes,
  selector, absence evidence, migration treatment, and bidirectional inventory
  before they are admitted.

## Rejected alternatives

- **Trusting a content-derived primary id.** It detects only mutations that do
  not also rewrite the id, and it cannot distinguish deletion from absence.
- **Using redundant fields as independent evidence.** Consistently rewriting
  every field preserves the contradiction; co-location is not independence.
- **Healing or resealing on current open.** This turns damage into new
  authority and makes the first reader a migration process without a versioned
  contract.
- **Inferring history from NULL.** Deleting current provenance would become a
  privilege downgrade into a weaker compatibility path.
- **One global database digest.** It serializes unrelated writers, gives no
  useful local diagnosis, and cannot express lawful mutable lifecycles.
- **Table-specific seal stores and algorithms.** They duplicate one mechanical
  mechanism and invite unequal retry laws. Families own semantics; the shared
  store owns only write-once seal identity.
