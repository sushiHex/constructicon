# M8 — Live executors behind a proved process boundary, rev 1

Status: review draft; not approved for implementation.

Planning base: `71c4fe38ec8898d8af0f463c56ff34f3850bf63e`, the squash merge
of M7.1 documentation closure PR #25. Written in Codex after inspecting that
tree and primary backend documentation on 2026-09-09 UTC.

Approval requires a decision on
[proposed ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md).
This PR contains planning only. Existing tests are baseline evidence, not
evidence that any M8 isolation or adapter behavior is implemented.

## 1. Outcome and scope

M8 makes Claude Code, Codex, and Pi usable through the existing task-shaped
`Executor`, where each configuration can actually enforce the requested
grants. The order remains Claude Code, then Codex, then Pi, as in the frozen
M8 milestone. Each adapter joins the same credential-free contract suite.

The design principle is to keep one owner per fact:

- `EffectiveGrants` say what this invocation may do.
- The executor's profile says which grants it can enforce.
- Its content-derived capability revision identifies the installed launch law.
- The existing capability lease owns the physical acquisition.
- The backend decoder reports observations, not authority or scheduling intent.

READ and WRITE are separate assembled configurations, not a mutable mode
switch. A READ agent cannot write the admitted snapshot. A WRITE agent can
change its staging acquisition, not the authority repository, journal, parent
checkout, or another acquisition. A candidate still crosses as `GitRef` and
can be installed only through M3's existing proof-carrying effect.

Non-goals: a completion-level provider interface; a general container platform;
remote job dispatch; backend session synchronization; a second scheduler;
automatic model fallback; dynamic plugin discovery; a new artifact service;
exactly-once model billing; M9 learning; kernel-attested panel provenance; and
wall-clock human deadlines. A CLI timeout is the already-granted process
deadline, not a new human-wait policy.

## 2. What the base already establishes

Read [INVARIANTS](../../INVARIANTS.md), [ARCHITECTURE](../../ARCHITECTURE.md),
and [CONTRIBUTING](../../CONTRIBUTING.md) first. Relevant frozen decisions are
[0005](../../adr/0005-executor-seam.md),
[0008](../../adr/0008-isolation-admission.md), and
[0009](../../adr/0009-git-authority.md). Older plans remain historical.

The source audit found:

| Existing seam | What exists | M8 obligation |
| --- | --- | --- |
| `core/executor.py` | Task, profile, success/partial/failure, `validate_grants`, `execute` | Reuse them; replace `workspace: object` with `WorkspaceView` |
| `core/grants.py` | Concrete grants and an isolation declaration | Add complete live grant policy, not a second grant language |
| `runtime/validator.py::_register_atomic` | Posture/profile check | Check the complete declared live policy before admitting |
| `api/system.py` | Channel assembly coherence; other capabilities can be lazy | Establish exact live executor descriptor/object coherence |
| `runtime/registry.py::activate` | Sealed capability revision equality | Keep it; require the revision to bind actual launch content |
| `core/workspace.py` | `WorkspaceView`, synchronous `WriteWorkspace`, invocation leases | Reuse views/identities; keep the synchronous contract legacy and give contained capture an explicit async contract |
| `runtime/walker.py` | Acquire → durable lease → invoke → close; checkpoint recovery | Add generic post-record materialization; no backend scheduling or session recovery |
| `substrate/executors/fake.py` | The only current executor | Preserve the fake and add a genuine subprocess test double |
| `substrate/git/authority.py` | `commit_all` runs Git against mutable staging metadata on the host | Contain staging Git and validate its immutable object export before authority import |
| `substrate/gates/runner.py` | Repository checks run as host subprocesses with inherited environment | Contain checks before offering live WRITE, not at milestone closeout |
| `api/introspection.py` | Published executor profiles at description schema 2 | Publish the expanded profile honestly at schema 3 |

The audit also matters negatively: `network_enforced` is not consulted by
`IsolationProfile.satisfies`, and the current admission path does not call
the injected executor's `validate_grants`. A new adapter cannot treat these
names as an existing full-grant proof. The new shared predicate must be used
by both admission and the adapter, without executing subprocesses in L2.

The available `system.describe()` inspection used a temporary, fake-only
assembly. It exposed the existing executor profile and no hidden standard CLI
component. Descriptions are assembly-specific; this is not an inventory of
some unrelated user's running system. Details are in the
[planning evidence](../handoffs/M8-planning-evidence.md).

## 3. Proposed host boundary

### 3.1 First supported environment

Propose a dedicated Linux host/environment, initially a pinned Ubuntu 24.04
CI image, with a pinned and tested bubblewrap build. Required facilities are
unprivileged user namespaces and mount, PID, IPC, UTS, and network namespaces.
The implementation must record the exact kernel, distribution, bubblewrap,
runtime root, and effective policy used for acceptance. A distribution name
or `bwrap --version` is not the availability check.

Native Windows and macOS run the fake and parser suites but do not offer a
live executor. WSL2 is not auto-approved: the same probes must pass, and the
journal, authority repository, and acquisitions stay on the Linux filesystem,
not on a mounted Windows checkout. This session has no installed WSL
distribution; no Linux containment result is claimed here.

Ubuntu 24.04's default AppArmor user-namespace restriction is an explicit
prerequisite, not something the launcher may bypass. Canonical documents a
purpose-built `bwrap` profile; see the primary sources in the evidence record.
An operator must approve and provision the exact image's compatible profile,
or choose another reviewed environment before the containment slice proceeds.
The evidence must identify the loaded policy and executable attachment, not
only a profile file on disk, and run the probes as the actual service user.

Constructicon's installer, runtime, and test runner never change AppArmor,
sysctls, privileges, or installed distributions. Explicit image provisioning
is separate, reviewed operator work. The proposed Ubuntu lane keeps the global
user-namespace restriction enabled; a global disable, root execution, setuid
fallback, or broad shell exemption is not an accepted repair. A denied/missing
profile must fail availability and its negative test. A host failing these
prerequisites is unavailable, not a degraded live backend. No working image
or loaded profile has been proved in this planning session.

Before advertising availability, the substrate must run a bounded benign
probe through the exact outer launch recipe under that service user. Prove
namespace setup and the effective mount/process restrictions, not just that
`unshare(CLONE_NEWUSER)` succeeds. Missing or denied policy makes the profile
unavailable before task execution. Recheck the prerequisites before launch;
a subsequent setup failure still prevents the backend from starting. No
availability result licenses a direct-host retry.

### 3.2 Threat and trust boundary

Treat repository content, task text, backend output, and all model-generated
commands as hostile. Protect the host and other runs even when those commands
ignore every permission flag. Trust the kernel, bubblewrap, the pinned runtime
root, deterministic substrate code, operator provisioning, and registered
host-side Python components. M8 does not sandbox arbitrary Python components
inside the Constructicon process.

