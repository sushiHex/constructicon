# M6 — durable MCP control plane (draft rev 1)

## Context

M1–M5 are merged and green. M5 established the complete authoring contract:
strict Graph JSON, one validator, `system.describe()`, typed repair faults,
restart-safe SDK tasks, and identical manifest identity across SDK, direct, and
architect-authored Graphs.

M6 adds the v1 operational front door without adding a second control model.
The frozen milestone requires authenticated actors, caller idempotency keys on
every mutation, bounded pagination, stable opaque cursors, detail by reference,
conflict results, registry promotion/rollback, counterfactual runs, and a
response-loss acceptance test proving that retries create no duplicate runs,
approvals, or promotions.

The implementation targets the official MCP Python SDK v2 stable line and the
2026-07-28 protocol revision. MCP remains an optional L4 dependency; no `mcp`
import may appear in core, substrate, runtime, or SDK.

> **MCP is a skin. The durable control plane remains Constructicon.**

## Acceptance criterion

An authenticated actor can connect over stdio or Streamable HTTP, discover the
same authoring contract M5 exposes, submit a Graph, receive a durable RunId
without holding the tool call open, inspect status and event pages through
stable cursors, cancel/resume/reproduce/counterfactually replay it, record a
human approval, and promote or roll back a component. Every mutation requires a
caller idempotency key. The server durably claims the command before mutating,
reconciles an interrupted command from domain facts, and stores the exact
terminal response. Repeating the same actor + operation + key + request returns
that response; using the same key with different input returns a typed conflict.
A simulated response loss after any committed mutation creates exactly one run,
one approval, and one promotion. Counterfactual runs pin the source world except
for explicit exact-version overrides, record their parent and overrides, call no
external effect adapter, emit truthful simulated receipts, and discard every
leased mutable resource. All list/read responses are bounded; full immutable
detail remains retrievable by reference.

Pinned assertions:

```text
one RunId for long-running work
one command ledger for every mutation
one actor contract, never an actor tool argument
one cursor codec
one detail-reference vocabulary
one MCP adapter over the system object
zero MCP imports below L4
zero duplicate mutation after response loss
zero external effect in a counterfactual run
```

## 0. Decisive rulings

### 0.1 Do not mirror Constructicon runs into MCP Tasks

MCP Tasks is an extension and client support is not universal. Constructicon
already has the stronger durable object: `RunId` plus journaled status, events,
cancellation, resume, and reproduction. Creating an MCP task row beside every
run would give one operation two identities and two state machines.

M6 therefore returns a RunId immediately from `runs_start`, `runs_resume`,
`runs_reproduce`, and `runs_counterfactual`. Clients poll ordinary Constructicon
tools. If a later client genuinely requires the Tasks extension, an adapter may
map `task_id == run_id` over the same journal; it must not create another task
store.

### 0.2 Use the high-level MCPServer

The server uses the official v2 `MCPServer` and typed tool/resource functions.
Pydantic request and response models remain the schema source, and the SDK
validates structured output. Dropping to the low-level Server would require
Constructicon to hand-author and re-validate schemas that already exist.

Graph proposals are the deliberate exception: MCP accepts them as a generic
JSON object, then calls M5's `admit_graph()`. Typing the parameter as `Graph`
would cause the MCP SDK to reject malformed proposals before Constructicon can
return its versioned `AdmissionFault` repair model.

### 0.3 Expected conflict is data

Malformed MCP arguments are SDK tool errors. Missing authorization is a protocol
refusal. Expected Constructicon outcomes—admission rejection, idempotency
conflict, live command ownership, moved stable pointer, terminal run state—are
structured discriminated results, not thrown strings. Unexpected exceptions are
allowed to become sanitized tool failures and full server logs.

### 0.4 Resources carry full detail

Tools return bounded summaries and `DetailRef`s. One `DetailResolver`
implementation backs both MCP resource templates and a `details_read` tool for
hosts that do not make resource reads directly available to the model. Source
records are never silently truncated or mutated for display.

### 0.5 HTTP is authenticated or absent

