# ADR 0022 disposal command: state and proof review

Draft design review for the future disposal command, under accepted
[ADR 0022](../../adr/0022-operator-disposal-records-abandoned-capabilities.md)
and the owner's 2026-10-13 approval of the complete disposal wave.
Initially inspected `implement/adr22-disposal-command` at `2c454b7`, 2026-10-13.
Implementation preparation now uses the concrete accounting interface at
`4730981` in this isolated stack, authorized by root on 2026-10-13.
This draft contains source-grounded design requirements, not executed command,
migration, privacy or physical-cleanup evidence. Root read the complete review
and approved this design on 2026-10-13, subject to the parent merges and actual
merged accounting snapshot interface integration. Root also approved the
historical-versus-disposed closure distinction recorded below.

The provenance PR 180 and then the accounting result/detail PR must merge
before this slice is published or merged. Root approved preparing source and
tests against the concrete `4730981` accounting interface in the isolated
stack. Waiting for parent merges before implementation was an earlier staging
choice, not an ADR requirement. This review changes no accepted ADR or frozen
plan. GitHub Issues remains the work tracker; this document is a state review,
not a backlog. Executed implementation evidence belongs in the living record.

## Smallest implementation boundary and proven reuse

One new mutation uses the existing command ledger and the exact assembled
SQLite journal. Add strict frozen L0 request, selected-row snapshot, domain
plan, public receipt/audit and bounded response values. Extend the existing
`ControlPlaneStore`; do not create a command engine, lease manager, journal
protocol or memory journal. Reuse the merged accounting history reconstruction
and public detail projection rather than introducing another accounting law.

| Existing source seam at the inspected head | Reuse or necessary extension |
| --- | --- |
| `api/control.py`: `_admit_mutation`, `_release_mutation` | ADMIN authorization before startup; existing lifecycle admission and synchronous `finally` release. |
| `api/_control_commands.py`: `_begin_command`, `_CommandSession` | Claim/replay/conflict, one immutable typed plan, stored observational rejection, completion and crash probes. Strict disposal request validation precedes claiming. |
| `api/_control_commands.py`: stored-plan operation dispatch and terminal validators | Register one L0 disposal plan; validate success against its receipt and post-plan refusal against immutable plan facts. |
| `substrate/journal/_sqlite_control.py`: `store_approval_exchange`, `_command_fenced` | Co-located transaction precedent and exact prepared-command owner/epoch fence. The store revalidates the sealed ADMIN actor and command/plan/request binding. |
| `substrate/journal/_sqlite_control.py`: `_terminal_command`, `_domain_fact_owned_by` | Positive terminal seal and substrate-level prohibition on rejecting a command that owns disposal evidence. Check both plan-derived and redundant relationship identities. |
| `substrate/journal/_sqlite_execution_facts.py`: sealed base events, relationship projection and inventory | Compose one disposal relationship projector above the existing fact-seal primitives; preserve exact event bytes and bidirectional coverage. |
| `substrate/journal/_sqlite_execution.py`: exact pair selection and `_validate_capability_lease_history` | One acquisition/lifecycle law, cross-run identity checks, full baseline reconstruction and canonical `LeaseTransition` payloads. |
| `substrate/journal/_sqlite_capability_provenance.py`: histories, eras and old-lost witnesses | Preserve positive per-run floors and commitments; classify historical loss independently of administrative loss. |

These are inspected implementation seams, not proof that the proposed command
already works. The current worker writer refuses new `lost` and lost-to-active
transitions; administrative disposal must not call that worker writer with an
invented lease.

## Exact admission and one coherent baseline

Derive actors in transports. Positively prove ADMIN before lifecycle startup
or command claiming; OPERATE, including the submitting actor, does not suffice.
Validate a nonempty batch of at most 100 exact pairs, duplicate refusal,
canonical pair ordering, Unicode scalar identities up to 200 characters,
exact positive epochs, and the bounded canonical reason required by the ADR.
Canonical ordering is part of request hashing; do not trim or repair input.

For an unplanned claimed command, read the run and every selected pair from
one connection-owned snapshot. Admit RUNNING, NULL owner, and active/None rows
belonging to that run. Refuse non-NULL ownership even when expired. Collect
complete bounded pair diagnostics and explicit run-level faults; one bad pair
refuses the whole batch. Already-disposed diagnostics contain only a validated
public receipt reference. Retained proof without its row is damage, not a
missing selector or permission to dispose again.

The plan binds immutable command/actor/request facts, run and manifest/world
identity, status, NULL owner and expiry, owner epoch, event cut, private reason,
and each exact row's immutable acquisition facts, lifecycle, update time and
validated provenance. Row hashes bind the complete baseline, not just pairs.
The public `RunHead` lacks owner epoch and acquisition inventory. Use an
operation-specific L0 snapshot on the existing co-located store, sharing the
merged accounting validators through a caller-owned SQLite connection.

