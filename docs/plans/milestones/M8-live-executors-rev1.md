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
| `core/workspace.py` | `WorkspaceView`, `WriteWorkspace`, invocation leases | Reuse workspace and acquisition identities |
| `runtime/walker.py` | Acquire → durable lease → invoke → close; checkpoint recovery | No backend-specific scheduling or session recovery |
| `substrate/executors/fake.py` | The only current executor | Preserve the fake and add a genuine subprocess test double |
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

No installer silently enables user namespaces, changes AppArmor policy, starts
a privileged service, or installs a distribution. Provisioning is an explicit
operator action. A host failing prerequisites is unavailable with a repair
reason, not a degraded live backend.

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

### 3.3 Environment, authentication, and configuration

Construct the child environment from scratch. The grants' allowlist selects
which approved host values may be inherited; it is not permission to inherit
the rest. Fixed sandbox-local `HOME`, `PATH`, locale, and backend config paths
come from the launch recipe, not the host's values. Loader/interpreter injection,
host auth, git helpers, and endpoint-routing variables cannot arrive through
an ordinary environment grant. Unsupported names are refused, not ignored.

The proposed initial auth mode is a provisioned provider gateway with an
invocation-scoped credential. The actual provider/account secret stays outside
the child. The delegated credential is intentionally available to the whole
invocation and authorizes only the configured native provider route during
its lifetime. Revoke it on close, cap its lifetime at the granted deadline,
and refuse cross-invocation reuse. Host death must not leave indefinite access.

Provision an acquisition-specific Unix-domain route socket outside the
namespace; mount only that endpoint, not its parent or a general gateway
control socket. An invocation-owned loopback byte bridge inside the namespace
connects that endpoint to the CLI's native HTTP base URL. It performs no HTTP
policy, provider translation, credential issuance, or routing selection. The
external gateway owns all route/auth enforcement. The bridge is a concrete
subprocess detail with all three CLIs as consumers, not a new public protocol.
It is killed with the invocation and exists only for `network="allow"`.

The gateway must not offer arbitrary CONNECT, client-selected upstreams,
redirects to unapproved origins, admin routes, or account mutation. Prove its
route, expiration, and revocation properties with a local fake service. Tokens
must be unguessable, never used as identity digests, and absent from argv,
public metadata, logs, and recorded fixtures. The child can already use its
token; do not call this protection of a token from its holder.

Route allocation/revocation uses the gateway's trusted provisioning interface
from the executor lease provider, never an interface mounted into the child.
Its handle belongs to the existing acquisition, is idempotently closed, and
expires without a live host. The configured integration must supply a genuine
fake implementation exercising the same lease contract; no generic gateway
manager or second durable store is introduced. A socket path is a locator,
not evidence of ownership; a stale acquisition cannot revoke a newer route.

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
4. provider-route and credential-delegation policy, excluding credential values.

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

Use the existing `LeasedCapability` protocol for live providers. `acquire`
allocates a bounded resource handle and binds `LeaseContext`; it does not
launch the untrusted CLI. The walker records the capability lease before
passing its acquired `Executor` to component code. A bound executor rejects
grants differing from that acquisition's sealed grants.

Retype `Executor.execute(workspace=...)` to `WorkspaceView | None`, using the
existing `WriteWorkspace` for a WRITE acquisition. No caller-authored string,
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

Namespace-private scratch dies with its processes. Any host-side resource
allocated before the durable lease must be either immediately cleaned on
failure or recoverable by exact acquisition identity. Add process-death probes
on both sides of allocation and lease recording. No new persistent process
ledger is needed; if the chosen launch mechanism makes one necessary, stop
and revise this decision rather than introducing it under a helper name.

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

### 4.4 Task data and observation

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

### PR A — launch law and hostile subprocess proof

Implement the complete profile/predicate, derived live capability identity,
descriptor coherence, schema-3 description, typed workspace seam, leased
READ snapshots, and one concrete Linux launcher. Add the recorded-subprocess
test double and bounded stream runner. No real backend is offered yet.

The test double runs actual child processes through the production launch
boundary. Demonstrate READ denial, WRITE confinement, no ambient authority,
exact-grant refusals, kill-tree cleanup, owner death, closed-handle rejection,
epoch separation, and unchanged historical manifests. Add a required Linux
containment CI lane with explicit prerequisites; no skip may count as proof.
Ordinary unsupported-host verification remains runnable and reports that
containment was not exercised.

