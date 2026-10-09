# M8 N5 Stage 4: the one WRITE turn

Status: Review draft: S4 decisions open on #78; authorizes nothing.

This is the planning deliverable for [#141](https://github.com/sushiHex/constructicon/issues/141),
following [Stage 3](M8-N5-stage3-read.md). Every implementation, proof and host
step below is future work. No WRITE code, smoke, host session or model request
is established by this document. Owner decisions will be recorded in a later
reviewed update; recommendations here are not those decisions.

## Authority and boundaries

The frozen [N5 state review](M8-N5-state-review.md), Stage 4, requires a fresh
acquisition and lease through the qualification path, the real worker, capture
and gate, and a credential-free smoke against the host's runtime Python before
the WRITE turn. Its decision 6 and refusal/retry rules remain the budget:

- One separately authorized WRITE `turn/start`, after READ.
- WRITE 300 s, shared by the native exchange and its callbacks, including the
  launcher's prerequisites. Existing capture operations separately inherit the
  writer's same 300 s grants; S4-5 proposes a bounded downstream gate. These
  are not extra model attempts or a total session/cleanup wall-clock ceiling.
- The recorded sealed cumulative input limit (1 MiB by default), eight bounded
  callbacks, and the existing per-program/per-output bounds.
- Tokens observational, unavailable usage unknown; backend request count
  unknown. No hard token, backend-request or finite monetary ceiling is
  requested or claimed.
- At most one more attempt across READ and WRITE, only after a diagnosed local
  failure known not to have dispatched. A possibly dispatched turn spends its
  stage's attempt. If Stage 3 T6 spent the shared retry, none remains for WRITE.
- `operator_authorized` overage under the account's own settings, with no turn
  starting while its spend control reports reached; authorized carry-over
  after dispatch remains applicable.

[#141](https://github.com/sushiHex/constructicon/issues/141) also records the
owner's provider-retry decision: vendor defaults within one `turn/start`,
bounded by its deadline; revisit for WRITE if READ evidence shows retries
firing, then weigh 0/0. READ evidence and that disposition are prerequisites
to S4-6, not an assumption that retries did or did not fire.

Implementation needs a separate issue only after the owner states Stage 3 is
finished on [#78](https://github.com/sushiHex/constructicon/issues/78), takes the
S4 decisions, and [#132](https://github.com/sushiHex/constructicon/issues/132)
has merged. Its actual cleanup outcome must be inspected; a closed issue is
not proof. [#142](https://github.com/sushiHex/constructicon/issues/142) separately
gates its controller change on owner-declared Stage 3 completion. This plan
does not permit either merge early, create the implementation issue, install
anything or run a host step. Host preparation, smoke and WRITE each need their
applicable owner authorization. No runnable host commands or authorization
record are included here.

## S4 decisions, all open on #78

1. **S4-1: WRITE attempt accounting.** Alternatives: extend the one-record
   exception accepted for READ, or seek a different reviewed accounting
   design before implementation. Recommendation: one exclusive attempt record
   per WRITE authorization, using the existing `AttemptRecord` and one epoch.
   The record survives a journal reset and accounts for the turn; no executor
   ledger or effect claiming exactly-once model computation/charge is added.
   S3-1's exception was for a read authorization; this extension is not already
   accepted. Capture/gate completion belongs in S4-7's separate derived report.
2. **S4-2: task, fixture and fixed gate.** Alternatives: a disposable minimal
   repository with one exact file change, or a larger owner-selected harmless
   fixture with correspondingly reviewed checks. Recommendation: the minimal
   fixture and proposed literal task in Part B, with deterministic exact-tree
   checks defined by trusted code: an empty seed tree, one new `100644` file
   `n5-write.txt` with bytes `b"ready\n"`, and no other paths. The owner chooses
   this recommendation or a specified replacement; the model cannot define
   its own exam. The literal below and a size under 200 UTF-8 bytes are
   proposals, not accepted WRITE requirements inherited from S3-3.
3. **S4-3: bind the rest of the WRITE assembly.** Alternatives: extend the
   root-installed qualification authorization with typed WRITE pins checked
   by L4, or design a separately reviewed trusted assembly seal and its binding
   to the authorization. Recommendation: typed pins in the existing
   authorization, as described in Part A, with no new store-generation fields
   or durable assembly-seal service. Exact proposed fields and checks require
   review; current authorization does not already pin workspace/base/gate.
4. **S4-4: generation and controller route.** Alternatives: use the existing
   authorized update/requalification route into the next generation, or first
   obtain a separately reviewed, owner-approved no-reboot controller/quiescence
   procedure that permits conditional g4 reuse. Recommendation: expect the
   next generation using the existing route. LR9's ordered route starts with
   LR1's fresh boot; g4 cannot survive it without maintenance/requalification.
   This plan does not design or authorize a no-reboot alternative. Unchanged
   frozen modules establish source compatibility, not an installed route.
5. **S4-5: smoke, capture and gate limits and custody.** Alternatives: keep the
   existing per-operation bounds with a fixed gate check, or seek a reviewed
   overall-deadline mechanism before implementation. Recommendation: preserve
   the accepted 300 s exchange/callback deadline and the writer/workspace's
   exact matching 300 s grants, hence 300 s per reset/capture operation. Give
   the separate checker invocation READ grants with no tools/environment or
   network, 30 s enclosing verification (merge preparation, snapshot, digests,
   20 s Python check and attestation), with joined cleanup. Keep the existing
   30 s populate launch and 30 s per assembly runtime-identification probe.
   For the smoke, use 300 s for its deterministic worker launch and each
   capture operation, then the same 30 s/20 s gate. Recommend a 1200 s WRITE
   observation wait, covering populate + exchange + optional reset + capture
   + gate (30 + 300 + 300 + 300 + 30 s). Timeout means incomplete, never an
   automatic retry. These are per-phase/observation bounds, not a total session
   or cleanup wall-clock cap; cancellation joins cleanup.
   Use disposable fixture authority and retained candidate/evidence only;
   never install into a real target. Specify its private root custody in the
   reviewed runbook. Later owner-directed cleanup preserves the spent record.
6. **S4-6: retry disposition after READ.** Alternatives: retain vendor defaults
   under the existing decision where applicable, or owner-approved 0/0 after
   reviewing READ evidence and its effect on the installed configuration.
   Recommendation: read the actual READ evidence first and record the chosen
   route and generation consequences. Account separately for the single N5
   retry's remaining availability. No automatic retry after possible dispatch,
   wrong output, capture failure or gate failure is proposed.
7. **S4-7: qualification verdict and public evidence.** Alternatives: derive
   one bounded WRITE report from existing attempt/journal facts, or request
   additional adapter telemetry and accept its freeze/generation consequences.
   Recommendation: the derived report in Part D. Require a completed turn,
   exact captured fixture change, candidate-bound passing gate attestation,
   succeeded run and affirmatively settled lease obligations. Do not require
   an exact observed callback count the current public facts do not provide.
   Report the enforced eight-callback ceiling as a limit, never a measurement.

## Part A: qualification authorization and host assembly

The existing [authorization contract](../../../src/constructicon/core/qualification.py)
accepts only `qualification-no-dispatch` and `qualification-read`. Proposed
`qualification-write` would be a dispatching stage with exact WRITE grants,
an absolute attempt-record path and `max_epoch=1`, and would retain the run,
invocation, executor binding/revision, graph hash, operator binding digest,
dedicated journal and expiry pins. The root-file reader remains the sole
authority source; minting remains computation, not permission.

WRITE-only pins must appear only in the WRITE wire shape. Preserve retained
READ/no-dispatch authorization serialization exactly, including existing keys
and defaults; do not add null/default WRITE keys to those records. Preserve
existing attempt-record fields independently: its reservation names the
authorization id, run, epoch and acquisition, not an authorization-payload
digest. Golden compatibility fixtures must hold both existing wire shapes.
Stage-aware parsing must return the existing `QualificationAuthorization`
interface consumed by the frozen provider, not an incompatible wrapper.
The complete serialized WRITE record must fit the root reader's 8192-byte
limit. Its scope/binding/epoch/expiry checks govern the executor acquisition;
workspace/gate authority comes from the proposed L4 pins and manifest checks,
not an invented generic authorization-acquisition rule.

The current graph hash pins the fixed component source and bindings. It does
not pin the catalog's workspace/gate revisions or the fixture base. Under the
recommended S4-3 option, add a typed WRITE-only pin block for the workspace
capability id/revision, gate capability id/revision (its check-set identity),
fixture identity and exact base commit/target, and derived-report definition
identity. Trusted L4 assembly would check every value against actual prepared
artifacts before registration, admission or RunHost startup, and require the
same assembly when recovering the dedicated journal. The fixture identity
would bind its reviewed seed bytes and canonical authority relationship;
locators stay private operator configuration. It must refuse a different
authority, moved target/base, changed gate/check argv, workspace revision or
report definition, including on recovery. An authorization's claimed digest
alone is not an artifact or physical-custody check.

These additional checks belong in the trusted entry/assembly, not the walker
or a native tool. They would use existing descriptor/manifest contracts and
the current authorization record, without changing frozen Codex modules or
adding authority to an operator-store descriptor. Implementation must resolve
the exact pin schema and custody checks before making this path runnable.

The [host assembly](../../../src/constructicon/substrate/executors/codex_host.py)
currently builds only READ. Add a WRITE assembly using the installed launcher,
production configuration, executable and sealed account/store facts, with:

- `NativeOperatorExecutorProfileV3`: WRITE, `filesystem="workspace_only"`,
  only `contained_python`, workspace required, native workspace none, worker
  network none, separate native/worker zones, narrow vendor store, existing
  account assurance and `operator_authorized` overage.
- Exact WRITE grants: prepared catalog model and effort, network `allow` for
  the native vendor session only, empty environment allowlist,
  `allowed_tools=("contained_python",)`, and 300 s. The entry uses these WRITE
  root grants, not its current hardcoded READ root grants; the graph narrows
  the downstream checker to S4-5's explicit READ grants.
- `ContainedWriteWorkspaceProvider` and `ContainedGateRunner` against the
  prepared fixture authority, actual installed runtime and dedicated journal,
  with exact leased descriptors of kinds `workspace.contained` and
  `gates.contained`. Gate creation identifies its runtime before advertising
  its revision; its Python/check paths name the contained runtime, not the
  controller's interpreter.

The provider remains unavailable except for the specifically authorized graph.
Take the three conformance references from sealed `Q`, following S3-2: a
reference to startup qualification, not earned WRITE/vendor conformance.

### Freeze answer: unchanged modules; next generation by the existing route

The proposed implementation leaves `codex.py` and `codex_protocol.py` unchanged.
The current wave's brief freezes both with no end date; S3-4's accepted text
explicitly names `codex.py`. Their whole-module source digests
are Stage 2's adapter/protocol revisions. The existing provider already reserves
any authorization's attempt-record path, uses its `dispatches` predicate and
settles any supplied attempt record, independent of posture. Extending the
core stage predicate and L4 assembly therefore has a source-compatible route;
that route still needs the future proofs below. The adapter's source digest
does not include the imported core dispatch predicate: unchanged adapter bytes
do not prove unchanged dispatch semantics or compatibility.

Before relying on g4, `sealed_account` must accept the exact generation's
closed passing startup evidence and compare every installed `launch_facts`
identity: adapter, protocol, launch/runtime, executable/catalog seals,
configuration and egress. Keep that equality and existing boot/store custody
checks throughout. A WRITE profile and callback catalog produce a distinct
executor capability revision, which the WRITE authorization must pin; they do
not themselves prove a new store generation is needed or that g4 suffices.

The updated controller tree also needs its authorized installation route.
[Stage 2](M8-N5-host-session.md), H1 and decision 5, requires a current controller.
[Launch replacement](M8-N4-launch-replacement.md), Order and LR9, starts with
LR1's fresh boot: that is its quiescence premise, not an optional process scan.
Stage 2 decision 4 says a reboot requires authorized requalification into the
next generation. Therefore S4-4 recommends that existing route, even with both
modules unchanged. Conditional g4 reuse also requires a separately reviewed,
owner-approved no-reboot controller/quiescence procedure; none exists in this
proposal. Its equality tests above are necessary but insufficient.

The future runbook must name the reviewed merged commit and applicable owner
authorization; Stage 2's authorization cannot silently authorize another
update. Frozen-module edits, changed configuration/runtime/egress or failed
compatibility proofs likewise stop for the owner's replacement/requalification
decision. No conformance hash may be invented to bridge any mismatch.

## Part B: the fixed WRITE graph

Use one strict Graph and the existing walker/ControlPlane/RunHost path. The
writer binds both executor and contained workspace on the same invocation;
the downstream checker binds the contained gate. A workspace acquired by a
different node is not transferable: existing ownership checks require the
same run, epoch, path, manifest, owner and exact effective grants.
Keep aliases `executor` then `workspace`, the admission/walker acquisition
order, so the attempt is reserved before workspace population. Population
failure may leave an acquired-only record, which proves no turn was dispatched;
it grants no new retry right. Only the existing diagnosed-local-failure rule,
remaining shared retry and separate owner authorization permit a new record.

Proposed task literal, inside the writer function:

> Use contained_python to create n5-write.txt containing exactly ready followed
> by a newline. Change no other files.

The proposed disposable fixture has one seed commit whose tree is empty; its
actual commit identity is pinned when prepared. The expected candidate tree
contains only `n5-write.txt`, a regular `100644` file with bytes `b"ready\n"`.
The model receives only the literal, no repository or account content, no task
context or response schema. Existing worker argv is
`/usr/bin/python3 -I -c` with code read from stdin; the native zone receives no
workspace, and the worker receives no vendor store or provider route.

The writer requires `ExecutorSuccess`, then awaits `commit_all` and emits the
candidate `GitRef`. Capture imports verified immutable pack bytes through the
existing containment/quarantine/publication fence. The checker verifies that
exact candidate through `MergeGate.verify`, requiring the one exact path,
bytes and mode above, with no other entries. Its separate invocation uses the
30 s READ grants and fixed 20 s check proposed in S4-5. Gate checks are fixed
by trusted code and included in its revision. A
failed check is data; the qualification node/report must explicitly reject
`evaluation.ok=False` rather than treating run completion as a passed exam.
No merge/install effect is assembled. Record target/base equality affirmatively.
Refuse base/target drift observed during preflight or before the writer calls
`execute`. The trusted L4 fixed WRITE request carries the sealed base, and the
writer compares the acquired `workspace.base` before executing. The report
must prove gate `subject.candidate` equals the captured candidate,
`expected_base` equals the sealed base, and `tested_tree` equals the candidate's
tree: the contained gate actually checks a prepared merge tree. This is not
an atomic fence around dispatch: drift observed later
must fail the gate/report and cannot undo or refund a dispatched turn.

The current [qualification entry](../../../src/constructicon/api/qualification.py)
needs stage-specific definitions, graph, bootstrap, assembly and mint/run
handling, including WRITE root grants and S4-5's 1200 s observation wait rather
than the current READ grants/600 s default. Use importable node functions and
source digests as Stage 3 does;
put the task literal inside its function, not a module constant. A fixed gate
program is bound by its actual check argv/check-set identity. No caller-supplied
task, code, tool widening or dynamic check selection is introduced.

## Part C: owner-run smoke and session shape

The future credential-free smoke would run a deterministic program against the
installed runtime Python using the same worker argv, real Linux launcher and
acquisition-owned contained workspace, then real capture and the fixed gate.
Use `LinuxLauncher.run` with fixed `WORKER_ARGUMENTS` and `input_kind="task"`,
never a Codex handle, native session or store lock. Use a separate smoke fixture
and journal; independently recheck the WRITE seed/base afterwards. It needs no
credential or model request. It must affirmatively
produce the exact candidate, passing gate attestation and settled leases under
the host's runtime identities. This proves that host's worker/capture/gate
composition, not authenticated Codex callbacks; those are exercised by the
separately authorized WRITE turn and the credential-free scripted integration.

The future session runbook would specify these phases, with refusal tables:

1. Owner evidence: Stage 3 finished, remaining shared retry disposition, S4
   decisions, reviewed implementation head and prerequisites. Resolve S4-6
   from READ evidence before choosing the configuration/generation route.
2. The authorized controller update and next-generation requalification, or
   S4-4's separately reviewed no-reboot alternative plus g4 equality checks.
   Do not touch the store via
   an unreviewed controller or invent a new login requirement.
3. Fresh private state, reviewed fixture/base and the authorized no-model smoke
   on the host's actual runtime. A failed smoke stops before a WRITE turn.
4. Stage-specific mint and owner/root review/install of the WRITE authorization;
   verify all pins before use. Fresh run, acquisition, logical lease and attempt
   names; no closed READ handle, journal or record is reused.
5. One WRITE invocation, followed by the bounded evidence verdict in Part D.
   A complete turn followed by failed capture/gate is an incomplete WRITE
   qualification and still a dispatched attempt.
6. Only an owner-authorized retry after a diagnosed local failure proven not
   dispatched, and only if the shared N5 retry remains. Use entirely fresh
   names and preserve the previous record. Stop on any uncertain dispatch,
   unresolved custody or cleanup failure; inspection does not grant a retry.

An observation timeout leaves the WRITE verdict incomplete. Recovery may
finish only the checker if the exact durable writer checkpoint restores the
captured candidate without acquiring another executor or dispatching. With a
spent attempt and no such checkpoint, refuse writer replay; neither a longer
wait nor recovery creates another attempt. Prove both paths before relying on
that distinction, including checkpoint integrity and #132's final behavior.

## Part D: evidence and verdict

The frozen adapter's attempt outcome records dispatch class and bounded turn
facts: status/refusal, answer length where emitted, usage/served model or
unknown, readbacks, relay counts, process facts and identities. Its `completed`
means accepted executor success, before capture and gate. Preserve those
semantics. No prose answer is required for WRITE, and answer length does not
prove a workspace change.

Derive the additional report from the existing dedicated journal, sealed
manifest, checkpoints, fixture authority and stored gate attestation. Do not
rewrite the settled attempt record or introduce a second cleanup ledger. The
reviewed report contract would expose only allowlisted bounded facts:

- Run/manifest, authorization/attempt, acquisition and capability identities;
  observed turn dispatch class separately from WRITE qualification status.
- Actual sealed limits and model/effort, telemetry/readbacks or explicit
  unknowns, and unchanged installed identities, without inferring telemetry.
- Fixture/base/candidate identities, exact change-check verdict, unchanged
  target, workspace/gate revisions, gate subject/check-set/attestation ids and
  bounded per-check statuses. Verify candidate equality against the stored
  attestation and its journal provenance; do not accept a caller-created proof.
- Run terminal status and every recorded acquisition's closure state; distinguish
  missing/incomplete evidence and unresolved obligations from success. #132's
  final recovery behavior must be incorporated before this becomes executable.

Public evidence excludes credentials, account identifiers, raw protocol,
callback program/output, model text and local host paths. Operator-private
authorization/state may contain required locators. Bound the entire public
report by declared field, item-count and byte limits; do not forward unbounded
journal events or gate details. Existing attempt facts do not publish callback
counts, candidate or gate facts. Report an exact count only if a separately
reviewed affirmative producer measures it; accessing private counters is not
an established public contract. Additional adapter telemetry would reopen S4-4.

WRITE passes only with affirmative evidence of all of: completed attempt,
accepted exact captured change, passing candidate-bound gate/attestation,
succeeded run, settled lease obligations and unchanged target. Missing evidence
means incomplete, never passed. Candidate/gate evidence does not grant merge
or qualified production availability. The owner reports the verdict on #78;
this draft cannot certify N5 completion.

## Future proof and review

The following is the required proof design, not tests written or executed:

- **Portable accepting and refusing paths:** WRITE authorization shape and
  grant/pin equality; golden retained authorization/attempt wire shapes;
  existing provider interface and root-reader 8192-byte bound;
  wrong graph/run/path/epoch/revision/base/fixture/gate;
  expired authorization; spent record across journal reset; unavailable
  provider preserved; importable node/source identity. Run the permitting
  writer-capture-gate path from the first implementation slice as well as
  refusal tests. Inspect actual immutable descriptors with `system.describe()`
  and detail/impact surfaces before adding any production component.
- **Attempt boundaries:** acquisition, durable intent, expiry before/after
  intent, input refusal before dispatch, interrupted `turn/start` write,
  cancellation and lost response. Hold completed turn versus failed capture,
  red gate, lost checkpoint and cleanup failure separately. Recovery must not
  replay a model turn through a fresh attempt after dispatch; a spent record
  must refuse even where older unqualified WRITE tests replayed the writer.
  Test executor-before-workspace acquisition, populate failure/acquired-only
  accounting, and observation timeout with exact writer checkpoint (checker
  recovery only) versus without it (spent writer refuses, no dispatch).
  Exercise #132's final terminal-obligation behavior instead of assuming
  terminal status means all leases closed.
- **Physical credential-free composition:** production WRITE profile/grants,
  scripted native peer and real worker/capture/gate on the provisioned Linux
  lane. Hold same-invocation workspace provenance, no worker credentials/network,
  single exchange/callback deadline, sequential callbacks, accepting exact
  change, wrong/extra/mode-changed files, failed gate, closure and no target
  installation. Test moved base before dispatch versus after dispatch, matching
  writer/workspace 300 s capture grants and separate 30 s/20 s gate bounds.
  Hold sealed-base request/workspace equality, candidate/expected-base/tested-
  tree proof, 30 s populate/probes and 1200 s observation independently.
  Exercise limits with an input where each bound actually binds.
  The existing N2 composition in
  [test_codex_write_capture.py](../../../tests/substrate/test_codex_write_capture.py)
  is a reusable test shape, not evidence that this new assembly ran.
- **Runbook rehearsal analogous to #138:** run the future runbook's actual
  eligible blocks on the foundation lane with a synthetic generation and
  logged-out fixture, checking the precise account-gate refusal, real process
  facts, zero connections, spent-record refusal and fresh retry names. That
  rehearsal cannot prove anything after the refused account gate. Pair it
  with the accepting scripted physical path and smoke; label each limit.
- **Evidence contract and mutants:** field-by-field report bounds, no secrets,
  text or paths; distinct turn/qualification verdicts; incomplete facts cannot
  pass; matching candidate/attestation/check-set and closed obligations. Add
  assertion-killed mutants for new decisions and boundaries, register them in
  exactly one CI lane and retain live targets/collectable killing tests.
- **Final implementation head:** repository gate, relevant native/mutation and
  compatibility lanes, exact frozen-module/installed-fact comparisons and
  independent review. A Windows skip or docs-only check is not containment,
  vendor, host or g4 proof. Owner-only host smoke and turn evidence remain
  separate from CI and must be reported as unrun until they actually run.

## Independent cross-review disposition

Claude review `job_ce5e2115ccef`, selected actual model `claude-opus-5-5`, found
two introduced planning blockers, reproduced against source and adopted:
LR9's fresh-boot premise invalidates the proposed default g4 route, and the
READ-root/600 s entry defaults and recovery distinction were not fully planned.
S4-4 now recommends the existing next-generation route; Parts A-C specify WRITE
root grants, 1200 s observation and checkpoint-only checker recovery.

Adopted refinements: complete populate/probe/gate bounds; sealed base versus
actual workspace and merged tested tree; executor-first acquired-only failures;
separate smoke fixture/journal and direct worker launch; authorization interface,
8192-byte limit and retained wire compatibility; executor-only authority scope;
and source hashing's imported-dispatch limitation. All are future proposals,
with S4 decisions still open and no implementation/host proof claimed.

Rejected the review's proposed narrowing of the freeze to `codex.py`: the wave
brief freezes both modules. Adopted its citation correction, since S3-4 itself
names only `codex.py`. The review's uncertainty about #132/#142 status supplies
no positive status evidence; their issue/owner gates remain unchanged. The owner
confirmed Stage 2/3 are unrun. No second cross-review is claimed.
