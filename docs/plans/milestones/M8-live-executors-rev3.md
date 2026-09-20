# M8 rev 3: operator-bound subscription executors

Status: **accepted for implementation** on 2026-09-13, with the acceptance of
ADR 0021. N1 (#74) and N2's first slice (#75) are implemented and merged
against it.

Decision: [#38](https://github.com/sushiHex/constructicon/issues/38).
Authority: accepted [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md).
Baseline: `d2b8f9421e3b3a5d9edeec42064fa3b42100fa52`.

This is the successor to [rev 2](M8-live-executors-rev2.md), whose bytes and
unestablished vendor-identity requirement remain intact. Accepted
[ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md),
[ADR 0019](../../adr/0019-hosted-linux-runners-are-requalified-not-image-pinned.md)
and [rev 1](M8-live-executors-rev1.md) still govern, and no old test obtains a
new meaning retroactively.

**Acceptance is of this plan, not of anything it describes as separate.** It
does not authorize a vendor account, a credential, a paid call, a deployment,
or live use. Each of those remains its own decision, as the sequence below and
ADR 0021 state.

## Outcome and reuse

Claude Code and Codex execute graph tasks using their vendor-managed
subscriptions. External authors/reviewers and separately billed APIs do not
fulfill this outcome. Codex goes first because its bounded fixture has been
measured; Claude must independently qualify the same task contract. Pi remains
part of integrated M8, and APIs/local harnesses remain modular options under
[ADR 0005](../../adr/0005-executor-seam.md), not required subscription fallbacks.

ADR 0021 owns the law once: operator-store custody instead of vendor-principal
attestation; explicit unverified account/scope continuity; unchanged tool,
startup, network, process and effect enforcement. This plan owns only gates
and evidence. Reuse rev 2's section 3 contract map and the merged A-D foundations:
`ExecutorProvider`, task/outcome, effective grants, workspace/capture, contained
gates, bounded duplex, supervisor, lease/journal and `RunHost`. Inspect
`system.describe()` and actual contracts before each implementation slice.
No new completion layer, workflow language, account service or scheduler.

The credential-free #62/#64 evidence in rev 2 section 2 remains useful only
at its original account-empty fixture boundary. The
[0.153.4 preflight](../handoffs/M8-native-account-interface-preflight.md)
remains a negative result for the stronger profile, not a failed subscription
login or a positive operator-mode proof. Current vendor docs do not select a
production binary. The bounded Codex 0.154.0 and Claude source screens remain
linked in #38; there is no automatic candidate-upgrade loop.

## Gated implementation sequence

Acceptance of this ADR and plan permits credential-free construction only.
Every implementation PR still requires its applicable exact-head verification,
native/mutation evidence and independent review. A passing baseline does not
qualify a provider. READ and WRITE are separate profiles; N4 and N5 below each
need separate explicit operator authorization, for each provider.

### N1 — strict operator-mode contracts

Implement ADR 0021's v3 records, v1/v3 parsing, single grant predicate,
SystemDescription 4 and complete fake providers. Do not implement ADR 0020's
principal-attested v2 or add a selector that silently downgrades into v3.
Preserve v1 bytes and source-law revision with goldens reproduced from
`d2b8f94` in an independent worktree. The existing profile remains unversioned;
dispatch occurs at the new outer union, never by adding a legacy field.
Reject explicit version 2 and unknown
versions; failed v3 parses never fall through to historical permissive parsing.
Test retained opaque/complete profiles, exact model/effort/tool inventory,
unsupported narrowing, `network=none`, strict description-3 readers and the
published unverified assurance. Two fixtures with different vendor principals
but the same operator binding must not manufacture a claim of different or
equal verified accounts. A new maintenance generation changes the revision;
ordinary simulated refresh does not. Overages forbidden versus explicitly
authorized are distinct sealed profiles, not an automatic fallback. Private
fixed-actor ingress must be an availability prerequisite, not caller input.
No native process or provider connection.

### N2 — credential-free Codex task adapter

Name the exact binary/source, callable non-secret subscription-mode interface,
narrow vendor layout, bounded startup protocol and fixed catalog in this PR.
Stable vendor-principal metadata is not its prerequisite. The mode interface
and startup must actually support a no-model-request initialization phase;
do not pretend an automatic inference command supplies that boundary. If a
candidate differs from the retained fixture, repeat all affected catalog,
startup, mediation and lifecycle proofs rather than inherit version credit.

Implement the existing task-shaped provider over bounded duplex and the
owned launcher, using the account-empty local fake peer. Prove READ and
WRITE through unchanged components, with WRITE using merged capture/gates.
Retain rev 2 N2's call accounting, finite bounds, malformed/partial outcomes,
cancellation, checkpoint/no-new-call and fresh-acquisition recovery matrix.
A qualification-only fake route never advertises subscription availability.
No account, credential parsing, OAuth helper or real vendor traffic.

### N3 — physical binding and egress, harmless fixtures

Implement the dedicated native-only store, retained lock, binding-generation
checks and acquisition-scoped egress from ADR 0021. Retain rev 2 N3's physical
native/worker separation, owner-death/old-reaper races, closure, alias and
lock handoff, DNS/TLS/destination denial and maintenance exclusion proofs.
Prove descriptor publication cannot overwrite an existing key/generation;
after a real restart, a same-path replacement root still refuses under the old
descriptor. Exercise crashes before/after durable withdrawal, descriptor
publication and activation: no store mutation before withdrawal, no stale
provider accepting a retired selection, and no activation before fresh
qualification. Store presence or an old qualification record is insufficient.
Simulate vendor refresh with harmless markers: permit its qualified file
replacement but refuse store-root/lock substitution and an alias acquiring a
second lock. Both initial and terminal binding checks must be load-bearing.
Intentional maintenance produces a new generation; an old manifest cannot
materialize it. Cleanup must leave persistent vendor state alone.

Add controlled account/configuration changes before and during a turn. They
must never widen callbacks, startup helpers, destinations, mounts or writes,
even without a principal-change signal. Reject subscription-to-API mode
changes without fallback. Exercise pre-model refusal with no model request
and closed callbacks; a shared TLS destination alone is not phase proof.
Prove the overage policy's limit behavior independently of auth-mode labels;
unknown enforcement cannot qualify an overages-forbidden profile.
These fixtures prove physical and protocol laws, not vendor refresh semantics
or real authentication. Use qualified credential-free Linux Actions; archive
no credential contents, secret hashes or auth traffic.

### N4 — private authenticated startup

First obtain explicit operator authorization for the selected qualified Linux
deployment, vendor mode, dedicated binding, permitted startup/network activity
and evidence retention. This proposal selects none. No account goes into
public Actions; no desktop cache is imported. Login is performed directly
through the unmodified vendor client under the maintenance/lock procedure.

Prove actual narrow storage and refresh, subscription-mode observation,
no-model startup phase, physical custody, cloud/managed inputs, effective
catalog, egress, expiry, quiescent maintenance, generation invalidation and
restart. Every authority input is excluded, fixed and revision-bound, or
enforced before use, including changes during refresh. Missing principal or
workspace identity is explicitly unverified, never a passed continuity test.
Keep rev 2 N4's authenticated positive controls except its full principal/scope
comparison: replace that with binding/layout/mode refusal, and independently
prove configuration/tool/egress confinement regardless of account identity.
An unsafe or unavailable positive control leaves the profile unqualified.

Do not infer zero spend from a mode flag or account tier. Record only bounded,
non-secret observations; vendor identity is not added to public telemetry.
N4 does not authorize inference. Actual model-session TLS/egress remains
pending N5 even when configured destinations are known.

### N5 — separately authorized subscription task acceptance

Obtain explicit authorization for the selected binding/provider, model,
permitted task data, fixed request/token budget, vendor overage policy and
cost ceiling before model calls. If a requested hard spending bound cannot
be enforced under that arrangement, stop for a different operator decision;
do not promise one from a local token limit. No paid-API fallback or repeated
smokes until a model succeeds.

Run one bounded READ lane and a separately authorized WRITE/capture/gate lane
through the same owned boundaries. Prove real subscription-mode execution,
model-session TLS/destinations, bounded results and timeout/cancellation;
complete only the observed profile's conformance. Reuse deterministic fakes
for response loss/replay and mutation proof; model quality is not a substitute.
Qualification uses the real launcher/driver/worker and leases without
publishing an unqualified production provider or inventing conformance hashes.
Subscription limits, unavailable telemetry and partial output remain truthful.

### N6 — independent Claude Code qualification

Apply N2-N5 independently to unmodified Claude Code, with its own pinned
protocol, supported direct login, mode observation, layout, startup, tool
mediation and egress evidence. Do not infer Claude's store or mode API from
Codex, or treat Agent SDK billing guidance as product-login permission.
Protocol differences stay in the adapter. Repeat unchanged graph/component
substitution, grants, outputs, capture, disposal, replay and each live posture.
Claude is a required subscription deliverable, not an external-reviewer
substitute. Its credential-free interface review may run alongside Codex work;
credentials/live calls remain separately gated and never inherit Codex credit.

### N7 — Pi and integrated closure

Retain rev 2 N7 and applicable rev-1 E-H proofs: Pi is still required, future
API/local models fit the same seam, and OpenRouter #47 remains a separate
enhancement. No API spend or gateway deployment is selected here. A Pi mode
needs its own explicit provider/authentication choice and conformance.

Integrated acceptance requires both subscription adapters plus Pi, fake-first
and real-process restart, sealed revisions, contained WRITE/gates, simulated
counterfactuals, malformed/partial output, truthful telemetry and independent
exact-head review. Missing deployment, subscription proof or Pi qualification
keeps the corresponding outcome open. M8-first remains; M9 is not advanced.

## Proof and tracking discipline

Rev 2 section 5's evidence separation continues, except that **no evidence in
this profile attests vendor principal/scope continuity**, including a live
smoke. Source and artifact review are separate where physical claims rely on
downloaded evidence. New assertion mutants must catch binding/generation
substitution, lock/refresh confusion, mode fallback, premature model start,
startup/config widening, false identity telemetry and compatibility fallback.
These are future tests, not mutations already executed in this docs PR.

GitHub Issues remains the backlog. After explicit acceptance of ADR 0021 and
this plan, re-read current work and apply rev 2 section 6's proposed transition
with **ADR 0021/v3** as authority: #38 records the scoped choice, #41 owns
Codex N1-N5, #40 owns independent Claude N6, #42 retains Pi/integrated N7,
and #39 stays the unselected, separately billed gateway option rather than an
unconditional native blocker. Create bounded sub-issues/dependencies before
implementation; do not apply that migration merely because this draft merges.
No issue closes as a result of authoring this proposal.

The decision requested is ADR 0021's narrower account assurance and sequence,
not approval of credentials, model spend, vendor terms or a Linux target.
Keep approved plans and rejected/earlier proposals byte-preserved. A review
redline may amend this draft before decision; after approval use a successor.