The launcher gives the whole CLI a new filesystem/process boundary:

- A read-only, content-identified runtime root; no bind of the host `/` or home.
- Exactly one acquired workspace at a fixed sandbox path. READ uses a
  read-only mount; WRITE uses the invocation's separate staging repository.
- Private scratch, temporary files, and runtime home. These are disposable
  namespace storage, not persistent host writes authorized by READ.
- Fresh proc/dev views with no parent-process filesystem view, service sockets,
  SSH agents, inherited descriptors, or shared terminals.
- No authority repository, journal, sibling workspaces, package-manager host
  cache, or host credential files. Symlinks cannot enlarge those mounts.
- A new PID namespace, a new session, dropped capabilities, no-new-privileges,
  and a tested parent-death chain. `setsid`, double-fork, ignored TERM, and
  grandchildren holding output pipes do not outlive completion or cancellation.

Use a small concrete bubblewrap recipe, not a general sandbox DSL. The kernel
already kills the namespace when its init exits; use that ownership boundary
instead of inventing process-tree discovery as the security mechanism. The
implementation must test the complete parent-death chain and launch races,
not infer it from that kernel fact. External references are evidence for the
candidate mechanism, not an executed Constructicon proof.

PR B records and asserts the actual mount/FD table: fresh PID-local `/proc`,
no `/sys`, minimal private `/dev`, private mount propagation, explicit service
UID/GID mapping, and only the named standard-I/O/control descriptors. The
launcher must not use optional namespace fallbacks such as `--unshare-user-try`.
`no_new_privs` is not a seccomp policy. No additional general syscall filter is
selected here; the trusted-kernel and resource-exhaustion exclusions below are
intentional. Namespace rearrangement by a child does not authorize a host
namespace FD or additional host mount. Test that boundary, including nested
namespace attempts, rather than inferring it from backend sandbox settings.

Always use a private network namespace. For `network="none"`, expose no
external route or inherited network-capable socket. This also prevents model
access. The initial remote-backed profiles accept only `allow`; a denied
remote task refuses before spawn. `allow` is an upper bound, not an obligation
to expose the host's network. These profiles additionally publish
`network_access="provider_route_only"`: the only reachable external service
is the invocation's leased native provider route described below. Host loopback,
DNS, LAN, internet, and arbitrary CONNECT are unavailable to descendants.
Network-capable harness tools such as general web fetch are not offered.

This restriction applies to both ordinary and counterfactual execution.
Otherwise a simulated effect adapter would provide no protection against a
shell performing the same external write directly. Model requests themselves
remain explicitly authorized network use and are not claimed to be free,
simulated, or exactly-once billed.

No defense against host-kernel exploits, side channels, or resource exhaustion
is claimed. Acceptance uses bounded hostile children, not a real fork bomb.
Per-process limits and output/deadline limits are still required, but do not
become a claim of multi-tenant denial-of-service isolation.
A hostile invocation may exhaust the dedicated runner and disrupt its other
runs. Operators needing stronger availability must provision a separately
reviewed VM/cgroup resource boundary; this plan does not silently supply one.

### 3.3 Environment, authentication, and configuration

Construct the child environment from scratch. The grants' allowlist selects
which approved host values may be inherited; it is not permission to inherit
the rest. Fixed sandbox-local `HOME`, `PATH`, locale, and backend config paths
come from the launch recipe, not the host's values. Loader/interpreter injection,
host auth, git helpers, and endpoint-routing variables cannot arrive through
an ordinary environment grant. Unsupported names are refused, not ignored.

The proposed initial auth mode is a provisioned provider gateway reached by an
invocation-owned route. Provider/account credentials and any gateway bearer
credentials stay in trusted host-side provisioning, outside the child and its
bridge. Possession of the mounted route is the invocation's delegated network
authority; no bearer secret is needed inside it. A CLI that requires a nonempty
API-key setting may receive a fixed, public placeholder only when that exact
integration proves it grants no authority outside the mounted route. Otherwise
that bootstrap is unavailable. Do not claim redaction can keep a credential
secret from hostile code that received it.

Provision an acquisition-specific Unix-domain route socket outside the
namespace; mount only that endpoint, not its parent or a general gateway
control socket. An invocation-owned loopback byte bridge inside the namespace
connects that endpoint to the CLI's native HTTP base URL. It performs no HTTP
policy, provider translation, credential issuance, or routing selection. The
external gateway owns all route/auth enforcement. The bridge is a concrete
subprocess detail with all three CLIs as consumers, not a new public protocol.
It is killed with the invocation and exists only for `network="allow"`.
The initial transport is plaintext HTTP on namespace-private loopback, with
upstream TLS owned by the external gateway. Each pinned CLI must prove it
supports that base URL. No TLS interception, added CA, general proxy, or CONNECT
fallback is introduced to accommodate an incompatible backend. The bridge
holds no workspace descriptor and transfers bytes only; the endpoint rejects
ancillary descriptor passing rather than importing new capabilities.

The gateway must not offer arbitrary CONNECT, client-selected upstreams,
redirects to unapproved origins, admin routes, or account mutation. Its fixed
route supplies upstream authentication outside the namespace; child-supplied
auth, host, path, and forwarding headers cannot change that authority or cause
it to be returned in responses. No privileged credential belongs in argv,
child environment/files, public metadata, logs, or fixtures. The whole
invocation can use its route, including hostile shell code; this is bounded
provider access, not protection of model usage from that invocation.

Route allocation/revocation uses the gateway's trusted provisioning interface
from the executor lease provider, never an interface mounted into the child.
Its handle belongs to the existing acquisition, is idempotently closed, and
expires without a live host, no later than its granted deadline. Revocation
must stop existing connections as well as new ones. The configured integration
must supply a genuine fake exercising the same lease contract; no generic gateway
manager or second durable store is introduced. A socket path is a locator,
not evidence of ownership; a stale acquisition cannot revoke a newer route.
Before allocation, the durable lease's `resource_ref` records a non-secret
allocation key derived from its existing acquisition identity and epoch.
The gateway must support idempotent allocation and closure by that key;
closure permanently refuses a later allocation even if no route existed yet.
A lookup returning absent is not revocation. The server-minted route lease id
is returned to the live handle, not required to discover it after a lost reply
or written back as a second lease-record phase. The gateway binds each request
and stream to its server-owned lease, not client-supplied identity, peer UID,
or a reused socket path. Its clock enforces the granted deadline even after
host death; the maximum orphan window is the remaining granted lifetime.

