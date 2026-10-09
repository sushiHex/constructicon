# 0022 — Operator disposal records abandoned capability accounting

Status: Proposed

Issue: [#143](https://github.com/sushiHex/constructicon/issues/143).
Baseline inspected: `d355416`. Only the owner may accept this ADR. Merging its
documentation under the normal PR gate does not accept it; the issue remains
open. Implementation needs a separate issue after owner acceptance and the
merge of [#132](https://github.com/sushiHex/constructicon/issues/132).

## Problem and existing facts

The final implementation direction on
[#132](https://github.com/sushiHex/constructicon/issues/132#issuecomment-6072723429)
requires the journal to refuse transitions to all four terminal statuses,
including PARKED, while any capability row is `active`. Cleanup failure then
leaves a RUNNING run whose worker releases ownership. This guard is not present
at the inspected baseline. A retained node completion plus failed cleanup is
one way to reach the proposed RUNNING/owner-NULL state; it must not be described
as a FAILED run after #132's guard is installed.

`runs_resume` already admits RUNNING without a live owner:
`RESUMABLE_RUN_STATUSES` maps it to `RunReclaimed`, the command rejects live
ownership, and explicit `RunHost.launch` clears process-local deferral. The
claim of a missing retry route in #132's earlier design comment was corrected
in its final handoff. The obstruction is the walker: `_reconcile_stale_leases`
runs before its first control check. Persistent reconciliation failure therefore
prevents an already recorded cancellation from being observed on each attempt.

The existing `CapabilityLease` contract permits `active`, `closed`, and `lost`.
Its durable table identity is `(lease_id, acquisition_epoch)`; a logical lease
id alone can name several physical acquisitions. The current recovery loop
selects only `active` rows from older epochs. No current writer records `lost`.
The existing `transition_capability_lease` requires worker `RunLease` authority,
and the journal checks exact canonical `LeaseTransition` payloads. Neither is
an administrative disposal API.

The current public `RunResultPreview` has only run id, status, outputs, failures,
and optional detail. Its terminal result detail includes no capability
inventory. Neither already exposes lost accounting.

Source anchors: [resume contracts](../../src/constructicon/core/control.py),
[resume command](../../src/constructicon/api/_control_commands.py),
[host launch](../../src/constructicon/api/run_host.py),
[recovery ordering](../../src/constructicon/runtime/walker.py),
[capability contract](../../src/constructicon/core/manifest.py),
[fenced lifecycle and exact lease history](../../src/constructicon/substrate/journal/_sqlite_execution.py),
[result query](../../src/constructicon/api/_control_queries.py), and
[result detail](../../src/constructicon/api/detail.py).

## Proposed decision

Add one transport-neutral control mutation, `runs_dispose_capabilities`, requiring
`constructicon:admin` and a caller idempotency key. It abandons accounting for
explicitly named acquisitions of one RUNNING run with NULL journal ownership.
It moves only those rows from `active` to `lost`, with `disposition=None`.
The command does not cancel, resume, or terminalize the run. Existing
`runs_cancel` and `runs_resume` remain the separate commands for those intents.

`lost` means an administrator explicitly stopped retrying that acquisition's
cleanup obligation. It is not evidence of process death, physical cleanup,
lock release, candidate disposal, store reuse eligibility, or successful
`release`/`discard`. External acquisition fences, supervisor custody, and store
locks retain their existing authority. NULL ownership proves only that the
journal has no current worker owner. It proves no physical quiescence. This
meaning is specific to receipt-backed disposal; retained opaque `lost` facts
have unknown cause and must not acquire an invented administrative meaning.

### Exact request and admission

The strict request contains a run id, a nonempty set of at most 100 named
`(lease_id, acquisition_epoch)` pairs, a bounded reason, and the existing caller
key. Duplicate pairs refuse; pairs are sorted canonically before request
hashing. Each id is a canonical nonempty Unicode scalar string bounded to 200
characters; epochs are exact positive integers. The reason is canonical,
nonempty Unicode scalar text, at most 1,000 characters and 4,000 UTF-8 bytes,
with no control characters. Refuse violations rather than trimming, truncating,
or silently dropping members. The reason is retained administrative text;
callers must not place credentials or private resource paths in it.

Authorization precedes command claiming or lifecycle startup. An OPERATE actor,
even the run's submitting actor, cannot dispose. A transport derives its actor
and delegates once; it accepts no caller-authored identity or authority object.
The API may be exposed through an ADMIN-gated MCP handler under ADR 0012; MCP
does not acquire journal authority of its own.

Plan preparation uses one coherent journal read of the run and all named rows.
Admit only RUNNING with `owner_id=None` and every named row belonging to that
run, `state="active"`, and `disposition=None`. A missing, closed, or already-lost
member refuses the entire request. A non-NULL owner refuses even if expired;
the ordinary recovery path must first unwind and release it. This deliberately
narrow command serves #132's owner-NULL failure state without taking over an
owned attempt or claiming that expiry proves a dead process. Historical
terminal runs with active rows are outside this proposal.

After claiming a schema-valid request, observational row refusals are itemized
for every named pair: missing, wrong run, closed, opaque lost, already
disposed, or another baseline mismatch. An already-disposed item carries
its validated public receipt reference. At most 100 pair items are returned,
matching the
input bound; run-level ownership/status faults remain explicit as well. A
single bad member refuses the batch and changes no member.

The immutable typed domain plan seals the actor/command/request identities,
run id and manifest identity, expected RUNNING status, NULL owner and owner
epoch, latest event sequence, canonical reason, and every exact named row's
identity, immutable acquisition fields, expected lifecycle, update time, and
validated acquisition/lifecycle provenance. A hash of that complete validated
baseline binds each row; it is not a hash of the selector alone. The existing
public `RunHead` omits owner epoch and lease inventory, so it is insufficient
as this plan's snapshot: add an operation-specific L0 snapshot on the existing
co-located store. Use real SQLite contract tests and instrumented providers,
following the existing `store_approval_exchange` transaction precedent.
`InMemoryControlStore` deliberately is not a `ControlPlaneStore`; do not expand
it into a second journal merely to test this command. This adds no interface,
lease manager, or store abstraction.

### One administrative transaction and receipt

Extend the existing `ControlPlaneStore` transaction contract on the exact
assembled journal. Applying disposal checks the command claim fence and its
sealed ADMIN actor and typed plan, then checks the complete run fence and
every exact row baseline again, inside the same SQLite write transaction.
No awaited provider operation or separate worker claim occurs in that
transaction. A command plan is intent; only this deterministic, authorized
store operation may turn it into disposal authority.

If the fence still agrees, that transaction:

1. Keeps owner id and lease expiry NULL and leaves owner epoch unchanged.
   Existing worker writes require both owner id and epoch; NULL already fences
   a stale token. Only a subsequent real worker claim advances that epoch.
   It changes no run status, cancellation flag, manifest, checkpoint, output,
   or effect receipt.
2. Moves all named rows to `lost`/`None` and emits one existing canonical
   `LeaseTransition` per row, with its exact old state, identity, observed time,
   and the existing `legacy_base_hash` only when that row has a legacy seal.
3. Appends one new typed `CapabilityDisposalRecorded` audit event, binding the
   command id, request/plan digests, run fence before and after, named row
   baseline hashes and exact transition sequences. The request and plan
   digests bind the reason; its text stays in the private request and plan.
   This event is the immutable domain receipt, not an `EffectReceipt`: no
   external effect was performed.
4. Co-seals one `capability_disposal` command/event relationship over immutable
   command identity/actor/request facts, typed plan, audit event, and ordered
   transitions. The live command owner/epoch fence is checked at application;
   an application claim epoch may be recorded as a historical fact but is not
   a requirement that later command ownership remain unchanged.

Use the existing journal transaction, event insertion, and positive-seal
machinery. Administrative event-sequence allocation must compare the planned
NULL-owner/status/epoch/event fence in that transaction; it must not construct
a fictional `RunLease` or call a worker writer with invented ownership. The
command attribution lives in the typed audit receipt, and the reason text in
the private request and plan, never as extra fields on the existing canonical
`LeaseTransition` payload. Current worker writers must refuse minting `lost`
or reactivating a lost acquisition; an existing historical transition retains
its original interpretation. Disposal does not change a closed row.

A worker claim and disposal serialize against the same runs row. If the worker
claims first, disposal changes no row and returns the durable refusal below.
If disposal commits first, a later worker claim observes its new events and
ordinarily advances the epoch; recovery skips the lost rows. An old explicit
resume plan can be superseded by the new event fence. In particular, a
submitted intent queued before worker claim can be dropped by the pump after
disposal, then ordinary RUNNING recovery can start an attempt. Submission is
not proof the queued attempt claimed its fence. A fresh resume key is needed if the
operator requests a new explicit attempt; disposal does not guarantee that
every route needs one or that an old submitted command becomes rejected.
No check before a transaction or process-local lock can substitute for this
comparison. Another administrator's overlapping disposal similarly causes
one transaction to refuse; batches never partially apply.

The relationship family has primary key `command_id` and secondary selector
`(run_id, audit_event_seq)`. Its one canonical projector independently
validates the immutable ADMIN command identity/actor/request, typed plan,
exact audit event, each contiguous preceding transition in canonical pair
order, each acquisition's existing provenance, and the final lost/None
lifecycle. Both command and event point reads, retries,
and bounded inventory reads use that projector. Bidirectional open inventory
requires each new audit event to have exactly one relationship, and each
relationship to own exactly one audit event and the complete planned batch.
The row/history projector additionally requires every transition to `lost` to
be owned by exactly one disposal receipt or one positive pre-v8 witness, with
disjoint provenance eras. An initial legacy lost lifecycle similarly requires
its explicit historical witness. Audit-to-relationship inventory alone cannot
prove this: deleting both audit and relationship must still fail the surviving
lost transition's row-to-proof check. A deleted event/row with retained proof
is damage, not absence or permission to dispose again. A command owning that
receipt cannot become rejected.

Receipt projection never compares its historical application claim with the
command's current mutable claim owner/epoch. Reclaiming a prepared command
after domain commit legitimately changes that fence, and completion releases
it. The immutable relationship must remain valid across those handoffs, or
the domain/completion crash seam could not replay successfully.

Version the persistence extension rather than silently admitting a new fact
family into schema 7. If no intervening change advances it, use migration 7→8.
First validate the old journal through its existing canonical projectors.
Migration alone mints `capability_lost_pre_v8` witnesses for its valid retained
lost transitions, keyed by exact `(run_id, event_seq)` and selected by
`(lease_id, acquisition_epoch)`, hashing their exact canonical event bytes and
identities. It separately mints `capability_initial_lost_pre_v8` witnesses for
valid legacy initial lost seals, keyed/selected by the exact lease pair and
binding run identity, base hash, and canonical initial lifecycle bytes.
These classify only observed old writer facts, never a disposal actor or
reason.
Both families have bidirectional sealed inventories, migration-only mint
guards, and canonical point/batch projectors. Current reads/writes/open cannot
mint either family; missing current disposal attribution is never a historical
classification. Fixtures produced by the actual old journal writer must prove
the retained shapes. Existing lease events, legacy seals, plans, responses, and
manifests retain their bytes.

The same migration records a positively sealed per-run
`capability_accounting_era` row, keyed and selected by run id, binding the
exact retained run world,
`source="schema7-migration"`, and that run's event-sequence floor. The floor is
the validated latest sequence at migration, not a sequence invented for a
legacy initial lifecycle. Its witnesses must name only facts at or before
that floor. New runs co-commit their era row with creation, using
`source="schema8-creation"` and floor zero; their full history begins at
creation.
Only migration can classify an existing run as migrated, and only actual new
creation can mint the new-run era. Row-to-seal and run-to-era inventories
reject missing, deleted, moved, or altered era evidence; a current open cannot
repair it. This small operation-specific era record bounds the accounting
projection described below; it is not a new generic query facility.

### Command law, refusal, and replay

The command follows `authorize → claim → plan → apply once → record → replay`.
After authorization, malformed JSON, schema-invalid input, oversized fields,
duplicate pairs, and invalid keys return `REQUEST_INVALID` before claiming:
they create no command and are not a replayable durable refusal. For a claimed,
schema-valid request, pre-domain observational refusals retain their complete
typed response in the existing rejection-plan family. Once a domain plan
exists, fence supersession has one
canonical refusal determined by that immutable plan. The failed comparison
and terminal rejection commit together under the command fence in the same
store transaction; its positive terminal seal retains the actual rejection
decision. Mutable later ownership or row state cannot change that refusal on
replay. Return fresh-key repair guidance, not an instruction to retry a
terminally rejected key.

After a successful domain commit, complete the command with a typed bounded
result: `status="disposed"`, run id, exact named pairs, count, command metadata,
receipt reference, and `physical_cleanup="unverified"`. This response derives
only from the sealed plan and validated domain receipt. Completion remains a
separate command phase so recovery exercises the existing domain/completion
crash seam. A repeated key/request first resolves the receipt or terminal
response; it does not require those rows still to be active. Matching current
`lost` rows alone never count as this command's receipt.

| Interruption | Required retry behavior |
| --- | --- |
| After plan commit, before domain mutation | Reclaim the command; apply the same sealed batch at its original fence, or retain the canonical superseded refusal; never re-plan from new rows. |
| After domain mutation, before command completion | Resolve the positively sealed batch receipt; complete the same success response without another transition or provider call. |
| After command completion, before delivery | Replay the stored response, changing only existing replay metadata; no journal domain mutation. |

A fresh key naming a row already `lost` or `closed` refuses, even when another
command disposed it. A same-key success replays after later recovery or status
changes, because its receipt is historical evidence. An exact batch that was
refused stays refused after the run becomes idle. Key reuse with changed pairs,
run, or reason is the existing typed idempotency conflict and changes nothing.

### Truthful public accounting and compatibility

Add an explicitly versioned result projection, `RunResultPreviewV2` with
`result_schema_version=2`, as the new `runs_result` response. This field is
distinct from sibling command responses' existing global `schema_version=3`.
It retains the existing run/status/outputs/failures/detail fields and adds
a required typed capability
accounting summary: exact `active_count`, `disposed_count`, `opaque_lost_count`,
`lost_count = disposed_count + opaque_lost_count`, `through_event_seq`, and an
accounting detail reference. Receipt-backed lost rows count as disposed and
render "capability cleanup abandoned; physical cleanup unverified", including
when the run status is SUCCEEDED. Witness-backed old lost rows render
"lost capability; cause and physical cleanup unknown". Counts describe
validated durable rows, never provider success. The summary contains no
inferred disposal actor/reason for opaque facts and no claim of physical
clearance when all counts are zero.

Derive status and accounting through one coherent read snapshot; count all
validated rows rather than a truncated preview. Full identities and disposal
receipt links are in bounded/chunked detail pinned to that event cut, including
on a RUNNING run. A new accounting-detail URI family is needed: the present
terminal-only result reference cannot supply it. Issue only server-derived cuts
at or after the sealed per-run accounting floor; refuse any requested cut below
that floor or without its era evidence. For a migrated run, existing canonical
history and legacy initial seals establish its state at that migration floor,
then exact later events reconstruct supported cuts. The old legacy seal alone
cannot establish its position in arbitrary earlier event history. New runs
have full history from floor zero. Detail validates disposal relationships and
old witnesses and never reads mutable current rows as the state of an older
cut. Public detail authorization is the existing run-read
scope. Keep the free-text reason and actor's private command detail behind the
existing command actor-or-ADMIN authorization; public audit events and
accounting detail expose the disposal event id and existing plan/request
digests, not private reason text, a separate public reason digest, or the
actor's private command record. Event
summary/detail reads therefore need no weaker or special authorization path.

The current old projection is a live query, not a durably stored command
response. Its compatibility fixtures retain the unversioned shape; absence of
`result_schema_version` selects exactly that shape, with accounting unknown,
never fabricated as zero. Current writers emit version 2 only. Do not silently
add fields to the unversioned old preview or weaken `extra=forbid` in old
clients: they must refuse and upgrade for new result responses. Other existing
control schema-3 responses keep their wire shapes; this result family's version
does not allocate a new
global control schema. Existing terminal result detail bytes/digests remain
unchanged; the accounting reference is separate. Historical command responses
are not rewritten, and missing current disposal proof never selects a legacy
fallback. Publish the new response and tool schema through the existing typed
control/MCP vocabulary; no Graph or manifest schema change is required.

Current `runs_result` reads status, materialized outputs, failure events, and
detail separately; it scans at most 1,000 events and retains at most 20 failure
items. These are pre-existing query limits, not defects introduced by disposal
or behavior fixed by this documentation. V2 must explicitly mark its bounded
failure preview partial when either bound omits evidence, using affirmative
scan/truncation evidence rather than interpreting absence as completeness.
The new coherent-read promise covers status and capability accounting only;
outputs, failure preview, and terminal detail retain their existing semantics
and limits. No generic query redesign is proposed.

### What the next attempt can do

Disposal does not promise the next attempt terminates: unnamed active rows can
still fail reconciliation and keep #132's terminal guard engaged. Lost rows are
skipped by the existing recovery selector; closed rows remain unchanged. When
all remaining active obligations reconcile, the ordinary first control check
can observe retained cancellation and record CANCELLED. Outputs then follow
the existing cancellation contract, rather than being promised by disposal.

Without cancellation, the existing walker restores matching checkpoints and
runs misses under fresh acquisitions. A retained completion can produce
SUCCEEDED without repeating its invocation; lost accounting remains visible
alongside its outputs. A new acquisition may still fail against a retained
physical guard or store lock. Disposal does not authorize reuse of an old
resource, bypass adapter checks, or retroactively prove an output's physical
publication. All ordinary effect, capability, and output contracts still apply.

## Alternatives and tradeoffs

- **Keep retrying or add a retry command.** Existing resume already retries;
  another command does not remove the reconciliation obstruction. Retrying
  remains preferable when cleanup can recover without abandonment.
- **Force CANCELLED or invent a run status/daemon.** This bypasses #132's
  accounting invariant or creates a second recovery owner. Named disposal and
  the existing resume/cancel commands suffice.
- **Mark closed/released/discarded.** That would assert a provider operation
  never proved. Existing `lost`/`None` records the narrower fact truthfully.
- **Take over an expired non-NULL owner.** That broadens this escape hatch into
  administrative worker takeover. Requiring NULL ownership reduces scope but
  can force the operator to wait for ordinary recovery/release, and a competing
  recovery claim can supersede the plan. It still establishes no process death.
- **Update rows directly or fabricate worker authority.** Neither proves the
  command law, worker-claim race, or provenance. A co-located administrative
  transaction adds a small explicit authority law to the existing journal.
- **Infer success from rows already lost.** That credits the wrong command and
  loses reason/actor evidence. Only the exact positive receipt replays success.
- **Hide lost behind a terminal result detail.** Current detail contains none,
  and a stuck RUNNING run has no terminal result. Versioned summary plus an
  immutable accounting cut costs a client upgrade and makes abandonment visible.

## Required future evidence

None of the following proofs has been implemented or executed by this docs
slice. The separate implementation must supply credential-free tests of both
acceptance and refusal and assertion-only mutation evidence:

- Real SQLite contract tests admit exact ADMIN disposal and
  refuse OPERATE, non-NULL ownership (live and expired), wrong run/epoch,
  duplicate/oversized/noncanonical input, and mixed active/nonactive batches;
  input refusals prove no command claim, and observational refusals prove a
  complete bounded per-pair response, including existing receipt references.
- All three crash seams in the table, including real process restart over a
  durable fake world, prove one receipt, an unchanged owner epoch, exact
  transitions, and unchanged canonical success/refusal responses.
- Deterministic worker claim, heartbeat, resume-plan, and overlapping disposal
  races prove the accepting and superseded paths and no partially applied batch.
  A submitted resume queued before claim is superseded by disposal; test both
  dropping its intent and subsequent ordinary recovery, without falsely
  promising that its already-submitted command turns rejected.
- Exact event/relationship/plan/row deletion, relocation, valid-to-valid rewrite,
  deletion of both audit and relationship with a surviving lost transition,
  receipt omission, and false legacy classification fail closed on point,
  batch, retry, query, and open inventory paths. Schema-7 fixture migration
  preserves bytes and never invents old disposal provenance. Migration-only
  witnesses and per-run accounting floors must resist current minting,
  deletion, relocation, and valid-to-valid alteration; below-floor cuts refuse.
- Providers are instrumented: disposal and replay call neither `close` nor
  `reconcile`, and neither remove physical guards nor unlock/reuse stores.
  A retained guard must still refuse a fresh acquisition after accounting loss.
- Lost rows versus unnamed active rows, recorded cancellation, checkpointed
  outputs, and fresh uncheckpointed acquisition exercise the next-attempt
  outcomes. The #132 terminal guard remains binding until no active rows remain.
- Every published field has an invariant bound; inputs at those bounds make
  them bind. Result summary/detail cuts stay coherent across later disposal,
  recovery, and resumed attempts. Failure previews whose bounds actually bind
  must report partial. Current/legacy result readers, receipt-backed versus
  opaque lost facts, event/command/detail authorization, and MCP's single
  delegation receive explicit compatibility and secret-free accepting-path
  tests.

## Independent review dispositions

Claude's single cross-review (`job_98aaf8880642`, actual `claude-opus-5-5`)
reviewed the Proposed ADR at `f580d7d`. It found the core decision valid
without a redesign and reported nine refinements. The reviewer could not
read GitHub issues; the drafting agent and root independently read both
issue threads.
The following source checks reproduce its premises; these are documentation
corrections, not executed proof of the proposed implementation.

| Finding and classification | Disposition and source premise |
| --- | --- |
| 1. Introduced: lost-to-receipt coverage missing. | Adopted. `_validate_capability_lease_history` accepts canonical `lost` independently of attribution. Require row/history-to-proof coverage, exact migration-only old witnesses, and deletion-of-both evidence tests. |
| 2. Introduced: all old lost facts labeled abandoned. | Adopted. Existing history records no disposal actor/reason. Split disposed and opaque counts and meanings; never invent old administrative intent. |
| 3. Design choice: full transactional double requirement. | Adopted simplification. `substrate/control.py` and `test_control_store.py` explicitly keep the memory ledger outside `ControlPlaneStore`; use real SQLite and the existing co-located-method precedent instead of a second journal. |
| 4. Introduced: result version confused with global version; nonexistent durable old query responses. | Adopted. `RunResultPreview` is unversioned live query data; choose `result_schema_version` and limit byte-preservation claims to real command responses and terminal detail. |
| 5. Introduced: legacy initial lifecycle given an invented event position. | Adopted. `_sqlite_leases.py` retains state/disposition/update time without sequence. Add positively sealed accounting floors and restrict new cuts; do not claim arbitrary old-cut reconstruction. |
| 6. Introduced: malformed requests incorrectly treated as durable refusals; batch diagnostics underspecified. | Adopted. `_begin_command` refuses malformed key/JSON before claiming. Distinguish input from observational refusal and itemize every named pair within the request bound. |
| 7. Introduced: queued resume supersession stated too strongly. | Adopted. `_fill_capacity` drops stale event-fenced intents before ordinary recovery; an already-submitted command is not thereby rejected. Require the deterministic queued-before-claim race test. |
| 8. Pre-existing: separately read and truncated result fields. | Adopted scope clarification. `_ControlQueries.runs_result` caps events/failures. V2 must expose partial failure preview; coherent-read promise covers only status/accounting. This slice fixes no current query implementation. |
| 9. Introduced: reason described as plan-only and extra public reason digest. | Adopted. The canonical request also retains reason text; keep both private. Existing request/plan digests already bind it, so omit a separate reason digest. |

No finding was rejected. The proposal remains Proposed after these changes;
owner acceptance and separate implementation authority remain outstanding.

## Authority and scope

This proposal applies ADRs 0012 and 0016 and invariants I1, I4, I7, I8, I9, and
I13. It does not revise frozen accepted ADRs, any accepted plan, the six run
statuses, the walker scheduler, or the Codex adapter/protocol. Its documentation
PR needs one independent cross-review and the normal exact-head gate. Only an
owner decision can accept it. #132's Stage 3/Stage 4 sequencing remains its own;
this proposal introduces no new Stage 4 prerequisite, host action, vendor
request, credential access, or operator disposal authorization.