Streamable HTTP is never served anonymously. It is configured as an OAuth 2.1
resource server with an injected token verifier. Stdio has no HTTP auth channel,
so its actor identity and scopes are fixed by the trusted process launcher.
Actor identity never appears as a caller-controlled tool argument.

## 1. Core control contracts

New `constructicon/core/control.py`:

```python
class AuthenticatedActor(BaseModel):
    actor_id: str
    auth_method: Literal["static", "oauth"]
    scopes: frozenset[str]
    client_id: str | None = None

class ControlFault(BaseModel):
    code: ControlCode
    message: str
    repair: str
    details: dict[str, JsonValue] = {}

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
    created_at: AwareDatetime
    completed_at: AwareDatetime | None

class CommandReceipt(BaseModel):
    command_id: str
    replayed: bool

class RunOrigin(BaseModel):
    kind: Literal["start", "reproduce", "counterfactual"]
    actor_id: str
    command_id: str
    source_run_id: RunId | None = None
    overrides: dict[str, Digest] = {}
    effects: Literal["enabled", "simulated"] = "enabled"
    capabilities: Literal["normal", "discard"] = "normal"
```

Public page/result contracts are concrete Pydantic models—`RunPage`,
`EventPage`, `VersionPage`, `RunSummary`, `RunSubmission`,
`PromotionCommandResult`, `ApprovalCommandResult`, `ComponentComparison`—rather
than untyped dictionaries.

### Actor scopes

```text
constructicon:read      describe, validate, status, events, result, registry reads
constructicon:operate   start, cancel, resume, reproduce, counterfactual
constructicon:approve   record a human approval/rejection
constructicon:promote   promote and rollback stable pointers
constructicon:admin     implies every scope
```

The scope check is server-side and occurs before the control operation. Tool
annotations remain hints only.

## 2. One durable command ledger

A caller idempotency key is required for every mutating MCP tool. It is an
opaque non-empty string with a bounded length; Constructicon never treats the
MCP request ID as an idempotency key because transport request IDs change on
retry.

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

`CommandStore` is an L0 protocol. `SqliteJournal` implements it over the same
WAL database; an in-memory test double exercises the same claim/replay contract.
This is one transactional store, not a control-plane database beside the
journal.

### Claim state machine

```text
no row
  → insert PREPARED with owner + epoch 1; caller executes

same key + same request, COMMITTED/REJECTED
  → return exact stored response with replayed=true

same key + different request hash
  → control.idempotency.conflict; execute nothing

same request, PREPARED, live command lease
  → control.command.in_progress with command_id + retry_after

same request, PREPARED, expired lease
  → reclaim at epoch+1, reconcile, then finish
```

Commands are deliberately short. Long work is submitted as a run and returns;
there is no command heartbeat. A claim TTL protects a process that dies in the
small submission window.

`complete_command()` and `reject_command()` are fenced by command owner + epoch.
A deterministic domain refusal is stored and replayed. An unexpected exception
is not cached as a terminal result; the claim expires so a retry can reconcile
or try again.

### Operation-specific reconciliation

The generic ledger owns identity and replay; each command owns its recovery
proof:

| Operation | Durable recovery fact |
|---|---|
| start / reproduce / counterfactual | deterministic RunId derived from command_id; exact run row is write-once |
| cancel | run cancel flag or terminal state |
| resume | run state + run lease |
| approve | deterministic approval_id derived from command_id and subject |
| promote | attestation_id uniquely authorizes one PromotionRecord |
| rollback | request includes `expected_stable`; target and policy-attestation are deterministic from immutable promotion history |

A retry after a domain write but before command completion observes that fact,
reconstructs the exact response, and completes the command. No mutation is
blindly repeated.

## 3. Asynchronous run submission without a second scheduler

Current `Constructicon.start()` waits for the walker. M6 separates durable
submission from execution while preserving the existing convenience method.

```python
Walker.prepare(manifest, run_id, inputs, origin) -> None
Walker.run_prepared(run_id, *, cancellation="cancel" | "abandon") -> RunResult

Walker.start(...):
    prepare(...)
    return await run_prepared(..., cancellation="cancel")
```

A concrete L4 `RunDispatcher` owns only process-local asyncio tasks and a bounded
semaphore. It does not inspect Graphs, order nodes, resolve dependencies, or
schedule invocations; the walker remains the only graph scheduler.

