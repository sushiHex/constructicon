# M8 N5 Stage 1: the qualification acquisition

Status: implemented, credential-free, one PR (frozen plan:
M8-N5-state-review.md:95-99).

**Design reviews:**
- v2: Astra (source) and Fable (law);
- v3: Astra;
- v4: Fable recommended the three owner decisions below;
- the implementation: Astra (source) and Fable (law).

**Prerequisites, both merged:** the live loser's custody (#130) and a lost
answer after the lease commit (#131).

## What Stage 1 does

It runs the real acquire, record (the "enroll" of ADR 0021:119), materialize,
cancel, close and reconcile of the codex operator provider, which stays
unavailable throughout and never dispatches. One owner-placed authorization lets
exactly one fixed run do this.

The governing law is the accepted law: rev3:156-157 and ADR 0021. ADR 0020 is
only proposed. Rev3:156-157 reads: "Qualification uses the real
launcher/driver/worker and leases without publishing an unqualified production
provider".

## Owner decisions (2026-10-08)

1. **The authorization** is a root-owned file, `0640 root:<service group>`, in
   a root-owned directory nobody else can write. It is placed for one run with
   `max_epoch` 1. It is operator configuration under ADR 0021:162-165.
2. **The budget is per journal incarnation.** A reset journal restarts the
   epochs within the window. This is accepted for a stage that never
   dispatches. Single consumption across a reset needs a new durable field
   (ADR 0018:314-315), and is a successor decision for the first stage that
   dispatches.
3. **"Clears no unearned reason":** the authorization is the earning act. For
   its one run, admission omits the `executor_unavailable` fault. `describe`
   still publishes every reason, and `available` stays false.

## Design

**The authorization** (L0, `core/qualification.py`) is a closed, frozen model
with predicates only. It pins:
- **the run:** actor, `runs_start` and idempotency key, hence the command and
  run ids;
- **the invocation:** scope and binding alias, hence, with the run, the
  logical lease;
- **the source graph hash;**
- **the provider:** capability id, adapter revision and operator binding
  digest;
- **the dedicated journal path;**
- **bounds:** `max_epoch` and `not_after`.

Its two predicates:
- `admits` is timeless: graph, capability and revision only. Admission must
  never vary with the clock.
- `acquisition_faults` names every way an acquisition differs from the
  authorized one, expiry and epoch included.

**The budget** needs no count and no new state. An epoch is a durable, fenced
claim, and `acquire` refuses any epoch above `max_epoch`. Recovery past the
budget therefore reconciles the old row and records nothing new, and the node
fails; with a checkpoint, it restores instead.

The budget counts ownership claims, not acquisitions. A crash before the first
acquire still spends an epoch, and so does another owner's steal. Either
failure is closed, and needs a new authorization and journal.

**Admission** (`runtime/validator.py`):
- The source graph hash is now computed once, when admission starts.
- At the executor-unavailable site, the optional L0 protocol
  `QualificationAuthorizing` asks the assembled provider whether it authorizes
  this graph for this capability. If it does, only that capability's published
  reasons are omitted.
- An absent or incoherent provider is never cleared, and nothing is deferred.
- **Never under a resolution lock.** A reproduce or counterfactual can keep the
  authored graph while resolving other code (Astra's implementation review).

**The provider** (`substrate/executors/codex.py`):
- An optional verified `qualification` is fixed at assembly. Assembly refuses
  one that names another revision or binding, or has no physical binding.
- `acquire` enforces the run, invocation, graph, provider, epoch and expiry,
  using the run's source graph from its manifest (an in-memory
  `LeaseContext.source_graph_hash`), because recovery runs a stored manifest
  without admission.
- The handle it mints has `dispatch=False`, so `execute` refuses first.
- `close` and `reconcile` never consult the authorization, so cleanup survives
  expiry and a spent budget.
- The journal pin is the entry's, not the provider's. Assembling an authorized
  provider elsewhere is trusted code, not a surface.

**The reader** (`substrate/executors/qualification.py`) is the only source. It
opens every ancestor directory without following a symlink, and requires each
one root-owned and unwritable by group and others (the operator store's own
trusted walk). The leaf must be:
- opened without following a symlink;
- single-linked;
- root-owned, mode 0640;
- bounded in size.

The OS's permission check is what makes it readable through the service's
group. Each check has its own CI variant and mutant, and its refusals disclose
nothing. CI's fixture authorizations are built by tests, never parsed, so no
fixture path exists in `src`.

**The entry** (`api/qualification.py`) is a thin L4 assembler over the fixed
graph: one node `qualify`, one executor binding, no loop, and an explicit
component version. Its body holds the materialized executor and returns,
without ever executing it. The entry:
- refuses an authorization naming any other invocation;
- refuses a journal that holds any run but the authorized one, before recovery
  starts, since the RunHost resumes whatever a journal holds. One
  authorization therefore means one fresh journal;
- assembles a private `Constructicon` over that journal;
- registers and promotes the component idempotently, per version;
- starts the run through `ControlPlane.runs_start`;
- waits for a terminal status, with startup and shutdown inside one
  `try/finally`.

Recovery has one driver, the control plane's own RunHost. A call after a crash
is a fresh owner that replays the same command. An import contract forbids the
MCP adapter from reaching the entry.

**Boundaries, stated rather than solved:**
- **A timeout is a death.** The entry's timeout abandons the run as a death
  does, so no relinquishment fires. A successor in another process waits for
  the abandoned process to exit before reconciling its guard.
- **Two clocks.** Expiry is read from the system clock at `acquire`; leases use
  the journal's clock.
- **The pin covers the node, not the entry.** It covers the node's source (its
  version) and the graph. Edits to the entry itself do not change it, and the
  digest is of checked-out bytes, so the owner mints on the host that runs it.
