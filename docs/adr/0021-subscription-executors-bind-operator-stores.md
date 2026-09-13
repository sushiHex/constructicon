# 0021 — Subscription executors bind operator stores

**Status:** accepted (M8), 2026-09-13 — supersedes ADR 0018 only for the
explicit v3 profile; credential-free N1 construction authorized. Credentials,
deployment, authenticated startup, model calls and live profiles remain
separately unauthorized.

## Decision record

On 2026-09-13 the owner accepted this ADR and M8 rev 3 as written, at
reviewed head `e228ef8535bceb316bdbfd3c309066befa9f67f0` (merged as
`9e55364f8cb8261eb50678936fd9170c00c83cf1` in PR #72), in the
[decision record on issue #38](https://github.com/sushiHex/constructicon/issues/38#issuecomment-5651362966).
The acceptance covers the operator-bound scope, the residual
wrong-account/data-context risk with vendor identity explicitly unverified,
the v3 compatibility boundary and the rev-3 sequence. It authorizes
credential-free N1 construction only; N4 and N5 each need separate explicit
operator authorization per provider, and the private qualified Linux
deployment is a separate operator decision. ADR 0020's proposed
description-4 allocation is retired in favour of this one; its text is
unchanged and it remains proposed.

The owner requires Claude Code and Codex subscription use **inside the graph**.
External authors/reviewers and separately billed APIs do not satisfy that
outcome. On 2026-09-12 the owner authorized preparation and independent review
of this narrower design, with vendor account/workspace identity explicitly
unverified. That authorized this proposal; the acceptance above is the
separate decision. Credentials, account inspection, model calls, provisioning
and deployment remain separately unauthorized.

[Issue #38](https://github.com/sushiHex/constructicon/issues/38) owned the
decision. [M8 rev 3](../plans/milestones/M8-live-executors-rev3.md) is the
accepted implementation baseline. Accepted [ADR 0018](0018-live-executors-are-leased-contained-processes.md)
and [ADR 0019](0019-hosted-linux-runners-are-requalified-not-image-pinned.md)
continue to govern outside the explicit v3 profile; this ADR is the successor
decision for that profile. Proposed
[ADR 0020](0020-native-harnesses-mediate-contained-tools.md) and M8 rev 2
retain their bytes and stronger, currently unestablished identity guarantee;
this document does not silently amend them or implement their profile.

## Problem and scope

[ADR 0005](0005-executor-seam.md) already accommodates subscription CLIs and
API-backed harnesses through one task-shaped executor. The missing abstraction
is not an authentication broker or a completion provider. ADR 0020 additionally
requires a supported fresh vendor principal and every selected authority scope,
with continuity throughout the turn. The
[pinned preflight](../plans/handoffs/M8-native-account-interface-preflight.md)
did not establish that interface. An opaque store is not a substitute proof.

This proposal chooses a different capability subject: **one operator-owned
physical login-store binding**, not a verified vendor principal. It is for
one trusted operator administering the deployment and its data. It does not
authorize a multi-tenant service, account-based access control, delegated
subscription pooling, credential resale, or account/tenant-specific audit.
Constructicon actors still come from its transports; a vendor login never
authenticates a control-plane actor or authorizes a graph effect.

Initial assembly is private and operator-controlled, with trusted local
transports/actors inside that one administration boundary. It must not expose
this capability through a shared HTTP service, arbitrary remote callers or
multiple operating-system users sharing a store. Trusted assembly fixes that
deployment scope before publishing the capability; a mutex or caller-supplied
"single operator" flag cannot authorize it. Multi-user hosting needs a separate
decision, not reuse of this assurance label. The provisioning operator is the
vendor end user; internal agents act only for that operator. A deployment that
serves another end user through the binding, or cannot enforce this private
fixed-actor ingress with the existing transport/assembly contracts, must refuse
availability. It cannot add a caller-authored operator identity to cure that
failure. New ingress authority would need a separate decision.

The tradeoff is real. Constructicon cannot guarantee which vendor account,
organization or workspace receives task data or usage, or detect every change
during refresh. An operator mistake or an undetected vendor-side switch can
send data to an unintended account context. Neither equal pre/post metadata
nor an exclusive local lock establishes vendor identity continuity. Deployments
requiring that guarantee must refuse this profile, not interpret its opaque
binding as an account attestation. This residual risk was part of the decision
requested and was accepted by the owner on 2026-09-13; acceptance is not
evidence that the risk is absent.

## Decision

### One task, two zones, one lifecycle

Keep `Executor`, `ExecutorProvider`, `TaskSpec`, `ExecutorOutcome`,
`WorkspaceView`, effective grants, the existing lease/acquisition row, bounded
duplex launcher, supervisor, journal, walker and `RunHost`. The adapter owns
one task acquisition, not a persistent agent service or another scheduler.

- The native zone runs a pinned **unmodified** vendor client. Only its qualified
  authentication, provider protocol, fixed tool router and store custody are
  trusted. It receives the dedicated narrow vendor store, disposable other
  state, bounded callback endpoint and restricted vendor egress. It has no
  workspace, authority Git, journal, worker scratch, host home, sibling state,
  inherited service descriptors, or effect adapter.
- The worker zone receives only its admitted READ or WRITE workspace and tools.
  It has no vendor store, native home, provider connection, DNS or network.
  Trusted adapter code launches it through the existing supervisor. READ is
  physically read-only; WRITE still uses contained capture and contained gates.

Native model outputs and all callback arguments are untrusted. Every
model-selectable operation must be an admitted callback or mechanically
unreachable. This includes native shell, patch, file/image readers, code mode,
MCP, apps, plugins, skills, hooks, subagents, dynamic tools, and auth/config
operations. Startup helpers require their own qualified bounded authority;
a denylist or claimed empty inventory alone proves neither property.

The callback validator checks the known turn/call identity, exact catalog,
bounded schema, sealed grant, bound worker and one terminal response. Unknown,
duplicate, late, cross-invocation and malformed calls refuse. Its private
endpoint proves invocation membership, not CLI authorship: no stronger
authority is granted based on a sender's alleged identity. The graph/model
cannot select a host path, store, executable, model endpoint, or wider grant.
Worker-local operands remain bounded task data, not authority locators.

The existing acquisition law remains: acquire inertly, record/enroll, then
materialize. One physical owner holds guards through all descendants; close
revokes callbacks and connections, kills/joins owned trees and disposes scratch.
Successor recovery publishes/rechecks closure and waits for physical quiescence,
never signals a persisted PID or resurrects a native conversation. A valid
checkpoint may avoid a new call; uncheckpointed computation may repeat. No
exactly-once model computation or charge is claimed. No failure in transport,
worker, capture, gates or cleanup may become success because the CLI said so.

### The operator binding is an assembly fact

Trusted assembly selects one privately provisioned binding descriptor: an
opaque non-secret key, a non-reused maintenance generation, an opaque store
instance ID, and the physical store/lock recipe. The descriptor lives in a
trusted root inaccessible to native/worker processes and read-only to normal
execution. Its qualified filesystem identity pins the physical store root and
retained lock, not a credential-file inode. These are future provisioning
inputs to existing assembly, not state the current code already supports.
None of the identifiers is a bearer credential or a vendor identity.

The binding digest uses the ordinary canonical identity law:

```text
digest("native-operator-binding", 1, {
    "key": operator_key,
    "generation": maintenance_generation,
    "store_instance": store_instance_id
})
```

The instance ID names that descriptor's immutable physical-root relationship.
It is never reused for a replacement root; descriptor publication must refuse
an existing key/generation rather than overwrite its mapping. Reopening an
existing generation compares the actual root/lock with that retained descriptor
before use. A locator plus an assertion that the operator did not change it is
insufficient. Root identity/mount checks across reboot must be qualified; if
they cannot re-establish the relation, availability stops for maintenance.
The descriptor's mapping and lock association are protected by the provisioning
boundary; the digest alone does not authenticate an arbitrarily rewritten
descriptor. Malicious modification of this trusted root is outside this mode's
threat model, like replacement of trusted adapter code.

Only the digest enters public identity, not raw keys, physical identifiers,
paths, account metadata or secrets. It proves which provisioned slot was bound,
not successful authentication or unchanged vendor principal. One immutable
descriptor per generation is operator configuration, not a runtime account
database or service. No journal record, recovery owner or generation API is
added; an implementation needing new durable authority must stop for review.

Assembly must refuse one physical store assigned multiple bindings/lock
identities, and a binding remapped to another store without maintenance.
Under the exclusive lock, before materialization and before accepting a result,
the adapter checks the selected binding generation, qualified layout and
physical mount identity against its sealed revision. It does not read or hash
credential contents. The vendor's qualified refresh may replace its own files
within that same narrow layout; a credential-file inode or content hash is not
the store's identity. Symlink/rename/alias checks and the trusted parent/mount
recipe must prevent substitution of the bound store or lock by a descendant.
Tests must prove this distinction rather than freezing normal refresh writes.

Concurrent acquisitions sharing a store are forbidden initially. Materialization
waits cancellably on the existing OS-backed exclusive-lock discipline while
observing run control. One stable retained lock inode lives outside the writable
vendor store and is inaccessible to native/worker processes. The supervisor
inherits its open file description until all native processes and refresh
activity quiesce; caller death, rename or a second alias cannot release it early.
This serializes local custody, not vendor-side account activity.

Operator login, logout, repair, store replacement or intentional account switch
requires stopping availability, requesting normal quiescence, taking the same
lock, and re-proving zero owned acquisitions/processes while holding it.
Every such maintenance assigns a new non-reused generation and invalidates the
affected startup/account-mode conformance, even for the same intended account.
Refresh through the qualified vendor path does not mint a generation. Old
manifests cannot silently acquire the new binding revision; recovery disposes
their existing acquisitions but never upgrades them. Under the same lock,
maintenance first durably withdraws the old generation from active assembly
configuration **before any store mutation**, then publishes a fresh immutable
descriptor. Only completed qualification permits atomic activation of the new
selection. An interrupted withdrawal must prevent store mutation; a crash
after withdrawal leaves the binding disabled. Startup and per-turn binding
checks must compare with this active selection, not accept an old descriptor
merely because its file and prior conformance still exist. This is one
operator-published assembly configuration, not a runtime account service;
normal execution cannot rewrite it. Its atomicity/durability and old-provider
refusal need physical tests. Close/reconcile neither
logs out nor deletes, copies, rolls back or repairs the persistent store.

### Vendor-owned subscription authentication, not a credential relay

The operator signs in directly through the selected vendor's supported flow.
The unmodified client owns credential creation, storage, refresh, provider TLS
and logout. Constructicon never implements an OAuth flow, supplies external
tokens, parses a credential file, copies a desktop login, exports a store, or
turns subscription credentials into an API endpoint. Only a proven narrow
vendor layout is eligible; mounting the whole home or copying a subset is not
a fallback. Vendor-defined refresh writes to this store are the sole persistent
native-write exception, including in a READ task; READ workspace is unchanged.

For Codex the candidate interface is
[managed ChatGPT authentication](https://learn.chatgpt.com/docs/app-server),
not experimental externally supplied tokens. For Claude Code it is direct
end-user login into the unmodified binary, not a custom Claude.ai login or
credential-intermediation service. Anthropic's
[current billing notice](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
states that the proposed separate SDK-credit change is paused;
[its integration restrictions](https://code.claude.com/docs/en/legal-and-compliance)
remain distinct from that billing statement. These public documents orient
the design; they do not qualify a pinned client, deployment or user's terms.

Subscription mode is explicit. The adapter excludes alternate API keys,
credential helpers, provider overrides and automatic paid-API fallback through
its fixed environment/configuration and qualified startup. A supported,
non-secret authentication-mode observation must establish subscription mode
freshly for the executing session before each model turn and before accepting
its result; cached initialization metadata alone is insufficient. Absence,
an unknown mode,
expiry or an observed mode change refuses availability/result acceptance; it
does not trigger login, switch provider or parse secrets. Qualification must
prove that vendor refresh cannot silently select API/cloud authentication
mid-turn, independently of the expressly unverified principal/scope tuple.
If the pinned interface cannot prove mode selection, that adapter remains
unavailable. A model's claim that it used a subscription proves nothing.

Subscription mode does not mean zero cost or unlimited use: vendor overage,
credit and subscription-limit policy remains with the operator/vendor. Surface
emitted rate-limit/overage facts; otherwise report `None`. Do not invent a
spend guarantee. The sealed profile states `subscription_overage="forbidden"`
or `"operator_authorized"`; absent operator approval selects only `forbidden`.
The first requires proved mechanical refusal at the included limit; if the
vendor arrangement cannot supply that proof, the profile is unavailable.
The second requires explicit operator approval of subscription-linked overage
and its bounds before qualification/use, not approval inferred from this ADR.
They are different capability revisions, never an automatic runtime switch.
Unknown overage control is not permission to incur it. Expiry, limits and refusal return
bounded truthful outcomes; there is no retry-until-success or automatic
billing-mode switch.

### Identity uncertainty cannot widen startup, tools or network

Before the first model request, keep callbacks closed while the bounded
initialization verifies binding, subscription mode, effective configuration
and catalog against the launch identity. No unqualified account-dependent
startup code may execute before that gate: permitted helpers are pinned,
excluded from workspace/effect authority and independently qualified. Failure
tears down without a model turn. Where initialization and inference share TLS
destinations, a firewall alone does not prove this phase boundary; the pinned
protocol/startup implementation must enforce it.

Account/cloud-managed settings are untrusted authority inputs, not harmless
because vendor principal is unknown. Every reachable input must be excluded,
fixed and revision-bound, or mechanically constrained at its point of use.
Qualification must demonstrate that a vendor-side account/scope or configuration
change cannot enable additional native tools, helpers, destinations, workspace
access or persistent writes. A changed catalog cannot be accepted by learning
its new hash. Post-turn comparison alone cannot undo an earlier authority
widening. If enforcement relies on discovering every account switch, this
profile cannot qualify; use the stronger proposal or remain unavailable.

Only the native zone may use acquisition-scoped `native_vendor_session_only`
egress. Preserve ADR 0020's destination-restriction design: fixed qualified
vendor destinations, bounded resolver/TLS assumptions, denial of auxiliary
traffic, no arbitrary proxy/DNS/URL or host network. The vendor client owns TLS;
the enforcing layer neither terminates nor translates model traffic nor injects
credentials. Redirects, ECH, dynamic endpoints and startup must be proved within
the declared restriction or refused, never repaired with general egress.
`network="none"` still excludes model networking, so this profile requires
`network="allow"`; workers stay networkless. Allocation follows the durable
lease, teardown revokes established streams, and a connection cannot outlive
the acquisition deadline. Refresh does not renew that deadline.

## Public contract and compatibility

Publish exactly one new operator-bound mode, not a runtime selector between
weaker and stronger account assurances. ADR 0020's principal-attested mode is
not implemented by this work and remains unavailable. Reserve its proposed
schema 2; use schema **3** for the new native operator policy/profile/launch.
This avoids giving incompatible proposals the same serialized meaning.

The proposed L0 records are strict (`extra="forbid"`, frozen):

- `NativeOperatorGrantPolicyV3`: schema 3; finite normalized tool sets, nonempty
  explicit model inventory, exact efforts through the profile, environment
  allowlist, workspace requirement, `network_modes=("allow",)`,
  `network_access="native_vendor_session_only"`, and
  `tool_path="mediated_callbacks_only"`.
- `NativeOperatorIsolationProfileV3`: schema 3; the existing physical posture,
  process ownership and environment/network facts, plus no native workspace,
  no worker network, narrow writable vendor store and separate zones.
- `NativeOperatorExecutorProfileV3`: schema 3; name, one posture, structured
  output fact, finite efforts, the policy and isolation records,
  `authentication="vendor_managed_subscription"`, and
  `account_assurance="operator_bound_vendor_identity_unverified"`, plus the
  explicit `subscription_overage` policy above.
- `NativeEgressIdentityV1`: the fixed enforcement-build, destination, resolver,
  TLS-assumption, configuration and physical-conformance digests described in
  ADR 0020; no endpoint locator or account fact.
- `NativeOperatorStoreIdentityV1`: schema 1; the operator-binding digest and
  digests of layout, mount/lock law, subscription-mode adapter and store
  conformance. No principal-query digest, account tuple or secret hash.
- `NativeOperatorLaunchIdentityV3`: schema 3; the complete executable, runtime,
  adapter/decoder, isolation/configuration/limits, callback protocol/catalog,
  profile, egress/store identities, authenticated-startup and subscription-mode
  conformance, and source-derived v3 law revision. Its domain is
  `executor-native-operator-launch`, version 3, distinct from both older modes.

One pure grant predicate serves admission and adapter validation. No profile
name, boolean bypass or inferred field may stand in for these facts. Complete
fake providers exercise the same contract without publishing production
availability. `describe()` exposes the assurance literal and unavailable
reasons, never vendor identity inferred from the binding. Assemblies requiring
verified vendor identity must not offer this capability to graphs.

Preserve existing gateway v1 canonical bytes, source-law revision and semantics,
including historical opaque profiles. Reproduce v1 goldens from baseline
`d2b8f9421e3b3a5d9edeec42064fa3b42100fa52` before editing a source-derived
closure. Do not modify that closure to implement v3. Boundary decoders dispatch
outside it. The future outer profile union is
`ExecutorProfile | NativeOperatorExecutorProfileV3`, explicitly decoded by the
raw object's `schema_version`: absence selects the existing **unversioned**
`ExecutorProfile`, exact 3 selects the strict native record, and every other
explicit value refuses. Do not add a version field or wrapper to historical
profile serialization. The launch-identity union similarly dispatches its
existing explicit schema 1 versus new schema 3; schema 2 and unknown values
refuse. Never fall back to permissive parsing after a failed native parse or
accept mixed profile/policy/launch versions. No principal-attested branch is
implemented. N1 must prove retained decode and re-encoded bytes independently.

Publish `SystemDescription` 4 and digest domain 4, so strict version-3 readers
refuse rather than discard the new assurance. Graph/admission, manifest and
SQLite schemas stay unchanged: existing capability revisions seal this mode.
Any contrary implementation discovery needs a successor decision. Billed APIs,
Pi, OpenRouter and future local/cloud harnesses remain supported extensions of
the existing task-shaped seam, not subscription fallbacks or a closed provider
enum. No API deployment or enhancement is delivered by this ADR.

There is no native v2 or description-4 writer in the current code. These are
proposed version allocations, not a v2-to-v3 data migration. Description 4
can contain the v3-discriminated profile; a reader written for ADR 0020's
proposed strict v2 profile must refuse it, not relabel its assurance.
Acceptance retires ADR 0020's proposed description-4 allocation in favor
of this one, without changing its historical text. Any later principal-attested
profile must obtain a new native/description version in its own decision.

## Exact authority delta and acceptance gates

As accepted, this ADR supersedes ADR 0018 **only for the explicit v3 profile**:
gateway-only initial authentication becomes vendor-managed subscription mode;
whole-CLI credential exclusion becomes native-only narrow custody; single-zone
placement becomes native/worker separation; provider-route egress becomes
native vendor-session egress; and the built-in native shell exercise becomes a
real mediated callback exercising the contained worker shell. The vendor-store
refresh WRITE exception is explicit. Gateway v1 is not reinterpreted.

Relative to proposed ADR 0020, store binding replaces principal binding, and
binding/layout/subscription-mode checks replace complete principal/scope
queries. Through-turn **vendor identity** continuity is not claimed; through-turn
tool, configuration, egress and billing-auth-mode enforcement is still required.
The stronger profile is neither accepted nor made available by this alternative.
All thirteen invariants, physical isolation, deterministic effects, grants,
source-derived identity, maintenance fencing, cleanup/recovery and proof honesty
remain unchanged. This is weaker account assurance, not a claim of equivalent
protection under different words.

After explicit ADR/plan acceptance, the rev-3 sequence is: credential-free
contracts, Codex task adapter, physical store/egress qualification, separately
authorized private authenticated startup, separately authorized bounded model
smoke, independent Claude Code qualification, and Pi/integrated M8 closure.
Missing vendor principal metadata alone no longer blocks the operator-mode
contract slice; missing mediation, mode, store, egress or lifecycle proof still
blocks the affected adapter. No fake pass or changed label supplies that proof.

GitHub Actions remains credential-free under ADR 0019. No account is loaded
there; OpenAI's [account-authenticated CI recipe](https://learn.chatgpt.com/docs/non-interactive-mode)
explicitly excludes public/open-source repositories. A private qualified Linux
deployment remains an unselected operator prerequisite. This decision neither
enables Hyper-V nor promises native Windows containment or remote dispatch.
Source/interface screens, authenticated startup and real model use remain
distinct gates; each provider and READ/WRITE posture qualifies independently.

## Decision requested and made

The decision requested was to accept or redline the operator-bound scope,
residual wrong-account/data-context risk, explicit v3 compatibility boundary,
and rev-3 sequence, in an acceptance record naming this ADR and the reviewed
plan/head. Merging the review draft did not supply it, and until that record
existed no runtime change, account, deployment or live executor was authorized
by this proposal. The record was made on 2026-09-13 (see the decision record
above): accepted as written.
