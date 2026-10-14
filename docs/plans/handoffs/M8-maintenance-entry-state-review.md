# M8 maintenance entry: one authorized application attempt

This is the operational successor to the
[data-only maintenance design](M8-maintenance-workflow-state-review.md), tracked
in [#186](https://github.com/sushiHex/constructicon/issues/186). The owner
approved the narrow `codex.py` exception on 2026-10-14 after the source audit
and Fable advisory recorded on that issue. This document specifies the
implementation and proof obligations; it does not claim they have run.

## Decision and limits

A maintenance attempt is not N5 qualification. Give it a distinct closed
authorization, and reuse the existing exact-run admission/acquisition checks
and exclusive attempt record. Do not add a scheduler, durable attempt ledger,
provider-promotion mechanism or caller-selected task/exam.

The authorized adapter change admits that separately named authorization,
checks its exact provider and binding, enforces its acquisition and expiry
predicates, and identifies its attempt as maintenance. Published unavailable
reasons remain unchanged. The exception is for the authorized graph and run,
not a declaration of general production availability. Reproduce and
counterfactual resolution locks do not gain an availability exception.

Preserve `codex_protocol.py`, historical N5 entrypoints, existing qualification
wire shapes and accepted plan bytes. Native model/effort, callback catalog,
configuration, store/egress custody, execution limits and cleanup do not change.
New adapter bytes nevertheless change its revision. Deployment must install
the reviewed revision and obtain fresh qualification; historical g8 acceptance
does not qualify it.

## One sealed application

The authorization binds the exact maintenance graph and request, source/base,
workspace and gate revisions, executor revision and operator binding, grants,
actor and idempotency key (hence run), writer scope/binding, dedicated journal,
attempt-record path, one epoch and expiry. The installed root-owned record is
operator configuration, not a caller-authored capability. A printed preflight
record is a proposal for installation, never evidence of that installation.

The command assembles the existing `maintenance_system`, Graph, workspace,
capture and contained gate. Repository state comes from a reviewed pinned base
in a dedicated private authority, not from a mutable model-written checkout.
The fixed input-only JSON path, reference, renderer and eight-mutant exam stay
those of the merged application. The worker receives no push, installation,
promotion or merge capability.

Preparation and execution assume the existing single-operator host custody:
another trusted process under the service identity must not rewrite the
authority while the session runs. Metadata aliases are refused before writing
constructors; this is not a new isolation boundary between mutually hostile
processes sharing that same service identity.

Preflight identifies actual resources without a vendor turn. Execution uses
ControlPlane registration and `runs_start`, with its existing RunHost as the
only process-local recovery owner. Inspection observes retained evidence only:
it does not start recovery, launch runtime probes, construct a writing Git
authority or dispatch a model. Historical recorded success must be labeled as
such rather than claimed as current qualification.

## State when control resumes

| Boundary | Required positive fact and failure behavior |
| --- | --- |
| Before startup | Validate the dedicated journal and any retained run's exact graph, inputs and descriptors before RunHost can recover it. A matching run id alone is insufficient. |
| Assembly probes | Runtime, base or provider state may have changed while awaiting identification. Recheck actual pins before publishing preflight or starting recovery. |
| Admission | Only this exact graph/provider is excepted; default unavailability and all other authority checks remain. |
| Acquisition | Check run/path/binding/grants/epoch/expiry before reserving the existing exclusive attempt record and exposing a handle. Journal reset cannot restore its budget. |
| Materialization | Use existing enrollment, custody checks and joined teardown; local cancellation cannot close a successor's authority. |
| Dispatch | Durable intent precedes the write. An `acquired` record alone does not prove no dispatch; absent or incomplete evidence remains uncertain and cannot authorize retry. |
| Capture | Only positive executor success advances; publication and response can be separated by death. Existing closure fencing and capture identity checks remain authoritative. |
| Writer checkpoint | A durable checkpoint restores its candidate without another turn. Without it, a spent attempt refuses redispatch even if that prevents completion. |
| Gate checkpoint | Restore or finish the existing candidate check under the normal walker. A successful generic tree gate is not yet application acceptance. |
| Publication | Join shutdown, then derive the exact journal/manifest/attestation/one-file/sole-parent acceptance proof. Failed publication does not turn the model attempt into unused budget. |
| Inspection | Report only retained bounded facts. Never use an empty fault collection, missing record or absent output as proof of success or non-dispatch. |

The native exchange/callback deadline remains 300 seconds, with the existing
callback and byte limits. Capture and gate phases retain their separately
defined limits; these do not create an overall cleanup wall-clock bound.
Tokens are observational, backend request count is unknown, and no finite
monetary ceiling is claimed. There is no automatic retry after timeout,
uncertain dispatch, failed capture, rejected vectors or failed result writing.

## Proof and live sequence

Use a genuine scripted executor through the same command and Graph. Prove
acceptance and refusal with concrete capture/gate/result checks, as well as
pre-startup foreign-run refusal, pin drift, spent-record refusal after a journal
reset, writer-checkpoint recovery without another dispatch, joined shutdown,
and bounded read-only inspection. Every new guard needs an assertion-killed
mutant; errors, skips and unexecuted tests are not proof. Separate Linux proofs
establish physical execution, not the portable platform substitutions.

Only after reviewed source, exact-head CI and relevant Linux proofs pass:

1. Confirm current exclusive custody and inspect the host's actual state.
2. Execute a reviewed exact-revision installation/qualification procedure;
   preserve evidence, notify before reboot and stop on unexpected output.
3. Rehearse the actual operational path credential-free on that installation.
4. Install the exact application authorization and dispatch at most one task.
5. Preserve either accepted candidate evidence or the truthful failure. An
   accepted candidate may be proposed in a normal repository PR; the worker
   cannot merge it, and passing the finite exam does not establish novelty or
   universal coverage.

No host commands or new qualification facts are supplied by this design alone.
The implementation record carries measured evidence; #186 carries current
ownership, pending deployment and task state.