Two proofs are separate. Credential-free CI exercises allocation, mounted-route
access, close, expiry, and stale-owner behavior against the fake. Before a live
profile is available, an operator must select a concrete production integration
and supply deployment-specific conformance evidence for the actual gateway
build and effective route/auth policy. Exercise the same adversarial requests
against that deployed enforcement, including header/path substitution,
redirects, CONNECT, cross-route access, expiry, and revocation of open streams.
Use controlled upstreams and sentinel credentials; no paid call is necessary
to prove the policy. A fake or a successful model smoke call cannot replace it.

Bind the integration build/configuration, effective policy, and conformance
suite revision into the secret-free launch identity. Trusted assembly verifies
the configured deployment matches that evidence; allocation must refuse policy
drift and pin the proved policy for the route's lifetime. A deployment that
cannot establish those facts remains unavailable. This is an operator-owned
prerequisite, not caller-supplied attestation or a second durable authority
store. No concrete production integration is selected or proved by this draft;
PR E cannot be accepted without one. Accepting the gateway-only posture is not
accepting an unspecified gateway as safe.

This is an external transport prerequisite, not permission to implement a
Constructicon completion API or an account manager. Native request/response
bytes pass through without model selection, completion normalization, or
retry policy being invented by Constructicon. The adapter selects no fallback
provider. A deployment without a suitable gateway is unavailable for the
initial auth mode. Operator-approved routes and the recipe, excluding secrets,
participate in capability identity.

Subscription-login support is not assumed to have the same safe bootstrap as
API-key gateway access. No login file is copied out of this machine. Before
offering such a mode, a backend slice must prove an officially supported,
credential-isolated bootstrap and the same failure contract; otherwise it
records the mode as unavailable. **Owner acceptance of gateway-only initial
authentication is a planning decision, not an implementation shortcut.**

Each backend starts with controlled configuration and no ambient extensions,
MCP servers, hooks, skills, subagents, background sessions, or startup commands.
Repository instruction files may be admitted as task data, but cannot become
an executable configuration source. Exercise malicious user, project, local,
and managed configuration independently. A convenience flag is not sufficient
when another precedence layer can override it. No prompt or task field may
select CLI flags, model routes, host paths, or a resume session.

Each pinned backend also needs an egress inventory: attempted endpoint,
disable/routing control, and expected refusal or harmless failure. A model
base URL is not a promise that updates, telemetry, authentication, and other
traffic use it. Observe connect attempts in the isolated namespace during
startup, a tool call, and completion; prove necessary traffic uses the one
route and denied auxiliary traffic does not prevent the supported operation.
Otherwise the configuration is unavailable, not eligible for wider egress.

### 3.4 One outer boundary; no required nested sandbox

The initial Linux configurations disable backend-internal OS sandboxing
where present. Constructicon's proved outer launcher remains mandatory for the
whole CLI and every descendant. Tool selection and noninteractive approval
policy remain separate, explicitly tested controls. This is a fixed launch
decision, not an automatic fallback after an inner sandbox fails.

The supported configuration candidates are Codex's
`--sandbox danger-full-access` with `approval_policy="never"`, and Claude
Code's `sandbox.enabled=false` in controlled settings. Official documentation
describes these controls; the evidence record links it. The pinned Linux
versions must prove their effective behavior. These settings apply only
inside the acquired outer boundary, never to the operator's current CLI or
host configuration. Neither changes the admitted READ/WRITE or network grant.

Do not enable weaker nested-sandbox modes, add another sandbox-policy
abstraction, or relax AppArmor/capabilities to make an inner launcher work.
If the pinned CLI or applicable managed policy requires nested isolation,
that configuration is unavailable; do not bypass the managed requirement.
The effective backend configuration is already part of launch identity.
Changing this composition would need a separately reviewed, proved recipe.

PR B must exercise an outer launch on the selected restrictive image and
record whether a child can initialize a nested `bwrap`. Do not equate lack
of child capabilities with rejection of the `userns` syscall itself. PRs F
and G must then run the actual pinned CLI against a credential-free fake
provider on an image where nested `bwrap` initialization is denied. Require
an actual shell tool, driven by a scripted provider response, to complete
inside the outer boundary. Assert no inner launcher attempt and unchanged
READ/WRITE/network restrictions. Config/argv capture alone is insufficient.
Malicious project configuration and forced managed-policy incompatibility
must not silently change the chosen mode or cause a retry outside the outer
boundary.

## 4. Contracts and authority placement

### 4.1 One complete profile and one grant predicate

Add one optional `ExecutorProfile.grant_policy` in L0. Its non-null shape is
versioned and complete for M8:

```text
ExecutorGrantPolicy(schema_version=1)
  tool_sets: exact supported sets of model-callable tool names
  network_modes: supported subset of {none, allow}
  network_access: none | provider_route_only
  environment_names: host environment names eligible for inheritance
  workspace_required: bool
```

Store tool sets as sorted, duplicate-free tuples and normalize their inventory
order. An empty tool set is a supported configuration only if explicitly
listed. Unknown names, unsupported combinations, command-prefix patterns, and
wildcards are refused. This finite inventory avoids claiming every narrowing
is implementable by every CLI. A backend may add a proven combination under a
new capability revision. No model translates grants into permissions.

`ExecutorProfile` owns the pure itemized grant predicate. It checks posture,
isolation, the exact tool set, network support/enforcement, inherited names,
and an explicitly requested effort against `accepted_efforts`. `None` effort
means the explicit backend default, not a made-up effort. Missing/empty explicit
model ids are refused; the adapter handles backend model-id syntax without
silently replacing a request. Runtime admission and adapter `validate_grants`
call the same predicate. The adapter additionally checks dynamic task shape
and live availability before any launch.

Tool grants are a selection of the pinned harness's operations, not a security
claim that `Bash(git *)` contains a shell. The backend's reachable tool catalog
must match the selected set in the fixture/launch proof. If a pinned version
cannot disable a tool or an implicit feature, that set is not offered. Even
if a backend violates its tool policy, OS containment still prevents wider
filesystem authority. No observation after a tool ran retroactively authorizes
it. `FakeExecutor` remains the real second consumer of the task contract;
the new subprocess double covers process behavior the fake cannot exercise.

### 4.2 Bind installed reality to the existing revision

The live factory builds one secret-free launch identity containing:

1. backend and runtime-root content digests, not a version string alone;
2. adapter/decoder law revision and the complete profile;
3. isolation recipe revision, controlled configuration, and fixed limits;
4. gateway integration build/configuration, effective route/auth policy, and
   conformance suite revision, excluding credential values and route locators.

Its canonical digest is the existing `CapabilityDescriptor.revision`. Host
installation paths are locators, not portable identity. Cache verification only
for immutable artifacts; refuse executable/config/runtime drift before launch.
There is no lookup of `latest`, PATH fallback, auto-update, or silent retention
of a revision over changed bytes. CLI processes cannot update their mounted
runtime or access another executable installation on the host.

