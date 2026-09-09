# M8 implementation record

Status: PR A merged; hosted-runner qualification; not milestone completion.

Authority: [accepted ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md)
and [frozen rev 1](../milestones/M8-live-executors-rev1.md). PR #26 merged as
`3ee1beb6a58fac0bab85841a1f34d96b514c3c34`, PR A's exact base. The merged
tree equals its reviewed head `8308cf8`. Approval does not provision Linux or
a gateway. Neither the frozen plan nor its planning evidence is edited here.

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
[Proposed ADR 0019](../../adr/0019-hosted-linux-runners-are-requalified-not-image-pinned.md)
separates the rolling host we observe from launch artifacts we control. That
evidence-location decision still needs acceptance before PR B can use it as
its acceptance environment. Accepted ADR 0018 and frozen rev 1 are unchanged.

One credential-free workflow provisions a fixed Ubuntu bubblewrap package,
a non-sudo service account, and a reviewed profile attached only to a private,
root-owned executable copy. A separate non-root probe checks the exact kernel
profile stack, six namespace identities, service identity, read-only mount,
private loopback, missing host home/sysfs, reduced privileges, and refusal of
nested and unprofiled namespace creation. Add-only loading, absent-path guards,
and unchanged global restrictions prevent provisioning from silently replacing
policy. Nothing is installed on Windows or imported by Constructicon runtime.

The first two jobs refused because the host supplied no bubblewrap profile.
After operator authorization, the first profile loaded but its exec rule
requested an additional executable attachment search. The fixed named stack
removes that search entirely; it does not add an inheritance or unconfined
fallback. The next job launched with the expected enforcing stack and exposed
two incorrect probe assumptions: `--dev` uses an intermediate user namespace,
so the child map's parent-side zero is not host root; explicit AppArmor userns
denial reports EACCES rather than the global gate's possible EPERM. The final
checks name the exact namespace operation and the pinned mapping recipe.
Both corrections were traced to upstream source, not accepted merely to make
the probe pass. References and operation are in [the runbook](../../M8_CI.md).

The 50 portable tests and 20 assertion-killed mutations test the probe's
refusal logic, not Linux containment. Actual job links, image/commit evidence,
and exact-head gate results belong in PR #28. Its JSON always says
`runner_prerequisites_only` and `production_available: false`. The benign
diagnostic root borrows `/usr`; it is not PR B's pinned runtime. No hostile
process-tree cleanup, complete filesystem/FD exclusion, gateway, live model
call, or production availability is claimed by qualification.

## Remaining slices and operator prerequisites

PR B still needs its complete physical proofs under the actual Linux service
account and production policy. Hosted-runner qualification supplies only
prerequisite evidence. The Windows machine remains unchanged; no gateway,
secret access, paid request, or account login has been authorized.

B: Linux launcher and containment. C: safe async WRITE capture. D: contained
async gates. E: selected gateway integration and deployment-specific
conformance. F/G/H: Claude Code, Codex, then Pi and integrated closeout.
No live WRITE profile is enabled before capture, gates, and routed authority
are proved. The public model contracts are not substitutes for those proofs.
