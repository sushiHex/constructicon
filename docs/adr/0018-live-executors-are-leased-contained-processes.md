# 0018 — Live executors are leased, contained processes

**Status:** accepted (M8), 2026-09-09; implementation proofs remain required

## Decision record

The owner delegated completion of the review, design acceptance, and planning
merge in this session: "continue with 1-4. make utterly elegant design
decisions." The technical proposal at `8f0c2e5bc3be2b39fe63a120ce43eefc00e0b02d`
passed exact-head confirmation, CI, and the local 1,531-test baseline. This
record accepts its Linux-first boundary, gateway-only initial authentication,
complete finite grant policy, description schema 3, and eight separately gated
implementation slices. It does not claim the owner independently reviewed
that exact commit or that baseline tests prove M8 behavior.

The reviewed [rev-1 plan](../plans/milestones/M8-live-executors-rev1.md) is
frozen byte-for-byte. Its pre-decision draft wording is historical; this ADR
and the planning index record its approval. PR A may implement the accepted
contracts; each later slice still requires its own proof. No Linux target or
production gateway has been selected here. Installing a distribution, changing
operator security policy, acquiring credentials, or making paid requests
requires separate explicit direction, not this design acceptance.

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

## Decision

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
The proof records the actual mount/FD/UID map, including private `/proc`,
absent `/sys`, minimal private `/dev`, and private mount propagation. There
is no optional namespace fallback. No general seccomp policy is selected;
`no_new_privs` does not imply one. A hostile invocation can exhaust this
dedicated runner; stronger VM/cgroup availability isolation is separate
operator work, not an inferred guarantee.

The initial recipe has one OS-isolation owner: Constructicon. It disables
the CLI's internal sandbox through controlled, revision-bound configuration;
it never depends on permission to create a second namespace boundary. Prove
actual backend shell-tool execution on the selected image with nested
`bwrap` unavailable. Tool allowlists and approval policy remain separate.
An incompatible pinned backend or managed requirement refuses availability;
there is no weakened nested mode, host-policy relaxation, or direct-host
fallback. The outer launcher must pass a bounded benign availability probe
and refuse setup failures before it starts any backend. These decisions do
not change the operator's CLI settings or claim nested behavior was tested
in this planning session.

### Existing capabilities carry the lifecycle

A live executor provider uses `LeasedCapability`. Its acquisition returns a
bound `Executor` with the invocation's existing lease/acquisition identities
and sealed grants. `execute()` remains task-shaped; its workspace becomes
`WorkspaceView | None`, not a path string or a new workspace abstraction.
The provider closes and reconciles its own resources through the existing
lease law. M8 `acquire` is inert: it returns the handle and its complete
recovery reference before creating persistent resources. An optional L0
`AcquiredCapability.materialize` async callback supplies one generic phase:
record the lease, enroll the acquisition in cleanup, await materialization,
then expose the resource. The default absent callback preserves legacy
provider behavior, not a claim that eager legacy allocation is crash-safe.
Real providers and deferred-resource doubles exercise the same lifecycle.

All persistent resources, including later snapshots and quarantines, are
owned by the predetermined root/key in that durable row. The callback cannot
change its identity or recovery reference. Before recording there is no
persistent allocation; after recording, recovery can dispose even a partially
materialized or never-started acquisition. No cleanup-only `finally` is
credited with surviving process death.

Closing a local handle that never entered materialization is non-persistent:
mark it locally closed, refuse later materialization, and create no external
marker, guard, or gateway tombstone. This preserves the walker's cleanup call
when recording fails without allocating unrecorded state through cleanup.
Materialization marks entry before its first await/I/O; after entry, close
uses the full physical fence. Reconciliation has a different input, a durable
row: it always fences even an absent resource, since it cannot trust an old
process's local phase. Legacy eager-provider cleanup remains unchanged.