Assembly compares the actual provider's derived revision and profile with the
descriptor, including READ/WRITE and leased status. A declared executor with
no live provider is unavailable for admission. Activation keeps exact revision
checking; before every launch the substrate rechecks the pinned physical
prerequisites. Runtime decides no OS policy. Missing prerequisites produce a
typed unavailability/refusal before child execution, not a manifest rewrite.

### 4.3 Reuse invocation leases and workspace types

Use the existing `LeasedCapability` protocol for live providers. For M8,
`acquire` constructs an inert resource handle, binds `LeaseContext`, and
computes the complete recovery reference. It creates no persistent directory,
snapshot, quarantine, or provider route, and launches no CLI. Add one optional
in-memory field to L0 `AcquiredCapability`:

```text
materialize: Callable[[], Awaitable[None]] | None = None
```

The generic sequence is acquire handle → record lease → enroll in cleanup →
await materialization → expose resource. Materialization prepares the already
returned handle; it does not replace its identity or mutate `resource_ref`.
The walker awaits it only after durable recording and adding the acquisition
to its ordinary cleanup set. Recording failure never calls it; materialization
failure/cancellation uses that cleanup boundary, and ownership loss leaves
the durable row for successor reconciliation. The callback contains provider
work, not a walker choice about Git, processes, or gateways. A bound executor
still rejects grants differing from its acquisition's sealed grants.

The default `None` preserves legacy providers' call convention and behavior;
it does not credit their eager allocations with M8 crash safety. The new
providers and genuine deferred-resource doubles exercise the post-record
phase. No durable schema or extra acquisition state is introduced.

Retype `Executor.execute(workspace=...)` to `WorkspaceView | None`. Keep the
existing synchronous `WriteWorkspace` for historical assemblies; the contained
WRITE resource in section 4.4 exposes the same view with explicit async capture.
No caller-authored string,
`TaskSpec` field, `ArtifactRef.locator`, or arbitrary path becomes a mount.
The live provider validates workspace ownership against the assembled workspace
provider and the same invocation/acquisition epoch. READ needs an exported
snapshot; add its leased provider beside the existing git workspace provider,
not a new workspace hierarchy. The fake still permits `None`.

`close` terminates the entire owned process boundary before returning. A
backend returning success while descendants still run is not completed.
Cancellation cleanup must withstand repeated cancellation, then propagate
`CancelledError`; it must not convert shutdown abandonment into user cancel.
`reconcile` can reap only exact stale acquisitions supplied by the existing
lease mechanism, never scan-and-kill arbitrary PIDs. Reused PIDs and a new
epoch are not the old resource. Do not reuse backend session ids on recovery.

Namespace-private scratch dies with its processes. Every persistent resource
starts after lease recording and is recoverable from that row alone: local
resources stay under its predetermined acquisition root, and remote resources
use its predetermined allocation key. This includes later call resources,
gate snapshots, and import quarantines, not only initial workspace creation.
Random unrecorded paths and a cleanup-only `finally` do not satisfy this law.
Before the row exists there is nothing persistent to recover; after it exists
the successor can close a never-started, partial, or complete materialization.

Late materialization must not recreate a disposed resource. Git-backed READ,
WRITE, and gate acquisitions reuse the immutable closure marker in section
4.4. One acquisition-scoped filesystem guard serializes physical use/creation
with removal. A producer checks that marker under the guard before creating
or using any path; closure commits the marker first, waits for guarded work
to quiesce, and then removes its owned resources. It cannot report disposal
complete while a previous producer can still write. A late producer must
observe closed and refuse, including one already waiting for the guard.

Use a concrete Linux advisory file lock outside child mounts. Its lifetime
must cover the actual work, not just the Python coroutine: transfer the held
descriptor to the trusted launcher supervisor while a subprocess can write,
without passing it to the untrusted payload. Parent death must not release
the guard before the child boundary is quiescent. The selected bubblewrap
build's `--sync-fd` is the candidate primitive; PR B must prove its lifetime
and non-exposure, including death during setup. Guard files are stable
coordination inodes, not payload storage; initial M8 retains them with the
closure markers. Never unlink/recreate a guard while an old waiter could
still hold its inode. Async waiting and cancellation must leave the event
loop responsive. Gateway allocation
uses its native close-by-key fence from section 3.3, not this filesystem lock.

The row is the recovery inventory; the marker is the external revocation fact;
the lock only serializes physical work. None is a second scheduler or process
ledger. Death probes cover both sides of recording and materialization, and
both orders of late production versus reconciliation. A failure to quiesce
leaves the lease unreconciled for retry rather than claiming successful cleanup.

Executor teardown cannot depend on the lexical order of capability aliases.
`execute` finishes cleanup before its caller can commit/release a WRITE
workspace; lease close is the idempotent safety net. A resource handle cannot
continue executing after its acquisition has closed.
This is essential because the existing walker checkpoints the node before
ordinary lease closure. Do not move or duplicate the checkpoint law to make
an executor that returns early appear safe.

Each `execute` call owns and reaps its own namespace. The acquisition owns
those call resources; it does not become a persistent backend session.
Sequential calls within a trusted component remain task calls, with no
session resume or model-charge deduplication claim. Concurrent calls must
either be explicitly supported with isolated call resources or be refused
before launch; the first implementation serializes them. Closing an
acquisition prevents any new call before tearing down existing resources.

### 4.4 Mutable staging never becomes host execution authority

The existing `StagedWriteWorkspace.commit_all` runs `git add`, `status`, and
`commit` on the host against the staging repository's local configuration.
A harmless hook probe confirmed execution there. Containing the preceding
model process does not sanitize `.git`, attributes, hooks, filters, helpers,
or an object-store locator. The whole stage remains untrusted after teardown.

Preserve ADR 0009: a WRITE acquisition is a separate repository, the agent may
commit and move its refs, and the exact candidate commit crosses as `GitRef`.
Do not replace this with a worktree-only importer that invents a different
commit or deletes the agent's history. Instead use the same concrete launcher
for every Git operation that reads mutable staging metadata, including reset,
capture, and export. These processes get no authority repository, host home,
network/provider route, or arbitrary inherited descriptor. Disabling known
hooks is defense in depth, not proof that every Git execution surface is gone.

Teardown of the model call precedes capture. The contained capture commits
and resolves the candidate, then reaps every writer. A subsequent read-only
contained export produces a bounded, self-contained Git pack for that exact
commit; no staging writer or bridge-held workspace handle survives across
this boundary. Missing objects, stale locks, malformed output, cancellation,
or an export that does not contain the named commit fail capture. Resetting
uses a trusted pack of the exact admitted `GitRef`, not host access from the
dirty repository to the authority. No host `git -C <stage>`, local fetch from
it, config copying, or import-time walk through its `.git` is permitted.
Symlink-safe disposal of the acquisition is cleanup, not Git interpretation.

