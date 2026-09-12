# M8 native fixture recovery: acceptance and evidence

Status: credential-free Slice B investigation authorized by the owner on
2026-09-12, after the independently reviewed startup gate recorded in
[PR #62](https://github.com/sushiHex/constructicon/pull/62).
[#63](https://github.com/sushiHex/constructicon/issues/63) owns this work;
[#38](https://github.com/sushiHex/constructicon/issues/38) owns authentication.
Acceptance was committed as `7d8db2e` before implementation. The implementation
is [PR #64](https://github.com/sushiHex/constructicon/pull/64). That PR owns
current exact-head gate and review status; this record preserves acceptance,
executed evidence and its limits, not a second work-status list.

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
Successor reports preserve native and worker observations. Joined peer evidence
is in separate placement files, correlated by the exact socket root and native
thread, not run/acquisition ids alone: isolated test journals reuse those ids.

The portable instrument suite is deliberately separate from Linux proof.
Its assertion mutations cover durable-row validation, unentered/absent-resource
cleanup, control and closure checks, borrowed guards, the fixture's network
grant and failed worker evidence. Exact-head results and artifact identities
belong in the linked PR; a green portable test never implies physical isolation.

## Executed evidence and limits

On source head `8c8a3c79bd1c54f04832a0fc58372adf58829bb6`,
[Linux run 34663385354](https://github.com/sushiHex/constructicon/actions/runs/34663385354)
passed 30 recovery-stage checks (12 physical cases and 18 portable checks),
15 new assertion mutants, 131 combined-stage tests, 87 mediation tests and 324
containment tests, plus the retained mutation inventories. The local gate
passed 2,040 tests with 358 platform skips; CI passed 2,114 with 284 skips.
Artifact `10288154121` records that exact head, non-sudo UID 1002, enforcing
profiles, and unchanged pinned binary/catalog/runtime inventories. The placement
runtime is `sha256:1e9cca3b94f293754b83ddcecd9525ed1924e3aeb24067b5f95d0f93a32a0b48`.

Both model profiles exercise all five process-death seams. Old native and
workspace rows are discarded before checkpoint, released after checkpoint;
old payloads are absent after row-driven reconciliation. A retained checkpoint
produces no new acquisition or native call. Eight uncheckpointed death cases
and the ownership case complete through fresh successors. Cancellation has no
successor computation. The original revoked host stops work without claiming
its successor's durable cleanup.

Artifact inspection found 12 recovery reports and 15 associated placement
records: 13 completed exchanges each have two peer requests, no peer failures,
clean native/worker exits and a successful decoded worker outcome. The two
cooperatively interrupted old calls each retain one peer request, no post-join
peer error, and no complete process/decoded result. The two abruptly killed
active drivers have no post-join peer artifact; absence does **not** mean zero
requests. Their pre-death wire and worker readiness are partial observations.
Completed successor evidence is independent of that missing old completion.

The audit also caught an overbroad process observer: supervisors carry the
worker program in their argv too. The observer now matches the exact workload
argv and its changed session, not any argv containing that program. A portable
regression and two mutants distinguish supervisor, worker parent and worker
child. The final linked PR must rerun Linux with this tighter observer; the
earlier artifact is not retroactive proof of the corrected assertion.

The combined result qualifies only the accepted credential-free fixture after
its exact-head gates and independent artifact review. It permits proposing a
successor ADR, not accepting one or making an adapter available. Authenticated
startup, externally reachable cloud/plugin inputs, provider/account conformance,
credential ownership and live deployment remain unexecuted and separately gated.
The fixture route proves invocation membership, never CLI sender authentication.
