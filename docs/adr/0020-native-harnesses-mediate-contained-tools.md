# 0020 — Native harnesses mediate contained tools

Status: proposed successor to ADR 0018; owner decision required.

## Decision record

This proposal is the native-account decision artifact for
[issue #38](https://github.com/sushiHex/constructicon/issues/38). While proposed,
it authorizes no implementation, login, credential access, provider request,
deployment, or paid use. Acceptance requires a future owner decision.

Credential-free Codex [PR #62](https://github.com/sushiHex/constructicon/pull/62)
and [PR #64](https://github.com/sushiHex/constructicon/pull/64) qualify one
pinned, account-empty fixture: separate native harness and contained worker,
bounded callbacks, and recovery through the existing lease, journal, `RunHost`,
and supervisor. It does not qualify credentials, authenticated/cloud startup,
network policy, entitlement, provider terms, or a production adapter. Its
private endpoint proves invocation membership, not CLI authorship.

If accepted, this ADR selects Codex as the first native account-mode adapter
because that is the measured interface, not because Codex defines a common
provider protocol. Claude and Pi must qualify independently. OpenRouter may be
a later Pi configuration if Pi earns that reuse; it is not added to M8 by this
decision. Standard hosted Actions remains a credential-free evidence host.

## Context

[ADR 0005](0005-executor-seam.md) requires a task-shaped executor and forbids a
completion-provider abstraction. [ADR 0008](0008-isolation-admission.md)
requires physical enforcement and admission refusal. Accepted
[ADR 0018](0018-live-executors-are-leased-contained-processes.md) initially
selected an external gateway whose secrets never enter the CLI. Its separately
gated subscription mode said that a reusable account secret in an untrusted
child was ineligible.

The measured native candidate motivates testing a different premise: an
unmodified native harness could own its vendor-supported login while every
model-selectable tool is removed or dispatched to a separately contained
worker. That authenticated property remains unproved. Renaming the whole CLI
trusted would not be sufficient: its model-facing behavior and native code
remain attack surfaces. The useful boundary is a small split of authority.
The native harness may hold credentials and speak the provider protocol; it may
not receive workspace or effect authority. The worker may receive admitted
workspace and tool authority; it may not receive credentials or provider
networking.

The official Codex documentation describes managed mode, in which Codex owns
OAuth and token persistence/refresh, and experimental external-token mode, in
which the host supplies and refreshes a token. This decision chooses managed
mode and rejects external-token mode. Those
[authentication](https://learn.chatgpt.com/docs/auth) and
[app-server authentication](https://learn.chatgpt.com/docs/app-server)
pages are interface direction only. They neither pin Codex `0.153.4` nor prove
an account's entitlement, provider permission, or the safety of authenticated
startup. The historical fixture proof remains pinned to Codex `0.153.4`, source
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`. The first production candidate is
selected only after the supported principal/store interface preflight below.
A changed binary repeats catalog, startup, placement, mediation and lifecycle
qualification, not just the authenticated stage; current documentation cannot
supply compatibility credit.

## Decision

### One executor, one acquisition, two physical zones

Keep the existing `Executor`, `ExecutorProvider`, `LeasedCapability`,
`WorkspaceView`, acquisition row, journal, walker, `RunHost`, and owned-process
supervisor. A native adapter is one task-shaped executor acquisition, not a
completion broker, provider enum, native-session service, or second owner.
It creates two physically separate zones under that one acquisition:

1. The **native zone** runs one pinned vendor harness and its necessary owned
   descendants. It has no repository, authority Git, journal, worker scratch,
   host home, sibling acquisition, general host filesystem, inherited service
   descriptor, or effect adapter. It receives a narrow vendor credential-store
   mount, disposable non-account state, the fixed callback endpoint, and the
   admitted vendor-session egress described below.
2. The **worker zone** is the existing contained READ or WRITE workspace and
   process boundary. It has no credential store, native home, provider route,
   DNS, or network. WRITE still requires contained capture and contained gates
   before availability. Workers are launched only by trusted adapter code
   through the existing supervisor and acquisition guards.

The trusted adapter fixes the executable, model, effort, configuration,
startup roots, callback catalog, endpoint, framing bounds, deadlines, and
worker binding from the sealed manifest and launch identity. Model text,
native RPC arguments, environment, files, and account state select none of
them. The walker still decides nothing.

The native harness is trusted only for its pinned vendor authentication,
provider protocol, fixed tool-router implementation, and correct custody of
its store. The adapter, callback validator, launcher, egress enforcement,
worker boundary, supervisor, and deterministic effect code are also in the
trusted computing base. Model-selected code, worker code, repository content,
native outputs, callback arguments, and provider responses are untrusted.
Qualification of native code is therefore necessary; worker OS proof does not
prove it, and source review does not replace physical placement proof.

### The callback path is the only model-selectable tool path

The native catalog for an available profile contains exactly the admitted
callback tool set. Native shell, patch, file/image readers, code mode, internal
host tools, MCP, apps, plugins, skills, hooks, subagents/collaboration tools,
dynamic tool installation, and model-selectable authentication or configuration
RPCs are absent or mechanically unreachable. Startup helpers may exist only
when the profile's authenticated-startup conformance names them and proves they
cannot acquire model-selectable authority. A configuration flag or empty list
alone is not that proof.

The data path is fixed:

```text
sealed TaskSpec/grants -> trusted adapter -> native vendor protocol
provider tool call -> bounded private callback -> trusted validator
trusted validator -> existing contained worker -> bounded tool result
trusted adapter -> native vendor protocol -> ExecutorOutcome
```

The control path is fixed:

```text
journal lease -> materialize acquisition -> start native/bridge/worker
RunHost control + acquisition closure -> supervisor quiescence -> close row
success -> existing checkpoint/effect laws; restart -> existing recovery
```

For every callback, trusted code requires a known native turn and call id, an
exact registered callback name, schema-valid bounded arguments, the sealed
tool grant, the invocation's already-bound worker capability, and one terminal
response. Unknown, duplicate, late, cross-invocation, malformed, or oversized
calls refuse and remain truthful failure evidence. Callback results correlate
the native call, worker invocation, complete worker outcome, and native turn.
No callback lets the model select a host path, launch executable, capability
id, provider endpoint, configuration name, or grant widening. Worker-local
file operands and program text remain task data under the admitted worker's
tool contract; they cannot select the physical authority boundary.

The endpoint remains an invocation-membership boundary. A native descendant
may reproduce a permitted request, so byte equality is never called CLI-sender
authentication. This is safe only because every process able to reach the
endpoint receives the same finite invocation grant and the validator grants no
authority based on sender identity. A future operation that needs distinct
authorship must add a real physical/authenticated boundary or remain
unavailable; call-shape heuristics are not proof.

No native observation directly mutates external state. WRITE candidates still
cross the existing contained pack-verification path, and irreversible effects
still require deterministic code and journal-minted attestations (I1). Native
success cannot override callback, worker, capture, cleanup, gate, or transport
failure. Unemitted and interrupted facts remain absent or partial (I4).

### Vendor-owned credential lifecycle

Only the vendor's managed login is supported. An operator invokes the pinned
vendor binary's supported login/logout or repair flow directly. The native
harness owns token creation, secure-at-rest representation, refresh, provider
transport, and logout. Constructicon never implements an OAuth redirect or
token-refresh relay, supplies an external access token, copies a desktop auth
file, parses or redacts a bearer token, exports the store, or journals credential
bytes. A token visible to Constructicon or a worker is a conformance failure,
not an integration technique.

The account store is persistent, operator provisioned, dedicated to one
adapter/account binding, and not an ordinary native home. Assembly admits only
a vendor layout whose credential files can be mounted without general user
configuration, hooks, skills, plugins, MCP state, conversation caches, or
unrelated account data. The rest of each native home is fresh,
acquisition-owned, and deleted at close. If the vendor layout cannot separate
those classes, this mode is unavailable; copying a subset or mounting a broad
home is not a fallback.

The narrow store is the sole exception to the normal READ rule that persistent
state is not writable: the credential-owning native process may perform
vendor-defined refresh writes there. READ workspace remains immutable and
unmounted from the native zone. The exception neither grants a model tool nor
makes credential refresh a graph effect. No other persistent native write is
allowed.

One account binding is represented by a domain-separated digest of an
operator-selected opaque account key and the vendor-reported stable account
authority tuple: principal plus every independently selectable workspace,
tenant or organization scope. Raw account identifiers, email, tenant, token,
store path, store content hash, and rotating credential facts never enter
public descriptions, launch identity, the journal, or logs. After native
startup but before every model turn, and again before accepting its result,
trusted adapter code asks the vendor interface for the current non-secret
authority tuple, recomputes the binding digest, and refuses on absence or
mismatch. Token rotation preserves identity; an account or selected-workspace
switch does not. The qualified vendor refresh path must preserve that tuple
throughout the turn; pre/post checks alone do not prove it. If the vendor
cannot supply that guarantee and a supported query of every applicable
authority dimension, the mode is unavailable. A response claim from the model
or provider stream cannot establish account authority.

Before that initial match, worker callbacks remain closed and the driver sends
no model-turn request. Egress permits only qualified initialization,
principal-query and account/startup traffic, not model-session traffic. A
shared TLS destination is not proof that those operations are separated: the
pinned native protocol/startup implementation must enforce the phase boundary,
with destination enforcement applied wherever it can distinguish the phases.
If initialization needs uncontrolled account-dependent authority or can begin
a model turn before the check, the mode is unavailable. The bounded startup
conversation and its transition to task authority are identity-bound.

The pinned [account protocol](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs)
defines an `account/read` response exposing email and plan type, not
a stable account/workspace identifier. The source also declares account-session
types, but those declarations alone prove no dispatched metadata operation.
They do not satisfy this gate, and email is not a principal substitute. Before
implementation, use credential-free source/interface inspection to identify
a supported principal-metadata operation and store layout capable of this law.
That inspection identifies the operation, not an account's actual values.
If that needs another binary, select and requalify
it in a separately approved investigation; do not parse the authentication
cache, patch the vendor binary, or quietly weaken account binding. Actual
authenticated conformance remains a later, explicitly authorized gate.

Concurrent calls for one binding are initially forbidden. After lease
enrollment, materialization waits cancellably for an OS-backed exclusive store
lock while continuing the existing control checks. The existing physical
process owner holds the lock until all native processes and refresh activity
quiesce; caller death must not release it while descendants survive. Its crash
proof includes owner death and lock handoff, not merely successful close. It is
a lock on operator state, not a scheduler, durable lease ledger, or recovery
authority; the journal still owns invocation recovery.

Use one stable retained lock inode in a trusted, native-inaccessible root,
outside the writable vendor store. It is not deleted or replaced while the
binding exists. The existing supervisor inherits the same open file
description and does not explicitly unlock it before quiescence. Refresh,
rename, symlink and store replacement cannot change this lock object.
Assembly refuses aliases that give one physical store multiple lock identities;
operator maintenance takes this same lock. This reuses the existing acquisition
guard discipline, not a new lock registry or durable ownership law.

Login, logout, repair, store replacement, and account switching require the
operator to stop availability for that binding, request normal run quiescence,
take the same exclusive lock, and re-prove zero owned acquisitions/native
processes while holding it before maintenance. A pre-lock observation is not
the fence. Local close cancels, kills and joins through its live process handle,
revokes egress/callbacks, deletes disposable state, and releases the lock.
Successor reconciliation publishes/rechecks the existing externally addressable
closure fence and waits for the inherited guard and store lock: the original
supervisor reaps on live cancellation, owner-pipe death or its own deadline. A
successor does not recover a signal handle from the journal or signal a stored
PID. Neither path logs out, deletes, copies, repairs, rolls back, or interprets
the persistent vendor store. Store damage or a principal mismatch makes the
profile unavailable until explicit operator repair and requalification.

An operator login, logout, repair, store replacement or account/workspace
switch invalidates authenticated-startup and account-mode conformance even
when the resulting principal is unchanged. Requalify those affected gates
before restoring availability. Only refresh through the already qualified
vendor path preserves that evidence; changing binary, layout or physical
policy additionally repeats the corresponding earlier gates.

A native conversation and process id are observations, not durable authority.
Checkpointed work resumes without a native call where the existing manifest
allows it; uncheckpointed work may make a fresh acquisition and native call.
No account mode claims exactly-once model computation or resumes an old vendor
session after ownership loss.

### Acquisition-scoped vendor-session egress

`EffectiveGrants.network == "none"` continues to mean no networking by any
executor process, including model access. A remote native account profile
therefore supports only `network == "allow"`. Its meaning is narrowed by a new
public access mode, `native_vendor_session_only`: only the native zone may use
the exact vendor login/refresh/model and authenticated-startup destinations in
the qualified identity. Workers remain networkless. There is no host network,
arbitrary DNS, generic HTTP proxy, model-selected URL, user-supplied base URL,
localhost service inventory, or gateway-route alias.

Egress enforcement is substrate-owned and allocated only after the lease is
recorded. Its implementation may use a namespace firewall and a purpose-bound
connect relay, but it may not terminate or translate the vendor model protocol,
inject credentials, or become a completion provider. The native binary owns
TLS and validates the vendor peer. The trusted egress layer restricts destination
and connection lifetime; its pinned resolver, destination set, fail-closed
address-change behavior, TLS-observation assumptions, and denial of auxiliary
traffic are part of conformance. If redirects, proxies, ECH, dynamic endpoints,
or authenticated startup prevent mechanical restriction to the declared set,
the profile is unavailable rather than broadened to general egress.

Allocation is derived from the existing acquisition identity and guarded by
the same closure law. The physical owner refuses new connects, terminates
streams, and joins the bridge/native/worker trees before releasing its guards.
Local close drives that owner through live handles; successor reconciliation
publishes/rechecks closure and waits for physical quiescence before completing
lease disposition. Recovery uses the durable acquisition row and physical
closure, not a second route record or persisted PID. The maximum usable connection lifetime is
the remaining acquisition deadline; refresh creates no renewable lifetime.
Provider-side acceptance after local teardown is not claimed exactly once.

This differs deliberately from ADR 0018's `provider_route_only`: the native
harness possesses the persistent vendor login and originates vendor TLS, while
the gateway mode withholds credentials and exposes one externally authenticated
route. Neither mode may serialize as the other, share its conformance result,
or hide the distinction in a name or configuration digest.

### A parallel versioned public contract

Existing `ExecutorGrantPolicy` schema 1, `ExecutorProfile`,
`ProviderRouteIdentity`, `ExecutorLaunchIdentity` schema 1, their canonical
bytes, and every historical revision remain unchanged. In particular, the
source-derived `EXECUTOR_LAW_REVISION` v1 must be pinned in N1 to the value
independently reproduced from baseline `3718a86`; no checked-in literal golden
currently establishes it. Add that literal and representative complete-v1
canonical launch bytes/revisions as goldens, never expected values recomputed
from post-change source. Do not edit the bodies in its `inspect.getsource`
closure to add this mode. A new outer identity union dispatches by explicit
schema version. Old definitions and manifests resolve exactly as before.

L0 adds these distinct strict (`extra="forbid"`, frozen) records:

- `NativeExecutorGrantPolicyV2`: `schema_version=2`; finite normalized
  `tool_sets` and nonempty `model_ids`; `model_selection="explicit_only"`;
  `network_modes=("allow",)`;
  `network_access="native_vendor_session_only"`; finite normalized
  `environment_names`; `workspace_required`; and
  `tool_path="mediated_callbacks_only"`.
- `NativeIsolationProfileV2`: the existing workspace filesystem posture,
  process-tree ownership, environment allowlisting, and network enforcement;
  plus `native_workspace="none"`, `worker_network="none"`,
  `credential_state="narrow_vendor_store_rw"`, and
  `zones="native_and_worker_separate"`.
- `NativeExecutorProfileV2`: `schema_version=2`, name, structured-output fact,
  exactly one posture, finite efforts, the two records above, and
  `authentication="vendor_managed_account"`. Its one grant predicate requires
  exact posture/tool set, an explicit model in `model_ids`, a listed effort,
  no unproved environment inheritance, `network="allow"`, the workspace requirement, and
  every isolation fact; there is no closest match.
- `NativeEgressIdentityV1`: digests of the enforcement build, fixed destination
  policy, resolver policy, TLS assumptions, configuration, and physical
  conformance revision. It contains no endpoint locator or account fact.
- `NativeAccountStoreIdentityV1`: digests of the vendor store-layout law,
  mount/lock recipe, principal-query adapter, and store conformance revision,
  plus the non-secret `account_binding_digest`. It contains no path, principal,
  PII, credential, or store-content digest.
- `NativeExecutorLaunchIdentityV2`: `schema_version=2`; executable, runtime,
  adapter, decoder, isolation, configuration, limits, callback-protocol and
  callback-catalog digests; the v2 profile; egress and account-store identities;
  authenticated-startup and account-mode conformance revisions; and the
  source-derived v2 executor-law revision. Its revision uses a new
  `executor-native-launch` domain/version and cannot collide with v1.

The public executor/provider identity type becomes an explicit union of the
unchanged v1 and native v2 records. `Executor.profile` and capability-description
projection use the matching profile union. New boundary decoders dispatch on
version before model validation: an absent profile version selects historical
v1, exact `2` selects native v2, and any other present profile version refuses.
A failed v2 parse
never falls back to permissive v1 profile parsing. Keep this dispatch outside
the unchanged v1 source-law closure. This evolution publishes
`SystemDescription` 4 with description digest domain 4; schema-3 readers refuse
instead of dropping the trust mode. Graph/admission and manifest schemas need
not change: they already seal concrete grants and a capability revision. If
implementation discovers that a durable field rather than the existing
capability revision is required, it stops for a successor decision.

A v2 factory derives facts from actual artifacts and the operator binding,
rechecks them before launch, and is unavailable unless every conformance
revision is current. Constructing v2 data proves no placement. A fake may test
contract logic but cannot publish a production profile or satisfy an OS,
credential, authenticated-startup, or network gate.

Every model in one profile must support its advertised posture, tools and
efforts. If that product differs by model, publish separate truthful profiles
instead of accepting a combination the catalog cannot honor. The finite model
inventory is identity-bound and inspectable; a configuration digest or profile
name alone cannot supply model membership to a pure admission predicate.

### Qualification and availability

Acceptance of this ADR would authorize only the bounded implementation sequence,
not credentials or live availability:

1. Add the parallel v2 contracts, v1 golden compatibility proofs, schema-4
   description, and pure admission faults. No production provider is available.
2. Build the Codex concrete adapter against the existing account-empty fixture,
   preserving the pinned startup, mediation, lifecycle, mutation, and truthful
   failure evidence. This proves adapter behavior without credentials.
3. Prove physical native/worker separation, narrow-store mounts and exclusions,
   lock/quiescence, callback/egress allocation and revocation, destination
   refusal, cancellation, death, and successor recovery on qualified Linux.
   Synthetic store markers and controlled TLS peers may prove placement,
   lifecycle and local enforcement, never real login, refresh, vendor TLS,
   principal, or authenticated startup.
4. Only with separate explicit operator authorization, create a dedicated
   account binding through vendor login and qualify the pinned binary's actual
   authenticated startup, principal check, token refresh, account/startup TLS
   and egress, cloud/account configuration, extension inventories, malformed/refused paths,
   teardown, and account switch. An account-dependent positive control that
   cannot safely be exercised stays unqualified; a credential-free surrogate
   cannot establish it. Inventory the configured model destinations but leave
   actual model-session TLS/egress pending stage 5; no model turn is authorized
   by this startup stage. Unexpected reachable authority blocks availability.
5. Only with another explicit operator authorization, run a bounded live smoke
   for the exact READ or WRITE profile and account arrangement. This proves
   actual model-session TLS and destination behavior and completes the egress
   and account-mode conformance revisions before production availability.
   It is not an entitlement, legal, cost, performance, or general-model certification.

Stages 4 and 5 are explicit operator qualification runs through the same
owned launcher/driver/worker and lease boundaries. They do not advertise a
production provider as available or fabricate completed conformance revisions
to get past admission. Production factories require the resulting evidence;
the bounded qualification harness gathers it without a public availability
override, caller-selectable bypass, or second lifecycle owner.

Each stage needs the repository gate, exact-head Linux evidence where physical
claims are made, assertion mutations, downloaded-artifact inspection with no
secret retention, and independent review. READ and WRITE identities qualify
separately. A different binary, model catalog, store layout, account mode,
destination policy, runtime, startup surface, or provider arrangement is a new
conformance result. Claude and Pi begin at their own interface and placement
qualification; they do not inherit Codex evidence.

## Exact relationship to ADR 0018

If accepted, this ADR supersedes ADR 0018 only for profiles explicitly carrying
`NativeExecutorLaunchIdentityV2`:

- it replaces gateway-only **initial** authentication with the named
  vendor-managed native-account mode;
- it replaces the requirement that credentials stay outside the CLI, its home,
  and descendants with one narrow vendor store visible only to the qualified
  credential-owning native zone;
- it replaces `provider_route_only` for those profiles with
  `native_vendor_session_only` and permits the native binary to originate TLS;
- it adds the credential-store WRITE exception and native/worker zone split to
  isolation truth, rather than claiming the old single-zone profile unchanged;
- it replaces rev 1's built-in native shell-tool exercise for these profiles
  with a real native callback driving the contained worker shell while the
  built-in native tool is unreachable; effective sandbox configuration and
  authenticated startup helpers still require proof, not assumed nesting;
- it replaces gateway allocation/conformance for those profiles with the
  account-store, principal, authenticated-startup, and egress laws above.

It does not amend the existing gateway mode or its v1 bytes. It preserves ADR
0018's Linux-first physical enforcement, no unsandboxed fallback, one acquisition
and cleanup owner, inert acquire/materialize order, closure and recovery law,
task-shaped executor, complete finite grants, explicit model/effort, immutable
launch identity, network-none semantics, bounded process conversations,
truthful telemetry, contained WRITE capture, contained gates, and operator
authorization for credentials and deployment. ADR 0019's per-host
requalification continues to govern hosted Linux evidence and grants no secret
use on Actions.

## Alternatives rejected

- Copying a desktop login or token into an ephemeral home: the process still
  possesses a reusable credential, Constructicon becomes its intermediary, and
  rotation/recovery lose their vendor-owned meaning.
- Constructicon-managed OAuth or experimental external-token mode: creates the
  credential relay and refresh authority this decision excludes.
- Mounting the whole vendor home: silently admits configuration, extensions,
  cached conversations, and unrelated persistent mutation.
- A fresh login per call: expands account and browser state beyond the lease,
  makes refresh/logout failure part of every invocation, and does not improve
  workspace containment.
- Concurrent native calls sharing one store: risks vendor-state corruption and
  makes account switching or refresh race invocation identity.
- Calling the native process wholly trusted: ignores model-selectable native
  tools and would let credentials become workspace/effect authority.
- Treating callback request bytes as CLI authentication: the physical fixture
  refutes that claim; membership plus uniform bounded authority is the actual law.
- Relabeling v1 `provider_route_only` or changing its source-derived law: hides
  materially different credential, TLS, persistence, and trust semantics and
  changes historical revisions.
- A universal auth RPC, completion gateway, provider enum, broker, native
  session ledger, or second supervisor: duplicates existing contracts and
  violates the task-shaped seam and single-owner laws.

## Consequences

The design admits a narrow native subscription route without giving the model
credentials, native-zone workspace access, or new durable authority. It adds
the pinned authentication/tool-router code, vendor store layout, principal
query, and egress enforcement to the trusted computing base. OS containment
limits consequences but does not prove correct secret handling.

Account persistence is intentionally longer than an invocation while every
connection, callback, process, workspace, and disposable home remains
acquisition-scoped. Operator account maintenance is serialized with runs; it is
not automated recovery. Failing any separation, startup, account, principal,
TLS, egress, mediation, or cleanup gate leaves the profile discoverable as
unavailable with itemized reasons.

This proposal is not evidence that its gates passed. Until explicit acceptance
and the separately authorized stages succeed, ADR 0018's gateway route remains
the only designed live authentication mode; no native account executor exists.
