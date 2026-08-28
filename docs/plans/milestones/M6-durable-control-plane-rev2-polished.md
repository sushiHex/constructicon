# M6 — durable control plane over MCP (rev 2, polished)

## Context

M1–M5 are merged and green. M5 completed the agent authoring contract: strict
Graph JSON, one validator, `system.describe()`, typed repair faults,
restart-safe SDK tasks, and identical manifest identity across SDK, direct, and
architect-authored Graphs.

M6 adds the v1 operational front door without adding a second control model.
The frozen milestone requires authenticated actors, caller idempotency keys on
every mutation, bounded pages, stable cursors, detail by reference, conflict
results, promotion/rollback, counterfactual runs, and response-loss tests proving
retries create no duplicate runs, approvals, or promotions.

The implementation targets the official MCP Python SDK v2 stable line and the
2026-07-28 protocol revision. MCP is an optional L4 dependency; no `mcp` import
may appear in core, substrate, runtime, or SDK.

> **MCP is a transport. Constructicon owns the control plane.**

## Conceptual kernel

```text
Actor       who is asking
Command     one durable mutation intent
Run         long-lived work
Reference   bounded access to immutable detail
```

Pages are projections. Cursors continue projections. MCP carries these objects;
it never redefines them.

## Acceptance criterion

An authenticated actor can connect over stdio or Streamable HTTP, inspect M5's
authoring contract, submit a Graph, receive a durable `RunId` immediately, page
through status and events, cancel/resume/reproduce/counterfactually replay a
run, record a human decision, and promote or roll back a component.

Every mutation requires a caller idempotency key. Constructicon claims the
command before planning or mutating, stores an immutable operation plan before
the first domain write, reconciles interruption from durable domain facts, and
stores the exact terminal response. Repeating the same actor, operation, key,
and request returns that response; reusing the key with different arguments is
a typed conflict and performs nothing.

Counterfactual runs pin the source world except for explicit exact-version
overrides, call no live external effect, use a distinct simulated-effect identity
namespace, and discard every leased mutable resource. All responses are bounded;
full immutable detail remains available by reference.

Pinned assertions:

```text
one transport-neutral ControlPlane
one RunId for long-running work
one command ledger for every mutation
one actor contract, never an actor tool argument
one cursor codec
one detail-reference vocabulary
one MCP adapter over ControlPlane
zero MCP imports below L4
zero duplicate mutation after response loss
zero live external effect in a counterfactual run
```

## 0. Decisive rulings

### 0.1 MCP adapts `ControlPlane`

M6 adds a transport-neutral L4 `ControlPlane`. It owns authorization,
idempotency, paging, detail references, approvals, run submission, and
counterfactual semantics.

```text
MCP server ─┐
            ├─→ ControlPlane → Constructicon domain operations
future CLI ─┘
```

`Constructicon` remains the domain and assembly root. MCP handlers contain no
reconciliation logic and no direct SQLite logic. Removing
`constructicon.api.mcp` leaves every durable control fact intact.

### 0.2 `RunId` is the only long-running identity

Do not mirror runs into MCP Tasks. Constructicon already has journaled status,
events, cancellation, resume, and reproduction. M6 returns a `RunId` from
`runs_start`, `runs_resume`, `runs_reproduce`, and `runs_counterfactual`; clients
poll ordinary run tools. A later Tasks adapter may use `task_id == run_id`, but
must project the existing journal and add no task store.

### 0.3 Use the high-level `MCPServer`

Typed tools/resources preserve Pydantic as the request, response, and structured
output contract. The low-level server would duplicate schemas and validation.

Graph proposals are the deliberate exception: MCP accepts generic canonical
JSON and delegates to M5 `admit_graph()`. Typing the argument as `Graph` would
hide repairable Graph faults behind MCP argument validation.

### 0.4 Expected conflict is data

Malformed MCP arguments are SDK tool errors. Missing authority is a protocol
refusal. Admission rejection, idempotency conflict, live ownership, moved
stable pointers, and terminal run states are structured result variants.
Unexpected exceptions are logged and sanitized. No tool returns an error string
as a successful result.