Trusted import accepts immutable pack bytes, never a command stream, archive
path list, client refspec, or staging pathname. Use a fresh substrate-owned
quarantine with clean metadata, outside all child mounts, to verify object
format, object hashes/types, complete reachable closure, and the exact
candidate OID. Git's strict pack/object validation is the mechanism, not a new
Python Git parser. Reject traversal/symlink redirection, alternates/promisor
dependencies, malformed packs, and size/object-count bounds without fetching
anything. Only verified immutable objects may enter the authority, whose
existing write-once candidate-ref operation pins the same OID. Neither the
target branch nor the installation receipt changes. The quarantine is an
acquisition-owned temporary import buffer, not another durable repository of
record or a second attestation authority.

Expose `AsyncWriteWorkspace` in L0 as `WorkspaceView` plus async `reset_to`
and `commit_all`, with the existing arguments/results. The contained provider
and a genuine controllable fake exercise this contract. A distinct
`workspace.contained` capability kind and new awaiting component versions
separate it from legacy synchronous `WriteWorkspace`; never silently change
a retained call convention or wrap the blocking legacy importer in a thread.
The capture path keeps the event loop responsive, observes ownership and
cancellation, and quiesces all work before cleanup returns. A check before
publication is not an atomic ownership fence. Reuse the Git-owned closure
fact introduced with resource materialization: an immutable marker named
from the existing acquisition id (which includes the epoch), under a reserved
authority ref namespace. It points to that acquisition's trusted base commit.
Its absence permits physical work/publication; its presence revokes them.
For a gate the anchor is its admitted base, not a candidate discovered later.
It never reopens,
and initial M8 performs no marker GC: deletion could authorize a late writer.
This is an explicit extension of ADR 0009's external lifecycle evidence,
not a SQLite schema change, process ledger, or new install effect.

Publication uses one `update-ref --stdin` transaction that verifies the
closure marker is absent and creates the write-once candidate ref, or verifies
its identical OID on an exact retry. Close/reconcile uses the same Git
transaction boundary to create/verify the closure marker and either retain
the checkpointed candidate (`release`) or CAS-delete/verify absence of the
uncheckpointed candidate (`discard`). A concurrent change retries the complete
transaction against the observed ref values; it must not skip an absent
candidate without verifying that absence. Marker and candidate identity come
from the trusted acquisition, never a supplied refspec.

Thus publication either precedes closure and is seen by disposal, or follows
closure and is refused by Git. This is not claimed to be atomic with SQLite's
ownership transfer. Reconciliation cannot finish before the external closure
transaction commits, and no late old-epoch publication can cross it, even if
the old host dies before post-publication cleanup. A fresh epoch has different
refs. Use the existing lease's authoritative disposition; the marker adds no
new rule deciding which candidate a checkpoint retains. Failure leaves the
lease unreconciled for retry, never reports disposal complete.

Existing acquisition/lease identities own staging and quarantine. Publication
followed by response loss reuses the same candidate while open or follows the
existing release/discard law once closed. Of authority refs, only protected
candidate refs and closure markers change; installation still requires the
existing attestation and effect transaction.

The live WRITE assembly requires both this safe workspace provider and the
contained gates. Neither the launcher-only slice nor a fake may enable a
model-written stage to reach legacy `commit_all`, gates, or effects. Historical
trusted/fake-only assemblies keep their exact bytes and stated scope.

### 4.5 Task data and observation

`TaskSpec.instruction` enters as stdin data, not shell text or a CLI option.
Arguments are an argv vector with fixed delimiters; launch uses no shell.
Record an argv-capture fixture with quotes, newlines, leading dashes, and
non-ASCII text. Task/context limits are checked before spawn.

Literal `TextContext` is supported. `GitRef` context resolves through the
assembled git authority to exact, read-only materialization; path selections
are validated, never treated as host paths. `ArtifactRef` requires bytes from
an explicitly assembled content-addressed resolver with digest, size, and
media-type verification. No generic locator fetch is added. If no resolver is
assembled, refuse that context kind before spawn; M8 does not build an artifact
service just to make every reference available.

The subprocess pump owns concurrent stdout/stderr draining, deadlines,
backpressure, UTF-8 framing, bounds, and teardown. Backend decoders own only
their native event grammar and observation extraction. Private concrete
helpers are enough; a new interface needs the real subprocess pump and its
contract-exercising test double. There is no shared public backend event IR.

Proposed fixed, revision-bound defaults: 1 MiB combined instruction/literal
context, 4 MiB per stdout record, 32 MiB total stdout consumed, 64 KiB retained
stderr head+tail, and 2 seconds TERM grace before forced teardown. Artifact
materialization uses a separately bounded 16 MiB total. Tests override with
small values through trusted assembly only. Exceeding a bound stops the
process and reports a non-success outcome; never drop bytes and report success.
Deadline enforcement includes spawn and pipe draining; teardown grace is
reported elapsed cleanup, not additional authorized backend work.

Outcome precedence, reusing existing types:

| Evidence | Result |
| --- | --- |
| Unavailable runtime/grants/task shape, no child started | `ExecutorFailure(kind="unavailable")` |
| OS spawn/setup fails | `ExecutorFailure(kind="spawn")` |
| Deadline reached, even after useful text | `ExecutorFailure(kind="timeout")`, salvaged observation |
| Backend nonzero exit or explicit terminal failure | `ExecutorFailure(kind="exit")`, salvaged observation |
| Exit zero but damaged/truncated/contradictory stream, bound exceeded, or no valid terminal result | `ExecutorPartial`, never success |
| Valid terminal success, undamaged stream, exit zero, all descendants reaped | `ExecutorSuccess` |
| Cancellation/ownership loss | Clean up and propagate control flow; no successful output/checkpoint |

Bounds deliberately causing termination retain the partial classification,
not a misleading backend-exit diagnosis from our own kill. A setup failure
and a backend failure are distinct. Malformed records cannot be repaired by a
later success event. Unknown semantic record types demote; only explicitly
fixture-listed nonsemantic records can be ignored. Preserve UTF-8 across byte
chunks, split JSONL on LF only, and reject duplicate keys/non-finite JSON.

Usage comes from authoritative backend observations, never delta-plus-final
double counting. Missing usage/model/rate-limit fields stay `None`. A model
alias or a CLI echo of the requested name does not prove which model served
the request. Aggregate fallback/provider results cannot be attributed to a
single served model unless the backend evidence establishes it.