Git-backed acquisitions use the closure marker below and one acquisition
file lock for physical creation/use/removal. Producers check closure under
the lock before touching resource paths. Disposal commits closure, waits for
guarded work to quiesce, and then removes the payload resources. The trusted
launcher holds the guard through actual subprocess lifetime, not merely its
parent coroutine; the untrusted payload receives no guard descriptor. Linux
death/race probes must prove this, including setup. Initial M8 retains guard
inodes with closure markers rather than allowing old waiters and replacement
inodes to disagree. The lock serializes work; the marker revokes it; neither
decides lease disposition or replaces the journal's recovery inventory.
Remote allocation uses the gateway's native close-by-key fence instead.
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

The initial authentication mode uses a narrowly scoped, externally
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
It holds no workspace descriptor; the endpoint rejects ancillary FD passing.
The initial CLI-to-bridge leg is private-loopback plaintext HTTP, with
upstream TLS at the external gateway. An incompatible CLI is unavailable,
not a reason to add TLS interception or a general proxy. Each pinned backend
must inventory all egress attempts and prove denied auxiliary traffic does
not break the supported operation; a model base URL alone is not that proof.
The gateway is an environment prerequisite, not a new Constructicon model
provider API: backend requests and responses retain their native protocol.
Constructicon neither translates completions nor builds account-login,
credential-refresh, or general HTTP-proxy infrastructure. The route supplies
upstream authentication host-side; child-supplied headers cannot redirect it
or expose its credentials. Revocation and expiry close existing streams as
well as refusing new ones. The trusted provisioning interface is never mounted.

Before allocation, the existing durable lease records a non-secret allocation
key derived from its acquisition identity and epoch. Gateway allocation and
closure are idempotent by that key; closure permanently refuses late allocation
even when no route existed. An absent lookup alone is not closure. The
server-minted route id belongs to the live handle and is recoverable by key
after response loss, without a second journal phase. The gateway associates
each request/stream with its server-owned lease, never client identity, peer
UID, or a reusable socket path. Its clock enforces expiry after host death;
the maximum orphan window is the remaining granted lifetime. No second
Constructicon route ledger is introduced.

The fake service proves the allocation/revocation contract, not production
enforcement. Before any live profile is available, the operator must select
a concrete integration and provide conformance evidence against its deployed
build and effective route/auth policy, using controlled upstreams without
paid calls. The build, configuration, policy, and conformance suite revision
participate in capability identity. Assembly and allocation refuse an
unproved or drifted deployment; a route pins that policy for its lifetime.
No deployment is selected or proved by this decision. Gateway conformance is
a separate blocking implementation slice, not an optional model smoke test.

Subscription authentication remains a separately gated mode:
if it needs a raw reusable account secret in an untrusted child, it is not
eligible under this decision. Owner acceptance of this limitation is required.

### Contain mutable Git before importing its candidate

ADR 0009's staging repository stays a repository: the agent may commit and
move its refs. But local Git config, hooks, filters, helpers, and object-store
locators are hostile data. Every operation that interprets mutable staging
metadata runs inside the same proved launcher, including reset, candidate
capture, and export. A denylist of Git execution knobs is not the boundary.

After the model's writers are reaped, contained capture resolves the exact
candidate. After capture's writers are reaped, a read-only contained export
emits a bounded self-contained Git pack. Trusted import receives immutable
bytes, not a staging path, refspec, or command stream. A fresh trusted
quarantine verifies object format, hashes/types, closure, and the exact OID,
with no lazy fetch, copied local configuration, or alternate object store.
Only verified objects cross into the authority under its existing write-once
candidate ref. The candidate's OID/history and the sole attested install
transaction remain unchanged. The temporary quarantine belongs to the
existing acquisition, not a new durable authority or an attestation service.