### 0.5 Resources carry detail

Tools return bounded summaries and `DetailRef`s. One `DetailResolver` backs MCP
resource templates and `details_read()` for hosts that do not expose resource
reads directly to the model. A URI is an address, not a bearer capability;
every read rechecks actor scope.

### 0.6 HTTP is authenticated or absent

Streamable HTTP is an OAuth 2.1 resource server with an injected token verifier.
Stdio receives a fixed actor from its trusted launcher. Actor identity is never a
tool argument.

### 0.7 Run hosting is not graph scheduling

A process-local `RunHost` owns asyncio tasks and a run-level semaphore. It never
inspects Graphs, orders nodes, resolves dependencies, or schedules invocations.
The walker remains the only graph scheduler.

## 1. Core control contracts

New `constructicon/core/control.py`:

```python
class AuthenticatedActor(BaseModel):
    actor_id: str
    # Canonical principal id minted by ActorSource.
    # Static: "static:local-operator".
    # OAuth: derived from issuer + subject, never subject alone.
    auth_method: Literal["static", "oauth"]
    scopes: frozenset[str]
    display_name: str | None = None
    issuer: str | None = None
    subject: str | None = None
    client_id: str | None = None

class ControlFault(BaseModel):
    code: ControlCode
    message: str
    repair: str
    details: dict[str, JsonValue] = Field(default_factory=dict)

class DetailRef(BaseModel):
    uri: str
    media_type: str = "application/json"
    digest: Digest | None = None

class PageInfo(BaseModel):
    next_cursor: str | None
    snapshot_digest: Digest
    count: NonNegativeInt

class CommandClaim(BaseModel):
    command_id: str
    actor_id: str
    operation: str
    epoch: PositiveInt
    expires_at: AwareDatetime

class CommandRecord(BaseModel):
    command_id: str
    actor: AuthenticatedActor
    operation: str
    idempotency_key: str
    request_hash: Digest
    state: Literal["prepared", "committed", "rejected"]
    plan: JsonValue | None
    response: JsonValue | None
    owner_id: str | None
    owner_epoch: NonNegativeInt
    lease_expires_at: AwareDatetime | None
    created_at: AwareDatetime
    completed_at: AwareDatetime | None

class CommandMeta(BaseModel):
    command_id: str
    replayed: bool

class RunOrigin(BaseModel):
    kind: Literal["start", "reproduce", "counterfactual"]
    actor_id: str
    command_id: str
    source_run_id: RunId | None = None
    overrides: dict[str, Digest] = Field(default_factory=dict)
    effects: Literal["live", "simulated"] = "live"
    capabilities: Literal["normal", "discard"] = "normal"
```

All public pages and results are concrete Pydantic models—`RunPage`,
`EventPage`, `VersionPage`, `RunSummary`, `RunSubmission`,
`PromotionCommandResult`, `ApprovalCommandResult`, `ComponentComparison`—not
untyped dictionaries. Every mutating result contains `CommandMeta`.

### One control-store contract

`ControlStore` lives in `core/control.py` and owns command claim/plan/terminal
state plus approval records. `SqliteJournal` implements `Journal`,
`RegistryStore`, and `ControlStore` over one WAL database. The protocols remain
separate because the concepts remain separate. An in-memory `ControlStore` is
the I6 test double.

`RunOrigin` is inserted atomically with the run through `Journal.create_run`.
Existing M1–M5 runs have no origin row and are exposed as `origin=None`; no actor
or command is invented retroactively.

### Actor scopes

```text
constructicon:read      describe, validate, status, events, results, registry reads
constructicon:operate   start, cancel, resume, reproduce, counterfactual
constructicon:approve   record a human approval or rejection
constructicon:promote   promote and roll back stable pointers
constructicon:admin     implies every scope
```

Scope checks occur in `ControlPlane` before command claim or replay. Tool
annotations remain hints only. M6 adds authorization and audit, not multi-tenant
data partitioning: actors with read scope may inspect system run/registry data;
command records remain actor-owned or admin-readable.