`response_schema` uses a backend's native structured-output mode only where
supported. It does not justify inventing a general JSON Schema engine. Parsing
is strict; application components still validate their returned typed payload.
Pi initially advertises no native structured-output guarantee and refuses a
non-null requested schema unless its pinned interface later proves one.
A recorded terminal result is not proof that the model obeyed arbitrary schema.

## 5. Backend sequence and evidence

The following are candidate interfaces, not supported-version promises. Each
backend PR pins its Linux executable/runtime digest and fixture provenance.
The Windows binaries inspected here are not those Linux acceptance artifacts.
The [evidence record](../handoffs/M8-planning-evidence.md) links primary sources.

| Backend | Candidate one-shot interface | Specific trap to prove |
| --- | --- | --- |
| Claude Code | `-p`, stream JSON, partial messages, controlled tools/config, native schema option | `--allowedTools` is auto-approval, not containment; bare mode changes authentication; safe mode still has managed-policy exceptions |
| Codex | `exec --json --ephemeral`, stdin prompt, explicit sandbox/approval config, native output schema | Ignore user config is not proof that every project/managed customization is disabled; terminal usage is not served-model proof |
| Pi | `--mode json -p --no-session`, explicit tools, discovery disabled | Final message vs deltas; extension/theme/context discovery; no native schema promise inferred from JSON event output |

No adapter resumes, forks, launches background sessions, adds subagents, loads
MCP, or chooses a fallback model. Backend-internal defaults are observed only
when grants explicitly select them. The first live route for each CLI is the
same approved credential-isolated gateway posture; additional auth modes are
separate proven configurations, not a copy of the operator's desktop login.

Use real captured native transcripts where obtainable with authorized live
access, and deterministic fake-provider sessions otherwise. Label each fixture
as captured, fake-provider-produced, or synthetic adversarial. Record backend
version/content digest, generation command, platform, relevant settings,
sanitization, expected outcome, and SHA-256. Synthetic data never claims to be
an upstream recording. No credentials are required by CI, and this plan does
not authorize a paid call or the acquisition of any credential.

## 6. Reviewable implementation slices

These are separate PRs with separate acceptance evidence, not subcommits of
the former omnibus PR A. A → B → C → D → E establish the prerequisites; only
then may F → G → H offer live adapters. No intermediate slice advertises a live
WRITE configuration while repository-controlled gates still run on the host.

### PR A — contracts, coherence, and publication

Implement the complete profile/predicate, derived capability-identity contract,
descriptor coherence, schema-3 description, typed workspace seam, and the
generic post-record materialization phase. Exercise the policy with
`FakeExecutor` and a genuine unavailable-provider double; deferred-resource
doubles prove record-before-materialize, cleanup enrollment, refusal, and
legacy behavior through the walker.
Prove exact-grant refusals, descriptor disagreement, strict reader versioning,
and unchanged historical profiles/manifests. Define no OS or gateway success
by a boolean in that double. No Linux launcher, gateway, or real backend ships
in this slice; profiles remain unavailable without proved implementations.

### PR B — Linux launcher and physical containment proof

Implement the concrete launcher, deferred READ snapshots and staging,
workspace ownership, acquisition closure/guard, bounded subprocess pump, and
recorded-subprocess double. The double runs
actual hostile child processes through the production boundary, with no
external route. Demonstrate READ denial, WRITE confinement, no ambient
authority, kill-tree cleanup, owner death, closed handles, and epoch separation.

Operator provisioning from section 3.1 is a prerequisite to this PR's proof.
Record the exact image, loaded AppArmor policy, service user, runtime root,
and executable digests. Add a required Linux containment CI lane; missing
prerequisites or a skipped probe cannot count as passing. Unsupported-host
verification remains runnable and reports that containment was not exercised.
Approval requires reproducible native Linux evidence. No backend or gateway
integration is bundled into this boundary review.

Kill real hosts before recording, after recording, and during materialization.
Assert no pre-record allocation and exact post-record recovery. Pause a
producer before its guarded work and race successor reconciliation; also kill
the Python owner while its setup child retains the guard. Both orders must
leave the old acquisition closed, no resource recreated after disposal, and
the new epoch untouched. Remove each ordering/guard check independently.

### PR C — safe WRITE capture and immutable Git handoff

Implement section 4.4 independently of gate containment. This slice owns the
async workspace contract/double, contained staging operations, read-only pack
export, trusted quarantine/import, and exact candidate identity. Extend B's
same closure transaction to candidate publication/disposition. Keep all
resource ownership within the existing lease; no new durable schema or
alternate installation path. The Linux launcher is already proved by B.

Credential-free tests plant hooks, config includes, filters, fsmonitor and
credential helpers, alternate object stores, symlinked Git paths, stale locks,
and detached writers in the stage. Assert no host sentinel is read, executed,
or changed; capture either succeeds entirely inside the boundary or fails
without publishing a candidate. A valid candidate arrives byte-identically
with its exact OID and history; malformed/truncated/oversized packs and a
mismatched named OID publish nothing. Cover reset after a hostile call,
repeated cancellation, owner death, and response loss around candidate-ref
publication, including old/new epochs and counterfactual discard. Mutate
containment, immutable handoff, verification, and the live-assembly guard
independently. Existing synchronous fixtures retain their historical identity.

The closure marker is mandatory external state, not a process-local flag.
At a barrier after the old worker's ownership check, let a successor reclaim
and finish discard, then release the old publication and kill its host: Git
must refuse the late ref, with no candidate left. Prove the reverse order too:
publication wins, then closure removes it. A crash/retry of closure, exact
publication retries, release retaining a checkpointed candidate, and a fresh
epoch remain lawful. Remove the marker absence check and the transactional
candidate-absence check independently; each mutant must fail this lane.

No live WRITE profile is offered yet: contained gates in D and the gateway
in E are still prerequisites. B's hostile-child proof remains a disposable
test, not permission to run its output through legacy capture or gates.

### PR D — contain repository-controlled gates

The contained gate runner is another production consumer of the concrete
launcher, not an `Executor` wrapper or another process protocol. Separate two
phases: assembly identifies the installed check runtime; invocation checks a
candidate. Any tool-version probe runs during assembly in that pinned runtime,
with private scratch and no candidate or repository mount. It must finish
before publishing the check-set/capability revision or admitting a manifest.
That identity is independent of the candidate; checking different candidates
cannot change it. Immutable tool content, not version text alone, binds it.

Only the invocation's checks mount the prepared merge snapshot read-only.
Both phases use a clean environment and no network/provider route. Host
authority, journal, credentials, and other acquisitions remain absent. Finish
descendant cleanup before integrity verification and attestation minting; a
timeout, output bound, or teardown failure cannot produce a passed check.

