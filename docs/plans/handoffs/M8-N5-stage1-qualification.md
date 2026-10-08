# M8 N5 Stage 1: the qualification acquisition

Status: implemented, credential-free, one PR (frozen plan:
M8-N5-state-review.md:95-99).

**Design reviews:**
- v2: Astra (source) and Fable (law);
- v3: Astra;
- v4: Fable recommended the three owner decisions below.

**Prerequisites, both merged:** the live loser's custody (#130) and a lost
answer after the lease commit (#131).

## What Stage 1 does

It runs the real acquire, record, materialize, close and reconcile of the codex
operator provider, which stays unavailable throughout and never dispatches. One
owner-placed authorization lets exactly one fixed run do this.

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
claim, and each acquisition of the pinned lease is at one. `acquire` refuses
any epoch above `max_epoch`. So recovery past the budget reconciles the old
row, records nothing new, and the node fails. With a checkpoint, it restores
instead.

**Admission** (`runtime/validator.py`):
- The source graph hash is now computed once, when admission starts, rather
  than after the faults.
- At the executor-unavailable site, the optional L0 protocol
  `QualificationAuthorizing` asks the assembled provider whether it authorizes
  this graph for this capability. If it does, only that capability's published
  reasons are omitted.
- An absent or incoherent provider is never cleared, and nothing is deferred.

**The provider** (`substrate/executors/codex.py`):
- An optional verified `qualification` is fixed at assembly. Assembly refuses
  one that names another revision or binding, or has no physical binding.
- `acquire` enforces the whole authorization itself, using the run's source
  graph from the manifest (an in-memory `LeaseContext.source_graph_hash`),
  because recovery runs a stored manifest without admission.
- The handle it mints has `dispatch=False`, so `execute` refuses first.
- `close` and `reconcile` never consult the authorization, so cleanup
  survives expiry and a spent budget.

**The reader** (`substrate/executors/qualification.py`) is the only source. It
requires:
- a regular file, single-linked;
- owned by root and by the reader's group, mode 0640;
- in a root-owned directory that group and others cannot write;
- opened without following symlinks;
- bounded in size.

Its refusals disclose nothing. CI's fixture authorizations are built by tests,
never parsed, so no fixture path exists in `src`.

**The entry** (`api/qualification.py`) is a thin L4 assembler over the fixed
graph: one node `qualify`, one executor binding, no loop, and an explicit
component version. Its body holds the materialized executor and returns,
without ever executing it. The entry:
- refuses an authorization naming any other invocation;
- assembles a private `Constructicon` over the pinned journal;
- registers and promotes the component idempotently, per version;
- starts the run through `ControlPlane.runs_start`;
- waits for a terminal status.

Recovery has one driver, the control plane's own RunHost. A call after a crash
is a fresh owner that replays the same command. An import contract forbids the
MCP adapter from reaching the entry.

## Crash cases

| Case | Behaviour | Proof |
|---|---|---|
| the run completes | the acquisition materializes, the row closes `released`, nothing dispatches | entry test; Linux twin |
| rerun after completion | the same command replays; nothing is acquired | entry test |
| process death after materialization | the row stays `active` and the handle keeps custody | entry test (`InjectedCrash`); Linux twin (`os._exit` holding the real flock and store lock) |
| successor, `max_epoch` spent | epoch 1 is reconciled after physical quiescence; epoch 2 refuses at `acquire`; the run fails with no new row | entry test; Linux twin |
| successor within the budget | epoch 1 is reconciled; epoch 2 acquires and succeeds | entry test |
| a live loser | relinquishes its custody (#130) | #130's tests |
| a lost answer after the lease commit | settled against the journal under the fence (#131) | #131's tests |
| expiry | admission still admits; `acquire` refuses; cleanup proceeds | entry and provider tests |
| any other run, invocation, graph, capability or binding | refused before a handle exists | core and provider tests |
| journal reset within the window | epoch 1 is permitted again: no dispatch, no credential, no spend | accepted (decision 2) |

## Proof

**Portable:**
- `tests/core/test_qualification.py`: every predicate, one refusal reason per
  field, and the closed shape.
- `tests/api/test_executor_admission.py`: the authorized graph is admitted,
  every reason is still published, and another graph meets the exact reasons
  (the I6 double).
- `tests/substrate/test_codex_qualification.py`: published reasons unchanged;
  assembly coherence; acquisition refusals; no dispatch; cleanup after expiry.
- `tests/api/test_qualification_entry.py`: the real walker and RunHost over the
  real provider. Accept, replay, death and both successor outcomes, refusals
  before any journal, and expiry.

**Linux twin, foundation lane, as `m8-service`.** The service mints the pins,
and root installs each authorization. With the real launcher, store, flock
guard and closure, and the production reader:
- the accepted run;
- the real process-death recovery;
- one root-prepared variant per reader check (owner, mode, parent), plus a
  symlink.

**Mutants.** Every one fails an assertion:
- `check_m8_n5_stage1_mutations.py`: one per gate (13).
- `check_m8_n5_stage1_linux_mutations.py`: one per reader check (4).