## 2. One durable command law

Every mutation follows one sequence:

```text
Authorize
→ Canonicalize request
→ Claim command
→ Store immutable plan
→ Apply or reconcile one domain mutation
→ Store exact terminal response
→ Return
```

The caller key is mandatory, opaque, non-empty, and length-bounded. MCP JSON-RPC
request IDs are transport identities and are never reused as idempotency keys.

```python
command_id = digest(
    "control-command",
    1,
    {
        "actor_id": actor.actor_id,
        "operation": operation,
        "idempotency_key": caller_key,
    },
)

request_hash = digest("control-request", 1, canonical_arguments)
```

### Plan before mutation

The command stores an operation-specific immutable plan before its first domain
write:

| Operation | Stored plan |
|---|---|
| start | accepted manifest, deterministic RunId, exact inputs, origin |
| reproduce | source manifest, deterministic child RunId, origin |
| counterfactual | resolution lock, overrides, child RunId, origin |
| approve | exact subject, decision, deterministic approval_id |
| promote | exact attestation, attested baseline, target version |
| rollback | expected stable and deterministic prior target |

A retry never recomputes a stored plan. Registry changes or pointer movement
therefore cannot change the meaning of an interrupted command. A deterministic
planning refusal—admission rejection, unknown exact version, stale expected
stable—is stored as a terminal rejected response and replayed exactly.

### Claim state machine

```text
no row
  → PREPARED, owner epoch 1

same actor + operation + key + request, terminal
  → exact stored response, replayed=true

same actor + operation + key, different request
  → control.idempotency.conflict; no mutation

same request, PREPARED, live owner
  → control.command.in_progress

same request, PREPARED, expired owner
  → reclaim at epoch+1; reuse plan; reconcile; finish
```

Commands are short; long work becomes a run and returns. There is no command
heartbeat. `store_plan`, `complete_command`, and `reject_command` are fenced by
owner and epoch. Contradictory plans or terminal responses at one command ID are
journal damage. Unexpected exceptions are not cached as terminal responses; the
claim expires for safe retry.

### Deterministic domain identities

```python
run_id = RunId(
    "run-" + short_digest("run-from-command", 1, {"command_id": command_id})
)

approval_id = (
    "approval-"
    + short_digest(
        "approval-from-command",
        1,
        {"command_id": command_id, "subject": subject},
    )
)
```

Recovery facts:

| Operation | Durable fact |
|---|---|
| start / reproduce / counterfactual | deterministic RunId; run + origin are write-once |
| cancel | cancel flag or terminal run state |
| resume | run state + fenced run lease |
| approve | deterministic approval_id + exact subject |
| promote | one attestation authorizes one PromotionRecord |
| rollback | exact expected stable + target from immutable history |

A crash after the domain write but before command completion reconstructs the
response from the stored plan and durable fact. Nothing is blindly repeated.

## 3. Asynchronous run submission

`Constructicon.start()` remains the local convenience that waits. M6 adds:

```python
Walker.prepare(
    manifest,
    *,
    run_id,
    inputs,
    origin: RunOrigin | None,
) -> None

Walker.run_prepared(
    run_id,
    *,
    cancellation: Literal["cancel", "abandon"],
) -> RunResult
```

`prepare()` stores manifest, inputs, PENDING run, and optional origin in one
transaction. `Walker.start()` becomes prepare + `run_prepared(..., "cancel")`.

A concrete L4 `RunHost` launches prepared runs and performs startup recovery:

```text
PENDING runs
RUNNING runs whose owner lease is lost
```

It never auto-resumes FAILED, PARKED, CANCELLED, or SUCCEEDED runs. Multiple
hosts may sweep; the fenced run lease admits one owner.

Submission sequence:

```text
claim command
→ store accepted manifest + deterministic RunId plan
→ prepare run + origin atomically
→ complete command with RunSubmission
→ request RunHost launch
→ return
```