The contained resource exposes `async verify(candidate) -> MergeEvaluation`.
Define this task-level gate contract in L0 as `MergeGate`, with the existing
`target_ref` property. Move the existing `MergeEvaluation` data contract there
unchanged and re-export it from its old import location; never define it twice.
The contained provider and a genuine controllable fake exercise this contract.
The process launcher remains the same concrete mechanism used by executors.

Preserve the existing synchronous `GateRunner`/`BoundGateRunner.verify` as
legacy trusted/fake-only behavior. The new provider uses the distinct
`gates.contained` capability kind and new component versions that explicitly
await `verify`; do not change a retained consumer's call convention, silently
rebind it, or return sometimes-a-value/sometimes-an-awaitable from one method.
Retained fake-only worlds keep their exact descriptors and reproduction path.
Do not adapt the blocking legacy verifier with `asyncio.run` or `to_thread`:
cancelling that wrapper would not own and quiesce its work.

The async path keeps the event loop responsive through preparation, process
execution, and cleanup. Cancellation, shutdown abandonment, or ownership loss
terminates and reaps the owned boundary, quiesces any offloaded trusted work,
releases its transient snapshot, and propagates control flow without minting
an attestation or returning successful output. Observe cancellation and check
ownership before minting. Repeated cancellation cannot interrupt cleanup.

Preserve `CheckResult`, the complete merge subject, exact-tree verification,
and journal-minted authority. Bind the contained runtime and launch law into
the new check-set/capability identity; do not rewrite historical attestations
or relabel the M3 runner as contained. The supported live assembly must refuse
an uncontained gate binding before making a live WRITE executor available.
This is L4 coherence over assembled services, not a walker rule or a search
for gates in a graph. Historical fake-only assemblies keep their stated scope.

Use a malicious staged test/plugin as the credential-free regression: it
attempts host writes, environment-secret reads, socket access, network egress,
and detached children while gating the exact prepared commit. Assert denial
and cleanup through the public async merge-evaluation path. While a check is
held at a barrier, prove heartbeats and cancellation still run, then assert
no surviving child, attestation, or successful checkpoint after cancellation
or owner death. Prove assembly needs no candidate and its identity stays fixed
across candidates. Mutate the phase separation, async cancellation boundary,
assembly guard, and gate launcher independently.
No live model is needed to close this exposure before the first adapter.

### PR E — gateway integration and conformance

Select and document the concrete externally provisioned integration. Implement
only its lease allocation/revocation binding and the namespace-local byte
bridge; exercise the same lifecycle against its genuine local fake. Keep
privileged credentials entirely host-side and prove the public placeholder,
if needed, confers no authority outside a mounted route.

Acceptance also requires the deployment-specific conformance proof in section
3.3 and its revision binding, not just the fake contract. Test the actual
gateway enforcement with controlled upstreams, including existing-stream
revocation and configuration drift. CI remains credential-free; a paid model
smoke test is not this gate. If no concrete deployment can supply the proof,
this slice is blocked and no live profile becomes available. Linux containment
and gate isolation are already proved; this review owns only routed authority.

### PR F — Claude Code, first real adapter

Add its native decoder, argv/config generation, tested exact tool-set inventory,
and the first gateway-backed configuration under READ and WRITE identities.
Run it through the same pump/lease tests using recorded output and fake-provider
sessions. Prove every discovery layer disabled and backend failures classified
honestly. Include section 3.4's actual-CLI shell-tool proof with internal
sandboxing disabled and nested launch unavailable. Real auth is an explicitly
requested local smoke test only.

Add an ordinary restart-importable acceptance component that consumes
`Executor`, not `isinstance(FakeExecutor)`. Register/promote through the control
plane. Do not modify historical component source merely to make the demo generic.
The component's ports explicitly carry the outcome when partial/failure is data;
a success-only component must refuse non-success rather than mint success output.

### PR G — Codex, the substitutability proof

Add the second native decoder/configuration and run the **same** acceptance
component and process contract. Share only mechanically identical lifecycle
code. Prove config precedence, no approval escalation, missing terminal events,
stderr saturation, schema output, and model/usage attribution with its actual
fixtures, including section 3.4's external-boundary-only shell-tool proof.
A backend-specific permission exception cannot leak into the common
grant law. Use a new capability binding, not a new orchestration API.

### PR H — Pi and integrated closeout

Add Pi's native event decoder and explicit resource-discovery controls. Prove
delta/final accounting and honest refusal of unsupported schema/tool requests.
Run the common component with each compatible executor; refusal for an
incompatible profile is part of substitutability, not a reason to weaken it.

The credential-free acceptance lane exercises READ analysis and a staged WRITE
candidate, deterministic checks, proof-gated installation, and restart recovery
through `ControlPlane`/`RunHost`. It composes safe capture from C, contained
gates from D, and the route boundary from E; it postpones none of those proofs
until closeout. Tests reassemble the lane with a legacy workspace importer
or uncontained gate runner and require refusal before any live WRITE child.

Run resume/reproduce/counterfactual cases: checkpoints prevent replay of
completed invocation computation; an interrupted CLI may be invoked again;
mutable counterfactual workspaces discard; effect adapters still simulate;
no raw CLI output can install code or mint a trusted attestation.
Model transport may still incur requests under explicit network authority;
counterfactual does not promise free or bit-identical model output.

Update current-truth architecture/contribution guidance and the implementation
record only when those slices land. M8 closure must state exactly which host,
tool sets, auth modes, and backend versions were actually proved, not merely
which CLI class names were added.

## 7. Failure proof and mutation inventory

Every row needs an observable public/OS assertion, not only a helper mock.
Use barriers and deterministic fake children rather than timing guesses.