Application rechecks the command fence, ADMIN proof, plan/request binding and
complete run/row baseline inside one write transaction. Allocate the batch's
event sequences against the planned NULL-owner/status/epoch/event fence.
Commit all lost/None rows, their canonical transitions, the public audit and
private relationship together. Owner epoch is unchanged by disposal; only a
real worker claim advances it. Status, cancellation, outputs, checkpoints,
manifest and effect receipts are unchanged. A transaction contains no await,
provider operation or separate worker claim.

## State at awaits, transactions and crash boundaries

| Boundary | State that may exist when execution resumes | Required action or interruption result |
| --- | --- | --- |
| MCP actor await | Run ownership, events and rows may already have changed. | Derive the verified actor and delegate once; trust no caller identity or pre-await run observation. |
| Lifecycle startup/admission awaits | Startup can start ordinary recovery; shutdown can begin. No command need exist yet. | Authorize ADMIN before startup. Take the admission snapshot afterward. A closed control plane refuses through the existing lifecycle law. |
| Claim transaction | An equal key may be live, terminal, or reclaimable with a higher command epoch. | Reuse exact request conflict/replay/in-progress behavior. Malformed input creates no command. |
| Admission snapshot to plan commit | Another worker or administrator may change the run after the snapshot. | Seal that exact baseline once; never silently refresh it. Application compares again atomically. |
| After plan commit, before application | Command remains prepared; worker claim, closure or another disposal may have won. | Reclaim and load the same plan; resolve its own validated receipt first, then apply or prove supersession. |
| Application lock and statements | Another connection can win before the lock; batch rows/events remain private before commit. | Compare all fences under the write lock. Any error rolls the whole batch back. Validate the completed relationship before commit. |
| After failed domain comparison, before rejection | No batch was applied by this attempt; command is still prepared and may later be reclaimed. | Receipt-first retry, then re-prove monotone supersession and record the same plan-derived refusal. Do not retain mutable diagnostics as the canonical refusal. |
| After domain commit, before command completion | Lost rows, transitions, audit and relationship exist; command can still be prepared under its old claim. | A new command claim resolves the receipt and completes identical success without another transition or provider call. Historical proof does not compare current command ownership to the application claim. |
| After completion, before delivery | Stored response and terminal seal exist; delivery may fail or the caller may cancel. | Replay the validated stored response; only existing replay metadata changes. No domain mutation. |
| Public reference mint or later detail chunk | Recovery, cancellation, terminalization and newer acquisitions can commit. | Use the immutable accounting cut and public receipt bytes. Reconstruct historical lifecycle; never reinterpret current rows as old-cut state. |
| Shutdown/cancellation of the caller | Cancellation can arrive around synchronous calls; shutdown waits for admitted mutations. | Preserve the existing synchronous mutation-counter release. A committed domain fact remains replayable even if completion/delivery did not occur. |

Do not add an await between the authoritative comparisons and writes. SQLite
interleavings still require real two-connection tests even when an executor
method contains no await. A successful domain commit is not necessarily a
success response delivered to the caller.

## Canonical refusal and receipt-first recovery

Observational pre-plan refusals retain their complete typed response in the
existing rejection-plan family. Post-plan supersession has one immutable
plan-derived refusal, with fresh-key repair guidance. A real worker claim
advances owner epoch; domain changes advance event sequence. Release reverses
neither. Later idleness cannot restore that plan's baseline or change refusal
wording. Command ownership loss and journal damage are separate failures, not
evidence of domain supersession.

Every retry and rejection path resolves the command's validated receipt first.
Matching lost rows do not establish command ownership of disposal. A command
with its own committed receipt can never become rejected, including through
direct substrate rejection. Terminal success remains valid after later lawful
run status/ownership changes. A fresh key naming closed or lost pairs refuses;
same-key success replays without requiring those pairs still to be active.

## One non-recursive proof dependency order

The dependency direction is sealed primary facts -> exact structural histories
-> disposal relationships -> lost attribution -> complete inventories/public
projections. It is not lease projection -> receipt projection -> lease projection.

1. Project sealed command identity/request/plan, run world/extent and exact event
   bytes with the existing canonical fact primitives. A base fact is internally
   validated data, not a public disposal receipt or permission to skip proof.
2. Construct exact acquisition/lifecycle histories once with the shared row
   decoding and chain law. Validate acquisition events or legacy seals, event
   identity across runs, update times and the era-floor inventory commitment.
   Preserve all history, including legitimate pre-v8 lost transitions.
3. The single disposal projector consumes those facts and histories. Independently
   bind ADMIN command/plan/request, complete reason-bearing private contents,
   public audit bytes, canonical contiguous transitions and reconstructed
   pre-disposal baselines. Require complete planned membership and final
   receipt-backed lost/None lifecycle. Historical pre-v8 losses in a prefix keep
   their exact migration witnesses. Compare immutable application facts, not
   current mutable command ownership or current run fence equality.
4. The attributed lease/event projector requires each lost transition to belong
   to exactly one validated disposal receipt or one valid pre-v8 witness, in
   disjoint eras. Initial legacy loss requires its own witness. No absence-based
   historical fallback exists. Surviving lost transitions still refuse after
   both audit and relationship are deleted.