Crash outcomes are mechanically recoverable:

- before plan: retry repeats pure planning only;
- after plan, before run: retry creates the planned run;
- after run, before command completion: retry finds the exact row;
- after command completion, before launch: run remains PENDING;
- during execution: M2 run ownership expires and reads as lost.

### Abandon is not cancel

Graceful server shutdown uses `cancellation="abandon"`:

- stop owned process trees;
- discard uncheckpointed mutable acquisitions;
- stop heartbeats and release run ownership;
- do not set the cancel flag or durable CANCELLED status.

The first uncheckpointed invocation may replay. Only `runs_cancel` records user
intent to cancel.

## 4. Counterfactual runs

### 4.1 Exact resolution lock

A counterfactual never re-resolves bare Refs against today's stable pointers.
Admission accepts an optional source-derived lock:

```python
class ResolutionPin(BaseModel):
    scope: ScopePath
    component: str
    version: Digest

class ResolutionLock(BaseModel):
    source_manifest_hash: Digest
    pins: tuple[ResolutionPin, ...]
```

Each source scope resolves to its recorded exact version. Overrides are keyed by
exact component name, apply to every occurrence, and must name retained exact
versions. Floating aliases are refused.

M6 replay is deliberately contract-compatible. The ordinary validator rechecks
ports, grants, capabilities, loops, and contracts. An override that changes
topology or invalidates source scopes returns
`control.counterfactual.lock_mismatch`. Topology-changing candidate replay waits
for M9's explicit migration contract.

### 4.2 Truthful simulated effects

`EffectReceipt.status` gains `"simulated"` and `EffectRequest` gains:

```python
mode: Literal["live", "simulated"] = "live"
```

Counterfactual requests must never collide with live receipts:

```text
live       → existing idempotency v1, byte-identical to M1–M5
simulated  → digest("idempotency-simulated", 1, {manifest, path, kind, subject})
```

`EffectAdapter` gains one honest seam:

```python
class EffectProfile(BaseModel):
    ...
    simulation: Literal["supported", "unsupported"]

async def simulate(request: EffectRequest) -> EffectReceipt: ...
```

The counterfactual boundary calls `simulate`, never `execute` or `reconcile`,
and records request + simulated receipt + `EffectSimulated` transactionally. The
kernel invents no URL, commit, or identifier. Unsupported simulation fails with
a typed counterfactual fault before external I/O.

Existing fake and Git adapters implement simulation. For `merge_verified`, the
simulated reference is the prepared exact merge commit; the protected ref is
untouched.

### 4.3 Discard-only capabilities

Every acquired leased capability closes with `discard`, including on successful
invocations. Non-leased immutable capabilities remain ordinary injected
objects. A counterfactual may execute in WRITE workspaces but retains and
installs nothing.

`RunOrigin` records parent run, overrides, simulated effect mode, and discard
mode. The counterfactual remains a normal journaled run with checkpoints,
resume, status, events, and results.

## 5. Stable pages and detail references

### Cursor law

One codec serves every page. A cursor is base64url canonical JSON containing:

```text
schema version
actor id
query kind + query hash
last key
snapshot upper bound
self-check digest
```

The self-check detects corruption; it is not authorization. Every page rechecks
scope and query ownership. Clients treat cursors as opaque and obtain them only
from the previous page.

Stable upper bounds:

| Page | Snapshot boundary |
|---|---|
| events | `through_seq` |
| runs | captured final `(created_at, run_id)` key |
| component versions | `registration_seq` |
| promotions | `promotion_seq` |
| reverse dependencies | recompute at captured `registration_seq` |

A cursor used with another actor, query, resource, or filter returns
`control.cursor.query_mismatch`. Unsupported versions return a one-move
restart-from-first-page repair. Event tailing starts a new query after the prior
snapshot is drained; tailing and snapshot paging are not mixed.

### Detail vocabulary