- **The root grants are the assembler's and unpinned.** That is harmless
  without dispatch; the first dispatching stage must pin them.
- **No production assembly yet.** Stage 1 ships the entry and the reader. The
  host assembly of the production provider arrives with the first host stage;
  until then the Linux twin is the only composition.

## Crash cases

| Case | Behaviour | Proof |
|---|---|---|
| the run completes | the acquisition materializes, the row closes `released`, nothing dispatches | entry test; Linux twin |
| rerun after completion | the same command replays; nothing is acquired | entry test |
| a lost answer after the lease commit | settled against the journal under the fence; the row closes `discarded`; the run fails | entry test (real provider) |
| cancellation mid-materialization | the row closes `discarded`, custody is released, the run is cancelled | entry test (real provider) |
| ownership loss mid-materialization | the loser relinquishes custody and closes nothing; the successor reconciles, then acquires within the budget | entry test (real provider) |
| process death after materialization | the row stays `active` and the handle keeps custody | entry test (`InjectedCrash`); Linux twin (`os._exit` holding the real flock and store lock) |
| successor, `max_epoch` spent | epoch 1 is reconciled after physical quiescence; the next epoch refuses at `acquire`; the run fails with no new row | entry test; Linux twin |
| successor within the budget | epoch 1 is reconciled; the next epoch acquires and succeeds | entry test |
| expiry | admission still admits; `acquire` refuses; cleanup proceeds | entry and provider tests |
| a journal holding another run | refused before recovery starts | entry test |
| a locked (reproduce or counterfactual) admission | never exempt | admission test |
| any other run, invocation, graph, capability or binding | refused before a handle exists | core and provider tests |
| journal reset within the window | epoch 1 is permitted again: no dispatch, no credential, no spend | accepted (decision 2) |

## Proof

**Portable:**
- `tests/core/test_qualification.py`: every predicate, one refusal reason per
  field, and the closed shape.
- `tests/api/test_executor_admission.py`: the authorized graph is admitted,
  every reason is still published, another graph meets the exact reasons, and
  a locked admission is never exempt (the I6 double).
- `tests/substrate/test_codex_qualification.py`: published reasons unchanged;
  assembly coherence; acquisition refusals; no dispatch; cleanup after expiry.
- `tests/api/test_qualification_entry.py`: the real walker and RunHost over the
  real provider. Accept, replay, lease-recording response loss, cancellation,
  ownership loss with joined cleanup, death and both successor outcomes, a
  foreign journal, refusals before any journal, and expiry.

**Linux twin, foundation lane, as `m8-service`.** The service mints the pins;
root installs each authorization and one variant per reader check. With the
real launcher, store, flock guard and closure, and the production reader:
- the accepted run;
- the real process-death recovery;
- the sealed authorization accepted;
- every variant refused.

CI's authorizations are minted by the service and sealed verbatim by root, so
the lane proves the reader's checks, not owner provenance.

**Mutants.** Every one fails an assertion:
- `check_m8_n5_stage1_mutations.py`: one per gate (15).
- `check_m8_n5_stage1_linux_mutations.py`: one per reader check (8).
