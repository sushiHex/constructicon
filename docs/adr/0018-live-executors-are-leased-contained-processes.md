# 0018 — Live executors are leased, contained processes

**Status:** proposed (M8); not accepted and not authority to implement

## Context

ADRs [0005](0005-executor-seam.md), [0008](0008-isolation-admission.md), and
[0009](0009-git-authority.md) already decide the task-shaped executor seam,
admission-time isolation, and separate staging repositories. M8 must realize
those decisions, not reopen them. A CLI tool allowlist is not a filesystem
boundary, a process group is not ownership of escaped descendants, and
permission bits do not contain hostile same-user code.

At the M7.1 closure, only `FakeExecutor` exists. `IsolationProfile` describes
enforcement but does not establish it. A capability revision is an arbitrary
string, and executor descriptor/live-object coherence is not checked like
channel coherence. The launch workspace is still typed `object | None`.
These are the specific seams M8 needs to close.

## Proposed decision

### One supported boundary first

The initial live host is a dedicated Linux execution environment with a
tested bubblewrap installation and user, mount, PID, IPC, and network
namespace support. Windows and macOS retain the credential-free executor
suite, not a claim of native live containment. WSL2 is eligible only after
the same Linux probes pass; its presence alone establishes nothing. The
control process, journal, authority repository, and acquisitions live in that
Linux environment. M8 adds neither remote dispatch nor a Windows path bridge.

The proposed Ubuntu 24.04 image needs an operator-approved, loaded AppArmor
profile permitting the pinned launcher under the actual service user. Image
provisioning is explicit and separately reviewed. Constructicon never adjusts
host security policy; disabling the global user-namespace restriction, running
as root, or selecting a privileged fallback is not a supported repair. A
distribution label or profile file alone is not containment evidence.

The substrate launches the **whole CLI**, not only commands the CLI labels
as shell tools, inside its own boundary. It supplies a small, immutable
runtime root and one acquired workspace. READ exposes that workspace through
a read-only mount; WRITE exposes only the separate staging acquisition as
writable persistent storage. Private temporary storage is disposable and is
not another host workspace. Authority repositories, journal files, host homes,
service sockets, inherited descriptors, and sibling acquisitions are absent.

The launcher owns a fresh PID namespace and parent-death chain. Completion
includes terminating and reaping descendants, including ones that change
session or process group. Backend cancellation is not the proof. Namespace
support, effective mounts, and safe process cleanup are tested prerequisites;
failure refuses availability or launch, never selects an unsandboxed fallback.
Host-kernel compromise and resource-denial resistance are not claimed.

### Existing capabilities carry the lifecycle

A live executor provider uses `LeasedCapability`. Its acquisition returns a
bound `Executor` with the invocation's existing lease/acquisition identities
and sealed grants. `execute()` remains task-shaped; its workspace becomes
`WorkspaceView | None`, not a path string or a new workspace abstraction.
The provider closes and reconciles its own resources through the existing
lease law. It starts no CLI before the acquisition is durably recorded.
No executor journal, session scheduler, or backend conversation recovery is
introduced. Uncheckpointed computation may run again; model charges are not
claimed to be exactly once.

Each live READ/WRITE configuration has a separate capability identity and
profile: the existing single filesystem posture cannot truthfully describe
both at once. A canonical, secret-free launch identity determines the
capability revision. It covers the runtime and CLI content digests, decoder
revision, isolation recipe, grant policy, and provider-route policy. Assembly
derives the descriptor from that object and refuses mismatches. Activation
checks the sealed revision; the substrate rechecks availability before launch.
No absolute host path, credential, PID, or acquisition nonce enters the digest.

### Grants and credentials are explicit

One L0 policy predicate supplies both admission and `validate_grants`.
Complete live profiles state which exact tool sets, network modes, and
inherited environment names they support. Unsupported narrowing is a refusal,
not a closest match. An empty tool grant means no model-callable tools.
Tool names describe harness operations, not permitted shell command prefixes;
OS containment still bounds their effects.

`network="none"` means no networking by the CLI or its descendants, including
model access. The initial remote-backed profiles therefore require `allow`,
but expose only one leased provider route inside a private network namespace.
The profile publishes that additional restriction. No host-network sharing,
backend-default exception, or hidden provider bypass is introduced. Generic
network tools are not offered; shell commands cannot bypass simulated effect
adapters with independent outbound requests.

The proposed first authentication mode uses a narrowly scoped, externally
provisioned provider gateway. Provider and gateway credentials stay outside
the CLI, its bridge, its environment, its home, and its descendants. The
invocation receives authority through possession of one mounted route, not a
bearer secret it could encode into output or a candidate. A backend may use a
fixed public API-key placeholder only if it grants no authority outside that
route. Hostile code can use the route during its authorized lifetime; no
promise of model-usage isolation within the invocation is made. There is no
ambient host-login reuse or reliance on redaction to contain a known secret.

