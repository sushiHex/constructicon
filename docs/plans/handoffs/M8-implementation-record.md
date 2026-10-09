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

### First Linux CI run

PR #97's first run at `1ec4943` is the slice's first physical evidence. In the
foundation lane
([run 35808396680](https://github.com/sushiHex/constructicon/actions/runs/35808396680)),
six of the eight containment proofs passed as `m8-service` with the production
runtime and store fixture:

- `test_the_zone_reaches_only_the_pinned_destination`: the accepting TLS path,
  the decoy, IP-literal, SNI, ECH and redirect refusals, the in-zone errnos,
  the abstract and unmounted socket controls and the resolver recorder;
- `test_the_zone_walk_finds_a_socket_planted_in_the_store`, including the
  `/proc/self/fd/<dirfd>` bind;
- `test_cancel_mid_stream_revokes_the_upstream`;
- `test_controller_death_ends_streams_and_a_successor_disposes_the_relay`;
- `test_a_stalled_controller_holds_its_guard_until_its_streams_end`;
- `test_no_evidence_file_contains_key_material`.

On the unprivileged Linux `verify` job
([run 35808396701](https://github.com/sushiHex/constructicon/actions/runs/35808396701)),
2,727 tests passed and 4 failed. The passes include the real bind
(`test_the_real_bind_records_the_socket_it_created`), the `SCM_RIGHTS` refusal
and every portable relay test, among them the abortive close that discards the
upstream queue. The lane's mutation step did not run, because the containment
step failed first, so mutant 29 still has no kill.

Six tests failed. One was a product defect, the other five wrong test
assumptions:

| Failure | Cause | Class | Fix |
| --- | --- | --- | --- |
| `test_require_current_refuses_a_replaced_socket` did not raise | The test closed the first listener before binding the replacement. `S_ISSOCK`, owner and path matched by construction, so only `(dev, ino)` could have refused it: the runner's `/tmp` handed the released inode number to the replacement. A bound socket holds its own inode until its last descriptor closes (`unix_bind_bsd` keeps `dget(dentry)` in `u->path`, v6.8), so a replacement bound while the listener is open cannot share the number | test assumption; exposed the defect below | The replacement is bound while the first listener is open, and the test asserts the two identities differ |
| `test_a_replaced_socket_is_not_unlinked_and_exit_raises` and `test_no_private_locator_reaches_the_outcome[substituted-socket]`: exit accepted the substitute | The portable stand-in inode was held by nothing, so its number was reused at once by the substitute; the stand-in did not model the listener's hold | test assumption | The stand-in is held by a hard link that the substituted listener removes on close, which is what a bound socket does |
| (defect) `__aexit__` closed the listener before `_release_path` compared `(dev, ino)` and unlinked | Between the close and the check, the number was free: a replacement created in that gap could receive it and be unlinked as the relay's own. Same-uid custody only, and a synchronous window, but the identity law was read past the point where it holds | introduced | Test first: `test_the_socket_is_released_while_the_listener_still_holds_its_inode` failed before the fix (the path still existed when the listener closed). `_release_path` now runs before any socket closes. Mutant 44 |
| `test_teardown_closes_a_client_whose_handler_never_ran`: `CORO_SUSPENDED` | The scenario polled for the handler with `sleep(0)`; whether its wake-up ran before the handler's first step is a scheduling race, which the Windows runs won and the Linux run lost | test assumption | Deterministic: the scenario connects with a blocking loopback connect, then awaits a future resolved inside `_clients.append`, which queues its wake-up before the handler's first step |
| `test_an_ordinary_worker_sees_an_empty_regular_leaf`: `EACCES`, not `ECONNREFUSED` | `unix_find_bsd` checks `path_permission(MAY_WRITE)` before `S_ISSOCK` (`net/unix/af_unix.c`, v6.8). The leaf is 0444 and the worker holds no capability, so write permission refuses first | test assumption | Asserts `EACCES` exactly |
| `test_the_deadline_cuts_an_actively_streaming_client`: `deadline > started + seconds` by 3 ms | `run_native` takes its deadline after `started`, so `started + seconds` is its lower bound, not its upper | test assumption | `started + seconds <= deadline <= streaming_at + seconds`, where `streaming_at` is when the client first reports streaming through the relay |

The kernel really did reuse the number. The wrong part was an unstated premise,
that `(dev, ino)` still names a file after nothing holds it. The documents now
state the hold, and the relay compares only while its listener provides it.
Comparing `os.fstat` of the listener instead would not help: a socket
descriptor's `fstat` reports its sockfs inode, not the path's.

**Verification of this correction:** the three portable N3b files passed 96
with 4 platform skips on Windows. `test_the_socket_is_released_while_the_listener_still_holds_its_inode`
failed before the reorder and passed after it.
`scripts/check_m8_n3b_mutations.py` killed 43 of 44 by assertion, including
the new mutant 44 and mutant 43 under the deterministic test; mutant 29 again
reported NOT PROVEN on Windows. `uv run verify` on the complete tree: clean
ruff, strict mypy over 102 source files, four import contracts kept, and 2,637
tests passed with 409 platform skips. Its one failure was the plan-manifest
test, run before these two documents' manifest lines were refreshed; after the
refresh that test passed on its own, and `sha256sum --check` passed.

**Unexecuted until the next Linux CI run:** both corrected Linux unit tests,
the new real-socket exit test
(`test_a_replaced_real_socket_is_not_unlinked_and_exit_raises`), the two
corrected containment tests, the deterministic unstarted-handler test on the
selector loop, the pinned stand-in on the runner's filesystem, and mutant 29.

### Codex review of `1ec4943`

One independent Codex pass (job `job_b21d1b3a3fbb`, requested by the
orchestrator) reviewed head `1ec4943`. It is the slice's only Codex round, so
this is the independent-model review that the implementation review recorded
as owed (its finding 10); its fixes have had no model review of their own. The
state review's "Codex review of the implementation" table carries the
classification and the rejected finding 1 with its reason. Every premise was
reproduced first. A probe on the selector loop showed `EgressDestination`
accepting `127.0.0.1`, `10.0.0.1`, `224.0.0.1`, `::1` and `fe80::1%eth0`, and
`sock_connect` to `fe80::1%eth0` calling a recorded `loop.getaddrinfo` once
(asyncio's `_ipaddr_info` returns `None` for any host containing `%`). The
others are source facts: the pump called `_require_live` only, the zero
linger was set only in `_abort` during cleanup, and the controller-death test
started its successor after observing the peer's EOF.

- **Destinations (findings 2 and 3).** A pinned address must be globally
  routable unicast (`is_global`, not multicast, not reserved, not IPv6
  site-local) and carry no zone id. The zone refusal is its own check. The
  routability rule is a module predicate, `_routable`, which the suites replace
  with one that admits exactly `127.0.0.1`, the controlled peers' address. That
  is the smallest honest seam: the same kind of substitution the suites
  already make for the socket primitives, visible at every use as the
  `controlled_loopback` fixture (implied by `listeners`), an autouse fixture in
  the containment module, and one line in `_egress_owner.py`. The policy tests
  run the real predicate, and one test proves the seam admits nothing but
  `127.0.0.1`. A policy flag or a test subclass was not taken, because
  production code could select either. Policies that are never dialled now pin
  a routable address. Fifteen refusals, two acceptances.
- **Established streams (finding 4).** The pump now calls `_admit` (liveness,
  then `check_control`, a raise latching stop) after every resumed read,
  before its send. `test_ownership_loss_leaves_an_established_stream_until_the_relay_stops`,
  which pinned the opposite, is replaced by
  `test_control_lost_on_an_established_stream_forwards_nothing_more`: bytes
  before the loss arrive, nothing read after it does, the stream is cut as
  `denied:control`, and the next connect is refused as `stopped`. The cost, one
  synchronous journal read per resumed read, is recorded as a limit. The "only
  at connect points" limit in this section's earlier text is superseded.
- **Queued bytes on controller death (finding 5).** Upstream sockets come from
  `_upstream`, which sets zero linger before anything can queue; `_abort` is
  gone and cleanup closes plainly. New Linux containment test
  `test_controller_death_discards_the_upstream_queue`: a controller floods a
  raw peer that never reads until `/proc/net/tcp` shows a non-empty send queue
  toward it, is killed, and the test asserts the queue gone within 5 s and no
  byte beyond what the peer held. The `sock_sendall` partial-write limit is
  unchanged.
- **Controller death (finding 6).** The claim is now supervisor-observed
  physical quiescence before successor disposal, not an in-process join. The
  death test starts `dispose_acquisition` at the kill and asserts that it
  completes after the peer's EOF and that, when it completes, a non-blocking
  try of the guard's exclusive `flock` on a fresh open file description is
  granted: no process holds any copy. Before the kill the same try is refused,
  the positive control. Two earlier forms scanned descriptors and failed in the
  foundation lane with `EACCES` on `/proc/<pid>/fd`. The first walked every
  process of the uid. The second walked only the controller and its direct
  children, and its pre-kill scan passed: both were readable and held the
  guard. It failed after disposal instead, on a candidate with its original
  start time. Linux makes `/proc/<pid>/fd` root-owned once a task's memory is
  gone (`task_dump_owner`, `fs/proc/base.c`, v6.8). So the likeliest identity
  of that pid is the supervisor after it had exited but before it was reaped.
  That is reasoning: the log does not name the process. The statement that the
  guard reaches only the controller and its supervisor stands, because the
  supervisor launches bubblewrap with `close_fds`. Skipping unreadable
  processes would have read "could not see" as "no holder", so the test now
  observes the lock itself.
- **Mutants (finding 7).** Sixteen new mutants, 45-60: control in the pump, the
  routability terms and the zone, and `parse_connect`'s token count, method,
  version, port grammar, port bound, host grammar, unbracketed and bracketed
  literals, and terminator. Pure parser cases assert each refusal's reason,
  plus the accepting targets at ports 1 and 65535. Mutant 17 is retargeted at
  `_admit` and mutant 40 at the creation-time linger. Two gates, the missing
  separator and the non-ASCII refusal, have no meaningful mutant (state
  review, Mutation inventory).

**Verification of this round (Windows):** the three portable N3b files passed
127 with 4 platform skips. The new address tests failed against the previous
relay: 15 refusals were not raised. `scripts/check_m8_n3b_mutations.py` killed
59 of 60 by assertion, and mutant 29 reported NOT PROVEN as expected.
`uv run verify` on the complete tree: clean ruff, strict mypy over 102 source
files, four import contracts kept, and 2,668 tests passed with 410 platform
skips. Its one failure was again the plan-manifest test, run before the two
documents' manifest lines were refreshed; after the refresh that test passed
on its own, and `sha256sum --check` passed.

**Unexecuted until the next Linux CI run:** the new queue-on-death proof, the
reordered controller-death test with its guard scan, the flood client mode,
the seam inside the owner subprocess, and every containment test under the
routable-address rule. The partial-write limit on Linux keeps its existing
stalled-controller assertion.

### Merged at the reviewed head

**Merged `6dac9f2` (PR #97) on 2026-09-23 UTC from reviewed head `9a94959`.**
Everything in the "unexecuted" list above then ran. The Linux results at that
head are in the [containment run 35816848792](https://github.com/sushiHex/constructicon/actions/runs/35816848792):

- **Proofs.** All 9 N3b containment proofs passed. They include the queue on
  controller death, and the controller-death test observing the guard by its
  lock.
- **Mutants.** 60/60 N3b mutants were killed by assertion, including mutant 29,
  which only runs on Linux. 47/47 N3a mutants and 110/110 native
  review-regression mutants were also killed.
- **Tests.** Containment as the non-sudo service user passed 330; combined,
  mediation and lifecycle passed 135, 87 and 101; `verify` passed 2,764.

The GitHub connector reviewed that exact head and posted no findings. One
Codex pass covered the implementation (`job_b21d1b3a3fbb`). Its fixes were
verified by tests, mutants and this run rather than by another review round.

This section supersedes the "unexecuted" lists above for head `9a94959`. It
qualifies that head and no later changed one. What N3b does not establish
stays as stated under Limits: real vendor destinations, the Codex
`HTTPS_PROXY` path, a phase-separation claim, and anything assigned to N3c.

## M8-D2 reviewed-artifact installation (#94), merged

**Merged `8c1b14e` (PR #99) on 2026-09-23 UTC.** The merge was a squash of
reviewed heads `6e13409` and `5eefafa` onto `6dac9f2`; #94's own files are
byte-identical to `5eefafa`. The design, the operator runbook (R0-R7) and every
review disposition live in
[M8-D2-host-installation.md](M8-D2-host-installation.md).

**The ruling.** Root on the private host executes no repository code. Stock git
proves that commit C is on main's first-parent line, running as the operator,
with grafts disabled. An unprivileged judge then proves four things:

- the staged bytes equal the blobs at C;
- bubblewrap and each root tool are in root custody;
- every destination is absent;
- every destination ancestor is a real directory that only root can write.

Every root write comes after that proof, as a fixed stock sequence: `install`,
then `apparmor_parser --add`. The one root command before the judge is a
read-only `cat` of the kernel's profile list, which the judge needs as input.
That command's custody is proved only afterwards, and the design document
states the exception. An unprivileged verifier recomputes the installed state
against git. `installed` defaults to false.

**Measured.** The Linux `verify` job at the merged tree
([run 35818944312](https://github.com/sushiHex/constructicon/actions/runs/35818944312))
killed 37/37 host-artifact mutants by assertion and passed 2,954 tests. The same
inventory had already run on the reviewed heads. The connector reviewed
`5eefafa` and posted no findings.

**Not established.** CI never executes the real host path: a real `sudo`
install, a real `apparmor_parser` load, the kernel's profile list, and the
probe on the private host. Those run only in a separately authorized operator
session under the runbook. #73 stays open until that evidence exists, and a CI
result never qualifies the host. The runtime and launch closure is carried to
N4 (#77).

## N3c — maintenance, activation and the remaining matrix (#76)

N3c is the rest of issue #76 after N3a and N3b. It was written on the N3b
review head `1ec4943`; its own diff was then applied onto `main` after N3b
merged (`6dac9f2`) and the handoff record (`6c41ca3`), as `0ddb247` (PR #101).
That move was not neutral. The final N3b refuses a loopback egress pin unless
the `_routable` seam is applied, and N3's persistence proof did not apply it,
so it failed in the foundation lane at `0ddb247`. The fixes for that and for
the PR review are recorded under "PR #101 review fixes" below. The pre-code
[state review](M8-N3c-state-review.md) was reviewed once by Codex
(`gpt-5.6-terra`, job `job_2036d3ab16a8`) and amended in `dd1a36b`. Its six
owner questions were decided by the orchestrator before any code, and the
decisions and their reasons are recorded in that document. The one Codex pass
for this PR was spent on the design; **the implementation has had no
independent-model review.**

What changed in `src/`, and nothing else:

- `operator_store.py` gains a third state of `active.json`, the withdrawal
  record `{"generation_floor", "key", "schema_version"}`. Every existing reader
  refuses it by shape, so no reader changed. There are two offline helpers
  beside publication. `maintain_offline` is a context manager: it takes the
  retained lock and re-proves the bundle, store and lock identities under it.
  It computes the floor from the descriptor inventory, durably replaces
  `active.json` with the withdrawal record, and only then yields the store
  locator; its exit only closes. `activate_offline` requires this key's
  withdrawal record, a generation above its floor, and a descriptor that passes
  the provider's own descriptor law (`_check_descriptor`, extracted from
  `_check_selection`) against the qualified identity and the live objects. One
  ownership law (`_seal_metadata_fd`: the directory's group, `0440`) covers
  `_publish_new` and the new `_replace_metadata`. Publication now holds the
  retained lock from before it reads the anchor and inventory until its
  descriptor is published, and takes the same `wait_s`: finite, not a bool, at
  least 0; 0 is exactly one attempt. The `/proc/self/mountinfo` read became
  `_read_mountinfo()` so the parse runs portably. After the PR review
  (decision 7), maintenance also re-anchors a bundle after a reboot. It does
  so under the lock, after the withdrawal is durable, and only when every
  stable field of the bundle's identity is unchanged and the boot id changed.
  `_anchor_is_current` now holds the anchor check that `_open_offline` used to
  inline.
- `codex.py` forces `OVERAGE_NOT_ENFORCED` on an overages-forbidden profile.
  It reads the sealed overage literal and nothing else, and no reason tuple
  can clear it. The READ and WRITE accepting-path fixtures move to
  `operator_authorized` under owner decision 2: that literal is not the
  approval ADR 0021 requires, and the default unavailability keeps it
  unavailable in production.

No journal record, service, runtime maintenance API, walker change, L0 field
or reader branch was added. Both store law digests move, because they digest
`operator_store.py`: every existing descriptor refuses until it is republished.
The CI fixture publishes afresh on every run.

### Operator procedure

This is the procedure the decisions assign to the operator. Nothing here
automates it.

1. Recover or cancel every run of the old generation under the old assembly.
   That assembly's `reconcile` never reads the selection, so it can still
   dispose after activation (S12). A new-generation assembly refuses the old
   reference without disposal (S13).
2. `maintain_offline(root, key, wait_s=...)`. It refuses, having written
   nothing, while any acquisition is materialized or any supervisor survives
   its controller. Portably that is S2 and S20. On Linux, a paused helper
   holding the real lock refuses a contender (R2, R3). A surviving supervisor
   keeps that same lock description (the N3a owner-death evidence). Inside the
   context, and only there, run the vendor login against `store_path`.
   **After a reboot**, start here. Providers, publication and activation
   refuse until maintenance re-anchors the bundle (decision 7). Then publish
   and activate a new generation, because every earlier descriptor names the
   previous boot.
3. Exit the context, then publish the next generation. Publication cannot run
   inside the context, because the lock is per open file description. First
   provisioning is: publish g1, maintain and log in, publish g2, activate g2.
4. Qualify the published generation. The qualified identity is operator
   input (decision 3).
5. `activate_offline(root, key, g, qualified=..., wait_s=...)`.
6. When a helper raises, read the state with the strict readers rather than
   assume it. After a directory `fsync` failure the new record is already
   visible. A second maintenance withdraws again, and a second activation over
   an active state refuses (U4).
7. A `.pending-*` left in `descriptors/` by a killed publication disables
   selection, maintenance and publication until the operator removes it by
   hand, having confirmed that no publisher is running (S10). In the bundle
   directory it depends on who left it. A maintenance or activation killed
   before its rename leaves an inert temporary, because no reader lists that
   directory (R2's temporary kill point). A first publication killed between
   linking and unlinking the anchor leaves a second name for `anchor.json`.
   Every reader and helper then refuses on the link count until it is removed
   (R7). Remove either kind the same way.

### Local evidence

Everything below ran on Windows 11 with Python 3.11. The portable doubles
(`StoreWorld`) substitute only the descriptor, identity, flock and writer
primitives. They prove ordering, parsing and lifecycle logic, never flock,
ownership, `fsync` or mounts.

**Every count in this subsection is pre-move.** The counts were taken on the
tree based on `1ec4943`, at commits `8192b7c` and `607c20b`. Those commits
survive only on the local branch `n3c-backup`, so no reviewer can reproduce
them. The current evidence is under "PR #101 review fixes".

- `test_operator_store_maintenance.py` (S, 73 tests) drives every helper rule
  in both directions: exposure strictly after the durable withdrawal, with the
  order recorded; a held lock and a failed withdrawal leave the body unrun;
  every provider refuses inside the context; objects replaced during the wait
  refuse under all three helpers, and unchanged objects proceed; exit releases
  the lock and never activates; maintenance refuses while an acquisition is
  materialized; a materializer waiting through a whole cycle refuses after
  it, and a sealed successor is accepted; the full maintain, publish, activate cycle executes to
  success, and the retired provider refuses; a descriptor published before
  maintenance cannot be activated; absent, active, malformed and other-key
  states refuse activation; the floor itself and below it refuse; the
  qualified identity, laws, live store and lock, and the descriptor's own key
  and generation are all checked; an orphaned `.pending-*` disables
  everything until it is removed, through the real `_descriptor_names`;
  store bytes survive close, reconcile, maintenance and activation; recovery
  across a generation (S12, S13); seven mount-topology inputs; publication
  waits for a held handle and for a maintenance context; and `wait_s`
  validation and exact single-attempt semantics.
- `test_codex_matrix.py` (C, 28 tests) covers the forced reason over posture,
  plan label, binding and overage; that a caller's reason tuple can neither
  clear nor duplicate it; and `describe()`. It also covers a WRITE
  conversation refused at the pre-turn reading, which never sends
  `thread/start` or `dynamicTools` and never calls the worker. With an early
  callback it is refused before `account/read`. The accepting WRITE control is
  here too. Then: an API-key switch at the pre-acceptance reading, with exactly
  the six clean methods and one launch; the pinned `account/rateLimits/updated`
  name discarding a turn; and a `usageLimitExceeded` turn, published as
  partial with `rate_limit` `None`, six methods, one launch, no spend or login
  request, and every field inside its bound. Its bytes do not depend on a
  profile.
- The field-walking surface test now also walks the withdrawal record as a
  terminal state. The limit-reached partial walks every field bound (C5).
- `scripts/check_m8_n3c_mutations.py` (pre-move): 22 of 28 killed by
  assertion. The six Linux unit mutants (9, 10, 11, 15, 24, 27) reported NOT
  PROVEN on Windows, where their tests skip. That is expected, and they are
  not kills. At `0ddb247` the review reproduced only 19. Mutants 20-22 hit the
  harness's 60 s limit, because every case of their killing test seeded a git
  authority.
- The retained inventories (pre-move): N3a 47/47 after two
  changes. The eight `_check_selection` anchors that compare the descriptor
  were retargeted to `_check_descriptor`, with the same killing tests. The
  inventory also found one defect in this change: the pre-existing mutant
  "zero metadata write cannot be treated as one byte of progress" had begun
  to error at `_fchown` on Windows (NOT PROVEN), because the new seal sits
  between the write loop and the link. Its test now substitutes
  `_seal_metadata_fd`, as its sibling does, and the mutant is killed by
  assertion again. N3b 42/43, which was the 43-mutant inventory of
  `1ec4943`; the merged N3b has 60. N2 82/82 and N2 WRITE 49/49, all by
  assertion, with the fixtures on `operator_authorized`.
- `uv run verify` (pre-move, on `607c20b` plus these documents): clean ruff,
  strict mypy over 102 source files, four import contracts kept, and 2,739
  tests passed with 429 platform skips.

### Self-review

A narrow pass over this change asked three questions: what state exists when
each `await` resumes, what is decided by negative inference, and which tests
only refuse. What it found:

- **The design's S16 was never written.** It is now: a candidate waits on the
  lock while a withdrawal and then an activation land, refuses after the wait,
  and a sealed successor is accepted in the same run.
- **S4 only refused.** It now also has a permitting case: the same wait over
  unchanged objects proceeds, under all three helpers.
- **Decision 6's check was proved only indirectly.** S20 was added.
- **The inventory found a defect inside the change.** This is the N3a
  zero-write mutant described above.
- **Two limits were added** (below): the pre-lock transient refusal, and the
  conformance revisions that activation does not check.

The new operator-store code is synchronous, so it has no `await`. The
provider's awaits are unchanged. Their composition with the new writers is
S16, portably, and R5 in a fresh interpreter. No success is inferred from an
absence. Activation refuses an absent `active.json`. The withdrawal floor is
read from the inventory under the lock. `_replace_metadata` marks the replace
done only after `os.replace` returns. The receipt exists only after the
directory `fsync`.

### Deviations from the design

- **File names.** The root-lane proofs are
  `test_operator_store_maintenance_restart.py`, not additions to
  `test_operator_store_restart.py`. The service-lane proofs are
  `test_operator_store_persistence.py`, not additions to
  `test_operator_store_containment.py`. The workflow pin requires each file to
  run in exactly one step, and N3c has its own step.
- **Publication re-proves its objects under the lock.** The design required
  publication only to take the lock. All three helpers share `_hold_offline`,
  which also reopens and compares identities after the wait. Without it, a
  descriptor would carry identities observed before the wait.
- **S20 was added** (maintenance refuses while an acquisition is
  materialized). Decision 6 asks for its check to be proved directly, and
  S17 and S18 prove only maintenance against maintenance and publication
  against a handle.
- **C2's early-callback variant** is refused before `account/read` (the
  methods are `initialize, initialized`). That is stronger than the design's
  three, and it is pinned as observed.
- **S10 substitutes `os.scandir`** for the duration of the test, so the real
  `_descriptor_names` filter runs portably. No further primitive was
  extracted from `src/`.
- **Three pre-existing tests substitute one more primitive:**
  `_seal_metadata_fd` in the two `_publish_new` fault tests, and `_flock` in
  the oversized-publisher test. Their subjects are unchanged.
- **N3 compares only the native launches' arguments.** Each exchange also runs
  its mount-free probe through `argv`. Both launches use one acquisition id,
  so the leaf path is identical by construction and any difference is the
  store's doing. Its write denials accept `EROFS`, `EACCES` or `EPERM`: which
  one a read-only bind over a root-owned directory reports is kernel ordering
  that nothing here measured. The observed errno is written to the evidence.
- **U1 binds the group** with a supplementary group when the runner user has
  one, and records the `fchown` call either way.

### Limits and unexecuted proofs

The state review's limits apply unchanged: power loss, the trusted operator
and same-uid host processes, unobserved store content, qualification as
operator input (decision 3), qualifying a withdrawn generation, orphaned
temporaries, publication needing quiescence, old-generation recovery as a
procedure (decision 6), store content inert to constructicon but not
necessarily to the vendor (N4), the mid-turn root substitution proved in
halves, and overage (decision 2). Two limits were added by self-review:

- **A pre-lock candidate can refuse transiently.** `open_candidate` reads the
  inventory before the lock, so a publication in progress can show it a
  `.pending-*` and refuse it. That costs availability and is not a widening.
  Under the lock the race is closed, as designed.
- **Activation neither records nor checks the qualified identity's two
  conformance revisions.** It checks the binding digest and both laws. The
  revisions travel only in the provider's sealed identity, as they did before
  N3c.

Where the Linux proofs run, and what has run, is below. Windows skips are
not passes.

- **U1-U4** (`test_operator_store_replace.py`: the real writer's order, mode
  and group, failed replaces, the directory `fsync` failure through both
  helpers, and the mount-id comparisons in `_open_bundle`) run in the
  unprivileged Linux `verify` job, not in the foundation step. At `0ddb247`
  that job passed with 3,067 tests and no failure. Its log is quiet and names
  no test, but this file skips only off Linux.
- **R and N** run in the foundation step "Prove N3c maintenance, refresh and
  non-widening", with evidence in `n3c-*.json`:
  - R is `test_operator_store_maintenance_restart.py`: the full cycle read as
    `m8-service`, `SIGKILL` at each helper's replace, bind-mount aliases, a
    reader waiting through a cycle, a simulated reboot and a second anchor
    name.
  - N is `test_operator_store_persistence.py`: in-place and rename refresh
    with both checks, cleanup bytes, persistence through the real relay, and
    the service refused at the bundle write.
- **The six Linux unit mutants** (9, 10, 11, 15, 24, 27) run only in that
  step's inventory.

`vendor_conformance_qualified` stays false.

### PR #101 review fixes

Two sources found these: an adversarial review of `0ddb247` (five
dimensions, every finding reproduced by two independent skeptics) and the
first Linux CI run on that head. Each premise was reproduced here before it
was fixed. The fixes were test-first: the three reboot tests failed before the
re-anchor existed. Still no independent-model review has run on the
implementation.

**Linux CI at `0ddb247`** (M8 containment run `35903421821`; verify run
`35903421679`):

- The foundation lane's N3c step passed R1-R5 (seven tests) and N1 and N4.
- N3 failed at `policy_for`, which reported "an egress destination pins a
  globally routable address". The step stopped there, so the N3c inventory,
  and with it the six Linux unit mutants, never ran.
- Every other proof lane passed. The Linux `verify` job passed with 3,067
  tests and 325 skips.

| Finding | Class | Disposition |
| --- | --- | --- |
| P1: N3 built its policy without N3b's `_routable` seam | introduced by the move | Fixed. N3 requests `controlled_loopback`, as N3b's lane does, and constructs its peers inside the `try`. Driven locally with only the Linux collaborators stubbed, the real body raised the CI error without the seam and reached the launch with it. Everything after that point (relay counters, errnos, argument equality) has still never executed |
| P2: a reboot stranded the binding, because the boot-bound anchor refused every helper | pre-existing (N3a), surfaced by N3c | Fixed by decision 7 (state review). Maintenance re-anchors the same physical bundle. S covers a reboot permit; nine identity cases (a permit, a same-boot mount change, and each of seven stable fields); and a failed re-anchor whose rerun completes. R6 simulates the reboot in fresh interpreters by substituting the kernel boot id. Mutants 42-50 |
| P2: the floor was correct only because the inventory sorts numerically, and no input showed it | introduced | Inventories {1, 9, 10} and {1, 3} now run through the real `_descriptor_names`, with the scan order reversed. The double now orders names numerically. Mutants 30 and 31 |
| P2: mountinfo octal decoding was never exercised | introduced (row 8 took the check into scope) | Escaped space, tab and backslash inputs that bind; the size bound at its limit; malformed lines. Mutants 32-35 |
| P2: the evidence counts were pre-move | introduced by the move | Relabelled as pre-move above. This head's numbers are below |
| P3: mutants 20-22 hit the 60 s harness limit | introduced | The 16-case test requests the git-seeded binding only for its bound cases (about 90 s down to 13 s here). The three mutants target single unbound nodes. The limit is unchanged |
| P3: the bundle-directory `.pending-*` row cited U2, which never creates that state, and was false for the anchor | introduced | Row and procedure corrected. R2 gains a kill point with the rename temporary on disk, which proves it inert. R7 plants a second name for the anchor, which refuses until removed. R2 and R3 now also show that the paused helper holds the real lock: a `wait_s=0` contender refuses and leaves `active.json` unchanged |
| P3: gates with neither an input nor a mutant | introduced | New inputs: an anchor for another key, or a different bundle in the same boot, under maintenance and activation; a withdrawal record with schema 2, an extra key or a bool floor; activation's generation guard and its sealed-identity guard, both before filesystem entry. Mutants 36-41 |
| P3: U1-U4's run location; design mutant 26 against the implemented one | introduced | The limits above now say U1-U4 run in the Linux `verify` job. The design's row 26 is marked as two mutants: 26, the key half, and 29, the generation half |
| Stale line citations in the inventory table | introduced by the move | Refreshed against this head with a script that locates each cited line's text. Row 15's two fixture citations still describe the state before N3c |
| Disputed: the overage reason keys on `== "forbidden"` | not acted on | The contract field is `Literal["forbidden", "operator_authorized"]` on a frozen, `extra="forbid"` model. No `src/` path builds a profile through `model_copy` or `model_construct`, the only ways to bypass validation. Inverting the test would guard against unvalidated construction, which nothing in `src/` performs |

Evidence at this head, on Windows 11 with Python 3.11:

- Tests by file: S 107, C 28, U 11, R 10, N 3. U, R and N are Linux-only.
- `scripts/check_m8_n3c_mutations.py`: **44 of 50 killed by assertion.** The
  six Linux unit mutants were NOT PROVEN, as expected. Of the original 28,
  22 are killed and 6 are Linux-only.
- N3a 47/47. N3b 59/60 (mutant 29 is Linux-only and NOT PROVEN). N2 82/82.
  N2 WRITE 49/49.
- `uv run verify` passed: clean ruff, strict mypy over 102 source files, four
  import contracts kept, and 2,881 tests passed with 548 platform skips. After
  that run only this entry and its manifest line changed. Both were rechecked
  with `sha256sum --check` and the plan-manifest test.

Still unexecuted until Linux CI reruns: R2's temporary kill point, R6, R7,
the R2/R3 lock controls, N3 past its policy, and the six Linux unit mutants.

**Self-review of these fixes:**

- The re-anchor follows the durable withdrawal. A crash between the two
  leaves a withdrawn binding with the old anchor, which the next maintenance
  repairs (tested).
- Whether to re-anchor is decided again under the lock.
- `False` from `_anchor_is_current` is never a default. It requires a
  changed boot id and seven equal stable fields.
- Maintenance is still the only helper that may repair the anchor. A
  provider, a publication or an activation after a reboot refuses.

**One limit added:** a host whose device numbering changes across boots
(`dev`), or an operator who adds a directory to the bundle (`nlink`), makes
maintenance refuse after a reboot. That fails closed and needs a new binding.

### Re-anchor attack fixes

A three-lens attack on the re-anchor (`389b0d3`) found no P1 or P2. No
different bundle could be adopted: fourteen single-field variations all
refused. It found four reproduced P3s, fixed here test-first:

- **A lock replaced across a reboot was accepted.** Instance history matched
  old descriptors by instance, which includes the boot id. Both new tests
  failed before the fix. Decided (option 1, recorded as part of decision 7):
  publication and `_check_descriptor` match an old descriptor's store by its
  boot-independent fields, and then require the lock to match on the same
  fields. The tests run both directions at both sites; mutants 53 and 54. The
  N3a mutant "historical lock identity cannot be remapped" then went NOT
  PROVEN, because the new rule also refuses its remap to another object. Its
  test gains a case the new rule does not look at (same object, other owner),
  and the mutant is killed again.
- **The re-anchor-after-withdrawal order was unpinned.** The failed-re-anchor
  test now asserts that the withdrawal is recorded when the anchor write
  starts. Mutant 51 swaps the two writes.
- **The reboot decision under the lock was untested.** A new case makes a
  genuine reboot pass the pre-lock check and then substitutes the anchor
  during the wait; maintenance refuses and writes nothing. Mutant 52 drops
  the under-lock rule.
- **The crash table lacked the re-anchor points, and M1 still called the
  pre-lock check exact.** The state review adds M3a and M7a-M7c and a
  crash-matrix row, and corrects M1. Only an injected failure proves the
  re-anchor points. Process death inside the re-anchor is unproved: no
  root-lane kill point sits there.

Evidence, on Windows 11 with Python 3.11:

- S now has 112 tests.
- `scripts/check_m8_n3c_mutations.py`: 48 of 54 killed by assertion; the six
  Linux unit mutants NOT PROVEN, as expected.
- N3a 47/47. The other inventories do not target the changed functions and
  were not rerun; their results at `389b0d3` are above.
- `uv run verify` on this code: clean ruff, strict mypy over 102 source
  files, four import contracts kept, and 2,886 tests passed with 548
  platform skips. The one failure was the plan-manifest digest check, because
  these documents had not yet been refreshed. After the refresh, the
  plan-manifest test and `sha256sum --check` passed. After that only this
  entry and its manifest line changed, and both were rechecked.

### Merged at the reviewed head

**Merged `a8a8f63` (PR #101) on 2026-09-24 UTC from head `3810b10`.** That
head is the reviewed commits `0ddb247..34dd520`, applied onto `main` `d5c0760`
after the N4 bridge. The conflicts were union-only, and the N3c code and test
files are byte-identical to `34dd520`. Every "unexecuted" item above then ran
([containment run 35938902900](https://github.com/sushiHex/constructicon/actions/runs/35938902900)).

- **N3c proofs.** The root lane passed 10/10: the crash matrix with process
  death at each kill point, the simulated reboot (R6), bind-mount aliases, the
  second-name anchor (R7), and the lock controls. The service lane passed 3/3:
  refresh, cleanup bytes, and persistence and non-widening through the real
  relay.
- **Earlier slices.** N3a (20 + 3), N3b (9) and the N4 bridge (6) passed in the
  same lane.
- **Mutants.** 291 were killed by assertion across the lane's inventories,
  including N3c's six Linux-only mutants. None is NOT PROVEN.
- **Verify** is green.

The GitHub connector reviewed `3810b10` and posted no findings. This section
supersedes the "unexecuted" lists above for that head. It qualifies that head
and no later changed one. The limits above still stand: the operator-supplied
qualification record; process death inside the re-anchor, which is unproved on
the root lane; and the vendor's real refresh and overage behaviour, which is N4
and N5 work.

## N4 preparation: proxy bridge

Credential-free preparation for N4 (#77), on branch `m8/n4-proxy-bridge` off
`6c41ca3`. It closes the gap N3b carried: "the pinned Codex client's
`HTTPS_PROXY` path". The design, the pinned-source census and the review
disposition live in [M8-N4-proxy-bridge.md](M8-N4-proxy-bridge.md). It was
committed as `c1c3131`, reviewed once by Codex (`gpt-5.6-terra`, effort high,
job `job_8257a0ea4e68`) and amended in `afb1ffc`: one P1 whose premise was
narrowed, four P2 and one P3 adopted, one installer note carried. No second
Codex round was run.

**The finding that required code.** The pinned client reaches a proxy only as
`http://host:port` over TCP: reqwest's environment proxy for HTTPS and the
forked tungstenite's for WSS. No transport accepts a Unix-socket proxy, and a
`unix://` value in `HTTPS_PROXY` is silently dropped by hyper-util, so the
client would go direct and fail. The N3b leaf is a Unix socket, so a shim is
required.

**What was built.** One standalone stdlib file,
`substrate/executors/_egress_bridge.py`, installed in the immutable runtime at
`/usr/libexec/constructicon-egress-bridge.py` beside the supervisor.
`LinuxLauncher.argv` prefixes the vendor command with it exactly when it mounts
the egress leaf, so no worker and no leaf-less launch gets one. The script:

1. refuses unless `/vendor-egress.sock` is a socket;
2. binds `127.0.0.1:18080`;
3. forks the forwarder, which drops the payload's stdio and every other
   descriptor and then writes one readiness byte;
4. reads that byte, treating EOF as a refusal;
5. `execve`s the vendor with `HTTPS_PROXY=http://127.0.0.1:18080` added.

The forwarder joins each accepted connection, byte for byte and with
half-close, to one new leaf connection. It parses nothing, answers nothing and
never writes a byte it did not read. It is not a boundary: the relay is. PID 1
terminates and reaps it with the payload. The relay, its policy and its five
egress identity digests are unchanged. The launcher revision and the runtime
digest change.

**Relay compatibility, by source.** The relayed dependency reads say that
hyper-util's tunnel writes `CONNECT host:port HTTP/1.1` + `Host` + a lower-case
`user-agent` line, and that tungstenite adds `Proxy-Connection: Keep-Alive`.
`parse_connect` judges only the request line (`egress.py:204-227`). The relay's
reply is exactly `HTTP/1.1 200 Connection established\r\n\r\n` with nothing
after it before the hello (`egress.py:64, 648`), which reqwest's
`HTTP/1.1 200` rule and tungstenite's dropped-tail read both accept. The pinned
user agent is built from the adapter's fixed `clientInfo`, an empty environment
and the immutable runtime, so a realistic head is about 200 bytes against the
8192-byte bound. The bound is unchanged.

### Local evidence (Windows 11, Python 3.11)

- `tests/substrate/test_egress_bridge.py`: 12 passed, 5 Linux skips. The
  forwarder moves bytes unchanged both ways (256 KiB out, 200 KB of
  non-HTTP bytes in) and half-closes each way. A failed leaf dial closes the
  client with zero bytes. The environment is exactly inherited plus
  `HTTPS_PROXY`. The leaf check and the script refuse an absent leaf, a
  regular-file leaf and a relative command before binding. Both client head
  shapes pass **through the forwarder into the real N3b relay**: accepted,
  replied to with exactly the established line and nothing after it, the hello
  forwarded byte-identical, and the decoy refused as `destination`.
- `tests/substrate/test_egress_launch.py`: the prefix follows the leaf, is
  absent without one and absent for a worker.
- `scripts/check_m8_n4_bridge_mutations.py`: 13 of 20 killed by assertion.
  Mutants 4, 13-17 and 20 reported NOT PROVEN, as expected on Windows; their
  killing tests are Linux-only. Two mutants (1, 12) first reported NOT PROVEN
  because their tests errored rather than asserted. A timed-out read and a
  `None` listener were both harness errors. The tests were sharpened: read to
  EOF and compare, and use a closable fake listener.
- Retained inventories against the changed `argv`: N3b 59/60 (mutant 29 NOT
  PROVEN on Windows as before), N3a 47/47. The containment and duplex
  inventories killed 16 and 13, and their NOT PROVEN mutants all need the
  provisioned lane. None reported an anchor mismatch.
- `PYTHONIOENCODING=utf-8 uv run --python 3.11 verify` on the implemented tree
  (`56713c6` plus uncommitted record text): clean ruff, strict mypy over 103
  source files, four import contracts kept. 2,757 tests passed and 532 were
  skipped for platform. The one failure was
  `test_docs_validation_accepts_the_actual_repository`, run before these
  documents' manifest lines were refreshed. After the refresh that test passed
  on its own, and `sha256sum --check` passed.

**Deviations from the design, found in implementation.**

- On Windows, `shutdown(SHUT_RDWR)` does not wake a `recv` blocked in another
  thread. A probe measured a blocked `recv` still blocked 2 s after the
  shutdown. The forwarder is Linux-only and relies on Linux's behaviour, so the
  two reset tests and mutant 4 are Linux-only. The design document says so.
- Python's descriptors are close-on-exec (PEP 446), so the parent's explicit
  listener close before `execve` is a second, independent guarantee. Mutant 17
  proves the close exists, not that it is the only protection.
- **A defect inside the design, found by self-review.** The script's own
  interpreter ignores `SIGPIPE` and `SIGXFSZ`, and `execve` keeps ignored
  signals. PID 1 launches through `subprocess`, whose `restore_signals`
  restored them, so without a fix the bridge would have changed the vendor's
  signal dispositions. Under the supervisor's `RLIMIT_FSIZE` that turns a
  `SIGXFSZ` kill into an `EFBIG` error. The script now resets both to
  `SIG_DFL` before `execve`. A Linux unit test asserts it at the exec point,
  and mutant 20 covers it. This is reasoning about CPython and the kernel until
  the Linux job runs the test.

### Limits and unexecuted proofs

These have **no execution** until Linux CI runs them, and Windows skips are not
passes:

- the fork, readiness, isolation and exec unit tests and mutants 4, 13-17 and 20
  (unprivileged `verify` job, and the foundation lane's mutation step);
- the bridge inside the real zone (`test_native_egress_bridge.py`, the new
  foundation step "Prove the N4 proxy bridge in the native zone", evidence
  `n4-*.json`): an environment-proxy client reaching the pinned peer through
  forwarder, leaf and relay; the decoy refused by the relay; `ENETUNREACH`
  direct; the zone's only listener at `127.0.0.1:18080`; the forwarder's stdio
  on `/dev/null`; the exact CONNECT preface;
- **the pinned binary through the bridge**: `codex app-server` with
  `[analytics] enabled` and an `otlp-http` metrics exporter aimed at a
  controlled peer, no login and no model request. It must export
  `codex.process.start` on stdin EOF through `HTTPS_PROXY`. The source says it
  will; only the lane can say it does. The foundation lane now downloads the
  pinned package and builds a startup image for this step;
- N3b's probe with the new listener inventory, which now runs under the
  bridge, like every leaf-bearing launch.

Carried to N4: the websocket and the other reqwest client families (proved
from source only), `otlp-grpc` and the code-mode `unix:` transport (unknown or
bypassing), refused hosts unnamed by the relay, and the private-host runtime
closure, which must carry the script. The provider stays unavailable and
`vendor_conformance_qualified` stays false.

### First Linux CI run (PR #103)

The first run was at head `cce8651`, the diff applied onto main `c950016`.
[Containment run 35911952425](https://github.com/sushiHex/constructicon/actions/runs/35911952425)
is the slice's first physical evidence.

**Passed:**

- **The pinned client through the bridge.**
  `test_the_pinned_client_reaches_a_controlled_peer_through_the_bridge` ran
  the pinned `codex app-server` with no login and no model request. It
  exported `codex.process.start` to the controlled peer via `HTTPS_PROXY`, the
  forwarder, the leaf and the relay: one `POST /v1/metrics`, and the relay
  counted `accepted: 1`. The captured preface was exactly
  `CONNECT allowed.invalid:<port> HTTP/1.1\r\nHost: allowed.invalid:<port>\r\n\r\n`.
- **N3b under the bridge.** All nine N3b containment proofs passed with the
  bridge prefix, including the new listener inventory.
- **`verify` on Linux:** 2,972 tests passed, including this slice's fork,
  readiness, isolation, exec and signal unit tests.

**An unsolicited startup connection.** The same pinned run also opened
`CONNECT chatgpt.com:443 HTTP/1.1` with no `user-agent` line, before any login.
The relay denied it as `destination`. The evidence names the host because the
test records every head the relay's parser judged. The source path behind it
is not identified here. One candidate is the curated-plugin export fallback
(`core-plugins/src/startup_sync.rs:26`), but that is unverified. This is N4
startup-traffic evidence: the census's claim that such paths fire without a
model request is now measured once.

**Failed:** two tests, one cause.

| Failure | Cause | Class | Fix |
| --- | --- | --- | --- |
| `test_an_environment_proxy_client_reaches_only_the_pinned_peer`: `facts.get("ssl")` was `None` | The bridge proof's in-zone client never reported an `ssl` fact, unlike N3b's client, whose precondition `facts_of` it reuses. The fact was absent, not false: the client imports `ssl` and ran in the production runtime. The precondition's message ("ssl cannot import") claimed the negative the absence did not show | introduced (test) | Test first: `test_the_ssl_precondition_names_an_absent_fact_apart_from_a_failed_import` and `test_the_bridge_client_reports_the_ssl_fact` both failed before the fix. `facts_of` now fails an absent fact as "absent" and a false one as "cannot import". The client reports `ssl` the way N3b's does, after a guarded import |
| `test_no_evidence_file_contains_key_material`: only `n4-pinned-client.json` | Consequence of the first: `n4-bridge.json` is written after the failed assertion | consequence | None needed |

The N4 mutation step did not run, because pytest failed first.

**Verification of this correction (Windows):** the four portable bridge and
egress files passed 24 with 17 platform skips.
`scripts/check_m8_n4_bridge_mutations.py` killed 13 of 20, unchanged, with the
seven Linux-only mutants NOT PROVEN. `uv run verify` on the corrected tree:
clean ruff, strict mypy over 103 source files, four import contracts kept.
2,760 tests passed and 532 were skipped for platform. The one failure was
`test_docs_validation_accepts_the_actual_repository`, a digest mismatch on
this record, run before its manifest line was refreshed. After the refresh
that test passed on its own, and `sha256sum --check` passed.

**Unexecuted until the next Linux CI run:** the environment-proxy client proof
and its evidence file, and the N4 mutation step (mutants 4, 13-17 and 20).

### Merged at the reviewed head

**Merged `d5c0760` (PR #103) on 2026-09-24 UTC from head `fd6bd8b`.** Every
unexecuted item above then ran
([containment run 35935694711](https://github.com/sushiHex/constructicon/actions/runs/35935694711)).

- **Bridge proofs.** All 6 passed:
  - the environment-proxy client, through forwarder, leaf and relay to the
    pinned peer;
  - the decoy refusal;
  - the in-zone listener inventory;
  - the pinned `codex app-server` exporting through `HTTPS_PROXY`, with no
    login and no model request.
- **N3b under the bridge prefix.** Its 9 proofs passed.
- **Mutants.** 237 were killed by assertion, including the seven Linux-only
  bridge mutants. None is NOT PROVEN.

The one intermediate failure was the half-close mutant. Its test died on
`ENOTCONN`, not an assertion, so it reported NOT PROVEN. The test now fails by
assertion.

The connector reviewed `fd6bd8b` and posted no findings. The limits above
stand:
- the websocket family is proved by source only;
- containment is the relay's claim alone;
- the unsolicited startup `CONNECT chatgpt.com:443` has not been traced to its
  code path, and belongs to N4's startup-traffic work.

## N4 preparation: narrow native layout

This is a preparatory slice for N4 (#77), on branch `m8/n4-layout` off `9006f93`. It
implements section 1 of the N4 state review, as the orchestrator decided
(question 2: a separate PR, limited to the layout). The N4 lane stacks on it.
That review, `M8-N4-state-review.md`, travels with the lane on
`m8/n4-startup`. It found one gap and closes it: **in production, nothing
delivered the sealed configuration to the client, and nothing routed the
store's credential to it.**
- The provider only digested `configuration` (`codex.py:1797, 1851`).
- The store was bound at `/vendor-store`, which is not `CODEX_HOME`.

A real login would never have been found, and the client would have run on
built-in defaults.

**What changed in `src/`:**

- `linux.py`:
  - `NativeStoreMount` drops `path` and carries three distinct descriptors:
    `lock_fd`, `configuration_fd` and `credential_fd`.
  - `argv` replaces `--bind <store> /vendor-store` with a fresh
    `/tmp/home/.codex` inside the existing tmpfs. The sealed configuration is
    bound there with `--ro-bind-data <fd>`, the store's `auth.json` with
    `--bind-fd <fd>`, and `CODEX_HOME` is set explicitly.
  - `_run` refuses a mount descriptor that is also a guard. It passes both
    mount descriptors to the supervisor, with `--mount-fds=a,b`.
  - `sealed_data_fd(data)` writes a memfd, seals it (`WRITE|GROW|SHRINK|SEAL`),
    re-reads it and rewinds it.
- `_supervisor.py`: it takes `--mount-fds`, `fstat`s each descriptor, passes
  them only to bubblewrap's `pass_fds` (never to the payload, since trusted
  PID 1 launches with `close_fds`), and closes them at exit.
- `operator_store.py`:
  - `CREDENTIAL_FILE = "auth.json"`;
  - `open_credential(opened)`, which is `O_PATH|O_NOFOLLOW|O_CLOEXEC`
    relative to the identity-checked store descriptor, so the file is never
    read;
  - `check_credential(fd, owner_uid)`: a regular file, one link, the store
    directory's owner, mode exactly `0600`;
  - `BindingStore.open_credential(held)`.

  The layout and mount-lock laws move, because they digest this module.
- `codex.py`:
  - The provider retains `configuration`, which its existing drift check has
    already bound to the published digest.
  - `_converse` opens the credential from the held store. On refusal it
    publishes `unavailable` before any launch. It then seals the
    configuration and closes both descriptors in a `finally`. That runs only
    after the exchange task has ended, because awaiting a task returns, even
    for a cancelled caller, only once the task is done.

`scripts/ci/build_m8_runtime.py` no longer creates a `vendor-store` mount
point. `scripts/ci/build_m8_store_fixture.py` now writes harmless
`auth.json` bytes (mode `0600`, owned by the service) in place of
`fixture-marker`. No L0 field, journal record, walker change or availability
change is made. `LinuxLauncher.revision`, `runtime_digest`, `ADAPTER_REVISION`
and both store laws all move, so every launch identity and descriptor has to be
re-derived. The CI fixtures re-derive them on every run.

### Local evidence (Windows 11, Python 3.11)

- New `tests/substrate/test_operator_store_credential.py`: 19 passed and 1
  skipped (the memfd seal test, which is Linux-only).
  - Accepting cases: the checked descriptor is handed over, and the owner
    compared is the store directory's.
  - Refusals, each confirmed closed with `fstat`: group-readable, read-only,
    a second name, another owner, a directory, a symlink and an absent file.
  - The real open is `O_PATH|O_NOFOLLOW|O_CLOEXEC` relative to the store
    descriptor, and never reads.
  - Only mode `0600` passes.
- `test_native_store_launch.py` (17 passed):
  - the exact eleven-argument layout, with no `--bind` and no `/vendor-store`;
  - a worker launch gets no codex home;
  - the three descriptors must be distinct;
  - a mount descriptor that is also a guard never reaches the binding check;
  - the supervisor alone receives `--mount-fds` right after `--report-fd` and
    inherits both descriptors, and a worker launch gets neither;
  - `sealed_data_fd` refuses off Linux.
- `test_codex_store.py`:
  - the three-checks test now asserts that the zone received the very
    credential descriptor that was opened, and the provider's own
    configuration bytes, and that both are closed after the exchange;
  - six credential shapes refuse before any launch, with an accepting twin;
  - a failed seal closes the credential without launching;
  - a cancelled caller's descriptors close only after its exchange ends.
- `tests/operator_store_world.py`: `StoreWorld.install` now also substitutes
  the credential open and `fstat` primitives, and the sealed memfd. The
  memfd substitute is an ordinary descriptor holding the same bytes. The rule
  itself, and descriptor ownership, stay production code.
- Mutation inventories:
  - `scripts/check_m8_n3a_mutations.py` gains L1-L20 and retargets five N3a
    mutants onto the layout (bound by descriptor, `HOME`, `--unshare-net`,
    distinct descriptors). **65 killed by assertion.** L19 and L20, the memfd
    rewind and seal, are NOT PROVEN on Windows as expected, because their
    test is Linux-only.
  - The first run found one weak test. L6 (a refused descriptor is closed)
    survived, because the test compared descriptor *numbers* with a list of
    closed ones, and the number had been reused. The test now proves the
    closure with `fstat`, and L6 is killed.
  - Two proposed mutants were dropped as unkillable by this runner, and each
    is instead proved positively on Linux:
    - the supervisor's `pass_fds` runs in a separate interpreter from the
      installed runtime (proved by the layout proof launching at all);
    - a path-bind variant has no path to name (proved by the descriptor-swap
      proof).
  - The other inventories: N2 83/83, N2 WRITE 49/49, N3b 59/60, N3c 48/54, the
    bridge 13/20, containment 16/42 and duplex 13/19. Every NOT PROVEN is
    Linux-only, and each count matches its earlier record.
- `PYTHONIOENCODING=utf-8 uv run --python 3.11 verify` on this tree:
  - clean ruff;
  - strict mypy over 103 source files;
  - four import contracts kept;
  - 2,940 tests passed and 558 skipped for platform.

  The one failure was `test_docs_validation_accepts_the_actual_repository`.
  This entry was edited during the run, before its manifest line was
  refreshed. After the refresh, that test and `sha256sum --check` passed.

### Linux proofs rewritten, not yet executed

These run only in the provisioned foundation lane. **Nothing below has
executed.**

- `test_operator_store_containment.py`. It gains a shared `native_mount`
  helper (the same two calls the handle makes), which every Linux store
  launch now uses. Two proofs:
  - **Layout proof** (evidence `n3a-native-layout.json`):
    - in the zone, `auth.json` reads the fixture bytes, is rewritten in place,
      and its bytes reach the store's same inode;
    - `rename` and `unlink` over it fail with `EBUSY`;
    - `config.toml` holds exactly the sealed bytes and is read-only;
    - the home lists exactly `auth.json` and `config.toml`;
    - `CODEX_HOME` and `HOME` are exact;
    - `/vendor-store` is absent;
    - no descriptor names `auth.json`, a memfd, the lock, a guard or the
      anchor;
    - the store directory still holds only `auth.json`;
    - an ordinary worker sees neither `/vendor-store` nor the codex home.
  - **Descriptor proof** (`n3a-native-layout-descriptor.json`): `before_spawn`
    swaps the store path to a different `0600` file after the descriptor was
    opened, and the zone still reads the checked object's bytes.
- `test_operator_store_persistence.py`:
  - **Refresh:** an in-place rewrite of the bound file keeps the inode, and
    `os.replace` over it fails with `EBUSY`. Both checks accept, and the bytes
    survive close.
  - **Persistence:** planted `hooks.json` and `helper` in the zone's home
    survive into neither the next launch's arguments (compared with the two
    per-launch descriptor numbers erased) nor its home. A write to
    `config.toml` is denied. The sealed configuration is unchanged. The store
    directory is unchanged. The same probe runs inline and shows the zone's
    reach unchanged, with a same-run relay control.
- `test_native_egress_containment.py`: the socket walk's positive control
  plants its socket in the zone's own home. The store is no longer a pathname
  route.
- `_operator_store_owner.py` and `_egress_owner.py` use `native_mount`, and so
  does every N3b launch.
- `test_operator_store_credential.py`'s memfd seal test runs in the
  unprivileged Linux `verify` job.

**What is unproved until the lane runs:**
- that bubblewrap `0.9.0-1ubuntu0.3` accepts `--bind-fd` and `--ro-bind-data`
  from inherited descriptors under the AppArmor launch profile (the
  orchestrator found both flags in the pinned binary's strings; behaviour is
  CI's to show);
- `EBUSY` for `rename` and `unlink` over a file bind;
- the zone's descriptor inventory.

### Deviations from the design

- The design's `before_spawn` opened the credential. Here the handle opens it
  just before the launch instead: `argv` needs the descriptor number before
  `before_spawn` runs. The object bound is still the object checked, because
  the check is on the descriptor.
- The design put a cancellation hand-off (a done-callback) on the mount
  descriptors. A test showed it unreachable: a caller awaiting the exchange
  task returns only once that task is done. The code closes in the `finally`,
  and the test pins the ordering.
- The evidence files are `n3a-native-layout*.json`, not `n4-*`. The bridge
  lane asserts its exact `n4-*.json` set, and these proofs run in the N3a
  step.

**Correction, found while building the N4 lane on top of this slice.** The
first commit, `37db228`, broke the N4 bridge proof on Linux. The breakage
was found by reading, not by execution. There were two causes:
- **The startup bootstrap.** The bridge proof's bootstrap
  (`_native_startup_bootstrap.py`) created `/tmp/home/.codex` and wrote
  `config.toml` there. Under the layout, that directory already exists and
  `config.toml` is a read-only bind, so both calls would have raised.
  - The bootstrap now creates the directory with `exist_ok`.
  - When the layout has bound a configuration, the bootstrap requires that
    configuration to equal the setup's bytes and never writes it. When nothing
    is bound (placement images), it writes the configuration as before.
  - `run_native` gains a `configuration` argument, so the pinned-client
    proof binds its telemetry configuration as the sealed one.
- **The zone environment.** The bridge proofs' expected zone environment now
  includes `CODEX_HOME`.

**First Linux CI run of PR #106** (run 35967705858, at `37db228`). CI's
uv-managed CPython 3.11 has no `fcntl.F_ADD_SEALS`. That failed:
- the memfd test in `verify`;
- both layout proofs;
- the owner-death proof. Its owner process builds the same mount, so it
  never printed `ready`.

N3a's 20 root-lane proofs passed.

The fix:
- `seal_constants` and `memfd_flags` take the module's names when they
  exist, and otherwise the Linux UAPI values
  (`include/uapi/linux/fcntl.h`: `F_ADD_SEALS` 1033, `F_GET_SEALS` 1034, seal
  bits 1/2/4/8; `include/uapi/linux/memfd.h`: 1 and 2).
- `sealed_data_fd` now reads the seals back and refuses anything but exactly
  the four it applied, so a wrong constant fails loudly.
- Portable tests cover both selections, as mutants L20-L23. The read-back
  check itself has no mutant: only a wrong constant on Linux reaches it.

## N4: the authenticated-startup lane

This is the credential-free half of N4 (#77), on `m8/n4-startup`, stacked on
the layout slice above. The design is
[M8-N4-state-review.md](M8-N4-state-review.md). It was reviewed once by Codex
(`job_874f14f36992`) and amended, and the orchestrator's decisions are
recorded at its end. **The implementation has had no independent-model
review.** No login, credential, vendor contact or model request has happened,
and `vendor_conformance_qualified` stays false.

What changed in `src/`:

- `codex_protocol.py`:
  - `rate_limits_read_request`, which is exactly `{"id", "method"}`.
  - `spend_reading`. It judges only `rateLimitsByLimitId["codex"]`, and only
    when that entry's own `limitId` is `"codex"`; the headline and every
    other bucket are never read.
  - `spend_faults`, the owner's N5 bound written as code. Credits must be
    present with `hasCredits` false, `unlimited` false, and the balance absent
    or a zero decimal. An absent credits object refuses. The readback plan is
    compared.
  - `spend_change_faults`: the five overage fields must not move across the
    turn.
  - `rate_limit_of`, a fixed vocabulary of `before.*` and `after.*` flags and
    bounded numbers. `is_using_overage` is always `None`.
  - `account_notice_faults` replaces the blanket namespace refusal. Only
    `account/rateLimits/updated` with exactly `{rateLimits}` params and a
    plan that is absent, null or accepted passes. Every other `account/` and
    every `modelProvider/` notification refuses.
  - `ExpectedAccount.alternatives`, for qualification only (decision 1).
  - The dead projection from `turn.rateLimits` is removed. The pinned `Turn`
    has no such field.
- `codex.py`: `CodexConversation` sends the readback after the pre-turn gate
  (refusing before `thread/start`) and after the pre-acceptance gate (the
  change rule).
  - `startup_only=True` ends the phase after the first readback, with four
    methods. Only the lane sets it: the handle never does.
  - The conversation records `before_spend`, `after_spend` and
    `observed_plan`. The plan is recorded only once it has been accepted.
  - The observation's `rate_limit` is `rate_limit_of(before, after)`.
- `egress.py`: a separate `EgressRelay.destinations` counter holds
  `accepted:<host>:<port>` and `relayed:<host>:<port>`. It is named from the
  sealed policy only. Denials stay counted by reason in `observed`, so every
  existing assertion is unchanged.
- `operator_store.py`: `StoreMaintenance` carries its `lock_fd`, `check()`
  (this key's withdrawal, this floor and the same objects, under a digest
  domain no provider uses) and `open_credential()`.
- New `codex_lane.py`, an offline operator helper:
  - `run_login` (the device login's stdout goes only to the operator) and
    `run_startup`;
  - custody from maintenance or from the active selection;
  - closed evidence, written create-exclusive with `completed` last. Its
    digest is the conformance revision (decision 5);
  - `main` for the host.

### Local evidence (Windows 11, Python 3.11)

- New tests:
  - `test_codex_spend.py`: the bound in both directions, the bucket rules,
    the change rule, publication and the notice allowlist;
  - `test_codex_startup.py`: the four-method phase, aborts, the handle never
    running startup, pre- and post-turn readbacks, WRITE never offering
    tools, provider recovery, and the qualification plan set;
  - `test_codex_lane.py`: the login output never reaching evidence,
    denials, a fresh lane directory, measured versus unmeasured refresh,
    evidence ordering and exclusivity, and both custody kinds;
  - `test_egress.py`: per-destination counting, and a planted 190-character
    hostname never becoming a key;
  - `test_operator_store_credential.py`: the maintenance check and the
    maintenance credential.
- Changed tests:
  - `SIX` becomes `EIGHT`;
  - the scripted peer answers readbacks, and its last-reply hooks move to the
    final readback;
  - `FORGED_GOOD_ACCOUNT` now takes id 6;
  - the recorded forward cost is flipped (a plan-free rate-limit update now
    passes; a plan change refuses);
  - the turn-rate-limit tests become "a turn record is never a rate-limit
    source".
- Inventories, each killed by assertion:
  - `check_m8_n2_mutations.py`: **103/103**, of which 21 are new N4
    mutants. Three stale anchors were retargeted: the plan fault, the
    account refusal and the rate-limit vocabulary. (Corrected 2026-09-24,
    review F2: the first version of this line said 104/104.)
  - `check_m8_n4_bridge_mutations.py`: 30 in total, 20 existing and 10 new
    (lane and relay). 23 were killed; the same 7 are Linux-only NOT PROVEN as
    before. (Corrected, review F2: the first version gave 23 as the total.)
  - `check_m8_n3c_mutations.py`: 58 in total on the rebased base, of which 4
    are new (the maintenance check). 52 were killed; the same 6 are
    Linux-only. (Corrected: the first version gave 52 without saying it was
    the killed count.)
  - Unchanged: N3a 65 (2 Linux-only), N3b 59/60, N2 WRITE 49/49.
- The first N2 run surfaced four NOT PROVEN mutants, and each was corrected:
  - one replacement raised `NameError`, and the test now also asserts that no
    `None` value is published;
  - one test died on a `KeyError`, not an assertion;
  - two mutants were equivalent to the code (an extra guard, and a plan that
    tests always accepted), and were rewritten to remove the request and to
    record the plan before the gate.

  One bridge mutant (5) was NOT PROVEN only while two inventories ran
  concurrently. Rerun alone, it was killed.
- `PYTHONIOENCODING=utf-8 uv run --python 3.11 verify` on this code:
  - clean ruff;
  - strict mypy over 104 source files;
  - four import contracts kept;
  - 3,051 tests passed and 560 skipped for platform.

  The one failure was `test_docs_validation_accepts_the_actual_repository`,
  because these documents were edited during the run. After their manifest
  lines were refreshed, that test and `sha256sum --check` passed.

### Linux proofs added, not yet executed

These go in `test_native_egress_bridge.py`, which runs in the foundation
lane's bridge step with the pinned binary and the store fixture, so no
workflow change is needed. **Neither has executed.**

- **L2:** the pinned `app-server` with the production-shaped sealed
  configuration and no login (the fixture's `auth.json` is set to `{}` for
  the test, then restored).
  - It must send three methods and refuse with exactly the fault set an
    `account/read` error reply produces: no result object, so the gate never
    completes, the fourth method is never sent and no readback is judged. It
    must show a relay with no destinations, no denials and no CONNECT heads.
  - Same-step control: the same configuration with plugins on must produce a
    counted destination denial and a recorded head.
- **L3:** the pinned `codex login --device-auth` against a policy that names
  only a decoy.
  - It must `CONNECT auth.openai.com:443`, be denied, and exit non-zero.
  - Nothing printed reaches the evidence.
  - `auth.json` stays a bound `0600` file: the pre-login logout's `unlink`
    meets `EBUSY`.
- The bridge step's key-material test now expects the two new files,
  `n4-lane-startup.json` and `n4-lane-login.json`.

### Deviations from the design

- **`--hold` pauses after the exchange, while custody still holds the lock.**
  The design paused before stdin closes. For control S6a the lock is what
  matters, and custody holds it either way.
- **The `refused-destinations` subcommand was dropped.** Decision 2 left
  nothing for it to do.
- **Per-destination counts live in their own counter.** They are not keys of
  `observed`, which keeps every existing reason assertion intact.
- **`active_custody` is an asynchronous context manager.** It is used from
  the lane's async tests and from `main`'s single event loop.
- **The readback is taken in every task turn,** so every existing turn test
  now sends eight methods.
- **The evidence schema differs from the first draft's block** (review F1).
  The block in the state review is now the emitted schema, and a test pins
  the two together. The changes and their reasons are listed there.

### Limits carried

The state review's limits apply unchanged. In particular:
- no live readback, login or refresh has been observed;
- qualification before activation stays operator-asserted;
- mid-turn spend fields are judged only through the post-turn readback;
- `modelProvider/` recovery during an N5 turn now discards that turn, which
  is the new forward cost.

### Inherited-lock custody (orchestrator decision, 2026-09-24)

Host-runtime decision 1 runs the N3c helpers as root. The service is refused
at the withdrawal write, and the launcher refuses root. So the lane's own
`maintain_offline` call could not work on the host. The decided design and
its reasons are in the state review ("Host-runtime interface required",
item 4). What changed:

- `operator_store.py`:
  - `run_under_maintenance` and `main` (`maintain ... -- LANE-COMMAND`) are
    root's side, inside the maintenance helper.
    - The lane starts as the service by `subprocess`'s own
      `user`/`group`/`extra_groups=[]`, not `setpriv`.
    - Its environment is fixed, it inherits only the lock, the helper sets
      the custody options itself, and the helper waits for the lane before
      leaving maintenance.
  - `inherit_maintenance` is the lane's side. It proves custody before
    anything is exposed:
    - the lock identity;
    - that the description holds the lock, taken by the parent
      (`/proc/self/fdinfo`);
    - the anchor, the withdrawal, and a floor that matches the record, the
      inventory and the helper.
- `codex_lane.py`:
  - `--custody maintenance` now takes `--lock-fd` and `--floor`, and uses
    `inherit_maintenance` with `parent=os.getppid()`;
  - without those options it refuses to start;
  - `--wait` moved to the helper;
  - `allow_abbrev=False`.
- Runbook S2 to S4 are amended in the state review:
  - the empty `auth.json` is created with the store owner's ownership before
    any activation;
  - login and qualification are separate helper runs.

Local evidence (Windows 11, Python 3.11):

- New `test_operator_store_inheritance.py`: 37 portable tests, plus one
  Linux unit test of the real kernel report with a real inherited
  description in a child.
- The lane tests cover the new options.
- Root lane: a new test in `test_operator_store_maintenance_restart.py` (the
  N3c root step, so no workflow change), with evidence
  `n4-inherited-maintenance.json`. **It has not executed.**
- `check_m8_n3c_mutations.py` has 81 mutants: 23 new (N4-M5..M27) and 75
  killed. The same 6 are Linux-only NOT PROVEN. (Corrected: the first
  version said 75 and 69, counting from the wrong base.)
- `check_m8_n4_bridge_mutations.py` has 32 mutants: 2 new (N4-L11, L12), 25
  killed. (Corrected: the first version gave 25 as the total.)
  - Mutant 5 (a failed leaf dial authors no reply) was NOT PROVEN once, when
    it ran directly after the N3c inventory. Rerun alone, it was killed. That
    is the timing sensitivity recorded above; the bridge code is unchanged
    here.
  - The same 7 are Linux-only.
- `PYTHONIOENCODING=utf-8 uv run verify` passed: 3,168 tests passed and 624
  were skipped for platform.

### Lane review fixes and the bound vendor tree (2026-09-24)

A five-lens review of the lane (at the pre-rebase `ef145d7`) confirmed 19
findings, each by two independent skeptics, and refuted none. Every premise was
reproduced here before its fix. The protocol and conversation findings were
reproduced by new tests failing against the unfixed code. The lane findings
were reproduced by a probe run against a temporary worktree at `6c97d7d`:
- a login ran under active custody with no fault;
- a startup whose launcher never conversed wrote `faults: []`;
- `credential.checked` was the literal `True`, and no executable was recorded;
- an fsync failure left a complete file at the final name;
- an existing evidence path was found only after the lane ran, at a 120 s
  login deadline.

The design and the reasons are in the state review: sections 3 and 5, the
evidence schema, runbook S2 to S4, and interface item 1. What changed:

- `codex_protocol.py`:
  - the notice fault names no turn (NOTICE-5);
  - `account/rateLimits/updated` is judged for spend: credits must meet the
    zero rule and `spendControlReached` must not be true (SPEND-3);
  - `account_request_faults` refuses id-bearing `account/` and
    `modelProvider/` records (NOTICE-2);
  - `settings_notice_faults` requires `thread/settings/updated` to name the
    sealed model and provider (NOTICE-4, adopted although disputed).
- `codex.py`:
  - the drain to EOF judges id-less records (NOTICE-1, RL-5);
  - `_judge_identified` applies the account-request rule at every site, and
    in the startup phase refuses any other unowned request;
  - one plan literal per run (SPEND-2, NOTICE-3);
  - `pause` for the startup hold (RL-3);
  - `provider` and `configured_provider`, which the handle passes.
- `codex_lane.py`:
  - login is maintenance-only, in `run_login` and in `main` (CC-1);
  - an affirmative pass, where every missing fact is a named fault (SPEND-1,
    RL-1);
  - credential facts are measured after the run, and a terminal custody check
    runs (CC-2, RL-4);
  - the executable's path and SHA-256 are recorded, and `--binary` is gone
    (CC-3);
  - `EvidenceFile` reserves the evidence path first and publishes by a
    no-replace link (RL-2, RL-6);
  - the hold runs inside the exchange (RL-3);
  - the login deadline is 960 s (RL-7);
  - `--first-login` covers S2 (CC-4);
  - the closed schema is `LOGIN_FIELDS` and `STARTUP_FIELDS` (F1).
- `operator_store.py`: `StoreMaintenance.create_credential`
  (create-exclusive, `0600`) and `credential_facts`.
- **The bound vendor tree (orchestrator decision).**
  - `linux.py` gains `NativeVendor`: the launch set's `native-codex` and
    `codex-models.json`, bound read-only at `/opt/codex` and
    `/opt/codex-models.json` on native launches only.
  - A launch checks their custody in `check_artifacts`, never their content.
  - The launch revision names both paths.
  - `runtime_plan` gains only the two empty mount points.
  - `codex_lane._launcher` binds them.
- Linux proofs, not yet executed:
  - L2 and L3 now run the client from the bound tree and read the bound
    catalog;
  - L3 runs under a test-only maintenance relabelling (CC-1);
  - L2's relay record includes `closed`.
- F2: the earlier inventory counts are corrected above.

Local evidence (Windows 11, Python 3.11):
- Inventories, each killed by assertion unless stated:
  - `check_m8_n2_mutations.py`: **118/118**, of which 15 are new (N4-22 to
    N4-36).
  - `check_m8_n3c_mutations.py`: 84, of which 3 are new (N4-M28 to M30); 78
    killed, the same 6 Linux-only.
  - `check_m8_n4_bridge_mutations.py`: 75, of which 43 are new:
    - N4-L13 to L41 (the lane findings);
    - N4-V1 to V14 (vendor custody, bind and revision).

    68 killed, the same 7 Linux-only. Mutant 5 was NOT PROVEN once, again
    after the N3c inventory, and was killed alone.
  - N2 WRITE, N3a (1 Linux-only) and N3b (1 Linux-only) are unchanged.
  - `check_m8_host_artifact_mutations.py`: 41 killed. Each NOT PROVEN is a
    host check that needs Linux (root, ownership, ancestors, the staged
    trees). The runtime plan's two new mount points add no mutant; the
    host-runtime test pins them.
- `test_the_design_documents_the_emitted_schema` pins the state review's
  schema block to the code.
- `PYTHONIOENCODING=utf-8 uv run verify` passed before the rebase: 3,284
  tests passed and 625 were skipped for platform.

**After the rebase onto `88c033d` (#107, the controller environment).**
- `PROOF_MODULES` gains `constructicon.substrate.executors.codex_lane`.
  R19's module list in `M8-N4-host-runtime.md` is updated to match, and a
  test holds the two equal. So the verify lane's import proof and the host
  check load exactly the module N4 runs, under `python3 -I -S -B` from the
  flat tree.
- A portable test runs the lane's entry point as `-I -S -B -c`, with only
  explicit `sys.path` entries. That rules out any reliance on site
  processing, `.pth` files or a writable cache.
- One conflict, in `runtime_plan`'s docstring: #107 already records the
  bound-not-baked decision. The resolution keeps its words and adds the two
  mount points, because a read-only root cannot gain one at launch.
- `PYTHONIOENCODING=utf-8 uv run verify` on the rebased head: 3,353 tests
  passed and 648 were skipped for platform.

**Bridge mutant 5 made deterministic (2026-09-24).** It had passed or failed
depending on what ran before it, which is flakiness, not evidence.
- **The shared cause was timing, not leftover state.** The killing test sent
  the vendor's `CONNECT` and then read. When the forwarder thread finished
  first, the `CONNECT` reached a closed socket. Its RST discarded the
  client's receive buffer, so the mutant's authored `502` read as `b""` with
  EOF. The mutant survived whenever the thread won the race.
- **Reproduced on Windows with a scratch test:** the same mutant body loses
  its reply to exactly that order, and keeps it when the client is already
  reading.
- **The fix.** The forwarder dials before it reads, so a refused dial never
  depends on the client's bytes. The test therefore joins the forwarder
  before the client does anything, and the client writes nothing. The close
  is a plain FIN, and an authored byte is always read.
- **Measured afterwards:**
  - mutant 5 killed 15 of 15 times alone;
  - mutant 6 killed 5 of 5 times;
  - both killed in a run of the full bridge inventory directly after the
    N3c inventory, the order that had failed.

### Merged

The N4 prerequisites and the lane merged on 2026-09-24 UTC. Every check was
green on each final head: verify, runner qualification and Linux containment.
The launch set and the controller environment are recorded in
[M8-N4-host-runtime.md](M8-N4-host-runtime.md).

| PR | Slice | Merge | Final head | Containment run |
|---|---|---|---|---|
| #105 | launch set | `e26f438` | `50ec94c` | [35969460318](https://github.com/sushiHex/constructicon/actions/runs/35969460318) |
| #106 | narrow layout (above) | `908b9ae` | `fb22d26` | [35974188145](https://github.com/sushiHex/constructicon/actions/runs/35974188145) |
| #107 | controller environment | `88c033d` | `18f3a67` | [35980325990](https://github.com/sushiHex/constructicon/actions/runs/35980325990) |
| #108 | this lane | `40b663e` | `a4c3053` | [36053680493](https://github.com/sushiHex/constructicon/actions/runs/36053680493) |

**The layout's Linux proofs ran on `fb22d26`.** These are the items listed
above as unexecuted: the layout and descriptor proofs, refresh and
persistence, and bubblewrap accepting `--bind-fd` and `--ro-bind-data` from
inherited descriptors.

**Every unexecuted lane item ran at `a4c3053`:** L2, L3, the inherited-custody
proof and the Linux-only mutants. Mutants killed by assertion per proof lane:
foundation 402, lifecycle 51, combined 196, mediation 22. None is NOT PROVEN.

**Review of #108.** The connector reviewed `d01d937` and raised one P1:
- `--expected` defaulted to `pro`;
- an account reporting `prolite` would have refused at S4, stopping the
  owner-attended qualification.

`a4c3053` fixes it:
- `QUALIFICATION_PLANS = ("pro", "prolite")` is bound in maintenance custody,
  and an operator-supplied `--expected` refuses there;
- active custody requires `--expected` naming the literal recorded at S4;
- `--alternative` is removed.

Tests and the CI run above verify the fix. By the one-pass rule, there was no
second connector pass.

**Limit added: a kill mid-save.** The pinned save truncates `auth.json` and
then writes it ([token-refresh research](../../../research/m8-codex-token-refresh.md)).
- A vendor process killed between the two, by the lane's deadline or by power
  loss, can leave the file empty or partial.
- After a server-side rotation, the previous refresh token is spent as well.
- The next run refuses, and maintenance must log in again.

The state review names this only for controller death during login. The
window is one small write, and the vendor's save cannot be changed from here.

**Remaining for N4:** the owner-attended session on `constructicon-m8`,
runbook S0 to S10, with the evidence recorded on #77.

### First host installation: a verify defect (2026-09-26)

R8 ran on the host at `C` = `376a3fd` under the
[owner's authorization](https://github.com/sushiHex/constructicon/issues/77#issuecomment-5841548875).
The steps up to the root install all passed:
- R10, after the permitted `useradd m8-service`;
- R11, with every pin matched;
- R12, with nothing unattributed;
- R13's judge (`ready: true`), and the chain printed `R13 installed`.

**`verify-launch` then refused an installation that was correct**
([output](https://github.com/sushiHex/constructicon/issues/77#issuecomment-5841573222)).
- `observe_launch` listed every directory that was not a tree, including
  `operator-stores`.
- That directory is `0750 root:m8-service` by design, and the operator account
  is outside that group. So the listing raised `PermissionError`, the entry
  became "unobservable", and the assessment failed.
- The tests missed it because their fake host's store belongs to the test
  user, who can always list it.

**Fix.** Only the launch root's entries are reviewed, so only the launch root
is listed. The store is judged on uid, gid and mode alone, as the table always
said. What guards it:
- a portable test that denies the listing as the host did;
- a mutant, "the store is never listed".

**Recovery, as the runbook says.** The output was posted, then
`pre-m8-runtime` was restored with the VM off. No vendor store ever existed.
- The restore is an M8-D2 requalification trigger. The next session reruns
  M8-D2's verify and R5 before R10.
- The controller runbook (R16-R20) did not run.
- The rerun needs a new authorization naming the new `C`.

### N4 operator command entry points (2026-09-28, unmerged)

Scope: the offline entry points and session preparation missing from S0-S10,
not the owner-attended session itself. The command companion is
[M8-N4-operator-commands.md](M8-N4-operator-commands.md). The accepted state
review, host-runtime design and host-installation document remain unchanged.

**Design checks before implementation.** The root helper stays in
`operator_store`: it neither imports the vendor lane nor reads a credential.
Provisioning uses the existing descriptor publisher and an exclusive first
bundle creation; publication and activation retain the existing lock and
generation laws. A qualification digest is explicit operator input, not a
claim that this helper performed qualification (state-review decision 5).
Preparation runs as the unprivileged service user, resolves the two fixed
hosts once, and publishes its completion record only after the three input
artifacts. A partial directory is not reusable completion evidence.

**Two command-level corrections.**

- The controller is an explicit import-path installation, not a global Python
  package. The commands use the host-runtime's reviewed isolated bootstrap,
  which supplies the same module arguments as `-m` without site processing.
- The lock-contention control S6a must precede g2 publication: maintenance
  after publication would raise the withdrawal floor to g2 and prevent its
  activation. The command companion orders the control accordingly and uses
  the last clean maintenance startup's evidence for publication.

**Review corrections (introduced, reproduced in portable tests).** A failed
exclusive completion-file write must not delete the existing file that caused
the refusal. Preparation now reuses `EvidenceFile` for its last publication,
rather than adding a second completion/cleanup protocol. A partial initial
bundle must not be repaired implicitly by `publish`; the CLI requires its
current anchor before delegating. A supplied qualification digest must match
both sealed revision fields independently. Tests isolate each refusal so a
later guard cannot conceal a removed earlier guard.

**Credential-free evidence so far.** The focused command, lane, inheritance,
runbook and configuration checks passed locally: 198 passed, two
Windows platform skips. The extracted runbook checker accepts actual fake-lane
login, qualification, lock hold, active startup, refresh and expected refusals;
it refuses missing completion, extra faults and mismatched plan or custody.
All 48 new mutants (31 store CLI, 17 preparation)
were independently rerun and killed by assertion, not collection errors or
skips. Final-head gate and Linux results belong to the PR evidence. The added
root proofs use synthetic qualification and fake DNS;
they run in the existing N3c root step, without a workflow change. The existing
binary-test fixtures and their binary executions are unchanged; the new
configuration comparison is portable and launches nothing.

**Evidence status.** Final verification and Linux proof results will be
recorded on the PR's exact head. No private-host command, credential
operation, vendor login, model request or deployment qualification is performed
by this slice. Installing the new helpers requires its own authorized,
verified controller update; the installed `29a5fa5` controller lacks them.
An R6 drift-baseline change is not authorized by this implementation.

**PR review follow-up (2026-09-29).** The review found introduced proof gaps:
the guard's own tests did not prove the CLI called it, and the direct
next-generation test did not prove publication requested that law. Main-level
tests now exercise the real root guard with the command's root and service,
publication of a non-next generation, and activation's sealed-file reader.
Additional tests cover no-follow handling of a sealed-file symlink; call-site
and no-follow mutants require assertion failures, not harness errors.

The command companion now runs each step as a script over non-interactive SSH,
checks non-interactive sudo before starting, rechecks drift after reboot and
before refresh, and reconstructs shell state from recorded evidence. The
negative binding controls distinguish stale-generation binding refusal from
reboot-anchor refusal; unrelated failures cannot pass. Preparation itself,
running as the service user, owns the fresh-directory check. No additional
review round or private-host action is part of this follow-up; exact-head
verification is recorded on the same PR.

The follow-up focused suite passed 81 tests locally, with the real Linux
symlink check skipped on Windows. Nine added call-site/no-follow mutants
were independently rerun and assertion-killed, including literal deletion
and bypass of both root-validation call sites. The PR's added inventory is
now 57 mutants (40 store CLI and 17 preparation). Runtime source and frozen
plans are unchanged by this follow-up.

### N4 session: S3 stopped on the lane launcher (2026-09-30)

The owner-attended session ran S0 to S2 at `def8e73` ([#77](https://github.com/sushiHex/constructicon/issues/77#issuecomment-5903006364)).
- **Passed:** the checkpoints were deleted, the drift check reported NO DRIFT, S1 prepared its inputs, and S2 provisioned g1.
- **S3 stopped:** `codex_lane._launcher` raised `KeyError: 'policy'` before building a launcher.
- **Nothing reached the vendor:** no vendor process, relay, device code or credential. The store was left in its withdrawn state with floor 1, and its directory is empty.

**Cause.** `_launcher` (#108) read `policy` and `policy_sha256` from the launch set's `runtime.json`.
- The file R13 installs is written by `m8_host_artifacts.runtime_json`, and has neither key. Its launch-profile pin is `apparmor_policy_sha256`.
- The one test of `_launcher` built an invented document with the wrong keys. Every other lane test replaced `_launcher` outright.

**Fix.**
- `_launcher` binds the installed profile `/etc/apparmor.d/constructicon-m8-launch` (`LAUNCH_POLICY`), pinned by the manifest's `apparmor_policy_sha256`.
- The test now builds `runtime.json` with the host tool's own writer, and fails on the old code with the host's exact `KeyError`.
- New `codex_lane preflight --launch-root L` runs `LinuxLauncher.probe()`: the artifact checks, then the benign physical probe every launch runs first, including the AppArmor child attachment. It starts no vendor process. The runbook runs it as S3's first command, so a defect of this kind stops the session before a device code exists. (The first version ran only the artifact checks; the connector's P2 review corrected it.)
- Mutants: N4-V15 (the policy path), N4-V16 (the pin's key) and N4-V17 (preflight runs the probe).

**To resume.**
1. Reinstall the controller at the new `C` (R15).
2. Run S3 as written. S0 to S2 stand, and S3 left no file to collide with.

### N4 session: S3 stopped on the zone's trust store (2026-09-30)

At `799da8d`, after the controller reinstall, preflight passed, including the
physical probe and the `constructicon-m8-launch//&constructicon-m8-workload
(enforce)` attachment
([#77](https://github.com/sushiHex/constructicon/issues/77#issuecomment-5917873676)).

S3 then stopped before any device code:
- The relay accepted and relayed one connection to `auth.openai.com:443`.
- The pinned client exited with status 1 after 0.95 s, with 303 bytes of stderr, which the lane keeps no text of.
- The store holds only the empty `0600` file `--first-login` created.

**Cause, as far as it is proved.**
- The zone's runtime had no `/etc` at all, so it had no CA store.
- At the pin, the client's default HTTP TLS is native-tls (OpenSSL) (`M8-N4-proxy-bridge.md`, section (c)), and the zone gave it no roots to find. The exact error text was not captured.
- A cross-review by Codex (`gpt-6-astra`) corrected two earlier claims:
  - the HTTP stack is not rustls-native-roots;
  - in-zone TLS proofs did exist, but none exercised the auth client's own root discovery.

It also required an accepting control, and trust bound to the admitted bytes.

**Fix: the zone trusts what installation admitted.**
- `runtime_plan` admits the host's `/etc/ssl/certs/ca-certificates.crt` into the image, like every other host file (`m8_host_artifacts.TRUST_BUNDLE`).
  - Its bytes are pinned by `runtime_digest`, and every launch rechecks them.
  - A host update to them is drift that verify-launch reports.
  - The file is generated by `update-ca-certificates`, so no package claims it, and it is listed as unattributed.
- Every native launch sets `CODEX_CA_CERTIFICATE` to that path (`linux.TRUST_BUNDLE`). This is the client's own documented override. The provider path gets it too, because it launches through the same native-store `argv`.
  - Its HTTP stack then switches to rustls and adds those roots (`http-client/src/custom_ca.rs` at the pin).
  - Its websocket stack layers the same file over the native roots, and those come from the same standard path.
  - The launch revision already hashes the recipe and the runtime digest, so no new identity field is needed.
- **The claim is necessary and sufficient, not exclusive.** reqwest 0.12 is built with its defaults plus `cookies` (`codex-rs/Cargo.toml:415`), and `webpki-roots` is in the lock. Whether the rustls path also compiles in Mozilla's roots is UNVERIFIED. If it does, the trust set is those roots plus this store. The proof shows a CA must be in this store, not that nothing else is trusted.
- The rejected alternative was a per-launch bind of the host's live bundle. It needs new custody and memfd plumbing in both the lane and the provider, and it adopts host changes without admission.

**Proof.** The Linux proof `test_the_zone_trust_store_decides_what_the_device_login_trusts` runs the pinned client's own device login. `--experimental_issuer` moves only the issuer URL's port to a controlled peer. That the rest of the device path is the production one is read from the CLI source (`cli/src/login.rs:403`), not proved. Each arm needs an affirmative observation, so a reset, deadline or peer fault fails the test:
1. **Refused:** on the production image, which lacks the throwaway CA, the client sends `TLSV1_ALERT_UNKNOWN_CA` and no request. This is the host's failure mode.
2. **Accepted:** on a test image whose store also admits the CA (`scripts/ci/build_m8_trust_fixture.py`), TLS completes and the request line is `POST …/deviceauth/usercode` (`login/src/device_code_auth.rs:68`).
3. **Wrong name:** a trusted CA with a leaf for another host is refused by certificate alert.

Evidence is written to `n4-lane-trust.json`. It includes the refused run's stderr, for comparison with the host's 303 bytes.

Mutants: N4-V18 (the launch names the store), and "the runtime admits the zone's trust store".

**Limits.**
- The certificate chains on the real hosts are not proved. S3 is the first real handshake.
- Expired certificates, revocation and OCSP are unproved.
- A root-level change to the host bundle takes effect only through a reviewed reinstall.
- **After the first login, a host CA update is drift that verify-launch reports.** The only documented launch-set replacement is the removal, which is forbidden after login because it deletes the store. Re-admitting a new bundle then needs a credential-preserving launch-set update, which does not exist yet.
  - This is the existing limit for any host runtime drift (libc, Python); the CA bundle is a new, more frequent trigger for it.
  - Until that update exists, the installed snapshot keeps serving launches, because each launch checks the installed copy, not the host.

Cross-review: one Codex pass on the diff (`gpt-6-astra`, verdict fix-then-ship). Four P2s were adopted:
- the exclusivity claim is narrowed;
- the refusal arms need an affirmative alert;
- the accepted arm needs the device-code request line;
- the post-login coupling is recorded as a limit above.

Both P3s were fixed: the PEM separator, and the manifest.

**To resume.** This changes the runtime image, so the launch set is reinstalled (R8) at the new `C`.
- The fixed removal is still valid, since no login has succeeded. It also removes the store.
- S1 to S3 then run fresh, S3 with `--first-login`, once the old session directory `/home/m8-service/m8-n4-session` has been removed.
- The controller is reinstalled at the same `C` (R15).

### N4 session: S3 logged in, S4 refused on the spend bound (2026-10-01)

At `92b956e` (#114), the launch set and the controller were reinstalled and verified, and S0 to S2 ran fresh ([#77](https://github.com/sushiHex/constructicon/issues/77#issuecomment-5922986780)). The runtime has 654 entries, and `unattributed` is exactly the CA bundle.

Then ([#77](https://github.com/sushiHex/constructicon/issues/77#issuecomment-5943007632)):
- **S3: the owner's device login succeeded.** The lane gave `faults: []`, and `check_evidence login` passed. The S3 timestamp was written.
- **S4 refused, exactly as the bound required.** The plan was `pro`, exactly the four methods were sent, and the relay was clean. The readback showed `has_credits: true` and `balance_zero: false`.
  - The faults were the credit fault and the incomplete gate.
  - The owner reported the balance as a free OpenAI credit grant that expires at the end of 2026.
- The store stays withdrawn and holds the credential; nothing beyond g1 is published.

### The owner's `operator_authorized` bound (2026-10-01)

The owner approved, verbatim, on [#78](https://github.com/sushiHex/constructicon/issues/78#issuecomment-5945414633):

> I approve subscription_overage = operator_authorized for the Codex binding on my Pro account. The bound is my account's own settings (included usage, credit balance including purchased credits, automatic reload, any spend control), which I own; there may be no finite money ceiling. Constructicon does not enforce or claim to enforce a ceiling: it refuses to start a turn when the account reports its spend control reached, and surfaces the readback facts. This approval does not apply to any other executor.

This is ADR 0021's approval "of subscription-linked overage and its bounds" for this binding (ADR 0021:249-250). It is the written record that N3c owner decision 2 deferred to N5 (`M8-N3c-state-review.md:716-723`). It is not N5's full authorization: model, permitted task data, and a fixed request/token budget remain, and READ and WRITE acceptance are authorized separately. The overages-`forbidden` profile stays forced unavailable.

**The lane, as code.** A different owner bound is a new `PROTOCOL_REVISION` (the module's source), never a parameter, and no code branches on the profile literal.

| Where | Before | Now |
| --- | --- | --- |
| Before a turn (`spend_faults`) | unreadable, other plan, or not proved zero credits refuses | unreadable, other plan, or `spend_control_reached` true refuses; credit state never does |
| After the turn | `spend_faults` plus `spend_change_faults` (five fields unchanged) | `readback_faults`: unreadable or other plan only. A completed turn is never second-guessed on spend |
| `account/rateLimits/updated` | credits must prove zero, the control must not be reached | plan always; until `turn/start` is written, a `spendControlReached` other than `null`, absent or `false` also refuses (`notice_stop_faults`). Credits are never judged |
| `spendControlReached` present, non-null and not a boolean | read as unknown (`None`) | the reading is unreadable: damage is never "not reached". JSON `null` stays admissible |
| Unparseable balance | published `balance_zero: false` | published as unknown (`None`) |
| Runbook `check_evidence` | zero-credit predicate | `spend_control_reached` is exactly `false` or `null`, so damaged evidence refuses too |

`spend_faults` previously never checked `spend_control_reached`; only the notice path did. That gap is closed.

**Deviations from the accepted N4 design.** `M8-N4-state-review.md` keeps its bytes. Its section 2 predicate, change rule and SPEND-3 notice rule, with their tests and mutants, are superseded here by the owner's later decision.

**Proof.**
- `test_codex_spend.py`:
  - every credit state passes;
  - the balance is published as measured;
  - a reached or malformed control refuses;
  - the headline bucket is never judged;
  - a completed turn's readback is judged only on its bucket and plan;
  - a notice's spend facts are not judged.
- `test_codex_startup.py`:
  - a startup on an account holding credits completes;
  - a reached control starts no thread and offers no WRITE tools;
  - through the handle, a turn that draws credits and reaches the control succeeds with its output, and its outcome publishes both readbacks;
  - through the handle, a post-turn plan change fails as unavailable with no output;
  - a stop notice reported before `turn/start` (after `initialize`, after the readback reply, or after `thread/start`) starts no turn, and one ends a startup;
  - a stop notice after `turn/start` is not judged.
- `test_m8_operator_commands.py`: the runbook checker accepts actual lane evidence with credits. It refuses a reached control and the malformed values `1`, `0`, `"true"`, `{}` and `[]`.
- Mutants N4-6/7/8/9/9b/10/11/14/18/26 were rewritten for the new rule, and N4-27 and N4-28 are retired with `_no_spend`. N4-37 to N4-40 cover the pre-turn stop notice: the notice is judged; the turn starts at `turn/start` and not at `thread/start`; and a damaged flag counts as a report. Locally the runner reported "121/121 mutants KILLED by assertion; 0 UNMEASURED".

**Cross-review** (Codex `gpt-6-astra`, two passes before building).

Adopted:
- the approval states its bound explicitly;
- the stop signal judges admission only;
- malformed data is never read as open;
- the full scope of rules, mutants, README and record.

Rejected:
- "A new post-login controller replacement procedure is needed." `M8-N4-host-runtime.md:770-773` already defines it: removal, then a fresh install. It does not touch the store.
- "Publish readback telemetry on refused outcomes." This is pre-existing, and a refusal-contract change.
- "Compare revision values in `check_evidence`." This is pre-existing. Both are recorded on #78.

The one pass on the diff (`gpt-6-astra`, fix-then-ship) found four issues; all were fixed:
- the runbook check accepted malformed stop values;
- two outcome tests asserted less than their names claimed;
- the mutant count was wrong (117, not 118);
- the record did not say that JSON `null` stays admissible.

The connector review on ready raised one P1, which was adopted. As first written, a `spendControlReached: true` notice that arrived after the clean readback but before `thread/start` was accepted, so a turn could start after the account had reported its control reached. The turn now counts as started when `turn/start` is written. Until then, such a notice refuses.

**Limits.**
- Nothing here bounds money. The account's settings do, and Constructicon neither reads nor enforces them.
- An absent `spendControlReached` is not a reached control: the account's own enforcement is the owner's.
- The readback is a snapshot: a turn may run past the plan limit, and the balance may go negative in flight (`research/m8-subscription-spend-bounds.md`, section 1a).

**To resume** (separate authorization). These modules are controller-only, so the launch set is unchanged.
1. Controller replacement at the new `C`: the fixed removal, then R17 to R19. There is no R16 checkpoint, because the first login has happened.
2. Fetch `C` into the launch workspace and run `verify-launch` at `C`, so S0 holds both at one commit.
3. S0, then S4 and S6a under fresh evidence names, then S5, S7, S8 and S9.
4. S10 at least 24 hours after the recorded S3.

The login and g1 stand.

### Launch-set replacement after the first login (2026-10-03)

**What stopped the session**
([#77](https://github.com/sushiHex/constructicon/issues/77#issuecomment-5961905462)).
- The controller was replaced and verified at `1138564`.
- Then `verify-launch` failed with `different: 3`, on `libssl.so.3`, `libcrypto.so.3` and `libexpat.so.1`.
- `unattended-upgrade` had upgraded them on 2026-10-01, along with the kernel (6.8.0-139 to 142), which `m8-host-drift` reports.
- The only launch-set replacement was the fixed removal, and it deletes `L` with the store, which holds the login.
- Security updates stay enabled (`docs/AGENT_HANDOFF.md`, "Drift is visible rather than frozen"), so this would recur with every update.

**The fix: the store is never in the removal's reach.** The new runbook
`M8-N4-launch-replacement.md` has root retire only the launch profile and the five
disposable entries (`m8_host_artifacts.DISPOSABLE`), then run R13's file
commands into the kept `L`. Two read-only commands bracket root's removals.

`judge-retire` proves, before the first write:
- `L` is a real root-owned 0755 directory with nothing mounted at or beneath it (`mounts_beneath` reads `/proc/self/mountinfo`), so no removal under it can reach another file system;
- the store is a real root-owned 0750 directory of the service group, never listed;
- `L` holds no unnamed entry;
- `rm`, `cat` and the parser are root's alone;
- a loaded profile still has the root-owned file that unloading reads.

It records the store's device, inode and group in `retire.json`.

`verify-retired` requires:
- `L` holds only that store;
- no profile file is present;
- no launch profile is loaded.

`judge-launch` accepts an existing `L` only as that recorded state (`"replacement": true`). `verify-launch` holds a replacement to the same identity, and states `"replacement"`. The runbook requires `true`, so a workspace that lost `retire.json` cannot pass as a replacement.

`loaded_among` now reads the whole profile list; it previously read a list truncated to 16 entries. Nothing in the store, lane, launcher or adapter source changed.

**Proof.**
- Linux fake-root tests:
  - a drifted host is retired and reinstalled with the store's inode and a sentinel's bytes and inode unchanged;
  - a partial retirement completes on a rerun;
  - each of `judge-retire`'s eleven refusals, including mounts at and beneath `L`;
  - an incomplete retirement and a still-loaded profile refuse;
  - a substituted store (same name, mode, owner and group) is refused by `verify-retired`, `judge-launch` and `verify-launch`;
  - a retirement record from another commit, of the wrong shape, or with no identity is refused.
- The fake root runs real `rm`, `install` and `cp`, emulating only root's ownership and permission override. It runs the removals unconditionally. The conditional unload and the interruption table are shown by the runbook's own records on the host, not by these tests.
- Portable tests:
  - the runbook's LR4 and LR6 root commands match the tested sequences as text;
  - no removal names `L` or the store, and no `install -d` appears;
  - mountinfo is unescaped and matched only at or beneath the path;
  - a launch profile past the record's bound still refuses.
- Mutants:
  - replacement: freshness split into two; kept-root membership; store identity in two places; the retirement's commit; the mount refusal; `L`'s mode; the store's owner, group and mode; `rm` custody; unnamed entries; the loaded profile's file; the retired profile;
  - portable: whole-list reading; unescaping; the path boundary.

**Cross-review** (Codex `gpt-6-astra`).

The design pass proposed this option. It rejected the alternatives:
- freezing updates and logging in again;
- moving the store (an unproven migration);
- a live swap;
- a runtime built from pinned packages.

The build-plan pass returned "build with changes". All of its findings were adopted:
- **P1:** mount aliases in the removal's scope;
- **P1:** a process scan presented as proof of quiescence (replaced by a controlled fresh boot and the store law's `reboot-anchor` refusal);
- **P1:** the retirement's rerun semantics;
- **P2:**
  - preservation evidence;
  - the D2 order;
  - the exact R10 differences;
  - tests and mutants;
  - session continuity;
  - the truncated profile list.
- **P3:** no controller reinstall; LR8 verifies by content, and S0 now says so.

S9 now runs the launch preflight and names M8-D2's reboot obligation.

The one pass on the diff returned "fix-then-ship". Every finding was fixed:
- **P1:** the fake root's `rm` obeyed read-only modes, so retirement tests failed in setup. CI showed it, and the harness now emulates root's override.
- **P2:**
  - a `grep` error read as "not loaded"; absence is now status 1 only;
  - LR8 ran R17, which needs the controller absent; it is now an explicit block;
  - recovery restaged into existing staging; it now rejudges it;
  - `verify-launch` silently fell back without `retire.json`; it now states `replacement`;
  - LR2 and S9 lacked D2's workspace and commit; LR2 now carries a block, which S9 cites.
- **P3:** a malformed `retire.json` raised a traceback; it is now a refusal.

**Limits.**
- The store directory's identity is proved; the binding inside it is judged by the store law at the next maintenance.
- Real root ownership, real mounts and real AppArmor removal are observed only by the host's records.
- A hostile root, a concurrent administrator and another mount namespace are out of scope.
- `M8-N4-host-runtime.md`'s claim that `cp --no-target-directory` refuses an existing destination is too strong. Its bytes are kept.

**To resume** (owner authorization):
1. LR0 to LR8 at the merge commit, with M8-D2 requalification and its baseline as LR2 needs them.
2. Then the N4 session at S0. The refused S4's evidence is kept under new names.
3. S4, S6a, S5, S7, S8 and S9.
4. S10 at least 24 hours after the recorded S3.

S3's login evidence stays historical; the transition is recorded on #77.

### N4 session: replacement, S0 to S10 (2026-10-03 and 2026-10-04)

Each step is recorded on #77 with its evidence digests.

**Launch replacement at `88effe1`**
([#77](https://github.com/sushiHex/constructicon/issues/77#issuecomment-5972942853)).
- **D2 on the new kernel.** It verified and the probe qualified on `6.8.0-142-generic`, and the drift baseline was recaptured.
- **Retirement and reinstall.**
  - `judge-retire` recorded the store as `{"dev": 64512, "ino": 1573540, "gid": 1002}`.
  - `verify-retired` found only that store.
  - The reinstall verified with `replacement: true`, and the runtime moved from `62ab0390…` to `f3445bcb…`.
- **Preflight and controller.** Preflight passed, and the controller verified by content at `C`, so no reinstall.
- **No login or credential operation ran.**

**S0 to S9**
([#77](https://github.com/sushiHex/constructicon/issues/77#issuecomment-5972977282)).
- The refused S4 record was kept as `s4-refused-qualification.json`.
- S4 and S6a qualified on `pro`, with the readback the #78 bound admits: credits present, the spend control not reached.
- g2 was published and activated, and S8's active startup was clean.
- S6b and S6c refused with exactly their expected faults.
- **S9 restart.**
  - D2 qualified again on the new boot.
  - g2 refused on its stale anchor, and the publish before re-anchoring refused.
  - Re-anchored qualification gave g3, activated, with a clean active startup.

**S10, run early at the owner's request**
([#77](https://github.com/sushiHex/constructicon/issues/77#issuecomment-5984386980)).
- About 69 hours after S3, the active g3 startup was clean, but refresh was *unmeasured*: no `auth.openai.com` connection and an unchanged credential.
- The access token from the login was still valid, and the pinned client refreshes lazily.
- At the pin, refresh is due when the access token's `exp` is within 5 minutes, or after a 401. The 8-day interval applies only to a token with no `exp` (`research/m8-codex-token-refresh.md`). The `exp` is unobserved, so the time a run would measure refresh is unknown. A measuring run needs its own authorization and fresh evidence names.

**State.** g3 is active. The VM is running on boot `11911d42…`.
`vendor_conformance_qualified` stays false until refresh is measured and the
owner records a qualified disposition.

### CI timing flakes made deterministic (#110)

Each fix makes the outcome depend on an event, not on timing. No bound was
raised.

**Driver-death wait** (`test_driver_death_and_explicit_successor_reconciliation[…-before-worker]`).
- **Cause.** The test killed the driver as soon as the native had started, possibly mid-handshake. The native then ran its own graceful drain, which at the pin can take up to 30 s for in-flight requests (`app-server/src/lib.rs:1178-1187`), before exiting on EOF.
- **Fix.** The owner now reports its `before-worker` pause, and the test kills only after that report, from the same idle state as `active`. It then waits on the pinned pidfd's exit event instead of polling `/proc`.

**Deadline attribution** (`test_the_deadline_cuts_an_actively_streaming_client`).
- **Cause.** The launcher shares the relay's deadline and cancels the owner when it passes. So a refusal past the deadline could be counted `stopped` if the owner's cancellation was seen first. A read reset by the zone's kill, on a socket still holding unread bytes, was counted `reset`.
- **Fix.**
  - `_require_live` now judges the deadline first.
  - Every stream read and send goes through `_io`, which judges a `ConnectionError` by the same liveness. A reset past the deadline, mid-read or mid-send, is the deadline's cut, and any other `OSError` stays a fatal relay failure.
  - The containment test asserts the whole `observed` count.
  - Mutants 61 to 64 cover the rules: deadline first, reclassification, only a `ConnectionError`, and the send path. N4-L3 is re-anchored.

**Bridge mutant 1.**
- **Cause.** It was not a hang. With `CI=true`, pytest diffed a 256 KiB byte operand, which took about 33 s per kill and once crossed the 60 s harness limit.
- **Fix.** The test compares length and SHA-256 instead of the bytes.

### #110 follow-up: the two later flake reports

The three fixes above merged in #118. Two additional failures were then
reported on #110, on the same pinned `rust-v0.153.4` client.

**A stream `ETIMEDOUT` before the relay deadline.** The portable test injected
the upstream read error as soon as that read began. On a loaded Windows run,
the relay could close the client before the test read its established reply or
observed the first hello at the peer. The test now holds the injected error on
an event until both establishment observations are affirmative and the upstream
read has begun. It then releases the error and requires the same `accepted: 1,
reset: 1` result. The acquisition deadline and every bound are unchanged.

**Empty startup proxy connections.** One foundation run of the clean,
plugins-off startup test recorded five `denied:eof` connections and no parsed
CONNECT head. A bridge connection reaches the relay before the bridge reads
any client byte, so an EOF count alone cannot say whether the pinned client
sent a partial head or when it closed its local proxy socket. The zero-denial
assertion remains in force. The test now preserves bounded, byte-free events
for relay handler entry, client read lengths, protocol drain and relay exit,
and marks the evidence `assertions_passed: false` until all assertions pass.
This is diagnosis, not a correction or a passing N4-L2 claim.

An exact-pin source check ruled out the identified candidates: plugin startup
is gated by `plugins_enabled` (`app-server/src/message_processor.rs:525-543`,
`core-plugins/src/manager.rs:2735-2745`); `--strict-config` prevents a default
fallback (`app-server/src/lib.rs:540-563`); `account/read` with
`refreshToken: false` is local
(`app-server/src/request_processors/account_processor.rs:1108-1130`); the
bound static catalog ignores online models refresh
(`models-manager/src/manager.rs:556-565`); remote control waits for
authentication (`app-server-transport/src/transport/remote_control/websocket.rs:579-650`);
and Linux proxy route selection does not probe TCP
(`http-client/src/outbound_proxy.rs:248-282,352-380,575-585`). It did not
identify the caller of the five sockets. Green runs cannot settle whether
that caller is intermittent, because this trace records only observed
connections.

The first instrumented [foundation run 37454996873](https://github.com/sushiHex/constructicon/actions/runs/37454996873)
passed N4-L2 at head `fd0c3fe`. Its `n4-lane-startup.json` has
`assertions_passed: true`. The clean run recorded no relay handler entry, no
CONNECT head, no destination and no denial. In the same test, the plugins-on
control recorded three 59-byte CONNECT heads and destination denials during
`startup`, then two separate zero-byte client reads counted `denied:eof`
during `protocol-drain`, before relay exit. These control observations show
that an empty relay connection can occur during protocol drain. They do not
establish when or why the clean run in #120 produced five such connections.
The fourth flake remains unresolved; a green run is not a deterministic fix.
PR #124 subsequently changed the current pin to `rust-v0.160.1` and changed
this test's positive control from plugin sync to an analytics exporter. The
`fd0c3fe` trace above is historical evidence at `rust-v0.153.4`; it does not
qualify the new pin or identify the clean-run EOF caller there.

**Verification.** On the instrumented head `fd0c3fe`, the ordinary `verify`,
M8 runner qualification and all four M8 containment lanes passed. Locally on
Windows with Python 3.11.15, `uv run --python 3.11 verify` passed ruff, strict
mypy, the four import contracts and pytest (3,541 passed, 678 platform skips). A separate
Python 3.13 attempt stopped at
`test_every_structural_sqlite_channel_must_prove_its_exact_journal`: its
pre-existing `_MailboxProxy.__getattr__` test double is not recognized by the
runtime `Channel` protocol check on that interpreter. That test and the
assembly code are unchanged by this slice; the 3.11 gate is the local result,
not a claim that the 3.13 suite passed.

### N5 Stage 0a: one vendor pin record

This is the first half of the upgrade routine (`M8-N5-state-review.md`). It changes no behaviour at the current pin.

**One record.** The workflow's acquisition step is the pin. `VENDOR_STEP` is its exact template, and `vendor_pin` parses it while `render_vendor_step` writes it, so each URL stays bound to its output file and to the digest check run on it. The version and the catalog commit are read from the URLs, never stored twice.
- A pin anywhere else in the workflow is not the pin.
- Another host, a query string, another output file, an unchecked download, two steps, no step, or a zero-padded version all refuse.
- The step must end where the next step begins, so nothing can run after its last command, not even a condition.
- YAML context, such as a disabled job or an anchored scalar, is deliberately not parsed by the stdlib-only host script. Instead, CI opens the package and the catalog it actually installed under the parsed pin's digests. A pin that names files CI never acquired fails CI, and a host reads pins only at commits whose checks passed.
- `derive` now takes the two vendor digests from the step rather than from loose lines.

**The host reads the pin from the commit.** A read-only command, `vendor-inputs C W`, proves the launch blobs at `C` and lists the package and catalog URLs and digests. The replacement runbook's LR3 now runs an **R11 variant**: R11's provenance steps, then `vendor-inputs`, then the downloads, checked against the listed digests. Frozen R11 named the old release by literal URLs. A test holds the variant equal to R11 apart from the stated differences.

**Tests read one helper.** `tests/vendor_pin.py` derives the version and digests from the workflow, replacing three hand copies. The parser's own oracle is two pins written out by hand, never derived. Recorded vendor behaviour (the models a fixture names, request shapes, efforts) stays recorded; it is re-observed on a bump, not derived.

**The host's archive rules run in CI.** CI unpacks the package with `tar`, but the host plans it with stricter rules (no links, special modes or duplicates). The foundation lane now runs the actual downloaded package through `vendor_plan` and requires the planned tree to equal the one CI installed. A release the host would refuse is found before any host retires its old one.

**Proof.**
- Portable tests: the round trip, decoy and refusal cases, and the R11 variant.
- Linux: `vendor-inputs`, and the CI parity test.
- Four new mutants are killed: the step read exactly once, the version from the URL, the derived values including the pin, and malformed pins never rendered.

**Cross-review.** Codex (`gpt-6-astra`) reviewed the plan before building, verdict "revise", with no P0. Adopted:
- the canonical step binding;
- one JSON output for `vendor-inputs`, built on the full launch-blob proof;
- an R11 variant with digest checks, not just new URLs;
- independent parser oracles;
- the CI host-archive check.

The one pass on the diff returned fix-then-ship.
- **P2, adopted.** The parser recognized a text match, not the executed step. It now requires the step boundary, and CI binds the pin to the files it installed.
- **P3, recorded.** The R11 variant ends with `cat "$W/vendor.json"`, so the block exits 0 even after a failed listing. No download follows a failed listing. The runbook's verdict is the `R11 complete` line, never the block's exit status.

### N5 Stage 0a: the bump tool

This is the second half of the upgrade routine. It changes no behaviour at the current pin.

**Against the plan.** The routine's item 2 says the tool "opens a PR". It does not: it rewrites the pin and reports, and whoever runs it opens the PR, whose gates are the routine's item 3. Its checks go beyond the plan's `SHA256SUMS` alone, as below. The plan's bytes stay as decided.

**`scripts/bump_codex_pin.py [--version X.Y.Z] [--dry-run]`.** A person or an agent runs it; CI never does. It is stdlib-only and writes nothing until every check passes.
- **Selection.**
  - Candidates come from GitHub's complete tag listing (`git/matching-refs/tags/rust-v`, observed 2026-10-05 to return all 1418 tags on one unpaginated page). They do not come from the release list, which GitHub cuts at 1000.
  - Only exact `rust-vX.Y.Z` tags count, and they are ordered as numbers.
  - The greatest tag whose release is published and is neither a draft nor a prerelease is chosen, or exactly the requested one.
  - At most the ten greatest are tried; past that the tool refuses rather than settling on an older release.
- **No downgrade.** An older version refuses. The pinned version with different bytes refuses as something to investigate. The pinned version with the same bytes is a no-op.
- **Two digests and the bytes.** The package must be listed exactly once in the release's `codex-package_SHA256SUMS`, GitHub's own asset digest must agree, and the downloaded bytes must hash to it. These are agreement checks within GitHub's trust domain, not publisher authentication; the signature is Stage 0b's.
- **The catalog at the tag's commit.** The listed tag object is peeled through annotated tags (at most four) to a commit, and the catalog is hashed there. The current pin's catalog is re-fetched and must still match its digest.
- **One rewrite.**
  - Only the acquisition step changes, rendered by `render_vendor_step`. A second copy of the step anywhere refuses.
  - The result must parse back to the new pin. Uniform line endings are kept, and mixed ones refuse.
  - The bytes go to a private staging file. They replace the workflow atomically, and only if it still holds the bytes read at the start, so an edit made while the tool fetched is never overwritten. A write in the instant between that last comparison and the replace is not seen; the tool has no concurrent writer of its own.
- **Fetches.**
  - HTTPS on every hop, including redirects. Each fetch is bounded, and a paginated response refuses, because every listing must be complete.
  - A token from the environment goes to `api.github.com` only, as an unredirected header. urllib copies ordinary headers onto a redirect to any host.
- **Report.**
  - Old and new pins.
  - The newest listed model per family. Its lowest effort is ranked by name (`low` to `ultra`), never by list position, and is reported as unknown if the model lists an effort the ranking lacks.
  - The recorded behaviour to re-observe: the native fixtures, request shapes, and the pinned facts in `M8-N5-state-review.md`.

**Cross-review.** One Codex (`gpt-6-astra`) pass on the diff returned "request changes". Every premise was reproduced before acting.
- **P1, adopted.** A redirect could carry the token to another host, and over HTTP. Confirmed in the stdlib's `redirect_request`. The fix is the unredirected header and the HTTPS-only redirect handler.
- **P1, adopted.** The CI signature step drafted for this PR would have failed at the current pin. `rust-v0.153.4` publishes Sigstore bundles for its binaries but none for the package archive (its asset list, checked 2026-10-05). `0.158.0`, `0.159.0`, `0.160.0` and `0.160.1` do publish one. The step therefore moves to Stage 0b, in the same PR as the first bump, whose run is its positive control. There it also binds the certificate's own commit with `--certificate-github-workflow-sha` (present in cosign `v2.6.5`'s source), rather than the tag's current target.
- **P2, adopted.** Two P2s concerned the write path: the compare-and-swap compared two reads taken inside `apply`, and the staging path was shared. The fix compares against the bytes read at the start and stages to a private file.
- **P2, adopted.** The 1000-release window could hide a greater stable release. The fix selects from the complete tag listing, and a paginated listing refuses.
- **P3, adopted.** The first-listed effort is now the lowest-ranked effort, and mixed line endings refuse.
- **Design choice, recorded.** If the upstream tag is moved or deleted after a bump, later CI refuses. This is fail-closed, at an availability cost.

The connector's review on ready raised one P1, adopted: the first push edited the owner-decided `M8-N5-state-review.md`. Its bytes are restored, and this record carries the difference.

**Proof.**
- `tests/test_bump_codex_pin.py` runs the tool against a scripted GitHub keyed by exact URL; every expectation is written out by hand.
- Thirty-one mutants in `check_m8_host_artifact_mutations.py` are all killed. They cover every refusal, the selection rules, token scoping, HTTPS redirects, the bounds and pagination, the compare-and-swap and its cleanup, and the no-op.
  - The parse-back check is not mutated: a step rendered from a valid pin always parses back.
  - The 404 branch is not mutated either: without it, an unreleased tag crashes the tool rather than misselecting.
- A dry run against the real GitHub on 2026-10-05 selected `rust-v0.160.1`: commit `d27764b8`, package sha256 `34080156…21f0`, and the catalog unchanged from 0.160.0 (`fd219bd9…`). The newest models were `gpt-6.1-sol` (the default), `gpt-6-astra`, `gpt-6-luna` and `gpt-5.6-terra`, each at `low`. Moving the pin is Stage 0b.

### N5 Stage 0b: the protocol at the pinned shapes

This lands at the current pin, `rust-v0.153.4`. The decoder change fixes the current pin too: today's decoder reads `turn.output`, `turn.model` and `turn.usage`, none of which the pinned `Turn` has (`v2/thread_data.rs:366-387`). A real turn would therefore have decoded as a success with no output. The shapes below were read at both `rust-v0.153.4` and `rust-v0.160.0` and are identical.

**`account/updated`, exact match only (decision 1).**
- `updated_plan` admits only `params` exactly `{"authMode": "chatgpt", "planType": <a plan the binding accepts>}`. Both keys are always serialized (`v2/account.rs:545-548`). The record carries no `result` or `error`.
  - Anything else refuses, with the usual neutral notice fault: another or null key, another mode (including `chatgptAuthTokens`), or another plan.
  - An id-bearing one, including `"id": null`, still refuses through `account_request_faults`.
  - The envelope's top-level `emittedAtMs` (`common.rs:2048-2058`) is outside `params` and plays no part.
- The adapter keeps the plan the first exact notice names (`_noticed_plan`). Every later notice must name that plan, and the first `account/read` reading must name it too. A notice therefore never narrows the expected account before the reading, so the rate-limit rule is unchanged.
- Identical repeats pass anywhere: before the reading, before the `turn/start` reply, mid-turn and in the drain.
- A contradiction is a fault, and faults are never removed, so it latches.
- The reading-variant guard is narrowed accordingly. The reading gate (`account_faults`) still never reads a mode. The notice's own `authMode` is matched exactly, which decides nothing about the reading.

**The decoder.** Everything comes from the pinned events, each correlated by the `threadId` and `turnId` it carries.
- **Answer.** It is the text of the single `agentMessage` under `itemsView: "summary"` in this turn's `turn/completed`. `turn/completed` carries the last agent message, or no items under `"notLoaded"` (`bespoke_event_handling.rs:1398-1416`).
  - Any other items shape is damage.
  - An empty text is no answer.
  - **The READ rule:** a READ conversation (no callback catalog) whose turn completes without an answer is damage, so it decodes as partial. A WRITE turn may complete without prose, because the vendor sets `completed` independently of the last message (`:1578-1580`).
- **Partial text.** `item/completed` is admitted for `agentMessage` items only. Its text is the turn's own, not command output, though whatever the model writes is in it. The last completed message is kept as partial text when there is no terminal answer: when a turn never completes, or when it failed or was interrupted, since the vendor drops the last message then (`:1579, 1614`). It stays in the conversation's observation, the evidence a lane records. It never satisfies the READ rule. Through the adapter, a turn that never completes is refused, and the refusal publishes none of it. Streaming deltas stay out.
- **Usage.** It comes from the last `thread/tokenUsage/updated` for this turn: `tokenUsage.total`, both counts required, non-negative, number-sized integers.
- **Served model.** It is the last `model/rerouted` target, as a bounded model name. With no reroute it is unknown (`None`), never the requested model.
- A usage, reroute or item record naming another thread or turn, or malformed, is damage. It never rewrites an earlier fact.

**Ordering and completeness.**
- **Held evidence.** Evidence read while the `turn/start` reply is outstanding is held in arrival order. It joins the transcript as soon as the reply names the turn, before any buffered callback runs, so a snapshot read during a callback stays the later one.
- **Pre-send records.** A record whose bytes were framed before `turn/start` was written is never held, whatever ids it carries.
- **The drain.** The observation is now folded after the drain, so evidence the drain reads is judged like any other.

**Real-binary proofs.** The placement lane (one fake response) and the combined lane (two, across a tool continuation) fold every notification the lane's wire logged from `turn/start` on, now through a drain to EOF, as the adapter's fold does. One limit is pre-existing: the probe consumes notifications while it awaits the reply, so a completion before the reply would stall the lane, never pass it. Each fake response reports one input and one output token, so the assertions are:
- answer `"fixture complete"`;
- usage equal to the number of responses served, which proves both a zero baseline and accumulation (fact 4);
- no served model;
- no damage.

**Proof.**
- Unit tests cover the exact-match matrix, the notice and reading agreement cases (including the two-plan set), the answer and summary shapes, the READ and WRITE rules, partial text, evidence attribution and malformation, held order across a callback, the pre-send boundary (framed and straddling) and the drain.
- Thirty mutants (N5-1 to N5-29, and the re-anchored usage bound) are all killed.

**Cross-review.** Codex (`gpt-6-astra`) reviewed the design before the build. It raised three P1s and five P2s, with no P0. All were adopted after their premises were checked against source:
- held evidence was released after a callback;
- `total` as the turn's usage was unproved, and is now proved by the lanes above;
- the timeout's partial text was missing;
- the pre-send boundary was ignored;
- the READ answer rule was applied to WRITE;
- notice-first narrowing changed the rate-limit rule;
- the drain was not folded;
- the lane proof used only the post-reply records.

Recorded as a design choice: the vendor emits `model/rerouted` as the reroute target, and the source read does not prove that it names the model that finally served the answer. It is published as the served model per decision and fact 5.

The one pass on the diff raised three P2s, with no P0 or P1. Each premise was checked before acting:
- **Adopted.** A failed or interrupted turn erased the partial text seen before it. It now keeps it, as above.
- **Adopted.** The record claimed a timeout publishes its partial text, but the adapter refuses such a turn and publishes none of it. The claim is corrected, and an adapter test now pins both halves.
- **Adopted.** The lanes neither drained to EOF nor logged late records. Both now drain, and the probe's pre-reply limit is stated.

The connector's review on ready raised two P2s, both adopted:
- A later empty message left the older text as the partial text. The last completed message now decides, and an empty one leaves none.
- The lane drain decoded with permissive `json.loads`, so a duplicate-key record after the terminal could pass the real-binary proof. It now reads through the probe's own strict reader.

Recorded, as a design choice: `raw` carries an admitted record whole, so an `agentMessage`'s text, any extra fields it carries, and the existing `turn/` prefix (including `turn/diff/updated`) publish vendor payload. This is the module's documented limit on legitimate turn records.

### N5 Stage 0b: the pin at rust-v0.160.1

The upgrade routine's first real use. It moves the pin to the latest stable release, with the real-binary lanes as the gate.

**The bump.** `scripts/bump_codex_pin.py` rewrote only the acquisition step:
- package sha256 `34080156…21f0`;
- catalog `fd219bd9…` at `d27764b8`, the commit the tag peels to.

**The signature, in CI.** The foundation lane verifies the package's Sigstore bundle with cosign `v2.6.5`, itself pinned by sha256. It checks the release workflow's identity at the pinned tag, the GitHub Actions issuer, and `--certificate-github-workflow-sha` equal to the catalog commit.
- The certificate's own workflow SHA (extension `1.3.6.1.4.1.57264.1.3`) is `d27764b8`. So the binding needs no live tag lookup, and a tag moved later cannot pass.
- The bundle is the legacy format.
- The first run printed `Verified OK`, which is the positive control.

**Re-observed at the pin.** The lanes failed first, and each failure was traced to its cause before changing anything.
- **`goals`.** The feature is stable and on by default at both pins (`features/src/lib.rs:1545` at 0.153.4, `:1703-1707` at 0.160.1). What changed is visibility. At 0.153.4 its tools were visible only where they were available, on persisted threads (`ext/goal/src/runtime.rs:122`). At 0.160.1 they are visible on ephemeral threads too (`:126`), which ours are, while still unavailable there.
  - So every model request now carried three built-in tools, `get_goal`, `create_goal` and `update_goal`. That caused every mediation and combined failure (99 of them).
  - Automatic continuation still requires availability (`runtime.rs:425`), so it did not newly start on these threads.
  - Every recipe that turns the other built-ins off now sets `goals = false`, the production configuration included. This is the existing rule applied, not a new decision: no built-in tool surface beyond the mediated one, and no requests beyond the fixed attempt budget.
  - With it off, every recorded tool fixture is unchanged.
  - Mutant N5-P1 holds it off in production.
- **Sol's `spawn_agent` description.** Its model list follows the new catalog, and one guidance line was removed from the binary's text. That one string in `native_combined_sol_tools.json` and its pin are updated.
  - Its source is independent of the failing test: run 37485328028, mediation artifact 11423161931, `codex-gpt-5.6-sol-contained_python-images-false-unchanged.json`, `requests[0].input[additional_tools].tools`.
  - Only `spawn_agent`'s description was taken. The same file's `exec` description gained goal sections, which `goals = false` removes.
  - The evidence handoff's provenance (`M8-combined-startup-evidence.md`) stays historical.
- **The deadline's SIGTERM.** The native now exits 0 rather than 143. Its retries and its never-terminal turn are unchanged.
- **`account/read`.** The reading now carries `workspaceRouting`, null in a fresh recipe. A non-null value can name another backend (fact 2). Judging it under decision 2 is the remaining Stage 0b work.
- **The startup containment control.** The plugins-on control never ran the plugin sync with the empty-auth fixture:
  - an empty `auth.json` loads as a ChatGPT auth with no tokens, so the remote plugin catalog counts as active (`core-plugins/src/manager.rs:743-764`);
  - it raced unawaited background requests against shutdown, and at 0.160.1 it stopped connecting.

  The control now turns analytics on and changes nothing else. The metrics exporter connects to `ab.chatgpt.com`, and the process awaits that flush before exiting on stdin EOF (`app-server/src/lib.rs:1356-1357`). Plugins stay off in both runs. The test requires that exporter's own `CONNECT ab.chatgpt.com:443`, so another background connection cannot stand in for it. Mutants N5-P2 and N5-P3 hold the single difference.
- **No `account/updated` at startup without a login.** The no-login startup sent none, so fact 1 holds at most with a login. That is a question for the 0.160.1 audit, before the host session.
- **`incomplete headers` is unchanged.** These are connections that send nothing, in tests that pass and start no model turn, with the same count at 0.153.4.

**Proof.** The full real-binary gate passes at the pin: foundation, lifecycle, mediation and combined.

**Cross-review.** One Codex (`gpt-6-astra`) pass on the diff raised one P2 and two P3s, with no P0 or P1. All three were adopted after checking against source:
- the control named no host, and now requires the exporter's head;
- the stated cause of the goal tools was wrong, as corrected above;
- the golden's new provenance was missing, as above.

The pass also found:
- **The signature step.** No fail-open path, and the archive is bound to the installed tree by the host-plan parity test. Replaying the approved archive stays valid for a pin.
- **New default-on features.** Between the pins these are `daemon_auto_start`, `unified_exec_tty`, `worktrees`, `system_proxy_fallback`, `write_stdin_approval`, `guardian_reuse_parent_compaction` and `realtime_conversation`. None adds a model-visible tool or a request path in this stdio recipe. The 0.160.1 audit gives each an explicit disposition.
- **`windows.sandbox_private_desktop`.** It is the only removed configuration key, and it is absent from the Linux recipe.

**Not in this PR, the rest of Stage 0b:**
- model and effort sealed from the catalog;
- relay denials in the shared provider outcome;
- the `check_evidence` identities;
- the `account/read` recovery tests;
- `workspaceRouting` under decision 2;
- the real-binary controls for trust roots and the voice host.

### N5 Stage 0b: the rules at the pin

Every vendor fact below was read at rust-v0.160.1 (`d27764b8`).

**The sealed model and effort (decision 3).**
- The production configuration names `model = "gpt-6.1-sol"` and `model_reasoning_effort = "low"`. These are the pinned catalog's newest `sol` at its lowest listed effort.
- One pure rule, `codex_catalog.catalog_choice`, states the choice:
  - "newest" orders by the numbers in the slug;
  - efforts are ranked by name, never by their order in the catalog;
  - a family with no listed model, or an effort outside the ranking, refuses.
- A foundation test holds `PREPARE_MODEL` and `PREPARE_EFFORT` to that rule over the catalog CI installed. A bump that moves the choice must move them.
- The bump tool's report reads the same rule.
- The turn sends no effort, so the configuration decides it. The provider now:
  - requires the configuration to name one the profile accepts;
  - refuses a grant whose effort differs, or that names none.

  This matters because Luna and Terra default to `medium`, so an unnamed effort would be the vendor's choice, not the grant's.

**Relay denials in the provider (fact 9).**
- `EgressRelay.denied` is the one reading of the relay's counters. The lane and the provider both use it.
- The provider reads it however the exchange ends and refuses the turn's result on any denial, beside the conversation's own faults. A successful answer can no longer mask one.
- The public fault is fixed text. The reason literals stay evidence. This reverses N4's "a denial must not be fatal to the turn", as the N5 design requires.

**Identities in `check_evidence`.** The runbook's checker compares each lane record against what is installed:
- its adapter and protocol revisions, against the installed controller's own constants;
- its runtime digest, against the launch set's `runtime.json`;
- its vendor client's sha256, against the launch set's `native-codex/bin/codex`;
- its catalog's sha256, against the launch set's `codex-models.json`;
- its configuration digest, as before.

The catalog's digest is new evidence, carried inside the existing `executable` record, so the frozen N4 schema's top-level keys are unchanged. `ADAPTER_REVISION` now hashes the whole module (version 2). Version 1 hashed three class bodies, so a module-level rule they call could change without changing it.

Evidence from another controller, runtime, vendor client or catalog never passes, however clean its facts. The launch revision is not compared: it records the vendor tree by path, not by content, so the two digests above are what bind the vendor.

**An unsealed backend stops the session (decision 2).**
- An `account/read` reading's `workspaceRouting` moves model turns to its `backendOrigin`. It leaves account checks and rate limits on `chatgpt_base_url`, and the client checks no allowlist (`account_processor/workspace_routing.rs`).
- Every reading now refuses unless the routing is one of:
  - absent or null;
  - exactly `https://chatgpt.com` with a known residency override (`NO_CONSTRAINT`, `us`, `us_cr`). The override only adds a header on the same host.
- The fault names no origin.
- The relay would deny such a destination anyway. This refuses before any turn.

**Unmeasured and incomplete usage (fact 4).**
- Every model request has input, so a measured total has input tokens. The pinned client publishes two totals without any:
  - `fill_to_context_window` (`protocol.rs:2316`), on `context_length_exceeded`, replaces the accumulated total with `{totalTokens: <context window>}` and every other count zero;
  - with no prior usage it initializes a zero total (`session/mod.rs:4861`).
- A total with no input tokens is therefore no measurement, and the fold reports the turn's usage as unknown, never zero. It is not damage.
- A compaction leaves the total incomplete: its own request's usage is not added (`compact_remote_v2.rs:319`). Both compaction paths emit a `contextCompaction` item, whose payload is only an id. `item/completed` now admits that item type too, and once this turn's compaction is seen its usage is unknown.

**The provider's retries stay at the vendor defaults (owner decision, 2026-10-06, #78).**
- Production sets neither `request_max_retries` nor `stream_max_retries`.
- A built-in provider cannot be overridden from config, Bedrock aside: `merge_configured_model_providers` only inserts (`model-provider-info/src/lib.rs:691-726`). So `[model_providers.openai] request_max_retries = 0` would be silently ignored.
- The defaults are 4 request and 5 stream retries, with a 200 ms base delay. A 429 is never retried; 5xx and transport errors are (`:64-65, 448-453`).
- These retries happen within one `turn/start`, not across dispatches, and stay bounded by the stage deadlines.
- The backend request count is unknown, with this budget stated. No bound is claimed that is not in force.

**The seven features newly on by default since rust-v0.153.4.**
- **Disabled: `system_proxy_fallback`.** It wraps the account and config-bundle GETs in a 5 s timeout and re-sends them through the system proxy, so their count and timing drift. Production sets it `false`.
- **Left on, because none of them can connect, spawn, add a tool or add a request in this stdio recipe:**
  - `daemon_auto_start` and `worktrees` are read only by the TUI or `codex exec`;
  - `unified_exec_tty` and `write_stdin_approval` need the shell tools, which are off;
  - `guardian_reuse_parent_compaction` acts only when approvals are reviewed, never under `never`;
  - `realtime_conversation` is read only by the TUI. The real gate is the experimental-API opt-in, and this client sends no `thread/realtime/*` request.
- `js_repl` and `apply_patch_freeform` are now removed features, so setting them is a no-op, still accepted by `--strict-config` (`features/src/lib.rs:606, 615`). They stay as recorded intent.

**Open before the READ turn: the native tool inventory.**
- Removing `apply_patch_freeform` does not remove the native `apply_patch` tool. Its handler is registered whenever an execution environment exists and the model advertises the tool (`core/src/tools/spec_plan.rs:1269`), without consulting `shell_tool` or the removed flag.
- The pinned catalog's `gpt-6.1-sol` advertises it (`models-manager/models.json:182`), and the default local environment is selected (`exec-server/src/environment_provider.rs:83`).
- So a production turn would offer an unmediated native tool. It writes only inside the native zone, so this is not a containment escape, but ADR 0020 requires tools to be mediated, so it is a tool surface the recipe does not account for.
- The lanes restrict it with a transformed catalog. Production uses the pinned catalog as is.
- Resolving this, and proving the production tool inventory with a pinned-binary request capture, comes before Stage 3.

**The voice host.** The package's `codex-resources/voice/bin/codex-voice-host` is spawned only by the TUI. Neither app-server nor core references it, and `thread/realtime/start` opens connections but spawns no helper. This is proved from source, not from a real-binary control.

**Trust roots.**
- The zone sets `CODEX_CA_CERTIFICATE`; without it the client's default TLS found no roots (#77, S3).
- That switches the HTTP stack to rustls, which adds the zone bundle and also the compiled-in Mozilla roots and the native roots (`http-client/src/custom_ca.rs:296-330`, reqwest `client.rs:683-702`). A TLS protocol-version fallback trusts the Mozilla set too.
- So the variable widens trust rather than narrowing it. Trust roots are not a containment control here. The egress relay is: every connection must reach a sealed, address-pinned destination.
- `linux.py`'s `TRUST_BUNDLE` now states this as proved, replacing "not proved".

**Proof.**
- Unit tests for each rule.
- Mutants killed:
  - N5-30 to N5-42 (effort, relay denial, routing, unmeasured usage, compaction);
  - N5-P4 and N5-P5 (the prepared effort, the proxy fallback);
  - the catalog rule's five, now in `codex_catalog`.
- Mutants re-anchored where the rule moved: the refused-turn discard, the nested configuration, and the usage bounds, whose fixtures are now malformed in exactly one count each.
- The routing override's `isinstance` guard is not mutated: without it an unhashable override raises, a crash rather than a pass.
- The foundation lane checks the sealed literals against the installed catalog.

**Cross-review.** One Codex (`gpt-6-astra`) pass on the diff raised one P1, three P2s and one P3. Every premise was checked against source.
- **P1, adopted.** The adapter revision did not cover the new module-level rules.
- **P2, adopted.** Compaction and initialized zero totals could publish incomplete or false usage.
- **P2, adopted.** The identity claim overstated what was compared. The vendor client and catalog are now compared.
- **P3, adopted.** A malformed routing override raised instead of refusing.
- **P2, recorded above as the open item before Stage 3.** The native `apply_patch` tool survives the recipe.

The pass also checked and rejected four attacks: the sealed effort is what runs, a relay denial cannot be bypassed, routing equivalence holds, and `system_proxy_fallback` is accepted.

The connector's review on ready raised one P2, adopted: a `contextCompaction` item without its pinned `id` was taken as proven compaction and cleared valid usage. Only the pinned shape (`v2/item.rs:426-428`) counts now; anything else is damage and clears nothing (mutant N5-43).

### N5 Stage 0b: the native tool inventory

Design: [M8-N5-native-tool-inventory.md](M8-N5-native-tool-inventory.md), reviewed once by Codex (`gpt-6-sol`, job `job_1e39d303f2d5`) before it was built. This closes the open item above.

**Finding, measured.** The placement lane ran the production configuration, swapped only for its provider and catalog path, against the real rust-v0.160.1 binary. The first request offered `gpt-6.1-sol` fourteen native tools (CI run 37614544749), and in WRITE the admitted callback only nested inside code mode's `exec`. The pinned catalog's tool selectors outrank the configuration, and two more tools are on by default.

**What changed.**
- **The sealed catalog.** `linux.sealed_catalog` closes four tool selectors in every entry. The launcher seals it per launch from the installed catalog, after the probe's custody check, and binds it with `--ro-bind-data` at `CATALOG_MOUNT`. The launch set keeps the vendor's pinned bytes; the host installation, planner, `verify-launch` and bump tool are unchanged.
- **No execution environment.** The launcher also binds `environments.toml` (`include_local = false`) into `CODEX_HOME`. Both sealed files are a launcher-owned `NativeLayout`, never a caller's choice.
- **The configuration.** `TOOL_CONTROLS` pins the default-on gates the other layers leave (`image_generation`, `sleep_tool`, `multi_agent_v2`, `[agents]`, `request_user_input`) and makes tool-name collisions fatal: dispatch is by name and never checks the offer (`core/src/tools/registry.rs:551-573`), and the first registration wins a collision. `apply_patch_freeform` and `js_repl`, removed features, are gone from the configuration.
- **Evidence.** `executable.sealed_catalog_sha256` beside the source's digest; `check_evidence` recomputes it from the launch set.

**Proof, on the real binary** (placement lane, `tests/substrate/test_provider_placement.py`):
- Sealed, READ offers nothing; WRITE offers exactly the adapter's `contained_python` declaration in one `functions` namespace, compared as sent. The WRITE callback round trip completes without an environment.
- The model's call to each of 18 known native names comes back `unsupported call`, with nothing reaching the client.
- Each layer removed alone lets back exactly what it held. The catalog layer holds code mode, `clock`, and the asynchronous user-input tool. The environment layer alone holds `apply_patch`. The configuration holds `request_user_input` and image generation. `[agents] enabled = false` also holds collaboration without the catalog layer, which the design had not predicted.
- The real-zone layout test sees the environment file at its exact bytes, read-only.
- Mutants N5-L1 to N5-L3 and N5-I1 to N5-I9 are killed; two N3a mutants were re-anchored.

**Not proved here.** Later requests after a remote compaction, which the probe provider cannot perform, and a hidden tool under a name not yet known. Both are recorded in the design under "What the lane cannot see".

**Cross-review of the diff.** One Codex pass (`gpt-6-sol`, job `job_37134cdd5a1e`). Every premise was checked against the code.
- **Adopted: the lanes never observed production's own seal.** The placement lane offers the model the image's baked seal, and the real-launcher lanes make no model request, so a `_launch` mounting the raw catalog would have passed every lane. A real-zone test now runs production's launch path with the launch set's vendor and checks the zone's catalog is exactly the seal (the digest the evidence records, never the installed bytes) and its environment file is the launcher's. Mutants N5-Z1 and N5-Z2, in the new in-zone inventory `check_m8_n5_inventory_mutations.py`, are its counterexamples. Together with the placement lane, both halves now meet at the same bytes: production mounts `sealed_catalog(installed)`, and those bytes offer nothing native.
- **Recorded as a design choice: `argv` trusts the layout it is given.** It checks presence, not origin. The boundary is `exchange`, which seals the layout itself; no production caller reaches `argv` or `_run` with its own, and the review found none.
- **Recorded, pre-existing: `check_evidence` does not compare `launch_revision`** with the installed launcher's. It recomputes the seal's digest from the launch set, which the zone test now ties to what is mounted.
- **Recorded: no environment-only layer case.** The environment layer is shown holding `apply_patch` with the catalog layer also removed; alone it removes nothing the sealed catalog leaves.
- **Verified by CI, not by review:** `--ro-bind-data` onto the runtime image's empty `CATALOG_MOUNT` works; the vendored startup lanes start from it under `--strict-config`.

The connector's review on ready raised one P2, adopted: the evidence gained a required field under the same `schema_version`, as #125's `catalog_sha256` had. `LANE_SCHEMA` is now 3, and `check_evidence`, which accepts only the current version, refuses earlier evidence by its version.

### N5 Stage 0b: `account/read` recovery

Design: [M8-N5-account-read-recovery.md](M8-N5-account-read-recovery.md), reviewed once by Codex (`gpt-6-sol`, job `job_63e271332db7`) before it was built. This closes the plan's Stage 0 item: "a 401, then refresh, then a clean or refused reading", with store, mode, configuration and egress restrictions holding (`M8-N5-state-review.md:85`). No production code changed.

**How.** The production startup lane, `run_startup`, drives the real binary with production's configuration, command, URLs and eight-connection bound. Only the destinations are fakes: one HTTPS server at `127.0.0.1:443` serves `chatgpt.com` and `auth.openai.com` by SNI from the trust fixture's throwaway CA, which gained a `chatgpt.com` leaf. The store's credential is a fixture (unsigned id_token, far expiry), restored after. The fake logs each token only by class, and the evidence scan fails on any fixture token. The foundation lane's bridge step lowers `ip_unprivileged_port_start` to 443 for that step only, on the disposable runner.

**Measured** (the design's table): a clean recovery reaches all four methods with no fault and `refresh: measured`; a refused refresh is cached and leaves the file byte-identical; an account change refuses before any new-bearer check, with the new tokens already persisted; an unsealed backend is refused by `routing_faults`. Unpredicted: when the check stays 401 after a good refresh, the adapter's reading recovered again with the new refresh token until the relay's bound refused a ninth connection. Reaching the bound depends on how the vendor's discovery callers race, so a sixth case, `bounded`, proves the refusal deterministically under a three-connection bound: the recovery's fixed opening fills it, and the first discovery still owes a check.

**Cross-review.** The design pass's adopted points are in the design's disposition; the largest was the composition: one fake at production's port 443 replaced an exec shim, a configuration override and a widened connection bound, so the proof speaks for production's own URLs and bound. The diff pass (`gpt-6-astra`) found four introduced defects, all adopted: measured schedules pinned as invariants despite three racing discovery callers, refusal cases that tolerated unrelated faults, a fake that could fail open, and incomplete token hygiene. It also recorded a pre-existing gap: `ExpectedAccount` pins the plan, not the user, so account continuity across readings is not proved here; the account-change case stays strict so that schedule would fail it. The connector's review on ready raised two findings, both adopted: the schedule-tolerant still-unauthorized case no longer exercised the bound it claimed (hence `bounded`), and evidence was published before its assertions (now written unproved first, then marked proved).

### N5: the sealed account identity

Design: [M8-N5-account-identity.md](M8-N5-account-identity.md), reviewed once by Codex (`gpt-6-sol`, job `job_80d69b31fa35`) before it was built. This closes the gap the `account/read` recovery work recorded: `ExpectedAccount` bound the plan, not the account.

**What changed.**
- `account_identity` digests the two facts the wire names an account by, `account.email` (the login) and `workspaceRouting.chatgptAccountId` (the workspace), and keeps neither. The vendor's internal user id is not on the wire, so this binds the account as the wire names it.
- `ExpectedAccount.identity`. `account_faults` refuses a ChatGPT reading that names no login and workspace, and one that names another account than the sealed one.
- Qualification seals its first reading's identity beside its plan, so the after-turn reading must name the same account. The provider refuses an expectation without an identity.
- The expectation travels as one token, `ExpectedAccount.seal` (`<plan>/<identity>`), through the lane's `--expected`, the evidence's `gate.account` (recorded even for a refused reading), `check_evidence` (which accepts `-` only for the first qualification and a login) and the runbook (`read_seal`, `SEAL`). `LANE_SCHEMA` is 4.

**Proof.** Portable tests cover each missing or differing fact, the seal's grammar, per-run sealing, the provider's refusal, and the checker's new refusals. On the real binary, the account-recovery lane now runs every case sealed for the fixture's account, and a new `stranger` case, the same clean recovery sealed for another login, is refused by the identity fault at `account/read`. Mutants N5-A1 to A9 (A5 dropped with the redundant check it targeted) and N5-L4 are killed.

**Not proved here.** The production binding: Stage 3's assembly must take the seal from the generation's qualification evidence, checked against its sealed digest. A switch that only the vendor's hidden user id would show, or one made and undone between the two readings of a run.

**Cross-review of the diff** (`gpt-6-sol`): three introduced findings adopted (the design's seal grammar wording; a custody test that argparse had hollowed out, which CI's mutant N4-L42 also caught; one routing assertion). One pre-existing item recorded for Stage 2: the runbook's S6b expects `account/read` to pass without `chatgpt.com`, but at rust-v0.160.1 `account/read` itself calls it, so S6b must be re-derived before the host session.

### N5: S6b's shape at rust-v0.160.1

The runbook's S6b removes `chatgpt.com` from the startup policy and expected `account/read` to pass and the rate-limit readback to be denied. At rust-v0.160.1 `account/read` itself checks the workspace at `chatgpt.com` (`app-server/src/request_processors/account_processor/workspace_routing.rs:295-325`), so the reading is denied at the relay and the run stops at the third method. Recorded by #128's diff review; fixed here before the Stage 2 host session would have tripped on it.

- **Measured on the real binary.** A new `unrouted` case in the account-recovery lane runs S6b's exact policy with its declared denial. `account/read` is denied (`denied:destination`), no request reaches either host, the vendor reports "workspace routing discovery failed", nothing is refreshed, and the run stops at the third method with exactly the lane's stopped-gate faults and `NO_RESULT_FAULT`.
- **The checker and runbook.** `check_evidence`'s `denial` mode now requires that shape: three methods, `gate` `{completed: false, plan: null, account: null}`, no readback, and that exact fault set with the destination denial. Its test scripts the vendor's error reading. The runbook says why, and its mode list now names `initial` and the account seal.

### N5: a live loser's custody

A losing process that stays alive kept its codex acquisition guard and store lock, because the walker closes nothing after ownership loss and only close released them. The successor's reconciliation then waited on that guard until the loser's process exited, forever when RunHost re-claims in the same process. Reproduced on `main` with a retaining double (both loss paths) before the fix. An optional L0 `RelinquishingCapability` now lets the walker free local custody on loss without any durable write; the codex handle's cleanup splits into the durable closure commit (close only) and one shared local release. Proof and mutants: M8-N5-live-loser-custody.md.

### N5: a lost answer after the lease commit

A caught exception after `record_capability_lease` commits (response loss: the row is durable, only the answer is lost) made the walker discard the acquisition as unrecorded and fail the run, leaving the row `active` on a FAILED run that startup recovery never revisits. Found by the Stage 1 v2 source review and reproduced on `main` (`active`, no disposition). The walker now settles the ambiguous outcome against the journal: a recorded row is closed under the ownership fence like any recorded acquisition; only an absent one is discarded locally. Process death (`InjectedCrash`) was already recovered by the successor. A settling read that itself fails keeps the local discard this path always had (a regression caught by the diff review), and the ownership fence is affirmed by a heartbeat before any physical cleanup, so a late answer after a successor claimed the run leaves the row to it (the connector review). Tests: `test_a_lost_answer_after_the_lease_commit_closes_the_recorded_row`, `test_a_failed_settling_read_still_discards_the_acquisition_locally`; two mutants in `check_m8_native_recovery_mutations`. A FAILED run whose own cleanup fails can still keep active leases: pre-existing, #132.

### N5 Stage 1: the qualification acquisition

The real acquire, record, materialize, close and reconcile of the codex operator provider, which stays unavailable and never dispatches, under one owner-placed authorization (owner decisions of 2026-10-08: a root-owned file with `max_epoch` 1; a per-journal-incarnation budget for a stage that never dispatches; the authorization earns the omitted admission fault while every reason stays published). L0 `QualificationAuthorization` and `QualificationAuthorizing`; admission computes the source graph hash on entry and omits only an authorizing provider's published reasons; the codex provider enforces the whole authorization at `acquire` (recovery included, through the in-memory `LeaseContext.source_graph_hash`) and mints handles that refuse to dispatch; the root-file reader is the only source; `api/qualification.py` is the thin entry over one fixed graph, recovered through its control plane's RunHost. Proven portably (lease-recording response loss, cancellation and ownership loss on the real provider included) and on the provisioned Linux lane with real process death; 16 portable and 8 Linux mutants, one per gate and reader check. The implementation reviews found the dedicated journal assumed rather than enforced, a resolution-lock admission exemption, symlinked ancestors, a startup leak, and (the connector) a stored run with the authorized id but another graph; all fixed. Design, decisions and crash table: M8-N5-stage1-qualification.md.

### N5 Stage 2: the host-session runbook

The operator runbook described only the N4 session, so N5 Stage 2 had no runnable script; a read-only audit at b0d9556 found the session structure stale, not the #126-#129 changes (already in). `M8-N5-host-session.md` composes OC and LR by reference: a fresh session directory beside N4's read-only one, S1/S4/S6a unchanged, g4 published and activated with g3 refusing, the active startup with S6b/S6c at g4, and numbered refresh attempts checked `active` before `refresh` with no elapsed-time criterion. It states five default decisions for the owner to confirm (S6b/S6c run; S4's plan must be N4's `pro`; post on #78; refresh attempts on one boot; LR9 authorized). LR gains LR9, the post-login controller replacement: it confirms LR8 refused an installed tree, sets LR8's workspace aside, removes the tree, then runs R17 to R19 exactly as written (only R16's checkpoint is forbidden after login), and an explicit Order with the probe after the controller is current. OC's S1 prose names the production model by its code constant instead of a stale literal. Tests: every session block parses after the composed common file, the override, g4/g3, numbered attempts, LR9, and every flag the session passes is offered by the real parsers.

### N5 Stage 3, part A: the production host assembly

`codex_host.py` assembles the operator provider from installed facts only (the launch set, the session's sealed policy and production configuration, the operator store and the generation's sealed identity), with the production `READ_PROFILE` and `READ_GRANTS`, a `sealed_account` loader that twins the runbook's `check_evidence` (the evidence is exactly the sealed one, read bounded and duplicate-free, a closed passing maintenance startup, every nested object closed and every affirmative lane fact strict, naming this host's artifacts through the lane's own `launch_facts`), and the three conformance revisions taken from the sealed qualification digest `Q` (owner decision S3-2: a reference, not a conformance claim). `python -m constructicon.api.qualification mint|run` computes an authorization's pins from the host, and runs an installed one through the root-file reader, closing Stage 1's "no production assembly" boundary; run as `__main__`, the entry hands over to the importable module so both commands register the same graph. The owner's Stage 3 decisions S3-1 to S3-4 are recorded in M8-N5-stage3-read.md; part B (the read stage) follows, both before Stage 2 runs. Proven portably and, as the service on the provisioned lane, against the real runtime, vendor and catalog; twenty-one mutants. Astra's review (job_95d1f6760f0b) found the weaker check, the `__main__` graph, the fixture's addresses and state path, the unbounded read and the authority built before validation; the connector review found open nested shapes, permissive booleans and a linked `closure.git`; all are fixed. The `launch_facts` refactor moved three N4 bridge mutants' targets, now retargeted.

### N5 Stage 3, part B: the read stage and its session

The `qualification-read` authorization pins the READ grants, an attempt record and one epoch. `attempt_record.py` is the owner's one durable artifact per authorization (decision S3-1): reserved exclusively at `acquire`, so no later acquisition, even after a journal reset, can dispatch; its intent is written, with expiry checked on both sides, as the conversation's last word before `turn/start`; and its outcome is classified from facts, `not dispatched` only if the write of `turn/start` never began. The record holds Stage 3's evidence list, bounded and never text, including what a refused turn observed and why it was refused. A read authorization's handle dispatches; a clean result salvaged from a failed exchange is now refused for every handle (a pre-existing gap). The fixed read graph carries its task literal inside the node (S3-3), and `mint --stage` pins the read stage. `M8-N5-read-session.md` is the session (T0 to T6): T5 passes only a succeeded run with a completed record, and T6 may spend N5's one more attempt (READ and WRITE together), only after a diagnosed local failure with nothing dispatched, under entirely new names. Proven portably over the scripted client, the entry end to end and the runbook's own programs; twenty-four mutants in the lifecycle lane. Astra's review (job_18dce68827b2) found nine defects, eight introduced and one pre-existing; all are fixed. `codex.py` and `codex_protocol.py` are frozen from here (decision S3-4): Stage 2's evidence records the adapter and protocol revisions, which digest each whole module, so any edit invalidates g4; a change waits for an owner decision on #78.

### N5 Stage 3: the READ session rehearsed on CI

`tests/test_m8_n5_read_rehearsal.py` (foundation lane, new step) runs
`M8-N5-read-session.md`'s own T2 to T6 blocks, composed with HS's common file
and one CI override (OC's `PY` as this checkout's interpreter under the same
isolated `runpy` entry, and the fixture's store key).

It runs over the N3a fixture under a synthetic g4 whose revisions are a
passing record's digest, with the credential swapped to `{}` and restored.
It pins every link of the refusal: the exact `account/read` fault, zero relay
connections, a clean vendor exit on the base runtime, and no observation after
the gate. A second run with or without its journal leaves the record
unchanged, and T6 runs under new names.

Fable's design review (job_08bb94033cdd) held that the store's silence about
`Q` is designed (ADR 0021:160-163), not a defect, and that #132 and the
control-denial narrowing land after Stage 3 (job_5067d4ce7dad).

### #110, the remaining flakes: each outcome now an event

**Driver death.** Nothing in Constructicon ended the harness's native after its
driver was SIGKILLed: the vendor drained its stdin EOF, bounded only by its own
45 s watchdog at `rust-v0.160.1`, so the 5 s wait was a margin over vendor
shutdown. #118's "each fix makes the outcome depend on an event, not on
timing" overstated this one. The owner fixture now spawns the native under
`setpriv --pdeathsig KILL`, so the kernel ends it as its driver exits; the 5 s
is only a hang guard. Production native lifetime remains the launcher's
`--die-with-parent` and supervisor; this is harness hygiene, not production
evidence.

The active stage's "heartbeat stopped" check had leaned on that drain too. It
sampled the heartbeat once the native exited, and the slow drain had given
the worker's supervisor time to tear the worker down. The test now pins every
child of the owner before the kill and waits for each to exit. That includes
the worker's supervisor, a subreaper that exits only after reaping the
worker's whole tree, so the heartbeat has stopped by construction.

Proven portably (the native, and only the native, is wrapped; one mutant) and
on Linux (a stub that ignores EOF exits with its killed owner). That stub
announces itself on a FIFO, which it can do only after `setpriv` has run
`prctl` and exec'd it, so the kill can never beat the signal's installation.

**Startup EOFs: corrected attribution.** The five `denied:eof` connections were
the plugins-on positive control's, not the clean run's: job 112020223955 fails
at the control's assertion, after the clean run's zero-denial assertions
passed. The passages above that attribute them to the clean run, and the
exact-pin search for a clean-run caller, rest on that misreading. #124's
awaited analytics exporter replaced the racing control, and the control now
requires its denials to be destination denials only.

**WRITE worker entry.** The 5 s bound covered about 0.3 s of work, not the
4 s the report assumed (setup precedes it), and an early end of `execute`
read as the same timeout. The test now races the worker's entry against
`execute`'s end, with no margin, and names the outcome if `execute` ends
first.

**Bridge mutant 4.** Its killing test could pass with the mutant in place: a
reset that reached the dial before it returned took the forwarder's
failed-dial exit, which ends it without the wake. The test now waits for the
dial to return before the reset, so only the wake can end the forwarder; the
test's leaf is blocking, as production's is.

**N3b mutant 15** (found in this PR's own CI). Without the control check before
the dial, the relay still dials, and its post-dial check refuses. The killing
test's only discriminating fact was the peer's accept list, which can lag that
dial, so the mutant survived once in 0.10 s. The test now also counts the
upstream sockets the relay opens, the relay's own witness that it never
dialled.

No production code changed.

### PR #140: committed plan-manifest baselines and complete staged inventory

The new `scripts/regen_plan_manifest.py` initially trusted working manifest
digests and enumerated only manifest entries. Isolated Git fixtures reproduced
both introduced connector findings: a staged frozen-plan edit plus a matching
manual digest succeeded, and an unnamed staged new document was omitted while
the helper reported success. Omitting the frozen plan's manifest entry also
bypassed the first implementation's check.

The helper now anchors unnamed documents to `HEAD:docs/plans/MANIFEST.sha256`
and checks the complete staged Markdown inventory. Unnamed digests, missing
committed entries, staged deletions and unnamed additions refuse before a
write. Manifest and staged document conflicts must be explicitly resolved
before refreshing; all standard and diff3 manifest conflict markers refuse.
The helper also checks the manifest's unmerged Git index stages before reading
its baseline, because modify/delete conflicts can leave marker-free working
bytes while the index remains conflicted.
Named new and living documents use staged blobs even if working bytes differ.
Naming a document does not approve editing a frozen plan, and deletion or
renaming is outside the helper's supported workflow.

`tests/test_regen_plan_manifest.py` supplies real Git fixture proofs for these
refusals, unchanged manifest bytes on refusal, no-op behavior, named staged
updates and conflict refusal. Five new cases in the existing
`scripts/check_m8_mutations.py` inventory remove the committed baseline,
complete staged inventory, omitted-entry check, conflict-marker refusal and
unmerged-manifest-index refusal;
they use the shared assertion-only mutation runner and existing CI job.
At the first repair (`a7569e8`), the manifest fixtures, docs validation and
mutation-inventory checks passed together (111 tests), and all 37 M8 mutants
were assertion-killed on Windows. A further connector finding reproduced an
omission on one manifest conflict side hidden by the aggregate parser. That
evidence did not establish each side's inventory. The follow-up removes
automatic manifest conflict resolution entirely; a test with each marker and
otherwise unique valid entries isolates the marker check from other parser
refusals for its mutation proof.
The first follow-up (`e5002e7`) passed 24 manifest fixture cases and 93
docs/inventory checks locally (117 total); all 37 cases in the updated M8 mutation inventory were
assertion-killed on Windows, including the explicit conflict-marker check.
Its further connector review reproduced a real modify/delete conflict whose
marker-free working manifest was accepted despite unresolved index stages.
The index check applies to every conflict form; real Git fixtures cover both
modify/delete directions, add/add with manually resolved working bytes, and
acceptance after the caller stages an explicit resolution.
The index follow-up passed 28 manifest fixture cases locally. Its fifth
manifest guard-removal mutant was separately assertion-killed on Windows.
No frozen plan, adapter, protocol or runtime behavior changes in this repair.

### Issue #141: Stage 4 WRITE planning draft

[M8-N5-stage4-write.md](M8-N5-stage4-write.md) specifies proposed WRITE
authorization/assembly pins, the fixed writer and downstream contained gate,
attempt accounting distinct from capture/gate qualification, owner-run smoke
and session shape, bounded evidence and future proof requirements. Its seven
S4 decisions are open on #78. The recommended installed route expects the next
generation: LR9's ordered procedure depends on LR1's fresh boot. Conditional
g4 reuse needs a separately reviewed owner-approved no-reboot controller and
quiescence procedure as well as sealed-fact equality and compatibility proof;
this draft supplies none. Unchanged adapter bytes alone do not qualify a host.

Status: Review draft: S4 decisions open on #78; authorizes nothing.
This entry records a planning draft, not implementation or executed proof.
The owner has not run Stage 2/3 in this planning session. Stage 4 implementation
remains gated on owner-declared Stage 3 completion, S4 decisions and #132's
merged cleanup outcome. No code, host action, model request, qualification,
production availability or owner decision is established here.

Independent Claude review `job_ce5e2115ccef` (actual selected model
`claude-opus-5-5`) found two introduced planning blockers: the existing
controller route cannot preserve g4, and WRITE root grants/observation limits
and checkpoint-only recovery needed explicit treatment. Both were reproduced
against source and adopted, with refinements to phase bounds, base/tree proof,
acquisition ordering, smoke isolation and authorization compatibility/scope.
Its proposed narrower freeze was rejected because the wave brief freezes both
modules; the S3-4 citation was corrected to acknowledge its narrower text.
Reviewer uncertainty about issue state was not treated as evidence; the owner's
confirmation that Stage 2/3 are unrun remains the host status. The plan's proof
requirements remain future work; no second cross-review is claimed.

### #143 — proposed operator disposal of unreconcilable capability accounting

[ADR 0022](../../adr/0022-operator-disposal-records-abandoned-capabilities.md)
is Proposed. Its docs-only slice inspects `d355416` and the complete #143 and
#132 discussions; it adds no implementation or behavior evidence. Only the
owner may accept it, and the documentation PR does not settle that decision.
The issue remains open; implementation needs a separate issue after acceptance
and #132's merge. Claude's independent cross-review at `f580d7d`
(`job_98aaf8880642`, actual `claude-opus-5-5`) found the core valid and nine
refinements. Its issue access was unavailable; the drafting agent and root
independently read the complete discussions. The ADR records all nine adopted
dispositions, distinguishing introduced gaps, a simplified design choice, and
the pre-existing bounded result query. Exact-head verification remains required
after these changes and rebase; the review is not owner acceptance.

The proposal names at most 100 exact `(lease_id, acquisition_epoch)` rows and
requires ADMIN, a bounded reason, an idempotency key, and a RUNNING run with NULL
journal ownership. One co-located transaction compares a sealed run/row fence,
keeps ownership and its epoch unchanged, moves the exact active batch to
`lost` with no disposition, and records canonical lease transitions plus a
positively sealed command receipt. The three command crash seams, worker-claim
races, truthful public result summary/detail, migration, and accepting/refusing
tests are future
proof obligations, not results of this slice. Receipt-backed `lost` abandons
cleanup accounting; old opaque lost facts have unknown cause. Neither proves
process death, lock release, physical cleanup, or store reuse.

The review corrections require every lost transition to carry either exact
disposal ownership or a positively sealed migration-only old witness; removing
both audit and relationship must still fail row-to-proof coverage. Per-run
accounting era floors bound server-issued new detail cuts because legacy initial
seals contain no event position. Result-family `result_schema_version=2`
separates disposed and opaque lost counts and labels truncated failure previews
partial. Real SQLite tests replace the unnecessary full journal double. Invalid
input refuses before command claim; observational refusals itemize the complete
bounded batch. A queued submitted resume can lose its attempt fence before
claim and still be followed by ordinary recovery. Private reason text is in
both request and plan. The connector review of `5767164`
([comment 4227634594](https://github.com/sushiHex/constructicon/pull/146#discussion_r4227634594))
found an introduced privacy oracle in the draft's public request/plan digests.
Source inspection confirms the request hash is deterministic; an executed
credential-free synthetic three-candidate check recovered the actual reason.
That is hash-oracle evidence, not disposal implementation or public-surface
proof. The corrected proposal keeps reason-bearing hashes in the private
command/event relationship. All run-readable audit, accounting, result and
receipt-reference bytes, including reference content hashes, derive only from
public records. Private binding/replay integrity and actor-or-ADMIN command
detail authority remain unchanged. Accepting READ-only recursive field walks
and indistinguishable public records for different private reasons are future
proof obligations. This corrects cross-review disposition 9's insufficient
removal of only a dedicated reason digest; no additional Claude review is
claimed. All proposed behavior remains future implementation/proof.

The source-backed correction is that `runs_resume` already reaches RUNNING with
no live owner and clears same-host deferral. No new retry command is proposed.
Persistent reconciliation fails before the first control check, which is why a
recorded cancellation alone cannot pass it. #132's guard is still unmerged at
the inspected baseline; its accepted implementation direction refuses all four
terminal statuses, including PARKED, while any active row remains. A retained
completion with cleanup failure then stays RUNNING/owner NULL. After disposal,
ordinary resume still can fail on unnamed active rows or a retained physical
guard; cancellation and checkpoint/output behavior keep their existing laws.
The proposal adds no Stage 4 prerequisite and authorizes no host or vendor work.
