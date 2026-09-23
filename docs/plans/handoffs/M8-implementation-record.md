# M8 implementation record

Status: PR A–D merged; ADR 0021 accepted on 2026-09-13; N1–N7 remain, with
N1 authorized as credential-free construction.

Authority: [accepted ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md)
and [frozen rev 1](../milestones/M8-live-executors-rev1.md). PR #26 merged as
`3ee1beb6a58fac0bab85841a1f34d96b514c3c34`, PR A's exact base. The merged
tree equals its reviewed head `8308cf8`. Approval does not provision Linux or
a gateway. Neither the frozen plan nor its planning evidence is edited here.
From 2026-09-13, accepted [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
and [frozen rev 3](../milestones/M8-live-executors-rev3.md) govern the
subscription route; see the dated section at the end of this record.

## PR A — contracts, coherence, and publication

The implementation adds no launcher, model adapter, credential handling,
gateway, Git lifecycle marker, or OS availability proof. Its production change
is the contract boundary; genuine fakes exercise its consumers.

- L0 owns one normalized finite `ExecutorGrantPolicy` and one pure itemized
  `ExecutorProfile.grant_faults`. Admission and the complete-policy fake call
  it. Historical `None` policy remains absent, not serialized as null, and
  the fake's default historical grant behavior remains unchanged.
- `ExecutorLaunchIdentity` binds executable/runtime, adapter/decoder, recipe,
  configuration, limits, complete single-posture profile, and optional
  `ProviderRouteIdentity`. Locators and credentials are not identity fields.
  The existing string capability revision is its canonical digest.
- The shared policy/identity source bodies contribute `EXECUTOR_LAW_REVISION`
  automatically, following the panel law's existing source-derived precedent.
  Backend factories still bind their own actual artifacts; they do not have
  to remember an additional manual policy-version stamp. Complete profile set
  serialization is normalized across process hash seeds; historical profile
  serialization is not rewritten.
- `ExecutorProvider` extends `LeasedCapability` with actual identity and cached
  unavailability reasons. `CapabilityDescriptor` compares profile canonical
  bytes and revision, checks kind/leased agreement, and refuses a provider
  hiding behind incomplete metadata. The same check serves assembly,
  admission, and description. No L2 filesystem or process probe is added.
- `SystemDescription` and its digest move to 3. Embedded Graph/admission stay
  1; manifests stay 2/3; SQLite stays 7. M7.1's published membership vocabulary
  remains unchanged. Strict version-2 readers refuse version 3.
- `Executor.execute` uses the existing `WorkspaceView | None`. One optional
  in-memory materialization callback extends `AcquiredCapability`; the walker
  awaits it after recording and cleanup enrollment. Resource identity is
  unchanged, and the existing checkpoint/disposition law decides cleanup.

The fake allocation ledger is explicitly a test instrument, not a new
Constructicon durable store. Reconstructed providers share it so local handle
state cannot stand in for a durable fence. Tests cover recording refusal,
never-started recovery, partial allocation, cancellation, earlier siblings,
ownership loss, and a new owner's fresh acquisition. A real control-plane
command and its RunHost also execute the complete fake through the lease.
InjectedCrash is a unit seam, not process-death or Linux containment evidence.

## Proof inventory and limits

The initial PR A head added 63 tests. Its 26-case mutation inventory in
`scripts/check_m8_mutations.py` independently removes grant checks, shared-law
and content identity, descriptor checks, availability, admission delegation,
record/materialize ordering, cleanup enrollment, inert-close discipline,
local reentry refusal, entry-before-await, and reconciliation of absence.
All 26 produced assertion failures on the implementation tested before review.
The posture assertion was tightened after its first mutant survived: the
isolation check alone was still refusing the request, so a generic "posture"
substring did not prove the selection check.

Mutation runners share one code-object instrument and never edit source files.
Its pytest hook distinguishes assertion failures from setup/collection errors,
unexpected exceptions, and harness timeouts. The M7.1 inventory now uses that
instrument too; its two description selectors follow the renamed test, its
baseline mutation selects the baseline block explicitly, and three assertions
name missing coordinates/incorrect pinned refusal instead of relying on an
incidental KeyError, StopIteration, or uncaught AdmissionError.

`scripts/check_m8_compatibility.py` exports the complete committed pre-M8
`src`, `tests`, and configuration into a disposable directory. Base and current
source both pass the seven-case compatibility suite: six exact manifest
goldens plus the empty-node refusal. Legacy fake profile bytes match exactly.
Both run with current interpreter/dependencies; this is not recreation of an
old dependency environment. The older provenance script additionally
reproduces seven historical endpoint manifests from `b5ff31f` and the empty-id
golden from `8262d4f`, using each historical validator with current dependencies.

Exact-head full-gate, CI, and independent-review results belong in the PR's
review record before readiness. A green baseline alone proves none of these
new laws; conversely, these contract tests prove no physical boundary.

## PR A review corrections

The independent review of `daf8577` reported two P1 lifecycle gaps. Both were
reproduced on that head before changing production code; the first regression
also demonstrated a cooperative cancel ignored during materialization.

1. A materializer can return normally after the heartbeat has observed that
   another owner claimed the run. The component was then invoked before its
   completion hit the journal fence. The existing `_check_run_control` now runs
   immediately after the await, before resource exposure. Tests pause a real
   materializer, expire/claim the actual run lease, wait for the actual heartbeat
   refusal, and require zero executor calls/checkpoints. The successor alone
   reconciles the old acquisition and completes under its fresh one. A
   cooperative cancellation at the same barrier must cancel, not succeed.
2. A second task cancellation could interrupt an enrolled acquisition's close.
   One `_finish_cleanup` mechanism now joins both unrecorded cleanup and the
   entire recorded batch, including each fenced journal transition. Shielding
   one resource at a time would still abandon siblings. The existing
   checkpoint/disposition law is unchanged: successful checkpoints retain
   release; unfinished work discards. An empty batch adds no scheduling point.
   Cleanup failure or ownership loss remains observable rather than being
   converted to cancellation or a false closed row.

`test_materialization_control.py` adds 12 barrier-based cases: observed
ownership/cooperative cancellation; repeated task cancellation during
materialization cleanup and post-checkpoint release; one or two acquisitions;
user cancellation versus shutdown abandonment; provider-close failure and
fenced-transition ownership loss followed by real successor reconciliation.
The last two queue cleanup completion before delivery of another cancellation,
proving the already-terminal cleanup result must still be observed. This
strengthening followed an initially surviving result-observation mutation;
ordinary await failure propagation had masked that separate guarantee.

The totals are 75 new PR A tests and 33 M8 mutations, all assertion-killed on
the corrected implementation. The seven new mutations remove post-await
control, recorded-batch shielding, shield isolation, repeated joining,
cancellation propagation, sibling coverage, and terminal failure observation
independently. Exact-head local/CI/review confirmation is recorded on PR #27;
these tests remain lifecycle proofs, not Linux process containment.

## Hosted-runner qualification — PR #28

PR #27 merged as `d5a8a94`. The owner selected standard GitHub Actions runners
instead of enabling virtualization on the Windows PC, then explicitly
authorized a scoped bubblewrap AppArmor profile on those disposable runners.
[Accepted ADR 0019](../../adr/0019-hosted-linux-runners-are-requalified-not-image-pinned.md)
separates the rolling host we observe from launch artifacts we control. That
evidence-location decision was accepted after PR #28 merged as `1b999be`:
the owner authorized PR B and its independent physical proof on these runners.
Accepted ADR 0018 and frozen rev 1 are unchanged; no PR B proof is inherited.

One credential-free workflow provisions a fixed Ubuntu bubblewrap package,
a non-sudo service account, and a reviewed profile attached only to a private,
root-owned executable copy. A separate non-root probe checks the exact kernel
profile stack, six namespace identities, service identity, read-only mount,
private loopback, missing host home/sysfs, reduced privileges, and refusal of
nested namespace creation and an unprofiled launch. Add-only loading,
absent-path guards, and unchanged global restrictions prevent silently replacing
policy. Nothing is installed on Windows or imported by Constructicon runtime.

The first two jobs refused because the host supplied no bubblewrap profile.
After operator authorization, the first profile loaded but its exec rule
requested an additional executable attachment search. The fixed named stack
removes that search entirely; it does not add an inheritance or unconfined
fallback. The next job launched with the expected enforcing stack and exposed
two incorrect probe assumptions: `--dev` uses an intermediate user namespace,
so the child map's parent-side zero is not host root; explicit AppArmor userns
denial reports EACCES rather than the global gate's possible EPERM. On this
kernel, the unprofiled copy creates namespaces but loses the capability needed
for loopback setup. Its refusal is recorded at that stage, not falsely at
namespace creation. The final checks name each operation and the pinned
mapping recipe.
Both corrections were traced to upstream source, not accepted merely to make
the probe pass. References and operation are in [the runbook](../../M8_CI.md).

The 52 portable tests and 20 assertion-killed mutations test the probe's
refusal logic, not Linux containment. Actual job links, image/commit evidence,
and exact-head gate results belong in PR #28. Its JSON always says
`runner_prerequisites_only` and `production_available: false`. The benign
diagnostic root borrows `/usr`; it is not PR B's pinned runtime. No hostile
process-tree cleanup, complete filesystem/FD exclusion, gateway, live model
call, or production availability is claimed by qualification.

## PR B — Linux containment and acquisition lifetime

The concrete networkless launcher, deferred READ/WRITE workspaces, permanent
Git closure marker, and retained acquisition guard merged in PR #30 as
`c39afe7033a259932dbf4110160501519b8710e0`, following PR #29 at `efe63c2`.
The merged tree matches reviewed head `ec43d128cfab417186afa72ae144396a46c88e7c`.
The trusted single-call subreaper keeps guard descriptors outside the payload's
PID namespace until its children are reaped; neither a Python controller's
death nor the bubblewrap monitor's return proves quiescence by itself.

The runtime is a curated immutable closure, not a mount of the host's `/usr`.
Provisioning moved from `/opt` to `/var/lib` after a hosted image's world-writable
`/opt` correctly failed the ancestor check. No check or host directory mode was
weakened to accommodate it. The service has no sudo or provider credentials.

An early independent review identified four concrete corrections: install the
supervisor source in that immutable closure; separate the 16 MiB artifact bound
from the 1 MiB task-input bound; include availability and spawn in the call's
deadline and elapsed observation; and keep deletion off the event loop while
retaining the acquisition guard through repeated cancellation and completion.
The Git export also drains after stopping its producer, so a full pipe cannot
strand bounded materialization cleanup. Bulk filesystem work and fixed
trusted-authority metadata calls use joined worker threads, never a legacy
Git importer or verifier.

The existing owner pipe now authorizes start only after the controller owns
the real spawn handle, then witnesses controller lifetime. A setup child
retains the acquisition guard while waiting; death before that authorization
cannot start a payload. The reaper also receives the remaining deadline in
the shared monotonic clock. It enforces expiry independently of asyncio,
including when the controller's event loop is stalled. Elapsed observation
includes setup and joined cleanup; expired cleanup cannot report success.
Shutdown gives the workload the plan's two-second TERM grace before forced
teardown. No additional backend authority is granted during cleanup. One
process-lifetime chain retains the guards until quiescence; it adds no graph
scheduler, persistent PID ledger, or journal phase.

The runtime digest and retained inventory use one projection. Symlinks cannot
reach executable content outside that immutable closure. The physical proof
records six namespaces, single-ID UID/GID maps, exact minimal devices,
no-new-privileges, zero effective capabilities, process limits, private mounts,
an allowlisted environment, and only standard payload descriptors. The pinned
bubblewrap emits `/dev/core` as a legacy `/proc/kcore` alias; the assertion
requires that exact link and proves opening it is denied, rather than claiming
the name is absent. No kernel memory is read by this test.

Native regressions cover READ refusal, WRITE confinement, host file/socket/FD
exclusion, private network, hostile detached descendants and held pipes,
timeouts, repeated cancellation, controller death during setup and execution,
and real control-plane deaths before recording, after recording, and during
materialization. Recovery proves exact closure and epoch separation. A
recorded-subprocess Executor double exercises the same task, grant, lease,
workspace and outcome contracts without a provider request.

The required CI lane uses the actual non-sudo service user. Its artifacts retain
the exact runtime inventory/digest, bubblewrap and AppArmor policy/ABI digests,
commit, observed runner/kernel/service facts, and the child boundary projection.
They contain no host environment dump or credentials and expire after seven
days. [The runbook](../../M8_CI.md) distinguishes this from qualification.
Windows skips remain explicitly not physical evidence. Exact-head local/CI,
mutation, compatibility and independent-review results are recorded on PR #30
before readiness, not inferred from the implementation's existence.

### Mutation coverage and independent defensive strength

The native inventory removes READ mount protection, network isolation,
workspace mount selection, runtime link containment, deadline transfer,
start ordering, elapsed accounting, export bounds, permanent-closure checks,
literal sentinel semantics, the closure transaction, physical serialization,
revocation-before-wait ordering, and deletion cancellation/loop discipline.
Network/visibility payloads additionally test the recipe directly after
artifact validation, so an availability refusal cannot masquerade as proof
that an attempted escape was physically stopped. Only assertion failures
count; setup errors and harness timeouts do not.

Some checks are intentionally redundant and are not independently credited:
the controller's spawn timeout is now backed by the reaper's transferred
deadline; post-wait local view checks are backed by the durable closure check;
and bubblewrap's parent-death mechanism is backed by the external reaper's
exact-child termination. In-memory controller mutations do not modify the
installed immutable reaper. Its descendant-reap and inherited-guard code is
proved by actual stopped-reaper/controller-death experiments, not falsely
claimed as independently mutation-killed source. Killing the trusted reaper
itself, kernel compromise, and aggregate multi-tenant resource isolation are
not promised. Per-process limits do not establish a tenant-wide quota.

### PR B confirming-review corrections

Review of `78d83c8` found three additional defects. A start byte buffered before
owner death arrived as `POLLIN | POLLHUP`; consuming the byte discarded the
observed death. The supervisor now refuses HUP/ERR before process creation.
A native fork test inherits the actual function and observes whether Popen
is reached with a real buffered-and-closed pipe. Its code-object mutation
discriminates that branch without racing a payload against its later kill.
This is a native owner-pipe law proof, not a rewrite of the installed reaper.

The recorded double now captures and checks the exact program against its
admitted configuration digest after acquiring both guards; the same local
string enters the command. Launch-revision checking also occurs after the
workspace wait. A changed recording cannot run behind an old identity. The
decoder counts actual malformed/contradictory records separately from a byte
bound or missing terminal result: those conditions alone invent no malformed
record. Dedicated regressions and three additional mutations cover these
corrections. Final exact-head confirmation remains the PR's gate.

Review of `999fe7e` found that availability still transferred its independent
ten-second deadline to the reaper and that launcher fields could be reloaded
across the probe await. The launch configuration is now one frozen value;
reconfiguration creates a new value, never changes an admitted call midway.
Identity-bearing changes also change its revision; relocating identical
artifacts does not. Each configurable field has a refusal test. Immutability is
the standard dataclass contract, not an independently mutated custom guard.
`run` passes its deadline through `probe` to that same reaper. Standalone
qualification alone supplies a default deadline. A native probe emits its
actual namespace observation, then stalls; a pidfd proves its reaper exits
on the caller deadline even while the controller event loop is blocked.
Removing the deadline transfer is a separate native mutation. Expiry is
reported as timeout rather than as an unrelated prerequisite failure.

Review of `b8256a6` found synchronous runtime hashing before the probe's first
await. Artifact verification now uses the existing owned-work join around a
read-only worker thread. Heartbeats and cancellation remain deliverable while
storage is busy. Expiry or repeated cancellation joins that worker before
returning and cannot start a probe or payload afterward. This is not a hard
wall-clock bound on a stalled host filesystem: joining an in-progress read is
cleanup latency, not additional authorized execution. A portable barrier test
proves both responsiveness and ownership; moving hashing back onto the loop
or abandoning the worker on cancellation is independently assertion-killed.
Native tests continue to validate the actual artifacts and launch recipe.

Review of `e97f762` identified the same event-loop hazard in READ archive
extraction. Extraction now joins its filesystem worker before releasing the
acquisition guard, including repeated cancellation. A native barrier proves
that the loop stays responsive, another guard holder cannot enter early, and
the actual archive writes finish before the cancelled materializer returns.
Synchronous extraction and an unjoined worker are separate mutations.

The same audit covered the newly introduced trusted metadata boundaries:
base-ref resolution, guarded closure checks at materialization/use, and the
closure-marker transaction. They now join off-loop work as well. Revocation
still commits before waiting for the guard; a cancellation during that write
can leave a closed, unreconciled acquisition for retry, never false disposal.
The four boundary cases each test responsiveness and repeated-cancellation
ownership, with one mutation for each guarantee. These fixed, bounded Git
plumbing calls operate only on the trusted authority. No hostile staging
importer or gate verifier is wrapped in a thread, and no legacy API changes.
Small fixed-count guard/path syscalls remain synchronous; repository-sized
processing and subprocess waits do not run on the event loop.

Review of `f9236c7` rejected the recorded immediate-KILL deviation from the
frozen shutdown default. TERM must reach the workload, not bubblewrap's
monitor: the pinned monitor's parent-death behavior otherwise kills namespace
init before a cooperative child can flush. A small trusted PID-1 shim now
replaces bubblewrap's built-in init. The external reaper retains the guards;
one private lifetime socket links it to the shim, which inherits neither guard
nor controller pipe. The shim closes private descriptors in the actual child
and disables dumpability so that child cannot inspect its descriptors/memory.
Both roles reuse one reaping loop and one non-renewable two-second shutdown
state. Namespace-wide TERM/KILL is guarded by the private-PID-1 precondition;
the external fallback still signals only exact children through pidfds.
See the pinned [bubblewrap implementation](https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c).

Native tests require cooperative output flushing on timeout, cancellation and
output-bound teardown, bounded escalation for TERM-ignoring work, descriptor
privacy, and the existing descendant/owner-death proofs. Portable policy tests
independently mutation-check grace duration, non-renewal, TERM/KILL selection,
and the PID guard. These policy mutants do not rewrite installed immutable
code; actual signal delivery and cleanup remain mandatory native proofs.

The first grace-enabled native run passed all 112 tests but exposed one
surviving elapsed-time mutant: a slower payload alone could satisfy the old
absolute threshold. The test now observes the real probe and payload spans
separately and requires the returned total to include both. No launch result
or OS observation is fabricated, and the threshold is not merely increased.

Review of `ab6daf8` found that the external fallback started its grace before
namespace init delivered TERM. Stop requests now carry no grace timestamp.
The private socket's write-half closure requests shutdown; trusted PID 1
acknowledges the actual TERM send time in one atomic record. Both reapers use
that same timestamp, and repeated requests or acknowledgements never renew it.
The payload inherits no endpoint and cannot inspect init's private descriptors.
Without acknowledgement the external reaper neither invents a clock nor
releases guards over living descendants. A stalled trusted init can delay
cleanup; it cannot turn missing evidence into quiescence.

A native regression stops the exact namespace init through a pidfd, cancels
the call, and waits beyond the old fallback window. Init must remain alive and
the acquisition guard held. After continuation, the real TERM handler takes
one second to flush successfully before teardown. The portable shutdown-law
test also delays acknowledgement and independently kills a mutation that
starts grace at request time. The native fixture, not that policy mutation,
proves the installed immutable reapers exchange the timestamp correctly.

### Post-merge correction: deterministic spawn-order evidence

The README wording correction in PR #32 (`d35ae85`) exposed a gap in the existing
mutation proof. All 113 native tests passed, but `payload start before spawn
ownership` survived: the test sampled a workspace marker after 300 ms, so
slow process startup could hide an already-authorized payload. Neither the
launcher nor the mutation had changed in that PR.

The corrected test records the real owner-pipe writes and native spawn-handle
returns. Device/inode identity joins each writer to the inherited read end;
reused descriptor numbers cannot confuse the probe with the workload. Both
operations still call the OS unchanged. Assertions run after the real workload
completes and cleanup joins. For each native handle, the first successful start
write must follow handoff: a later lawful duplicate cannot hide an early write,
and duplicate counting cannot substitute for the ordering proof.

Two payloads exercise the same assertion. One writes directly; the other waits
for stdin, which the controller supplies only after handle return. The latter
deliberately hides the file effect of premature authorization, so marker
absence cannot be credited as evidence. No fixed observation delay, mocked OS
return, or production protocol change is used. This proves controller-side
authorization ordering; the unmodified native reaper and lifetime tests remain
responsible for enforcement and cleanup. Windows skips are not native evidence;
exact-head Linux and mutation results belong in the follow-up PR.

### Backend extensibility and subscription intent

The owner reaffirmed that Claude Code, Codex, and Pi are the starting adapters,
with future cloud and local models using the same task-shaped executor seam.
This follows ADR 0005: API models enter through a compatible harness, not a
completion-level provider abstraction in the kernel. No CLI-specific base
class, provider enum, model switch in the walker, or alternate workspace
contract is required by this launcher. Adapter profiles and launch identity
continue to state exactly what is supported and enforced.

The owner's primary solo-developer motivation includes subscription reuse.
That intent does not establish a working or authorized authentication route:
accepted ADR 0018 still requires gateway-only initial authentication. Resolving
subscription-backed access is an explicit prerequisite decision before the
live Claude Code/Codex slices, not something PR B claims or silently enables.
The [authentication feasibility record](../../designs/EXECUTOR_AUTHENTICATION.md)
separates documented native CLI login from credential intermediation. It
now links the owner-authorized
[native-authentication investigation](M8-native-auth-feasibility.md): pinned
Hardline source, published CLI interfaces, and credential-free Codex schema
generation. These establish possible integration points, not complete native
tool mediation or subscription availability. The proposed next experiment
keeps scripted driver proof separate from actual native CLI proof. No successor
ADR, credential access, or changed authentication policy follows from it.
That prerequisite decision was made on 2026-09-13; see the ADR 0021 section
at the end of this record.

## PR C — safe async WRITE capture (merged as #34)

The new `AsyncWriteWorkspace` has an explicitly awaiting consumer and a
controllable fake. `workspace.contained` uses the existing acquisition,
launcher, and Git authority. Legacy synchronous capture remains unchanged.
Mutable staging Git executes inside the launcher, followed by a separate READ
export. A fresh acquisition-owned quarantine validates immutable pack bytes
before trusted import; only the exact candidate OID is published.

Publication and disposition extend the existing closure transaction, including
the candidate-absence comparison. No SQLite schema, scheduler, or installation
path changes. The physical guard ends only after import and quarantine cleanup;
publication needs no payload path and is fenced by the Git transaction itself.
`LeaseContext.check_control` exposes the walker's existing in-memory control
check before publication, not a second ownership law or an atomic SQLite/Git
transaction. New WRITE process assemblies refuse legacy capture/gate resources,
including relabeled instances. No live provider is enabled by this slice.

The explicit revision is a string, as the manifest requires. It binds the
provider's source closure, installed trusted Git, launcher, object format,
target ref and limits. Portable admission tests exercise that real descriptor
without materializing anything. New awaiting component definitions enter the
normal canonical registration path; no retained component is rewritten.

The native lane exercises hostile hooks, includes, filters, fsmonitor,
credential helpers, alternates, symlinked Git metadata and stale locks;
detached capture writers; a physically READ-only export; reset after hostile
metadata; and repeated cancellation. Actual child processes run through the
production launcher, not substituted OS results. Quarantine Git also inherits
fixed Linux address-space/file/CPU limits before parsing compressed objects.
Its exact open guard survives the Python owner's death, so recovery cannot
delete an import root while that child still owns it.

Public-control tests cover capture and counterfactual discard, plus literal
controller death during import, after publication and after checkpointing.
The late-publisher barrier is after the local control and literal marker reads:
the successor finishes discard before the old host attempts its Git
transaction and is killed. The reverse order preserves the existing
checkpoint-selected release/discard law. Portable tests separately pin both
atomic absence comparisons, closure response loss, SHA-1/SHA-256 handoffs,
malformed/oversized packs, missing history and exact OID/type checks. The
controllable fake proves that the walker awaits capture before checkpointing.

### PR C review corrections and scope

The first independent review found permanent authority `.keep` files after
import. Removed them rather than adding a second recovery inventory. Verified
objects may await publication without becoming immortal: normal Git GC can
reclaim unreferenced imports, and Git refuses a ref transaction if an external
prune removed its target first. A real-Git test pins reclaimability. Mutable
buffers are refused at the handoff, preventing verification/import drift.

The next review found a real identity gap: the provider pinned one Git binary,
but authority ref operations still looked up bare `git` through current PATH.
`GitAuthority` now owns one resolved executable and checks its content before
use; the contained provider reads that same fact instead of discovering or
retaining a second locator. PATH changes cannot redirect candidate/closure
operations or snapshot export, and a changed executable refuses. The new
regressions and mutants pin all three boundaries. Historical Git values and
call conventions do not change.

The follow-up check/use review exposed an unsupported input that was not yet
refused: a service-replaceable host Git installation. Contained providers now
reuse the launcher's exact fixed-artifact check for Git and its ancestors;
even a mode-0555 tool owned by the service is not immutable. The shared check
keeps its existing behavior and messages. Historical authorities still accept
operator-supplied Git; they are not silently relabeled as contained.
Privileged operators must not replace a live world's installed tools. Racing
such a replacement is outside the same fixed-runtime assumption used by B,
not a guarantee supplied by executing a pathname or by an open descriptor.
No new cross-platform execution mechanism or process owner is introduced.

The confirming pass found the companion bootstrap gap: the resource-limit
trampoline still selected the application's possibly service-writable Python.
It now uses fixed system Python on Linux through the same artifact predicate,
and the capture revision binds those interpreter bytes. The application venv
is not a trusted subprocess locator. A native shim proves replacement of that
locator cannot execute, while a separate identity mutation proves interpreter
content is not omitted from the sealed revision. Windows does not use this
trampoline and retains its existing path.

The next review found a root-container test assumption, not another execution
gap. The service-owned-artifact proof now explicitly requires a non-root
service user: root-owned test copies exercise a different ancestor refusal.
Root development containers skip this ownership proof; the mandatory native
lane runs both cases as its real non-root service account.

A native rerun also exposed a weak existing guard proof: a metadata thread
could leave reconciliation unfinished even when locking was removed. The
test now opens a second file description and requires the actual kernel lock
to refuse it while the producer holds its guard, before testing revocation.
No added delay or production change substitutes for that exclusion proof.

The same review proposed requiring both contained workspace and gate instances
in every WRITE provider assembly. That broader rule was not adopted: accepted
ADR 0018 refuses legacy capture/uncontained gate bindings, which assembly now
enforces, but PR C defines no production live provider. Requiring a PR D gate
to instantiate the credential-free capture-only double would add an invented
gate or collapse the approved slice sequence. Such a graph does not run checks
or install its candidate. D/E remain prerequisites for the live F/G/H
factories; this scope reading is explicitly included in the confirming review.

Pre-M8 compatibility was reproduced against full base
`3ee1beb6a58fac0bab85841a1f34d96b514c3c34`: seven checks pass in both trees;
the historical fake profile and six manifest goldens are byte-identical.
Exact-head native/mutation/local/CI results and the confirming review remain
acceptance gates in PR #34; Windows skips are not physical evidence.

## PR D — contained async gates (merged as #35)

Started from PR C's squash merge `04c7b19`. L0 owns the explicit async
`MergeGate` and the unchanged `MergeEvaluation`, re-exported at its historical
import path. The contained provider and a controllable fake use the same
awaiting component through ordinary registration, admission, and execution.

Runtime identification has no candidate mount and finishes before publishing
the check-set identity. Verification uses the existing authority merge law at
the current target, an acquisition-owned exported snapshot, and the existing
READ-only networkless Linux launcher. The candidate never supplies runtime
identity. Anonymous assembly descriptors allocate no persistent lease. Private
gate recovery references carry the provider, acquisition, normalized storage
locator and closure repository, never a base; host locators do not enter the
portable runtime digest.

Trusted metadata and filesystem workers are joined, not a wrapped legacy
verifier. The bound operation observes the existing invocation control callback
while checks run and before minting. Cleanup completes before authority. The
same Git closure and physical guard fence late use and successor disposal.
The new snapshot proof also compares exported blobs and modes with the prepared
Git tree: archive attributes cannot hide or substitute the bytes being tested.
Lossy exports and unsupported gitlinks refuse; legacy gate behavior is unchanged.

PR #35 merged on 2026-09-10 as `882871ba7698508878c467ddd700c8db1d1a1edf`.
Its tree is identical to reviewed head
`f1ec0ab0fcbccd0cc8666540c9a69874088c870e`. On that head, the local gate passed
1,785 tests with 145 expected Windows skips; [standard CI](https://github.com/sushiHex/constructicon/actions/runs/34469665363)
passed 1,833 with 97 skips; the [native Linux lane](https://github.com/sushiHex/constructicon/actions/runs/34469665386)
passed 268 and killed all 91 B/C/D mutants. Seven compatibility checks passed
against the full pre-M8 base; the legacy profile and six manifests remained
byte-identical. The [independent exact-head review](https://github.com/sushiHex/constructicon/pull/35#issuecomment-5617881708)
reported no new findings, and all four review threads were resolved before
merge. The [final handoff](https://github.com/sushiHex/constructicon/pull/35#issuecomment-5618008046)
records the complete gate. Windows skips are not credited as physical evidence;
none of these results proves a provider route or live model adapter.

### PR D review corrections

The first independent review found three introduced gaps. Assembly now proves
that a contained gate and the real merge effect share the exact journal and
authority objects. The effect also refuses a subject for another repository
before execution, reconciliation or simulation: mirrored Git objects confer no
authority over a different repository. The positive public-control lane runs
the contained gate and installs its exact attested subject through the effect.

Recovery previously selected its guard from the current configured root. A
changed root could falsely report an old acquisition reaped while its payload
and guard remained elsewhere. The private durable reference now pins that
locator and refuses a mismatched restart before closure or disposal. The
original root still recovers normally. Independent design adjudication accepted
the private locator and identified its companion fence: the closure repository
is privately pinned too, and the complete stale batch is validated before any
physical effect. Close already uses the provider-minted handle's original paths,
not a reconstructed route. No new ledger or path-dependent launch identity is
introduced. Relocating live acquisition storage, or rebinding an unchanged host
pathname to different storage, is not supported by this trusted deployment.

The confirming review found one remaining ambiguity: legacy `GitAuthority`
accepts relative repository paths, so two service working directories can give
different repositories the same `repository_id`. The new contained gate now
requires a canonical absolute authority locator before qualification. It refuses
relative paths and symlink aliases rather than silently rewriting historical
merge subjects or changing the legacy constructor. The regression constructs
both working-directory worlds; the native companion covers an absolute alias.

Exit codes 125--127 are valid check exits, not evidence that setup failed. The
trusted namespace reaper now reports the actual payload exit through its
existing private control socket and an anonymous report pipe owned by the
launcher. Repository code inherits neither descriptor. Missing or contradictory
exit evidence is an infrastructure failure; a completed nonzero check is a
check failure, including 125--127. This extends the shared launcher observation
instead of inventing a gate-specific child supervisor. All existing B/C proofs
and inventories must pass again alongside the new D regressions.

## Remaining slices and operator prerequisites

PR B completed its physical proofs under the actual Linux service account and
pinned containment policy on GitHub Actions. Its final head passed the local
gate (1,699 passed, 72 skipped), CI gate (1,720 passed, 51 skipped), native lane
(113 passed), and mutation inventory (42 killed); confirming review reported
no actionable findings. These are PR B evidence, not proof of a native model
adapter or gateway. Hosted-runner qualification alone still supplies only
prerequisite evidence. The Windows machine remains unchanged; no gateway,
secret access, paid request, or account login has been authorized.

Capture and contained gates are now merged. Under the accepted plan, E remains
selected gateway integration and deployment-specific conformance; F/G/H remain
Claude Code, Codex, then Pi and integrated closeout. The native-authentication
investigation has not superseded ADR 0018. Current sequencing, the owner decision,
and completion criteria live in the [M8 milestone](https://github.com/sushiHex/constructicon/milestone/1),
under the repository's [issue-first workflow](../../WORK_TRACKING.md).
No live WRITE profile is enabled before routed authority and its adapter are
also proved. Public model contracts and completed containment slices are not
substitutes for those proofs. This sequencing was superseded on 2026-09-13
by the ADR 0021 acceptance recorded at the end of this record.

## Native mediation and OpenRouter investigation

The [credential-free Linux probe](M8-native-mediation-probe.md) follows the
earlier Windows/interface feasibility record without rewriting it. It exercises
the native app-server against a loopback fake, reuses the contained worker and
existing acquisition cleanup, and inventories native tools separately from
client RPCs. Its observations do not qualify subscription authentication or
complete slice E. The enabled-image control exports the PNG fixture without a
worker callback; the disabled-image configuration removes the reader and
refuses its direct invocation. The probe record preserves both results and
their exact-head evidence, leaving broader mediation and lifecycle proof open.
The PR #49 follow-up measures two real pinned model profiles as well. Both
execute native patch writes in the disposable harness home despite the
requested disabled flag, without dispatching the contained worker. The bounded
matrix distinguishes this failed mediation obligation from passing controls
and unmeasured startup/restart surfaces. No native credential-bearing profile
is qualified, and no successor ADR follows from these results. The
[authentication packet](../../designs/EXECUTOR_AUTHENTICATION.md#bounded-decision-packet-pr-49)
returns the concrete route choice to the owner; it does not select paid API
usage as a substitute for subscriptions.
PR #50 tests the explicitly authorized controlled-catalog hypothesis. With
three tool selectors changed on the same two model entries, native patch is
refused and Sol's CodeMode/collaboration surface disappears; the unchanged
catalog remains the positive control. Driver SIGKILL, explicit lease-provider
reconciliation, and a fresh native invocation are tested separately from
manual cleanup. This is not RunHost/journal recovery or ownership of the native
home and all descendants. The
[follow-up evidence](M8-native-mediation-probe.md#controlled-catalog-experiment-pr-50)
keeps those remaining obligations explicit; ADR 0018 and live-profile
availability are unchanged.
The [OpenRouter assessment](../../designs/OPENROUTER.md)
proposes configuration of the planned Pi harness rather than another executor
or kernel abstraction. The follow-on scope is two explicit qualified models,
no automatic fallback, and separate Pi/authentication prerequisites. It is
not an approved expansion of M8 or a completed Pi integration.

## Bounded duplex transport: merged

The owner authorized steps 1-4 on 2026-09-11: merge PR #51, design the bounded
transport, implement it after review, and resume only qualified native work.
PR #51 merged as `ddad9f07f13b64bffd84476b3d7999d373b2ac7f`, tree-identical
to reviewed `3b1b840c6844728ccd22811b568ce328b28e7cfb`.

Under that delegation this session accepts the
[bounded duplex contract](M8-bounded-duplex-contract.md) at reviewed head
`28714ce3dbf644ee498dfb402d65f2e0d02be272`. Three independent contract-review
rounds closed short-read progress, deterministic failure outcomes, and
shutdown-induced I/O precedence; the final pass reported no major issues.
The reviewed contract remains byte-identical, including its historical
proposed status; this record carries acceptance, not an invented owner review
of its exact bytes. No ADR 0018 clause, authentication route, or network policy
is changed by this transport scope.

Contract PR #52 merged as `eaa0894f6af6b2c70fae415f8faea2dde7643307` and
implementation PR #53 as `6d6379c56bc1dd44a6f32f82b00efefbefdbe939`.
Both merged trees equal their reviewed heads. The implementation was rebased
without changing any of its six patches or its complete tree. Fresh proof on
`159f4595bee8988840cc775063deef3befeb239e` passed: local verify 1,852 tests
(262 Windows skips), CI verify 1,900 (214 skips), Linux containment 324,
native mediation 87, and all 132 assertion mutants. The final independent
review found no major issues; all prior threads were resolved. The downloaded
native artifact independently matched the head, challenge transcripts,
outcomes, and launch identity. These are transport proofs, not complete
native startup or journal-driven qualification.

The implementation reuses the existing launch owner and one bounded capture.
The first independent code review (head `548a67b`) found five failure-law gaps:
cancellation coinciding with a failed join or spawn, settled write failures
misclassified by a later stop, discarded read errors, and private-report
corruption hiding a callback error. The follow-up keeps actual cancellation
objects in the existing `finish_owned` helper, groups concurrent failures,
arbitrates writes against their owned operation's completion, and retains
read/report failures. The launch identity now binds the helper source too.
Self-review additionally made stop idempotent so callback cleanup receives
one cancellation, not repeated interruptions. New native regressions and
assertion mutants are required to confirm these corrections; the previous
303-test Linux pass did not satisfy the complete mutation gate because an
older mutation anchor no longer matched uniquely.

The final correction separated waiting for owned completion from retrieving
the owned result. That preserves pre-entry caller cancellation even when the
owned task self-cancels immediately, without inferring the source of a
cancellation from counters. Regressions cover immediate/delayed self-cancel,
completed failures, and repeated caller cancellation.

The [controlled-startup investigation](M8-controlled-startup-evidence.md)
continues #37 under the existing networkless recipe. It records its own
evidence and provider-connectivity gap; it cannot borrow transport success
as a claim of native authentication or durable recovery.

## Authentication route decided: ADR 0021 accepted (2026-09-13)

The owner accepted [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
and [rev 3](../milestones/M8-live-executors-rev3.md) as written at reviewed
head `e228ef8535bceb316bdbfd3c309066befa9f67f0` (merged as
`9e55364f8cb8261eb50678936fd9170c00c83cf1` in PR #72), in the
[decision record on issue #38](https://github.com/sushiHex/constructicon/issues/38#issuecomment-5651362966).
ADR 0021 supersedes ADR 0018 only for the explicit v3 profile; gateway v1
bytes, semantics and source-law revision are unchanged, and ADR 0019 still
governs hosted Linux evidence. ADR 0020 and rev 2 remain proposed, neither
accepted nor rejected; ADR 0020's proposed description-4 allocation is
retired in favour of ADR 0021's.

On the same day, rev 2 section 6's proposed transition was applied with ADR
0021/v3 as authority: #41 was re-scoped to Codex N1–N5 with one sub-issue
per slice (#74–#78), #40 to independent Claude Code qualification N6, #42
retains Pi and integrated closure N7, #39 remains the unselected, separately
billed gateway option, and #73 (M8-D2) was opened for the private qualified
Linux deployment decision that N4 needs. No issue closed as a result of the
proposal. Current readiness, dependencies and ownership live in GitHub
Issues under the [issue-first workflow](../../WORK_TRACKING.md), not here.

What acceptance authorizes: N1, credential-free construction of the strict
operator-mode contracts, the v1/v3 boundary decoders, one pure grant
predicate, `SystemDescription` 4 and complete fake providers, with v1 goldens
reproduced from `d2b8f94` in an independent worktree. What it does not
authorize: credentials, account inspection, login, authenticated startup, a
Linux deployment, model or provider calls, provisioning, or any live
READ/WRITE profile. N4 and N5 each require separate explicit operator
authorization per provider. No implementation had started when this section
was recorded; N1's evidence follows.

## N1 — strict operator-mode contracts (#74)

N1 implements rev 3's first slice under accepted ADR 0021; its PR and merge
identifiers are recorded on #74. One new L0 module, `core.native_operator`,
holds the six strict records (`NativeOperatorGrantPolicyV3`,
`NativeOperatorIsolationProfileV3`, `NativeOperatorExecutorProfileV3`,
`NativeEgressIdentityV1`, `NativeOperatorStoreIdentityV1` and
`NativeOperatorLaunchIdentityV3`, whose revision uses the domain
`executor-native-operator-launch` version 3), the operator-binding digest, the
source-derived v3 law revision, and the two boundary decoders that dispatch
on the raw `schema_version` outside the v1 source-law closure: absent selects
the unversioned `ExecutorProfile`, exact 3 the native record, every other
value refuses; schema 2 is reserved and refused; a failed v3 parse never
falls through; and a schema-1 launch identity refuses a nested profile that
carries any `schema_version`, because the v1 profile ignores extra keys. One
pure predicate, `NativeOperatorExecutorProfileV3.grant_faults`, serves
admission and the adapter: exact posture, exact tool set, an explicit listed
effort, an explicit model from the finite inventory and `network="allow"`;
`network="none"` is refused because it excludes model networking.

`SystemDescription` is version 4 with digest domain 4: `executor_profile` is
the explicit v1/v3 union and each capability publishes `unavailable_reasons`
beside `available`, with a validator refusing any record in which the two
disagree; strict version-3 readers refuse the document. Graph,
admission, manifest and SQLite schemas are unchanged. The assembly WRITE
guard reads postures through `offered_postures`, so a v3 provider is checked
by the same rule as v1; the capture mutation anchor moved with it.

Preserved: the v1 legacy and complete profile bytes, the v1 launch-identity
bytes and revision, and `EXECUTOR_LAW_REVISION`
(`sha256:8da4745822d8915145e417f86273006010d66089b0fa0e8157a03e5c5c473f9b`)
equal the goldens captured from a detached worktree at `d2b8f94`;
`scripts/check_m8_native_operator_compatibility.py` reproduces all five from
a base export on every run. Complete fakes (`FakeNativeOperatorExecutor` and
the test-world `FakeNativeOperatorProvider`) exercise the same contract
without publishing production availability: private fixed-actor ingress is
an assembly constructor fact whose absence makes the provider unavailable;
two providers with different private vendor labels publish identical
identities and a description with no principal-like field; a new maintenance
generation changes the store identity and revision while a simulated refresh
does not; overage `forbidden` and `operator_authorized` are distinct sealed
profiles that no grant can select.

Evidence: local gate 2,111 passed, 358 skipped at the code head; 24 of 24
assertion mutants killed by `scripts/check_m8_native_operator_mutations.py`,
with the touched anchors in the capture, M8 and M7.1 suites re-checked; the
compatibility script identical at `d2b8f94` and the working tree. The design
was cross-reviewed before implementation; two redlines (the WRITE guard and
the hybrid-profile refusal) were adopted. An independent review of the
implementation found no blocking defect; its smaller items (the agreement
validator, a guard test, the vendor-label scan, decoder guard inputs and one
message) were folded in before merge, and its remaining observations are
recorded on #74 for N2. No native process, provider connection, credential,
deployment or live profile exists; N2 (#75) is the next slice.

## N2 — the Codex operator adapter, READ posture (#75)

N2's first slice binds ADR 0021's operator-bound route to a real contained
process for the READ posture. Two new L1 modules carry it. All of the
interesting judgement lives in `substrate.executors.codex_protocol`, which
performs no I/O and imports no launcher: process facts arrive through a
structural `ProcessFacts` protocol, so framing, the subscription-mode gate, the
turn fold and the decoder are provable on any platform with zero credentials
(I7). Its two consumers are the adapter and the protocol tests (I6).
`substrate.executors.codex` is the thin binding to `LinuxLauncher.exchange`:
one task, one acquisition, one contained conversation, with no persistent agent
service, no second controller and no scheduler.

The conversation is strictly sequential per direction — `initialize`,
`initialized`, `account/read`, `thread/start`, `turn/start`, records to a
terminal `turn/completed`, `account/read`, then stdin close and a drain to EOF.
Either reading faulting yields an unavailable failure naming the faults, and a
faulting pre-acceptance reading discards an otherwise successful turn. That is
ADR 0021's "refuses availability/result acceptance": the turn's output, its
served model and its transcript do not survive into the outcome, and the single
truthful fact that a turn ran is reported once through `produced_output`.

**The gate's completion is a positive record, not an inference.** The first
implementation read "the gate cleared" from the fault list being empty, and
empty had a second meaning: the conversation was aborted before it could record
anything. A `RecursionError` from a few thousand nested arrays — 8 KB, well
inside the record ceiling — is neither a `ValueError` nor a `UnicodeError`, so
it escaped every parse site; the conversation's `finally` had already closed
stdin and drained, so the child exited cleanly and the handle published
`ExecutorSuccess` carrying a turn whose pre-acceptance reading never ran. The
repair is `gate_completed`, set only after the pre-acceptance comparison, with
an explicit fault stated in the `finally` when it was not. One `parse_record`
helper now names the bounded decoder-failure set once across four call sites;
the fourth, `is_terminal_record`, was found late and raised the same way.

What this establishes is narrower than exhaustiveness and is worth stating in
those terms. `asyncio.CancelledError` escapes by design, a `ProcessIO` raising
outside `(ContractViolation, OSError)` escapes the reader, `MemoryError` and its
siblings are uncatchable without `except BaseException`, and `json.dumps` would
raise on a non-serializable payload no current builder can produce. The claim
that holds is that **an escape can no longer publish a result**, because the
`finally` runs on every one of those paths and leaves the fault list non-empty.

**What the gate does and does not establish.** The supported observation is
`account/read`. It reads a process-global credential cache and never reloads,
so the second reading is not proof that anything was re-observed; it is
load-bearing against a change that did occur, because a switch to an API key,
to Bedrock keys or to provider headers changes the reported account shape and
the pre-acceptance reading then refuses the result. Four pinned ChatGPT
credential variants collapse onto one account shape, so the gate is silent
about which is in use. That is covered by the published
`operator_bound_vendor_identity_unverified` literal and recorded in
`M8-subscription-mode-interface-screen.md`; the deprecated operation that would
name the variant is excluded as a boundary in either direction. The expected
account is an assembly fact, never caller input, and its plan is required: the
pinned plan type is an untagged union with a known `free` member, so an
accept-any default would admit a free plan as a vendor-managed subscription.

**Three exclusions are structural rather than conventional.** `initialize`
never sets `capabilities.experimentalApi`, which is what enables the externally
supplied token login ADR 0021 excludes. No request builder has a parameter that
can reach `model` or `modelProvider`, and a sealing helper refuses one that
appears anyway, because the gate observes the configured provider and a
per-turn override is a second channel it cannot see. `thread/start` sends
exactly `{cwd, sandbox, ephemeral}`: `approvalPolicy` is experimental-nested at
the pin, so the adapter does not send it at all, and a turn that blocks
awaiting an approval is a refusal here and a finding for N3.

**Account frames cannot reach the public outcome, and the guarantee is scoped
to frames rather than contents.** Three frames are excluded before a transcript
exists: a record carrying an `id`, which is the `account/read` reply and the
email it carries; a record whose method is in the `account/` namespace, which is
the notification surface; and unparseable bytes, which by definition cannot be
classified and are therefore never published at all — only their count and their
parse error are. An earlier attempt to filter those bytes by substring closed two
shapes and left the class open, which is why the rule is now "publish nothing
unclassifiable" rather than a marker.

Transcription is an allowlist of attested evidence rather than a denylist. A
denylist over a surface the design itself calls unenumerated is an open
assumption: an id-less record with an unknown method carrying an operator fact
was kept, uncounted, in a success. The attested set is one earned prefix and
three exact names — `turn/`, whose terminal member is observed from the real
binary and in whose terms this projection is defined, plus `error`, `warning`
and `configWarning`. `item/` was considered and excluded, because its only
observed member is the id-bearing `item/tool/call` request, so the namespace has
never been seen emitting a notification; it returns at N4 once a real stream has
been observed. The set is not a closed enumeration, and the docstring says which
entries are names and which is a prefix.

Because that exclusion can blank most of a real transcript, it is never silent:
the fold counts what it could not classify and states the count in the
transcript's own marker, beside the byte bound's. Neither becomes `first_error`
and neither demotes a clean success, because our own classification is not
transport damage — but a reader holding a near-empty `raw_reply` sees how many
records were withheld and knows what to go attest. An invisible withholding of
evidence is the same class of defect as a gate that passes without running.

The guarantee stops at frames. A legitimate `turn/completed` is this turn's
evidence and its payload is the vendor's, so filtering its contents would need a
schema this repository does not hold and must not guess at. That pass-through is
pinned by an assertion rather than left in prose, and qualifying what those
payloads may contain is an N3/N4 prerequisite.

**Every public surface is bounded at its point of use**, which is what ADR 0021
requires of an untrusted authority input. `RateLimitInfo.detail` admits a key
only when its value is a number or a flag, bounded in count and key length, so
identity facts are excluded by shape rather than by a vocabulary; the earlier
code copied the whole wire object, and an account id, an email and a plan type
alongside `usingOverage` all reached a **successful** outcome. Fault details
name a wire value only when it is short and lexical and report its JSON type
otherwise; the earlier code interpolated raw values, so a nested `account.type`
published an email and a 200 KB plan value produced a 200,041-character
`ExecutorError.detail`. The joined transcript is capped and says how many
records it dropped. Method names in the refusal fault are separately bounded,
with `/` admitted, because a classifier that stripped it would destroy exactly
the specificity that fault exists to provide.

**`requested_model` no longer rests on an unverified coupling.** The turn sends
no model, so the sealed configuration decides what runs, and nothing checked
that the configuration named the granted model — an assembly pinning A while the
grant said B published B and ran A. The provider now reads the model out of the
configuration with `tomllib`, refuses one outside the profile's inventory, and
refuses a grant that disagrees.

The provider is leased and schema 3. Availability is an assembly fact read
without runtime I/O, and this slice delivers no store, no egress and no
qualified ingress, so its published state is unavailable by default and nothing
at runtime can clear it. Its constructor refuses a published identity that
differs from this adapter's actual content in any of eight source-derived
fields, refuses a mediated callback catalog, and refuses a relative acquisition
root or a non-absolute binary. The launch-recipe drift check is reachable rather
than dead, because `LinuxLauncher.revision` is a property that re-hashes its own
sources at call time, and it is tested by a launcher whose revision changes
after construction. Reconciliation reaps nothing because the slice owns no
durable payload; the store binding, its exclusive lock and egress disposal
arrive with N3.

**The account refusal is deliberately over-broad, and that is a forward cost.**
Refusing every `account/` notification means that if the pin emits a benign one
during a normal turn — a rate-limit update, say — this adapter refuses a turn
that would otherwise have succeeded. Naming the methods that count as mode
changes would be guessing, because the enumeration held here is of requests. The
cost is zero in this slice, which refuses before any turn, and it first becomes
reachable when a credentialed session runs at N4; the published fault names the
method that fired, so the first occurrence identifies itself and narrowing is a
one-line change backed by evidence.

**Limits, stated rather than discovered later, and pinned by assertion wherever
a test can hold them.** A limit in prose gets quietly widened; a limit that
fails a test when it changes survives. The stderr `evidence_excerpt` is
unfiltered vendor output, kept because it is the only transport diagnosis
available and pinned by a test asserting an operator string does reach it —
establishing what the pinned binary writes there is an N4 prerequisite. The
numeric-only rate-limit rule stands in for a schema not held, so a mostly-string
payload publishes almost nothing, and a test pins a dropped timestamp as
intended. `configured_model` reads one top-level TOML key, verified against both
fixture helpers, so a production configuration using a profile table or a
layered include is refused rather than misread — fail closed, and an N4
prerequisite. The plan key `planType` is named by the preflight from pinned
source and its casing is corroborated by the combined lane's live capture of the
sibling `requiresOpenaiAuth`, but no capture of a populated account is
obtainable without a credential; a wrong key fails the plan check against a real
managed account. The `thread/start` sandbox value is never sent in the lane
because the gate refuses first, so its reachable variants are unverified, and
the only value observed live in this repository came from a session that opts
into the experimental capability. Whether the pinned schema requires
`capabilities` on `initialize` is not verifiable here; if it refuses the field,
the lane fails loudly on its exact-fault assertion. The turn projection keys are
unproven before N5 and each stays absent when unmatched, so a wrong name
degrades to truthful absence. `ExpectedAccount.plan_type` is a bare string, so a
vendor tier rename fails closed but is indistinguishable from a lapsed plan —
right posture, operational trap for N4. `_collect` has no deadline of its own
beyond the launcher's, so a child emitting one record just inside every window
holds the acquisition guard for the whole timeout. The two source-derived
revisions use `inspect.getsource` and are unavailable under `-OO` or a frozen
install, as N1's are.

**An id-bearing record is judged by ownership, and an unfinished check is a
refusal.** Ids are recorded as they are allocated, and one classifier runs at
every site that can meet an id-bearing record. Ownership is settled first,
because an id this conversation allocated is exactly the id a forger can
predict: a second answer, or an answer where none is awaited, refuses. Only
then does the record's shape matter, and only to separate a reply that answers
no request — which refuses promptly, so the outcome names the violation rather
than a deadline — from an unauthorized callback attempt, which is damage. An
earlier version decided severity from the presence of a `method` key, so one
extra key moved a pre-send forgery from a refusal to a published partial; the
key was the wrong discriminator, because ownership is what makes such a record
an attack.

The duplicate-id rule is the primary defence and the ordering marker is a
narrow complement — established by testing, not by argument: in a turn of
ordinary-sized records the straddling record is a filler that consumes the
marker, and what refuses the forgery is the genuine reply arriving behind it
under the same id. Because that rule carries the weight, an unfinished check is
treated as a failure: the drain runs to EOF whatever the framing does, its
inconclusive flag defaults to true and clears only at EOF, and its fault is
raised in a `finally` so an exception leaving the drain records it rather than
routing around it. Four bytes — an unterminated line between two replies — used
to silence the whole check and publish the turn as a success, with the damage
structurally unobservable because the observation is folded before the drain is
awaited. The fault, not the observation, is therefore the channel that reaches
the outcome.

**The vendor's message ordering is no longer assumed.** A `turn/completed` read
before the `turn/start` reply names the turn is buffered and judged once the
reply arrives, rather than refused on sight. Refusing it bet on the pinned
app-server never emitting a turn's notifications ahead of its response, and
nothing here could verify that bet — no test drives a turn against the real
binary, so a wrong bet would have refused every live turn and first surfaced on
the M8-D2 host. The containment lane then showed the server emitting two
notifications before any turn exists at all, which makes the bet worse than
cautious. Those two methods are instrumented rather than identified: the lane
now records the withheld method names, bounded and classified, so a later run
names them.

Ordering covers the framed queue **and the record currently being framed**: an
earlier version inspected only the queue, so a forgery straddling an 8192-byte
read boundary still cleared the gate. What escapes every rule here is a client
that forges a reply and then suppresses its own genuine one, because the vendor
authors the reply's *content* and not merely its timing — a client willing to
forge could instead answer the real request with a lie. Randomizing the ids
would not change that, which is why they were not randomized, and it is why the
gate detects a mode change the session **honestly reports** — ADR 0021's
vendor-refresh case — and cannot detect a session misreporting itself. What is
claimed about the duplicate rule is only the four shapes that are tested; a
shape not among them fails closed under the inconclusive rule, which is a
property of that rule rather than a proof that no other shape exists.

Evidence: local gate 2,335 passed, 361 skipped at the code head, and the
inventory `scripts/check_m8_n2_mutations.py` holds 82 mutants, all killed by
assertion with none unmeasured. That last fact is the outcome of a restructure
rather than of luck. Nine handle-level tests were originally gated to Linux
because the acquisition guard is physical and deliberately not injectable
(I1) — so they were written, type-checked, reasoned through, and executed on no
platform at all, which is how a broken cancellation assertion reached CI. They
now run everywhere against a fixture substituting only `acquisition_guard`,
which still yields a live descriptor, with handle, provider, conversation,
launcher and every assertion the repository's own. One test stays gated,
asserting `S_ISREG`, `st_uid`, `st_nlink` and that a second holder waits on the
non-blocking `flock`; it pins no mutant because it pins a property of the OS
rather than a decision of ours, which is why the inventory lost nothing. The
principle is the same one the unmeasured-mutant reporting already applied: a
test that has never run is not evidence, exactly as a mutant that was never
measured is not a kill.

`tests/substrate/test_codex_protocol.py` drives the pure protocol against
scripted bytes; `tests/substrate/test_codex_adapter.py` drives the adapter
against a genuine scripted byte channel that enforces the launcher's one-reader
and 1..8192 read contract, and its handle section drives `execute` end to end,
which is the only place the production discard is exercised.
`tests/substrate/test_codex_native.py` runs the pinned binary under containment
and remains the one thing this development host cannot execute.

**What the native lane proves is refusal, and that is the honest result.** The
lane is credential-free, so `account/read` returns a null account, the pre-turn
gate refuses, and no turn is ever sent — the model peer behind the bridge is
never reached. Both cases passed against the pinned binary in CI. A second case
sets the configured provider to require OpenAI authentication and observes that
only the empty-store fault remains, which separates the two faults the first
case reports together.

**Review history, because it is the most transferable thing in this slice.**
Twenty-eight defects were found before merge across four passes — two by the
supervising session and the rest by independent adversarial reviewers — every one
reproduced by running code rather than by reading it. The first head had passed a
green gate and killed 38 mutants while carrying a complete subscription-gate
bypass, so neither a green gate nor a full inventory was evidence of correctness
here, and later rounds were told to treat them as carrying no weight.

**Each round found a defect inside the previous round's fix.** Round one fixed an
account-notification leak; round two found the same hole in unparseable bytes and
a fourth unclassified `!r` site the fix had missed. Round two added value
classifiers to keep wire content out of public fields; round three found the
decoder's own exception message bypassing them, and 150 KB of vendor payload
published through `first_error` while the *same record* was correctly excluded
from the bounded `raw_reply`. Round three fixed reply ordering with a pre-send
drain; the same round then found the drain inspected the framed queue but not the
adapter's own framing buffer. Two things follow. A fix is not evidence that a
class is closed, and the narrow follow-up pass that only attacks the newest fix
has paid for itself every time.

Two causes account for nearly all of it. **Every account-leak test drove a
refusal**, and the refusal path correctly discards `rate_limit` and `raw_reply`,
so the suite was structurally blind to the accepting path where a real turn's
data is published — four separate leaks were living there. And **what state can
exist when an `await` resumes** was untested: the gate bypass and the forged
reply are both "something buffered, latched or aborted between two steps, and a
later step assuming it cannot be there". Both classes are cheap to test from the
first commit and expensive to retrofit, which is recorded on #76 as a constraint
on N3.

Underneath all of it sits one principle: **a negative inference is not a positive
fact.** An empty fault list meant both "the gate cleared" and "the conversation
died before recording anything". An id match meant both "this is the reply" and
"something guessed the id". A passing test meant both "the behaviour holds" and
"the test never ran". Where this slice now records the fact affirmatively — a
latch set only after the comparison, ordering over framed and framing bytes, a
duplicate-id refusal, a substituted guard that lets a written test actually
execute — the class closes. Where it still infers, the limit is written down and
pinned by an assertion.

Three fixes made the code smaller: a substring heuristic, an unfalsifiable
clause, and a test-only IO shim were deleted. Removing the unfalsifiable clause
added a kill rather than losing one, because what replaced it was a test that a
future widening of the allowlist would break. Manual Codex review remained paused
at the owner's request for its weekly limit, so the independent reviews were
fresh-context Opus reviewers; that is a real reduction in independence and is
recorded here rather than glossed. N3 is the next slice, and #76 carries its
delivery slicing and constraints.

## N3a: native-store custody (merged)

N3a implements only the dedicated native-only store, retained lock, binding
generation checks and immutable descriptor/restart rules from #76. It does not
close that issue. N3b's acquisition-scoped egress and N3c's complete maintenance,
refresh, crash, non-widening and overage matrix remain separate. No credential,
account, live vendor call, host deployment or production qualification is part
of this evidence.

The required pre-code async-resume design pass is
[`M8-N3a-state-review.md`](M8-N3a-state-review.md). Its independent Sol/Terra
review corrected idle-holder recovery and local-close lock ordering before
implementation. It was posted to #76 before code was written. An additional
Hardline review timed out and is not counted as evidence.

One private substrate binding owns the protected descriptor bundle. Its active
selection is explicit; publication alone cannot activate it. Immutable
generation files pin a publisher-derived physical store instance, the retained
lock and the actual source-derived laws. Current paths are reopened and checked
against held identities without reacquiring the retained lock. The existing
acquisition guard is acquired first and both guards span the materialized
lifetime; the existing supervisor inherits them. Local cleanup commits the
existing durable acquisition fence before joining owned work and closing its
copies. No new scheduler, journal schema, custody daemon or public identity
contract is introduced.

Readiness, post-probe launch and terminal result acceptance each require an
affirmative sealed `BindingCheck`. A missing check is not success. A terminal
refusal discards the completed turn. The launcher mounts only the selected
writable store at `/vendor-store`, separately from disposable HOME; native
store and worker workspace mounts cannot coexist. The native proof client is
harmless Python, not authenticated Codex. N3a does not install sealed vendor
configuration, route `CODEX_HOME`, or establish vendor refresh conformance.
Default production availability remains refused.

The portable proof substitutes only filesystem/lock primitives. It drives the
real provider, lifecycle, strict descriptor reader and conversation on both
accepting and refusing paths. The complete published outcome is checked using
N2's existing surface-bound walker, with private binding facts excluded from
the identity, outcome and inert acquisition reference. Descriptor tests reject
mutually consistent but wrong runtime laws, forged instances and wrong active
selection witnesses rather than trusting one stored record as its own proof.

Review has already corrected introduced defects: stale pre-wait identity
observations; source-law comparison only against another supplied value;
directory link growth misclassified as root replacement; offline ownership
changes before nonsymlink proof; and a portable double that recorded closes
without closing its real descriptors. Tests now cover those classes. One
reviewer's claimed privilege requirement for `name_to_handle_at(AT_EMPTY_PATH)`
was withdrawn after primary-source verification: it confused that syscall with
`open_by_handle_at`, which is not used. The state-review ledger preserves the
reasoning and source. A narrow second review of launcher/tests/provisioning
found no additional introduced blocker. The complete-diff review subsequently
found publisher inputs that its own reader refused, unusable fixed-child modes,
and a stale awaited acquisition-fence observation before readiness. The last
case was reproduced with the real durable closure and a deterministic barrier,
not a substitute closed flag. All are corrected; strict reader validation is
reused before publication, fixed modes are explicit, and the final durable
fence is read synchronously after each positive binding observation. Metadata
FIFOs and deeply nested JSON also now refuse without blocking or escaping the
typed failure path. Accepting and refusing outcomes share the public-field
bound test. The state-review ledger records the evidence and limits.
An additional root/independent-review reproduction found initial metadata I/O
errors exposing a private path through runtime failure-event text. The initial
reader now uses the same typed-refusal discipline as the lock and held checks;
a regression covers all three phases and its removal mutant fails by assertion.

The complete-diff reviewer was interrupted by a platform safety filter before
issuing its final verdict. Its confirmed findings are retained, but this is not
a completed review or approval. A bounded independent review of the fixes is
separate evidence; final review status is recorded in the exact-head N3a
closure below.

At an intermediate implementation head, the focused Codex/store/surface suite
passed 113 tests with one explicit privileged skip. N3a's inventory in
`scripts/check_m8_n3a_mutations.py` then killed 45/45 mutants by assertion,
including removal of the final materialization fence read. The initial-metadata
error regression added a 46th mutant and its individual assertion kill was
established. These interim focused results did not replace the later final-head
repository, compatibility, mutation or Linux evidence recorded below.

The hosted-Linux workflow now runs fresh-interpreter root/lock replacement and
no-overwrite publication tests, unprivileged native-only mount and retained
lock handoff tests, and a real controller-death/supervisor-custody test.
Run-scoped `n3a-*.json` artifacts contain only bounded positive fixture facts
and opaque sealed digests, not private descriptor contents. Actions containment
run `35542612151` passed on `4e7b2f2`: both fresh-interpreter replacement cases,
explicit selection/no-overwrite publication, native-only read/write including
child-directory creation, lock handoff and controller-death custody produced
positive artifacts. The ordinary worker did not receive the store. This is
credential-free physical fixture evidence, not vendor conformance. The same
head's ordinary verify run passed 2,460 tests but failed Linux mypy on a local
name reused with incompatible types; that introduced defect is corrected.
That head therefore was not final closure evidence; Windows skips are never
counted as physical proof.
The next physical run passed all three FIFO cases but caught Windows-specific
absolute paths in two portable fixtures. Those fixtures now use pytest's actual
absolute temporary path; the test was corrected, not the production refusal.

Marking PR #89 ready triggered the GitHub Codex connector's review of `62ac3bb`.
It found an introduced P1: the provider checked resolved acquisition/store roots
but retained the original acquisition path. The finding was reproduced with
harmless temporary directories. Merely retaining the resolved path was rejected
after a second-provider counterexample: a mutable alias could resolve to a new,
still-disjoint guard root on restart. The bound provider instead refuses
noncanonical acquisition roots and retains the exact checked locator. Guard,
cleanup and reconciliation paths all derive from that one field. The state
review records the trusted-ancestor limit; this is not a claim of inode pinning.
Regression and exact-head review/CI evidence are recorded on PR #89 and in the
N3a closure below.

### N3a closure

[PR #89](https://github.com/sushiHex/constructicon/pull/89) merged on
2026-09-21 at 01:08:54Z as
`7535903d4ccbb9c5e4583567995db152d08153d0`, from base
`153ab8e390fdb85b48094f277969b3806fcfab62`. Its merged tree
`a428dfaeadeb415b70c9da0926e2118b1e5666f2` is identical to reviewed head
`c12a681d8156e14aaca1fe86afa6ba3585f31ea9`.

On that final head, local `uv run verify` passed 2,407 tests with 375 skips,
alongside clean ruff, strict mypy across 101 source files and all four import
contracts. The
[Linux verify run](https://github.com/sushiHex/constructicon/actions/runs/35548285797)
passed 2,483 tests with 299 skips; the
[runner qualification](https://github.com/sushiHex/constructicon/actions/runs/35548285720)
and [containment run](https://github.com/sushiHex/constructicon/actions/runs/35548285699)
also succeeded. N3a's final inventory killed 47/47 mutants by assertion both
locally and on Linux. N2's local compatibility inventory retained 82/82
assertion kills with zero unmeasured mutants, and Linux platform mypy was clean.

The containment run's native artifact
[`m8-containment-35548285699-1`](https://github.com/sushiHex/constructicon/actions/runs/35548285699/artifacts/10617603819)
contains six N3a JSON records. They affirm publication and generation,
fresh-interpreter store and lock replacement refusals with unchanged accepting
controls, native-only read/write, owner-death retained-supervisor custody, and
lock handoff. This remains credential-free physical fixture evidence:
`vendor_conformance_qualified` is false, no production use or credentials are
qualified, N3b and N3c remain incomplete, and issue #76 remains open.

The [final-head connector review](https://github.com/sushiHex/constructicon/pull/89#issuecomment-5754017758)
reported no major issues. Its introduced acquisition-path P1 was fixed and the
[review thread](https://github.com/sushiHex/constructicon/pull/89#discussion_r4058671099)
was resolved before merge.

## N2 WRITE — callback and contained-workspace composition (#75)

[PR #95](https://github.com/sushiHex/constructicon/pull/95) carries the remaining
credential-free WRITE work. It references, rather than closes, issue #75 until
the complete acceptance matrix is established. The independent pre-code
[state review](M8-N2-WRITE-state-review.md) was committed as `f906137` before
implementation. It records the positive facts required across callback,
worker, workspace, capture and close awaits; no accepted plan bytes changed.

The implementation extends the existing adapter with one fixed
`contained_python` callback. WRITE opts into that carrier explicitly; READ's
requests retain their previous bytes. Callback request identities and client
reply identities remain separate, while both request and call identities are
spent before effects. A bounded pre-turn request waits for the naming reply;
a previously observed terminal record closes that authority. Worker completion
and response delivery are recorded separately from subscription-gate completion.

The handle reuses the workspace provider's ownership law, adding only owner,
revision and exact-grant checks. Its worker receives the workspace guard only,
not the native acquisition or store guards, and spends the native exchange's
remaining deadline. The unchanged proposal/capture and gate components compose
the behavior; there is no new graph primitive, journal record or scheduler.

### Introduced findings reproduced during implementation

The first callback implementation awaited the worker without observing native
EOF. Source inspection and an executable regression confirmed that the exchange
supervisor did not itself cancel the conversation at that seam. The state review
was amended before replacing that await with one owned worker/read race. It
judges a simultaneous native fact first, joins on refusal, and holds only exact,
bounded pending callbacks until the preceding response is completely written.

The correction initially discarded exceptions returned by its cleanup join.
Preserving those exceptions then exposed a second defect: a cleanup failure
could replace an enclosing cancellation and become an ordinary refusal. Separate
regressions reproduced both. Cleanup now retains the cancellation and failure
together; the workspace worker follows the same ownership rule. The independent
follow-up review found no remaining blocker in these two cleanup paths. These
are portable lifecycle proofs, not evidence of physical Linux process cleanup.

A source-based review also corrected the Linux fixture's assumption that a red
gate produces no attestation. The existing gate records failed checks too; its
`ok` verdict, not the existence of an attestation, distinguishes authorization.
The fixture now checks the retained attestation's subject and checks for both
outcomes. Its physical execution still requires the Linux lane below.

A later public-handle test initially reported lost cancellation/cleanup
evidence. That premise did not survive isolation: its one-second deadline could
expire while durable close was still recording its fence. With a finite
30-second budget, close reported the worker's cleanup error and active execution
reported cancellation. Those are the two owning await channels; requiring a
duplicate cleanup error inside the active task's exception group would add a new
contract. The test now pins both observable facts and guard-exit order without
that assumption. No production change was made for the withdrawn finding.

### First physical protocol evidence

At `e33ae98`, the
[Linux containment run](https://github.com/sushiHex/constructicon/actions/runs/35560627314)
executed both callback-registration cases against the retained Codex `0.153.4`:
explicit opt-in admitted `thread/start.dynamicTools`, while absent opt-in returned
code `-32600` and the exact required-capability refusal. Both asserted zero model
requests. All four physical lanes, qualification and ordinary verification
passed on that test-only head. It is evidence about the pinned interface, not
the later production implementation or authenticated model use. The later
fixture uses the production request constructors and requires its own CI run.

At `3a3e514`, the
[combined Linux lane](https://github.com/sushiHex/constructicon/actions/runs/35563296122/job/106220153099)
executed both production-constructor registration cases successfully: 135 tests,
82/82 retained N2 mutants and all 49 WRITE mutants passed their respective
assertions. Mediation and lifecycle lanes also passed. The overall gate did not:
the new workflow files were missing from the pinned proof inventory, and the
expanded cleanup tuple invalidated an older N3a mutation anchor. Both are
introduced test-integration defects, not qualifying evidence. Their corrections
preserve the complete inventory and the original mutant's active-exchange law.

At `897eb1f`, the
[foundation lane](https://github.com/sushiHex/constructicon/actions/runs/35564666753/job/106224039563)
executed the accepting capture/gate, red-gate and literal controller-death cases
successfully. Its checkpoint cases stopped at a test API error after host
shutdown: `RunState` has no `cancel_requested` field. The correction queries the
existing `journal.cancel_requested(run_id)` method instead. Neither checkpoint
case earned successor-recovery credit from that run; both require re-execution.
Ordinary verification, qualification, mediation and lifecycle passed on this
head; the failed foundation lane still blocks readiness.

**Superseded at the reviewed head.** That re-execution happened. At `7b89dcc`,
the reviewed head PR #95 merged as `184ff4d` byte-identically, every lane
passed: [foundation](https://github.com/sushiHex/constructicon/actions/runs/35565464075/job/106226317981),
[lifecycle](https://github.com/sushiHex/constructicon/actions/runs/35565464075/job/106226317980),
[combined](https://github.com/sushiHex/constructicon/actions/runs/35565464075/job/106226317977)
and [mediation](https://github.com/sushiHex/constructicon/actions/runs/35565464075/job/106226317913),
with [containment](https://github.com/sushiHex/constructicon/actions/runs/35565464075/job/106228161751),
[qualification](https://github.com/sushiHex/constructicon/actions/runs/35565464069/job/106226283373)
and [verification](https://github.com/sushiHex/constructicon/actions/runs/35565464105/job/106226283233)
beside them. Both sides of the candidate checkpoint executed, so the two cases
that earned no credit at `897eb1f` earned it here, and successor recovery is
executed rather than inferred: recovery reused a checkpoint without another
native exchange, callback or capture, while uncheckpointed work took a fresh
acquisition.

The `897eb1f` paragraph above is kept rather than rewritten, because the
correction it describes — `RunState` has no `cancel_requested` field, and the
journal owns that query — is the reason the later run could pass. A failed lane
that produced a real fix is evidence, not noise.

### Evidence limits

Portable tests exercise callback acceptance and refusal, exact byte bounds,
request/call identity separation, duplicate and over-limit calls, response loss,
workspace identity and cleanup ordering. Whole-outcome assertions cover both
acceptance and refusal. Their scripted managed-account replies are not a vendor
identity or subscription proof. Mutants must fail by assertion; fixture errors
and skipped native tests remain unproved.

The new Linux composition lane uses a scripted native peer and substituted
store syscalls with a real contained worker, Git capture and contained gate.
Its accepting and red-gate cases are distinct from the pinned-binary protocol
fixture. The executed cases and their exact heads are recorded above; they
qualify those heads and no later changed one.
The complete WRITE controller-death, successor and checkpoint matrix is not
inherited from READ or from separate workspace tests. Current evidence and
remaining ownership stay on issue #75 and PR #95.

The added checkpoint fixture uses lawful host abandonment and a reconstructed
control plane, with real contained capture. It distinguishes pre-checkpoint
re-execution from post-checkpoint reuse of the exact candidate and zero new
native exchanges, callbacks or captures. The literal-death companion stops a
real worker supervisor, kills its controller, and checks guard custody before
successor disposal. Its native peer remains scripted, so it cannot prove native
supervisor retention of the store lock. Both new fixtures require the provisioned
Linux lane; their local skips are not executed proofs.

Production availability remains refused. This work installs no vendor
configuration, credentials or deployment, proves no live subscription turn,
and does not complete N3b egress, N3c conformance or private-host qualification.

## N3b — acquisition-scoped egress (#76)

N3b is the egress slice of issue #76; it does not close the issue. The pre-code
[state review](M8-N3b-state-review.md) was committed as `9058290`, reviewed
independently by Codex (`gpt-5.6-terra`, job `job_7914037954a5`), and amended
in `60c51a5` for one P1, seven P2 and the adopted P3 findings. The rejected
findings and their reasons are recorded in that document. The amended text has
not itself been re-reviewed.

The slice adds one stdlib-only substrate module, `executors/egress.py`: a
host-side CONNECT relay per native execution, reached from the native zone
through one read-only socket leaf, `/vendor-egress.sock`, bound into the zone's
existing `--unshare-net` namespace. A destination is a sealed `(host, port)`
with one pinned literal address; nothing resolves a name, and the CONNECT host
never reaches the dialler. The first ClientHello must be one complete record
naming exactly the CONNECT host, with no ECH, no duplicate extension and one
`host_name`. That rule binds the first hello only; the pinned address is the
boundary. Every handler await is bounded by the acquisition deadline, and the
relay rechecks its stop latch, the owner task's cancellation and the deadline
synchronously after every resumed read, before any dial and before any
forward. `NativeStoreMount` carries the leaf, so no worker launch can; `argv`
re-identifies the bound socket (`S_ISSOCK`, owner, `(dev, ino)`) before mounting
it. The relay is entered inside the `self.active` task that `_cleanup_owned`
already cancels and joins, so it is torn down before either guard is released.
Allocation is an exclusive `mkdir` of the acquisition's own payload directory.
The provider refuses an egress identity that differs from the sealed policy and
an acquisition root too long for the socket path. The production runtime
reserves the leaf as an immutable empty regular file, which changes the runtime
digest. No L0 contract, journal record, supervisor or AppArmor change, and no
new forced unavailability reason: the default reasons still publish the
unqualified egress boundary, and a provider with no policy mounts no leaf.

Denials are counted in `observed` as evidence and are never fatal to a turn.
Every allocation, handler and teardown failure becomes one fixed-text
`ContractViolation` inside the relay, because the original exception text
carries private locators (review finding 1).

### Local evidence

Everything below was executed on Windows 11 with Python 3.11, with only the
relay's two platform primitives substituted (a loopback TCP listener with a
stand-in inode, and a plain `sock_recv`). It is portable evidence about the
relay's rules, not physical evidence.

- The portable suites (`test_egress.py`, `test_egress_launch.py`,
  `test_codex_egress.py`) drive every relay rule in both directions: CONNECT
  membership, IP literals and the head bound at its limit; a real stdlib
  ClientHello against twelve refusals; pipelining, including the pinned
  first-hello limit; the connection bound at its limit; the deadline on an
  active stream and an idle handler; stop, control, control lost during the
  dial, and ownership loss after the dial; exclusive allocation, a replaced
  socket and exit failures; the launcher leaf; the provider's identity and path
  budget; and the handle's allocation, close ordering and `network="none"`
  refusal. A resolver recorder with a same-run control saw zero relay calls on
  the accepting and refusing paths.
- The field-walking surface test seeds the acquisition root, socket name, pinned
  address and denial prefix on an accepted path, a refused path and four failure
  paths (existing payload, a bind error naming the path, a substituted socket at
  exit, an unclassified handler failure). None reaches any published field.
- `scripts/check_m8_n3b_mutations.py`: 34 of 35 mutants killed by assertion. The
  Linux-only ancillary mutant (29) reported NOT PROVEN, as expected on Windows;
  it has no kill until the foundation lane runs it.
- The retained inventories still kill every mutant by assertion against the
  changed `_converse`, `argv` and provider: N3a 47/47, N2 82/82, N2 WRITE 49/49.
- `uv run verify` on the complete tree passed: clean ruff, strict mypy over 102
  source files, four import contracts kept, and 2,630 tests passed with 408
  platform skips. The only change after that run was this record's own text and
  its manifest line, rechecked with `sha256sum --check` and the plan-manifest
  test.

### Deviations from the amended design

- The task body is a new `CodexOperatorHandle._exchange` method rather than
  inline code in `_converse`, so the N2 mutation anchor
  `guard_fds=(guard, held.lock_fd),` stays in `_converse` exactly once.
- The deadline tests accept a peer EOF up to one monotonic clock tick before the
  deadline. asyncio runs timers up to its clock resolution early; on Windows the
  first run measured EOF 3 ms before the deadline, with a 15.6 ms resolution. The
  state review's row now says so. The upper bound (deadline + 1 s) is unchanged.
- The store-socket positive control binds through `/proc/self/fd/<dirfd>`,
  because the store path is longer than `sun_path`. That mechanism is Linux
  reasoning until the lane runs it.
- Self-review after implementation found a second instance of review finding
  2's class: `sock_sendall` completes a partial write from an I/O callback that
  bypasses the pump's liveness check. It is recorded as a limit in the state
  review rather than fixed with a third substituted primitive, and the
  stalled-controller test asserts at most one chunk after resume instead of zero
  bytes. The "at most one 8 KiB chunk" bound first recorded here was false:
  the implementation review below found the kernel send queue behind it.

### Limits and unexecuted proofs

The state review's limits apply unchanged: pinned addresses, the direct CONNECT
client (the Codex `HTTPS_PROXY` path is N4), same-uid trust for pathname
sockets in the store, the first-hello-only rule, ownership loss observed only at
connect points, stalled-controller sockets, queued bytes (what the kernel sends
before a handler's abortive close, and a clean end's unacknowledged tail
discarded), an accept completed during teardown left for the garbage
collector, an unstarted handler's connection counted nowhere, an orphaned
payload after a teardown failure on a normally closed lease, and native TLS
validation as an N4 assumption.

These have **no execution** until Linux CI runs them, and Windows skips are not
passes: the real `AF_UNIX` bind and identity, `recvmsg` ancillary refusal
(mutant 29), `require_current` against a replaced real socket, the 107-byte
`sun_path` budget, the leaf in the production runtime, `ssl` inside the runtime
and `openssl` on the runner, the throwaway-CA TLS peers, the redirect, ECH, SNI
and IP-literal refusals through the real zone, the in-zone errno assertions,
the zone socket walk and its planted-socket control, the worker's empty leaf,
cancel and deadline revocation, controller death with successor disposal, and
the stalled-controller pin with its concurrent successor. They are
`tests/substrate/test_native_egress_containment.py` in the foundation lane's
"Prove N3b acquisition-scoped egress denial" step, with evidence in
`n3b-*.json`. `vendor_conformance_qualified` stays false, and production
availability remains refused. The portable tests added by the implementation
review below have run on Windows only; their first Linux run is CI's, including
the reset that discards the upstream queue.

### Implementation review

A single-model review of `6bc9500...ccee567` reproduced each finding with a
probe against the real relay before reporting it. No independent-model review
ran. Codex was paused under a weekly limit, and the round's rules forbade model
calls. **Neither the amended design, the implementation, the partial-write
deviation nor this round's fixes has had an independent-model review. That
review is still owed (finding 10).** Each finding below was reproduced again
before it was acted on. Findings 1, 6 and 8 failed a new test before the fix and
passed after it. The coverage findings (2-5, 7) are proven by new mutants 36-43
of `scripts/check_m8_n3b_mutations.py`, each killed by assertion.

| # | Finding | Class | Disposition |
| --- | --- | --- | --- |
| 1 | P2: the "at most one 8 KiB chunk after stop" limit is false. A graceful `upstream.close()` let the kernel keep sending the send queue after the deadline, after exit and after guard release | introduced | Fixed. Every upstream close in `_handle` and `_open` is abortive (`SO_LINGER` zero). Reproduced by the review probe: 75,250 bytes (peer buffer 1 KiB) and 599,538 bytes (256 KiB) reached the peer after exit; 0 after the fix. `test_nothing_queued_before_the_deadline_reaches_the_peer_after_exit` failed before the fix (75,250 bytes beyond what the peer held). Mutant 40. The limit text is rewritten as "Queued bytes" |
| 2 | P2: the owner-`cancelling()` liveness term had no test or mutant | introduced | Fixed. `test_a_cancelled_owner_still_reaping_admits_nothing`; mutant 36 (it survived all 88 portable tests before) |
| 3 | P2: the synchronous deadline term was unproven | introduced | Fixed. `test_a_read_resumed_past_the_deadline_forwards_nothing` blocks a substituted read past the deadline in the step that resumed; mutant 37 |
| 4 | P2: the handle's control wiring was unproven | introduced | Fixed. `test_control_lost_during_the_exchange_denies_the_connect` loses control inside the native exchange and asserts `denied:control` and zero peer connections; mutant 38 |
| 5 | P3: the handle's deadline wiring was unproven | introduced | Fixed. The accepting handle test bounds the relay's deadline by the exchange's own `loop.time() + timeout_s`; mutant 39 |
| 6 | P3: a mid-stream `ETIMEDOUT` counted as `denied:deadline` | introduced | Fixed. A stream `TimeoutError` is `denied:deadline` only when the handler's timeout expired, otherwise `reset`. `test_a_stream_timeout_before_the_deadline_is_a_reset` failed before the fix; mutant 41 |
| 7 | P3: the hello record bound was never tested where it binds | introduced | Fixed. A real hello grown to a 16,384-byte body is accepted and forwarded byte-identical, and 16,385 is refused; mutant 42 |
| 8 | P3: a handler cancelled before its first step never ran its `finally`, so its client stayed open after exit | introduced | Fixed. The relay keeps every accepted client and closes them after the join. `test_teardown_closes_a_client_whose_handler_never_ran` produces a genuinely unstarted handler (asserted `CORO_CREATED`), and it failed before the fix; mutant 43. The accept-future limit is narrowed: it was reasoning, and the same retention shape applies |
| 9 | P3: the README index row was stale | introduced | Fixed |
| 10 | Process: no independent-model review of design amendments, implementation or deviation | process | Recorded above as owed; not satisfiable in this round |

**Defects inside this round's fixes, found by self-review:**

- The first form of the finding 1 fix kept a graceful close for a stream that
  ended cleanly in both directions. That re-opened the same class: a clean end
  shortly before exit, with a slow peer, would keep sending after exit and
  after the guards are released. A probe also showed the branch cannot be
  discriminated portably: on Windows loopback, a completed send is already in
  the peer's buffer, so a clean-end test passed under both branches. Every
  upstream close is now abortive. The recorded cost is that a peer that
  half-closed and then reads slowly can lose the tail of what the client sent.
- Closing the accepted clients at exit made mutant 18 (teardown skips
  cancelling handlers) escape. An unjoined handler now saw its client closed
  and ended by itself, so the peer still saw EOF. The killing test now asserts
  the affirmative fact, before any await: every handler task is done when exit
  returns.

**Rejected or not adopted:**

- **Vendor-path network errors other than `ETIMEDOUT` as `reset`** (review
  finding 6, flagged by the reviewer as a design-choice disagreement). A
  mid-stream `EHOSTUNREACH` stays a fatal fixed-text `RELAY_FAILED`. That fails
  closed and costs the turn, not the boundary. Widening the non-fatal set beyond
  `ConnectionError` and a non-expired `TimeoutError` would need an errno list
  with evidence behind it, which this slice does not have. Linux can report a
  path failure as `EHOSTUNREACH` after a retransmission timeout. That is
  reasoning about the kernel, not measured here, so the classification is a
  recorded design choice rather than a claim that the two cases differ.
- The reviewer's own rejections stand:
  - A read-only bind does not block `connect`. This rests on the placement
    lane's measurement.
  - The selector loop's `sock_connect` resolves through `_ensure_resolved`,
    which returns a numeric host without calling `loop.getaddrinfo` (read in
    the Python 3.11.15 stdlib).
  - A group-swallowed cancellation cannot hang the join, because
    `finish_owned` waits until the task is done (`_lifetime.py`).
  - Mutants E, G and H are equivalent in effect.
- `_open`'s abortive close on a failed dial or hello forward is not separately
  pinned. The queue there holds at most the judged hello. No portable input
  separates it from a graceful close.

**Verification of this round:** the three portable N3b files passed 95 with 3
platform skips (88 before). `scripts/check_m8_n3b_mutations.py` killed 42 of 43
by assertion. Mutant 29 reported NOT PROVEN on Windows as expected, and it has
no kill until the foundation lane runs it. The reviewer's probes, re-run
against the fix, measured 0 bytes after exit and classed `ETIMEDOUT` as
`reset`. `uv run verify` on the complete tree passed: clean ruff, strict mypy,
four import contracts kept, and 2,637 tests passed with 408 platform skips.
After that run only this sentence and its manifest line changed. Both were
rechecked with `sha256sum --check` and the plan-manifest test.