The contained resource exposes L0 `AsyncWriteWorkspace`: the existing
`WorkspaceView` plus async `reset_to` and `commit_all`, with unchanged value
contracts. Its contained provider and a controllable fake exercise it.
`workspace.contained` and new awaiting component versions distinguish it
from the historical synchronous `WriteWorkspace`; the latter stays legacy.
Cancellation/ownership loss quiesces work before returning, and is observed
before candidate publication. That check alone cannot fence a later Git
write. Reuse one immutable acquisition-closure ref, established with deferred
resource allocation, derived from the existing epoch-specific acquisition id
and pointing to a fixed empty-blob sentinel in the authority's object format.
The value is independent of base, candidate, and invocation observations;
closure ensures that constant object exists before its ref transaction.
Read marker refs literally and require the exact sentinel, not through the
existing commit-peeling lookup; unexpected values or symbolic refs fail
closed. Marker transactions do not follow symbolic refs. A gate still prepares
against the actual current base at verification time, not a base pinned early
to make recovery possible. Its recovery reference never needs that subject.
Publication atomically verifies this marker's absence and creates/verifies
the exact candidate. Close/reconcile atomically creates/verifies the marker
and retains or CAS-deletes/verifies absence of the candidate according to the
existing lease disposition. Contention retries the whole ref transaction.

Publication either precedes closure and is disposed as required, or is
refused after closure. Reconciliation cannot complete before this external
fence commits; a dead old host cannot publish behind it. This is not an atomic
transaction with SQLite ownership transfer, nor a new disposition authority.
The marker never reopens and has no initial GC, because deleting it would
permit a late writer. This explicitly extends ADR 0009's Git lifecycle facts;
existing candidate/effect identities and the SQLite schema stay unchanged.
No blocking-importer thread wrapper or new persistent process ledger is
introduced.

### Contain checks before offering live WRITE

The M3 gate runner currently executes repository-controlled code in host
subprocesses with inherited environment. Containing the model while leaving
its generated tests uncontained would reopen the same host authority at the
next step. M8 accepts no such rollout window.

Before a live WRITE profile is available, safe candidate capture is required
and gates use the same concrete launcher
over the prepared merge snapshot, with private scratch, a pinned runtime,
clean environment, and no network or provider route. They finish descendant
cleanup before integrity checks and attestation minting. The live assembly
refuses legacy workspace capture and uncontained gate bindings. The launcher
has genuine additional consumers; gates do not become model executors, and
the walker gains no gate policy.
Existing check results, exact merge subjects, and journal-minted authority
remain the contracts. Historical fake-only assemblies are not relabeled as
contained, and historical attestation identities are not rewritten.

Runtime identity is an assembly fact, not a candidate observation. Contained
tool-version probes have no candidate mount and complete before publishing
the check-set/capability revision. The prepared merge snapshot exists only
at invocation time and is mounted only for the checks themselves.

Contained gates have an async `MergeGate.verify` contract in L0, exercised by
the contained provider and a controllable fake. `MergeEvaluation` remains one
unchanged data contract, re-exported at its old import path. The existing
synchronous gate resource remains explicitly legacy; a new `gates.contained`
kind and new awaiting component versions keep the two call conventions
unambiguous. There is no blocking-verifier thread wrapper or change to
retained consumer definitions. The async path delivers cancellation and
ownership loss while a check runs, finishes resource cleanup, and observes
control flow before minting; it cannot turn cancelled work into authority.

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

## Consequences

The [M8 plan](../plans/milestones/M8-live-executors-rev1.md) defines the
implementation slices and failure proof; the
[evidence record](../plans/handoffs/M8-planning-evidence.md) distinguishes
observed interfaces from unimplemented guarantees. The decision record above
accepts Linux-first support and gateway-only initial authentication; it grants
no implicit provisioning authority.

Accepting this ADR approves those boundaries, not the claim that bubblewrap,
an installed CLI, or a green transcript suite has already proved containment.
Separate slices establish contracts, Linux containment, safe WRITE capture,
gate containment, and deployed gateway conformance before the Claude Code,
Codex, and Pi slices.
Each proof has its own acceptance gate; none inherits credit from the other
or from documentation. M7.1's scoped-out provenance and human timeout work
stays separate.
