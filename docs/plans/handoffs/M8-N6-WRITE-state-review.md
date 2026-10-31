# Claude WRITE qualification: state and authority review

Living implementation review for [M8 N6 / #40](https://github.com/sushiHex/constructicon/issues/40),
under [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
and [M8 rev 3](../milestones/M8-live-executors-rev3.md#n6--independent-claude-code-qualification).
This document proposes the next credential-free implementation slice. It is
neither an accepted plan nor evidence that the proposed implementation works.
It grants no installation, boot, credential, maintenance, model-call, activation
or production authority. The completed live READ does not qualify WRITE.

## Outcome and verification tier

Deliver one qualification-only Claude WRITE through the existing graph and
leased executor contracts: admitted workspace, mediated callback, changed
candidate capture, exact contained gate, bounded report and three settled
obligations. The target ref remains at the admitted base. Installation or merge
of the candidate is outside this slice. Published provider availability remains
false; only an exact trusted qualification authorization admits the fixed run.

This is consequential work: callback execution, custody, asynchronous ownership
and evidence acceptance change. Its proof set is accepting and refusing
credential-free lifecycle tests, focused interleaving and restart tests, affected
physical Linux containment proofs and assertion-killed authority mutants, full
final-candidate CI, and independent review of the changed boundaries. Portable
substitutions establish state behavior, not physical Linux containment.

## Existing contracts and smallest change

- Keep `Executor`, `ExecutorProvider`, `TaskSpec`, `ExecutorOutcome`, grants,
  `LeaseContext`, acquisition rows, the walker and `RunHost` unchanged. No new
  L0 execution contract, scheduler, session service or workflow representation.
- Reuse `ContainedWriteWorkspaceProvider` / `ContainedWriteWorkspace` from
  `substrate/git/capture.py`: owned view, `use()` guard, contained capture,
  immutable pack import, candidate publication, `GitRef` and disposal.
- Reuse `ContainedGateRunner` / `BoundContainedGate` from
  `substrate/gates/contained.py`: fresh READ snapshot, fixed checks and
  journal-minted attestation. Native/model text cannot mint this proof.
- Reuse `QualificationAuthorization`, `WriteQualificationPins`, `AttemptRecord`
  and `CallbackObservation`. WRITE already requires an explicit model/effort,
  `contained_python`, empty environment, network `allow`, a 300-second grant,
  exact assembly pins, one epoch and one exclusive attempt record.
- Retain the Claude provider's acquisition/store guards, generation and binding
  checks, closure, native-only credential mount, egress relay and successor
  disposal. Workers receive neither vendor credentials nor network.
- Extend the existing Claude transaction narrowly for a closed WRITE catalog,
  schema and callback. Share framing, observations, correlation, native-read
  races, terminal acceptance and EOF drain; preserve READ defaults and behavior.
- Reuse the contained fixture/resource construction and exact-file checker in
  `_qualification_write_assembly.py`, and the deterministic capture/gate/report
  checks. Current Codex writer, graph, assembly verifier and report hardcode
  Codex handles, grants, scopes, profile or protocol limits; reuse requires
  explicit actual Claude inputs, not passing a Claude handle through a Codex
  identity check or copying Codex telemetry into a Claude report.

`codex.py` and `codex_protocol.py` remain untouched. Their recorded owner freeze
is not an invitation to extract a shared worker during this slice. A private
shared Claude worker base retains the existing owned-view, after-await and
cancel/join loop, with concrete READ and WRITE classes selecting fixed posture,
limits and input handling. This is internal L1 reuse, not a new L0 seam. A later
cross-provider extraction needs an applicable owner exception and must include
the helper in both source-derived identities.

## Closed WRITE recipe

Add a closed WRITE selection beside `ClaudeNativeRecipe.STREAM_JSON` and
`LOGIN`. `STREAM_JSON` remains the READ default. The WRITE selection has one
SDK-hosted tool, `contained_python`, accepting exactly `{program: string}`;
extra authority fields, arbitrary tool names and executable/path selectors
refuse. Its MCP server and fully qualified tool name are fixed assembly facts.
The Python program is untrusted task data executed only in the admitted
networkless WRITE workspace by the existing contained Python command.
The fixed qualification task requests one program; the finite catalog permits
sequential calls only. Already buffered or concurrent calls refuse under the
existing quiet barrier; there is no callback queue. Worker launch inherits only
the workspace guard, never credential, store-lock or relay descriptors.

Use the existing finite WRITE mediation bounds: one through eight admitted calls
must complete successfully for this qualification; zero refuses. Bound each by
128 KiB UTF-8 program bytes and 32 KiB UTF-8 output. Native cumulative
input, stdout, record and stderr bounds remain separately explicit and sealed;
the first applicable bound wins, including JSON encoding overhead. A per-call
bound does not promise that every maximum-sized call fits the cumulative wire
budget. READ's limits and one-file callback requirement remain unchanged.

One loop-absolute 300-second executor deadline covers materialization, probes,
startup, native exchange and callbacks. Each worker receives remaining time;
no callback renews it. Capture and gate use their existing separately bounded
capabilities after executor success. The outer control-host wait is an
observation bound and joins owned work before returning. These are not token,
backend request-count, money or guaranteed cleanup wall-clock ceilings.

The launcher already binds selected recipe, command and policy into its
revision and requires command/layout equality at launch. Use the selected
recipe's command everywhere; `ClaudeNativeVendor.command` currently denotes
READ. Bind the WRITE catalog consistently in registration, MCP calls,
assistant/tool records and `system/init` validation. Settings, hooks, mode,
binding, egress and native isolation retain their existing acceptance laws.
The native launcher still receives `workspace=None`, including for WRITE.
Nonzero/timeout worker results refuse the whole turn. Their mutations are
discarded through existing workspace disposal; failed turns do not capture.
Successful capture starts only after native drain and worker join, while its
workspace capability is still open. Existing capture interprets hostile Git
configuration only inside containment, then imports immutable pack bytes through
quarantine into trusted Git. This reuses the existing capture proof, not a new
host-side interpretation of workspace Git metadata.

The peer source review of pinned 2.1.296 found native tool timeout default
`Ar=1e8` ms (`B@244616142`), with `qo` selecting a server timeout of at least
1000 ms or `MCP_TOOL_TIMEOUT` before that default (`B@244617468`), and SDK idle
`Fr` including SDK servers with zero. No extra environment override is needed
for the 300-second controller deadline. SDK cancellation emits
`notifications/cancelled` on timeout/abort (`B@226910034`); propagation through
the native SDK control path is an inference, not a recorded live fact. The
existing quiet barrier refuses such cancellation traffic and joins the worker
without replay. These are source observations, not executed vendor evidence.

Startup evidence currently names the READ OBSERVE launcher revision. WRITE
selection must flow through trusted qualification and evidence validation;
READ evidence cannot be relabeled as affirmative WRITE launch qualification.
New helper code, catalog, bounds and assembly checks enter source-derived
identities. Old authorizations and conformance do not silently follow edits.

## Await, latch and crash review

Every resume checks the facts relevant to the authority about to be exercised.
A clean later result cannot replace an earlier missing observation.

| Boundary | State already possible after an await or crash | Positive fact required; refusal and final duties |
| --- | --- | --- |
| Admission and inert acquisition | An authorization may be spent, expired, replayed or for another graph. No physical work is owed merely by constructing a handle. | Exact source graph, invocation, binding, grants, assembly pins and revision; exclusive attempt reservation. No dispatch before durable enrollment. |
| Guard acquisition and store-lock wait | Close, withdrawal or recovery may commit while the waiter resumes. A returned lock establishes custody only. | Recheck invocation control, durable open fence, active generation and affirmative `BindingCheck`; recheck synchronously before transferring readiness. Join pending acquisition before releasing retained descriptions. |
| Probe/materialization resume | A probe may finish after closure or deadline; descriptors may already be owned. | Same sealed recipe, current custody, open fence and remaining deadline. Readiness is a single positive transfer, never inferred from an empty fault list. Cleanup closes every acquired descriptor even when materialization fails. |
| Before the user write | Startup reads may contain buffered records, partial frames or EOF. Intent persistence may consume the remaining authorization window. | Matching current mode/settings/hooks, complete handshake, classified received bytes, binding and open fence. Persist intent before the one user write; recheck expiry afterward. Uncertain dispatch remains possibly dispatched and is never retried. |
| Callback admission | IDs may already be spent, completion may be buffered, or another callback may be active. | Exact current invocation/catalog/schema, unique IDs, available callback slot, known session, open workspace and remaining deadline. Spend identity and persist admitted progress before launching; reentry/refusal poisons the owner. |
| Worker launch/use await | Closure, cancellation or native terminal/EOF can race a running program. The workspace may already be changed. | Genuine owned WRITE view with matching owner, epoch, capability revision and grants; no vendor/network launcher. Retain workspace guard through worker teardown. Native read damage or terminal state wins over a simultaneous worker success. |
| Worker result and guard exit | Worker may have completed before the native-read race selected it; guard release can observe closure. | Observe an actual `ProcessResult` at its producer boundary, with independent supervisor/payload exits, timeout, bounds and UTF-8 checks. Unknown stays unknown. Recheck workspace/control/closure/deadline after release before exposing output. |
| Callback response write | The physical change may exist although the response is partial or lost. | Increment completed count only after the whole response write positively succeeds, without an intervening await. Preserve one admitted effect; never replay on response loss. |
| Callback progress persistence | Rename may succeed before directory fsync fails; an older or newer snapshot can survive. | Latch persistence failure, prevent another effect and prevent a falsely final success. Preserve bounded observations without programs, output, paths or callback IDs. |
| Terminal controls and native drain | A success-shaped result may precede failed mode/binding checks, tail damage or missing EOF. | Correlated success metadata, current post-turn controls, exact callback response evidence, clean EOF, joined process/reader/relay and terminal custody observation. Failure demotes/refuses; retain emitted telemetry only at its actual scope. |
| Final attempt settlement | All work may have joined while an outcome write fails. A surviving final snapshot does not prove successful fsync. | Durable success before publishing executor success, with complete supplied callback observations. Prior progress failure cannot be overwritten into an apparently final census. Never reset the spent attempt. |
| Capture | Native success may have made no net change. Capture/import/publication can be interrupted independently. | Use existing guarded contained capture and closure-fenced candidate publication. Compare captured commit with admitted base; equality refuses before writer checkpoint and checker acquisition. Cleanup disposes workspace/candidate through its provider. |
| Writer checkpoint | Capture may exist without a checkpoint; response loss may hide an already durable checkpoint. | Persist the exact `GitRef` through the existing journal checkpoint law. Recovery reuses a valid checkpoint; without one, the exclusive spent attempt refuses a new model dispatch. Do not invent exactly-once model computation. |
| Gate acquisition/verification | Writer checkpoint may be durable while gate work or report delivery was interrupted. Target may have moved. | Fresh contained READ snapshot, fixed check set, matching candidate/tree/base/repository/target and journal-minted attestation. Recheck target; never accept model claims or a gate for another tree. Close gate custody on every outcome. |
| Shutdown, owner loss and recovery | Native, worker, relay or descendant processes may still own inherited guards. | Revoke callbacks/connections, cancel and join owned tasks/trees, preserve cleanup failures and release guards last. Successor validates all stale rows before fencing, waits for physical quiescence and disposes; it never signals persisted PIDs or resumes native conversation. |
| Report projection/replay | Only a prefix of observations or obligations may be visible; a terminal run may still lack evidence. | Derive bounded facts from the actual joined run, checkpoints, attempt, attestation and all three obligations. Missing/overflow/contradictory evidence yields incomplete/refused output, never pass by absence. Replay dispatches nothing. |

## Required accepting and refusing evidence

The first implementation must include an accepting fake path through real
control-plane admission and leased lifecycle, changed-file callback, ordinary
capture, exact contained gate and report. Assert the exact candidate tree,
matching attestation, unchanged target, executor/workspace/gate obligations and
their actual closure dispositions. A vendor success string alone is insufficient.

Its no-op counterpart runs a successful worker but refuses the unchanged
captured candidate before writer checkpoint, checker acquisition or redispatch.
Also refuse foreign workspace/epoch/owner/grants, READ/WRITE recipe substitution,
catalog/schema widening, duplicate/late calls, false process completion,
over-bound program/output/wire data and invalid UTF-8. Bounds need inputs where
they bind; a passing small script is not their proof.

Interleaving tests exercise native EOF/terminal/partial frame versus worker
completion, closure at probe/guard-release/result resumes, response loss,
repeated cancellation and cleanup failure. Observation tests cover admission
before effect, actual worker-result provenance, completed-response counts,
progress/final write failure before and after publication, explicit final
snapshot provenance and unknown legacy observations.

Restart tests cover capture without writer checkpoint, durable writer checkpoint
before gate completion, and completed result response loss. They positively
assert no additional model dispatch, valid checkpoint reuse, closure and settled
obligations. Physical Linux tests prove native/worker separation, networkless
WRITE and guard retention through descendant teardown. Existing generic capture
and gate proofs are reused unchanged; changed composition receives its own proof.

The report uses actual Claude grants, scopes, limits and emitted telemetry.
Unknown spend, backend request count, vendor retry count and served model remain
unknown. Public output contains no credential/account facts, private paths,
raw transport records, callback programs or worker output. Walk the entire
public report against its declared bounds, including refusal paths.

## Deliberate limits

This wave establishes implementation behavior with fakes and qualified harmless
Linux fixtures only. Fresh exact installation and WRITE startup qualification,
selected task/model/budget/overage decision and explicit live-attempt authority
remain prerequisites for any later subscription WRITE. No READ authorization,
spent attempt or historical Codex decision supplies those facts. Frozen plan
bytes and Codex modules remain unchanged.
