# M8 N2 WRITE: state and resume review

Status: independently reviewed pre-implementation design. Base: `c38f53d`. Scope: the remaining
WRITE slice of [issue 75](https://github.com/sushiHex/constructicon/issues/75).
Authority: [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md),
[M8 rev 3 N2](../milestones/M8-live-executors-rev3.md), and the retained
[rev 2 N2 matrix](../milestones/M8-live-executors-rev2.md). This record does not
amend those frozen artifacts. No implementation begins until an independent
source-based review accepts or corrects this design.

## Boundary and reuse

This slice adds one fixed mediated callback to a separate WRITE profile and
proves it through the existing task-shaped component, contained WRITE capture,
and contained gate. It does not add a component, graph language, executor
contract, public schema, journal row, scheduler, process owner, credential,
network route, or deployment authority.

The inspected schema-4 `system.describe()` assembly and current unavailable
READ adapter already publish the leased schema-3 executor profile, exact grant
policy, assurance literal, revision and unavailability reasons. No inspected
component dependency requires a new primitive. WRITE therefore remains the same `Executor.execute`
call used by `tests.captureworld.propose_and_capture`; the unchanged component
then awaits `AsyncWriteWorkspace.commit_all`, and a downstream unchanged gate
component awaits `MergeGate.verify`.

Reuse `CodexOperatorProvider`/`CodexOperatorHandle`, `CodexConversation`,
`LinuxLauncher.exchange`, `LinuxLauncher.run`, the existing acquisition/store
guards and positive binding checks, `ContainedWriteWorkspace.use`, capture's
immutable pack quarantine/publication, `ContainedGateRunner`, the walker lease
law, and `finish_owned`. The graph walker still schedules graph units; the
adapter owns only its one native conversation and at most one joined callback
worker task at a time.

The default provider stays unavailable. Credential-free scripted and contained
fixtures may assemble a deliberately fake-qualified route, but cannot publish a
production subscription capability. No real account, vendor request, credential
content, secret hash, VM, or external network participates.

## Exact retained-pin protocol

The retained candidate remains Codex `0.153.4`, tagged source
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`: archive SHA-256
`a822187e1a2420c61c5926721bfbd878701ed95547c9bb0d4de4498a16ba1821`,
binary SHA-256
`56ef98ab4032d317ab26e9b5e5a175650717351edb16ed9cde0cb6d1734d62da`,
and the generated `DynamicToolCallParams`/`DynamicToolCallResponse` schema
hashes recorded in [the mediation probe](M8-native-mediation-probe.md). The
restricted model-catalog bytes already measured there have SHA-256
`4f22dc85ec6e08bddd3b4e793601bf4298cd3d2c869e3a0f77c4ef2b55ca246d`.
Changing any pin repeats catalog, startup, mediation and lifecycle proof.

The callback is exactly `contained_python` with the already measured closed
input object `{program: string}`. The fixed code-bound schema and name enter the
callback protocol/adapter revisions; the finite catalog name enters
`callback_catalog_digest`. The WRITE grant policy offers only its exact tool
set, requires a workspace, one explicit model, `network="allow"` for the native
vendor session, and WRITE posture. No argument selects an authority locator,
executable, store, endpoint, grant, actor, model, provider or environment. The
program is untrusted task data and may name workspace-local paths; physical
worker containment, not string classification, confines it.

The retained-pin experiment establishes the callback only with
`initialize.params.capabilities.experimentalApi = true`; it did not run the
same `dynamicTools` request without that flag. The current
[official app-server reference](https://learn.chatgpt.com/docs/app-server) calls
the field experimental and says the flag is required, but current documentation
is not proof about `0.153.4`. The first pin fixture must therefore positively
show exact acceptance with the flag and exact pre-provider-request refusal
without it. The current READ adapter deliberately omits it. WRITE must not
quietly copy the probe or broaden READ:

- READ continues sending an empty capabilities object and no dynamic tools.
- WRITE advertises the opt-in at `initialize` only when its sealed profile and
  nonempty exact catalog agree. That does not open worker authority: the exact
  dynamic tool is first registered at `thread/start`, only after the first
  `account/read` gate has positively passed.
- One acquisition owns one app-server process, one client connection, one
  ephemeral thread and one turn. It never resumes, forks or shares a thread or
  connection across acquisitions; the pin contains unresolved cross-client
  shared-thread behavior, so this is a structural exclusion, not a convention.
- Trusted constructors retain an exact outgoing method inventory:
  `initialize`, `initialized`, `account/read`, `thread/start`, `turn/start`, and
  the response to one admitted `item/tool/call`. There is no constructor or raw
  forwarding path for login, `chatgptAuthTokens`, auth/config mutation,
  `process/*`, `thread/shellCommand`, approval, MCP, app, skill, hook, plugin,
  subagent, model/provider override, or arbitrary client RPC.
- One classifier handles every id-bearing server request. Only
  `item/tool/call` with the current thread, turn, exact tool, closed argument
  schema, unique nonempty call id, unique inbound request id and bounded bytes
  can enter the worker. Client reply ids and inbound server-request ids have
  distinct ownership/uniqueness domains; an inbound collision cannot satisfy or
  consume a future client reply. Calls are sequential and capped by a finite
  code-bound per-turn count included in the adapter/limits identity. Unknown,
  over-limit, duplicate, late, foreign or malformed requests refuse the result;
  they are never transcript-only damage after an effect.
- Each call id is spent before its first worker await. Response loss never
  reruns it. A positive per-call completion is recorded only after the worker
  has joined and the bounded response has been written. Missing completion,
  pending work, or an unfinished protocol check is refusal, never an empty-fault
  success.

Pinned-source inspection establishes that `experimentalApi` is a per-client
connection boolean gating experimental `ClientRequest` fields; setting it does
not itself authenticate, select a route or perform network I/O. The exact
request constructors and server-request classifier, not the false value, are
therefore the mechanical authority boundary. This is conditionally within ADR
0021's already accepted callback design and needs no new owner authority. The
claim that READ's omission froze the flag for every later posture is rejected:
the evidence supports that READ scope only. Independent review must still
confirm the closure. If the retained binary exposes an auth/config/process
operation as a model/server request outside it, stop for owner direction rather
than implement.

Existing MCP mediation is not an alternative. Constructicon's public MCP is an
L4 skin over `ControlPlane`, not an executor tool router. The tested project MCP
is an inert startup fixture; it has no route to an acquired workspace or the
parent adapter. The launcher deliberately withholds guards and control
descriptors from payloads. Making native MCP reach a worker would require a new
private channel/launcher surface, while placing the worker inside the native
zone would expose the vendor store and violate the two-zone law. N2 adds neither.

The retained restricted-catalog fixture removes the measured patch, CodeMode
and collaboration routes, and its fixture configuration disables the measured
image reader. That is not yet an applied production configuration proof.
`CodexOperatorProvider` currently hashes/parses supplied configuration bytes but
does not install them or route `CODEX_HOME`; N3a explicitly did not add that
behavior. `configuration_digest` therefore identifies proposed bytes, not an
observation that the launched client used them. N2 may exercise those exact
bytes in the credential-free mediation fixture, but the production provider
remains unavailable. N3c/N4 own applied configuration, refresh non-widening and
conformance. Within N2's state machine, any server request other than the exact
admitted callback refuses. Effective tool inventories, warnings and requests
remain positive fixture evidence; config flags or absence of a call are not
completeness evidence.

## Worker, capture and gate ownership

WRITE accepts only the assembled `ContainedWriteWorkspace`, not a relabeled
legacy or arbitrary `WorkspaceView`. Reuse
`workspace.provider.owned_view(workspace, executor.context)` for provider
minting, open/ready phase, run, epoch, execution-path, manifest and posture
checks rather than duplicate that predicate. Add only the facts it does not
compare: the same lease owner, the workspace binding's exact current revision,
and canonical equality of effective grants. Bindings may differ; invocation
identity and authority may not. Repeat this composed check before and after
worker awaits.

For an admitted callback, enter `workspace.use()` and retain its acquisition
guard while `LinuxLauncher.run` executes a fixed Python worker with
`workspace=Path(workspace.path)`, `posture=WRITE`, no network, a clean
environment, and the bounded program on stdin rather than argv. The worker gets
the workspace only; it gets no vendor store, native HOME, provider connection,
journal, authority Git, callback endpoint, or host path. The native app-server
continues in its separate namespace with the native store and no workspace.

One absolute deadline begins before the native launch probe. The handle computes
it before calling `exchange`, passes `deadline - loop.time()` as the exchange
timeout, and injects that same absolute value into the WRITE conversation. The
callback recomputes the remaining duration immediately before
`LinuxLauncher.run`; probe time and earlier protocol/worker time are already
spent, so a callback cannot renew the task deadline. The callback owns an
explicit worker task. On native EOF, callback
failure, outer cancellation or local close it cancels and joins that task with
`finish_owned` before leaving `workspace.use()` or letting native cleanup finish.
The worker launcher's supervisor owns all worker descendants. It inherits only
the workspace guard; the native acquisition/store guards remain with the outer
native supervisor and must never enter the worker zone.

The conversation must observe native death while that worker is active; awaiting
the worker alone cannot do so because the launcher does not cancel its protocol
task merely when the child reaches EOF. Under the same absolute deadline, race
one owned worker task with the conversation's sole read task. Judge a read first
when both complete. EOF, damage, an account notice, a terminal record, a client
reply or any non-exact server request refuses, cancels and joins the worker.
Ordinary id-less nonterminal notifications pass through the existing absorber
under a finite record-count bound. Strictly parsed same-turn callbacks may arrive
while one effect is active: reserve unique inbound request and call ids, and hold
their raw records in wire order under both the remaining call ceiling and a
code-bound aggregate byte ceiling. They perform no effect. After the active
worker has joined, write its response first; only a successful complete write
prepends the held calls ahead of the existing queue for sequential dispatch.
Response loss discards them, so it cannot start the next effect. Cancel and join
the pending read and worker on every exit. A pre-turn callback and completion
buffered together refuse before dispatch regardless of their order: no callback
response existed when the claimed completion arrived.

A worker timeout, bound, nonzero/incoherent exit, control loss, workspace fence
failure, response-write loss, or callback-protocol fault records refusal. Even
if the native turn later says completed, no `ExecutorSuccess` is published.
Because the unchanged component captures only after executor success, refused
or cancelled work is never imported; walker-selected discard closes both
acquisitions. On acceptance, the joined worker and released use guard precede
`commit_all`, whose existing quarantine and publication fence produce the
candidate. The downstream contained gate independently prepares and checks that
exact candidate. A CLI result never mints its attestation or bypasses a red gate.

The walker's recorded close batch follows acquisition order, and the unchanged
component binds workspace before executor. This is safe only because cancellation
cannot escape `Executor.execute` while its callback worker still owns
`workspace.use()`: the native exchange cancels and joins the conversation, which
cancels and joins the worker, before the walker can begin closing the workspace.
Pin that permitting order in a test. Do not rely on changing capability order or
silently reverse the generic close law. After literal controller death, the old
supervisors—not a Python callback—own the guards; successor workspace recovery
may wait for their physical quiescence before executor-row reconciliation.

## Proposed code shape

Keep the change inside the existing two adapter modules. In
`codex_protocol.py`, extend the fixed builders rather than add a protocol layer:
`initialize_request(..., experimental_api: bool)`,
`thread_start_request(..., dynamic_tools: tuple[Mapping[str, Any], ...])`, and a
pure strict parser for the one tool-call shape. Defaults reproduce the retained
READ request bytes. The dynamic-tool schema, finite call ceiling and response
builder are constants bound by `PROTOCOL_REVISION`; no Pydantic/public contract
is added.

In `codex.py`, give `CodexConversation` an optional exact catalog, one async
`worker(program) -> str` callback and the shared monotonic deadline. The READ
construction passes neither catalog nor worker. WRITE construction passes a
handle method which reuses `ContainedWriteWorkspace.provider.owned_view`, enters
`workspace.use()`, and calls the existing launcher's `run`. Conversation methods
own inbound-request/call sets, bounded pre-identity requests, call spending and
the positive completion latch. `CodexOperatorHandle.execute` chooses READ versus
WRITE behavior solely from its sealed single-posture profile and validates the
workspace before constructing the conversation. `CodexOperatorProvider`
replaces the current nonempty-catalog refusal with exact profile/catalog
coherence; launch-identity drift checks remain unchanged.

The focused portable seam remains `ProcessIO` plus the existing scripted
launcher and substituted acquisition guard. Extend that launcher to record and
control worker `run` calls; do not add a test-only production branch. Pure
protocol tests inject a bounded worker callback. Handle tests pass the actual
controlled contained-workspace object so provider minting, invocation identity,
control checks, response loss and join order are exercised end to end. The
separate Linux lane supplies the physical launcher/worker/capture/gate proof.

## Await/resume and early-return ledger

| Boundary | State possible when execution resumes | Required decision |
| --- | --- | --- |
| Executor entry | Wrong posture/catalog/grants, foreign or legacy workspace, prior execution | Set the one-execution latch before awaiting; refuse before native or worker I/O |
| Pre-launch closure/binding awaits | Close, cancellation, ownership loss, withdrawal or recipe drift | Reuse the current control, closure and positive pre-spawn checks; never inherit an earlier observation |
| Native request write/read | Buffered/framing bytes, forged future id, account notice, EOF or damage | Apply existing queue-plus-framing ordering and positive gate latches; every early return records refusal |
| First account gate | Gate replied but catalog is not yet open | Compare the exact expected account first; only then send WRITE `thread/start` with its fixed dynamic tool |
| Tool request before turn identity | A valid-looking request may be buffered before the `turn/start` reply names its turn | Defer only within the same record/total/call bounds and perform no effect; after the reply, validate its named turn before dispatch. If the reply never arrives, refuse at the existing deadline. Do not assume notification ordering |
| Tool request classification | Request may be foreign, duplicate, late, oversized, collide with a client id, or name a non-granted surface | Validate the distinct inbound request id plus call/thread/turn/catalog/schema/grant facts; spend the call id before worker await |
| Workspace guard wait | Workspace closed/recovered or run control lost | Revalidate invocation identity and both control checks after entry; launch no worker on failure |
| Worker launch/probe | Native process may exit; another exact call may arrive; outer cancellation/close may latch; deadline shrank | Under the shared deadline race the owned worker with the sole read; boundedly hold exact unique calls without effects; retain and join both tasks |
| Worker completion | EOF, terminal/account/damage or a foreign request may already be readable; workspace or control may have closed; output may be partial/bounded | Judge a simultaneously completed read first; refuse and join on terminal damage; otherwise recheck both acquisitions and interpret the complete `ProcessResult` |
| Tool response write | Worker may have changed the stage, exact later calls may be held, but peer may have vanished | Keep the call spent; write once; only after a complete write restore held calls in wire order. Response loss refuses and dispatches none of them |
| Turn completion | A callback may still be pending or terminal record may precede its naming reply | Buffer only under the existing bounded rule; require no pending callback and positive callback accounting |
| Second account gate | Forged/buffered reply, mode change, parse escape or unfinished drain | Reuse the positive gate/drain rules; discard turn fields on any refusal |
| Launcher completion | Child exit can be clean despite callback/protocol failure | Require conversation gate, callback ledger, complete process result, launch check and fresh terminal binding check |
| Component capture | Executor succeeded but control/closure may have changed | Existing `commit_all` rechecks, joins writers, verifies immutable pack, then atomically publishes or refuses |
| Gate verify | Candidate exists but cancellation/base change/check failure may occur | Existing gate control and attestation law decides; executor output conveys no gate authority |
| Close during any await | Native and worker tasks, materialization, store/acquisition/workspace guards may exist | Latch close; commit durable executor closure; cancel and join owned tasks; then release only owned descriptors. Cancellation must not reach the walker's workspace-first close until `workspace.use()` has exited |
| Successor recovery | Old callback/worker/native supervisor or published candidate may survive | Existing lease rows select disposition; close old executor/workspace/gate acquisitions before fresh uncheckpointed work |
| Checkpoint resume | Proposal node already has a successful checkpoint | Reuse its recorded candidate output; do not acquire/call native or capture again; downstream gate may acquire freshly |

No `finally` block sets callback/gate success. `finally` only closes input,
drains bounded evidence, cancels/joins owned work and adds an explicit
incomplete fact when a positive latch was never reached.

## Proof plan

Build accepting and refusing tests together. The portable accepting path drives
the actual provider/handle/conversation with a scripted managed account while
substituting only the platform-bound guard/launcher primitive; it proves the
state machine and assertions on every platform. A separate Linux accepting path
uses the real launcher, contained WRITE worker, capture and unchanged contained
gate component. Assert the worker's exact change is the captured Git candidate,
the gate checked that candidate, each call ran once, every positive latch/check
completed, and every public outcome field remains within its declared bound.

Pair it with refusals for wrong posture/tool/grant/workspace/epoch/path;
experimental field used by READ; callback before the first account gate;
unknown/duplicate/late/foreign calls; malformed ids/arguments; all non-callback
server requests; worker timeout/exit/bounds; response loss; mode change before
acceptance; native EOF; capture rejection; red/cancelled gate; and closure or
cancellation at every await in the ledger. Seed private store/workspace facts in
both accepting and refusing wire records and walk the complete published
outcome to prove only the already documented legitimate turn-payload limit
survives.

The lifecycle lane proves: cancellation with an active worker joins native and
worker trees before closure; controller death leaves supervisors holding guards;
successor reconciliation disposes stale executor/workspace acquisitions without
PID replay; crash before checkpoint permits one fresh acquisition/call; and a
proposal checkpoint resumes with zero new native call, zero new callback and no
second capture. A fresh downstream gate acquisition is not counted as a model
call. Repeated close/cancellation preserves cleanup errors and disposition.

The real pinned binary's credential-free lane remains a positive *refusal* at
`account/read`; it cannot prove a model turn. Separate retained-pin mediation
evidence establishes that the binary can issue the exact dynamic callback, and
the production protocol fixtures establish accepting behavior. Report those as
distinct facts, never as one live authenticated proof. Linux Actions proves the
physical worker/capture/gate and owner-death paths with no credentials or vendor
network. Every new judgement gets an assertion-killed mutant; skipped or errored
mutants are not kills.

## Artifact path and authority ceiling

N2 can name all bytes needed by a future reviewed bundle: merged Constructicon
source/wheel, source-derived adapter/protocol/launcher revisions, runtime tree,
bubblewrap, AppArmor policy, pinned Codex binary and source, restricted catalog,
sealed configuration, process limits, and the existing store/egress identity
inputs. Current identities can bind the proposed bytes, but that never proves
the private host installed them or that the vendor client applied configuration;
those are later positive conformance gates. No host or artifact schema belongs
in N2.

Packaging, provenance verification, atomic installation, partial-install
recovery and the private-host runbook belong exclusively to
[#94](https://github.com/sushiHex/constructicon/issues/94). That path must consume
a reviewed merged artifact and never a PR checkout or CI root builder. Its
absence blocks private-host qualification and N4, not this credential-free N2
slice. N2 neither starts nor modifies the VM and does not claim that a digest
alone authorizes installation.

## Pre-implementation review questions

Independent review must answer these before code:

1. Does WRITE-only `experimentalApi` plus the exact outgoing-method and
   server-request closures mechanically exclude external-token/auth/config/
   process authority under ADR 0021? If not, implementation is blocked pending
   owner direction or a newly proved stable callback carrier.
2. Can any measured built-in, startup helper, MCP/plugin/skill/hook, approval,
   client-RPC or model-catalog path still mutate/read outside the admitted
   callback despite the restricted catalog and configuration?
3. At every await above, can close, recovery, buffered protocol state or a
   finished worker exist in a state that later code mistakes for positive
   acceptance?
4. Does the workspace concrete check and `use()` guard prove the callback is in
   the same invocation/epoch without introducing authority or a second ledger?
5. Do accepting-path tests observe every published field, while refusal tests
   prove no worker change is captured or attested?

Any negative answer stops implementation for design correction. A green gate,
an empty fault list, or an old mediation artifact is not approval.

## Independent review disposition

The focused source-based review found no owner-authority or design blocker after
one correction. It confirmed that the pin's `experimentalApi` boolean is scoped
to one client connection and gates annotated client fields; it performs no
authentication or network action itself. The exact constructor/classifier
closure, one connection/thread/turn and no resume therefore remain within the
accepted ADR 0021 callback scope.

The review found that a shared deadline cannot be inferred from `ProcessIO`:
`LinuxLauncher.exchange` creates its deadline internally and the conversation
otherwise receives only I/O. The explicit handle-computed absolute deadline
above is adopted. The same review confirmed `owned_view` plus the added
revision/grant/owner checks, required that native/store guards never enter the
worker, and retained the bounded no-effect deferral for a pre-turn-identity tool
request. Its required first pin fixture is the paired positive opt-in and
flag-absent pre-provider refusal already listed above. With those corrections,
the pre-code review gate is satisfied; all executable proofs remain prospective.
