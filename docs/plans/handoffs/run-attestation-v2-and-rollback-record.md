# Run-scoped proof identity and truthful rollback results

Refs #371 and #373. The owner adopted the identity proposal and directed this
implementation in the 2026-11-05 delivery wave. [ADR 0023](../../adr/0023-ordinary-attestations-bind-their-minting-run.md)
records the additive decision. Accepted historical ADR/plan/proposal bytes are
unchanged; GitHub issues own current work state.

## Behavior

Ordinary proofs now include the fenced minting run in their v2 identity. Equal
drafts from independent valid runs get distinct proofs. Same-run retries retain
the exact prior fact before observing time, including witnessed historical v1
proofs. Policy IDs, command plans and one-proof/one-move semantics are unchanged.
The accepted occupied historical policy-ID conflict has the named refusal
`policy_attestation_id_owned_by_history`, with no mutation.

The atomic 9-to-10 rung validates the old inventory under its held write lock,
adds exact positive witnesses only for ordinary-v1 rows, leaves compatibility
context, validates the current inventory and publishes the version. Existing
proof bytes, IDs, references, timestamps and primary seals are retained. Current
readers refuse unwitnessed v1 evidence; current writes never create historical
witnesses. Migration context is confined to its exact connection and transaction
and resets on exception. Its SQL callback is explicitly non-deterministic;
JSON identity/seal predicates remain pure.

Point, run, channel and promotion consumers share the identity/era law. Before
cursor or actor filtering, guarded reads validate distinct ordinary-proof
creator worlds through the existing canonical projector in the same SQLite
snapshot. This includes retained manifests, creation-command plans and clone
source locks. SQL separately binds each proof to that proven creator's manifest;
it does not maintain a second partial world validator. Current administrative
disposal and read-only maintenance diagnosis use the current schema version.

A fresh rollback plan now refuses an already consumed deterministic policy
proof with `control.registry.rollback_proof_used`. Direct registry rollback
uses the same fresh planner. Completed command replay and previously persisted
plans retain exact historical receipt reconciliation, even after later moves.
Such a result is not a statement of the current stable pointer or unique
causation by a concurrent command. No policy identity or old result is rewritten.

## Evidence and review

The genuine schema-9 writer at `15e87ef20ed3233c12a289df34088dc0ac8f8a84`
reproduced the committed SQL fixture exactly (SHA-256
`0d1d0a4bd13d23f7dc2808fbb6fc94d42cb86a6ef16d72261ba3b4c71d7385b6`).
An independent reviewer repeated that comparison. Migration tests preserve all
logical facts and add exactly three era witnesses. The actual old reader
refused schema 10 with the logical dump, version and journal mode unchanged.
Fixture SQL is LF-pinned. Synthetic older-rung downgrade helpers are explicitly
synthetic and reject unsupported dependent JSON instead of inventing history.

Accepting/refusing tests cover independent merge/promotion proofs, policy mint
ordering, historical/current retry and the accepted policy conflict, ownership
reclaim, creator-world and witness damage, SQL filtering, promotion races and
reopen. Actual subprocess death covers both attestation commit boundaries and
three migration boundaries; real constructor interleaving verifies atomic
witness/version publication. Same-connection, cross-connection and exception
tests verify that migration compatibility cannot survive into current reads.

The initial journal/migration selection passed 807 tests with seven platform
skips before the final SQL correction. Final affected selections covered the
new identity/migration tests, run projection, request provenance, idempotency
and complete command response-loss file (191 passing); earlier narrow reader
selections also passed. Ruff, strict typing and import contracts passed on the
affected source. These are local receipts, not relabeled final-head CI.

Independent review reproduced two creator-authority gaps: a different manifest
could hide behind a filtered run or off-actor inbox, and a missing creator
command-plan seal could do the same after a partial SQL fix. The canonical
prefilter closes both. The reviewer verified those cases, clone-lock damage,
snapshot interleaving, callback reset and 98 cross-era migration tests at final
identity source `d05a2f4fe0349912222280cdc8855f16ab8312ba`. No remaining blocker
was found within that review scope. A displaced opposite-family seal selector
found during implementation self-review is also covered by shared joins and
refusing tests.

The rollback candidate `fd06d59e5d7ca1ca8b63ee63659d076a09c426cb` passed its
affected tests and received independent source review plus three public/direct
recurrence and preplanned-recovery checks. Its new refusal is distinct from
stable-moved because the current pointer can still equal the caller's expected
baseline. This rejected naming choice was corrected before delivery.

The existing registry inventory includes distinct mutants for creator-scoped
identity, point witness and creator authority, filtered witness visibility,
misplaced seal selection, complete creator-world prevalidation, proof/creator
manifest equality and consumed rollback proof reuse. Baselines and assertion
kills are required; errors do not earn kill credit. Final combined inventory
and required CI receipts belong in the delivery PR.

## Read-only diagnostic successor

The [installed diagnostic note](M8-maintenance-installed-diagnostics.md) pins
the prior schema-9 helper. The actual blob at `15e87ef` reproduced its
`421790bb5f850627f2828179efcc28bbd346134a35ccb5097356b3262f6d39c3` digest.
That note and the older sidecar procedure are unchanged. The evidence helper
bytes are unchanged as well. The current diagnostic reads the current schema
version and retains the existing read-only snapshot and output contract:

```text
SCHEMA10_DIAGNOSTIC_SHA256=0e89e8f6c6cfcaf37d1a785dd1b2e1198d2d101c6605361dcc682e3c36c637b8
```

The pin test distinguishes all three source eras without requiring Git
ancestry in CI. This is a source-byte comparison, not a host installation,
permission to inspect a live writer or a reinterpretation of old evidence.

## Limits

The creator prefilter validates distinct retained ordinary-proof creators per
guarded read. Its scaling cost is unmeasured; it is not a persistent cache or a
claim of constant-time pagination. No general recovery scan or full fact
inventory is added to these reads. Platform skips are not physical evidence.
The migration cannot infer facts erased with all their seals and references.
This delivery includes no credentials, private-host operation, vendor binary,
model call, production provider availability or M9 model-quality claim.
