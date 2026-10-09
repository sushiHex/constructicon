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
journal has no current worker owner. It proves no physical quiescence.

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

The immutable typed domain plan seals the actor/command/request identities,
run id and manifest identity, expected RUNNING status, NULL owner and owner
epoch, latest event sequence, canonical reason, and every exact named row's
identity, immutable acquisition fields, expected lifecycle, update time, and
validated acquisition/lifecycle provenance. A hash of that complete validated
baseline binds each row; it is not a hash of the selector alone. The existing
public `RunHead` omits owner epoch and lease inventory, so it is insufficient
as this plan's snapshot: add an operation-specific L0 snapshot on the existing
co-located store, with a genuine transactional test double. This is not a new
lease manager or store interface.

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
   baseline hashes, exact transition sequences, and reason digest. The reason
   text stays in the sealed command plan. This
   event is the immutable domain receipt, not an `EffectReceipt`: no external
   effect was performed.
4. Co-seals one `capability_disposal` command/event relationship over the exact
   command claim, typed plan, audit event, and ordered transitions.

Use the existing journal transaction, event insertion, and positive-seal
machinery. Administrative event-sequence allocation must compare the planned
NULL-owner/status/epoch/event fence in that transaction; it must not construct
a fictional `RunLease` or call a worker writer with invented ownership. The
reason digest and command attribution live in the typed audit receipt, and the
reason text in the plan, never as extra fields on the existing canonical
`LeaseTransition` payload. Current worker writers must refuse minting `lost`
or reactivating a lost acquisition; an existing historical transition retains
its original interpretation. Disposal does not change a closed row.

A worker claim and disposal serialize against the same runs row. If the worker
claims first, disposal changes no row and returns the durable refusal below.
If disposal commits first, a later worker claim observes its new events and
ordinarily advances the epoch; recovery skips the lost rows. An old explicit resume plan is
superseded by the new event fence; a subsequent resume uses a fresh key.
No check before a transaction or process-local lock can substitute for this
comparison. Another administrator's overlapping disposal similarly causes
one transaction to refuse; batches never partially apply.

The relationship family has primary key `command_id` and secondary selector
`(run_id, audit_event_seq)`. Its one canonical projector independently validates
the ADMIN claim, typed plan, exact audit event, each contiguous preceding
transition in canonical pair order, each acquisition's existing provenance,
and the final lost/None lifecycle. Both command and event point reads, retries,
and bounded inventory reads use that projector. Bidirectional open inventory
requires each new audit event to have exactly one relationship, and each
relationship to own exactly one audit event and the complete planned batch.
A deleted event/row with retained proof is damage, not absence or permission to
dispose again. A command owning that receipt cannot become rejected.

Version the persistence extension rather than silently admitting a new fact
family into schema 7. If no intervening change advances it, use migration 7→8;
old journals acquire an empty current disposal family, with no inferred
historical disposal attribution. Existing lease events, legacy seals, plans,
responses, and manifests retain their bytes. An old lost row remains an
opaque lost fact without an invented operator reason or receipt.

### Command law, refusal, and replay

The command follows `authorize → claim → plan → apply once → record → replay`.
Invalid pre-domain requests retain the complete typed refusal in the existing
rejection-plan family. Once a domain plan exists, fence supersession has one
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
`schema_version=2`, as the new `runs_result` response. It retains the existing
run/status/outputs/failures/detail fields and adds a required typed capability
accounting summary: exact `active_count`, exact `lost_count`, `through_event_seq`,
and an accounting detail reference. Any positive lost count is rendered as
"capability cleanup abandoned; physical cleanup unverified", including when
the run status is SUCCEEDED. Counts describe validated durable rows, never
provider success. The summary contains no inferred disposal actor/reason for
legacy lost facts and no claim of physical clearance when both counts are zero.

Derive status and accounting through one coherent read snapshot; count all
validated rows rather than a truncated preview. Full identities and disposal
receipt links are in bounded/chunked detail pinned to that event cut, including
on a RUNNING run. A new accounting-detail URI family is needed: the present
terminal-only result reference cannot supply it. It reconstructs lease state
at the pinned cut from exact current event history or legacy initial seals and
validates disposal relationships; it never reads mutable current rows as the
state of an older cut. Public detail authorization is the existing run-read
scope. Keep the free-text reason and actor's private command detail behind the
existing command actor-or-ADMIN authorization; public audit events and
accounting detail expose the disposal event id and reason digest, not a copy
of private reason text or the actor's private command record. Event
summary/detail reads therefore need no weaker or special authorization path.

The absence of a schema version denotes exactly the old result shape when
decoding retained legacy fixtures; its accounting is unknown, never fabricated
as zero. Current writers emit version 2 only. Do not silently add fields to the
unversioned old preview or weaken `extra=forbid` in old clients: they must refuse
and upgrade for new result responses. Other existing control schema-3 responses
keep their wire shapes; this result family's version does not allocate a new
global control schema. Existing terminal result detail bytes/digests remain
unchanged; the accounting reference is separate. Historical command responses
are not rewritten, and missing current disposal proof never selects a legacy
fallback. Publish the new response and tool schema through the existing typed
control/MCP vocabulary; no Graph or manifest schema change is required.

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

- A genuine co-located store double and SQLite admit exact ADMIN disposal and
  refuse OPERATE, non-NULL ownership (live and expired), wrong run/epoch,
  duplicate/oversized/noncanonical input, and mixed active/nonactive batches.
- All three crash seams in the table, including real process restart over a
  durable fake world, prove one receipt, an unchanged owner epoch, exact transitions,
  and unchanged canonical success/refusal responses.
- Deterministic worker claim, heartbeat, resume-plan, and overlapping disposal
  races prove the accepting and superseded paths and no partially applied batch.
- Exact event/relationship/plan/row deletion, relocation, valid-to-valid rewrite,
  receipt omission, and false legacy classification fail closed on point,
  batch, retry, query, and open inventory paths. Schema-7 fixture migration
  preserves bytes and never invents old disposal provenance.
- Providers are instrumented: disposal and replay call neither `close` nor
  `reconcile`, and neither remove physical guards nor unlock/reuse stores.
  A retained guard must still refuse a fresh acquisition after accounting loss.
- Lost rows versus unnamed active rows, recorded cancellation, checkpointed
  outputs, and fresh uncheckpointed acquisition exercise the next-attempt
  outcomes. The #132 terminal guard remains binding until no active rows remain.
- Every published field has an invariant bound; inputs at those bounds make
  them bind. Result summary/detail cuts stay coherent across later disposal,
  recovery, and resumed attempts. Current/legacy result readers, legacy opaque
  lost facts, event/command/detail authorization, and MCP's single delegation
  receive explicit compatibility and secret-free accepting-path tests.

## Authority and scope

This proposal applies ADRs 0012 and 0016 and invariants I1, I4, I7, I8, I9, and
I13. It does not revise frozen accepted ADRs, any accepted plan, the six run
statuses, the walker scheduler, or the Codex adapter/protocol. Its documentation
PR needs one independent cross-review and the normal exact-head gate. Only an
owner decision can accept it. #132's Stage 3/Stage 4 sequencing remains its own;
this proposal introduces no new Stage 4 prerequisite, host action, vendor
request, credential access, or operator disposal authorization.
