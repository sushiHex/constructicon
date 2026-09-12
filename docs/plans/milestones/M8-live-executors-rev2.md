# M8 rev 2: native harnesses, contained tools

Status: review draft; **not approved for implementation**.

Decision owner: [#38](https://github.com/sushiHex/constructicon/issues/38).
Proposed authority: [ADR 0020](../../adr/0020-native-harnesses-mediate-contained-tools.md).
Repository baseline: `3718a86cc16a68f02ba22c569de5058b2a63371d`.

This is a proposed successor to [M8 rev 1](M8-live-executors-rev1.md), not an
amendment to its bytes or an assertion that its remaining slices shipped.
Until an explicit owner decision accepts the successor ADR and this plan,
[ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md),
[ADR 0019](../../adr/0019-hosted-linux-runners-are-requalified-not-image-pinned.md)
and the approved rev-1 scope continue to govern. Merging a draft proposal
alone does not accept it, authorize a login, or unblock implementation.

## 1. Outcome and authority

Complete M8 with interchangeable task-shaped executors, beginning with the
pinned Codex harness, then independently qualified Claude Code and Pi adapters.
Codex goes first because the repository has measured its bounded interface
and process lifecycle. It receives no special kernel operation, task contract,
grant, or scheduler. Substitutability remains the milestone's test, not a claim
that the three vendors have the same authentication or extension mechanisms.

The proposed native mode lets the vendor harness own supported account login,
storage, and refresh. Constructicon owns the invocation, sealed permissions,
callback validation, and contained workspace workers. The harness has no
workspace mount; a worker has no account store or vendor route. ADR 0020 owns
the precise trust, account-maintenance, egress, and versioning decisions. This
plan owns sequencing and the evidence required before those decisions become
an available executor. It does not define a second version of their law.

The merged A-D foundations remain: complete profiles, qualified Linux process
containment, safe WRITE capture, and contained gates. The accepted bounded
duplex and fixture placement remain useful mechanisms and evidence; the
fixture is not promoted into a production provider by renaming it. Existing
gateway mode remains a separate option. Native account access is a deliberate
new mode, not a way to claim that a subscription login is a gateway credential.

Linux qualification remains in GitHub Actions under ADR 0019. There is no
Hyper-V, WSL distribution installation, separate Linux host, credential, or
deployment provisioning in this planning change. Actions proves credential-free
properties; it is not the selected home for a developer's account. A live
deployment requires a separate, explicitly authorized Linux arrangement.

## 2. Evidence already obtained, and its limits

These are completed investigations, not production acceptance:

| Boundary | Exact reviewed source and merged result | Executed evidence | Limit |
| --- | --- | --- | --- |
| Scoped startup | #62 head `482881aa23757820f85c92d9757e1d1e4b6d2db3`; merge `08c8243e05f734509abae93d550beafeb28d5ce9` | [Linux run 34661840154](https://github.com/sushiHex/constructicon/actions/runs/34661840154), artifact `10287857289`; independent startup review | Account-empty home and local fake peer only |
| Journal-driven native recovery | #64 head `26b182c4ab69a567076e41d178d3b49b33645751`; merge `3718a86cc16a68f02ba22c569de5058b2a63371d` | [Linux run 34666495658](https://github.com/sushiHex/constructicon/actions/runs/34666495658), artifact `10288803813`; independent source and artifact review | The exact credential-free fixture and placement, not authenticated recovery |

Both merges have trees identical to their reviewed source heads. The recovery
artifact's published digest is
`3b2f124b9f2163638bdc6b4a1f7cfb1aab78692ba85584fcbe6d34fc466598ac`.
It carries 12 native and 19 portable recovery checks, all 17 recovery mutants
killed, and the retained startup, mediation, and containment lanes. Windows'
2,041 passing tests and 358 skips do not substitute for that physical proof.
The [recovery record](../handoffs/M8-native-recovery-evidence.md) preserves
seams, corrections, partial observations, and the artifact's actual scope.

The investigated binary is Codex 0.153.4, source
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`. Its controlled catalog and two
model-profile names select local metadata, not model calls. The
[authentication packet](../../designs/EXECUTOR_AUTHENTICATION.md) and
[combined startup record](../handoffs/M8-combined-startup-evidence.md) retain
the configuration and startup-origin limits. Their account-empty results
cannot prove account-dependent managed configuration, refreshed credentials,
real vendor egress, or a future binary's tool inventory.

A further source limit is already known: the pinned `account/read` response
contains email and plan type, not the stable account/workspace identifier the
proposed binding requires. Declared account-session types are not proof of an
available RPC. Before N1 starts, a credential-free interface/layout preflight
must name a supported metadata path and narrow writable store arrangement.
If none exists, implementation remains blocked pending a separately approved
candidate/requalification decision. Do not spend the implementation slices on
an assumed API, substitute email identity, or read tokens to manufacture it.
That preflight cannot replace N4's actual authenticated proof. Historical
fixture evidence stays pinned to 0.153.4; a different production candidate
repeats catalog, startup, placement, mediation and lifecycle qualification
from N2 onward, not only the account-sensitive N4 stage.

In particular, no existing proof establishes that a usable authenticated
harness can exclude every uncontrolled tool or startup input in the proposed
placement. If it cannot, that native mode is unavailable. Neither a longer
denylist nor the owner's wish to reuse a subscription resolves the failure.

## 3. Reuse and compatibility budget

Use the existing contracts at their existing layers:

| Responsibility | Reused boundary |
| --- | --- |
| Task and result | L0 `Executor`, `ExecutorProvider`, `ExecutorProfile`, `ExecutorOutcome` |
| Authority and identity | L0 effective grants, capability revision, launch identity, and lease context |
| Workspace | L0 `WorkspaceView` / write-workspace contracts; existing leased acquisition and capture |
| Native bytes and process lifetime | Existing substrate bounded duplex, Linux launcher and process supervisor |
| Durable resume and ownership | Existing journal, capability leases, `ControlPlane` and `RunHost` |
| Graph execution | Existing admitted manifest and walker, unchanged |
| Provider-specific protocol | Substrate adapter/driver, not SDK, MCP, or a new runtime service |

The planning inspection used `system.describe()` on an isolated fake-provider
assembly: SystemDescription 3, Graph/admission 1, complete grant-policy 1,
network `none`, and no registered components in that assembly. This confirms
the inspectable surface; it is not discovery of a native production profile.
The native recovery fixture implements `LeasedCapability`, not
`ExecutorProvider`. N2 must implement the latter rather than crediting it as
already present. Inspect again before each implementation slice.

ADR 0020 proposes native policy/launch schema 2 and SystemDescription 4 while
preserving the complete v1 identity law. Source-derived law revisions matter:
editing an old class can change every old launch revision even when its JSON
looks unchanged. N1 must prove old canonical bytes **and old derived identity**
against pre-change artifacts. There is no Graph, admission, manifest, or SQLite
schema change in this proposal. Any discovered necessity requires a reviewed
decision before implementation, not an incidental migration.

Do not add a completion API, token broker, provider-specific task node, general
tool service, account database, extra recovery pump, or second process owner.
Callbacks are bounded inputs to the leased task adapter. A provider addition
must reuse this shape; its protocol decoder, catalog, and conformance evidence
are allowed to differ.

The rev-1 native shell-tool proof changes explicitly for this mode: prove a
real native callback reaches the contained worker's permitted shell while the
harness's built-in shell remains unavailable. Do not require a forbidden
native tool to execute merely to satisfy the old placement's test wording.
Prove the selected harness's effective sandbox configuration and startup
helpers under the outer boundary; never assume nested namespaces work.
ADR 0020 records this narrow replacement. Other applicable rev-1 decoder,
stream, context, failure, grant, capture and lifecycle obligations remain.

## 4. Small implementation and qualification gates

Each numbered slice is independently reviewed. Its gate is a prerequisite, not
permission inferred from a green test. Account access remains unavailable
until N4, model calls remain unauthorized until N5, and production availability
requires every applicable gate. READ and WRITE qualify separately; a READ pass
never enables WRITE. A supported negative finding can finish an investigation
without finishing M8 or enabling a profile.

### N1 — versioned contracts, no native process

Implement only ADR 0020's versioned policy, launch identity and introspection
surface, with complete fake providers. Pin one authoritative grant predicate
per version, discriminated parsing, strict rejection of unknown versions,
native-mode admission refusal without a complete qualified identity, and
profile availability that distinguishes a fake from a live provider.

The compatibility gate reproduces old bytes and revisions from the baseline
validator/identity implementation in a separate worktree. Check in the v1
source-law literal and representative complete-v1 launch JSON/revision goldens;
current tests do not pin these independently. Expected values must not be
derived from the new source under test. Test retained and
new admissions, READ/WRITE profiles, `network=none`, opaque historical profiles,
unknown/unsupported model and effort refusal, model-inventory drift, strict
SystemDescription-3 reader refusal, and version-4 discovery. No adapter,
credential storage, new mount, egress, or provider request belongs in this PR.

### N2 — one credential-free Codex task adapter

Implement the first real task-shaped `ExecutorProvider` using the pinned
driver, existing launcher, bounded duplex, and contained workers. Keep the
native process account-empty with the existing local fake peer. Source/context
selection comes from admitted input; the native cwd is never the repository.
Callbacks are selected from the sealed catalog and validated before effects.
Retain exact call identities, limits, ordering, denial, cancellation, and
terminal-result accounting. Unknown protocol or usage is refused or reported
honestly, not repaired into success.

Prove one READ task and one WRITE task through the same component interface.
WRITE composes the already merged capture and contained gate path; it never
falls through to a host gate runner. Failed/cancelled work discards through the
existing lease law. For each posture, run the real Linux lifecycle matrix,
including old-owner loss, checkpoint restore without a new native call, fresh
uncheckpointed acquisition, malformed output, resource exhaustion, and bounded
partial-output handling. Replay must not invent another successful effect.

This slice proves the adapter against a fake provider, not subscription login
or real model quality. Record that distinction in `describe()` and the PR.

### N3 — physical account-store and egress boundaries, harmless fixtures

Implement ADR 0020's native-only narrow account mount, serial ownership,
vendor-route restriction and teardown. Use harmless account-shaped markers
and controlled upstreams; no real account or credential is involved. This is
a separate physical-boundary PR, not an incidental addition to N2.

Prove workers cannot reach the marker, route, controller state, or native home;
the native process cannot reach the workspace; and a supported refresh changes
only the permitted persistent store, never the read-only source. Exercise
symlinks, descendants, redirected destinations, DNS/TLS checks, long-lived
streams, acquisition cancellation, host death, account-lock handoff, and
operator-maintenance exclusion. The successor publishes/rechecks closure and
waits for the physical owner to drain through the retained guards, without
signalling a persisted PID, deleting or logging out the account. Stale owners
cannot mutate the next invocation or release its lock. Race the successor with
a paused old reaper; do not credit only a successor started after old-owner
quiescence. Operator maintenance must recheck zero acquisitions/processes
while holding the account lock, not rely on an earlier observation.

Prove that native/store symlink, unlink, rename and replacement cannot change
the trusted retained lock inode. The same physical store cannot acquire a
second lock through an alias; a contender remains excluded until the old
native descendants quiesce, including after caller or supervisor death.

Use the existing per-host Linux qualification. Prove the actual new mount and
egress placement; #64's networkless fixture cannot supply that credit. Test
generic `network=allow` truthfully and refuse native use with `network=none`.
Capture bounded evidence without marker/credential contents. A qualification
record binds configuration and authority, never a secret hash.

### N4 — authenticated startup and deployment conformance

This is a separate investigation requiring explicit operator authorization
for a selected Linux deployment, vendor-supported account mode, account
principal, login/maintenance procedure and bounded startup network access.
No account is placed in public Actions. Do not import a desktop authentication
cache or implement a substitute OAuth/token-refresh service.

First confirm the exact pinned binary supports the proposed narrow storage
layout and managed login lifecycle. Current documentation is orientation, not
proof about this release. Then repeat the complete startup-origin inventory
with the actual selected account: cloud/managed configuration, catalog,
requirements, plugins/apps, skills, hooks, environment and session state.
Show that each reachable authority input is excluded, fixed and identity-bound,
or explicitly enforced before use. No account-sensitive startup path inherits
account-empty credit.

Before the full account-authority check succeeds, require worker callbacks to
remain closed and no model-turn request or model-session traffic to occur.
Test this with an absent/mismatched account and startup failure. Where startup
and model traffic share a TLS destination, a firewall rule alone is no proof;
the qualified native protocol must enforce the phase boundary or refuse the
mode. Only the bounded initialization/principal/startup path is permitted.

Prove full account-authority mismatch refusal, including the same principal
with a different selected workspace/tenant, refresh and expired-login behavior,
quiescent operator maintenance, concurrent acquisitions, authenticated
account/startup egress,
teardown and restart through the existing lifecycle. Persist only nonsecret
qualification results. A re-login, changed principal, binary/configuration or
authority-policy change invalidates the affected qualification as ADR 0020
specifies. A refresh must not silently switch account authority. Inventory
configured model destinations, but mark actual model-session TLS and destination
behavior pending N5; an idle authenticated harness cannot prove a connection
that it only opens for a model turn.

If exclusion cannot be proved without disabling required vendor behavior, or
the deployment/account is not authorized, keep the mode unavailable and the
blocking issue explicit. Do not loosen grants or substitute API authentication
and report subscription conformance. Passing N4 does not authorize a model turn.

### N5 — separately authorized bounded live acceptance

Ask the owner for provider/account, model, permitted test data, request/token
budget and cost ceiling before making model calls. Keep a small fixed task,
one READ lane and a separately authorized WRITE/capture/gate lane. No loop
that repeats calls until the model happens to pass. A failure remains evidence.

Prove the real deployment returns contract-valid results through the same
task interface, respects timeout/cancellation, reports actual or unavailable
usage, and preserves the qualified boundary. Prove the actual model-session
TLS and destination behavior, then finalize the egress/account-mode conformance
revisions before production availability. N4-N5 use the same owned launcher,
driver, worker and lease boundaries in the explicitly authorized qualification
harness; they neither publish an unqualified provider nor insert fictitious
conformance evidence to pass production admission. No public availability
override is introduced. Re-run deterministic replay,
response-loss and mutation proofs with fakes; a costly smoke test is not their
replacement. This gate is required for the applicable live posture's M8
acceptance, not for opening the credential-free implementation PRs.

### N6 — independent Claude Code substitutability

Qualify Claude Code's actual protocol, supported authentication, storage,
startup inputs, egress and tool mediation independently. Do not infer them
from the Codex flags or assume its account store has the same layout. Apply
N2-N5's separated construction, boundary, authentication and live gates with
provider-specific proofs, splitting PRs at those boundaries.

Swap the executor binding of the same unchanged task component/graph and
demonstrate the existing grant, output, capture and replay contracts. The
adapter is available only for proved profiles. A different protocol is an
adapter concern; an inability to satisfy the boundary is unavailability.

### N7 — Pi and integrated M8 closure

Pi remains a required M8 adapter, not a deferred enhancement. Qualify its
selected provider mode independently through the same gates and repeat the
unchanged-component substitution across all three adapters. An API or local
backend still implements the same task boundary; it does not gain a completion
primitive, raw credential channel, ambient network, or undocumented authority.

The integrated lane covers fake-first lifecycle, real process restart,
capability-version binding, contained WRITE gates, simulated counterfactuals,
malformed/partial results, optional telemetry, and independent exact-head
review. Reconcile every rev-1 E-H obligation: changed sequencing or auth mode
must not delete portable decoder tests, cross-executor comparisons, failure
proofs, or honest availability. Close M8 only with evidence for its intended
outcome, not merely because all construction PRs merged.

[#47](https://github.com/sushiHex/constructicon/issues/47) remains an OpenRouter
enhancement. Reuse a qualified Pi provider path if it actually fits; otherwise
propose the smallest separate adapter. It is not an unconditional M8 dependency
or an excuse to add another orchestration abstraction now. Future cloud and
local models enter at this same modular boundary.

## 5. Proof accounting

Every claim names its exact source/configuration, environment and observer.
Archive metadata in a reviewed implementation record; CI artifacts may expire.
Do not archive account contents, vendor tokens, prompts containing secrets,
raw authentication traffic, or persistent session state.

| Evidence | What it can establish | What it cannot establish |
| --- | --- | --- |
| Source inspection and current vendor documentation | Candidate interface and test hypotheses | Execution or conformance of the selected binary/account |
| Portable fakes and transcripts | Typed laws, refusal order, decoding, command/replay behavior | Linux isolation or real vendor behavior |
| Native credential-free Actions lane | Exact startup/worker/process boundary against controlled inputs | Authenticated configuration, subscription eligibility, or deployment readiness |
| Harmless account/egress fixtures | New physical placement, ownership, revocation and path isolation | Actual login/refresh semantics or account-dependent startup |
| Explicitly authorized authenticated deployment | Exact account/startup/provider arrangement and lifecycle | Unrelated accounts, releases, routes or successful model work |
| Bounded live smoke | The permitted real task and reported usage/result | Exhaustive mediation, deterministic replay or unlimited future authority |

Each implementation PR requires `uv run verify`, applicable native lanes,
independent review of the exact head, and regression/mutation evidence for
its new law. Source review and artifact review are distinct when native
observations carry the claim. Review fixes require confirming the resulting
head, not relying on approval of its parent. Docs-only CI here proves no N1-N7
behavior; all these rows are future gates unless section 2 says otherwise.

## 6. Proposed issue transition, not live backlog state

GitHub Issues owns status, ownership and native dependencies under
[WORK_TRACKING](../../WORK_TRACKING.md). The following is a one-time proposed
migration after an owner accepts ADR 0020 and this plan. Do not apply it merely
because this document merges. Re-read issues and linked PRs first; preserve
history and any intervening work. This table is not a second TODO.

| Issue | Existing role | Proposed disposition after acceptance |
| --- | --- | --- |
| [#38](https://github.com/sushiHex/constructicon/issues/38) | Authentication decision | Record the explicit decision and its scope; close only when that decision is actually made |
| [#39](https://github.com/sushiHex/constructicon/issues/39) | Deployed gateway conformance | Retain as the independent gateway option with its real external prerequisite; remove it as an unconditional blocker of native adapters, not close it as delivered |
| [#41](https://github.com/sushiHex/constructicon/issues/41) | Codex as second adapter | Re-scope to first native Codex qualification, N1-N5; depend on the accepted #38 outcome rather than Claude; split the independently assignable slices into native sub-issues before work |
| [#40](https://github.com/sushiHex/constructicon/issues/40) | Claude-first adapter | Re-scope to independent second-adapter qualification N6, depending on completed applicable #41 proof, not gateway deployment |
| [#42](https://github.com/sushiHex/constructicon/issues/42) | Pi and integrated closeout | Retain Pi and whole-M8 acceptance N7, after the two qualified adapters; do not close for a fake-only integration |

Under #41, N1 precedes N2, N2 precedes N3, N3 precedes N4, and N4 precedes N5.
Encode unconditional ordering as native issue dependencies when creating the
sub-issues. An unavailable deployment is a real external prerequisite, not a
new scheduler, placeholder implementation, or automatic `ready` label.
The gateway option requires its own owner selection and conformance; native
acceptance does not approve gateway provisioning. Do not move #43-#47 or M9
into this change except to preserve the conditional #47 relationship above.

## 7. Decision requested

The owner is deciding whether to accept ADR 0020's narrow native account
authority, the explicit persistence exception for its vendor-owned store,
versioned policy/identity/introspection changes, this Codex-first sequence,
and the required but separately authorized live-acceptance gate. In this
successor plan a credential-free construction pass alone cannot close M8's
selected live profiles; that is an explicit strengthening of acceptance, not
retroactive credit claimed from rev 1.
The owner is not certifying a vendor's account terms, approving arbitrary
credential handling, choosing a deployed account, or granting model-call spend.

An approval must be recorded explicitly in the ADR and issue. Then freeze this
plan and retain rev 1 as historical authority for what it governed. Redlines
before a decision amend this review draft; a post-approval scope change needs
a successor. Keep proposed architecture out of current-truth documentation
until implementation and its applicable qualification actually land.