Submission order:

```text
admit Graph
→ claim command
→ derive RunId from command_id
→ durably prepare run + RunOrigin
→ complete command with RunSubmission
→ schedule run_prepared(run_id)
→ return
```

If the process dies:

- before run creation: command reconciliation creates it;
- after run creation but before command completion: retry finds the exact row;
- after command completion but before scheduling: the run remains PENDING;
- during execution: M2's run lease expires and the run reads as lost.

At MCP server lifespan start, `RunDispatcher.recover()` schedules PENDING runs
and RUNNING/lost runs. It never auto-resumes FAILED, PARKED, or CANCELLED runs.
Multiple server processes may perform the sweep; the fenced run lease permits
one owner.

Graceful MCP shutdown uses `cancellation="abandon"`: it stops the heartbeat,
releases process ownership, and leaves the durable run resumable. It must not
misreport server shutdown as a user-requested CANCELLED run. `runs_cancel` uses
the existing cooperative cancel flag and remains the only ordinary cancellation
path.

## 4. Counterfactual runs

M6 lands the frozen counterfactual kernel enabler and exposes it through MCP.

### Resolution lock

A counterfactual may not re-resolve every bare Ref against today's stable
pointers. Admission gains an optional `ResolutionLock` derived from the source
manifest:

```python
class ResolutionPin(BaseModel):
    scope: ScopePath
    component: str
    version: Digest

class ResolutionLock(BaseModel):
    source_manifest_hash: Digest
    pins: tuple[ResolutionPin, ...]
```

Normal admission remains unchanged. Locked admission resolves every Ref by
static scope against its recorded exact version. Explicit overrides replace all
pins for the named component with one exact retained candidate version. Every
other component stays pinned. The ordinary validator then re-checks contracts,
ports, grants, capabilities, and loops and emits a new sealed manifest.

An absent version, scope mismatch, contract break, or widened grant is a typed
counterfactual admission refusal—not a fallback to current stable.

### Truthful simulation

`EffectReceipt.status` gains `"simulated"`. A counterfactual effect boundary:

- computes the ordinary request and idempotency identities;
- calls **no** external effect adapter;
- records request + simulated receipt + `EffectSimulated` in one journal
  transaction;
- returns a deterministic synthetic reference only when the component contract
  needs one.

Every leased capability closes with disposition `discard`, including on success.
WRITE workspaces may execute when the source workflow requires them, but no
candidate is installed and no mutable acquisition is retained. This is the
honest realization of “effects disabled” for code workflows.

`RunOrigin` records the parent run, exact overrides, simulated-effect mode, and
discard-only capability mode. The counterfactual itself is a normal run with
normal events, checkpoints, resume, status, and result retrieval.

## 5. Stable pages, opaque cursors, and detail references

### Cursor law

One codec serves every domain page. A cursor is base64url canonical JSON
containing:

```text
schema version
actor id
query kind
query hash
last key
snapshot upper bound
checksum = digest("cursor", 1, payload)
```

The checksum detects corruption and accidental construction; authorization
remains the security boundary. Clients must treat the token as opaque.

The first page captures an upper bound. Later inserts never appear midway
through that page sequence:

- events: `(run_id, seq)` and `through_seq`;
- runs: keyset `(created_at, run_id)` and a captured final key;
- component versions/promotions: existing registration/promotion sequence;
- reverse dependencies: sorted immutable snapshot plus snapshot digest.

A cursor presented to another actor, query, filter set, or resource returns
`control.cursor.query_mismatch`. An unsupported cursor version returns a typed
restart-from-first-page repair.

For live event tailing, a caller drains one stable page sequence, then starts a
new query with `after_seq=last_seq`. Snapshot paging and tailing are not mixed.

### Detail vocabulary

Tools return small previews and stable refs such as:

```text
constructicon://runs/<run_id>/manifest
constructicon://runs/<run_id>/result
constructicon://runs/<run_id>/events/<seq>
constructicon://commands/<command_id>
constructicon://approvals/<approval_id>
constructicon://attestations/<attestation_id>
constructicon://components/<opaque-component-key>
```

