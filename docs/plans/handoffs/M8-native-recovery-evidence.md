# M8 native fixture recovery: acceptance and evidence

Status: credential-free Slice B investigation authorized by the owner on
2026-09-12, after the independently reviewed startup gate recorded in
[PR #62](https://github.com/sushiHex/constructicon/pull/62).
[#63](https://github.com/sushiHex/constructicon/issues/63) owns this work;
[#38](https://github.com/sushiHex/constructicon/issues/38) owns authentication.
Acceptance was committed as `7d8db2e` before implementation. The implementation
is [draft PR #64](https://github.com/sushiHex/constructicon/pull/64); exact-head
qualification remains pending its local, Linux, mutation and independent gates.

## Exact scope

Implement the existing [Slice B](M8-native-qualification-plan.md) over the
baseline recorded in the [current decision packet](../../designs/EXECUTOR_AUTHENTICATION.md).
The accepted [placement fixture](M8-provider-fixture-proposal.md) stays
test-only. Preserve the binary, runtime and catalog pins, the account-empty
configuration, the bounded fake peer and the existing Linux supervisor.
The experimental packaged-shell hook control is not part of this baseline.

Use the existing `LeasedCapability` contract for a test-only native fixture,
not an `ExecutorProvider` with a fabricated production network/profile claim.
One ordinary capability-lease row predetermines its acquisition/root recovery
reference. Acquire is inert. Materialization creates only acquisition-owned
test resources after the walker records and enrolls the handle. The private
native home remains inside the launcher's ephemeral namespace. The fake
endpoint belongs under the recorded acquisition, not an unrelated temporary
directory. No native session id or observed PID becomes recovery authority.

The test graph composes the fixture with the existing contained READ workspace.
The native callback uses that workspace through its existing guarded view.
Native and worker launches use the existing process owner; no duplicate
reaper, generic protocol manager, new scheduler, lease ledger, schema, runtime
asset or production API. Cleanup and reconciliation reuse acquisition closure.
The existing test helpers may accept the real acquisition paths instead of
minting their historical stand-alone test guard.

## Failure proof

1. A real first interpreter starts a public run and is killed after recording
   but before materialization, during materialization, with native and worker
   active, after native completion before checkpoint, or immediately after
   checkpoint. A second interpreter opens the same SQLite journal and authority;
   its actual ControlPlane/RunHost reads the lease inventory and recovers.
2. Inspect the durable rows and old payload/socket/native-home/process evidence
   before recovery. Reports may identify what to observe, but cannot supply
   the successor's cleanup inventory. Require closure, absent old resources,
   correct epoch advance, and no old native home/session reused. A retained
   checkpoint must restore without another native call; uncheckpointed work
   may rerun, never claim exactly-once model computation.
3. The worker includes a benign session-changing descendant. The observation
   requires it to exist and to have changed session before the death seam;
   completion requires reaping, not merely a stopped process or zombie.
4. Cancellation and stolen ownership are separate controls. The old handle
   must not start work after closure. A blocked or failed cleanup never counts
   as closed. Preserve original failures while joining owned cleanup.
5. Retain bounded native wire, full process outcomes, fake-peer observations,
   runtime identity and actual journal results. A source/fake check is not
   physical proof. All exact-head local, CI, native, assertion-mutation and
   independent source/artifact gates must pass.

Any need for another persistent authority, unsupported startup mode, account
access, new network/grant policy, modified binary or wider host policy stops
implementation for a decision. Failure is evidence, not permission to bypass
the accepted boundary. The previous fixture's sender-authentication limitation
remains; this slice proves resource lifetime, not process authorship.

Only positive combined startup and lifecycle evidence supports a proposed
successor ADR. Production/account conformance and owner acceptance remain
separate. No paid gateway replaces the subscription-reuse goal.

## Implementation and review corrections

`tests/native_lifecycle.py` is a test-only leased capability, composed with the
ordinary contained workspace. No production source, schema, launcher policy or
runtime asset changes. Its graph grants generic network `allow`, truthfully:
the native fixture has the accepted bounded peer route. The worker still uses
the existing networkless launcher. This is not a production network profile.

One acquisition guard covers endpoint creation, native conversation, callback
and joined peer teardown. Both process trees inherit that borrowed guard; the
worker also inherits its workspace guard. The helper never re-locks the same
acquisition through a second descriptor. Trusted Git closure checks run on
joined background threads rather than blocking heartbeat/control observation.

The first Linux run,
[34662575154](https://github.com/sushiHex/constructicon/actions/runs/34662575154)
on `1fda132`, passed ten process-death cases and cancellation, but **failed**
ownership revocation. Independent review reproduced the cause: the test
expected the revoked owner to dispose durable acquisitions, whereas the walker
correctly leaves that work to the successor. That run is not qualification.
The corrected test observes old-process quiescence and stale-handle refusal
first, then starts a real successor RunHost over SQLite to reconcile and finish.

The review also required explicit old native/workspace dispositions and absent
payloads, truthful network grants, nonblocking closure checks, and full worker
evidence recorded before success assertions. Returned or salvaged process
results retain bytes, both exit codes, elapsed time, timeout and bound facts,
plus the decoded outcome. Interrupted work with no returned result records
`null`, not an invented exit. Readiness is observed separately from completion.
Successor reports preserve their complete native/peer/worker observations too.

The portable instrument suite is deliberately separate from Linux proof.
Its assertion mutations cover durable-row validation, unentered/absent-resource
cleanup, control and closure checks, borrowed guards, the fixture's network
grant and failed worker evidence. Exact-head results and artifact identities
belong in the linked PR; a green portable test never implies physical isolation.