```text
constructicon://runs/<run_id>/manifest
constructicon://runs/<run_id>/result
constructicon://runs/<run_id>/events/<seq>
constructicon://commands/<command_id>
constructicon://approvals/<approval_id>
constructicon://attestations/<attestation_id>
constructicon://components/<percent-encoded-name>/<version>
```

Standard percent-encoding handles namespaced components; no second opaque-key
codec is introduced. One `DetailResolver` returns canonical JSON and digest.
MCP resources and `details_read()` call it. Oversized details use the same cursor
law for chunks that reconstruct the canonical bytes exactly.

## 6. Authenticated actors

`ActorSource` has two implementations:

1. `StaticActorSource` — stdio and in-memory tests. Launcher fixes actor ID and
   scopes; startup rejects empty or noncanonical identity.
2. `OAuthActorSource` — Streamable HTTP. Maps verified issuer, subject, client,
   and scopes into one canonical actor ID.

Constructicon ships no authorization server or demonstration issuer. Tests use a
fake token verifier.

Forbidden:

- caller-controlled actor fields;
- MCP client metadata as authentication;
- anonymous Streamable HTTP;
- OS username presented as verified remote identity;
- OAuth subject alone as globally unique identity.

`whoami` returns actor and scopes. Commands store full actor JSON for audit.
`PromotionRecord.actor` receives the trusted actor ID. `ApprovalRecord.actor`
becomes `AuthenticatedActor`.

## 7. Transport-neutral `ControlPlane`

New `constructicon/api/control.py`:

```python
class ControlPlane:
    system: Constructicon
    store: ControlStore
    run_host: RunHost
    cursor_codec: CursorCodec
    details: DetailResolver
```

Read methods accept actor + bounded query parameters. Mutations accept actor +
idempotency key. MCP maps one-to-one and adds no behavior.

### Read operations

| Operation | Result |
|---|---|
| `whoami` | actor and scopes |
| `system_describe` | M5 `SystemDescription` |
| `graphs_validate` | M5 admission result |
| `runs_list` | stable `RunPage` |
| `runs_status` | bounded `RunSummary` + refs |
| `runs_events` | stable `EventPage` |
| `runs_result` | terminal preview + result ref |
| `commands_status` | actor-owned/admin command view |
| `registry_versions` | paged exact versions |
| `registry_candidates` | paged unpromoted versions |
| `registry_rdeps` | paged reverse-dependency closure |
| `registry_compare` | semantic component comparison |
| `details_read` | bounded detail read |

`registry_compare` reports semantic changes—role/body kind, ports, capability
requirements, learning profile, implementation digest, stable status, and
reverse-dependency impact—not a generic JSON diff.

### Mutating operations

| Operation | Scope | Result |
|---|---|---|
| `runs_start` | operate | admission rejection or RunSubmission |
| `runs_cancel` | operate | cancellation result |
| `runs_resume` | operate | same-run submission or terminal conflict |
| `runs_reproduce` | operate | exact-world child RunSubmission |
| `runs_counterfactual` | operate | simulated/discard-only RunSubmission |
| `runs_approve` | approve | one human decision record |
| `registry_promote` | promote | PromotionRecord or baseline conflict |
| `registry_rollback` | promote | expected-baseline rollback |

`runs_approve` stores `approved | rejected` plus optional reason against an exact
`ProofSubject`. M7 adds approval-consuming nodes and unparking; M6 does not
partially invent that workflow.

## 8. MCP adapter

```toml
[project.optional-dependencies]
mcp = ["mcp>=2,<3"]

[project.scripts]
constructicon-mcp = "constructicon.api.mcp.__main__:main"
```

Only `constructicon.api.mcp` may import `mcp`.

```python
build_mcp_server(
    control: ControlPlane,
    *,
    actor_source: ActorSource,
) -> MCPServer
```

Typed tools/resources use high-level `MCPServer`. Read tools set truthful
read-only hints; mutations set idempotent hints. Hints never grant authority.

The launcher accepts a Python factory reference, not YAML:

```text
constructicon-mcp myproject.control:create_control --transport stdio \
  --actor-id static:local-agent \
  --scope constructicon:read \
  --scope constructicon:operate
```