Component names contain `/`, so the component URI uses a base64url opaque key
minted by the server. Callers receive it; they never construct it.

One `DetailResolver` returns immutable canonical JSON with its digest. MCP
resource templates and `details_read()` call the same resolver. `details_read`
uses a cursor for bounded text chunks when one immutable object exceeds the
inline response limit. Source rows are never shortened in place.

## 6. Authenticated actors

`ActorSource` has two real implementations:

1. `StaticActorSource` — stdio and in-memory tests. The trusted launcher fixes
   actor ID and scopes. Startup refuses an empty actor.
2. `OAuthActorSource` — Streamable HTTP. It maps the SDK-verified access token's
   subject, client ID, and scopes into `AuthenticatedActor`.

The HTTP server is configured as an OAuth 2.1 resource server with an injected
`TokenVerifier` and `AuthSettings`. Constructicon does not ship an authorization
server or an insecure demonstration token issuer. Tests use a fake verifier.

The following are forbidden:

- `actor`, `from_actor`, or `approved_by` tool arguments;
- trusting MCP client-info metadata as authentication;
- unauthenticated Streamable HTTP;
- inferring a user from the OS and claiming that is verified identity.

`whoami` returns the resolved actor and scopes. The command ledger stores the
full actor JSON; existing `PromotionRecord.actor` receives the trusted actor ID.
`ApprovalRecord.actor` becomes `AuthenticatedActor` because M6 is its first
persistent producer.

## 7. MCP server shape

Optional package dependency:

```toml
[project.optional-dependencies]
mcp = ["mcp>=2,<3"]

[project.scripts]
constructicon-mcp = "constructicon.api.mcp.__main__:main"
```

The development group includes the same bounded MCP dependency for the
credential-free protocol tests. Import-linter adds:

```text
core, substrate, runtime, sdk may not import mcp
```

Only `constructicon.api.mcp` imports the SDK.

```python
build_mcp_server(
    system: Constructicon,
    *,
    command_store: CommandStore,
    actor_source: ActorSource,
    dispatcher: RunDispatcher | None = None,
) -> MCPServer
```

The server uses high-level typed tools and resources. Mutating tool annotations
set `idempotent_hint=True`; read tools set `read_only_hint=True` and
`open_world_hint=False`. These remain client hints, never authority.

A launcher takes a Python factory reference rather than inventing a YAML/config
DSL:

```text
constructicon-mcp myproject.control:create_system --transport stdio \
  --actor-id local-agent --scope constructicon:read --scope constructicon:operate
```

For Streamable HTTP, deployment code supplies an OAuth token verifier and public
auth settings. New work supports stdio and Streamable HTTP only; SSE is not a
new M6 surface.

The HTTP path is stateless and JSON-response mode. All durable state is explicit
in RunId, command_id, cursors, and the SQLite journal—never hidden in an MCP
session.

## 8. Tool inventory

### Read-only

| Tool | Result |
|---|---|
| `whoami` | authenticated actor and scopes |
| `system_describe` | M5 `SystemDescription` |
| `graphs_validate` | M5 `AdmissionAccepted | AdmissionRejected` |
| `runs_list` | stable `RunPage` |
| `runs_status` | bounded `RunSummary` + detail refs |
| `runs_events` | stable `EventPage` |
| `runs_result` | terminal result preview + immutable result ref |
| `commands_status` | command state/result for the owning actor or admin |
| `registry_versions` | paged exact versions |
| `registry_candidates` | paged unpromoted versions |
| `registry_rdeps` | paged reverse-dependency closure |
| `registry_compare` | typed contract/implementation difference summary |
| `details_read` | bounded read of one `DetailRef` |

`registry_compare` is deliberately semantic, not a generic JSON diff: role/body
kind, ports added/removed/changed, capability requirements, learning profile,
implementation digest, stable status, and reverse dependents, with exact
component-definition refs for full detail.

### Mutating — every request requires `idempotency_key`

