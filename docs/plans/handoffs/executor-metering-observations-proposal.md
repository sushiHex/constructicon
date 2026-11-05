# Retain metering observations at the executor dispatch boundary

**Status: proposed; pending explicit owner acceptance.** Refs
[#376](https://github.com/sushiHex/constructicon/issues/376). Source and
fixture observations are against `490562a`. This proposal changes no
implementation or accepted plan. [ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md)
requires a successor decision before adding a durable field.
[ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md),
[I4](../../INVARIANTS.md), and
[ADR 0016](../../adr/0016-positive-durable-facts-and-provenance-eras.md)
continue to govern custody, truthful observations, and durable provenance.

## What the current system can prove

Both adapters return the same optional `Usage` (input and output) in
`ExecutorOutcome`, separate from the requested and served models. Their
counters cover different scopes.

| Route | Existing wire evidence | Current durable retention |
| --- | --- | --- |
| Codex operator | Use the last correlated `thread/tokenUsage/updated` cumulative `total` for the fresh thread and its single turn. Do not add earlier snapshots or `last`. The decoder drops cache and reasoning fields. It treats a synthetic context-window total and an initialized zero as unmeasured; compaction clears usage because a request escapes the total. The last correlated reroute target does not prove which model served all counted requests. | When an authorization supplies a private attempt file, it can retain input/output and the reroute target. The run reader has no sealed locator for that file. The installed M9 selector checkpoints a specific **successful** observation as component output; it cannot supply failed attempts or general run metering. |
| Claude operator | The correlated terminal `usage` has main-loop input/output for the turn; it does not cover every helper request. The cumulative `modelUsage` map is a different scope; do not add it to terminal usage. The decoder accepts optional cache fields, does not publish them, and leaves served model unknown. Thinking progress is separate; `total_cost_usd` is validated as metadata and does not prove a charge. | The private attempt file retains dispatch, status, and callback and custody facts, but no usage or served model. Qualification component outputs also omit usage. |

The journal's lease and checkpoint contracts retain acquisition and node
identity, without a backend dispatch or executor observation. A released
acquisition does not prove a billable call; a failed node does not prove
that no call ran. The private attempt files enforce special operator
authorizations; those files and M9's named output retain their current roles.
The generic reader should neither open a host path nor interpret arbitrary
component outputs as metering evidence.

## Proposed durable seam

Use **one metering event family in the existing journal**, with `intent` and
`outcome` phases. The L4 assembly wires its fenced writer into the existing
single-use Codex and Claude handles; L1 invokes it at the dispatch and
settlement boundaries. Keep the walker, component outputs, and
`ExecutorOutcome` wire contract unchanged. No second ledger, generic provider
protocol, recovery owner, or backend session checkpoint is needed.

- **Identity.** The journal derives `run_id`, the frame-aware execution path,
  binding, revision and acquisition identity from the current `RunLease`,
  canonical retained acquisition, and its sealed manifest. Key one attempt by
  `(run_id, lease_id, acquisition_epoch)`, reusing `acquisition_id_for`.
  These two handles already refuse a second `execute()` on one acquisition.
  Multiple provider requests inside that call remain one attempt with
  source-scoped counters. An adapter that permits several `execute()` calls
  per acquisition is unsupported in this version; supporting it requires a
  reviewed per-dispatch identity that preserves each observation. New
  acquisition epochs and loop frames are distinct.
- **Intent.** After local framing and bounds checks, write the intent just
  before the first native user/task write (`turn/start` for Codex; the
  user record for Claude). It contains an explicit version, the acquisition
  identity, and the versioned usage source bound by trusted assembly to the
  sealed adapter revision. Check the requested model against the effective
  sealed configuration and any explicit model field the route sends. Codex
  sends no model in turn/start. Keep the private authorization and expiry
  checks: Codex's pre-turn callback runs before framing and the byte limit,
  so it cannot be the meter hook. Place the hook after encoding and the
  binding byte check in the actual send path, before the transport write.
  Claude's user-write path already validates framing and bounds before its
  existing callback. Recheck ownership, control and expiry after the fenced
  metering commit and before writing. A supported dispatch requires a
  successful intent commit. A failed transport write or lost reply never
  triggers a second send. An intent without an outcome means **possibly
  dispatched** and proves no usage, even if no request left the process.
- **Outcome.** While the same owner still holds the acquisition, retain at
  most one outcome after the adapter's existing correlation and cleanup
  checks, before handing the outcome back to the node or settling the lease.
  Record only bounded typed facts: observation scope, dispatch and executor
  result classification, observed served model, observed counters, and
  coverage. Preserve a trustworthy partial observation only if the owned
  adapter has handed it across subsequent control and cleanup boundaries and
  the fence still permits publication. A successful decoder return does not
  guarantee the outer handle can see it: Claude can fail a subsequent control
  or custody check before returning usage. Without that explicit handoff,
  classify the observation as unavailable. Loss of custody or a process
  death may leave intent alone.
  Omit raw replies, terminal frames, private provider ids, prompts, host
  paths, credentials and free-form errors. A metering outcome confers no
  completion, permission, or billing authority.
- **Retention and replay.** Co-commit the normal sealed event and a relation
  seal in the same transaction. The relation key is the exact event position;
  its independent selector is the canonical `[run_id, acquisition_id, phase]`.
  Bind the exact event hash, acquisition and manifest relationship, and (for
  outcome) the exact prior intent position. Generic `append_event` cannot
  mint the reserved kind. Replay of identical facts returns the original
  position; a conflicting or misplaced fact fails closed. Replaying a
  metering write never returns permission to dispatch. Point and run reads
  share the canonical verifier; range reads compare both directions of the
  scoped event/relation inventory. Missing, relocated or replaced evidence
  is journal damage.
- **Era.** A reviewed migration positively seals an unmeasured legacy era
  for every existing run; creation co-commits a current era seal thereafter.
  All pre-migration RunIds, including resumed runs, remain unmeasured in
  this projection. No attempt files, historical component outputs, or
  transcript fragments are imported. Existing result decoders stay exact.
  A new run on an unsupported route is also unmeasured. Absence of an event
  in the supported slice proves nothing about dispatch outside the slice.

## First product milestone

Publish a new explicit `runs_result` version through the existing
ControlPlane and detail surface. Take metering and status at the same
journal event cut as capability accounting. Return at most the two
supported usage-scope groups in the summary. Each shows the counts of
intent-only, unavailable, partial and fully observed attempts, plus a
**known subtotal** per reported token axis with trustworthy partial
observations included. An axis
with no measured contributor is null. Do not
sum Codex fresh-thread totals with Claude main-loop counts. Mark coverage
as limited to the supported observations; these totals do not claim to
include every model request made for the run.

Use a detail reference pinned to the run and event cut for attempt rows
in intent-event order. Include the acquisition identity, source, requested
and observed model, counter scope, coverage, and canonical event sequence
and digest as evidence. Keep detail reads bounded and chunked; verify the
reference against the same immutable cut, not the current run head. A
later outcome can change a new result, never the older detail. Authorization
stays in ControlPlane and the existing detail read path.

| Example | Attempt and run interpretation |
| --- | --- |
| Success | A Codex fixture updates cumulative counts from 5/1 to 11/3. The detail shows input 11 and output 3, with the reroute target separate from the requested model. The known subtotal is 11/3, with coverage of the source and both monetary fields null. |
| Partial | A Claude fixture observes main-loop input 17 and output 23 before a post-result failure. If retained under the same owner, report 17/23 and partial coverage; the different cumulative model map contributes nothing. Served model and money remain null. |
| Unavailable | Ownership is lost after intent, with no correlated outcome. Show a possibly dispatched attempt, with null counters and money. Legacy runs show unmeasured coverage, without inventing an attempt or token count. |

A replayed read, command response, or checkpoint adds no observations.
A fresh call after recovery can legitimately add spend under a new
acquisition. Simulated executor evidence cannot enter actual totals.
Counterfactual effects and discard-on-close do not make a real model
call simulated: report actual observed calls only in their own run, never
in the source run. Derive actual or simulated origin from the trusted assembly and sealed
adapter relation; do not trust a caller label or infer it from run mode.
Missing or contradictory origin cannot enter actual totals.

## Monetary boundary

The first product milestone can expose usage with **both monetary values
unknown**. Keep separately named estimate and confirmed-charge fields,
each with independent coverage. Native cost metadata, mode observations
and subscription accounting do not supply either amount by themselves.
A future estimate needs an exact applicable served model for the measured
units, an immutable rate version and currency, complete disjoint pricing
units, and deterministic arithmetic. An attributable charge needs
authoritative provider evidence explicitly bound to the attempt and currency;
it does not follow from an estimate or a subscription's monthly price.

For a synthetic arithmetic check only: a fixture with 100 input tokens
including 20 cached, 50 output tokens including 12 reasoning, and pinned
rates of 2, 1 and 4 micro-USD per uncached input, cached input and output
token has a 380 micro-USD estimate (80 × 2 + 20 × 1 + 50 × 4). Do not add
the 12 reasoning tokens again. This fixture asserts its own unit semantics;
neither adapter's current publication proves those inputs for pricing.
Missing cache attribution in that fixture prevents the estimate. Actual
estimates and confirmed charges, when a producer is supported, are separate
currency-specific subtotals; unknown amounts never become zero.

## Review and implementation evidence

The [Codex wire and fold fixtures](../../../tests/substrate/test_codex_protocol.py)
exercise successive totals, reroutes, synthetic zeros and compaction. The
[Claude wire fixtures](../../../tests/substrate/test_claude_read.py) use 17/23
terminal counters alongside 1700/2300 cumulative model counts and verify
that later refusal preserves only the former. Missing or uncorrelated terminal
records publish no usage. A local two-case probe drove both qualification
runs with those counts through their real graph, journal and result query,
using the existing portable process and guard fixtures. Both runs succeeded:
Codex retained 11/3 and the reroute target in its private attempt file;
Claude returned 17/23 from its handle but retained neither usage nor served
model in that file. Both generic results were still schema 2, with no meter.
These are credential-free scripted peers, not native account traffic.

The eventual implementation
must exercise both adapters through the result path, including the three
examples above, pagination with a binding limit, and same-world runs with
different RunIds. Exercise Codex framing and the input bound before intent,
a failed intent write with no dispatch, and Claude's post-observation
control and custody failure with an explicit partial or unavailable verdict.
Inject death before and after intent commit, during native
write, after outcome commit before response, and before checkpoint. Verify
a replayed result leaves the same subtotal, a real re-execution adds only
its new attempt, stale ownership cannot publish, and moved or removed
phase/era evidence fails closed. Open a migrated journal and an unchanged
old result fixture without manufacturing counts. Prove actual counterfactual
dispatch and purely simulated evidence cannot be confused. Those are future
acceptance tests, not behavior delivered by this proposal.