HTTP deployment supplies OAuth verification and public auth settings. M6
supports stdio and stateless JSON-response Streamable HTTP only; SSE is not a
new surface. Durable state lives in explicit IDs and SQLite, never an MCP
session.

`graphs_validate` accepts generic JSON objects and delegates through
`ControlPlane` to M5 `admit_graph()`, preserving strict repairable faults.

## 9. Registry and approval hardening

### Baseline-bound promotion

`registry_promote` verifies action, component, version, passing checks, and:

```text
attestation.subject.baseline_version == current stable
```

`PromotionRecord.from_version` is the attested baseline; the store performs the
ordinary pointer CAS. A stale evaluation cannot promote over an intervening
stable version.

### Expected-baseline rollback

`registry_rollback` requires `expected_stable`, derives the previous target from
immutable promotion history, mints the ordinary policy attestation bound to
`(component, target, expected_stable)`, and uses the same promotion CAS. The
attestation remains transport-neutral; command identity stays in the command
ledger.

### Human decisions

`ApprovalRecord` gains:

```python
decision: Literal["approved", "rejected"]
reason: str | None
actor: AuthenticatedActor
```

It binds one exact `ProofSubject` and run and is write-once under its
deterministic approval ID.

## 10. Errors

Public control codes include:

```text
control.auth.required_scope
control.idempotency.conflict
control.command.in_progress
control.command.unknown
control.cursor.invalid
control.cursor.query_mismatch
control.detail.not_found
control.run.unknown
control.run.live_owner
control.run.terminal
control.run.not_resumable
control.counterfactual.lock_mismatch
control.counterfactual.effect_unsupported
control.registry.stable_moved
control.registry.version_unknown
control.approval.invalid_subject
```

Graph faults remain M5 `AdmissionFault`s. Expected refusals are structured
results. Missing scope is a protocol refusal. Unexpected failures are sanitized.
Current authority is checked before replaying a stored command response.

## 11. SQLite schema v5

```sql
commands(
    command_id PRIMARY KEY,
    actor_id,
    actor_json,
    operation,
    idempotency_key,
    request_hash,
    request_json,
    plan_json,
    state,
    response_json,
    owner_id,
    owner_epoch,
    lease_expires_at,
    created_at,
    updated_at,
    completed_at,
    UNIQUE(actor_id, operation, idempotency_key)
)

approvals(
    approval_id PRIMARY KEY,
    run_id,
    subject_json,
    decision,
    reason,
    actor_json,
    command_id UNIQUE,
    created_at
)

run_origins(
    run_id PRIMARY KEY,
    origin_json
)
```

`create_run(..., origin=...)` inserts the run and origin in one transaction.
Existing runs omit origin. No cursor table is needed.

Write-once law remains:

```text
absent        → insert
identical     → idempotent
contradictory → damage
```

Migration is additive and one-way; old binaries refuse schema v5.

## 12. Tests

### Protocol

- Official SDK v2 in-memory client lists tools, validates structured output, and
  calls every read tool.
- Unknown Graph fields reach M5 repair faults rather than MCP argument rejection.
- Tool/resource schemas and annotations are snapshot-tested.
- No `mcp` import exists below `constructicon.api.mcp`.

### Actor/auth

- Static identity cannot be spoofed through arguments.
- Missing/noncanonical static actor refuses construction.
- Fake HTTP verifier: no/bad token → 401; valid token maps identity and scopes;
  insufficient scope moves nothing.
- Same OAuth subject under two issuers yields two actor IDs.

### Response-loss matrix

Inject at:

```text
A. after plan commit, before domain mutation
B. after domain mutation, before command completion
C. after command completion, before response delivery
```

Restart and retry. Assert one command, one mutation, and the exact replayed
response for start, cancel, resume, reproduce, counterfactual, approve, promote,
and rollback.

Also test different-request key conflict, concurrent same-key callers, expired
claim reconciliation, completed-before-launch recovery, and abandon-not-cancel
shutdown.