5. Validate audit-to-relationship, relationship-to-complete-batch and reverse
   event-to-row inventories. All public point/batch/detail reads, private command
   reads, retries and open use these composed canonical projectors.

Factor the structural constructor rather than adding `trusted`, `skip_receipt`
or recursion-guard parameters. Receipt internals consume sealed command/event
facts, not fully relationship-validating point readers that call them back.
The existing migration distinction is not a current-read bypass. Public current
entry points always compose attribution. Co-transactional insertion first
writes and seals primary facts, then co-seals the relationship and performs
full projection; no premature audit renderer may require a relationship before
it has been inserted. This is one fact law with dependency layers, not a second
accepting projector. Invalid later changes to receipt-backed lifecycle must
fail before a worker transaction commits.

Preserve the existing permitting path for witnessed historical lost-to-closed
transitions under current worker authority. Historical loss remains opaque;
later proved closure must not be refused merely because an old loss occurred.
A receipt-backed disposed pair, however, must refuse worker closure before
commit because its immutable receipt requires final lost/None. Test both the
historical accepting path and the administrative refusal, with unchanged rows,
events and receipt after refusal. The global lost-to-active guard stays.
Canonical exact-at-target retries remain observations, not new mutations:
the pre-existing worker writer validates the pair/history before returning
without checking current worker ownership. New transitions still pass the
actual owner/epoch fence before any write. Do not describe an exact no-op as
affirmative proof that its caller currently owns the run.

## Public bytes, physical limits and required accepting proofs

Public audit, receipt and accounting records contain exact event/receipt
identities, pairs, acquisition-baseline hashes and truthful abandoned-cleanup
meaning. They contain neither reason text nor any request/plan/private-proof
digest derived from reason. Public references hash only canonical public bytes.
Private request, plan and relationship bindings remain behind command
actor-or-ADMIN authority. Generic event and command/detail renderers must not
forward private relationship payloads onto run-readable surfaces.

Acceptance must recursively walk READ-only result summary, accounting chunks,
event summaries/pages, direct event detail, public receipt references and
already-disposed refusal references. Fixtures with identical public facts and
different private reasons must produce identical public bytes/reference hashes;
their private bindings differ, validate exact replay and refuse tampering.
Bounds need binding inputs: 100-pair command batches, maximum reason bytes,
large full run inventories, tiny Unicode chunks and failure-preview truncation.
The command request bound never caps whole-run accounting counts.

Instrument providers and actual physical guards: disposal and replay call no
`acquire`, `close`, `reconcile`, `execute`, `simulate` or physical maintenance
operation, remove no guard, and unlock/reuse no store. Keep
`physical_cleanup="unverified"`. A retained guard must still refuse a fresh
acquisition. Recorded cancellation, matching checkpoints, uncheckpointed work
and unnamed active rows exercise subsequent attempts; the terminal guard still
binds until no active obligations remain. These are future proofs, not claims
that NULL ownership establishes physical quiescence.

Disposal does not schedule or clear RunHost deferral. Test a failed host's
deferred run remaining idle after disposal, a fresh explicit resume clearing
deferral, and a restarted host recovering ordinarily. Test a queued resume
before worker claim becoming stale at the disposal event fence: the pump drops
that intent without rewriting its submitted command as rejected. Preserve the
existing shutdown-abandons-without-user-cancellation behavior.

## Persistence version after the sequential provenance release

ADR 0022 says to version the extension and to use 7->8 only if no intervening
change advances persistence. Provenance-only schema 8 is the intervening
publication. Disposal therefore adds schema 9, with 8->9 migration, rather than
broadening released schema 8's closed fact-family inventory silently.

Under one migration write lock, recheck version, validate the exact released
schema-8 inventory through its canonical laws, and affirmatively reject any
disposal audit/relationship facts in that pre-disposal baseline. Add only the
necessary disposal persistence structure, validate an empty disposal inventory
and commit version 9 atomically. A crash before commit leaves exact version 8;
a crash after commit leaves coherent version 9. Current open validates and
never repairs. The released v8 reader refuses v9 before its pragma writes.

Preserve every existing era, floor, inventory commitment and historical witness
byte. Do not remint pre-v8 witnesses, reset floors or label retained runs newly
migrated. The accepted ADR explicitly assigns new creation the source
`schema8-creation`; that name identifies the creation proof introduced in 8,
not an assertion that the current database version is 8. Keep the exact source
for actual new creation in 9 with floor zero and canonical empty inventory,
co-committed with the run. No new source value or accepted-ADR edit is needed.

Schema-8 fixtures made by the released writer must exercise valid migration,
both migration crash seams, zero-disposal baseline violations, preserved era
bytes and v8 refusal of v9. Command/receipt deletion, relocation, valid-to-valid
rewrite and missing-proof tests must attack every point, batch, retry, public
accounting and open path. Assertion-only mutation evidence and the exact-head
gate remain required after implementation; this draft supplies neither.
