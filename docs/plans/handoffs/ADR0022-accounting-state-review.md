# ADR 0022 accounting slice: snapshot and continuation state review

Pre-implementation review for
[#179](https://github.com/sushiHex/constructicon/issues/179), under accepted
[ADR 0022](../../adr/0022-operator-disposal-records-abandoned-capabilities.md).
Branch `implement/adr22-accounting`, stacked on provenance head `7c24bb4`,
2026-10-13. Parent PR 180 must merge before this slice merges. This document
records intended laws and future tests, not implementation evidence. Source
and tests begin only after the review recorded below.

Root reviewed the complete document and approved test-first implementation on
2026-10-13, subject to first integrating the parent point/world-versus-complete
snapshot fix. That review establishes the proposed implementation boundary;
none of the tests below has been written or executed at this review point.

## Scope and existing boundary

The new `runs_result` response is `RunResultPreviewV2`, with an exact
`result_schema_version=2`, required typed capability accounting and explicit
`failures_partial`. Control response schema 3, Graph and manifest schemas, old
unversioned result-preview bytes and old terminal result detail remain intact.
The public result method/tool publishes v2; a named boundary decoder selects
the exact old model only when its version field is absent. Unknown, coerced or
boolean versions refuse. Old clients retain `extra=forbid` and refuse v2.

Add a separate cut-bearing accounting detail address using the existing
`DetailResolver`, canonical public serialization, content hash, UTF-8 chunks
and actor-bound cursor law. Accounting detail is available on RUNNING and
PENDING as well as terminal runs; it does not borrow the terminal-only result
alias or change its historical payload/digest.

This slice exposes no disposal mutation, administrative receipt, private
relationship, reason or reason-bearing digest. All currently lawful lost facts
are exact migration-witness-backed opaque facts. Disposed count zero is backed
by current canonical provenance: a new lost fact without a current receipt or
old witness fails closed; no current disposal writer/receipt family exists.
Do not manufacture a receipt or administratively label old lost facts to test
an accepting disposal path. That accepting privacy/receipt proof is slice 3.

## One co-located read, not independently agreeing reads

Add one operation-specific typed read on existing `ControlPlaneStore`, the
exact journal already assembled into the control plane. It returns an internal
accounting snapshot containing validated run status/identity, current latest
event sequence, selected cut and complete public accounting members. It is not
a new protocol or an expansion of `InMemoryControlStore` into a second journal.
The public API and detail resolver use this read rather than combining
`run_head`, `run_record`, `max_event_seq` and `capability_leases` results.

The SQL implementation establishes one existing `_read` snapshot and uses a
connection-accepting canonical projection for both initial result and exact
detail cut. Validate the run world/lifecycle and complete event extent; select
all acquisitions by the existing row/acquisition/legacy-owner law; validate
full current row histories, reverse lease-event-to-row edges, positive era,
the reconstructed floor commitment and historical lost witnesses. Only then
reconstruct the selected cut and compute exact totals. A selected run's absent
row with retained era/acquisition evidence is damage, not an empty summary.

Status and latest accounting share this read snapshot. Outputs, failure
preview and old terminal detail retain their existing separate read semantics
and limits; this slice does not claim a coherent complete run result. An
interleaving after the accounting snapshot must not change which bytes its
new detail reference names.

## Historical reconstruction and public records

Reuse `CapabilityLeaseHistory`, `validate_accounting_run` and the same exact
history law established by slice 1. Factor reconstruction out of the existing
inventory-hash routine where necessary so floor validation and arbitrary
supported cut projection cannot disagree about state. A current acquisition
exists at a cut only after its positive `LeaseAcquired` event. A legacy
acquisition is present at the migration floor, starts from its exact sealed
initial lifecycle, and advances only through applicable exact later events.
Its acquisition event sequence remains unknown (`None`), never zero.

Current mutable row state/update time is only the final-history consistency
check, not the state of an older detail cut. Include all acquisitions at the
cut, in canonical exact `(lease_id, acquisition_epoch)` order. Later legitimate
acquisitions are absent from earlier cuts; later legitimate transitions leave
earlier state and public bytes unchanged. Require the positive per-run era and
reconstructed complete floor inventory on every accounting read, including a
genuinely empty run. Every migrated run uses its recorded floor; only a proved
creation era admits history from zero. A future or below-floor cut refuses.

Public detail carries the run id, selected event cut and full exact acquisition
identities/lifecycle, with typed unknown acquisition sequence and loss cause.
Use only needed public fields, not a dump of private storage proof objects.
Opaque lost means cause and physical cleanup unknown. Active/closed accounting
does not assert physical clearance; zero totals prove only validated durable
rows. The summary contains exact active, disposed, opaque-lost and combined
lost counts, cut and its required public `DetailRef`; a validator enforces the
lost-count equation. Counts cover all rows, not the first 100.

Receipt links and disposed classification are future extensions of this same
public projection. No command request/plan hashes or reason text are eligible
public fields. Each summary/detail reference hash binds only its exact public
record. Current actor-or-ADMIN command-detail authorization remains separate.

## Batched history validation and cost

Do not run global `validate_capability_lease_inventory` for every result:
validating unrelated runs is unnecessary, and per-pair UDF scans repeat the
whole journal. The operation needs all rows and reverse lease events for its
selected run, plus foreign events that name its exact selected identities.

Use a coherent batched prefetch to obtain selected-run lease events and all
same-pair events across runs. Preserve the existing strict identity predicate
before deciding which foreign facts are relevant. Every selected-run lease
event must resolve to its exact row/run; every relevant same-pair event retains
the canonical projector's cross-run checks and positive event seal. Do not
silently drop an unrecognized selected-run event or restrict histories by run
alone. Do not validate malformed unrelated events just because a global raw
prefetch saw them. Keep old opaque pre-seal event interpretation; no fabricated
initial position or newly inferred historical transition authority.

The canonical pair history validator should consume the prefetched exact
events instead of executing its UDF scan again for each pair. Existing point
reads still use the same validator with its normal query. Per-event seal
lookups may remain indexed point reads; the target is removal of repeated
whole-journal work, not a general query engine or cache. If helper context
reuses already-proved run/era facts, it exists only within this one SQLite
snapshot, never globally or across requests.

Measure query/identity-UDF work for over 100 valid pairs and additional
unrelated runs. Report remaining linear/global prefetch and serialization cost
honestly. Add a foreign same-pair contradiction test so a run predicate-only
optimization is demonstrably rejected. Preserve any historical named writer
shape; raise a design conflict rather than silently broaden or discard it.

## Every suspension, read boundary and return

The journal result/detail projection is synchronous. There is no new provider
await, task, scheduler or persisted command phase. Transports may await actor
derivation before one control delegation; authorization precedes any new
accounting read. A process cancellation before/after the synchronous projection
cannot turn a partial projection into a trusted result.

| Boundary | State that may change | Required behavior |
| --- | --- | --- |
| Transport actor await | Identity/authorization can fail before delegation. | Delegate once with the derived actor; no caller identity field or early storage read. |
| First SELECT in `_read` | Another process may commit just before the snapshot starts. | All subsequent status, extent, rows, proofs and cut calculations observe that same coherent state. |
| Batched row/event/proof reads | Another writer can close/acquire after one statement. | The current read remains internally coherent; affirm the writer committed and a later read sees it. |
| Initial result return | Domain state may change after snapshot release. | Use the already projected public accounting payload to mint its ref; do not re-query a different state while assembling the summary. |
| Detail reference resolution | The run may have acquired/closed more rows after reference issuance. | Reconstruct the exact URI cut, verify current canonical provenance and the sealed floor, and render identical historical public bytes. |
| Between chunks | Later state changes, actor changes, cursor/ref tampering or proof deletion can occur. | Reauthorize and revalidate the same immutable cut on each chunk. Legitimate later changes preserve bytes; damage or changed actor/cursor/ref refuses rather than substituting current data. |
| Result outputs/failure/terminal-detail reads | These pre-existing reads can observe later separate state. | Retain their stated semantics; do not advertise full-result snapshot coherence. |

The resolver may create a `DetailRef` directly from an already validated public
snapshot through a narrow helper; URI construction and public hashing remain
defined once. It must not require a second accounting query to mint the initial
reference. Caller-chosen accounting URIs use the existing READ family lock
before resolution and strict cut parsing; no mutable accounting alias is added.

## Affirmative failure-preview partiality

Read at most 1,001 events to obtain positive evidence that the existing
1,000-event scan bound omitted history. Project only the first 1,000 as before.
Apply the existing keyed failure preview and sorted first-20 rule, and mark
partial when its distinct failure inventory exceeds 20. Do not infer
completeness from an empty fault list or fewer observed failure kinds when the
event scan itself was bounded. Exactly 1,000 events and exactly 20 failures
have permitting tests; 1,001 events and 21 distinct failures make each bound
bind independently. The flag states bounded-preview completeness, not complete
executor telemetry or complete run history.

## Tests written first and handoff boundary

Planned new suites: `tests/core/test_capability_accounting_result.py`,
`tests/substrate/journal/test_capability_accounting_snapshot.py`, and
`tests/api/test_capability_accounting_result.py`, with narrow existing detail
and MCP tests as needed. Every refusal has its accepting counterpart.

- Empty, active, closed and actual old opaque-lost runs produce exact summary
  and detail; SUCCEEDED with witnessed opaque loss remains truthful. Over 100
  pairs prove exact totals and complete chunked identities without truncation.
- Controlled commits between status/inventory/proof statements prove one read
  snapshot affirmatively, then the next read proves the writer's changed state.
  A deliberately mixed supplied snapshot is refused rather than hidden.
- A reference issued before close/new acquisition renders its exact earlier
  cut across subsequent status/ownership changes and between chunks. Unknown
  legacy acquisition sequence remains `None`; below-floor/future/bad cuts
  refuse, exact floor and current-zero creation cuts permit.
- Source row/event/proof/era deletion, valid-to-valid rewrite, eventless legacy
  erasure and foreign same-pair facts fail closed on result and detail reads.
  Reverse acquisition and transition orphan checks cover both event kinds.
- Old preview fixture bytes decode as exactly the old model with accounting
  unknown. Exact v2 round trips; old strict readers reject v2, and boolean,
  float, unknown or removed version with new fields refuses. Old terminal
  detail golden bytes/digests remain unchanged after this slice.
- READ and ADMIN permit; OPERATE-only/no-scope refuse before store work.
  Caller-selected references, actor-bound continuations and MCP single actor
  derivation/delegation use their established genuine/fake client seams.
- Exactly-at-bound and bound-exceeding event/failure inputs test affirmative
  `failures_partial`. Recursive public field checks find no private proof,
  request/plan hash or synthetic disposal receipt/actor/reason.
- Cost instrumentation shows one batched history acquisition rather than one
  whole-journal UDF scan per pair, while retaining the cross-run refusal test.

This slice completes truthful result v2 and accounting detail only. It does
not claim an accepting disposal/privacy proof, administrative batch races,
domain/command crash replay or physical cleanup. Root owns the mutation script,
living record, archive manifest, CI and PR; this lane sends stable assertion
killing test ids and does not commit or edit accepted ADR/plan bytes. Its own
Python 3.12 `.venv312` is used with `PYTHONIOENCODING=utf-8`, every shell stdin
closed, and no vendor executable or credential access. Unexecuted checks remain
explicitly unverified.