This slice also specifies and exercises the gateway contract against a local
fake service. It does not implement a production gateway or enable a live
route. If the proposed deployment cannot provision one, surface that before
PR B. Approval of A requires reproducible native Linux containment evidence.

### PR B — Claude Code, first real adapter

Add its native decoder, argv/config generation, tested exact tool-set inventory,
and the first gateway-backed configuration under READ and WRITE identities.
Run it through the same pump/lease tests using recorded output and fake-provider
sessions. Prove every discovery layer disabled and backend failures classified
honestly. Real auth is an explicitly requested local smoke test only.

Add an ordinary restart-importable acceptance component that consumes
`Executor`, not `isinstance(FakeExecutor)`. Register/promote through the control
plane. Do not modify historical component source merely to make the demo generic.
The component's ports explicitly carry the outcome when partial/failure is data;
a success-only component must refuse non-success rather than mint success output.

### PR C — Codex, the substitutability proof

Add the second native decoder/configuration and run the **same** acceptance
component and process contract. Share only mechanically identical lifecycle
code. Prove config precedence, no approval escalation, missing terminal events,
stderr saturation, schema output, and model/usage attribution with its actual
fixtures. A backend-specific permission exception cannot leak into the common
grant law. Use a new capability binding, not a new orchestration API.

### PR D — Pi and integrated closeout

Add Pi's native event decoder and explicit resource-discovery controls. Prove
delta/final accounting and honest refusal of unsupported schema/tool requests.
Run the common component with each compatible executor; refusal for an
incompatible profile is part of substitutability, not a reason to weaken it.

The credential-free acceptance lane exercises READ analysis and a staged WRITE
candidate, deterministic checks, proof-gated installation, and restart recovery
through `ControlPlane`/`RunHost`. Gates executing repository-controlled code
must use the same proved process boundary before this lane claims adversarial
end-to-end containment; existing unsandboxed gate runners remain explicitly
outside that claim until integrated here. They are a genuine additional
consumer of the concrete process launcher, not a second executor protocol.

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
| Credentials | Unrelated sentinel secrets never reach argv/env/files/output; scoped token cannot use another route or survive expiry/revocation |
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
| Owner death | Kill the host before/after lease recording and after spawn; no CLI survives the proved parent-death chain |
| Repeated cancellation | Cleanup completes once, cancellation propagates, and no false successful checkpoint is written |
| Recovery | Restart with a new owner; only stale owned resources are reaped; current epochs and PID reuse are safe |
| WRITE completion | No descendant can mutate candidate bytes after executor return or while gates attest them |
| Command law | Existing plan/domain/completion response-loss probes remain green; no new mutation bypass |
| Compatibility | Pre-M8 manifests and absent profile fields retain exact bytes/digests; v2 description reader rejects v3 |
| Integration | Three compatible adapters run one component; incompatible profiles refuse; deterministic effect is the sole install path |

Mutation inventory must remove each enforcement boundary independently:
read-only mount, root visibility restriction, network isolation, descriptor
comparison, revision input, tool-set check, environment filter, final-status
check, damage latch, byte bound, usage accounting, process-tree teardown, and
epoch check. A collection error, timeout of the test harness, or incidental
failure is not a killed mutant. If a guard cannot be independently pinned,
record its actual defensive strength rather than crediting another test.

## 8. Compatibility, publication, and gate

This planning PR changes no source, tests, workflow, schema, or accepted ADR.
Implementation preserves Graph/admission schema 1, manifest schemas 2/3, and
SQLite 7. The one planned publication change is `SystemDescription` 3 and
description digest domain 3 for complete live grant policy. Old profile
serialization omits absent policy; old manifests are not rehashed.

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

1. Accept the Linux-first physical boundary and unsupported native-host policy.
2. Accept gateway-only initial authentication; do not promise subscription
   login until a supported credential-isolated mode is proved.
3. Accept finite supported tool sets, explicit remote-network grants, and
   description schema 3 rather than silently enriching schema 2.
4. Accept A → B → C → D, with physical containment required before offering
   a real executor and the existing gate runner included before claiming
   adversarial end-to-end WRITE acceptance.

These are proposals, not decisions made by merging a draft. Approval without
redlines freezes this revision and accepts ADR 0018 explicitly. Approval with
redlines produces a successor revision; pre-decision review edits may iterate
this draft. An implementation discovery requiring a different host boundary,
credential model, durable schema, or task seam returns to planning first.