| Boundary | Required probe |
| --- | --- |
| READ mount | Writes, chmod then write, rename, unlink, symlink traversal, subprocess writes all fail; snapshot bytes unchanged |
| WRITE scope | Own stage changes; authority refs, journal, parent checkout, sibling and previous/new epochs cannot be changed |
| Host visibility | Sentinel host home/file/socket/descriptor absent; no host proc traversal or terminal injection |
| Network none | Child and grandchild cannot reach a local sentinel server; remote-backed admission refuses before spawn |
| Network allow | Only the leased provider route is reachable; direct TCP/UDP, DNS, host loopback, redirects, CONNECT and forged upstreams fail |
| Host prerequisite | Missing/denied AppArmor attachment refuses under the service user; no global policy change or privileged fallback |
| Sandbox composition | Outer launch succeeds while nested `bwrap` is unavailable; actual Claude/Codex shell tools complete without an inner launch; incompatible effective settings refuse and outer failure starts no backend |
| Credentials | Provider/gateway sentinel secrets never reach the child/bridge; public placeholder cannot authorize outside its mounted route |
| Gateway conformance | The selected deployment rejects hostile routing/auth requests, closes expired/revoked streams, and refuses effective-policy drift; fake-only evidence cannot enable it |
| Config discovery | Malicious host/project/local/managed hook, plugin, MCP and extension fixtures do not execute |
| Tool narrowing | Empty and supported exact sets work; unknown, wildcard, prefix, and unsupported subsets refuse before spawn |
| Profile coherence | Lying descriptor, changed profile, missing provider, false leased flag, or unavailable host refuses |
| Runtime identity | Same version text with changed executable/config/decoder bytes cannot keep the admitted revision |
| Workspace admission | `None`, fabricated path/view, wrong posture/provider/run/epoch, and closed handle refuse before child start |
| Argv | Leading dashes, quotes, Unicode, stdin payload and embedded newlines remain data |
| Context | Wrong GitRef, path escape, digest/size mismatch, and unassembled ArtifactRef resolver refuse without locator fetching |
| Stream | Split UTF-8, duplicate/non-finite JSON, corrupt middle record, unknown semantic event, and missing terminal demote |
| Precedence | Success marker plus nonzero exit fails; success after corruption stays partial; timeout salvages text |
| Bounds | One huge line, many small lines, stderr saturation and a blocked stdin cannot deadlock or allocate unboundedly |
| Telemetry | Requested-but-unobserved model stays `None`; cumulative usage is not added twice; estimates do not become billing facts |
| Descendants | `setsid`, double-fork, ignored TERM, and held pipe descriptors do not survive return/cancel/deadline |
| Allocation | No persistent work before the lease row; death during materialization leaves an exactly recoverable row; recording/materialization failure preserves cleanup and legacy behavior |
| Allocation race | Close a never-started or partly materialized acquisition while an old producer is paused; no late local creation or gateway allocation; child-owned guard outlives Python death; new epoch untouched |
| Owner death | Kill the host before/after lease recording and after spawn; no CLI survives the proved parent-death chain |
| Repeated cancellation | Cleanup completes once, cancellation propagates, and no false successful checkpoint is written |
| Recovery | Restart with a new owner; only stale owned resources are reaped; current epochs and PID reuse are safe |
| WRITE completion | No descendant can mutate candidate bytes after executor return or while gates attest them |
| WRITE capture | Hostile Git metadata is read only inside containment; immutable pack handoff preserves exact OID/history; malformed objects, dependency fetching, wrong OID, or cancellation publish no candidate |
| Capture recovery | Reset/capture never use host Git against a dirty stage; both publication-vs-closure orders, closure crash/retry, response loss, and stale epochs obey the existing disposition; a closed acquisition can never publish late |
| Gate containment | Repository-controlled checks cannot access host authority, secrets, sockets, or network; detached children die before attestation; uncontained assembly refuses live WRITE |
| Gate phases | Contained runtime probing completes before admission with no candidate mount; check identity is candidate-independent; only actual checks mount the prepared snapshot |
| Gate cancellation | A blocked async check permits heartbeat/cancellation delivery; cancellation and ownership loss quiesce work before cleanup returns and produce no attestation/checkpoint; legacy synchronous consumers remain compatible |
| Command law | Existing plan/domain/completion response-loss probes remain green; no new mutation bypass |
| Compatibility | Pre-M8 manifests and absent profile fields retain exact bytes/digests; synchronous workspace/gate consumers keep their contracts; v2 description reader rejects v3 |
| Integration | Three compatible adapters run one component; incompatible profiles refuse; deterministic effect is the sole install path |

Mutation inventory must remove each enforcement boundary independently:
read-only mount, root visibility restriction, network isolation, descriptor
comparison, revision input, tool-set check, environment filter, final-status
check, damage latch, byte bound, usage accounting, process-tree teardown,
epoch check, staging-Git containment, pack verification/candidate publication,
record-before-materialize, cleanup enrollment, child-owned allocation guard,
acquisition-closure transaction and absence checks, remote close-by-key,
workspace/gate coherence,
host-policy prerequisite, gateway
deployment-evidence binding, route revocation, and controlled no-nesting
configuration. A collection error, timeout of the test harness, or incidental
failure is not a killed mutant. If a guard cannot be independently pinned,
record its actual defensive strength rather than crediting another test.

## 8. Compatibility, publication, and gate

This planning PR changes no source, tests, workflow, schema, or accepted ADR.
Implementation preserves Graph/admission schema 1, manifest schemas 2/3, and
SQLite 7. The public schema change is `SystemDescription` 3 and
description digest domain 3 for complete live grant policy. Old profile
serialization omits absent policy; old manifests are not rehashed.
Git additionally retains the acquisition-closure markers defined in section
4.4. That external lifecycle change is explicit; no existing candidate,
effect-marker, or historical attestation is rewritten.

A pre-M8 profile remains readable but cannot establish a new live executor's
M8 eligibility. The historical fake path retains its exact behavior/revision
for retained worlds; do not invent compatibility with an unrecorded live
writer. Changing a real launch configuration creates a new capability revision.
Reproduce on a host without the old immutable runtime refuses rather than
substituting the current installation.

For each implementation PR: local `uv run verify` on the exact head, required
CI, the slice's explicit physical/transcript tests, mutation inventory, base
compatibility reproduction, and adversarial review. Reproduce findings before
accepting or refuting them. Repeat confirmation after fixes on the new head.
Passing the current 1,531-test baseline establishes none of the new OS claims.

New interfaces need a named second implementation or genuine test double.
Kernel dependencies remain stdlib + Pydantic. Runtime imports L0 contracts,
never substrate. One subprocess owner and one bounded pump serve real users;
do not create a generic runner framework, shared-private catch-all, policy
mini-language, or mirrored registry to make the file tree look symmetrical.

## 9. Decisions requested

1. Accept the Linux-first physical boundary and unsupported native-host policy,
   with explicit operator provisioning, no global AppArmor relaxation, and
   backend OS sandboxing disabled only inside the mandatory outer boundary.
2. Accept gateway-only initial authentication; do not promise subscription
   login until a supported credential-isolated mode is proved.
3. Accept finite supported tool sets, explicit remote-network grants, and
   description schema 3 rather than silently enriching schema 2.
4. Accept eight separately reviewed slices: contracts → Linux containment →
   safe WRITE capture → gate containment → gateway conformance → Claude Code →
   Codex → Pi/closeout. Capture, gates, and the selected deployment's route
   must all be proved before the first live WRITE profile is available, not
   merely before milestone closure.

These are proposals, not decisions made by merging a draft. Approval without
redlines freezes this revision and accepts ADR 0018 explicitly. Approval with
redlines produces a successor revision; pre-decision review edits may iterate
this draft. An implementation discovery requiring a different host boundary,
credential model, durable schema, or task seam returns to planning first.