The route is reached through one acquisition-specific socket and an
invocation-owned loopback byte bridge, not a host TCP listener shared with
other services. The bridge carries native bytes and has no provider policy.
The gateway is an environment prerequisite, not a new Constructicon model
provider API: backend requests and responses retain their native protocol.
Constructicon neither translates completions nor builds account-login,
credential-refresh, or general HTTP-proxy infrastructure. The route supplies
upstream authentication host-side; child-supplied headers cannot redirect it
or expose its credentials. Revocation and expiry close existing streams as
well as refusing new ones. The trusted provisioning interface is never mounted.

The fake service proves the allocation/revocation contract, not production
enforcement. Before any live profile is available, the operator must select
a concrete integration and provide conformance evidence against its deployed
build and effective route/auth policy, using controlled upstreams without
paid calls. The build, configuration, policy, and conformance suite revision
participate in capability identity. Assembly and allocation refuse an
unproved or drifted deployment; a route pins that policy for its lifetime.
No deployment is selected or proved by this proposal. Gateway conformance is
a separate blocking implementation slice, not an optional model smoke test.

Subscription authentication remains a separately gated mode:
if it needs a raw reusable account secret in an untrusted child, it is not
eligible under this decision. Owner acceptance of this limitation is required.

### Contain checks before offering live WRITE

The M3 gate runner currently executes repository-controlled code in host
subprocesses with inherited environment. Containing the model while leaving
its generated tests uncontained would reopen the same host authority at the
next step. M8 accepts no such rollout window.

Before a live WRITE profile is available, gates use the same concrete launcher
over the prepared merge snapshot, with private scratch, a pinned runtime,
clean environment, and no network or provider route. They finish descendant
cleanup before integrity checks and attestation minting. The live assembly
refuses uncontained gate bindings. The launcher has a genuine second consumer;
gates do not become model executors, and the walker gains no gate policy.
Existing check results, exact merge subjects, and journal-minted authority
remain the contracts. Historical fake-only assemblies are not relabeled as
contained, and historical attestation identities are not rewritten.

### Published evolution is explicit

`ExecutorProfile` gains one optional, versioned `grant_policy` contract. `None`
means historical incompleteness, not permission to launch a live backend.
The absent field remains absent in old profile serialization. The richer
description is published as `SystemDescription` **3**, with description digest
domain 3, so version-2 readers refuse rather than lose the new policy.

Graph and admission schemas remain 1, manifest schemas remain 2/3, and SQLite
remains 7: launch identity fits the existing capability revision, and resource
ownership fits the existing lease. Historical manifests and profiles are not
rewritten or silently bound to a newly installed executable. A necessary new
durable field would require a successor decision before its implementation.

### Observation is not authority

One bounded subprocess pump serves backend-specific incremental decoders.
Malformed, truncated, contradictory, or unrecognized semantic records cannot
be promoted to success by a later success marker. A nonzero exit and a timeout
remain failures with salvaged observations. Requested model is not served
model; provider estimates are not measured billing. Existing outcome types
remain the public executor contract. There is no universal backend event bus.

## Alternatives rejected

- Native Windows and Linux containment in the first slice: doubles the
  unproved physical boundary before one implementation exists.
- Trusting backend flags or read-only file attributes as the substrate proof.
- Using a new container daemon, scheduler, or durable executor ledger when
  namespaces, the existing host, and invocation leases have the required roles.
- Giving the child host login files or broadly privileged provider keys and
  describing their presence as an environment allowlist.
- Implementing our own completion gateway or a generic provider SDK (ADR 0005).
- Persisting backend session ids as resume authority instead of checkpoints.
- Updating current-truth architecture documents before these guarantees exist.

## Consequences and approval

The [M8 plan](../plans/milestones/M8-live-executors-rev1.md) defines the
implementation slices and failure proof; the
[evidence record](../plans/handoffs/M8-planning-evidence.md) distinguishes
observed interfaces from proposed guarantees. Linux-first support and the
gateway-only initial auth posture are owner decisions, not inferred consent.

Accepting this ADR approves those boundaries, not the claim that bubblewrap,
an installed CLI, or a green transcript suite has already proved containment.
Separate slices establish contracts, Linux containment, gate containment,
and deployed gateway conformance before the Claude Code, Codex, and Pi slices.
Each proof has its own acceptance gate; none inherits credit from the other
or from documentation. M7.1's scoped-out provenance and human timeout work
stays separate.