### Paging/detail

- New rows inserted after page one never enter the existing snapshot.
- New tail query sees later events.
- Actor/query/filter/resource cursor mismatch is refused.
- Corrupt/unsupported cursor returns one repair.
- Pages obey item and byte limits.
- Detail refs recheck scope and chunked reads reproduce canonical bytes exactly.

### Counterfactual

- Non-overridden resolutions equal the parent.
- Exact override applies to every occurrence.
- Unknown, drifted, contract-breaking, or topology-changing override refuses.
- Origin records parent, overrides, actor, command, and modes.
- Live adapter `execute`/`reconcile` counts remain zero.
- Live and simulated requests for the same logical effect never share a key.
- Receipts say `simulated`; unsupported simulation fails before I/O.
- Every leased workspace is discarded; resume preserves simulation idempotency.

### Registry/approvals

- Stale promotion baseline and stale rollback expectation refuse.
- Retried approval writes one actor and decision.
- Actor spoofing is impossible.

### Compatibility

- SQLite v4→v5 migration with M1–M5 fixtures.
- All 180 M5 tests remain green.
- M5 describe/admission JSON contracts remain unchanged.
- Live effect idempotency keys remain byte-identical.

## 13. Implementation order

1. Core control contracts and `ControlStore`.
2. SQLite v5 command claim/plan/replay law.
3. Atomic run preparation, `run_prepared`, and `RunHost`.
4. Resolution lock, simulated effect identity, adapter simulation, discard mode.
5. Stable pages, cursor codec, semantic compare, and details.
6. Approval persistence and registry baseline hardening.
7. Transport-neutral `ControlPlane`.
8. MCP tools/resources, stdio actor, authenticated HTTP.
9. Response-loss acceptance, ADR 0012, architecture and contributor docs.

## 14. Files

```text
src/constructicon/core/control.py                   control contracts + ControlStore
src/constructicon/core/effect.py                    approval decision + simulated effects
src/constructicon/core/journal.py                   atomic run/origin + simulated receipt op
src/constructicon/runtime/validator.py              optional ResolutionLock
src/constructicon/runtime/walker.py                 prepare/run_prepared + abandon/simulation
src/constructicon/runtime/registry.py               baseline-bound promote/rollback
src/constructicon/substrate/journal/sqlite.py       schema v5 + ControlStore
src/constructicon/api/control.py                    ControlPlane + RunHost + paging
src/constructicon/api/detail.py                     DetailResolver
src/constructicon/api/mcp/{__init__,server,auth,__main__}.py
pyproject.toml                                      [mcp] extra + import contract

tests/api/test_control_commands.py
tests/api/test_cursors.py
tests/api/test_counterfactual.py
tests/api/test_run_host.py
tests/mcp/test_{tools,response_loss,auth_http,resources}.py
tests/migrations/test_v4_to_v5.py

docs/adr/0012-mcp-control-plane.md
docs/ARCHITECTURE.md
README.md
AGENTS.md
docs/CONTRIBUTING.md
```

## Out of scope

MCP Tasks or a second task store · subscriptions/event push · MCP Apps, prompts,
sampling, elicitation, or server logging · SSE · embedded authorization server ·
approval consumption/unparking (M7) · channels/mailbox/panel (M7) · distributed
workers · live CLI executors (M8) · topology-changing counterfactuals and learning
workflows (M9) · REST beside MCP · YAML configuration.

## Verification

`uv run verify` remains the single credential-free gate.

```text
Authenticate
→ Describe
→ Claim
→ Plan
→ Prepare one run
→ return RunId
→ lose response
→ retry
→ replay exact result
→ page status/events
→ read immutable detail
→ cancel/resume/reproduce/counterfactual
→ approve/promote/rollback once
```

The final elegance test:

> A mutating MCP handler derives an actor, delegates once to `ControlPlane`, and
> returns the typed result. It never opens SQLite, interprets a cursor, computes a
> RunId, reconciles a command, or decides authority. Removing the MCP package
> changes transport and nothing else.