| Tool | Required scope | Result |
|---|---|---|
| `runs_start` | operate | admission rejection or durable RunSubmission |
| `runs_cancel` | operate | idempotent cancellation result |
| `runs_resume` | operate | durable RunSubmission or terminal/conflict result |
| `runs_reproduce` | operate | new exact-world RunSubmission |
| `runs_counterfactual` | operate | simulated/discard-only RunSubmission |
| `runs_approve` | approve | one durable ApprovalRecord; M7 consumes/unparks it |
| `registry_promote` | promote | one PromotionRecord or baseline conflict |
| `registry_rollback` | promote | one explicit expected-baseline rollback |

`runs_approve` records approval or rejection but does not yet unpark an approval
node; that round trip is M7. It requires an existing run and exact ProofSubject.

## 9. Registry mutation hardening

MCP makes races public, so M6 closes two latent seams before exposing registry
writes:

- `registry_promote` verifies that the attestation's
  `baseline_version` exactly equals the current stable pointer. The resulting
  `PromotionRecord.from_version` comes from the attested baseline, not a fresh
  unverified snapshot value.
- `registry_rollback` requires `expected_stable`. It finds the previous version
  from immutable promotion history, mints a deterministic policy attestation
  bound to `(component, target, expected_stable, command_id)`, and performs the
  ordinary promotion CAS. A stale expected value is a typed conflict.

This makes component pointer movement symmetrical with Git's expected-base CAS.

## 10. Errors and result semantics

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
control.registry.stable_moved
control.registry.version_unknown
control.approval.invalid_subject
```

Rules:

- Graph/schema faults remain M5 `AdmissionFault`s.
- Expected domain refusals return structured result variants.
- Missing scope is an MCP protocol refusal; a better model cannot grant itself
  authority.
- Unexpected exceptions are logged and sanitized by the SDK.
- No tool returns `{"ok": false, "error": "..."}` as an apparent success.

## 11. Journal schema v5

Additive tables:

```sql
commands(
    command_id PRIMARY KEY,
    actor_id,
    actor_json,
    operation,
    idempotency_key,
    request_hash,
    state,
    plan_json,
    response_json,
    owner_id,
    owner_epoch,
    lease_expires_at,
    created_at,
    updated_at,
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
    kind,
    actor_id,
    command_id,
    source_run_id,
    overrides_json,
    effects_mode,
    capability_mode,
    created_at
)
```

Existing M1–M5 runs have no origin row and read as legacy `start` origins. The
migration is additive and one-way; old binaries refuse schema v5.

Journal/query additions:

```text
claim/complete/reject/load command
record/load approval
run origin read/write
runs page
latest event sequence
terminal run result materialization
record simulated effect
```

Write-once law remains: absent inserts; identical repetition is idempotent;
contradictory repetition is damage.

## 12. Tests

### Protocol contract

- Official SDK v2 in-memory `Client(server, raise_exceptions=True)` lists tools,
  validates structured outputs, and calls every read tool.
- Graph JSON malformed at the MCP boundary still reaches M5 and returns typed
  `AdmissionFault`, rather than being swallowed by MCP argument validation.
- Tool annotations truthfully mark read-only/idempotent/destructive hints.
- Tool/resource schemas are snapshot-tested.
- No `mcp` import appears below L4.

### Actor and auth

- Stdio/static actor cannot be spoofed through arguments.
- Missing static actor refuses server construction.
- Fake HTTP token verifier: no token → 401; bad token → 401; valid token maps
  subject/client/scopes; insufficient per-tool scope moves nothing.
- In-memory tests use the explicit static actor because in-memory transport
  bypasses HTTP authorization.

### Idempotency / response loss — non-negotiable

For each mutation, arm `mcp.before_response` after the durable command result is
stored, discard the first response, then retry with the same key:

```text
runs_start          → one run row, one RunId, at most one live owner
runs_approve        → one approval row
registry_promote    → one PromotionRecord
registry_rollback   → one pointer move
runs_reproduce      → one child run
runs_counterfactual → one child run
runs_cancel/resume  → one durable outcome
```

Also test:

- same key + different request → typed conflict, no mutation;
- two concurrent callers with one key → one command owner, other gets
  in-progress or replay;
- owner dies after domain mutation but before command completion → expired
  command claim reconciles from the domain fact;
- owner dies after command completion but before run scheduling → restart sweep
  executes the one PENDING run;
- graceful server shutdown abandons rather than cancels active runs.

### Stable paging and detail

- insert new runs/events/versions between page 1 and page 2; old cursor excludes
  them and preserves order;
- a new event-tail query sees later events;
- cursor used with another query, actor, or filter is refused;
- corrupted/unsupported cursor returns a one-move repair;
- pages remain below configured item/byte limits;
- detail ref resolves to the exact immutable object and digest;
- chunked `details_read` reconstructs an oversized canonical object byte-for-byte.

### Counterfactual

- non-overridden component resolutions equal the parent manifest exactly;
- an exact candidate override is applied everywhere named and revalidated;
- unknown/drifted/contract-breaking override refuses;
- parent + override set + command actor persist in RunOrigin;
- external effect adapter execution count remains zero;
- receipts are `simulated`, not falsely `committed`;
- every leased workspace is discarded even on success;
- crash/resume preserves simulated-effect idempotency.

### Compatibility

- v4→v5 migration with M1–M5 run, manifest, lease, component, promotion, and
  event fixtures;
- all 180 M5 tests remain green;
- M5 `system.describe()` and `admit_graph()` JSON contracts remain unchanged.

## 13. Files

```text
src/constructicon/core/control.py                  new public control contracts
src/constructicon/core/run.py                      RunOrigin/public run summaries
src/constructicon/core/effect.py                   Approval decision + simulated receipt
src/constructicon/core/journal.py                  command/approval/origin/read protocols
src/constructicon/runtime/validator.py             optional ResolutionLock
src/constructicon/runtime/walker.py                prepare/run_prepared, simulation/discard mode
src/constructicon/runtime/registry.py              baseline-bound promote/rollback
src/constructicon/substrate/journal/sqlite.py       schema v5 + CommandStore
src/constructicon/api/control.py                    command execution, paging, dispatcher
src/constructicon/api/detail.py                     one DetailResolver
src/constructicon/api/mcp/__init__.py               optional L4 package
src/constructicon/api/mcp/server.py                 MCPServer tools/resources only
src/constructicon/api/mcp/auth.py                   static + OAuth ActorSource
src/constructicon/api/mcp/__main__.py               factory-based launcher
pyproject.toml                                      [mcp] extra + import contract

tests/api/test_control_commands.py
tests/api/test_cursors.py
tests/api/test_counterfactual.py
tests/mcp/test_tools.py
tests/mcp/test_response_loss.py
tests/mcp/test_auth_http.py
tests/mcp/test_resources.py
tests/migrations/test_m4_to_m5_control.py            database v4→v5

docs/adr/0012-mcp-control-plane.md
docs/ARCHITECTURE.md
README.md
AGENTS.md
docs/CONTRIBUTING.md
```

The migration test file should be named for database versions rather than
milestone numbers if the repository standard is changed during implementation;
the semantic requirement is v4→v5.

## Out of scope

- MCP Tasks extension or a second task store;
- subscriptions/event push—M6 polls stable event pages;
- MCP Apps, prompts, sampling, elicitation, or server-initiated logging;
- SSE transport;
- an embedded authorization server or login UI;
- approval-node consumption and automatic unpark (M7);
- channels/mailbox/panel (M7);
- distributed worker fleet or remote queue;
- live CLI executors (M8);
- counterfactual evaluator/learning workflows (M9);
- HTTP/REST skin beside MCP;
- YAML configuration.

## Verification

`uv run verify` remains the single credential-free gate.

M6 is complete when this sequence is true under an official in-memory MCP
client and under a fake-auth Streamable HTTP client:

```text
Authenticate
→ Describe
→ Validate
→ Claim command
→ Prepare one run
→ return RunId
→ lose response
→ retry
→ replay exact result
→ page status/events through stable cursors
→ read detail by reference
→ cancel/resume/reproduce/counterfactual
→ approve/promote/rollback once
```

The elegance test:

> Removing `constructicon.api.mcp` leaves the durable control plane, command
> identities, RunIds, cursors, approvals, counterfactual semantics, and every
> journal fact intact. MCP changes transport, never meaning.
